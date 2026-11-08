#!/usr/bin/env python3
"""Scaffold a new native static recompilation port from an original Xbox executable (default.xbe).

Usage:
    python scaffold-new-port.py path/to/default.xbe --out-dir /path/to/NewGame-recomp

Features:
    - Pure Python XBE parser (no external binary dependencies required).
    - Extracts Title ID, Title Name, Base Address, Entry Point, and Sections.
    - Identifies statically-linked XDK libraries (D3D, DSOUND, XPP, XGRPH, DOLBY).
    - Generates complete ready-to-build project scaffold:
        * CMakeLists.txt & CMakePresets.json
        * src/main.c (pre-configured with Entry Point, Base VA, VEH handlers)
        * src/recomp_manual.c (stubs and entry hooks)
        * scripts/ pipeline automation (analyze, recomp, build, run)
        * config/seed_functions.json
"""
import argparse
import os
import struct
import sys
from pathlib import Path

XBE_MAGIC = b"XBEH"
ENTRY_POINT_RETAIL_XOR = 0xA8FC57AB
ENTRY_POINT_DEBUG_XOR  = 0x5B6D40B6
THUNK_RETAIL_XOR       = 0x5B6D40B6
THUNK_DEBUG_XOR        = 0xEFF83F0F

KNOWN_XDK_SECTIONS = {"D3D", "D3DX", "DSOUND", "XPP", "XGRPH", "DOLBY", "XON", "XMV", "XACT", "XAUDIO"}


class XbeParser:
    def __init__(self, data: bytes):
        self.data = data
        if len(data) < 0x200 or data[:4] != XBE_MAGIC:
            raise ValueError("Not a valid Xbox XBE file (magic XBEH missing)")

        self.base_addr = struct.unpack_from("<I", data, 0x104)[0]
        self.header_size = struct.unpack_from("<I", data, 0x108)[0]
        self.image_size = struct.unpack_from("<I", data, 0x10C)[0]
        self.cert_va = struct.unpack_from("<I", data, 0x118)[0]
        self.num_sections = struct.unpack_from("<I", data, 0x11C)[0]
        self.section_headers_va = struct.unpack_from("<I", data, 0x120)[0]
        self.raw_entry_point = struct.unpack_from("<I", data, 0x128)[0]

        # Decode Entry Point
        ep_retail = self.raw_entry_point ^ ENTRY_POINT_RETAIL_XOR
        ep_debug = self.raw_entry_point ^ ENTRY_POINT_DEBUG_XOR
        if self.base_addr <= ep_retail < (self.base_addr + self.image_size):
            self.entry_point = ep_retail
            self.is_debug_build = False
        elif self.base_addr <= ep_debug < (self.base_addr + self.image_size):
            self.entry_point = ep_debug
            self.is_debug_build = True
        else:
            self.entry_point = ep_retail
            self.is_debug_build = False

        # Parse Certificate
        self.title_id = 0
        self.title_name = "XboxGame"
        if self.cert_va >= self.base_addr:
            cert_offset = self.va_to_offset(self.cert_va)
            if cert_offset + 0x60 <= len(data):
                self.title_id = struct.unpack_from("<I", data, cert_offset + 0x8)[0]
                raw_name = data[cert_offset + 0xC : cert_offset + 0x5C]
                try:
                    self.title_name = raw_name.decode("utf-16le").split("\x00")[0].strip()
                except UnicodeDecodeError:
                    self.title_name = f"Title_{self.title_id:08X}"

        # Parse Sections
        self.sections = []
        if self.section_headers_va >= self.base_addr:
            sh_offset = self.va_to_offset(self.section_headers_va)
            for i in range(self.num_sections):
                entry_off = sh_offset + (i * 0x38)
                if entry_off + 0x38 > len(data):
                    break
                flags, va, vsize, raw_off, raw_size, name_va = struct.unpack_from("<IIIIII", data, entry_off)
                sec_name = f"sec_{i}"
                if name_va >= self.base_addr:
                    name_off = self.va_to_offset(name_va)
                    end_off = data.find(b"\x00", name_off)
                    if end_off != -1 and (end_off - name_off) < 64:
                        sec_name = data[name_off:end_off].decode("ascii", errors="replace")

                self.sections.append({
                    "name": sec_name,
                    "va": va,
                    "vsize": vsize,
                    "raw_offset": raw_off,
                    "raw_size": raw_size,
                    "flags": flags,
                })

    def va_to_offset(self, va: int) -> int:
        offset = va - self.base_addr
        if 0 <= offset < len(self.data):
            return offset
        for sec in self.sections:
            if sec["va"] <= va < (sec["va"] + sec["vsize"]):
                return sec["raw_offset"] + (va - sec["va"])
        return offset


def sanitize_identifier(s: str) -> str:
    cleaned = "".join(c if (c.isalnum() or c == "_") else "_" for c in s)
    return cleaned.strip("_") or "XboxGame"


def generate_scaffold(xbe_path: Path, out_dir: Path):
    with open(xbe_path, "rb") as f:
        data = f.read()

    parser = XbeParser(data)
    title_slug = sanitize_identifier(parser.title_name).lower()
    project_name = f"{title_slug}_recomp"

    print(f"[*] Parsed XBE: {xbe_path.name}")
    print(f"    Title Name  : {parser.title_name}")
    print(f"    Title ID    : 0x{parser.title_id:08X}")
    print(f"    Base Address: 0x{parser.base_addr:08X}")
    print(f"    Entry Point : 0x{parser.entry_point:08X}")
    print(f"    Sections    : {len(parser.sections)} found")

    xdk_sections = [s["name"] for s in parser.sections if s["name"].upper() in KNOWN_XDK_SECTIONS]
    print(f"    XDK Sections: {', '.join(xdk_sections) if xdk_sections else 'Standard only'}")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "src" / "recomp" / "gen").mkdir(parents=True, exist_ok=True)
    (out_dir / "src" / "hooks").mkdir(parents=True, exist_ok=True)
    (out_dir / "src" / "patches").mkdir(parents=True, exist_ok=True)
    (out_dir / "tools").mkdir(parents=True, exist_ok=True)
    (out_dir / "config").mkdir(parents=True, exist_ok=True)
    (out_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (out_dir / "game").mkdir(parents=True, exist_ok=True)

    # 1. CMakeLists.txt
    cmakelists_content = f"""cmake_minimum_required(VERSION 3.20)
project({project_name} VERSION 1.0.0 LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(WIN32)
    add_compile_definitions(WIN32_LEAN_AND_MEAN NOMINMAX)
endif()

set(XBOXRECOMP_DIR "${{CMAKE_CURRENT_SOURCE_DIR}}/tools/xboxrecomp" CACHE PATH
    "Path to xboxrecomp toolkit directory")

if(NOT EXISTS "${{XBOXRECOMP_DIR}}/CMakeLists.txt")
    message(FATAL_ERROR "xboxrecomp submodule missing. Run: git submodule update --init --recursive")
endif()

add_subdirectory(${{XBOXRECOMP_DIR}} ${{CMAKE_BINARY_DIR}}/xboxrecomp)

file(GLOB RECOMP_GEN_SOURCES CONFIGURE_DEPENDS "src/recomp/gen/*.c")
file(GLOB HOOK_SOURCES       CONFIGURE_DEPENDS "src/hooks/*.c" "src/hooks/*.cpp")
file(GLOB PATCH_SOURCES      CONFIGURE_DEPENDS "src/patches/*.c")

add_executable(${{PROJECT_NAME}}
    src/main.c
    src/recomp_manual.c
    ${{HOOK_SOURCES}}
    ${{PATCH_SOURCES}}
    ${{RECOMP_GEN_SOURCES}}
)

target_include_directories(${{PROJECT_NAME}} PRIVATE
    src
    src/recomp
    ${{XBOXRECOMP_DIR}}/include
)

if(WIN32)
    target_link_libraries(${{PROJECT_NAME}} PRIVATE xboxrecomp d3d11 dxgi dbghelp shell32)
    target_compile_options(${{PROJECT_NAME}} PRIVATE /bigobj /Zi)
else()
    target_link_libraries(${{PROJECT_NAME}} PRIVATE xboxrecomp ${{CMAKE_DL_LIBS}} m)
    target_compile_options(${{PROJECT_NAME}} PRIVATE -fno-strict-aliasing -fwrapv -ffp-contract=off)
endif()
"""
    (out_dir / "CMakeLists.txt").write_text(cmakelists_content, encoding="utf-8")

    # 2. CMakePresets.json
    presets_content = """{
  "version": 3,
  "configurePresets": [
    {
      "name": "win-x64-debug",
      "displayName": "Windows x64 Debug",
      "generator": "Ninja",
      "binaryDir": "${sourceDir}/build/win-x64-debug",
      "cacheVariables": {
        "CMAKE_BUILD_TYPE": "Debug"
      },
      "condition": {
        "type": "equals",
        "lhs": "${hostSystemName}",
        "rhs": "Windows"
      }
    },
    {
      "name": "win-x64-release",
      "displayName": "Windows x64 Release",
      "generator": "Ninja",
      "binaryDir": "${sourceDir}/build/win-x64-release",
      "cacheVariables": {
        "CMAKE_BUILD_TYPE": "Release"
      },
      "condition": {
        "type": "equals",
        "lhs": "${hostSystemName}",
        "rhs": "Windows"
      }
    }
  ]
}
"""
    (out_dir / "CMakePresets.json").write_text(presets_content, encoding="utf-8")

    # 3. src/main.c
    main_c_content = f"""/**
 * {parser.title_name} (Xbox) - Static Recompilation Host Entry Point
 * Title ID: 0x{parser.title_id:08X}
 * Base VA : 0x{parser.base_addr:08X}
 * Entry VA: 0x{parser.entry_point:08X}
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>

#include <xbox/xboxrecomp.h>

#define GAME_ENTRY_POINT  0x{parser.entry_point:08X}u
#define GAME_XBE_PATH     "game/default.xbe"
#define GAME_DATA_DIR     "game"

extern RECOMP_TLS uint32_t g_esp;
extern ptrdiff_t g_xbox_mem_offset;
extern void xbe_entry_point(void);

#if defined(_WIN32)
#include <windows.h>
#include <dbghelp.h>

static LONG CALLBACK veh_handler(PEXCEPTION_POINTERS ep)
{{
    if (ep->ExceptionRecord->ExceptionCode == EXCEPTION_ACCESS_VIOLATION) {{
        uintptr_t fault_addr = ep->ExceptionRecord->ExceptionInformation[1];
        uint32_t  fault_va   = (uint32_t)(fault_addr - (uintptr_t)g_xbox_mem_offset);

        // Hardware MMIO trap handling can be routed here
        fprintf(stderr, "[CRASH] Access violation at host RIP=0x%p, Xbox VA=0x%08X\\n",
                (void *)ep->ContextRecord->Rip, fault_va);
    }}
    return EXCEPTION_CONTINUE_SEARCH;
}}
#endif

int main(int argc, char **argv)
{{
    printf("=== Starting {parser.title_name} Recompiled ===\\n");

    FILE *f = fopen(GAME_XBE_PATH, "rb");
    if (!f) {{
        fprintf(stderr, "Failed to open %s. Place game dump in 'game/' directory.\\n", GAME_XBE_PATH);
        return 1;
    }}
    fseek(f, 0, SEEK_END);
    size_t xbe_size = ftell(f);
    fseek(f, 0, SEEK_SET);

    void *xbe_data = malloc(xbe_size);
    if (fread(xbe_data, 1, xbe_size, f) != xbe_size) {{
        fclose(f);
        return 1;
    }}
    fclose(f);

#if defined(_WIN32)
    AddVectoredExceptionHandler(1, veh_handler);
#endif

    printf("Initializing Xbox memory layout...\\n");
    if (!xbox_MemoryLayoutInit(xbe_data, xbe_size)) {{
        fprintf(stderr, "Failed to initialize memory layout.\\n");
        return 1;
    }}
    g_xbox_mem_offset = xbox_GetMemoryOffset();

    printf("Initializing Xbox kernel...\\n");
    xbox_kernel_init();
    xbox_kernel_bridge_init();

    extern void xbox_path_init(const char *game_dir, const char *save_dir);
    xbox_path_init(GAME_DATA_DIR, NULL);

    g_esp = XBOX_STACK_TOP;
    printf("Calling entry point at 0x%08X...\\n", GAME_ENTRY_POINT);

    xbe_entry_point();

    printf("Game exited cleanly.\\n");
    xbox_kernel_shutdown();
    xbox_MemoryLayoutShutdown();
    free(xbe_data);
    return 0;
}}
"""
    (out_dir / "src" / "main.c").write_text(main_c_content, encoding="utf-8")

    # 4. src/recomp_manual.c
    manual_c_content = f"""/**
 * Manual function overrides and hook stubs for {parser.title_name}.
 */
#include <stdio.h>
#include <stdint.h>

#include "recomp/gen/recomp_types.h"

// Define manual replacements here:
// void sub_XXXXXXXX(void) {{ ... }}
"""
    (out_dir / "src" / "recomp_manual.c").write_text(manual_c_content, encoding="utf-8")

    # 5. config/seed_functions.json
    (out_dir / "config" / "seed_functions.json").write_text("[]\n", encoding="utf-8")

    # 6. Pipeline script: scripts/pipeline.py
    extra_sec_str = ",".join(xdk_sections) if xdk_sections else "D3D,DSOUND,XPP,XGRPH"
    pipeline_py = f"""#!/usr/bin/env python3
import subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TK = REPO / "tools" / "xboxrecomp"
XBE = REPO / "game" / "default.xbe"
SEEDS = REPO / "config" / "seed_functions.json"

def run(cmd, **kwargs):
    print(">>", " ".join(cmd))
    res = subprocess.run(cmd, **kwargs)
    if res.returncode != 0:
        sys.exit(res.returncode)

def analyze():
    run([sys.executable, "-m", "tools.xbe_parser", str(XBE), "--json", str(REPO / "config" / "analysis.json")], cwd=TK)
    run([sys.executable, "-m", "tools.disasm", str(XBE), "--force",
         "--extra-sections", "{extra_sec_str}", "--seed-functions", str(SEEDS)], cwd=TK)
    run([sys.executable, "-m", "tools.func_id", str(XBE), "-v"], cwd=TK)
    run([sys.executable, "-m", "tools.abi_analysis", str(XBE), "-v"], cwd=TK)

def lift():
    run([sys.executable, "-m", "tools.recomp", str(XBE), "--all",
         "--split", "1000", "--gen-dir", str(REPO / "src" / "recomp" / "gen"),
         "--exclude-manual", str(REPO / "src" / "recomp_manual.c")], cwd=TK)

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "all"
    if action in ("analyze", "all"):
        analyze()
    if action in ("lift", "all"):
        lift()
"""
    (out_dir / "scripts" / "pipeline.py").write_text(pipeline_py, encoding="utf-8")

    print(f"\n[+] Successfully scaffolded project at: {out_dir}")
    print("    Next steps:")
    print("    1. cd", out_dir)
    print("    2. git submodule add https://github.com/vyanhursky/xboxrecomp.git tools/xboxrecomp")
    print("    3. Copy game dump into game/default.xbe")
    print("    4. python scripts/pipeline.py analyze")
    print("    5. python scripts/pipeline.py lift")
    print("    6. cmake --preset win-x64-debug && cmake --build build/win-x64-debug")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("xbe", type=Path, help="Path to default.xbe")
    ap.add_argument("--out-dir", type=Path, required=True, help="Destination directory for new port")
    args = ap.parse_args()

    if not args.xbe.is_file():
        sys.exit(f"Error: {args.xbe} does not exist")

    generate_scaffold(args.xbe, args.out_dir)


if __name__ == "__main__":
    main()
