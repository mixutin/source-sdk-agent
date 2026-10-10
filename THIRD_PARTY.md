# Licensing boundaries

The root 0BSD license applies to original Source SDK Agent code, documentation,
tests and original generated fixtures. It does not change external licenses.

## Valve Source SDK and runtimes

The SDK is an external checkout, not vendored here. Valve licenses it on a
non-commercial basis unless applicable permissions are obtained separately.
This tool does not grant commercial Source rights or permission to redistribute
Valve game assets. Steam, SteamCMD, game depots and compiler container images are
also external; obtain them through Valve's supported channels.

- SDK source: https://github.com/ValveSoftware/source-sdk-2013
- SDK license: https://github.com/ValveSoftware/source-sdk-2013/blob/master/LICENSE
- Mod distribution: https://partner.steamgames.com/doc/sdk/uploading/distributing_source_engine

## Tools++ and editors

The tested native compiler setup used Tools++ obtained from its author. Tools++
is NOT relicensed under 0BSD, and redistribution of its map compilers requires
its author's permission. This repository does not bundle or mirror them.

- Author's distribution: https://ficool2.github.io/HammerPlusPlus-Website/tools.html

Hammer, Hammer++, HLMV, Faceposer and their dependencies likewise require their
own installations and applicable permissions. Editor adapters do not include
those applications.

## Python and audio dependencies

MCP, Pillow, transitive Python packages and FFmpeg retain their own licenses.
requirements.lock records dependencies; no dependency binaries are bundled.
FFmpeg licensing depends on the selected build.

- MCP: https://github.com/modelcontextprotocol/python-sdk
- Pillow: https://github.com/python-pillow/Pillow
- FFmpeg: https://ffmpeg.org/legal.html

## Game assets

The fixture generator produces original simple geometry, a checkerboard texture
and a synthesized tone. Import provenance notes do not establish ownership or
redistribution permission. Review every asset before publishing a mod. A source
license, successful build or ZIP does not establish third-party content rights.
