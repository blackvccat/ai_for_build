#!/usr/bin/env python3
"""Run the first executable proof of the style-learning workflow."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from paris_builder.exporter import dump_json
from paris_builder.learning_workflow import (
    build_inventory,
    generate_massing_concept,
    validate_massing_set,
    write_massing_candidate,
)
from paris_builder.schematic import load_schematic


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=Path("runs/STYLE-LEARNING-PILOT-v0.1"))
    parser.add_argument("--skip-render", action="store_true")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    workspace = project.parent
    style_path = project / "knowledge/styles/paris_haussmann_v0.1.json"
    style = json.loads(style_path.read_text(encoding="utf-8"))
    output = args.output if args.output.is_absolute() else project / args.output
    output.mkdir(parents=True, exist_ok=True)

    windows = build_inventory(
        (workspace / "窗").glob("*.schem"),
        role="component_window_study",
        intended_view="axonometric_back_and_back_are_street_side",
    )
    buildings = build_inventory(
        (workspace / "巴黎建筑素材").glob("*.schem"),
        role="whole_building_or_street_block_reference",
        intended_view="SOURCE_SPECIFIC_REQUIRES_SEMANTIC_ANNOTATION",
    )
    dump_json(output / "internal_window_inventory.json", windows)
    dump_json(output / "internal_building_inventory.json", buildings)

    seeds = [1103, 2207, 3319]
    concepts = [generate_massing_concept(style, seed) for seed in seeds]
    replay = [generate_massing_concept(style, seed) for seed in seeds]
    concept_validation = validate_massing_set(concepts)
    concept_validation["checks"]["same_seed_is_byte_deterministic"] = (
        json.dumps([asdict(c) for c in concepts], sort_keys=True) ==
        json.dumps([asdict(c) for c in replay], sort_keys=True)
    )
    concept_validation["status"] = (
        "PASS" if all(concept_validation["checks"].values()) else "FAIL"
    )

    candidates = []
    for concept in concepts:
        folder = output / "massing_candidates" / concept.concept_id
        candidate = write_massing_candidate(folder, concept)
        readback = load_schematic(Path(candidate["schematic"]))
        candidate["technical_validation"] = readback.validation()
        candidate["voxel_state_hash"] = readback.voxel_state_hash()
        if not args.skip_render:
            from paris_builder.preview3d import render_previews
            candidate["previews"] = render_previews(
                Path(candidate["schematic"]), folder / "previews"
            )
        candidates.append(candidate)

    gates = {
        "G1_external_style_evidence": len(style["external_sources"]) >= 3,
        "G2_internal_sources_extracted": (
            windows["summary"]["schematic_count"] == 43 and
            buildings["summary"]["schematic_count"] == 14
        ),
        "G2_exact_states_retained": all(
            item["exact_state_counts"] for item in windows["items"]
        ),
        "G2_update_claims_are_marked_for_probe": all(
            probe["status"] == "NEEDS_CONTROLLED_PASTE_AND_NEIGHBOUR_UPDATE_PROBE"
            for item in windows["items"]
            for probe in item["update_suppression_candidates"]
        ),
        "G3_style_has_no_instance_section": not any(
            key in style for key in ("first_original_run", "run_id", "path")
        ),
        "G4_seeded_massing_set": concept_validation["status"] == "PASS",
        "G4_all_schematics_roundtrip": all(
            item["technical_validation"]["status"] == "PASS" for item in candidates
        ),
        "G5_seven_view_rendered": args.skip_render or all(
            all(name in item["previews"] for name in (
                "front", "back", "left", "right", "top",
                "axonometric_front", "axonometric_back",
            )) for item in candidates
        ),
        "G6_detail_is_still_locked": all(
            item["concept"]["detail_status"] == "PROHIBITED_UNTIL_MASSING_GATE_PASS"
            for item in candidates
        ),
    }
    report = {
        "pilot_id": "STYLE-LEARNING-PILOT-v0.1",
        "purpose": "Prove separation of research, craft evidence, massing and detail stages.",
        "style_model": str(style_path.resolve()),
        "style_model_sha256": hashlib.sha256(style_path.read_bytes()).hexdigest(),
        "inventory_summary": {
            "windows": windows["summary"],
            "buildings": buildings["summary"],
        },
        "concept_validation": concept_validation,
        "candidates": candidates,
        "gates": gates,
        "status": "PASS" if all(gates.values()) else "FAIL",
        "scope_of_pass": (
            "Executable feasibility only: evidence can be extracted, style and instance are "
            "separate, and diverse deterministic masses can be rendered from seven views. "
            "It does not claim that any candidate has passed visual or in-game acceptance."
        ),
        "manual_next_gates": [
            "Annotate component semantics and source crop coordinates.",
            "Run normal-paste versus suppressed-update A/B probes in Minecraft.",
            "Score massing candidates from seven views and select or reject them.",
            "Only then compose detail grammar and build a detailed prototype."
        ],
    }
    dump_json(output / "feasibility_report.json", report)
    if report["status"] != "PASS":
        raise SystemExit(json.dumps(report["gates"], ensure_ascii=False, indent=2))
    print(json.dumps({
        "status": report["status"],
        "output": str(output.resolve()),
        "window_sources": windows["summary"]["schematic_count"],
        "building_sources": buildings["summary"]["schematic_count"],
        "candidate_ids": [c.concept_id for c in concepts],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
