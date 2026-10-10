# Installation and toolchains

Use Linux x86-64, Python 3.10+, Git, rootless Podman, Steam's Source SDK Base 2013
Multiplayer (app 243750), and FFmpeg for audio. Python venv support or uv is needed.
Clone this repository and Valve's SDK, then run:

```bash
python3 install.py --sdk /path/to/source-sdk-2013 --pull-image
```

The installer detects native/Flatpak Steam libraries, pins the compiler image by
digest, installs locked Python packages, and creates local launchers. It does not
change OS privileges, remote-access settings or firewall rules. Configuration is
at `~/.config/source-sdk-agent/config.json`; SOURCE_SDK_AGENT_CONFIG selects an
alternate config. Existing workspaces are preserved. Explicit option updates
make a configuration backup.

Options include --sdk, --steam-root, --runtime, --workspace, --tools-dir,
--server-runtime, --image and --pull-image. See `python3 install.py --help`.
The default workspace is inside Steam's own data area for Flatpak compatibility.

## Content compilers

Obtain compatible VBSP, VVIS, VRAD and StudioMDL executables separately. The tested
native route used Linux Tools++ from its author's distribution:
https://ficool2.github.io/HammerPlusPlus-Website/tools.html . Redistribution of
its map compilers requires permission; they are not bundled here.

```bash
python3 install.py --tools-dir /path/to/source-content-tools
source-sdk doctor
```

Keep compiler libraries beside their executables. Config keys are map_tools.vbsp,
map_tools.vvis, map_tools.vrad and asset_tools.studiomdl. Native executables and
Windows .exe tools via a dedicated Wine prefix are supported by the adapter;
the Wine route has not received equivalent live integration testing. Temporary
gameinfo files and short content aliases resolve Steam paths without editing
installed depots. Outputs are staged, checked and backed up before replacement.

## Dedicated servers

The client SDK installation may lack a complete usable dedicated library set.
Point the adapter at a compatible installation containing srcds_linux64:

```bash
python3 install.py --server-runtime /path/to/compatible-dedicated-runtime
```

The recorded test used a locally installed TF2 dedicated runtime with the SDK's
compiled HL2MP module. This is a tested compatibility arrangement, not a guarantee
for every future depot combination. Per-session library/module aliases and
proxy gameinfo files leave Steam runtimes unchanged. Obtain runtimes through
Valve's channels and observe their licenses.

For client-library discovery, the adapter checks installed Steam/SteamCMD paths.
If needed, set steamclient_path in local configuration to a legitimate installed
steamclient.so. Do not copy account credentials into this repository. Smoke tests
use loopback port 28015; individual server operations allow another unprivileged
port. No public listener or firewall rule is created.

## Editors and assistants

Configure editor_tools.hammer, editor_tools.hlmv or editor_tools.faceposer with
licensed local executables, or use --tools-dir. open_editor requests a project
window, not GUI interaction or proof of compatibility. GUI editor execution was
not verified in the recorded release setup.

Register the generated environment Python and server.py with a local MCP client:

```bash
codex mcp add source-sdk -- /absolute/path/source-sdk-agent/.venv/bin/python /absolute/path/source-sdk-agent/server.py
```

Reload the session after upgrades. `codex mcp remove source-sdk` removes that
connection without deleting projects. A web assistant needs a separately
authorized terminal connector to invoke the CLI; stdio is not a cloud service.
