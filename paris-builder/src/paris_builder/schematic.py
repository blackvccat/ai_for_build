from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import nbtlib
import numpy as np


AIR_BLOCKS = {
    "minecraft:air",
    "minecraft:cave_air",
    "minecraft:void_air",
}


def base_block(state: str) -> str:
    return state.split("[", 1)[0]


def namespace(state_or_block: str) -> str:
    return base_block(state_or_block).split(":", 1)[0]


def decode_varints(data: Iterable[int]) -> np.ndarray:
    """Decode unsigned palette VarInts used by Sponge schematic v2."""
    values: List[int] = []
    value = 0
    shift = 0
    for raw in data:
        byte = int(raw) & 0xFF
        value |= (byte & 0x7F) << shift
        if byte & 0x80:
            shift += 7
            if shift > 35:
                raise ValueError("BlockData contains an overlong VarInt")
        else:
            values.append(value)
            value = 0
            shift = 0
    if shift:
        raise ValueError("BlockData ends with an incomplete VarInt")
    return np.asarray(values, dtype=np.int32)


def _root_compound(nbt_file: Any) -> Mapping[str, Any]:
    root_name = getattr(nbt_file, "root_name", "")
    if root_name and root_name in nbt_file:
        return nbt_file[root_name]
    return nbt_file


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def scan_nbt_signals(value: Any) -> Dict[str, Any]:
    namespaced_keys = set()
    behavior_keys = Counter()
    string_namespaces = set()
    watch = {
        "items",
        "bees",
        "loottable",
        "spawndata",
        "spawnpotentials",
        "command",
    }

    def visit(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                key_text = str(key)
                if ":" in key_text:
                    namespaced_keys.add(key_text)
                if key_text.lower() in watch:
                    behavior_keys[key_text] += 1
                visit(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                visit(child)
        elif isinstance(node, str) and ":" in node:
            prefix = node.split(":", 1)[0]
            if prefix and prefix.replace("_", "").isalnum():
                string_namespaces.add(prefix)

    visit(value)
    return {
        "namespaced_keys": sorted(namespaced_keys),
        "behavior_keys": dict(sorted(behavior_keys.items())),
        "string_namespaces": sorted(string_namespaces),
    }


@dataclass
class SchematicData:
    path: Path
    root_name: str
    width: int
    height: int
    length: int
    version: int
    data_version: int
    offset: Tuple[int, int, int]
    palette_max: int
    palette: Dict[str, int]
    id_to_state: List[str]
    block_ids: np.ndarray
    volume: np.ndarray
    metadata: Dict[str, Any]
    block_entities: Sequence[Any]
    entities: Sequence[Any]
    nbt_signals: Dict[str, Any]

    @property
    def voxel_count(self) -> int:
        return self.width * self.height * self.length

    @property
    def air_ids(self) -> np.ndarray:
        ids = [idx for state, idx in self.palette.items() if base_block(state) in AIR_BLOCKS]
        return np.asarray(ids, dtype=np.int32)

    def nonair_mask(self) -> np.ndarray:
        if not len(self.air_ids):
            return np.ones(self.volume.shape, dtype=bool)
        palette_is_air = np.zeros(max(len(self.id_to_state), int(self.volume.max()) + 1), dtype=bool)
        palette_is_air[self.air_ids] = True
        return ~palette_is_air[self.volume]

    def exact_state_counts(self) -> Counter:
        counts = np.bincount(self.block_ids, minlength=len(self.id_to_state))
        return Counter(
            {self.id_to_state[i]: int(count) for i, count in enumerate(counts) if count}
        )

    def base_block_counts(self) -> Counter:
        exact = self.exact_state_counts()
        result = Counter()
        for state, count in exact.items():
            result[base_block(state)] += count
        return result

    def block_entity_type_counts(self) -> Counter:
        result = Counter()
        for entity in self.block_entities:
            entity_id = entity.get("Id", entity.get("id", "unknown"))
            result[str(entity_id)] += 1
        return result

    def voxel_state_hash(self) -> str:
        """Hash dimensions and canonicalized states, independent of palette ordering."""
        ordered_states = sorted(self.palette)
        canonical_id = {state: idx for idx, state in enumerate(ordered_states)}
        remap = np.zeros(len(self.id_to_state), dtype=np.uint32)
        for old_id, state in enumerate(self.id_to_state):
            remap[old_id] = canonical_id[state]
        canonical = remap[self.block_ids]
        digest = sha256()
        digest.update(np.asarray([self.width, self.height, self.length], dtype="<u4").tobytes())
        digest.update("\n".join(ordered_states).encode("utf-8"))
        digest.update(canonical.astype("<u4", copy=False).tobytes())
        return digest.hexdigest()

    def validation(self) -> Dict[str, Any]:
        palette_ids = sorted(self.palette.values())
        expected_ids = list(range(len(palette_ids)))
        invalid_refs = int(np.count_nonzero(self.block_ids >= len(self.id_to_state)))
        checks = {
            "decoded_block_count_matches_volume": len(self.block_ids) == self.voxel_count,
            "palette_ids_contiguous_from_zero": palette_ids == expected_ids,
            "palette_max_covers_palette": self.palette_max >= len(self.palette),
            "all_block_references_in_palette": invalid_refs == 0,
            "offset_has_three_values": len(self.offset) == 3,
            "positive_dimensions": self.width > 0 and self.height > 0 and self.length > 0,
        }
        return {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "invalid_block_references": invalid_refs,
        }


def load_schematic(path: Path) -> SchematicData:
    nbt_file = nbtlib.load(path)
    root = _root_compound(nbt_file)
    width = int(root["Width"])
    height = int(root["Height"])
    length = int(root["Length"])
    palette = {str(state): int(idx) for state, idx in root["Palette"].items()}
    max_id = max(palette.values()) if palette else -1
    id_to_state = [""] * (max_id + 1)
    for state, idx in palette.items():
        if idx < 0 or idx > max_id:
            raise ValueError(f"Invalid palette id {idx} in {path}")
        id_to_state[idx] = state
    if any(not state for state in id_to_state):
        raise ValueError(f"Palette ids are not contiguous in {path}")
    block_ids = decode_varints(root["BlockData"])
    expected = width * height * length
    if len(block_ids) != expected:
        raise ValueError(
            f"Decoded BlockData count {len(block_ids)} does not match {width}x{height}x{length}={expected}"
        )
    if len(block_ids) and int(block_ids.max()) >= len(id_to_state):
        raise ValueError(f"BlockData references an absent palette entry in {path}")

    # Sponge v2 linear index is x + z*Width + y*Width*Length.
    volume = block_ids.reshape((height, length, width))
    block_entities = list(root.get("BlockEntities", []))
    entities = list(root.get("Entities", []))
    combined_nbt = {"BlockEntities": block_entities, "Entities": entities}

    return SchematicData(
        path=path,
        root_name=str(getattr(nbt_file, "root_name", "")),
        width=width,
        height=height,
        length=length,
        version=int(root["Version"]),
        data_version=int(root["DataVersion"]),
        offset=tuple(int(v) for v in root.get("Offset", [0, 0, 0])),
        palette_max=int(root.get("PaletteMax", len(palette))),
        palette=palette,
        id_to_state=id_to_state,
        block_ids=block_ids,
        volume=volume,
        metadata=_plain(root.get("Metadata", {})),
        block_entities=block_entities,
        entities=entities,
        nbt_signals=scan_nbt_signals(combined_nbt),
    )


def orthographic_surface_mask(nonair: np.ndarray) -> np.ndarray:
    """Union of blocks first visible along all six cardinal axis projections."""
    surface = np.zeros(nonair.shape, dtype=bool)
    for axis in range(3):
        occupied_lines = nonair.any(axis=axis)
        first = nonair.argmax(axis=axis)
        last = nonair.shape[axis] - 1 - np.flip(nonair, axis=axis).argmax(axis=axis)
        a, b = np.nonzero(occupied_lines)
        if axis == 0:
            surface[first[a, b], a, b] = True
            surface[last[a, b], a, b] = True
        elif axis == 1:
            surface[a, first[a, b], b] = True
            surface[a, last[a, b], b] = True
        else:
            surface[a, b, first[a, b]] = True
            surface[a, b, last[a, b]] = True
    return surface

