# CLI and MCP tool reference

Use any tool through `source-sdk call TOOL JSON_ARGUMENTS`.

## doctor

```python
doctor() -> 'dict'
```

Inspect local prerequisites and report missing configuration without hiding unverified capabilities.

## list_projects

```python
list_projects() -> 'dict'
```

List managed Source projects, not unrelated files.

## create_project

```python
create_project(name: 'str', title: 'str' = '', template: 'str' = 'hl2mp') -> 'dict'
```

Clone a separate SDK working tree and customize its gameinfo. Does not alter the upstream checkout.

## list_files

```python
list_files(name: 'str', directory: 'str' = '', limit: 'int' = 100) -> 'dict'
```

List one project directory, bounded to 500 entries.

## read_text

```python
read_text(name: 'str', path: 'str', offset: 'int' = 0, lines: 'int' = 200) -> 'dict'
```

Read a bounded text range plus the full-file SHA-256 used for safe edits.

## write_text

```python
write_text(name: 'str', path: 'str', content: 'str', expected_sha256: 'str' = '') -> 'dict'
```

Create project text, or overwrite only when its expected hash matches; preserve a backup.

## git_diff

```python
git_diff(name: 'str') -> 'dict'
```

Inspect changes without committing or publishing them.

## generate_room

```python
generate_room(name: 'str', map_name: 'str' = 'agent_test') -> 'dict'
```

Generate an editable six-brush sealed VMF test room with lights and player spawns. Does not compile it.

## build

```python
build(name: 'str', configuration: 'str' = 'release', target: 'str' = 'game') -> 'dict'
```

Start an isolated Linux64 Steam Runtime build. Target plugin is a small toolchain test; game builds the chosen template.

## compile_map

```python
compile_map(name: 'str', map_name: 'str', quality: 'str' = 'fast') -> 'dict'
```

Run configured VBSP, VVIS, VRAD sequentially and install the resulting BSP only on success.

## get_job

```python
get_job(job_id: 'str', tail_lines: 'int' = 60) -> 'dict'
```

Read job status and its bounded log; a queued/running job is not a completed build.

## list_jobs

```python
list_jobs() -> 'dict'
```

List the most recent 30 automation jobs.

## cancel_job

```python
cancel_job(job_id: 'str') -> 'dict'
```

Cancel only a still-running worker owned by this tool, guarding against PID reuse.

## register_mod

```python
register_mod(name: 'str') -> 'dict'
```

Add a sourcemods link. Never overwrite an existing different mod or restart Steam.

## launch

```python
launch(name: 'str', map_name: 'str' = '') -> 'dict'
```

Request a windowed launch through Steam. This is not proof of a successful game launch.

## console_log

```python
console_log(name: 'str', lines: 'int' = 80) -> 'dict'
```

Read a project's engine console log without accessing other applications' logs.

## package_mod

```python
package_mod(name: 'str') -> 'dict'
```

Create a local mod ZIP and checksums, excluding engine depots, logs and downloads. Does not publish.

## inspect_map

```python
inspect_map(name: 'str', map_name: 'str') -> 'dict'
```

Inspect VMF entities, brushes, connections, unique IDs, and spawn points; not a leak test.

## edit_map_entity

```python
edit_map_entity(name: 'str', map_name: 'str', entity_id: 'str', properties: 'dict', expected_sha256: 'str', connections: 'list | None' = None) -> 'dict'
```

Add an entity (empty entity_id) or update one, preserving geometry and duplicate I/O outputs.

## create_material

```python
create_material(name: 'str', material_name: 'str', shader: 'str' = 'LightmappedGeneric', parameters: 'dict | None' = None, expected_sha256: 'str' = '') -> 'dict'
```

Create a VMT for any named Source shader, including material parameters and nested proxies.

## compile_texture

```python
compile_texture(name: 'str', source: 'str', texture_name: 'str', expected_sha256: 'str' = '') -> 'dict'
```

Convert a project PNG/TGA/JPEG/BMP to a mipmapped Source VTF 7.2 RGBA8888 texture (uncompressed).

## convert_sound

```python
convert_sound(name: 'str', source: 'str', sound_name: 'str', mono: 'bool' = True, expected_sha256: 'str' = '') -> 'dict'
```

Convert project audio to Source-friendly 44.1 kHz, signed 16-bit PCM WAV through FFmpeg.

## import_asset

```python
import_asset(name: 'str', source: 'str', destination: 'str', license_note: 'str', expected_sha256: 'str' = '') -> 'dict'
```

Copy an asset staged inside this project into its game directory and record its provenance.

## inspect_bsp

```python
inspect_bsp(name: 'str', map_name: 'str') -> 'dict'
```

Validate BSP header/lump bounds and summarize compiled geometry, entities, lighting and embedded files.

## diagnose_job

```python
diagnose_job(job_id: 'str') -> 'dict'
```

Extract actionable compiler errors, leak messages and missing assets from a bounded job log.

## compile_model

```python
compile_model(name: 'str', source: 'str') -> 'dict'
```

Compile a project QC/SMD/DMX model using configured StudioMDL and stage outputs before installation.

## search_source

```python
search_source(name: 'str', query: 'str', directory: 'str' = 'src', limit: 'int' = 60) -> 'dict'
```

Search literal text within project source, with bounded file sizes/results and no external symlink traversal.

## start_server

```python
start_server(name: 'str', map_name: 'str', port: 'int' = 28015, max_players: 'int' = 8) -> 'dict'
```

Start a private loopback-only, insecure developer server for a compiled managed mod. No public listing or firewall changes.

## server_status

```python
server_status(name: 'str', lines: 'int' = 50) -> 'dict'
```

Check owned process identity, RCON readiness, current map and a redacted bounded server log.

## console_command

```python
console_command(name: 'str', command: 'str') -> 'dict'
```

Send a Source console command to this tool's own local developer server (never to another server).

## stop_server

```python
stop_server(name: 'str') -> 'dict'
```

Stop only this project's exact managed server process, with PID-reuse protection.

## smoke_test

```python
smoke_test(name: 'str', map_name: 'str', port: 'int' = 28015, timeout_seconds: 'int' = 45) -> 'dict'
```

Launch a local server, assert it loads the requested map and answers RCON, then always stop it.

## capabilities

```python
capabilities() -> 'dict'
```

Report implemented versus installed/tested Source capabilities without implying private engine-source access.

## discover_toolchain

```python
discover_toolchain(apply: 'bool' = False) -> 'dict'
```

Find compiler/editor executables only in known Source tool and Steam depot directories; optionally save their paths.

## inspect_vpk

```python
inspect_vpk(name: 'str', path: 'str', prefix: 'str' = '', limit: 'int' = 100) -> 'dict'
```

Read an owned project VPK directory, not installed Valve depots; validates inline offsets and paths.

## pack_vpk

```python
pack_vpk(name: 'str', source_directory: 'str', package_name: 'str', license_note: 'str', expected_sha256: 'str' = '') -> 'dict'
```

Package a project asset directory into a loadable custom VPK and record it as an authored archive.

## add_brush

```python
add_brush(name: 'str', map_name: 'str', minimum: 'list[float]', maximum: 'list[float]', expected_sha256: 'str', material: 'str' = 'dev/dev_measuregeneric01', entity_id: 'str' = '') -> 'dict'
```

Add a correctly wound cuboid to the world or an existing brush entity, with a hash-checked backup.

## remove_map_entity

```python
remove_map_entity(name: 'str', map_name: 'str', entity_id: 'str', expected_sha256: 'str') -> 'dict'
```

Remove one VMF entity by ID, keeping geometry elsewhere intact and retaining an undo backup.

## open_editor

```python
open_editor(name: 'str', editor: 'str' = 'hammer', path: 'str' = '') -> 'dict'
```

Request a configured Hammer/HLMV/Faceposer window for this project; does not claim GUI automation or successful startup.

## run_pipeline

```python
run_pipeline(name: 'str', map_name: 'str', configuration: 'str' = 'release', quality: 'str' = 'fast', models: 'list[str] | None' = None, test_server: 'bool' = True, package: 'bool' = False) -> 'dict'
```

Submit build -> optional models -> map compile -> optional server smoke test -> optional local ZIP. Never publishes.
