"""Evidence extraction and massing-first concept generation.

This module deliberately does not generate a finished facade.  It separates two
questions that the former PAR-001 generator mixed together:

* what a source schematic proves about Minecraft construction technique; and
* what a style model permits a new building mass to become.

The detail grammar may only be applied after a massing candidate passes the
multi-view gate.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
import hashlib
import json
import random
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np

from .exporter import dump_json, write_schematic
from .schematic import AIR_BLOCKS, base_block, load_schematic


STATEFUL_DETAIL_SUFFIXES = (
    "_wall", "_stairs", "_slab", "_pane", "_fence", "_fence_gate",
    "_trapdoor", "_door", "_button", "_rod", "_chain", "_bars",
)


def _state_properties(state: str) -> Dict[str, str]:
    _, marker, raw = state.partition("[")
    if not marker:
        return {}
    return dict(item.split("=", 1) for item in raw.rstrip("]").split(",") if "=" in item)


def _projection(mask: np.ndarray, axis: int) -> Dict[str, Any]:
    projected = mask.any(axis=axis)
    depths = mask.sum(axis=axis)
    occupied = depths[projected]
    return {
        "occupied_pixels": int(projected.sum()),
        "projected_area": int(projected.size),
        "coverage": round(float(projected.mean()), 5),
        "mean_occupied_depth": round(float(occupied.mean()), 3) if occupied.size else 0.0,
        "max_depth": int(occupied.max()) if occupied.size else 0,
        "silhouette_sha256": hashlib.sha256(np.packbits(projected).tobytes()).hexdigest(),
    }


def analyze_schematic(path: Path, *, role: str, intended_view: str) -> Dict[str, Any]:
    """Extract facts only; semantic interpretation remains a separate annotation."""
    data = load_schematic(path)
    mask = data.nonair_mask()
    exact = data.exact_state_counts()
    nonair_states = {state: count for state, count in exact.items()
                     if base_block(state) not in AIR_BLOCKS}
    stateful = {
        state: count for state, count in nonair_states.items()
        if _state_properties(state) or base_block(state).endswith(STATEFUL_DETAIL_SUFFIXES)
    }
    # Isolated voxels are useful evidence for intentionally floating facade marks.
    neighbor_count = np.zeros(mask.shape, dtype=np.uint8)
    neighbor_count[1:] += mask[:-1]
    neighbor_count[:-1] += mask[1:]
    neighbor_count[:, 1:] += mask[:, :-1]
    neighbor_count[:, :-1] += mask[:, 1:]
    neighbor_count[:, :, 1:] += mask[:, :, :-1]
    neighbor_count[:, :, :-1] += mask[:, :, 1:]
    isolated = mask & (neighbor_count == 0)
    update_probe_states = []
    for state, count in sorted(stateful.items()):
        props = _state_properties(state)
        sensitive = any(key in props for key in (
            "north", "south", "east", "west", "up", "down", "shape",
            "half", "facing", "open", "hinge", "face", "waterlogged",
        ))
        if sensitive:
            update_probe_states.append({
                "state": state,
                "count": int(count),
                "status": "NEEDS_CONTROLLED_PASTE_AND_NEIGHBOUR_UPDATE_PROBE",
            })
    return {
        "source": str(path.resolve()),
        "role": role,
        "intended_view": intended_view,
        "dimensions_whl": [data.width, data.height, data.length],
        "data_version": data.data_version,
        "voxel_state_hash": data.voxel_state_hash(),
        "nonair_blocks": int(mask.sum()),
        "palette_state_count": len(nonair_states),
        "exact_state_counts": dict(sorted(nonair_states.items())),
        "stateful_detail_counts": dict(sorted(stateful.items())),
        "isolated_nonair_voxels": int(isolated.sum()),
        "update_suppression_candidates": update_probe_states,
        "projections": {
            "front_back": _projection(mask, 1),  # collapse z -> y/x
            "left_right": _projection(mask, 2),  # collapse x -> y/z
            "top": _projection(mask, 0),         # collapse y -> z/x
        },
        "interpretation_status": "UNANNOTATED_EVIDENCE",
    }


def build_inventory(paths: Iterable[Path], *, role: str, intended_view: str) -> Dict[str, Any]:
    items = [analyze_schematic(path, role=role, intended_view=intended_view)
             for path in sorted(paths)]
    return {
        "inventory_version": "0.1.0",
        "evidence_policy": (
            "Exact states and projections are observations. Update suppression is only a candidate "
            "until normal-paste and suppressed-update paste are compared in game."
        ),
        "items": items,
        "summary": {
            "schematic_count": len(items),
            "stateful_source_count": sum(bool(item["stateful_detail_counts"]) for item in items),
            "update_probe_source_count": sum(bool(item["update_suppression_candidates"]) for item in items),
            "isolated_voxel_source_count": sum(item["isolated_nonair_voxels"] > 0 for item in items),
        },
    }


@dataclass(frozen=True)
class MassingConcept:
    concept_id: str
    style_id: str
    seed: int
    stage: str
    width: int
    depth: int
    base_height: int
    body_height: int
    roof_height: int
    storeys_above_base: int
    bay_count: int
    bay_pitch: int
    footprint_type: str
    front_corner_treatment: str
    central_risalit_width: int
    central_risalit_projection: int
    roof_profile: str
    street_balcony_strategy: str
    entrance_axis: str
    face_roles: Mapping[str, str]
    detail_status: str

    @property
    def total_height(self) -> int:
        return self.base_height + self.body_height + self.roof_height


def generate_massing_concept(style: Mapping[str, Any], seed: int) -> MassingConcept:
    rng = random.Random(seed)
    ranges = style["massing_ranges"]
    bay_count = rng.choice(ranges["bay_count"])
    bay_pitch = rng.choice(ranges["bay_pitch"])
    side_margin = rng.choice([3, 4])
    width = bay_count * bay_pitch + side_margin * 2
    base_height = rng.choice(ranges["base_height"])
    storeys = rng.choice(ranges["storeys_above_base"])
    floor_pitch = rng.choice(ranges["floor_pitch"])
    body_height = storeys * floor_pitch
    roof_height = rng.choice(ranges["roof_height"])
    depth = rng.choice(ranges["depth"])
    footprint_type = rng.choice(style["variation_axes"]["footprint_type"])
    corner = rng.choice(style["variation_axes"]["front_corner_treatment"])
    risalit_bays = rng.choice([1, 3]) if bay_count >= 9 else 1
    risalit_width = risalit_bays * bay_pitch
    projection = rng.choice([0, 1, 2])
    if footprint_type == "recessed_centre":
        projection = -1
    strategy = rng.choice(style["variation_axes"]["street_balcony_strategy"])
    entrance = rng.choice(["centre", "left_of_centre", "right_of_centre"])
    signature = f"{seed}:{width}:{depth}:{bay_count}:{footprint_type}:{corner}:{strategy}"
    concept_id = "MS-" + hashlib.sha256(signature.encode()).hexdigest()[:10].upper()
    return MassingConcept(
        concept_id=concept_id,
        style_id=style["style_id"],
        seed=seed,
        stage="MASSING_ONLY",
        width=width,
        depth=depth,
        base_height=base_height,
        body_height=body_height,
        roof_height=roof_height,
        storeys_above_base=storeys,
        bay_count=bay_count,
        bay_pitch=bay_pitch,
        footprint_type=footprint_type,
        front_corner_treatment=corner,
        central_risalit_width=risalit_width,
        central_risalit_projection=projection,
        roof_profile="mansard_two_slope",
        street_balcony_strategy=strategy,
        entrance_axis=entrance,
        face_roles={
            "north": "primary_street_front",
            "south": "courtyard_or_secondary_front",
            "west": "corner_return_or_party_wall",
            "east": "corner_return_or_party_wall",
            "top": "roofscape_and_skyline",
        },
        detail_status="PROHIBITED_UNTIL_MASSING_GATE_PASS",
    )


def _footprint(concept: MassingConcept) -> Tuple[np.ndarray, int]:
    pad = 4
    projection = max(0, concept.central_risalit_projection)
    length = concept.depth + pad * 2 + projection
    width = concept.width + pad * 2
    mask = np.zeros((length, width), dtype=bool)
    z0 = pad + projection
    mask[z0:z0 + concept.depth, pad:pad + concept.width] = True
    centre = pad + concept.width // 2
    half = concept.central_risalit_width // 2
    if concept.central_risalit_projection > 0:
        mask[z0 - projection:z0, centre - half:centre + half + 1] = True
    elif concept.central_risalit_projection < 0:
        mask[z0:z0 + 1, centre - half:centre + half + 1] = False
    if concept.footprint_type == "rear_courtyard_notch":
        notch_w = max(5, concept.width // 3)
        notch_d = max(4, concept.depth // 3)
        mask[z0 + concept.depth - notch_d:z0 + concept.depth,
             centre - notch_w // 2:centre + notch_w // 2 + 1] = False
    if concept.front_corner_treatment == "chamfered":
        for step in range(3):
            mask[z0:z0 + 3 - step, pad:pad + step + 1] = False
            mask[z0:z0 + 3 - step, pad + concept.width - step - 1:pad + concept.width] = False
    return mask, pad


def _edge(mask: np.ndarray) -> np.ndarray:
    interior = mask.copy()
    interior[1:-1, 1:-1] &= mask[:-2, 1:-1]
    interior[1:-1, 1:-1] &= mask[2:, 1:-1]
    interior[1:-1, 1:-1] &= mask[1:-1, :-2]
    interior[1:-1, 1:-1] &= mask[1:-1, 2:]
    return mask & ~interior


def build_massing_volume(concept: MassingConcept) -> Tuple[np.ndarray, List[str], Dict[str, Any]]:
    footprint, _ = _footprint(concept)
    height = concept.total_height + 2
    volume = np.zeros((height, footprint.shape[0], footprint.shape[1]), dtype=np.int16)
    palette = [
        "minecraft:air",
        "minecraft:polished_andesite",
        "minecraft:smooth_sandstone",
        "minecraft:deepslate_tiles",
    ]
    base_end = concept.base_height
    body_end = base_end + concept.body_height
    edge = _edge(footprint)
    for y in range(base_end):
        volume[y, edge] = 1
    for y in range(base_end, body_end):
        volume[y, edge] = 2

    # Framework openings belong to massing: they establish bay rhythm, storey
    # hierarchy and the relationship of all four faces.  Surrounds, mullions,
    # railings and state tricks remain prohibited detail.
    pitch = concept.body_height // concept.storeys_above_base
    pad_x = (footprint.shape[1] - concept.width) // 2
    margin = (concept.width - concept.bay_count * concept.bay_pitch) // 2
    bay_centres = [pad_x + margin + concept.bay_pitch // 2 + i * concept.bay_pitch
                   for i in range(concept.bay_count)]
    for floor in range(concept.storeys_above_base):
        opening_y = base_end + floor * pitch + 1
        opening_h = max(3, pitch - 2)
        for centre_x in bay_centres:
            for x in range(centre_x - 1, centre_x + 1):
                occupied_z = np.flatnonzero(footprint[:, x])
                if occupied_z.size:
                    volume[opening_y:opening_y + opening_h, occupied_z[0], x] = 0
                    # The framework model keeps rear openings aligned so the
                    # front orthographic view reads them as true voids. Later
                    # facade stages may vary their infill and subdivision.
                    volume[opening_y:opening_y + opening_h, occupied_z[-1], x] = 0

        # Side returns use their own depth rhythm rather than copying the front.
        for z in range(5, footprint.shape[0] - 5, max(5, concept.bay_pitch + 1)):
            occupied_x = np.flatnonzero(footprint[z])
            if occupied_x.size:
                volume[opening_y:opening_y + opening_h, z, occupied_x[0]] = 0
                volume[opening_y:opening_y + opening_h, z, occupied_x[-1]] = 0

    # Base openings establish shop/entrance cadence without committing to a
    # shopfront component language.
    entrance_offset = {"centre": 0, "left_of_centre": -1, "right_of_centre": 1}[
        concept.entrance_axis]
    entrance_bay = max(0, min(concept.bay_count - 1,
                              concept.bay_count // 2 + entrance_offset))
    for bay_index, centre_x in enumerate(bay_centres):
        if bay_index == entrance_bay or bay_index % 2 == 0:
            half_width = 1 if bay_index == entrance_bay else max(1, concept.bay_pitch // 2 - 1)
            for x in range(centre_x - half_width, centre_x + half_width + 1):
                occupied_z = np.flatnonzero(footprint[:, x])
                if occupied_z.size:
                    volume[1:max(3, base_end - 1), occupied_z[0], x] = 0

    # Full-width balcony slabs are large-scale articulation, not railing detail.
    balcony_levels = [base_end]
    if concept.street_balcony_strategy != "noble_floor_only":
        balcony_levels.append(base_end + (concept.storeys_above_base - 1) * pitch)
    for y in balcony_levels:
        for x in range(pad_x, pad_x + concept.width):
            occupied_z = np.flatnonzero(footprint[:, x])
            if occupied_z.size and occupied_z[0] > 0:
                volume[y, occupied_z[0] - 1, x] = 2
    roof_masks: List[np.ndarray] = []
    current = footprint.copy()
    for level in range(concept.roof_height):
        # A steep lower pitch and a shallower crown, expressed only as silhouette.
        should_inset = level < min(5, concept.roof_height - 2) or (level % 3 == 2)
        if should_inset and current.shape[0] > 4 and current.shape[1] > 4:
            eroded = current.copy()
            eroded[0] = eroded[-1] = False
            eroded[:, 0] = eroded[:, -1] = False
            eroded &= np.roll(current, 1, axis=0) & np.roll(current, -1, axis=0)
            eroded &= np.roll(current, 1, axis=1) & np.roll(current, -1, axis=1)
            if eroded.any():
                current = eroded
        roof_masks.append(current.copy())
        volume[body_end + level, _edge(current)] = 3
    if roof_masks:
        volume[body_end + concept.roof_height - 1, roof_masks[-1]] = 3
    metadata = {
        "stage": "MASSING_ONLY",
        "forbidden_at_this_stage": [
            "window surrounds", "balcony railings", "debug-stick state compositions",
            "material speckle", "shopfront lettering", "ornamental props",
        ],
        "framework_included": [
            "base/body/roof hierarchy", "bay and storey void rhythm", "entrance axis",
            "continuous balcony slabs", "front/rear/return opening relationships",
            "corner and courtyard transitions",
        ],
        "zone_palette_only": True,
        "concept": {**asdict(concept), "total_height": concept.total_height},
    }
    return volume, palette, metadata


def concept_difference(a: MassingConcept, b: MassingConcept) -> Dict[str, Any]:
    fields = (
        "width", "depth", "storeys_above_base", "bay_count", "bay_pitch",
        "footprint_type", "front_corner_treatment", "central_risalit_projection",
        "street_balcony_strategy", "entrance_axis",
    )
    changed = [name for name in fields if getattr(a, name) != getattr(b, name)]
    return {"changed_axes": changed, "count": len(changed)}


def validate_massing_set(concepts: Sequence[MassingConcept]) -> Dict[str, Any]:
    pairs = []
    for i, left in enumerate(concepts):
        for right in concepts[i + 1:]:
            pairs.append({"pair": [left.concept_id, right.concept_id],
                          **concept_difference(left, right)})
    checks = {
        "at_least_three_candidates": len(concepts) >= 3,
        "every_candidate_defines_five_face_roles": all(len(c.face_roles) == 5 for c in concepts),
        "details_deferred": all(c.stage == "MASSING_ONLY" and c.detail_status.startswith("PROHIBITED")
                                for c in concepts),
        "pairwise_variation_at_least_three_axes": bool(pairs) and all(p["count"] >= 3 for p in pairs),
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
            "pairwise_differences": pairs}


def write_massing_candidate(output: Path, concept: MassingConcept) -> Dict[str, Any]:
    volume, palette, metadata = build_massing_volume(concept)
    output.mkdir(parents=True, exist_ok=True)
    schem = output / "massing.schem"
    result = write_schematic(schem, volume, palette,
                             name=f"{concept.concept_id} | massing only", data_version=4671)
    dump_json(output / "concept.json", metadata)
    return {"concept": metadata["concept"], "schematic": str(schem.resolve()), **result}
