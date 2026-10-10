# Release verification

Recorded on 2026-10-10 for 0.3.0. These observations do not certify all Source
branches, platforms, editors, assets or gameplay.

**53 automated tests passed** on Ubuntu/Python 3.14, including a real stdio MCP
handshake and discovery of all 40 tools. Coverage includes paths, stale writes,
backups, VMF geometry/IDs/I/O, VTF mipmaps, WAV headers, VPK bounds, RCON framing,
installer discovery, and pipeline success/failure/cancellation behavior.

A real HL2MP pipeline completed all five stages: game client/server compilation,
QC/SMD model compilation, full VBSP/VVIS/VRAD map compilation, map-load/RCON smoke
test, and local ZIP packaging. The release_check map includes an added platform
brush, an original checkerboard material, and a custom cube model. VTF and PCM
sound fixtures were also generated through the tool. Test servers stopped after
verification. The BSP was validated and the resulting ZIP remained local.

The original SDK checkout stayed unchanged at commit
be57e3d01ac7d7aa6a2cacbfef187c0b46616db0. The Steam Runtime compiler image digest was
sha256:1c33c507bc75d012e77df5727f93b0d5b8c3f7c8d4142ba5f7a16882cc92e014.
C++ builds used four CPU slots and an 8 GiB memory ceiling.

There was no graphical client playtest, editor GUI test, TF-template integration
test, Windows/MSVC build, separate single-player branch test or internet-hosting
test. Server map loading does not prove correct client visuals, audio playback,
animations or gameplay. Asset rights require separate review.

CI repeats only portable tests, without downloading Valve game content. Private
paths, account data, credentials, depots, generated binaries and local logs are
not published as evidence.
