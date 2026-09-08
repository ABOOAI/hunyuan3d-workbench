"""Fast local CLI/MCP for the official Hunyuan 3D web workbench.

Persistent Chrome executes visible UI workflows using the web account.
Uploads, one-shot submission, durable monitoring and verified downloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import struct
import sys
import time
from typing import Any
import uuid
from contextlib import contextmanager

from PIL import Image

VERSION = "0.2.1"


def default_state_root() -> Path:
    """Choose a writable per-user location, never the installed package directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base.expanduser() / "hunyuan-workbench"


DEFAULT_ROOT = default_state_root()
VIEWS = ("front", "right", "back", "left", "top", "bottom", "left_front", "right_front")
WEB_LABELS = {"front": "正图", "right": "右图", "back": "背图", "left": "左图", "top": "顶图", "bottom": "底图", "left_front": "左45度图", "right_front": "右45度图"}
FACE_LABELS = {50000: "50k", 500000: "500k", 1000000: "1m", 1500000: "1.5m"}
STATES = {"PREPARED", "UPLOADING", "READY", "SUBMITTING", "UNCERTAIN", "SUBMITTED", "RUNNING", "SUCCEEDED", "FAILED", "DOWNLOADED"}
TRANSITIONS = {
    "PREPARED": {"UPLOADING"}, "UPLOADING": {"READY"}, "READY": {"UPLOADING", "SUBMITTING"},
    "SUBMITTING": {"SUBMITTED", "UNCERTAIN"}, "UNCERTAIN": {"SUBMITTED", "RUNNING", "SUCCEEDED", "FAILED"},
    "SUBMITTED": {"RUNNING", "SUCCEEDED", "FAILED"}, "RUNNING": {"SUCCEEDED", "FAILED"},
    "SUCCEEDED": {"DOWNLOADED"}, "FAILED": set(), "DOWNLOADED": set(),
}

def dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)

def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def inspect_image(path: Path) -> dict:
    path = path.expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("Reference must be a regular file")
    size = path.stat().st_size
    if size > 10 * 1024 * 1024:
        raise ValueError("Reference exceeds the local 10 MiB workbench preset")
    with Image.open(path) as im:
        width, height = im.size
        fmt = im.format
        if fmt not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError("Use PNG, JPEG or WEBP references")
        if not (128 <= width <= 4096 and 128 <= height <= 4096):
            raise ValueError("Reference must be 128..4096 pixels per edge for the web Studio preset")
        if getattr(im, "n_frames", 1) != 1:
            raise ValueError("Animated references are not supported")
        im.verify()
    return {"path": str(path), "bytes": size, "width": width, "height": height,
            "format": fmt, "sha256": digest(path)}

def inspect_glb(path: Path) -> dict:
    path = path.resolve(strict=True)
    size = path.stat().st_size
    if size > 2 * 1024**3:
        raise ValueError("GLB exceeds the 2 GiB local import limit")
    with path.open("rb") as f:
        header = f.read(12)
        if len(header) != 12:
            raise ValueError("Truncated GLB header")
        magic, version, declared = struct.unpack("<4sII", header)
        if magic != b"glTF" or version != 2 or declared != size:
            raise ValueError("Invalid GLB v2 header or file length")
        doc = None
        binary_bytes = 0
        while f.tell() < size:
            chunk_header = f.read(8)
            if len(chunk_header) != 8:
                raise ValueError("Truncated chunk header")
            length, kind = struct.unpack("<II", chunk_header)
            if length % 4 or f.tell() + length > size:
                raise ValueError("Invalid chunk boundary")
            if kind == 0x4E4F534A:
                if doc is not None or length > 64 * 1024**2:
                    raise ValueError("Duplicate or oversized JSON chunk")
                doc = json.loads(f.read(length).decode("utf-8").rstrip("\x00 \t\r\n"))
            else:
                if kind == 0x004E4942:
                    binary_bytes += length
                f.seek(length, 1)
        if doc is None or doc.get("asset", {}).get("version") != "2.0":
            raise ValueError("Missing glTF 2.0 document")
    external = [x["uri"] for k in ("buffers", "images") for x in doc.get(k, [])
                if x.get("uri") and not x["uri"].startswith("data:")]
    if external:
        raise ValueError("GLB contains external resources; bundle these before importing")
    accessors = doc.get("accessors", [])
    triangles = 0
    unsupported = []
    for mesh in doc.get("meshes", []):
        for p in mesh.get("primitives", []):
            idx = p.get("indices", p.get("attributes", {}).get("POSITION"))
            if not isinstance(idx, int) or not 0 <= idx < len(accessors):
                raise ValueError("Primitive references an invalid accessor")
            n = accessors[idx]["count"]
            if not isinstance(n, int) or n < 0:
                raise ValueError("Invalid accessor count")
            mode = p.get("mode", 4)
            if mode == 4:
                if n % 3:
                    raise ValueError("Triangle index count must be divisible by three")
                triangles += n // 3
            elif mode in (5, 6):
                triangles += max(0, n - 2)
            else:
                unsupported.append(mode)
    if not doc.get("meshes"):
        raise ValueError("GLB has no meshes")
    for buf in doc.get("buffers", []):
        if not buf.get("uri") and buf.get("byteLength", 0) > binary_bytes:
            raise ValueError("Declared buffer is larger than the GLB binary data")
    return {"path": str(path), "bytes": size, "sha256": digest(path),
            "mesh_triangles": triangles, "mesh_count": len(doc.get("meshes", [])),
            "material_count": len(doc.get("materials", [])), "image_count": len(doc.get("images", [])),
            "skin_count": len(doc.get("skins", [])), "animation_count": len(doc.get("animations", [])),
            "extensions_required": doc.get("extensionsRequired", []), "non_triangle_modes": unsupported,
            "validation_scope": "Container and declared mesh counts; not visual, manifold, or GPU validation"}

def inspect_asset(path: Path) -> dict:
    path=path.resolve(strict=True)
    if path.suffix.lower()=='.glb': return inspect_glb(path)
    size=path.stat().st_size
    if not 0<size<=2*1024**3: raise ValueError('Invalid downloaded asset size')
    with path.open('rb') as f: prefix=f.read(512)
    ext=path.suffix.lower()
    if ext=='.fbx':
        if not (prefix.startswith(b'Kaydara FBX Binary') or b'FBX' in prefix): raise ValueError('Invalid FBX header')
    elif ext in {'.png','.jpg','.jpeg','.webp'}:
        with Image.open(path) as im: im.verify()
    elif ext in {'.zip','.usdz'}:
        import zipfile
        with zipfile.ZipFile(path) as z:
            names=z.namelist()
            if not names or any(Path(n).is_absolute() or '..' in Path(n.replace('\\','/')).parts for n in names): raise ValueError('Unsafe archive member path')
            if sum(i.file_size for i in z.infolist())>4*1024**3: raise ValueError('Archive expanded size exceeds local limit')
            if z.testzip(): raise ValueError('Archive CRC error')
    elif ext=='.gif':
        if prefix[:6] not in {b'GIF87a',b'GIF89a'}: raise ValueError('Invalid GIF header')
    elif ext=='.mp4':
        if b'ftyp' not in prefix[:32]: raise ValueError('Invalid MP4 header')
    elif ext=='.stl':
        if not prefix.lstrip().startswith(b'solid') and (len(prefix)<84 or 84+50*struct.unpack('<I',prefix[80:84])[0]!=size): raise ValueError('Invalid STL size/header')
    elif ext=='.obj':
        if b'<html' in prefix.lower(): raise ValueError('Downloaded HTML instead of OBJ')
    else: raise ValueError('Unsupported downloaded file extension: '+ext)
    return {'path':str(path),'bytes':size,'sha256':digest(path),'format':ext[1:],
            'validation_scope':'File signature/archive integrity; mesh and animation need Blender validation'}

class Workbench:
    def __init__(self, root: str | Path | None = None):
        selected = root if root is not None else os.getenv("HUNYUAN_WORKBENCH_ROOT") or default_state_root()
        self.root = Path(selected).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "jobs.sqlite3"
        with self.connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, state TEXT NOT NULL, data TEXT NOT NULL, updated REAL NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, job_id TEXT NOT NULL, at REAL NOT NULL, state TEXT NOT NULL, evidence TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.db, timeout=15)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def get(self, job_id: str) -> dict:
        with self.connect() as con:
            row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise ValueError("Unknown job id")
            result = json.loads(row["data"])
            result.update(id=row["id"], state=row["state"], updated=row["updated"])
            result["events"] = [dict(r) for r in con.execute("SELECT at,state,evidence FROM events WHERE job_id=? ORDER BY seq", (job_id,))]
            return result

    def list(self) -> list:
        with self.connect() as con:
            rows = con.execute("SELECT id,state,data,updated FROM jobs ORDER BY updated DESC").fetchall()
        return [{"id": r["id"], "name": json.loads(r["data"])["name"], "state": r["state"], "updated": r["updated"]} for r in rows]

    def prepare(self, name: str, views: dict[str, str], face_count: int = 50000, height_m: float | None = None, revision: str = "v001") -> dict:
        if not name.strip() or len(name) > 100 or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,40}", revision):
            raise ValueError("Use a nonempty name and a simple revision identifier")
        if not 3 <= len(views) <= 8 or "front" not in views or set(views) - set(VIEWS):
            raise ValueError("Provide 3..8 named views including front")
        if face_count not in FACE_LABELS:
            raise ValueError("Workbench preset supports 50k, 500k, 1m or 1.5m faces")
        if height_m is not None and not 0 < height_m <= 100:
            raise ValueError("height_m must be positive and at most 100 metres")
        inspected = {view: inspect_image(Path(views[view])) for view in VIEWS if view in views}
        if len({v["sha256"] for v in inspected.values()}) != len(inspected):
            raise ValueError("Do not use duplicate image files as different views")
        spec = {"name": name, "revision": revision, "model": "3.1", "face_count": face_count,
                "height_m": height_m, "views": {k: v["sha256"] for k, v in inspected.items()}}
        fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute("SELECT id FROM jobs WHERE fingerprint=?", (fingerprint,)).fetchone()
            if existing:
                return self.get(existing["id"])
            job_id = "hy_" + uuid.uuid4().hex[:16]
            folder = self.root / "jobs" / job_id
            folder.mkdir(parents=True)
            for view, info in inspected.items():
                dest = folder / "references" / (view + Path(info["path"]).suffix.lower())
                dest.parent.mkdir(exist_ok=True)
                shutil.copy2(info["path"], dest)
                if digest(dest) != info["sha256"]:
                    raise ValueError("Reference changed during preparation")
                info["source_path"], info["path"] = info["path"], str(dest)
            data = {**spec, "feature":"geometry", "mode":"multiview", "views": inspected, "folder": str(folder), "provider": "official-web-workbench",
                    "workbench_url": "https://3d.hunyuan.tencent.com/", "submitted": False}
            (folder / "manifest.json").write_text(dump(data), encoding="utf-8")
            con.execute("INSERT INTO jobs VALUES (?,?,?,?,?)", (job_id, fingerprint, "PREPARED", dump(data), time.time()))
        return self.get(job_id)

    def transition(self, job_id: str, state: str, evidence: str, expected: str | None = None) -> dict:
        if not evidence.strip() or len(evidence) > 4000:
            raise ValueError("Supply short, observed UI evidence without cookies or tokens")
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise ValueError("Unknown job id")
            current = row["state"]
            if expected is not None and expected != current:
                raise ValueError(f"Expected {expected}, found {current}; inspect before acting")
            if state not in TRANSITIONS[current]:
                raise ValueError(f"Transition {current} -> {state} is not allowed; never blindly resubmit")
            con.execute("UPDATE jobs SET state=?, updated=? WHERE id=?", (state, time.time(), job_id))
            con.execute("INSERT INTO events(job_id,at,state,evidence) VALUES(?,?,?,?)", (job_id, time.time(), state, evidence))
        return self.get(job_id)

    def ingest(self, job_id: str, downloaded_file: str) -> dict:
        job = self.get(job_id)
        if job["state"] != "SUCCEEDED":
            raise ValueError("Verify the matching web task succeeded before archiving its output")
        src = Path(downloaded_file).resolve(strict=True)
        report = inspect_asset(src)
        folder = Path(job["folder"]) / "output"
        folder.mkdir(exist_ok=True)
        dest = folder / (job_id + "_source" + src.suffix.lower())
        if dest.exists() and digest(dest) != report["sha256"]:
            raise ValueError("A different output already exists; use a new revision")
        if not dest.exists():
            temp = dest.with_suffix(".partial")
            shutil.copy2(src, temp)
            if digest(temp) != report["sha256"]:
                raise ValueError("Download changed while copying")
            temp.replace(dest)
        report.update(source_download=str(src), path=str(dest))
        (folder / "inspection.json").write_text(dump(report), encoding="utf-8")
        self.transition(job_id, "DOWNLOADED", "Archived output SHA256=" + report["sha256"], expected="SUCCEEDED")
        return report

    def blender_script(self, job_id: str) -> dict:
        job = self.get(job_id)
        if job["state"] != "DOWNLOADED":
            raise ValueError("Archive and inspect the GLB first")
        report=json.loads((Path(job['folder'])/'output'/'inspection.json').read_text(encoding='utf-8'))
        source=Path(report['path'])
        if source.suffix.lower() not in {'.glb','.fbx','.obj','.stl'}: raise ValueError('This artifact is not a directly importable model')
        output = Path(job["folder"]) / "output" / (job_id + "_normalized.blend")
        payload = {"source": str(source), "output": str(output), "height": job["height_m"], "name": job["name"]}
        code = '''import bpy, json
from mathutils import Vector
cfg = json.loads(CONFIG_JSON)
bpy.ops.wm.read_factory_settings(use_empty=True)
suffix = cfg['source'].lower().rsplit('.',1)[-1]
if suffix=='glb': bpy.ops.import_scene.gltf(filepath=cfg['source'])
elif suffix=='fbx': bpy.ops.import_scene.fbx(filepath=cfg['source'])
elif suffix=='obj': bpy.ops.wm.obj_import(filepath=cfg['source'])
elif suffix=='stl': bpy.ops.wm.stl_import(filepath=cfg['source'])
bpy.context.scene.unit_settings.system = 'METRIC'
bpy.context.scene.unit_settings.scale_length = 1.0
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
points = [o.matrix_world @ Vector(v) for o in meshes for v in o.bound_box]
if not points: raise RuntimeError('No mesh geometry')
lo = Vector(tuple(min(p[i] for p in points) for i in range(3)))
hi = Vector(tuple(max(p[i] for p in points) for i in range(3)))
if hi.z - lo.z <= 0: raise RuntimeError('Zero-height asset')
root = bpy.data.objects.new(cfg['name'] + '_Root', None)
bpy.context.scene.collection.objects.link(root)
for obj in list(bpy.context.scene.objects):
    if obj != root and obj.parent is None:
        world = obj.matrix_world.copy()
        obj.parent = root
        obj.matrix_world = world
factor = cfg['height'] / (hi.z - lo.z) if cfg['height'] else 1.0
root.scale = (factor,) * 3
root.location = (-factor*(lo.x+hi.x)/2, -factor*(lo.y+hi.y)/2, -factor*lo.z)
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=cfg['output'])
print('HUNYUAN_IMPORT_OK ' + cfg['output'])
'''.replace("CONFIG_JSON", repr(json.dumps(payload)))
        target = Path(job["folder"]) / "output" / "import_in_background.py"
        target.write_text(code, encoding="utf-8")
        return {"script": str(target), "output": str(output), "run_mode": "blender --background --factory-startup --python SCRIPT", "note": "Run in a separate Blender process; resets its scene. No live-scene execution. Scaling assumes glTF importer has converted axes correctly; inspect visually."}


def serve():
    from command_api import serve as run
    run()

def main():
    from command_api import main as run
    run()

if __name__ == '__main__':
    main()
