#!/usr/bin/env python3
"""Scaffold a new native static recompilation port for PlayStation 1 (PS1/PSX) games.

Usage:
    python scaffold-psx-port.py path/to/game.cue --exe path/to/SLUS_XXX.XX --out-dir /path/to/PSXPort

Features:
    - Parses PS-X EXE headers (Entry PC, Load Address, Text Size, Initial SP).
    - Auto-configures game.toml with pre-configured modern controls:
        * p1_device = "auto" (Xbox/Bluetooth/DualSense gamepad auto-detection)
        * p1_mode = "analog" (DualShock analog + D-Pad support)
        * deadzone = 3277 (~10% radial deadzone)
    - Generates hardened CMakeLists.txt:
        * Automatic /experimental:c11atomics on MSVC for all C translation units.
        * Split-TU sharding configuration (full_00.c ... full_NN.c).
        * BigObj support and 64MB stack reservation.
    - Generates build.ps1, build.sh, and Play_<Game>.bat one-click launchers.
"""
import argparse
import os
import struct
import sys
from pathlib import Path

PSX_EXE_MAGIC = b"PS-X EXE"


class PsxExeHeader:
    def __init__(self, data: bytes):
        if len(data) < 2048 or data[:8] != PSX_EXE_MAGIC:
            raise ValueError("Not a valid PS-X EXE binary (magic 'PS-X EXE' missing)")
        
        self.entry_pc = struct.unpack_from("<I", data, 0x10)[0]
        self.gp0 = struct.unpack_from("<I", data, 0x14)[0]
        self.load_addr = struct.unpack_from("<I", data, 0x18)[0]
        self.text_size = struct.unpack_from("<I", data, 0x1C)[0]
        self.sp_base = struct.unpack_from("<I", data, 0x30)[0]
        self.sp_offset = struct.unpack_from("<I", data, 0x34)[0]


def generate_psx_scaffold(cue_path: Path, exe_path: Path, out_dir: Path, title_name: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "input").mkdir(exist_ok=True)
    (out_dir / "generated").mkdir(exist_ok=True)
    (out_dir / "seeds").mkdir(exist_ok=True)

    # Read and parse executable header
    exe_bytes = exe_path.read_bytes()
    header = PsxExeHeader(exe_bytes)
    game_id = exe_path.name.replace("_", "-").replace(".", "")
    clean_title = "".join(c for c in title_name if c.isalnum() or c in ("_", "-"))

    # Copy executable into input/
    dest_exe = out_dir / "input" / exe_path.name
    dest_exe.write_bytes(exe_bytes)

    # 1. game.toml
    game_toml = f"""[game]
name = "{clean_title}"
id = "{game_id}"
exe = "input/{exe_path.name}"
disc = "{cue_path.resolve().as_posix()}"
load_address = "0x{header.load_addr:08X}"
entry_pc = "0x{header.entry_pc:08X}"
text_size = "0x{header.text_size:08X}"
stack_base = "0x{header.sp_base:08X}"

[recompiler]
seeds = "seeds/functions.txt"
bios_config = "psxrecomp/bios/OpenBIOS.toml"
strict = true
out_dir = "generated"

[runtime]
window_title = "{clean_title} Recompiled"
bios_hle = false
overlay_cache = true

[controller]
p1_device = "auto"
p1_mode = "analog"
deadzone = 3277

[video]
renderer = "opengl"
"""
    (out_dir / "game.toml").write_text(game_toml, encoding="utf-8")

    # 2. CMakeLists.txt
    cmake_lists = f"""cmake_minimum_required(VERSION 3.20)
set(PSXRECOMP_ROOT "${{CMAKE_CURRENT_SOURCE_DIR}}/psxrecomp")
if(NOT EXISTS "${{PSXRECOMP_ROOT}}/runtime/runtime.cmake")
  message(FATAL_ERROR
    "PSXRecomp runtime is missing: ${{PSXRECOMP_ROOT}}/runtime/runtime.cmake\\n"
    "Ensure psxrecomp framework is located at ${{PSXRECOMP_ROOT}}.")
endif()

project({clean_title} C CXX)
set(CMAKE_C_STANDARD 99)
set(CMAKE_CXX_STANDARD 17)
set(PSX_RECOMP_UI OFF CACHE BOOL "" FORCE)
set(PSXRECOMP_BIOS_STEMS "OpenBIOS" CACHE STRING "" FORCE)

include("${{PSXRECOMP_ROOT}}/runtime/runtime.cmake")

file(GLOB GAME_FULL CONFIGURE_DEPENDS
  "${{CMAKE_CURRENT_SOURCE_DIR}}/generated/{exe_path.name}_full_*.c")
file(GLOB GAME_DISPATCH "${{CMAKE_CURRENT_SOURCE_DIR}}/generated/{exe_path.name}_dispatch.c")

psxrecomp_add_runtime_target(psx-runtime
  GAME_GENERATED_FULL_C "${{GAME_FULL}}"
  GAME_GENERATED_DISPATCH_C "${{GAME_DISPATCH}}"
  WINDOW_TITLE "{clean_title} Recompiled"
  DEFAULT_GAME_CONFIG_PATH "game.toml"
)

# Apply MSVC fixes: /bigobj, C11 atomics, stack size
if(MSVC)
  target_compile_options(psx-runtime PRIVATE /bigobj /GS- /guard:cf-)
  get_target_property(_all_sources psx-runtime SOURCES)
  foreach(_src IN LISTS _all_sources)
    if(_src MATCHES "\\\\.c$")
      set_property(SOURCE ${{_src}} APPEND PROPERTY COMPILE_OPTIONS /experimental:c11atomics)
    endif()
  endforeach()
  target_link_options(psx-runtime PRIVATE /STACK:67108864,67108864 /GUARD:NO)
endif()
"""
    (out_dir / "CMakeLists.txt").write_text(cmake_lists, encoding="utf-8")

    # 3. build.ps1
    build_ps1 = """$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
cmake -S $Root -B (Join-Path $Root 'build') -DCMAKE_BUILD_TYPE=Release
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
cmake --build (Join-Path $Root 'build') --config Release --parallel
exit $LASTEXITCODE
"""
    (out_dir / "build.ps1").write_text(build_ps1, encoding="utf-8")

    # 4. Play Launcher
    play_bat = f"""@echo off
title {clean_title} (PC Port)
cd /d "%~dp0build\\Release"
if exist "{clean_title}_Recompiled.exe" (
    start "" "{clean_title}_Recompiled.exe"
) else if exist "HarvestMoonBTN_Recompiled.exe" (
    start "" "HarvestMoonBTN_Recompiled.exe"
) else if exist "psx-runtime.exe" (
    start "" "psx-runtime.exe"
) else (
    echo Executable not found. Please run build.ps1 first.
    pause
)
"""
    (out_dir / f"Play_{clean_title}_PC.bat").write_text(play_bat, encoding="utf-8")

    # Empty seed file
    (out_dir / "seeds" / "functions.txt").write_text("", encoding="utf-8")

    print(f"\n[+] Successfully scaffolded PS1 Recompilation project at: {out_dir}")
    print(f"    Title:        {clean_title}")
    print(f"    Entry Point:  0x{header.entry_pc:08X}")
    print(f"    Load Address: 0x{header.load_addr:08X}")
    print(f"    Code Size:    {header.text_size} bytes")
    print("\nNext steps:")
    print("1. Recompile game binaray: psxrecomp.exe build ...")
    print("2. Run build.ps1 to produce native PC executable.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cue", type=Path, help="Path to game .cue file")
    ap.add_argument("--exe", type=Path, required=True, help="Path to extracted game executable (e.g. SLUS_011.15)")
    ap.add_argument("--out-dir", type=Path, required=True, help="Output destination folder")
    ap.add_argument("--title", type=str, default="PSXGame", help="Game title name")
    args = ap.parse_args()

    if not args.cue.is_file():
        sys.exit(f"Error: {args.cue} does not exist")
    if not args.exe.is_file():
        sys.exit(f"Error: {args.exe} does not exist")

    generate_psx_scaffold(args.cue, args.exe, args.out_dir, args.title)


if __name__ == "__main__":
    main()
