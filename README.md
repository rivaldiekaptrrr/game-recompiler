# Game Static Recompilation Skill (`game-recompiler`)

Complete playbook and Standard Operating Procedure (SOP) for statically recompiling original Xbox (2001) games to native PC (Windows, macOS, Linux, and Steam Deck) using the `xboxrecomp` toolkit.

---

## 📖 Overview

This skill teaches AI coding assistants (Antigravity, Gemini CLI, Claude Code, Codex) how to port original Xbox games through **ahead-of-time (AOT) static recompilation**. Unlike conventional emulators that interpret or JIT machine code at runtime, static recompilation translates 32-bit x86 Xbox machine code directly into clean, optimized native C code that compiles directly to 64-bit native binaries (`x86_64` or `ARM64`).

---

## 📂 Repository Contents

```text
game-recompiler/
├── SKILL.md                                 # Core agent skill instruction and architecture playbook
├── README.md                                # Project overview and installation guide
├── references/
│   ├── bringup-checklist.md                 # Step-by-step verification checklist (S0 to S4)
│   ├── troubleshooting-patterns.md          # Battle-tested fixes for compiler traps, ICALL, and crashes
│   └── controller-input-guide.md            # Comprehensive guide for Xbox/BT gamepad routing & mode config
└── scripts/
    ├── scaffold-new-port.py                 # Pure-Python scaffolder for original Xbox (XBE) ports
    └── scaffold-psx-port.py                 # Scaffolder for PS1 games with auto-gamepad routing
```

---

## 🚀 Key Topics Covered

1. **AOT Recompilation Pipeline:**
   - XBE extraction and verification (`xbe_parser`).
   - Disassembly using Capstone, including XDK static library sections (`D3D`, `DSOUND`, `XPP`, `XGRPH`, `DOLBY`).
   - Function identification (`func_id`) and calling convention / ABI recovery (`abi_analysis`).
   - C code generation (`tools.recomp`) with chunk splitting (`--split 1000`) and flat dispatch tables.
2. **Host Architecture & Bootstrapping (`src/main.c`):**
   - Memory layout offset (`g_xbox_mem_offset`) and Thread-Local Storage (`RECOMP_TLS`) registers.
   - Vectored Exception Handling (VEH) for MMIO trapping and detailed crash diagnostics.
   - Xbox kernel High-Level Emulation (HLE) and virtual path translation (`D:\`, `T:\`, `U:\`).
3. **Hardware Emulation & Translation:**
   - Translating NV2A pushbuffer commands directly to **Direct3D 11** and **Vulkan**.
   - Emulating APU audio, AC'97 bus master registers, and USB OHCI gamepads.
4. **Bring-Up & Debugging Loop:**
   - S0 to S4 boot stages.
   - Resolving indirect call targets via `seed-from-log`.
   - Fixing GPU fence deadlocks, audio DSP doorbells, and 64-bit integer divide anomalies.
   - **MSVC & Windows Build Diagnostics**: Handling C11 atomics (`/experimental:c11atomics`), resolving GCC/Clang built-in atomic incompatibilities with Win32 Interlocked APIs, bypassing MSVC C++17 lambda `static_assert` traps (`error C2131`), and path-with-spaces quoting.
   - **Split-TU Sharding Strategy**: Managing massive generated codebases (~750k+ lines) to avoid compiler heap exhaustion (`C1002`) and enable multi-core parallel builds.
5. **Modern PC Enhancements:**
   - Widescreen Hor+ camera projection math with 2D HUD element centering.
   - High-resolution / 4K upscaled texture replacement packs.
   - Modern gamepad support (Xbox, DualSense, Switch Pro) and in-game ImGui overlay.
6. **Cross-Console Recompilation Architecture:**
   - Comparative mapping between x86 (Xbox) and MIPS (PS1/PSX, N64) instruction lifting, function discovery (`jr $ra`), delay slots, and low-level BIOS/Kernel execution.

---

## 🛠️ How to Install in Your AI Environment

### Antigravity / Gemini CLI:
Clone or copy this folder into your skills configuration directory:
```bash
git clone https://github.com/rivaldiekaptrrr/game-recompiler.git ~/.gemini/config/skills/game-recompiler
```

### Claude Code / Codex:
Copy `SKILL.md` into your `.claude/skills/` or `.codex/skills/` directory:
```bash
mkdir -p .claude/skills/game-recompiler
cp SKILL.md .claude/skills/game-recompiler/
```

---

## 📜 License

MIT License. See [LICENSE](LICENSE) for details.

