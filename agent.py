#!/usr/bin/env python3
"""Local, project-scoped Source SDK 2013 automation. No public listener or root use."""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
import zipfile

VERSION = "0.3.0"
APP = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("SOURCE_SDK_AGENT_CONFIG", str(Path.home()/".config/source-sdk-agent/config.json")))
SLUG = re.compile(r"[a-z][a-z0-9_-]{0,47}\Z")
TEXT_EXT = {".cpp", ".h", ".hpp", ".c", ".vpc", ".vgc", ".txt", ".cfg", ".vmf", ".vmt", ".qc", ".qci", ".res", ".rc", ".json", ".md", ".vdf", ".rad", ".inc", ".fxc", ".hlsl", ".lua", ".nut", ".fgd", ".smd", ".vta", ".vcd", ".vsh", ".psh"}

class AgentError(Exception):
    pass

def cfg() -> dict:
    if not CONFIG.is_file():
        raise AgentError(f"Missing configuration: {CONFIG}. Run install.py first.")
    return json.loads(CONFIG.read_text())

def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def slug(value: str) -> str:
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise AgentError("Use 1–48 lowercase letters, numbers, underscores or hyphens, starting with a letter.")
    return value

def contained(root: Path, relative: str, allow_root: bool = False) -> Path:
    root = root.resolve()
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts or any(x.startswith(".git") or x == ".source-agent" for x in p.parts):
        raise AgentError("Path must stay within the project; internal metadata is not editable.")
    target = (root / p).resolve()
    if not target.is_relative_to(root) or (target == root and not allow_root):
        raise AgentError("Path escapes the project or targets its root.")
    resolved_parts = target.relative_to(root).parts
    if any(x.startswith(".git") or x == ".source-agent" for x in resolved_parts):
        raise AgentError("Symlink targets internal metadata.")
    return target

def project(name: str) -> tuple[Path, dict]:
    root = Path(cfg()["workspace_root"]).resolve()
    path = root / slug(name)
    if path.is_symlink() or not (path / ".source-agent/project.json").is_file():
        raise AgentError(f"Not a managed project: {name}")
    data = json.loads((path / ".source-agent/project.json").read_text())
    if data.get("template") not in ("hl2mp", "tf"):
        raise AgentError("Unsupported template in project metadata.")
    return path, data

def game_path(name: str) -> Path:
    root, meta = project(name)
    return contained(root, "game/mod_" + meta["template"])

def run_read(args: list[str], cwd: Path | None = None, timeout: int = 15) -> str:
    out = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if out.returncode:
        raise AgentError((out.stderr or out.stdout)[-4000:] or f"Command exited {out.returncode}")
    return out.stdout.strip()

@contextlib.contextmanager
def lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AgentError("Another operation is using this workspace. Check jobs first.") from exc
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

def doctor() -> dict:
    """Inspect local prerequisites and report missing configuration without hiding unverified capabilities."""
    try:
        c = cfg()
    except (AgentError, OSError, ValueError) as exc:
        return {"version": VERSION, "configured": False, "ready_for_cpp": False,
                "ready_for_map_compile": False, "issues": [str(exc)], "admin_required": False}
    sdk, runtime = Path(c["sdk_root"]), Path(c["runtime_root"])
    tools = {x: shutil.which(x) for x in ("git", "podman", "flatpak", "wine", "winepath", "ffmpeg")}
    cached, commit, issues = False, None, []
    if tools["podman"]:
        try:
            cached = subprocess.run([tools["podman"], "image", "exists", c["image"]], capture_output=True, timeout=15).returncode == 0
        except subprocess.SubprocessError:
            issues.append("Podman image inspection did not complete.")
    if sdk.is_dir() and tools["git"]:
        try:
            commit = run_read(["git", "rev-parse", "HEAD"], sdk)
        except (AgentError, subprocess.SubprocessError):
            issues.append("SDK directory is not a readable Git checkout.")
    else:
        issues.append("SDK checkout or Git is missing.")
    def present(group, key):
        value = c.get(group, {}).get(key)
        return bool(value and Path(value).is_file())
    installed = (runtime/"hl2_linux64").is_file()
    cpp = bool(tools["podman"] and cached and (sdk/"src/devtools/bin/vpc").is_file())
    if not cpp:
        issues.append("C++ builds need the SDK VPC tool, rootless Podman and the configured compiler image.")
    if not installed:
        issues.append("Source SDK Base 2013 Multiplayer runtime was not found.")
    return {"version": VERSION, "configured": True, "sdk_root": str(sdk), "sdk_commit": commit,
            "runtime_root": str(runtime), "runtime_installed": installed,
            "workspace_root": c["workspace_root"], "tools": tools, "build_image": c["image"], "image_cached": cached,
            "ready_for_cpp": cpp,
            "build_limits": {"jobs": c["jobs"], "memory_gib": c["memory_gib"], "network": "disabled inside compiler container"},
            "map_compilers": {x: c.get("map_tools", {}).get(x) for x in ("vbsp", "vvis", "vrad")},
            "ready_for_map_compile": all(present("map_tools", x) for x in ("vbsp", "vvis", "vrad")),
            "asset_tools": {"studiomdl": present("asset_tools", "studiomdl"), "ffmpeg": bool(tools["ffmpeg"])},
            "issues": issues, "free_gib": round(shutil.disk_usage(sdk if sdk.exists() else APP).free / 2**30, 1), "admin_required": False}

def list_projects() -> dict:
    """List managed Source projects, not unrelated files."""
    root = Path(cfg()["workspace_root"])
    items = []
    for p in sorted(root.glob("*/.source-agent/project.json")):
        try:
            items.append(json.loads(p.read_text()))
        except (ValueError, OSError):
            pass
    return {"projects": items}

def create_project(name: str, title: str = "", template: str = "hl2mp") -> dict:
    """Clone a separate SDK working tree and customize its gameinfo. Does not alter the upstream checkout."""
    name = slug(name)
    if template not in ("hl2mp", "tf"):
        raise AgentError("template must be hl2mp or tf (current multiplayer SDK).")
    title = title or name.replace("_", " ").replace("-", " ").title()
    if not isinstance(title, str) or len(title) > 100 or any(x in title for x in ('"', '\\', '\n', '\r', '\x00')):
        raise AgentError("Title must be at most 100 characters without quotes, backslashes or newlines.")
    c = cfg()
    root = Path(c["workspace_root"])
    dest = root / name
    with lock(root / ".create.lock"):
        if dest.exists() or dest.is_symlink():
            raise AgentError("Project already exists; refusing to overwrite it.")
        run_read(["git", "clone", "--local", "--no-hardlinks", "--quiet", c["sdk_root"], str(dest)], timeout=180)
        run_read(["git", "remote", "set-url", "origin", "https://github.com/ValveSoftware/source-sdk-2013.git"], dest)
        info = dest / "game" / ("mod_" + template) / "gameinfo.txt"
        text = info.read_text()
        text = re.sub(r'(?m)^(\s*game\s+)"[^"\n]*"', lambda m: m[1] + '"' + title + '"', text, count=1)
        text = re.sub(r'(?m)^(\s*title\s+)"[^"\n]*"', lambda m: m[1] + '"' + title + '"', text, count=1)
        text = re.sub(r'(?m)^(\s*title2\s+)"[^"\n]*"', r'\1""', text, count=1)
        text = text.replace("mod_"+template+"/custom/*", "|gameinfo_path|custom/*").replace("mod_"+template+"/download", "|gameinfo_path|download")
        info.write_text(text)
        meta = {"name": name, "title": title, "template": template, "root": str(dest),
                "sdk_commit": run_read(["git", "rev-parse", "HEAD"], dest), "created": time.time()}
        atomic_json(dest / ".source-agent/project.json", meta)
        for folder in ("maps", "cfg", "materials", "models", "sound"):
            (info.parent/folder).mkdir(exist_ok=True)
        (dest/"mapsrc").mkdir(exist_ok=True)
    return {**meta, "game_dir": str(info.parent), "note": "A scaffold, not a compiled or playtested game."}

def list_files(name: str, directory: str = "", limit: int = 100) -> dict:
    """List one project directory, bounded to 500 entries."""
    root, _ = project(name)
    p = contained(root, directory, True)
    if not p.is_dir():
        raise AgentError("Not a directory.")
    files = [{"path": str(x.relative_to(root)), "directory": x.is_dir(), "symlink": x.is_symlink()}
             for x in sorted(p.iterdir()) if x.name not in (".git", ".source-agent")]
    n = max(1, min(int(limit), 500))
    return {"entries": files[:n], "truncated": len(files) > n}

def read_text(name: str, path: str, offset: int = 0, lines: int = 200) -> dict:
    """Read a bounded text range plus the full-file SHA-256 used for safe edits."""
    root, _ = project(name)
    p = contained(root, path)
    if not p.is_file() or p.stat().st_size > 4*1024*1024:
        raise AgentError("Missing file or exceeds 4 MiB text limit.")
    data = p.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AgentError("Not UTF-8 text; use the local asset workflow for binary content.") from exc
    arr = text.splitlines(keepends=True)
    offset, lines = max(0, int(offset)), max(1, min(int(lines), 500))
    return {"path": path, "sha256": sha(data), "total_lines": len(arr), "offset": offset,
            "text": "".join(arr[offset:offset+lines]), "next_offset": offset+lines if offset+lines < len(arr) else None}

def write_text(name: str, path: str, content: str, expected_sha256: str = "") -> dict:
    """Create project text, or overwrite only when its expected hash matches; preserve a backup."""
    root, _ = project(name)
    p = contained(root, path)
    if p.suffix.lower() not in TEXT_EXT or len(content.encode()) > 2*1024*1024 or "\x00" in content:
        raise AgentError("Unsupported extension, binary content or text larger than 2 MiB.")
    with lock(root/".source-agent/edit.lock"):
        backup = None
        if p.exists():
            old = p.read_bytes()
            if not expected_sha256 or sha(old) != expected_sha256:
                raise AgentError("Read the file first and supply its current sha256; refusing a stale overwrite.")
            backup = root/".source-agent/backups"/(str(time.time_ns())+"_"+p.name)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, backup)
        elif expected_sha256:
            raise AgentError("Expected an existing file, but it is missing.")
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name("." + p.name + "." + uuid.uuid4().hex + ".tmp")
        tmp.write_text(content)
        if p.exists():
            shutil.copymode(p, tmp)
        tmp.replace(p)
    return {"path": str(p), "sha256": sha(p.read_bytes()), "backup": str(backup) if backup else None}

def git_diff(name: str) -> dict:
    """Inspect changes without committing or publishing them."""
    root, _ = project(name)
    return {"status": run_read(["git", "status", "--short"], root),
            "diff": run_read(["git", "diff", "--no-ext-diff", "--", "src", "game", "mapsrc"], root)[-60000:]}

def generate_room(name: str, map_name: str = "agent_test") -> dict:
    """Generate an editable six-brush sealed VMF test room with lights and player spawns. Does not compile it."""
    slug(map_name)
    _, meta = project(name)
    counter = 1
    def uid():
        nonlocal counter
        counter += 1
        return counter
    def point(p):
        return "(" + " ".join(str(x) for x in p) + ")"
    def brush(a, b):
        x,y,z = a
        X,Y,Z = b
        faces = [((x,y,Z),(X,y,Z),(X,Y,Z)), ((x,Y,z),(X,Y,z),(X,y,z)),
                 ((x,y,z),(x,y,Z),(x,Y,Z)), ((X,Y,z),(X,Y,Z),(X,y,Z)),
                 ((X,y,z),(X,y,Z),(x,y,Z)), ((x,Y,z),(x,Y,Z),(X,Y,Z))]
        out = 'solid\n{\n"id" "%s"\n' % uid()
        for side_index, f in enumerate(faces):
            f = (f[1], f[0], f[2])  # Valve PlaneFromPoints uses reversed cross-product winding.
            u = "[0 1 0 0] 0.25" if side_index in (2,3) else "[1 0 0 0] 0.25"
            v = "[0 -1 0 0] 0.25" if side_index < 2 else "[0 0 -1 0] 0.25"
            out += 'side\n{\n"id" "%s"\n"plane" "%s"\n"material" "dev/dev_measuregeneric01"\n"uaxis" "%s"\n"vaxis" "%s"\n"rotation" "0"\n"lightmapscale" "16"\n"smoothing_groups" "0"\n}\n' % (uid(), " ".join(point(p) for p in f), u, v)
        return out + "}\n"
    text = 'versioninfo\n{\n"editorversion" "400"\n"editorbuild" "10000"\n"mapversion" "1"\n"formatversion" "100"\n"prefab" "0"\n}\nworld\n{\n"id" "1"\n"classname" "worldspawn"\n"skyname" "sky_day01_01"\n'
    boxes = [((-512,-512,-32),(512,512,0)),((-512,-512,256),(512,512,288)),
             ((-544,-544,-32),(-512,544,288)),((512,-544,-32),(544,544,288)),
             ((-512,-544,-32),(512,-512,288)),((-512,512,-32),(512,544,288))]
    text += "".join(brush(*b) for b in boxes) + "}\n"
    def entity(fields):
        return 'entity\n{\n"id" "%s"\n' % uid() + "".join('"%s" "%s"\n' % x for x in fields.items()) + "}\n"
    for i, origin in enumerate(("-128 -128 16", "128 128 16")):
        data = {"classname": "info_player_deathmatch" if meta["template"] == "hl2mp" else "info_player_teamspawn", "origin": origin, "angles": "0 0 0"}
        if meta["template"] == "tf":
            data["TeamNum"] = str(i+2)
        text += entity(data)
    text += entity({"classname":"light", "origin":"0 0 192", "_light":"255 240 220 600"})
    text += 'cameras\n{\n"activecamera" "-1"\n}\ncordons\n{\n"active" "0"\n}\n'
    result = write_text(name, "mapsrc/"+map_name+".vmf", text)
    return {**result, "compiled": False, "brushes": 6, "map_name": map_name}

def jobs_root() -> Path:
    return Path(cfg()["workspace_root"]) / ".jobs"

def job_file(job_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise AgentError("Invalid job ID.")
    return jobs_root() / (job_id + ".json")

def get_job(job_id: str, tail_lines: int = 60) -> dict:
    """Read job status and its bounded log; a queued/running job is not a completed build."""
    p = job_file(job_id)
    if not p.is_file():
        raise AgentError("Unknown job.")
    data = json.loads(p.read_text())
    log = jobs_root() / (job_id + ".log")
    if log.exists():
        with log.open("rb") as f:
            f.seek(max(0, log.stat().st_size - 50000))
            data["log_tail"] = "\n".join(f.read().decode(errors="replace").splitlines()[-max(1,min(tail_lines,300)):])
    return data

def list_jobs() -> dict:
    """List the most recent 30 automation jobs."""
    paths = sorted(jobs_root().glob("*.json"), key=lambda p:p.stat().st_mtime, reverse=True)[:30]
    return {"jobs": [json.loads(p.read_text()) for p in paths]}

def submit(name: str, operation: str, parameters: dict) -> dict:
    project(name)
    jid = uuid.uuid4().hex
    data = {"job_id": jid, "project": name, "operation": operation, "parameters": parameters, "state": "queued", "created": time.time()}
    atomic_json(job_file(jid), data)
    with (jobs_root() / (jid+".worker.log")).open("a") as out:
        subprocess.Popen([sys.executable, str(APP/"agent.py"), "_worker", jid], stdin=subprocess.DEVNULL,
                         stdout=out, stderr=out, start_new_session=True,
                         env={**os.environ, "SOURCE_SDK_AGENT_CONFIG":str(CONFIG)})
    return data

def build(name: str, configuration: str = "release", target: str = "game") -> dict:
    """Start an isolated Linux64 Steam Runtime build. Target plugin is a small toolchain test; game builds the chosen template."""
    if configuration not in ("release", "debug") or target not in ("game", "plugin", "client", "server", "launcher", "shaders"):
        raise AgentError("configuration must be release/debug; target must be game/plugin/client/server/launcher/shaders.")
    if not doctor()["ready_for_cpp"]:
        raise AgentError("C++ toolchain is not ready; run doctor for the missing prerequisite.")
    return submit(name, "build", {"configuration":configuration, "target":target})

def compile_map(name: str, map_name: str, quality: str = "fast") -> dict:
    """Run configured VBSP, VVIS, VRAD sequentially and install the resulting BSP only on success."""
    slug(map_name)
    root, _ = project(name)
    if not contained(root, "mapsrc/"+map_name+".vmf").is_file():
        raise AgentError("Map source is missing. Generate or write its VMF first.")
    if quality not in ("fast", "final"):
        raise AgentError("quality must be fast or final.")
    tools = cfg().get("map_tools", {})
    missing = [t for t in ("vbsp", "vvis", "vrad") if not Path(tools.get(t,"/missing")).is_file()]
    if missing:
        raise AgentError("Map compilation is unavailable: configure these official compiler executables first: " + ", ".join(missing))
    return submit(name, "compile_map", {"map_name":map_name, "quality":quality})

def proc_start(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")",1)[1].split()[19]
    except (OSError, IndexError):
        return ""

def cancel_job(job_id: str) -> dict:
    """Cancel only a still-running worker owned by this tool, guarding against PID reuse."""
    data = get_job(job_id, 1)
    pid = data.get("pid")
    if data.get("state") != "running" or not pid or proc_start(pid) != data.get("process_start"):
        raise AgentError("No matching running worker; nothing was terminated.")
    os.kill(pid, signal.SIGTERM)
    return {"job_id":job_id, "cancel_requested":True}

def worker(jid: str) -> int:
    data = json.loads(job_file(jid).read_text())
    c = cfg()
    root, meta = project(data["project"])
    data.update(state="running", started=time.time(), pid=os.getpid(), process_start=proc_start(os.getpid()))
    atomic_json(job_file(jid), data)
    container_name = "source-sdk-agent-"+jid
    def interrupted(signum, frame):
        raise InterruptedError("Job cancelled.")
    signal.signal(signal.SIGTERM, interrupted)
    def execute(args, out, cwd=None, env=None, timeout=3600):
        out.write(("\nCOMMAND " + json.dumps([str(x) for x in args])+"\n").encode())
        out.flush()
        p = subprocess.Popen([str(x) for x in args], stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=cwd, env=env, start_new_session=True)
        try:
            code = p.wait(timeout=timeout)
        except BaseException:
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
            raise
        if code:
            raise AgentError(f"Command failed with exit code {code}; see log.")
    try:
        if data["operation"] == "pipeline":
            from sdk_workflow import pipeline_job
            with (jobs_root()/(jid+".log")).open("ab") as out:
                data["pipeline"] = pipeline_job(data, out)
        else:
            with lock(Path(c["workspace_root"])/".build.lock"), (jobs_root()/(jid+".log")).open("ab") as out:
                if data["operation"] == "build":
                    cache = Path(c["workspace_root"])/".ccache"
                    cache.mkdir(exist_ok=True)
                    args = ["podman", "run", "--rm", "--name", container_name, "--pull=never", "--userns=keep-id",
                            "--network=none", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=512",
                            "--memory", str(c["memory_gib"])+"g", "--memory-swap", str(c["memory_gib"])+"g",
                            "--cpus", str(c["jobs"]), "-v", str(root)+":/my_mod:rw", "-v", str(APP)+":/agent:ro",
                            "-v", str(cache)+":/cache:rw", "-e", "CCACHE_DIR=/cache", "-e", "CCACHE_MAXSIZE=2G",
                            c["image"], "bash", "/agent/build.sh", meta["template"], data["parameters"]["configuration"], data["parameters"]["target"], str(c["jobs"])]
                    execute(args, out)
                    if data["parameters"]["target"] == "plugin":
                        expected = [root/"game/bin/linux64/serverplugin_empty.so"]
                    elif data["parameters"]["target"] == "launcher":
                        expected = [root/"game"/("mod_"+meta["template"]+"_linux64")]
                    else:
                        outputs = {"game": ["client.so","server.so"], "client": ["client.so"], "server": ["server.so"], "shaders": ["game_shader_generic_example.so"]}
                        expected = [game_path(data["project"])/"bin/linux64"/x for x in outputs[data["parameters"]["target"]]]
                    if not all(p.is_file() and p.stat().st_size > 0 for p in expected):
                        raise AgentError("Build exited successfully but expected binaries are missing.")
                    data["artifacts"] = [{"path":str(p), "bytes":p.stat().st_size, "sha256":sha(p.read_bytes())} for p in expected]
                elif data["operation"] in ("compile_map", "compile_model"):
                    from sdk_content import content_job
                    data["artifacts"] = content_job(data, out, execute)
                else:
                    raise AgentError("Unknown operation.")
        data["state"] = "succeeded"
    except BaseException as exc:
        data.update(state="cancelled" if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else "failed", error=str(exc))
    finally:
        if data["operation"] == "build":
            with contextlib.suppress(Exception):
                subprocess.run(["podman","stop","--ignore","--time","3",container_name], capture_output=True, timeout=10)
        data["finished"] = time.time()
        atomic_json(job_file(jid), data)
    return 0 if data["state"] == "succeeded" else 1

def register_mod(name: str) -> dict:
    """Add a sourcemods link. Never overwrite an existing different mod or restart Steam."""
    target = game_path(name)
    link = Path(cfg()["steam_root"])/"steamapps/sourcemods"/slug(name)
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        if not link.is_symlink() or link.resolve() != target.resolve():
            raise AgentError("Another mod already occupies this Steam entry.")
    else:
        link.symlink_to(target, target_is_directory=True)
    return {"link":str(link), "target":str(target), "note":"Steam may need a manual restart to list a new mod. Steam was not restarted."}

def launch(name: str, map_name: str = "") -> dict:
    """Request a windowed launch through Steam. This is not proof of a successful game launch."""
    game = game_path(name)
    if not all((game/"bin/linux64"/x).is_file() for x in ("client.so","server.so")):
        raise AgentError("Build the game target first; the client/server binaries are missing.")
    if map_name:
        slug(map_name)
        if not (game/"maps"/(map_name+".bsp")).is_file():
            raise AgentError("Compile this map before requesting launch.")
    c = cfg()
    cmd = ["flatpak","run","com.valvesoftware.Steam"] if c.get("steam_flatpak") else ["steam"]
    cmd += ["-applaunch","243750","-game",str(game),"-novid","-console","-condebug","-windowed","-w","1280","-h","720"]
    if map_name:
        cmd += ["+map",map_name]
    run_read(cmd, timeout=20)
    return {"launch_requested":True, "game_dir":str(game), "console_log":str(game/"console.log"), "verified_running":False}

def console_log(name: str, lines: int = 80) -> dict:
    """Read a project's engine console log without accessing other applications' logs."""
    p = game_path(name)/"console.log"
    if not p.exists():
        return {"exists":False, "note":"No console.log; the game has not written one yet."}
    with p.open("rb") as f:
        f.seek(max(0,p.stat().st_size-50000))
        text = "\n".join(f.read().decode(errors="replace").splitlines()[-max(1,min(lines,300)):])
    return {"exists":True,"path":str(p),"text":text}

def package_mod(name: str) -> dict:
    """Create a local mod ZIP and checksums, excluding engine depots, logs and downloads. Does not publish."""
    root,_ = project(name)
    game = game_path(name)
    dist = root/".source-agent/dist"
    dist.mkdir(exist_ok=True)
    archive = dist/(name+"-"+str(time.time_ns())+".zip")
    manifest = []
    authored_file = root/".source-agent/authored-vpks.json"
    authored = json.loads(authored_file.read_text()) if authored_file.exists() else {}
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(game.rglob("*")):
            rel = p.relative_to(game)
            if p.is_symlink() or not p.is_file() or any(x in ("download","downloads","screenshots") for x in rel.parts) or p.suffix.lower() in (".log",".dmp"):
                continue
            if not p.resolve().is_relative_to(game.resolve()):
                continue
            if p.suffix.lower() == ".vpk" and authored.get(str(rel), {}).get("sha256") != sha(p.read_bytes()):
                continue
            z.write(p, str(Path(name)/rel))
            manifest.append({"file":str(rel),"bytes":p.stat().st_size,"sha256":sha(p.read_bytes())})
        for legal in ("LICENSE","thirdpartylegalnotices.txt"):
            if (root/legal).is_file():
                z.write(root/legal,str(Path(name)/legal))
        z.writestr(name+"/SOURCE-SDK-AGENT-MANIFEST.json",json.dumps(manifest,indent=2))
        z.writestr(name+"/INSTALL-README.txt","Requires Source SDK Base 2013 Multiplayer (Steam app 243750). Extract this mod folder into steamapps/sourcemods. No engine or asset depots are included. Observe Valve's Source 1 SDK license and third-party content licenses. This archive does not certify playtesting.\n")
    return {"archive":str(archive),"sha256":sha(archive.read_bytes()),"files":len(manifest),"published":False,
            "has_game_binaries":all((game/"bin/linux64"/x).is_file() for x in ("client.so","server.so"))}

TOOLS = {fn.__name__:fn for fn in (doctor,list_projects,create_project,list_files,read_text,write_text,git_diff,generate_room,build,compile_map,get_job,list_jobs,cancel_job,register_mod,launch,console_log,package_mod)}

# Preserve one module instance whether invoked as a CLI or imported by the MCP server.
sys.modules.setdefault("agent", sys.modules[__name__])
from sdk_content import TOOLS as CONTENT_TOOLS
from sdk_runtime import TOOLS as RUNTIME_TOOLS
TOOLS.update(CONTENT_TOOLS)
TOOLS.update(RUNTIME_TOOLS)
from sdk_archives import TOOLS as ARCHIVE_TOOLS
TOOLS.update(ARCHIVE_TOOLS)
from sdk_editor import TOOLS as EDITOR_TOOLS
from sdk_workflow import TOOLS as WORKFLOW_TOOLS
TOOLS.update(EDITOR_TOOLS)
TOOLS.update(WORKFLOW_TOOLS)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command",required=True)
    for cmd in ("doctor","projects","jobs"):
        sub.add_parser(cmd)
    p = sub.add_parser("create")
    p.add_argument("name"); p.add_argument("--title",default=""); p.add_argument("--template",choices=["hl2mp","tf"],default="hl2mp")
    p = sub.add_parser("build")
    p.add_argument("name"); p.add_argument("--configuration",choices=["release","debug"],default="release"); p.add_argument("--target",choices=["game","plugin","client","server","launcher","shaders"],default="game")
    p = sub.add_parser("pipeline")
    p.add_argument("name"); p.add_argument("map_name")
    p.add_argument("--configuration", choices=["release", "debug"], default="release")
    p.add_argument("--quality", choices=["fast", "final"], default="fast")
    p.add_argument("--model", action="append", dest="models", default=[])
    p.add_argument("--no-server-test", action="store_false", dest="test_server")
    p.add_argument("--package", action="store_true")
    p = sub.add_parser("job"); p.add_argument("job_id"); p.add_argument("--tail-lines",type=int,default=60)
    p = sub.add_parser("call"); p.add_argument("tool",choices=list(TOOLS)); p.add_argument("arguments",nargs="?",default="{}")
    p = sub.add_parser("_worker"); p.add_argument("job_id")
    a = vars(parser.parse_args()); command = a.pop("command")
    if command == "_worker":
        return worker(a["job_id"])
    try:
        if command == "call":
            arguments = json.loads(a["arguments"])
            if not isinstance(arguments,dict):
                raise AgentError("Arguments must be a JSON object.")
            result = TOOLS[a["tool"]](**arguments)
        else:
            fn = {"doctor":doctor,"projects":list_projects,"jobs":list_jobs,"create":create_project,"build":build,"job":get_job,"pipeline":TOOLS["run_pipeline"]}[command]
            result = fn(**a)
        print(json.dumps({"ok":True,"result":result},indent=2))
        return 0
    except (AgentError, ValueError, OSError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok":False,"error":str(exc)},indent=2))
        return 1

if __name__ == "__main__":
    sys.exit(main())
