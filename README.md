# Source SDK Agent

[![Tests](https://github.com/mixutin/source-sdk-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/mixutin/source-sdk-agent/actions/workflows/tests.yml)
[![License: 0BSD](https://img.shields.io/badge/license-0BSD-blue)](LICENSE)

**Local Source SDK 2013 game-development automation for Linux, with a CLI and 40 typed MCP tools.** Create projects, edit C++, author maps, compile models and textures, control a private test server, and run a build-to-package pipeline from an authorized coding assistant or terminal.

This is an independent developer tool, not a complete/open-source copy of Valve's Source engine. It automates the public SDK and separately installed runtimes and content compilers. No root account, public HTTP listener, API key, or always-running AI service is required.

## What it does

| Area | Implemented operations |
| --- | --- |
| Projects and C++ | Independent HL2MP/TF project checkouts; source search; hash-checked edits and backups; game, client, server, launcher, shaders, and server-plugin build targets |
| Maps | Sealed-room generation; structured cuboid brushes; entity properties and I/O; entity removal; raw VMF editing; VBSP/VVIS/VRAD pipeline; BSP inspection and compiler diagnostics |
| Assets | Mipmapped RGBA8888 VTF textures; VMT materials and proxies; QC model compilation; PCM WAV conversion; asset import with provenance; VPK creation and inspection |
| Runtime | Steam client launch requests; private loopback dedicated servers; authenticated RCON commands; bounded logs; map-load smoke tests and cleanup |
| Workflow | Build → models → map → optional server test → optional local ZIP, with per-stage status and fail-fast behavior |
| Optional editors | Launch adapters for separately installed Hammer, HLMV and Faceposer; availability is reported, not assumed |

See [all 40 tools](docs/TOOLS.md), [installation and toolchain configuration](docs/INSTALLATION.md), [security boundaries](SECURITY.md), and [what was actually verified](docs/VERIFICATION.md).

## Quick start

The host needs Linux x86-64, Python 3.10+, Git, rootless Podman, and **Source SDK Base 2013 Multiplayer** installed through Steam (app 243750). FFmpeg is needed for audio conversion. Python's `venv` module or `uv` is needed for the wrapper environment.

```bash
git clone https://github.com/mixutin/source-sdk-agent.git
cd source-sdk-agent

git clone https://github.com/ValveSoftware/source-sdk-2013.git "$HOME/Development/source-sdk-2013"
python3 install.py --sdk "$HOME/Development/source-sdk-2013" --pull-image

~/.local/bin/source-sdk doctor
~/.local/bin/source-sdk call capabilities
```

The installer resolves Valve's compiler image to a digest, creates a private Python environment, detects native or Flatpak Steam libraries, and preserves existing project configuration. It does **not** download or redistribute Valve game assets or Tools++ binaries. Install compatible content compilers separately, then register their location:

```bash
python3 install.py --tools-dir "$HOME/Downloads/source-content-tools"
```

Use the full `~/.local/bin/source-sdk` path when `~/.local/bin` is not in your shell's `PATH`.

## Build a first mod

```bash
source-sdk create my_game --title "My Game" --template hl2mp
source-sdk call generate_room '{"name":"my_game","map_name":"first_room"}'

# Requires configured map compilers and a compatible dedicated runtime.
source-sdk pipeline my_game first_room --quality final --package
source-sdk jobs
source-sdk job JOB_ID
```

A returned job ID is a submission, **not a completed build**. Poll `job` until `state` is `succeeded`, `failed`, or `cancelled`. The pipeline stops at the first failed stage and does not package after a failed server test. `--no-server-test` explicitly skips the server check; it does not claim the result was playtested.

For individual steps:

```bash
source-sdk build my_game --target game
source-sdk call compile_map '{"name":"my_game","map_name":"first_room","quality":"final"}'
source-sdk call smoke_test '{"name":"my_game","map_name":"first_room"}'
source-sdk call register_mod '{"name":"my_game"}'
source-sdk call launch '{"name":"my_game","map_name":"first_room"}'
source-sdk call package_mod '{"name":"my_game"}'
```

Wait for each compilation job to succeed before starting dependent steps. Steam registration never restarts Steam automatically. A Steam launch request is not proof of successful visual gameplay.

## Connect a coding assistant

The installed `source-sdk-mcp` command is an on-demand **stdio MCP server**. For a local Codex installation:

```bash
codex mcp add source-sdk -- /absolute/path/source-sdk-agent/.venv/bin/python /absolute/path/source-sdk-agent/server.py
```

Other local MCP clients can use the same command and argument. Portable `plugin.json`, `mcp.json`, and `skills/source-sdk/SKILL.md` describe this package; run the installer before starting its MCP server. Reload the local client/session after updating tool definitions.

A web chat cannot directly start a stdio process on your PC. An already-authorized remote terminal connector can invoke the CLI instead. Installing this package does not automatically expose your computer to the internet.

## Resource and safety boundaries

C++ compilation uses a rootless Steam Runtime container with four CPU slots and an 8 GiB memory limit by default, no compiler-container network access, dropped capabilities, and a dedicated cache. Native map/model/audio tools run as the current user; they are **not** covered by that C++ container boundary. See [SECURITY.md](SECURITY.md).

Project edits require current SHA-256 values for overwrites and retain backups. The upstream SDK checkout is not edited. Managed servers bind to loopback and are intended only for development. Logs redact the generated RCON password. Packaging is local-only and excludes engine VPK depots unless an archive is registered as an authored project package.

## Development and tests

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m unittest discover -p 'test_*.py' -v
```

The tests use temporary projects and a real stdio MCP connection; they do not require Steam, a game account, or Valve downloads. The audio test needs FFmpeg. Real engine verification is documented separately. CI runs the portable suite on Python 3.10, 3.12 and 3.14.

## Current limitations

Linux x86-64 and the current multiplayer SDK are the implemented host/build target. The HL2MP pipeline has been tested end to end; the TF template is exposed but has not received equivalent integration testing. Windows/MSVC builds, a separate single-player branch, visual gameplay automation, and editor GUI interaction are not implemented. Editor launch adapters require licensed executables and compatible Wine/native dependencies. VTF output is uncompressed RGBA8888, not DXT/BC texture compression.

No wrapper can grant access to engine code that Valve has not released or grant permission to redistribute somebody else's assets. The project does not make those claims.

## License

**All original code in this repository is released under the [Zero-Clause BSD license (0BSD)](LICENSE).** You may use, modify, distribute, and sell this tool without an attribution or source-disclosure requirement. It comes without warranty.

This license does **not** relicense Valve's SDK, Steam runtimes, game assets, Tools++, FFmpeg, Pillow, or other dependencies. They retain their own terms. Valve's public SDK is licensed on a non-commercial basis unless you obtain applicable permissions separately. Tools++ redistribution requires its author's permission. Neither dependency is bundled here. Read [THIRD_PARTY.md](THIRD_PARTY.md) before distributing a game or a tool bundle.

Independent community project; not affiliated with or endorsed by Valve.
