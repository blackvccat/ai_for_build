"""TECHNIQUE-ATLAS step 1: all-source technique census (measure + render, no decomposition).

Scans every .schem in the four source groups (巴黎建筑素材, 巴黎建筑修改版, 窗,
_incoming_schematics), deduplicates by SHA-256, and for each source records:
dimensions, DataVersion, non-air count, distinct state count, a per-layer vertical
material profile, the four vertical side surfaces (street-face guess), corner
analysis (adjacent street faces / 45-degree chamfer / rounded corner), debug-stick
state fingerprints (door halves, stair shapes, wall up=false, pane connections,
trapdoors) and a first roof-type guess (mansard / flat / gable / other).

Building-level canonical sources are rendered to seven views with preview3d.
Window components are measured but not rendered. Idempotent: re-running reuses
completed renders whose render_metadata.json matches the source SHA-256.

    cd paris-builder
    PYTHONPATH=src python -X utf8 tools/atlas_survey.py [--skip-render]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from paris_builder.schematic import AIR_BLOCKS, base_block, load_schematic  # noqa: E402

BUILDER_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BUILDER_ROOT.parent

#: Scan order doubles as dedup priority: earlier groups are the canonical copies.
SOURCE_GROUPS = [
    PROJECT_ROOT / "巴黎建筑素材",
    PROJECT_ROOT / "巴黎建筑修改版",
    PROJECT_ROOT / "窗",
    PROJECT_ROOT / "_incoming_schematics",
]

VIEW_NAMES = ("front", "back", "left", "right", "top",
              "axonometric_front", "axonometric_back")

#: An envelope at or below this in every axis is a component, not a building.
COMPONENT_MAX = 8

#: Form-class labels for the 14 named sources, from reports/SOURCE_FORM_TYPOLOGY.md
#: (read off runs/SOURCE-FORMS-SHEET.png there; reused here, not re-derived).
KNOWN_FORM_CLASS = {
    "巴黎建筑素材1": "A 市政/纪念性",
    "巴黎建筑素材2": "C 转角公寓",
    "巴黎建筑素材3": "A/B 市政或府邸",
    "巴黎建筑素材4": "B 府邸",
    "巴黎建筑素材5": "A 市政/纪念性",
    "巴黎建筑素材6": "B 府邸",
    "巴黎建筑素材7": "A 市政/纪念性",
    "巴黎民居街区1": "C 转角公寓",
    "巴黎民居街区2": "D 连续街墙",
    "巴黎民居街区3": "D 连续街墙",
    "巴黎民居街区4[斜面建筑]": "E 坡地/斜面",
    "巴黎民居街区5": "E 长排店面",
    "巴黎民居街区6": "E 窄面深进深",
    "巴黎民居街区7": "D 连续街墙",
}

#: Dark blocks whose share rising in the top layers is the mansard signal.
DARK_HINTS = ("gray", "black", "dark_", "deepslate", "blackstone", "basalt",
              "prismarine", "obsidian", "_coal_", "slate")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_sources() -> list:
    files = []
    for group_root in SOURCE_GROUPS:
        if not group_root.is_dir():
            continue
        for path in sorted(group_root.rglob("*.schem"),
                           key=lambda p: str(p.relative_to(PROJECT_ROOT))):
            files.append(path)
    return files


def group_of(path: Path) -> str:
    return str(path.parent.relative_to(PROJECT_ROOT)).replace(os.sep, "/")


def source_kind(path: Path, width: int, height: int, length: int) -> str:
    parts = path.relative_to(PROJECT_ROOT).parts
    if any(part.startswith("窗") for part in parts[:-1]) or path.stem.startswith("窗"):
        return "component"
    if max(width, height, length) <= COMPONENT_MAX:
        return "component"
    return "building"


# ---------------------------------------------------------------- vertical profile

def vertical_profile(data, nonair) -> tuple:
    """Per-y non-air count and top-3 states, plus simple segmentation hints."""
    lut = np.asarray(data.id_to_state, dtype=object)
    layers = []
    top1_runs = []
    height = nonair.shape[0]
    for y in range(height):
        ids = data.volume[y][nonair[y]]
        if not len(ids):
            layers.append({"y": y, "nonair": 0, "top3": []})
            continue
        states, counts = np.unique(lut[ids], return_counts=True)
        order = np.argsort(-counts)[:3]
        top3 = [[str(states[i]), int(counts[i])] for i in order]
        layers.append({"y": y, "nonair": int(counts.sum()), "top3": top3})
        top1_runs.append((y, base_block(top3[0][0])))
    boundaries = []
    prev = None
    run = 0
    for y, block in top1_runs:
        if block != prev:
            if prev is not None and run >= 2:
                boundaries.append(y)
            prev = block
            run = 1
        else:
            run += 1
    occupied = [row["nonair"] for row in layers if row["nonair"] > 0]
    return layers, {
        "material_boundaries_y": boundaries,
        "occupied_layers": len(occupied),
        "max_layer_nonair": max(occupied) if occupied else 0,
        "median_layer_nonair": float(np.median(occupied)) if occupied else 0.0,
    }


# ------------------------------------------------------------------- side surfaces

def _side_states(data, nonair, axis, side):
    """States of the first/last non-air block along `axis` for every occupied column."""
    n = nonair.shape[axis]
    if side == "first":
        idx = nonair.argmax(axis=axis)
    else:
        idx = n - 1 - np.flip(nonair, axis=axis).argmax(axis=axis)
    occupied = nonair.any(axis=axis)
    if not occupied.any():
        return []
    a, b = np.nonzero(occupied)
    if axis == 2:  # x axis; occupied has shape (y, z)
        vox = data.volume[a, b, idx[a, b]]
    else:  # axis == 1, z axis; occupied has shape (y, x)
        vox = data.volume[a, idx[a, b], b]
    lut = np.asarray(data.id_to_state, dtype=object)
    return [str(s) for s in lut[vox]]


def facade_surfaces(data, nonair) -> dict:
    faces = {}
    for key, axis, side in (("-x", 2, "first"), ("+x", 2, "last"),
                            ("-z", 1, "first"), ("+z", 1, "last")):
        states = _side_states(data, nonair, axis, side)
        counts = Counter(states)
        glass = sum(n for s, n in counts.items() if "glass" in s)
        stateful = sum(n for s, n in counts.items()
                       if any(h in base_block(s) for h in
                              ("stairs", "slab", "wall", "fence", "pane", "door",
                               "trapdoor", "bars", "gate", "lantern", "chain")))
        faces[key] = {
            "surface_cells": len(states),
            "distinct_states": len(counts),
            "glass_cells": int(glass),
            "stateful_cells": int(stateful),
            "top_states": [[s, n] for s, n in counts.most_common(5)],
        }
    return faces


def pick_street_face(faces: dict) -> dict:
    """Street face = the most state-rich vertical side; glass is the tiebreak."""
    ranked = sorted(faces.items(),
                    key=lambda kv: (kv[1]["distinct_states"], kv[1]["glass_cells"],
                                    kv[1]["surface_cells"]),
                    reverse=True)
    if not ranked or ranked[0][1]["distinct_states"] == 0:
        return {"primary": None, "uncertain": True, "note": "no non-air surface"}
    best_key, best = ranked[0]
    second_key, second = ranked[1]
    confidence = best["distinct_states"] / max(1, second["distinct_states"])
    best_score = max(1, best["distinct_states"])
    street_faces = [key for key, f in faces.items()
                    if f["distinct_states"] >= 0.55 * best_score
                    and f["distinct_states"] >= 12
                    and f["surface_cells"] >= 0.2 * max(1, best["surface_cells"])]
    uncertain = confidence < 1.25
    note = ""
    if len(street_faces) == 2 and set(street_faces) in ({"-x", "+x"}, {"-z", "+z"}):
        note = "两个相对面都丰富：双面贯通块，不是转角"
    return {
        "primary": best_key,
        "runner_up": second_key,
        "confidence": round(confidence, 3),
        "uncertain": bool(uncertain),
        "street_faces": sorted(street_faces),
        "note": note,
    }


# ------------------------------------------------------------------ corner analysis

def _corner_profile(sub):
    """sub: (u, v) occupancy near one corner, both axes pointing inward."""
    r = sub.shape[0]
    profile = {}
    for u in range(r):
        col = np.nonzero(sub[:, u])[0]
        if len(col):
            profile[u] = int(col.min())
    return profile


def analyze_corners(nonair) -> dict:
    """Look for cut or rounded corners on the mid-body footprint's tight bounds.

    Sources keep wide air/street margins, so the tight bounding box of the
    mid-height layers is used instead of the schematic envelope. At each tight
    corner the boundary profile v_min(u) is fitted: u+v constant means a 45
    degree chamfer (pan coupe), u^2+v^2 constant means a rounded corner.
    """
    height, length, width = nonair.shape
    layer_nonair = nonair.sum(axis=(1, 2))
    ys = np.nonzero(layer_nonair)[0]
    if not len(ys):
        return {"verdict": "not_applicable", "forms": [], "evidence": [], "details": {}}
    span = ys[-1] - ys[0] + 1
    y0 = ys[0] + max(1, int(0.10 * span))
    y1 = ys[0] + max(2, int(0.65 * span))
    if y1 <= y0:
        return {"verdict": "not_applicable", "forms": [], "evidence": [], "details": {}}
    mid = nonair[y0:y1].any(axis=0)  # footprint of the mid-body layers, (z, x)
    zs, xs = np.nonzero(mid)
    if not len(zs):
        return {"verdict": "not_applicable", "forms": [], "evidence": [], "details": {}}
    x_lo, x_hi = int(xs.min()), int(xs.max())
    z_lo, z_hi = int(zs.min()), int(zs.max())
    r = min(14, (x_hi - x_lo + 1) // 3, (z_hi - z_lo + 1) // 3)
    if r < 3:
        return {"verdict": "not_applicable", "forms": [], "evidence": [], "details": {}}

    forms, evidence, details = [], [], {}
    regions = (
        ("x_min/z_min", x_lo, z_lo, mid[z_lo:z_lo + r, x_lo:x_lo + r]),
        ("x_max/z_min", x_hi, z_lo, mid[z_lo:z_lo + r, x_hi - r + 1:x_hi + 1][:, ::-1]),
        ("x_min/z_max", x_lo, z_hi, mid[z_hi - r + 1:z_hi + 1, x_lo:x_lo + r][::-1, :]),
        ("x_max/z_max", x_hi, z_hi, mid[z_hi - r + 1:z_hi + 1, x_hi - r + 1:x_hi + 1][::-1, ::-1]),
    )
    for corner, cx, cz, sub in regions:
        # sub indexed (v, u), both axes pointing inward, (0, 0) at the tight corner
        corner_col_fill = float(nonair[y0:y1, cz, cx].mean())
        profile = _corner_profile(sub)
        info = {"corner_xyz": [cx, None, cz], "corner_col_fill": round(corner_col_fill, 3),
                "boundary_profile": profile}
        pts = [(u, v) for u, v in sorted(profile.items()) if u <= 12]
        if len(pts) >= 3:
            us = np.array([p[0] for p in pts], dtype=float)
            vs = np.array([p[1] for p in pts], dtype=float)
            corr = float(np.corrcoef(us, vs)[0, 1]) if vs.std() > 0 else 0.0
            diag_std = float((us + vs).std())
            circ_std = float((us * us + vs * vs).std())
            depth = float((us + vs).mean())
            info.update({"chamfer_residual": round(diag_std, 3),
                         "rounded_residual": round(circ_std, 3),
                         "descent_corr": round(corr, 3), "cut_depth": round(depth, 1)})
            if corner_col_fill < 0.3 and corr < -0.4 and depth >= 3:
                if diag_std <= 1.6:
                    forms.append("chamfer")
                    evidence.append(f"({cx},{cz}) {corner}: 45°切角, 斜面进深≈{depth:.0f}格 "
                                    f"(u+v 残差 {diag_std:.2f})")
                elif circ_std <= 4.0:
                    forms.append("rounded")
                    evidence.append(f"({cx},{cz}) {corner}: 圆弧转角候选, "
                                    f"半径²≈{(us * us + vs * vs).mean():.0f} "
                                    f"(残差 {circ_std:.2f})")
        details[corner] = info
    return {"verdict": "", "forms": sorted(set(forms)), "evidence": evidence,
            "details": details}


def corner_verdict(street: dict, corners: dict, kind: str) -> dict:
    if kind == "component" or corners["verdict"] == "not_applicable":
        corners["verdict"] = "not_applicable"
        return corners
    faces = set(street.get("street_faces") or [])
    adjacent = ({"-x", "-z"} <= faces or {"-x", "+z"} <= faces or
                {"+x", "-z"} <= faces or {"+x", "+z"} <= faces)
    forms = list(corners["forms"])
    evidence = list(corners["evidence"])
    cut = bool(forms)
    if cut:
        verdict = "yes"
        if len(faces) >= 2:
            evidence.append("另有 %d 个丰富临街面: %s" % (len(faces), "/".join(sorted(faces))))
    elif len(faces) == 2 and adjacent:
        forms.append("adjacent_street_faces")
        evidence.insert(0, "相邻两个临街面都丰富: " + "/".join(sorted(faces)))
        verdict = "yes"
    elif len(faces) == 2:
        verdict = "no"
        evidence.append("两个丰富面相对（双面贯通），不是转角: " + "/".join(sorted(faces)))
    elif len(faces) == 3:
        verdict = "uncertain"
        evidence.append("三个面丰富：可能转角+装饰背/侧面，需渲染图复核: "
                        + "/".join(sorted(faces)))
    elif len(faces) == 4:
        verdict = "uncertain"
        evidence.append("四面均等丰富：独立体量（市政/府邸）或整街坊，需渲染图复核")
    elif len(faces) == 1:
        verdict = "no"
    else:
        verdict = "uncertain"
        evidence.append("没有明显丰富的临街面，无法判定")
    corners.update({"verdict": verdict, "forms": sorted(set(forms)),
                    "evidence": evidence})
    return corners


# ---------------------------------------------------------------- state fingerprints

def state_fingerprints(counts: Counter) -> dict:
    doors = {}
    stairs = Counter()
    wall_up = Counter()
    pane_patterns = Counter()
    pane_post_only = 0
    trapdoors = Counter()
    for state, n in counts.items():
        block = base_block(state)
        props = {}
        if "[" in state:
            props = dict(p.split("=", 1) for p in
                         state.split("[", 1)[1].rstrip("]").split(",") if "=" in p)
        if block.endswith("_door"):
            name = block.split(":", 1)[-1]
            doors.setdefault(name, Counter())[props.get("half", "?")] += n
        if "stairs" in block:
            stairs[props.get("shape", "?")] += n
        if block.endswith("_wall") or block == "minecraft:cobblestone_wall":
            wall_up[props.get("up", "?")] += n
        if "_pane" in block:
            pattern = tuple(props.get(d, "?") for d in ("north", "east", "south", "west"))
            if pattern:
                pane_patterns["/".join(pattern)] += n
                if pattern == ("false", "false", "false", "false"):
                    pane_post_only += n
            else:
                pane_patterns["(no connection props)"] += n
        if block.endswith("_trapdoor"):
            trapdoors[f"half={props.get('half', '?')},open={props.get('open', '?')}"] += n
    return {
        "doors_by_half": {k: dict(v) for k, v in sorted(doors.items())},
        "stairs_by_shape": dict(stairs),
        "wall_up_counts": dict(wall_up),
        "pane_connection_patterns": dict(pane_patterns.most_common(12)),
        "pane_post_only": int(pane_post_only),
        "pane_total": int(sum(pane_patterns.values())),
        "trapdoor_states": dict(trapdoors),
        "trapdoor_total": int(sum(trapdoors.values())),
    }


def fingerprint_highlights(fp: dict) -> list:
    out = []
    iron = fp["doors_by_half"].get("iron_door", {})
    if iron:
        lower, upper = iron.get("lower", 0), iron.get("upper", 0)
        tag = "iron_door half lower×%d/upper×%d" % (lower, upper)
        if lower and not upper:
            tag += "（全 lower：薄窗面/双半门手法）"
        out.append(tag)
    for name, halves in sorted(fp["doors_by_half"].items()):
        if name == "iron_door":
            continue
        lower, upper = halves.get("lower", 0), halves.get("upper", 0)
        if lower != upper:
            out.append(f"{name} lower×{lower}/upper×{upper}（半门不配对）")
    stairs = fp["stairs_by_shape"]
    shaped = {k: v for k, v in stairs.items() if k != "straight" and v}
    if shaped:
        out.append("stairs " + " ".join(f"{k}×{v}" for k, v in sorted(shaped.items())))
    up_false = fp["wall_up_counts"].get("false", 0)
    if up_false:
        out.append(f"wall up=false×{up_false}")
    if fp["pane_total"]:
        patterns = fp["pane_connection_patterns"]
        singles = sum(n for p, n in patterns.items()
                      if p.count("true") == 1)
        out.append(f"pane 连接模式 {len(patterns)} 种"
                   + (f"，单连接×{singles}" if singles else "")
                   + (f"，无连接立柱×{fp['pane_post_only']}" if fp["pane_post_only"] else ""))
    if fp["trapdoor_total"]:
        out.append(f"trapdoor×{fp['trapdoor_total']}")
    return out


# ----------------------------------------------------------------------- roof guess

def roof_guess(data, nonair, layers) -> dict:
    layer_nonair = np.array([row["nonair"] for row in layers], dtype=float)
    ys = np.nonzero(layer_nonair)[0]
    if not len(ys):
        return {"type": "unknown", "evidence": {}}
    y_lo, y_hi = int(ys[0]), int(ys[-1])
    span = y_hi - y_lo + 1
    mid = layer_nonair[y_lo + span // 4: y_lo + 3 * span // 4]
    body_median = float(np.median(mid)) if len(mid) else float(layer_nonair.max())
    roof_start = None
    for y in range(y_hi, y_lo - 1, -1):
        if layer_nonair[y] < 0.6 * body_median:
            roof_start = y
        else:
            break
    evidence = {"y_hi": y_hi, "body_median_layer_nonair": round(body_median, 1),
                "top_layer_coverage": round(float(layer_nonair[y_hi] / max(1, body_median)), 3)}
    if roof_start is None or y_hi - roof_start + 1 <= 2:
        evidence["note"] = "顶部质量没有明显退缩"
        roof_type = "flat" if layer_nonair[y_hi] >= 0.5 * body_median else "other"
        return {"type": roof_type, "evidence": evidence}
    roof_h = y_hi - roof_start + 1
    lut = np.asarray(data.id_to_state, dtype=object)
    roof_ids = data.volume[roof_start:y_hi + 1][nonair[roof_start:y_hi + 1]]
    states = [str(s) for s in lut[roof_ids]]
    counts = Counter(states)
    total = max(1, len(states))
    dark = sum(n for s, n in counts.items()
               if any(h in base_block(s) for h in DARK_HINTS))
    stairs_slabs = sum(n for s, n in counts.items()
                       if "stairs" in s or "slab" in s)
    glass = sum(n for s, n in counts.items() if "glass" in s)
    coverages = layer_nonair[roof_start:y_hi + 1]
    shrink = [round(float(c / max(1, coverages[0])), 2) for c in coverages]
    evidence.update({
        "roof_start_y": roof_start, "roof_height": roof_h,
        "dark_fraction": round(dark / total, 3),
        "stairs_slab_fraction": round(stairs_slabs / total, 3),
        "glass_in_roof": int(glass),
        "coverage_shrink": shrink[:20],
        "top_roof_blocks": [[s, n] for s, n in counts.most_common(5)],
    })
    dark_frac = dark / total
    if roof_h >= 4 and dark_frac >= 0.3 and stairs_slabs / total >= 0.1:
        roof_type = "mansard"
        if glass >= 20:
            evidence["dormers"] = "屋顶区玻璃 %d 格，疑似老虎窗" % glass
    elif roof_h >= 2 and dark_frac >= 0.55 and stairs_slabs / total >= 0.25:
        # 深色陡坡薄壳盖在实心主体上：层数少但材料指纹就是芒萨尔坡
        roof_type = "mansard"
        evidence["thin_shell"] = "深色陡坡薄壳（实心主体之上的芒萨尔坡）"
        if glass >= 20:
            evidence["dormers"] = "屋顶区玻璃 %d 格，疑似老虎窗" % glass
    elif roof_h >= 3 and len(coverages) >= 3:
        # 允许个别层小幅回升（装饰带/退台），整体单调退缩即坡屋顶
        raw = coverages
        rises = np.diff(raw) / max(1.0, raw[0])
        roof_type = "gable" if (raw[-1] <= 0.35 * raw[0] and rises.max() <= 0.12) else "other"
    else:
        roof_type = "other"
    return {"type": roof_type, "evidence": evidence}


# ------------------------------------------------------------------------- measure

def measure(path: Path) -> dict:
    started = time.monotonic()
    data = load_schematic(path)
    nonair = data.nonair_mask()
    counts = Counter({s: n for s, n in data.exact_state_counts().items()
                      if base_block(s) not in AIR_BLOCKS})
    layers, segmentation = vertical_profile(data, nonair)
    faces = facade_surfaces(data, nonair)
    street = pick_street_face(faces)
    kind = source_kind(path, data.width, data.height, data.length)
    corners = corner_verdict(street, analyze_corners(nonair), kind)
    fp = state_fingerprints(counts)
    roof = roof_guess(data, nonair, layers)
    return {
        "name": path.stem,
        "file": str(path.relative_to(PROJECT_ROOT)).replace(os.sep, "/"),
        "group": group_of(path),
        "sha256": sha256_file(path),
        "duplicate_of": None,
        "size_whd": [data.width, data.height, data.length],
        "data_version": data.data_version,
        "schematic_version": data.version,
        "nonair": int(nonair.sum()),
        "fill_ratio": round(float(nonair.sum()) / max(1, nonair.size), 4),
        "distinct_states": len(counts),
        "kind": kind,
        "form_class": KNOWN_FORM_CLASS.get(path.stem),
        "vertical_profile": layers,
        "vertical_segmentation": segmentation,
        "facades": faces,
        "street_face": street,
        "corner": corners,
        "state_fingerprints": fp,
        "fingerprint_highlights": fingerprint_highlights(fp),
        "roof": roof,
        "measure_seconds": round(time.monotonic() - started, 2),
    }


# -------------------------------------------------------------------------- render

def render_done(out_dir: Path, sha: str) -> bool:
    meta_path = out_dir / "render_metadata.json"
    if not meta_path.is_file():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if meta.get("source_sha256") != sha:
        return False
    return all((out_dir / f"{name}.png").is_file() for name in VIEW_NAMES)


def render_one(schem_path: Path, out_dir: Path, timeout: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-X", "utf8", "-m", "paris_builder.preview3d",
           str(schem_path), "--out", str(out_dir)]
    env = dict(os.environ, PYTHONPATH=str(BUILDER_ROOT / "src"),
               PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        proc = subprocess.run(cmd, cwd=BUILDER_ROOT, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "failed", "error": f"timeout after {timeout}s"}
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
        return {"status": "failed", "error": " | ".join(tail)}
    if not all((out_dir / f"{name}.png").is_file() for name in VIEW_NAMES):
        return {"status": "failed", "error": "exit 0 but view png missing"}
    return {"status": "ok"}


# ------------------------------------------------------------------------ SURVEY.md

def build_survey_md(entries: list, out_root: Path, stats: dict) -> str:
    lines = []
    add = lines.append
    add("# TECHNIQUE-ATLAS v0.1 — 全源手法普查（第①步：测量与渲染，不做拆解）")
    add("")
    add(f"- 扫描文件总数：**{stats['total_files']}**；SHA-256 去重后独立源：**{stats['unique']}**"
        f"（重复 {stats['duplicates']}）")
    add(f"- 建筑级独立源：{stats['buildings']}；窗/构件级：{stats['components']}")
    add(f"- 渲染：成功 {stats['render_ok']}，跳过（重复/构件）{stats['render_skipped']}，"
        f"失败 {stats['render_failed']}")
    add(f"- 数据：`source_inventory.json`；渲染：`previews/<组名>/<名字>/`（7 视角 + overview）")
    add("- 判定口径：街面 = 四个竖直侧面中状态丰富度最高者；转角 = 相邻两临街面都丰富，"
        "或检测到 45° 切角/圆弧；屋顶初判依据 y 剖面退缩与深色方块占比。")
    add("")

    def fmt_dims(e):
        w, h, d = e["size_whd"]
        return f"{w}×{h}×{d}"

    def corner_short(e):
        c = e["corner"]
        if c["verdict"] == "not_applicable":
            return "—"
        forms = {"chamfer": "切角", "rounded": "圆弧",
                 "adjacent_street_faces": "双临街面"}
        label = {"yes": "yes", "no": "no", "uncertain": "不确定"}[c["verdict"]]
        tags = [forms.get(f, f) for f in c["forms"]]
        return label + ("（" + "+".join(tags) + "）" if tags else "")

    def roof_short(e):
        r = e["roof"]
        names = {"mansard": "芒萨尔", "flat": "平顶", "gable": "双坡",
                 "other": "其他", "unknown": "?"}
        extra = "，有老虎窗迹象" if r["evidence"].get("dormers") else ""
        return names.get(r["type"], r["type"]) + extra

    def fp_short(e):
        return "；".join(e["fingerprint_highlights"][:3]) or "—"

    buildings = [e for e in entries if e.get("kind") == "building" and not e.get("duplicate_of")]
    components = [e for e in entries if e.get("kind") == "component"]
    dups = [e for e in entries if e.get("duplicate_of")]

    add("## 每源一行（建筑级，去重后）")
    add("")
    add("| 源 | 组 | 尺寸 W×H×D | 非空气 | 状态数 | 形态类(初判) | 转角 | 街面 | 屋顶初判 | 状态手法指纹亮点 |")
    add("|---|---|---|---|---|---|---|---|---|---|")
    for e in buildings:
        form = e["form_class"] or infer_form_class(e)
        street = e["street_face"]
        face = (street.get("primary") or "?") + ("(?)" if street.get("uncertain") else "")
        add("| %s | %s | %s | %d | %d | %s | %s | %s | %s | %s |" % (
            e["name"], e["group"], fmt_dims(e), e["nonair"], e["distinct_states"],
            form, corner_short(e), face, roof_short(e), fp_short(e)))
    add("")

    add("## 窗/构件级（测量，不渲染）")
    add("")
    add("| 源 | 组 | 尺寸 W×H×D | 非空气 | 状态数 | 指纹亮点 |")
    add("|---|---|---|---|---|---|")
    for e in components:
        add("| %s | %s | %s | %d | %d | %s |" % (
            e["name"], e["group"], fmt_dims(e), e["nonair"], e["distinct_states"],
            fp_short(e)))
    add("")

    add("## 转角判定汇总（转角楼清单）")
    add("")
    corner_yes = [e for e in buildings if e["corner"]["verdict"] == "yes"]
    corner_unc = [e for e in buildings if e["corner"]["verdict"] == "uncertain"]
    strong = [e for e in corner_yes
              if "adjacent_street_faces" in e["corner"]["forms"]
              and ("chamfer" in e["corner"]["forms"] or "rounded" in e["corner"]["forms"])]
    cut_only = [e for e in corner_yes
                if "adjacent_street_faces" not in e["corner"]["forms"]]
    face_only = [e for e in corner_yes
                 if e["corner"]["forms"] == ["adjacent_street_faces"]]
    if strong:
        add("**双临街面 + 切角/圆弧（转角楼证据最强）：**")
        for e in strong:
            add(f"- **{e['name']}**（{e['group']}）：" + "；".join(e["corner"]["evidence"]))
        add("")
    if cut_only:
        add("**实测到 45°切角/圆弧（附坐标与进深；另有多个丰富临街面者转角地块证据更强）：**")
        for e in cut_only:
            add(f"- **{e['name']}**（{e['group']}）：" + "；".join(e["corner"]["evidence"]))
        add("")
    if face_only:
        add("**相邻双临街面（无切角）：**")
        for e in face_only:
            add(f"- **{e['name']}**（{e['group']}）：" + "；".join(e["corner"]["evidence"]))
        add("")
    if not corner_yes:
        add("- 无")
    if corner_unc:
        add("**转角不确定（需渲染图复核）：**")
        for e in corner_unc:
            note = e["corner"]["evidence"][0] if e["corner"]["evidence"] else ""
            add(f"- {e['name']}（{e['group']}）：{note}")
    add("")

    add("## 街面方向判定存疑（confidence < 1.25）")
    add("")
    unsure = [e for e in buildings if e["street_face"].get("uncertain")]
    if unsure:
        add("| 源 | 首选 | 次选 | confidence | 说明 |")
        add("|---|---|---|---|---|")
        for e in unsure:
            s = e["street_face"]
            add("| %s | %s | %s | %.2f | %s |" % (
                e["name"], s.get("primary"), s.get("runner_up"),
                s.get("confidence", 0.0), s.get("note") or "两面丰富度接近"))
    else:
        add("无")
    add("")

    add("## 渲染失败列表")
    add("")
    failed = [e for e in entries
              if (e.get("render") or {}).get("status") == "failed"]
    if failed:
        for e in failed:
            add(f"- {e['name']}（{e['group']}）：{e['render'].get('error', '')[:300]}")
    else:
        add("无")
    add("")

    add("## SHA-256 去重清单（未纳入独立测量/渲染的重复件）")
    add("")
    if dups:
        add("| 重复件 | 组 | 等同于 |")
        add("|---|---|---|")
        for e in dups:
            add("| %s | %s | %s |" % (e["name"], e["group"], e["duplicate_of"]))
    else:
        add("无重复")
    add("")
    return "\n".join(lines)


def infer_form_class(e) -> str:
    c = e["corner"]
    street = e["street_face"]
    w, h, d = e["size_whd"]
    if c["verdict"] == "yes":
        return "C 转角（按测量推断）"
    faces = street.get("street_faces") or []
    if len(faces) == 1 and max(w, d) / max(1, min(w, d)) >= 2.5:
        return "D 街墙（按测量推断）"
    if h <= 25:
        return "极简单栋（未归入 5 类）"
    return "单栋（未归入 5 类）"


# ----------------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-render", action="store_true",
                        help="只测量与写报告，不渲染")
    parser.add_argument("--out", type=Path,
                        default=BUILDER_ROOT / "runs" / "TECHNIQUE-ATLAS-v0.1")
    parser.add_argument("--render-timeout", type=int, default=2400)
    parser.add_argument("--only", type=str, default=None,
                        help="只处理文件名包含该子串的源（调试用）")
    args = parser.parse_args()

    out_root: Path = args.out
    out_root.mkdir(parents=True, exist_ok=True)

    files = collect_sources()
    if args.only:
        files = [p for p in files if args.only in p.stem]
    print(f"[atlas] {len(files)} 个 .schem 待处理", flush=True)

    entries = []
    by_sha = {}
    for i, path in enumerate(files, 1):
        sha = sha256_file(path)
        if sha in by_sha:
            entries.append({
                "name": path.stem,
                "file": str(path.relative_to(PROJECT_ROOT)).replace(os.sep, "/"),
                "group": group_of(path),
                "sha256": sha,
                "duplicate_of": by_sha[sha],
                "kind": None,
                "render": {"status": "skipped_duplicate"},
            })
            print(f"[{i}/{len(files)}] 重复（={by_sha[sha]}）：{path.stem}", flush=True)
            continue
        by_sha[sha] = str(path.relative_to(PROJECT_ROOT)).replace(os.sep, "/")
        try:
            entry = measure(path)
        except Exception as error:  # noqa: BLE001 - 记录后继续，不中断普查
            entries.append({"name": path.stem, "group": group_of(path),
                            "file": str(path.relative_to(PROJECT_ROOT)).replace(os.sep, "/"),
                            "sha256": sha, "duplicate_of": None,
                            "error": f"{type(error).__name__}: {error}"})
            print(f"[{i}/{len(files)}] 测量失败 {path.name}: {error}", flush=True)
            continue
        print(f"[{i}/{len(files)}] 测量 {entry['group']}/{entry['name']} "
              f"{entry['size_whd']} nonair={entry['nonair']} "
              f"({entry['measure_seconds']}s)", flush=True)
        entries.append(entry)

    # 渲染：仅独立（非重复）的建筑级源
    render_targets = [e for e in entries
                      if not e.get("duplicate_of") and "error" not in e
                      and e.get("kind") == "building"]
    for e in entries:
        if e.get("duplicate_of") or "error" in e:
            continue
        if e.get("kind") != "building":
            e["render"] = {"status": "skipped_component"}
    if args.skip_render:
        for e in render_targets:
            e["render"] = {"status": "not_requested"}
    else:
        for j, e in enumerate(render_targets, 1):
            schem_path = PROJECT_ROOT / e["file"]
            out_dir = out_root / "previews" / e["group"] / e["name"]
            if render_done(out_dir, e["sha256"]):
                e["render"] = {"status": "ok",
                               "dir": str(out_dir.relative_to(out_root)).replace(os.sep, "/"),
                               "reused": True}
                print(f"[render {j}/{len(render_targets)}] 复用 {e['name']}", flush=True)
                continue
            print(f"[render {j}/{len(render_targets)}] 渲染 {e['group']}/{e['name']} ...",
                  flush=True)
            result = render_one(schem_path, out_dir, args.render_timeout)
            result["dir"] = str(out_dir.relative_to(out_root)).replace(os.sep, "/")
            e["render"] = result
            print(f"[render {j}/{len(render_targets)}] {e['name']} -> {result['status']}",
                  flush=True)

    inventory = {
        "atlas": "TECHNIQUE-ATLAS-v0.1",
        "project_root": str(PROJECT_ROOT),
        "skip_render": bool(args.skip_render),
        "view_names": list(VIEW_NAMES),
        "sources": entries,
    }
    (out_root / "source_inventory.json").write_text(
        json.dumps(inventory, indent=1, ensure_ascii=False), encoding="utf-8")

    stats = {
        "total_files": len(entries),
        "unique": sum(1 for e in entries if not e.get("duplicate_of")),
        "duplicates": sum(1 for e in entries if e.get("duplicate_of")),
        "buildings": sum(1 for e in entries
                         if e.get("kind") == "building" and not e.get("duplicate_of")),
        "components": sum(1 for e in entries if e.get("kind") == "component"),
        "render_ok": sum(1 for e in entries
                         if (e.get("render") or {}).get("status") == "ok"),
        "render_skipped": sum(1 for e in entries
                              if (e.get("render") or {}).get("status", "").startswith("skipped")),
        "render_failed": sum(1 for e in entries
                             if (e.get("render") or {}).get("status") == "failed"),
    }
    survey = build_survey_md(entries, out_root, stats)
    (out_root / "SURVEY.md").write_text(survey, encoding="utf-8")
    print(f"[atlas] 完成：{stats}", flush=True)
    print(f"[atlas] {out_root / 'source_inventory.json'}", flush=True)
    print(f"[atlas] {out_root / 'SURVEY.md'}", flush=True)


if __name__ == "__main__":
    main()
