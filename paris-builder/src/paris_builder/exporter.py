"""Deterministic Sponge-v2 output. All positions use local x/y/z coordinates."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path

import nbtlib
import numpy as np


def encode_varints(values):
    result = bytearray()
    for value in values:
        value = int(value)
        if value < 0 or value > 0x7FFFFFFF:
            raise ValueError("Palette ID must be a nonnegative signed 32-bit integer")
        while value > 127:
            result.append((value & 127) | 128)
            value >>= 7
        result.append(value)
    return bytes(result)


def canonicalize(volume, palette):
    if volume.ndim != 3 or volume.size == 0:
        raise ValueError("Volume must be a nonempty (height,length,width) array")
    if not np.issubdtype(volume.dtype, np.integer):
        raise ValueError("Volume must contain integer palette IDs")
    if int(volume.min()) < 0 or int(volume.max()) >= len(palette):
        raise ValueError("Volume references an absent palette entry")
    if len(palette) != len(set(palette)):
        raise ValueError("Duplicate block states in palette")
    used = np.unique(volume)
    states = sorted(palette[int(i)] for i in used)
    lookup = {state: idx for idx, state in enumerate(states)}
    remap = np.zeros(len(palette), dtype=np.int32)
    for old in used:
        remap[old] = lookup[palette[int(old)]]
    return remap[volume], states


def write_schematic(path: Path, volume, palette, *, name="Paris building", data_version=4671):
    volume, palette = canonicalize(volume, palette)
    height, length, width = volume.shape
    if max(height, length, width) > 32767:
        raise ValueError("This exporter intentionally limits dimensions to signed Short range")
    root = nbtlib.Compound({
        "Version": nbtlib.Int(2),
        "DataVersion": nbtlib.Int(data_version),
        "Width": nbtlib.Short(width),
        "Height": nbtlib.Short(height),
        "Length": nbtlib.Short(length),
        "Offset": nbtlib.IntArray([0, 0, 0]),
        "PaletteMax": nbtlib.Int(len(palette)),
        "Palette": nbtlib.Compound({state: nbtlib.Int(i) for i, state in enumerate(palette)}),
        "BlockData": nbtlib.ByteArray(np.frombuffer(encode_varints(volume.ravel()), dtype=np.int8)),
        "BlockEntities": nbtlib.List[nbtlib.Compound]([]),
        "Entities": nbtlib.List[nbtlib.Compound]([]),
        "Metadata": nbtlib.Compound({
            "Name": nbtlib.String(name), "Author": nbtlib.String("Paris Builder"),
            "CreatedBy": nbtlib.String("paris-builder/0.2.0"),
            "WEOffsetX": nbtlib.Int(0), "WEOffsetY": nbtlib.Int(0), "WEOffsetZ": nbtlib.Int(0),
        }),
    })
    if int(nbtlib.__version__.split(".")[0]) < 2:
        document = nbtlib.File({"Schematic": root})
    else:
        document = nbtlib.File(root, root_name="Schematic")
    raw = io.BytesIO()
    document.write(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        with gzip.GzipFile(fileobj=handle, filename="", mode="wb", mtime=0) as compressed:
            compressed.write(raw.getvalue())
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "palette_count": len(palette)}


def dump_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
