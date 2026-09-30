from __future__ import annotations

import colorsys
from hashlib import sha256
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .schematic import SchematicData, base_block


BACKGROUND = np.asarray([236, 241, 244], dtype=np.uint8)

COLOR_PREFIXES = {
    "white": (226, 226, 216),
    "light_gray": (166, 170, 166),
    "gray": (94, 99, 102),
    "black": (35, 36, 39),
    "brown": (103, 70, 48),
    "red": (143, 55, 49),
    "orange": (198, 111, 45),
    "yellow": (213, 183, 64),
    "lime": (111, 176, 54),
    "green": (69, 111, 62),
    "cyan": (52, 126, 137),
    "light_blue": (101, 155, 190),
    "blue": (53, 74, 143),
    "purple": (111, 67, 148),
    "magenta": (174, 79, 160),
    "pink": (213, 136, 155),
}


def _font(size: int) -> ImageFont.ImageFont:
    """Latin label font; the CJK system fonts are unsafe on Windows (see .fonts)."""
    from .fonts import load_font
    return load_font(size)


def block_color(block: str) -> Tuple[int, int, int]:
    name = base_block(block).split(":", 1)[-1]
    for prefix, color in COLOR_PREFIXES.items():
        if name.startswith(prefix + "_"):
            return color
    if any(key in name for key in ("sandstone", "end_stone")):
        return (205, 189, 143)
    if any(key in name for key in ("quartz", "calcite", "diorite", "bone_block", "mushroom_stem")):
        return (218, 217, 202)
    if any(key in name for key in ("deepslate", "blackstone")):
        return (55, 58, 62)
    if any(key in name for key in ("stone", "andesite", "tuff", "cobblestone", "gravel")):
        return (126, 126, 121)
    if any(key in name for key in ("brick", "terracotta", "clay", "granite")):
        return (146, 91, 71)
    if any(key in name for key in ("copper", "prismarine")):
        return (65, 133, 121)
    if any(key in name for key in ("glass", "ice")):
        return (124, 176, 188)
    if any(key in name for key in ("iron", "chain", "anvil", "cauldron", "hopper")):
        return (81, 88, 91)
    if any(key in name for key in ("leaves", "azalea", "moss", "vine", "grass")):
        return (75, 125, 65)
    if any(key in name for key in ("birch", "bamboo")):
        return (196, 177, 121)
    if any(key in name for key in ("oak", "spruce", "jungle", "acacia", "mangrove", "cherry", "wood", "planks", "log")):
        return (123, 88, 55)
    if any(key in name for key in ("torch", "lantern", "glowstone", "light")):
        return (226, 175, 74)
    digest = sha256(name.encode("utf-8")).digest()
    hue = int.from_bytes(digest[:2], "big") / 65535.0
    saturation = 0.18 + digest[2] / 255.0 * 0.18
    value = 0.55 + digest[3] / 255.0 * 0.18
    r, g, b = colorsys.hsv_to_rgb(hue, saturation, value)
    return (int(r * 255), int(g * 255), int(b * 255))


def palette_colors(schematic: SchematicData) -> np.ndarray:
    return np.asarray([block_color(state) for state in schematic.id_to_state], dtype=np.uint8)


def project(
    volume: np.ndarray,
    nonair: np.ndarray,
    axis: int,
    reverse: bool,
    colors: np.ndarray,
) -> np.ndarray:
    source_ids = np.flip(volume, axis=axis) if reverse else volume
    source_mask = np.flip(nonair, axis=axis) if reverse else nonair
    visible = source_mask.any(axis=axis)
    depth = source_mask.argmax(axis=axis)
    selected = np.take_along_axis(source_ids, np.expand_dims(depth, axis=axis), axis=axis).squeeze(axis)
    rgb = colors[selected].astype(np.float32)
    normalized = depth.astype(np.float32) / max(1, source_mask.shape[axis] - 1)
    shade = 1.0 - 0.24 * normalized
    rgb *= shade[..., None]
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    rgb[~visible] = BACKGROUND
    return rgb


def _orient(image: np.ndarray, axis: int) -> np.ndarray:
    if axis in (1, 2):
        return np.flipud(image)
    return image


def _framed(raw: np.ndarray, title: str, max_size: int = 1400) -> Image.Image:
    image = Image.fromarray(raw, mode="RGB")
    scale = max(2, min(8, max_size // max(1, max(image.size))))
    image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    header = 42
    canvas = Image.new("RGB", (image.width, image.height + header), (28, 31, 35))
    canvas.paste(image, (0, header))
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 9), title, fill=(245, 245, 245), font=_font(18))
    return canvas


def render_building(
    schematic: SchematicData,
    screenshot_path: Path,
    output_dir: Path,
    building_id: str,
    summary_lines: Iterable[str],
) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    nonair = schematic.nonair_mask()
    colors = palette_colors(schematic)
    definitions = [
        ("z_min", 1, False),
        ("z_max", 1, True),
        ("x_min", 2, False),
        ("x_max", 2, True),
        ("top", 0, True),
        ("bottom", 0, False),
    ]
    framed_views: List[Tuple[str, Image.Image]] = []
    paths: Dict[str, str] = {}
    for name, axis, reverse in definitions:
        raw = _orient(project(schematic.volume, nonair, axis, reverse, colors), axis)
        framed = _framed(raw, f"{building_id} / {name}")
        target = output_dir / f"{name}.png"
        framed.save(target, optimize=True)
        paths[name] = str(target)
        framed_views.append((name, framed))

    cell_w, cell_h = 620, 390
    sheet = Image.new("RGB", (cell_w * 4, cell_h * 2), (20, 22, 25))
    original = Image.open(screenshot_path).convert("RGB")
    original.thumbnail((cell_w - 20, cell_h - 52), Image.Resampling.LANCZOS)
    original_frame = Image.new("RGB", (cell_w, cell_h), (28, 31, 35))
    original_frame.paste(original, ((cell_w - original.width) // 2, 42))
    ImageDraw.Draw(original_frame).text((12, 9), f"{building_id} / source", fill="white", font=_font(18))
    sheet.paste(original_frame, (0, 0))

    for index, (name, view) in enumerate(framed_views):
        thumb = view.copy()
        thumb.thumbnail((cell_w - 20, cell_h - 20), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (cell_w, cell_h), (28, 31, 35))
        frame.paste(thumb, ((cell_w - thumb.width) // 2, (cell_h - thumb.height) // 2))
        col = (index + 1) % 4
        row = (index + 1) // 4
        sheet.paste(frame, (col * cell_w, row * cell_h))

    summary = Image.new("RGB", (cell_w, cell_h), (34, 38, 42))
    draw = ImageDraw.Draw(summary)
    draw.text((18, 14), "G0/G1 summary", fill=(245, 245, 245), font=_font(22))
    y = 55
    for line in summary_lines:
        draw.text((18, y), str(line), fill=(215, 220, 224), font=_font(16))
        y += 29
    sheet.paste(summary, (3 * cell_w, cell_h))

    overview = output_dir / "overview.png"
    sheet.save(overview, optimize=True)
    paths["overview"] = str(overview)
    return paths


def render_contact_sheet(items: List[Tuple[str, Path]], target: Path) -> None:
    cell_w, cell_h = 900, 330
    cols = 2
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cell_w * cols, cell_h * rows), (18, 20, 22))
    for index, (building_id, path) in enumerate(items):
        image = Image.open(path).convert("RGB")
        image.thumbnail((cell_w - 16, cell_h - 38), Image.Resampling.LANCZOS)
        x = (index % cols) * cell_w
        y = (index // cols) * cell_h
        sheet.paste(image, (x + (cell_w - image.width) // 2, y + 34))
        ImageDraw.Draw(sheet).text((x + 10, y + 7), building_id, fill="white", font=_font(18))
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target, quality=92, optimize=True)

