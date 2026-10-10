---
name: source-sdk
description: Create, edit, compile and test Source SDK 2013 mods through the local source-sdk CLI or MCP server. Use for C++ game code, VMF maps, Source assets, private server tests and local packaging on an authorized Linux computer.
---

# Source SDK development

Start with doctor, capabilities and list_projects using the source-sdk MCP server
or ~/.local/bin/source-sdk through an authorized terminal. Do not infer installed
compilers/editors or successful tests from a tool's existence. Current templates
are multiplayer HL2MP/TF, not a separate single-player branch.

Create independent managed projects. Read files before edits and provide the
current SHA-256 for overwrites. Use source search, raw text, structured brushes,
entity properties and I/O as needed. Preserve backups and inspect git_diff.
Never edit the upstream SDK or unrelated projects.

Build C++ through build. Maps use generate_room/add_brush/edit_map_entity and
compile_map. Asset operations cover VTF/VMT, QC models, audio conversion, imports
with provenance and VPKs. Check third-party prerequisites and content rights.

For a full loop use run_pipeline (CLI: source-sdk pipeline NAME MAP). It builds
code, optional models and the map, then optionally smoke-tests and packages.
Poll get_job to a terminal state. Cancel tracked workers/pipelines on interruption.
Never report a submitted job or plugin-only sample as a successful game build.

Use only managed loopback servers for runtime commands and stop them after tests.
A map/RCON smoke test is not graphical QA. Steam/editor launches are requests,
not proof of GUI success. Do not restart Steam, interrupt other games or alter
firewall/administrator settings. Native content tools are not isolated by the
C++ compiler container; work only with trusted source and executables.

package_mod creates a local archive, not a publication. Review it and its asset
licenses before a separately authorized upload. The wrapper's 0BSD license does
not cover Valve, Tools++ or imported assets. Local stdio does not expose a public
service or give a web chat direct access without an authorized connector.
