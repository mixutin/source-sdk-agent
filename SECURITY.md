# Security and trust boundaries

This experimental tool is for trusted local development projects. It is not a
sandbox for hostile source code, VMFs, QC files, images or audio.

The MCP server uses stdio only and runs as the current user. No public listener,
root account, unattended AI service or firewall change is required. A client
allowed to write/build/launch can execute project code. Only authorize trusted
clients. Do not remove remote-terminal safeguards or enable passwordless root.

C++ builds use a rootless Podman container, digest-pinned image, disabled container
network, dropped capabilities, no new privileges, PID/CPU/memory limits, and
mounts for the project, wrapper and compiler cache. Native map/model/audio/editor
tools run as the current user OUTSIDE that container. The 8 GiB ceiling applies
to C++ builds, not all content processes. Use trusted compilers and inputs.

Project file operations reject absolute paths, parent traversal and external
symlink targets. Existing edits need the observed SHA-256 and retain backups.
Git and internal metadata are excluded from text editing tools. These checks
reduce accidental damage; they are not a race-free boundary against another
malicious local process modifying the filesystem.

Jobs separate submission from success. Pipelines stop on a failed stage and
request cancellation of the active child on interruption. Managed servers bind
to 127.0.0.1, disable public listing, and use generated RCON passwords. Private
session files are mode 0600 and returned logs redact the generated password.
Developer servers disable VAC and enable cheats; do not use these defaults for
public production hosting. Console commands can alter or stop the owned server.

Public releases contain wrapper source, tests, docs and manifests, not local
configurations, credentials, logs, depots, projects or builds. The release audit
checks tracked files and common secret patterns but is not a comprehensive
security audit. Local mod ZIPs still need content and license review before any
separately authorized publication.

Report vulnerabilities through GitHub private vulnerability reporting when
available. Otherwise ask for a private reporting channel without posting secrets
or exploit details. Never attach raw session directories or private logs.
