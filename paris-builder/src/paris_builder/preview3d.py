"""Deterministic schematic previews from Mojang's real Java block models.

This is a small offline software renderer, not Minecraft and not an AI image.
It reads the official 1.21.1 client JAR into a local cache on first use. Block
variants, multipart states, inherited models, element rotations, model rotations,
and texture UVs are supported. Lighting is an approximation; uvlock, biome tint,
animated textures, block entities and physically correct glass are not simulated.
Textures remain in the local cache and are not part of a redistributable package.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import io
import json
import math
from pathlib import Path
import time
import urllib.request
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .schematic import AIR_BLOCKS, base_block, load_schematic


VERSION = "1.21.11"
DATA_VERSION = 4671
MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
DEFAULT_CACHE = Path(__file__).resolve().parents[2] / "assets" / "cache" / f"minecraft-{VERSION}"
NORMALS = {"north": (0, 0, -1), "south": (0, 0, 1), "west": (-1, 0, 0),
           "east": (1, 0, 0), "up": (0, 1, 0), "down": (0, -1, 0)}


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ParisBuilder/0.1"}), timeout=90) as response:
        return response.read()


def ensure_assets(cache_dir: Path = DEFAULT_CACHE) -> Path:
    """Fetch the official client once, verifying the manifest's SHA-1 digest."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / "client.jar"
    provenance = cache_dir / "provenance.json"
    if target.exists() and provenance.exists():
        metadata = json.loads(provenance.read_text(encoding="utf-8"))
        if hashlib.sha1(target.read_bytes()).hexdigest() == metadata["client_sha1"]:
            return target
    versions = json.loads(_get(MANIFEST_URL))
    entry = next(v for v in versions["versions"] if v["id"] == VERSION)
    metadata = json.loads(_get(entry["url"]))
    download = metadata["downloads"]["client"]
    print(f"Fetching official Minecraft {VERSION} model/texture assets ({download['size'] / 1e6:.1f} MB)", flush=True)
    data = _get(download["url"])
    if hashlib.sha1(data).hexdigest() != download["sha1"]:
        raise ValueError("Minecraft client download SHA-1 mismatch")
    target.write_bytes(data)
    provenance.write_text(json.dumps({"minecraft_version": VERSION, "manifest_url": MANIFEST_URL,
        "version_metadata_url": entry["url"], "client_url": download["url"],
        "client_sha1": download["sha1"], "source": "Official Mojang Java client assets",
        "redistribution": "Local rendering cache; do not redistribute Mojang textures with a standalone tool."}, indent=2), encoding="utf-8")
    return target


def _rotation(axis: str, degrees: float) -> np.ndarray:
    angle = math.radians(degrees)
    c, s = math.cos(angle), math.sin(angle)
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float32)
    if axis == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float32)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float32)


def _state_parts(state: str) -> tuple[str, dict]:
    name, _, rest = state.partition("[")
    props = dict(p.split("=", 1) for p in rest.rstrip("]").split(",") if "=" in p)
    return name, props


def _condition(when: dict, props: dict) -> bool:
    if "OR" in when:
        return any(_condition(branch, props) for branch in when["OR"])
    if "AND" in when:
        return all(_condition(branch, props) for branch in when["AND"])
    return all(props.get(key, "false") in str(value).split("|") for key, value in when.items())


def _face_vertices(face: str, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    return np.asarray({
        "north": [(x1,y1,z0),(x0,y1,z0),(x0,y0,z0),(x1,y0,z0)],
        "south": [(x0,y1,z1),(x1,y1,z1),(x1,y0,z1),(x0,y0,z1)],
        "west": [(x0,y1,z0),(x0,y1,z1),(x0,y0,z1),(x0,y0,z0)],
        "east": [(x1,y1,z1),(x1,y1,z0),(x1,y0,z0),(x1,y0,z1)],
        "up": [(x0,y1,z0),(x1,y1,z0),(x1,y1,z1),(x0,y1,z1)],
        "down": [(x0,y0,z1),(x1,y0,z1),(x1,y0,z0),(x0,y0,z0)],
    }[face], dtype=np.float32)


def _default_uv(face: str, lo: np.ndarray, hi: np.ndarray) -> list:
    a, b = lo * 16, hi * 16
    return {"down": [a[0], 16-b[2], b[0], 16-a[2]],
        "up": [a[0], a[2], b[0], b[2]],
        "north": [16-b[0], 16-b[1], 16-a[0], 16-a[1]],
        "south": [a[0], 16-b[1], b[0], 16-a[1]],
        "west": [a[2], 16-b[1], b[2], 16-a[1]],
        "east": [16-b[2], 16-b[1], 16-a[2], 16-a[1]]}[face]


class Assets:
    def __init__(self, jar_path: Path):
        self.jar = zipfile.ZipFile(jar_path)
        self.textures: list[np.ndarray] = []
        self.texture_ids: dict[str, int] = {}
        self.warnings: set[str] = set()

    @lru_cache(maxsize=None)
    def model(self, name: str) -> dict:
        namespace, _, path = name.partition(":")
        if not path:
            namespace, path = "minecraft", namespace
        raw = json.loads(self.jar.read(f"assets/{namespace}/models/{path}.json"))
        if "parent" not in raw or raw["parent"].startswith("builtin/"):
            return raw
        parent = self.model(raw["parent"])
        return {**parent, **raw, "textures": {**parent.get("textures", {}), **raw.get("textures", {})}}

    def texture(self, reference: str, mapping: dict, tint: bool = False) -> int:
        seen = set()
        while reference.startswith("#"):
            if reference in seen:
                reference = "minecraft:block/stone"
                break
            seen.add(reference)
            reference = mapping.get(reference[1:], "minecraft:block/stone")
        key = reference + (":tinted" if tint else "")
        if key in self.texture_ids:
            return self.texture_ids[key]
        namespace, _, path = reference.partition(":")
        if not path:
            namespace, path = "minecraft", namespace
        try:
            image = Image.open(io.BytesIO(self.jar.read(f"assets/{namespace}/textures/{path}.png"))).convert("RGBA")
        except KeyError:
            self.warnings.add(f"missing_texture:{reference}")
            image = Image.new("RGBA", (16, 16), (183, 174, 157, 255))
        if image.height > image.width:  # Use first animation frame deterministically.
            image = image.crop((0, 0, image.width, image.width))
        pixels = np.array(image)
        if tint:
            pixels[:, :, :3] = pixels[:, :, :3].astype(float) * np.array([0.48, 0.72, 0.35])
        idx = len(self.textures)
        self.texture_ids[key] = idx
        self.textures.append(pixels)
        return idx

    @lru_cache(maxsize=None)
    def faces(self, state: str) -> tuple[list[dict], bool]:
        name, props = _state_parts(state)
        if name in AIR_BLOCKS:
            return [], False
        namespace, block = name.split(":", 1)
        try:
            blockstate = json.loads(self.jar.read(f"assets/{namespace}/blockstates/{block}.json"))
        except KeyError:
            self.warnings.add(f"missing_blockstate:{name}")
            blockstate = {"variants": {"": {"model": "minecraft:block/stone"}}}
        applications = []
        if "variants" in blockstate:
            for key, value in blockstate["variants"].items():
                requested = dict(item.split("=", 1) for item in key.split(",") if "=" in item)
                if _condition(requested, props):
                    applications.append(value[0] if isinstance(value, list) else value)
                    break
        for part in blockstate.get("multipart", []):
            if _condition(part.get("when", {}), props):
                value = part["apply"]
                applications.append(value[0] if isinstance(value, list) else value)
        if not applications:
            self.warnings.add(f"unmatched_blockstate:{state}")
        result = []
        full_cube = False
        for application in applications:
            try:
                model = self.model(application["model"])
            except KeyError:
                self.warnings.add(f"missing_model:{application['model']}")
                continue
            model_rotation = _rotation("y", -application.get("y", 0)) @ _rotation("x", -application.get("x", 0))
            mapping = model.get("textures", {})
            for element in model.get("elements", []):
                lo = np.array(element["from"], dtype=np.float32) / 16
                hi = np.array(element["to"], dtype=np.float32) / 16
                element_rotation = element.get("rotation")
                if not element_rotation and np.allclose(lo, 0) and np.allclose(hi, 1) and len(element.get("faces", {})) == 6:
                    full_cube = True
                for direction, face in element.get("faces", {}).items():
                    points = _face_vertices(direction, lo, hi)
                    normal = np.asarray(NORMALS[direction], dtype=np.float32)
                    if element_rotation:
                        rotation = _rotation(element_rotation["axis"], element_rotation["angle"])
                        origin = np.asarray(element_rotation["origin"], dtype=np.float32) / 16
                        points = (points - origin) @ rotation.T
                        if element_rotation.get("rescale"):
                            scale = np.ones(3)
                            scale[[axis for axis in range(3) if "xyz"[axis] != element_rotation["axis"]]] /= math.cos(math.radians(element_rotation["angle"]))
                            points *= scale
                        points += origin
                        normal = rotation @ normal
                    points = (points - 0.5) @ model_rotation.T + 0.5
                    normal = model_rotation @ normal
                    cull = model_rotation @ np.array(NORMALS[face["cullface"]], dtype=np.float32) if "cullface" in face else None
                    u0, v0, u1, v1 = face.get("uv", _default_uv(direction, lo, hi))
                    uv = np.array([[u0,v0],[u1,v0],[u1,v1],[u0,v1]], dtype=np.float32) / 16
                    uv = np.roll(uv, -(face.get("rotation", 0) // 90), axis=0)
                    texture = self.texture(face["texture"], mapping, "tintindex" in face)
                    if np.any(self.textures[texture][:, :, 3] < 255):
                        full_cube = False
                    result.append({"points": points, "normal": normal, "cull": cull, "uv": uv, "texture": texture})
        return result, full_cube


def _mesh(schematic, assets: Assets) -> dict:
    models = [assets.faces(state) for state in schematic.id_to_state]
    opaque_lookup = np.array([model[1] for model in models], dtype=bool)
    opaque = opaque_lookup[schematic.volume]
    groups = {"points": [], "normal": [], "uv": [], "texture": []}
    height, length, width = schematic.volume.shape
    for index, (faces, _) in enumerate(models):
        if not faces:
            continue
        yzxs = np.argwhere(schematic.volume == index)
        xyzs = yzxs[:, [2, 0, 1]]
        for face in faces:
            locations = xyzs
            if face["cull"] is not None:
                direction = np.rint(face["cull"]).astype(int)
                neighbors = xyzs + direction
                valid = (neighbors[:, 0] >= 0) & (neighbors[:, 0] < width) & (neighbors[:, 1] >= 0) & (neighbors[:, 1] < height) & (neighbors[:, 2] >= 0) & (neighbors[:, 2] < length)
                hidden = np.zeros(len(xyzs), dtype=bool)
                n = neighbors[valid]
                hidden[valid] = opaque[n[:, 1], n[:, 2], n[:, 0]]
                locations = xyzs[~hidden]
            if not len(locations):
                continue
            count = len(locations)
            groups["points"].append(face["points"][None] + locations[:, None])
            groups["normal"].append(np.broadcast_to(face["normal"], (count, 3)))
            groups["uv"].append(np.broadcast_to(face["uv"], (count, 4, 2)))
            groups["texture"].append(np.full(count, face["texture"], dtype=np.int32))
    if not groups["points"]:
        raise ValueError("No renderable block model faces")
    return {key: np.concatenate(value) for key, value in groups.items()}


def _font(size: int):
    """Latin label font; the CJK system fonts are unsafe on Windows (see .fonts)."""
    from .fonts import load_font
    return load_font(size)


def _render(mesh: dict, assets: Assets, direction: tuple, title: str, target: Path, max_size: int = 1400) -> dict:
    camera = np.array(direction, dtype=np.float32)
    camera /= np.linalg.norm(camera)
    up_hint = np.array([0, 1, 0] if abs(camera[1]) < 0.99 else [0, 0, -1], dtype=np.float32)
    right = np.cross(up_hint, camera)
    right /= np.linalg.norm(right)
    up = np.cross(camera, right)
    view = np.stack([right, -up, camera])
    visible = mesh["normal"] @ camera > 0.00001
    points = mesh["points"][visible] @ view.T
    normals = mesh["normal"][visible]
    textures = mesh["texture"][visible]
    uvs = mesh["uv"][visible]
    lo, hi = points[:, :, :2].min(axis=(0, 1)), points[:, :, :2].max(axis=(0, 1))
    scale = (max_size - 100) / max(hi - lo)
    canvas_w, canvas_h = np.ceil((hi - lo) * scale + [100, 130]).astype(int)
    projected = points.copy()
    projected[:, :, :2] = (points[:, :, :2] - lo) * scale + [50, 75]
    background = np.array([229, 235, 239], dtype=np.uint8)
    rgb = np.broadcast_to(background, (canvas_h, canvas_w, 3)).copy()
    depth = np.full((canvas_h, canvas_w), -np.inf, dtype=np.float32)
    # Back-to-front improves the simplified alpha compositing used for glass.
    order = np.argsort(projected[:, :, 2].mean(axis=1))
    light = np.array([-0.45, 0.85, -0.5], dtype=np.float32)
    light /= np.linalg.norm(light)
    shades = 0.69 + 0.31 * np.maximum(normals @ light, 0)
    for i in order:
        polygon = projected[i]
        minimum = np.maximum(np.floor(polygon[:, :2].min(axis=0)).astype(int), [0, 0])
        maximum = np.minimum(np.ceil(polygon[:, :2].max(axis=0)).astype(int), [canvas_w - 1, canvas_h - 1])
        x0, y0 = minimum
        x1, y1 = maximum
        if x1 < x0 or y1 < y0:
            continue
        origin, a, b = polygon[0], polygon[1] - polygon[0], polygon[3] - polygon[0]
        determinant = a[0] * b[1] - a[1] * b[0]
        if abs(determinant) < 0.000001:
            continue
        xx = np.arange(x0, x1 + 1, dtype=np.float32)[None, :] + 0.5 - origin[0]
        yy = np.arange(y0, y1 + 1, dtype=np.float32)[:, None] + 0.5 - origin[1]
        s = (xx * b[1] - yy * b[0]) / determinant
        t = (yy * a[0] - xx * a[1]) / determinant
        inside = (s >= -0.00001) & (s <= 1.00001) & (t >= -0.00001) & (t <= 1.00001)
        zz = origin[2] + a[2] * s + b[2] * t
        depth_part = depth[y0:y1 + 1, x0:x1 + 1]
        inside &= zz >= depth_part - 0.00001
        if not inside.any():
            continue
        uv = uvs[i]
        uu = uv[0, 0] + (uv[1, 0] - uv[0, 0]) * s + (uv[3, 0] - uv[0, 0]) * t
        vv = uv[0, 1] + (uv[1, 1] - uv[0, 1]) * s + (uv[3, 1] - uv[0, 1]) * t
        texture = assets.textures[int(textures[i])]
        tx = np.clip((uu * texture.shape[1]).astype(int), 0, texture.shape[1] - 1)
        ty = np.clip((vv * texture.shape[0]).astype(int), 0, texture.shape[0] - 1)
        samples = texture[ty, tx]
        inside &= samples[:, :, 3] > 5
        if not inside.any():
            continue
        color = samples[:, :, :3].astype(np.float32) * shades[i]
        alpha = samples[:, :, 3:4].astype(np.float32) / 255
        rgb_part = rgb[y0:y1 + 1, x0:x1 + 1]
        rgb_part[inside] = np.clip((color * alpha + rgb_part * (1 - alpha))[inside], 0, 255).astype(np.uint8)
        depth_part[inside] = zz[inside]
    result = Image.fromarray(rgb)
    draw = ImageDraw.Draw(result)
    draw.text((24, 16), title, font=_font(22), fill=(36, 46, 53))
    draw.text((24, result.height - 25), f"Minecraft {VERSION} assets | software model preview | no shaders", font=_font(12), fill=(80, 90, 98))
    result.save(target, optimize=True)
    return {"path": str(target.resolve()), "size": list(result.size), "visible_model_faces": int(len(order))}


def render_previews(schem_path: Path, out_dir: Path, *, cache_dir: Path = DEFAULT_CACHE, max_size: int = 1400,
                    orbit: bool = False) -> dict:
    """Render north/front, south/back, both sides, top and two axonometric PNGs.

    Axonometric views use an orthographic camera so lengths remain comparable;
    they are deliberately labelled axonometric rather than perspective. Front is
    z_min. Returns absolute paths including overview and provenance metadata.
    """
    started = time.monotonic()
    schem_path, out_dir = Path(schem_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    schematic = load_schematic(schem_path)
    jar_path = ensure_assets(cache_dir)
    assets = Assets(jar_path)
    mesh = _mesh(schematic, assets)
    print(f"Model preview: {len(mesh['points']):,} exposed faces, {len(assets.textures)} textures", flush=True)
    definitions = [("axonometric_front", (1.3, 0.8, -2.2), "Front axonometric / true block models"),
                   ("front", (0, 0, -1), "Front / north / z_min"),
                   ("back", (0, 0, 1), "Back / south / z_max"),
                   ("left", (-1, 0, 0), "Left / west / x_min"),
                   ("right", (1, 0, 0), "Right / east / x_max"),
                   ("top", (0, 1, 0), "Roof / top"),
                   ("axonometric_back", (-1.3, 0.85, 2.2), "Rear axonometric / true block models")]
    if orbit:
        for elevation, rise in (("street", .18), ("high", .85)):
            for degrees in range(0, 360, 45):
                angle = math.radians(degrees)
                definitions.append((f"orbit_{elevation}_{degrees:03d}",
                    (math.sin(angle), rise, -math.cos(angle)),
                    f"{elevation} orbit {degrees} deg / true block models"))
    paths, stats = {}, {}
    for name, camera, label in definitions:
        target = out_dir / f"{name}.png"
        stats[name] = _render(mesh, assets, camera, label, target, max_size)
        paths[name] = str(target.resolve())
        print(f"Rendered {name}: {target.name}", flush=True)
    cell_w, cell_h = 900, 730
    sheet = Image.new("RGB", (cell_w * 2, cell_h * 2), (229, 235, 239))
    for i, name in enumerate(("axonometric_front", "front", "axonometric_back", "top")):
        image = Image.open(paths[name]).convert("RGB")
        image.thumbnail((cell_w - 16, cell_h - 16), Image.Resampling.LANCZOS)
        sheet.paste(image, ((i % 2) * cell_w + (cell_w - image.width) // 2, (i // 2) * cell_h + (cell_h - image.height) // 2))
    overview = out_dir / "overview.png"
    sheet.save(overview, optimize=True)
    paths["overview"] = str(overview.resolve())
    if orbit:
        orbit_sheet = Image.new("RGB", (2400, 1600), (229, 235, 239))
        for i, name in enumerate(name for name, _, _ in definitions if name.startswith("orbit_")):
            tile = Image.open(paths[name]).convert("RGB")
            tile.thumbnail((590, 385), Image.Resampling.LANCZOS)
            orbit_sheet.paste(tile, ((i % 4)*600+(600-tile.width)//2, (i//4)*400+(400-tile.height)//2))
        orbit_path = out_dir / "orbit_contact_sheet.png"
        orbit_sheet.save(orbit_path)
        paths["orbit_contact_sheet"] = str(orbit_path.resolve())
    paths["hero"] = paths["axonometric_front"]
    metadata = {"renderer": "paris_builder.preview3d", "minecraft_version": VERSION,
        "source_schematic": str(schem_path.resolve()), "source_sha256": hashlib.sha256(schem_path.read_bytes()).hexdigest(),
        "texture_source": json.loads((cache_dir / "provenance.json").read_text(encoding="utf-8")),
        "geometry": "Official Mojang block models selected through blockstates, including multipart and rotations",
        "front_direction": "north / z_min", "projection": "orthographic and axonometric (not perspective)",
        "limitations": ["No game shaders, ambient occlusion, shadow maps or biome-specific light",
            "Glass uses simplified alpha compositing", "UV-lock is not simulated",
            "First model variant and first animated texture frame chosen deterministically",
            "Block entities and entities are not rendered; modded blocks use stone fallback"],
        "warnings": sorted(assets.warnings), "exposed_model_faces": len(mesh["points"]),
        "views": stats, "elapsed_seconds": round(time.monotonic() - started, 2)}
    metadata_path = out_dir / "render_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["metadata"] = str(metadata_path.resolve())
    assets.jar.close()
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schematic", type=Path, nargs="?")
    parser.add_argument("--out", type=Path, default=Path("previews/generated"))
    parser.add_argument("--max-size", type=int, default=1400)
    parser.add_argument("--fetch-assets", action="store_true")
    args = parser.parse_args()
    if args.fetch_assets:
        print(ensure_assets())
    if args.schematic:
        print(json.dumps(render_previews(args.schematic, args.out, max_size=args.max_size), indent=2))


if __name__ == "__main__":
    main()
