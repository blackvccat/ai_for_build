#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np
from PIL import Image

from paris_builder import __version__
from paris_builder.render import render_building, render_contact_sheet
from paris_builder.schematic import (
    AIR_BLOCKS,
    base_block,
    load_schematic,
    namespace,
    orthographic_surface_mask,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def natural_key(path: Path) -> List[Any]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", path.stem)]


def building_id(stem: str) -> str:
    match = re.search(r"(\d+)", stem)
    number = int(match.group(1)) if match else 0
    if "民居街区" in stem:
        suffix = "-oblique" if "斜面" in stem else ""
        return f"residential-{number:02d}{suffix}"
    return f"monumental-{number:02d}"


def counter_top(counter: Counter, limit: int = 20) -> List[Dict[str, Any]]:
    return [{"name": name, "count": int(count)} for name, count in counter.most_common(limit)]


def relative(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.parent.resolve()))
    except ValueError:
        return str(path.resolve())


def json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def annotation_draft(entry: Dict[str, Any]) -> Dict[str, Any]:
    family = "residential" if entry["building_id"].startswith("residential") else "monumental_or_civic"
    return {
        "schema_version": "0.1.0",
        "building_id": entry["building_id"],
        "source_pair": {
            "png": entry["source"]["png"]["path"],
            "schem": entry["source"]["schem"]["path"],
        },
        "provisional": {
            "family": family,
            "lot_type": "oblique_or_wedge" if "oblique" in entry["building_id"] else "needs_review",
            "orientation": "unknown_axis_face",
        },
        "observation": [],
        "inference": [],
        "design_assumption": [],
        "facade": {
            "base_body_cornice_roof_ratio": None,
            "floor_count": None,
            "bay_count": None,
            "projection_depth_blocks": None,
        },
        "review_status": "NEEDS_SEMANTIC_ANNOTATION",
    }


def markdown_report(summary: Dict[str, Any], entries: List[Dict[str, Any]]) -> str:
    lines = [
        "# G0/G1 基准报告",
        "",
        f"生成器版本：`{summary['generator_version']}`",
        "",
        "## 闸门结论",
        "",
        f"- G0 素材完整性：**{summary['gates']['G0']}**",
        f"- G1 自动解析与统一预览：**{summary['gates']['G1']}**",
        f"- 已处理配对：{summary['pair_count']} 组",
        f"- schematic 技术校验：{summary['validation_pass_count']}/{summary['pair_count']} PASS",
        "",
        "## 汇总",
        "",
        f"- 总包围盒体素：{summary['total_voxels']:,}",
        f"- 非空气方块：{summary['total_nonair']:,}（{summary['overall_density_percent']:.2f}%）",
        f"- 六向正投影可见方块：{summary['total_orthographic_surface_blocks']:,}",
        f"- 联合基础方块：{summary['unique_base_blocks']} 种",
        f"- 联合精确 block state：{summary['unique_states']} 种",
        f"- BlockEntity：{summary['total_block_entities']:,}",
        f"- 含 Create 方块的样本：{summary['samples_with_create']}/{summary['pair_count']}",
        "",
        "## 单体数据",
        "",
        "| ID | 尺寸 W×H×L | 非空气 | 表面 | Palette | BlockEntity | Create | 校验 |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for entry in entries:
        schematic = entry["schematic"]
        dims = schematic["dimensions"]
        lines.append(
            f"| {entry['building_id']} | {dims['width']}×{dims['height']}×{dims['length']} | "
            f"{schematic['nonair_blocks']:,} | {schematic['orthographic_surface_blocks']:,} | "
            f"{schematic['palette_state_count']} | {schematic['block_entity_count']} | "
            f"{schematic['create_block_count']:,} | {schematic['validation']['status']} |"
        )
    lines.extend(
        [
            "",
            "## 风险与下一步",
            "",
            "- 现有单张截图只作为视觉参考；G2 必须依据统一正交图和实际体素做语义标注。",
            "- 全体方块频率受隐藏羊毛填充影响，风格材料统计应优先采用可见表面统计。",
            "- faithful 模式仍需锁定 Create 与资源包的准确版本。",
            "- vanilla 模式需执行方块替换与行为 NBT 清洗后再导出，当前阶段仅完成风险识别。",
            "- 下一闸门 G2：确认主要朝向，标注楼层/开间/立面分段/屋顶/构件语义，并形成首版风格语法。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the G0/G1 Paris architecture baseline")
    parser.add_argument("--source", type=Path, required=True, help="Directory containing paired PNG and .schem files")
    parser.add_argument("--output", type=Path, required=True, help="Paris Builder project directory")
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()

    png_by_stem = {path.stem: path for path in source.glob("*.png")}
    schem_by_stem = {path.stem: path for path in source.glob("*.schem")}
    stems = sorted(set(png_by_stem) | set(schem_by_stem), key=lambda value: natural_key(Path(value)))
    missing_pairs = [stem for stem in stems if stem not in png_by_stem or stem not in schem_by_stem]
    if missing_pairs:
        raise SystemExit(f"Missing PNG/.schem pairs: {missing_pairs}")

    global_base_counts = Counter()
    global_surface_counts = Counter()
    global_states = set()
    entries: List[Dict[str, Any]] = []
    overview_items: List[Tuple[str, Path]] = []
    total_voxels = total_nonair = total_surface = total_block_entities = 0
    samples_with_create = 0
    validation_pass_count = 0

    profiles = json.loads((output / "configs" / "compatibility_profiles.json").read_text(encoding="utf-8"))
    blocked = set(profiles["safety_defaults"]["blocked_base_blocks"])

    for stem in stems:
        png_path = png_by_stem[stem]
        schem_path = schem_by_stem[stem]
        identifier = building_id(stem)
        schematic = load_schematic(schem_path)
        nonair = schematic.nonair_mask()
        surface = orthographic_surface_mask(nonair)
        state_counts = schematic.exact_state_counts()
        base_counts = schematic.base_block_counts()
        surface_ids = schematic.volume[surface]
        surface_state_counts = Counter(schematic.id_to_state[int(idx)] for idx in surface_ids)
        surface_base_counts = Counter()
        for state, count in surface_state_counts.items():
            surface_base_counts[base_block(state)] += count

        namespaces = sorted({namespace(state) for state in schematic.palette})
        create_count = sum(count for block, count in base_counts.items() if namespace(block) == "create")
        create_states = sorted(state for state in schematic.palette if namespace(state) == "create")
        risky_blocks = sorted(block for block in base_counts if block in blocked)
        be_types = schematic.block_entity_type_counts()
        custom_heads = int(be_types.get("minecraft:skull", 0) + be_types.get("minecraft:player_head", 0))
        validation = schematic.validation()
        if validation["status"] == "PASS":
            validation_pass_count += 1
        if create_count:
            samples_with_create += 1

        with Image.open(png_path) as image:
            image_dimensions = {"width": image.width, "height": image.height, "mode": image.mode}

        preview_dir = output / "previews" / identifier
        summary_lines = [
            f"size: {schematic.width} x {schematic.height} x {schematic.length}",
            f"non-air: {int(nonair.sum()):,}",
            f"ortho surface: {int(surface.sum()):,}",
            f"palette states: {len(schematic.palette)}",
            f"block entities: {len(schematic.block_entities):,}",
            f"namespaces: {', '.join(namespaces)}",
            f"validation: {validation['status']}",
        ]
        preview_paths = render_building(
            schematic,
            png_path,
            preview_dir,
            identifier,
            summary_lines,
        )
        overview_items.append((identifier, Path(preview_paths["overview"])))

        entry = {
            "building_id": identifier,
            "display_name": stem,
            "source": {
                "png": {
                    "path": relative(png_path, output),
                    "bytes": png_path.stat().st_size,
                    "sha256": sha256_file(png_path),
                    "image": image_dimensions,
                },
                "schem": {
                    "path": relative(schem_path, output),
                    "bytes": schem_path.stat().st_size,
                    "sha256": sha256_file(schem_path),
                },
            },
            "schematic": {
                "format": "Sponge Schematic v2",
                "root_name": schematic.root_name,
                "version": schematic.version,
                "data_version": schematic.data_version,
                "offset": list(schematic.offset),
                "dimensions": {
                    "width": schematic.width,
                    "height": schematic.height,
                    "length": schematic.length,
                    "volume": schematic.voxel_count,
                },
                "palette_state_count": len(schematic.palette),
                "palette_max": schematic.palette_max,
                "namespaces": namespaces,
                "nonair_blocks": int(nonair.sum()),
                "density_percent": round(float(nonair.mean() * 100), 4),
                "orthographic_surface_blocks": int(surface.sum()),
                "create_block_count": int(create_count),
                "create_states": create_states,
                "entity_count": len(schematic.entities),
                "block_entity_count": len(schematic.block_entities),
                "block_entity_types": dict(sorted(be_types.items())),
                "metadata": schematic.metadata,
                "nbt_signals": schematic.nbt_signals,
                "risks": {
                    "risky_base_blocks": risky_blocks,
                    "custom_head_count": custom_heads,
                    "has_behavior_nbt": bool(schematic.nbt_signals["behavior_keys"]),
                    "has_unknown_namespaced_nbt": any(
                        key.split(":", 1)[0] not in {"minecraft", "create"}
                        for key in schematic.nbt_signals["namespaced_keys"]
                    ),
                },
                "top_base_blocks": counter_top(base_counts),
                "top_surface_base_blocks": counter_top(surface_base_counts),
                "voxel_state_hash": schematic.voxel_state_hash(),
                "validation": validation,
            },
            "previews": {
                key: relative(Path(path), output) for key, path in preview_paths.items()
            },
        }
        entries.append(entry)
        json_dump(output / "annotations" / "drafts" / f"{identifier}.json", annotation_draft(entry))

        global_base_counts.update(base_counts)
        global_surface_counts.update(surface_base_counts)
        global_states.update(schematic.palette)
        total_voxels += schematic.voxel_count
        total_nonair += int(nonair.sum())
        total_surface += int(surface.sum())
        total_block_entities += len(schematic.block_entities)

    contact_path = output / "previews" / "contact_sheet.png"
    render_contact_sheet(overview_items, contact_path)

    manifest = {
        "schema_version": "0.1.0",
        "generator_version": __version__,
        "source_directory": relative(source, output),
        "pair_count": len(entries),
        "pairing_rule": "same UTF-8 filename stem with .png and .schem extensions",
        "entries": entries,
    }
    json_dump(output / "manifests" / "source_manifest.json", manifest)

    summary = {
        "schema_version": "0.1.0",
        "generator_version": __version__,
        "pair_count": len(entries),
        "validation_pass_count": validation_pass_count,
        "total_voxels": total_voxels,
        "total_nonair": total_nonair,
        "overall_density_percent": round(total_nonair / total_voxels * 100, 4),
        "total_orthographic_surface_blocks": total_surface,
        "unique_base_blocks": len(global_base_counts),
        "unique_states": len(global_states),
        "total_block_entities": total_block_entities,
        "samples_with_create": samples_with_create,
        "top_base_blocks": counter_top(global_base_counts, 30),
        "top_surface_base_blocks": counter_top(global_surface_counts, 30),
        "gates": {
            "G0": "PASS" if len(entries) == 14 and validation_pass_count == len(entries) else "FAIL",
            "G1": "PASS" if len(overview_items) == len(entries) else "FAIL",
        },
    }
    json_dump(output / "reports" / "baseline_report.json", summary)
    report_path = output / "reports" / "baseline_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(markdown_report(summary, entries), encoding="utf-8")
    print(json.dumps({
        "manifest": str(output / "manifests" / "source_manifest.json"),
        "report": str(report_path),
        "contact_sheet": str(contact_path),
        "gates": summary["gates"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

