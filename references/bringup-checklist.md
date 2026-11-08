# Xbox Static Recompilation: Bring-Up Checklist (S0 to S4)

Use this checklist during the bring-up phase of a new Xbox game port.

---

## Stage 0: Dump Extraction & XBE Inspection
- [ ] Extract dump using `extract-xiso`.
- [ ] Run `tools.xbe_parser` on `default.xbe`.
- [ ] Record Base Address, Entry Point, and Section Table.
- [ ] Check if the XDK sections exist: `D3D`, `D3DX`, `DSOUND`, `XPP`, `XGRPH`, `DOLBY`.
- [ ] Create `config/dump-manifest.json` with SHA-256 hashes of all assets.

---

## Stage 1: Static Analysis & Section Coverage
- [ ] Run `tools.disasm` with `--extra-sections` for every code-bearing library section.
- [ ] Run `tools.func_id` to establish function boundaries.
- [ ] Run `tools.abi_analysis` to determine calling conventions and parameter stack sizes.
- [ ] Run `tools.recomp` with `--split 1000` to generate `src/recomp/gen/`.
- [ ] Verify `recomp_dispatch.c` is generated.
- [ ] Verify split-TU sharding: ensure code is partitioned into ~1,000-2,000 function shards to prevent compiler heap exhaustion (`C1002`).

---

## Stage 2: Host Scaffold Setup (`src/main.c`)
- [ ] Configure `YOUR_GAME_ENTRY_POINT` with the entry point VA from the XBE parser.
- [ ] Initialize memory layout with `xbox_MemoryLayoutInit()`.
- [ ] Set `g_xbox_mem_offset = xbox_GetMemoryOffset()`.
- [ ] Install Vectored Exception Handler (VEH on Windows, signal handler on Linux/macOS).
- [ ] Initialize Xbox Kernel HLE (`xbox_kernel_init()` and `xbox_kernel_bridge_init()`).
- [ ] Setup I/O redirections for `D:\`, `T:\`, `U:\`.
- [ ] Initialize `g_esp = XBOX_STACK_TOP`.
- [ ] Initialize D3D11 / Vulkan translator window.
- [ ] Initialize APU / AC97 audio stubs.
- [ ] Configure build system flags: enable `/bigobj` and `/experimental:c11atomics` on MSVC for all C translation units.
- [ ] Verify path safety: ensure no unquoted path arguments are passed to child processes or toolchain CLI tools when workspace paths contain spaces.

---

## Stage 3: Bring-Up Iteration Loop (S0 -> S4)
Run with the smoke tester: `.\tests\smoke\boot-smoke.ps1`.

### If crashing before S1 (Initialization):
- Check memory allocation failure (`xbox_MemoryLayoutInit`).
- Check TLS declarations: are `g_eax`, `g_esp`, etc. properly attributed with `RECOMP_TLS`?

### If crashing between S1 and S2 (Calling guest entry):
- Check CRT initialization: Does the game expect `__active_heap` initialized?
- Inspect exception address in VEH.

### If crashing at S2 (In guest code):
- Run `python scripts/triage.py` to identify the faulting `sub_XXXXXXXX`.
- Check if it is an `[ICALL] Failed to resolve VA` error:
  - Run `.\scripts\seed-from-log.ps1`.
  - Add missing VA to `config/seed_functions.json`.
  - Re-run analysis & lifting.
- Check if the function failed due to a missing hardware poke (e.g. GPU fence, AC97 reset):
  - Add MMIO stub in `src/hooks/`.

### If stuck at S2/S3 (Hang / Watchdog):
- Is audio spinning on a DSP doorbell?
  - Enable DSP auto-ack or stub the doorbell handshake.
- Is D3D spinning on GPU fence space?
  - Mirror Put into `*GetPtr` (`xbox_Nv2aMirrorFence`).

### Reaching S3 & S4:
- S3 reached: Pushbuffer commands are being translated to Direct3D 11 / Vulkan; first frame presented.
- S4 reached: Main game loop running cleanly without watchdog timeouts.

