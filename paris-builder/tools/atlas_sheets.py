"""TECHNIQUE-ATLAS step 3: cross-source comparison sheets (collage of existing previews).

This tool does not decompose or render anything. It reads the two cut-piece libraries
(`knowledge/library-v3/reference-techniques`, `knowledge/library-v4/atlas-techniques`),
groups every piece into a technique category, and lays each category out as one PNG
sheet under `runs/TECHNIQUE-ATLAS-v0.1/sheets/`, plus a `_index.png` cover and a
`manifest.json`. Inputs are read-only; re-running regenerates the same outputs.

Scale rule
----------
Every library preview is rendered by `paris_builder.preview3d` with `max_size=700`,
i.e. each image is normalised so the *largest projected extent* of the piece is 600 px,
so raw previews are NOT at a common px-per-block. To unify, each piece's current
px-per-block is recovered by measuring the rendered content against the block-space
extent of its `inventory.dimensions_whd` bounding box under the same orthographic
camera, and the image is then rescaled to the category's target px-per-block. The
target is chosen so the category's median-sized piece renders at `--median-px`
pixels. Pieces wider than 40 blocks may render at half that scale and are labelled
`1/2 scale`.

View rule
---------
The street-side axonometric is preferred: pieces facing south/+z use
`axonometric_back` (camera on the -x/+z corner, sees south+west+top), pieces facing
north/-z use `axonometric_front` (camera on the +x/-z corner, sees north+east+top).
For corner pieces the first direction named in `outside` decides; if the preferred
file is missing the flat view and then the opposite axonometric are tried.

Labels are ASCII-only on purpose: the Windows-safe font policy in
`paris_builder.fonts` guarantees Latin glyphs, CJK system fonts can hard-crash.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from paris_builder.fonts import load_font  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

LIBRARIES = (
    'knowledge/library-v3/reference-techniques',
    'knowledge/library-v4/atlas-techniques',
)

# Cameras as in preview3d.render_previews.
CAMERAS = {
    'axonometric_front': (1.3, 0.8, -2.2),
    'axonometric_back': (-1.3, 0.85, 2.2),
    'front': (0, 0, -1),
    'back': (0, 0, 1),
    'left': (-1, 0, 0),
    'right': (1, 0, 0),
    'top': (0, 1, 0),
}

VIEW_FALLBACKS = {
    'axonometric_back': ('axonometric_back', 'back', 'axonometric_front', 'front',
                         'overview', 'left', 'right', 'top'),
    'axonometric_front': ('axonometric_front', 'front', 'axonometric_back', 'back',
                          'overview', 'right', 'left', 'top'),
}

# First direction token (by position in `outside`) decides the street side.
SIDE_TOKENS = (
    ('south', 'back'), ('+z', 'back'), ('南', 'back'),
    ('north', 'front'), ('-z', 'front'), ('北', 'front'),
    ('west', 'back'), ('-x', 'back'), ('西', 'back'),
    ('east', 'front'), ('+x', 'front'), ('东', 'front'),
)

CATEGORY_ORDER = ('corner', 'shopfront', 'window', 'dormer', 'chimney', 'cornice',
                  'balcony', 'pilaster', 'roof', 'base', 'entry', 'arch', 'tower',
                  'cresting', 'pediment', 'court', 'facade')

# Category by the id's second segment, per the brief: prow/pavilion/turret count as
# corner, parapet and storey-band as cornice, colonnade as pilaster, plain cresting
# its own. `s3-upper-balcony` (segment "upper") joins balcony. `base-shop` is the
# one base that belongs to shopfront; st1-base-entry/arcade stay base.
SEGMENT_CATEGORIES = {
    'corner': 'corner', 'prow': 'corner', 'pavilion': 'corner', 'turret': 'corner',
    'window': 'window', 'dormer': 'dormer', 'chimney': 'chimney',
    'cornice': 'cornice', 'parapet': 'cornice', 'storey': 'cornice',
    'balcony': 'balcony', 'upper': 'balcony',
    'pilaster': 'pilaster', 'colonnade': 'pilaster',
    'roof': 'roof', 'base': 'base', 'entry': 'entry', 'arch': 'arch',
    'tower': 'tower', 'cresting': 'cresting', 'pediment': 'pediment',
    'court': 'court', 'facade': 'facade',
}

PREVIEW_BG = (229, 235, 239)
SHEET_BG = (24, 27, 34)
CELL_BG = (33, 37, 47)
CELL_BORDER = (58, 64, 80)
TEXT_MAIN = (238, 241, 247)
TEXT_DIM = (170, 178, 192)

HALF_SCALE_MIN_WIDTH = 40
SPLIT_ABOVE = 12


def categorize(piece_id: str) -> str:
    if 'shopfront' in piece_id or piece_id.endswith('base-shop'):
        return 'shopfront'
    parts = piece_id.split('-')
    segment = parts[1] if len(parts) > 1 else ''
    if segment in SEGMENT_CATEGORIES:
        return SEGMENT_CATEGORIES[segment]
    raise ValueError('no category rule matches piece id %r' % piece_id)


def street_side(outside: str) -> str:
    """'back' (south/west-ish) or 'front' (north/east-ish), by first direction token."""
    best_pos, best_side = None, 'front'
    for token, side in SIDE_TOKENS:
        pos = outside.find(token)
        if pos >= 0 and (best_pos is None or pos < best_pos):
            best_pos, best_side = pos, side
    return best_side


def _camera_basis(camera):
    cx, cy, cz = camera
    norm = math.sqrt(cx * cx + cy * cy + cz * cz)
    cx, cy, cz = cx / norm, cy / norm, cz / norm
    hx, hy, hz = (0.0, 1.0, 0.0) if abs(cy) < 0.99 else (0.0, 0.0, -1.0)
    rx, ry, rz = hy * cz - hz * cy, hz * cx - hx * cz, hx * cy - hy * cx
    rnorm = math.sqrt(rx * rx + ry * ry + rz * rz)
    rx, ry, rz = rx / rnorm, ry / rnorm, rz / rnorm
    ux, uy, uz = cy * rz - cz * ry, cz * rx - cx * rz, cx * ry - cy * rx
    return (rx, ry, rz), (ux, uy, uz)


def projected_extent(dims, camera):
    """Block-space screen extent of the w/h/d bounding box under the orthographic camera."""
    (rx, ry, rz), (ux, uy, uz) = _camera_basis(camera)
    w, h, d = dims
    return (w * abs(rx) + h * abs(ry) + d * abs(rz),
            w * abs(ux) + h * abs(uy) + d * abs(uz))


def content_crop(image: Image.Image):
    """Crop to rendered content: the preview background is a flat colour, and the
    header/footer captions live outside the renderer's content band (y in [75, h-55])."""
    rgb = np.asarray(image.convert('RGB')).astype(np.int16)
    height, width = rgb.shape[:2]
    zone = np.zeros((height, width), dtype=bool)
    zone[60:max(61, height - 40), :] = True
    diff = (np.abs(rgb - np.array(PREVIEW_BG, dtype=np.int16))).max(axis=2) > 10
    ys, xs = np.where(diff & zone)
    if len(xs) == 0:
        return image.copy()
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    return image.crop(box)


def load_pieces():
    pieces = {}
    for library in LIBRARIES:
        root = ROOT / library
        for piece_dir in sorted(root.iterdir()):
            record_path = piece_dir / 'record.json'
            if not piece_dir.is_dir() or not record_path.is_file():
                continue
            record = json.loads(record_path.read_text(encoding='utf-8'))
            piece_id = record['id']
            if piece_id in pieces:
                raise ValueError('duplicate piece id %r across libraries' % piece_id)
            dims = record['inventory']['dimensions_whd']
            outside = record.get('outside') or ''
            side = street_side(outside)
            preferred = 'axonometric_back' if side == 'back' else 'axonometric_front'
            view, view_path = None, None
            for candidate in VIEW_FALLBACKS[preferred]:
                path = piece_dir / 'previews' / ('%s.png' % candidate)
                if path.is_file():
                    view, view_path = candidate, path
                    break
            extent = projected_extent(dims, CAMERAS[view]) if view else (1.0, 1.0)
            pieces[piece_id] = {
                'id': piece_id,
                'title': record.get('title', ''),
                'source_id': record.get('source_id', '?'),
                'dims': dims,
                'outside': outside,
                'library': library.split('/')[1],
                'category': categorize(piece_id),
                'view': view,
                'view_path': view_path,
                'view_fallback': view is not None and view != preferred,
                'extent': extent,
                'half_scale': dims[0] > HALF_SCALE_MIN_WIDTH,
            }
    return pieces


def measure_piece(piece):
    """Open the chosen preview, crop to content, estimate its current px-per-block."""
    with Image.open(piece['view_path']) as image:
        crop = content_crop(image)
    ex, ey = piece['extent']
    scale_est = max(crop.width / ex, crop.height / ey)
    fit = max(crop.width / ex, crop.height / ey) / max(0.01, min(crop.width / ex, crop.height / ey))
    return crop, scale_est, fit


def scaled_cell_image(piece, crop, scale_est, px_per_block):
    target = px_per_block * (0.5 if piece['half_scale'] else 1.0)
    factor = target / scale_est
    size = (max(1, round(crop.width * factor)), max(1, round(crop.height * factor)))
    return crop.resize(size, Image.Resampling.LANCZOS)


def grid_columns(count: int) -> int:
    if count <= 2:
        return max(count, 1)
    if count <= 4:
        return 2
    if count <= 9:
        return 3
    return 4


def render_sheet(title: str, subtitle: str, cells, out_path: Path, fonts) -> tuple:
    """cells: list of (PIL image, [label lines]). Returns (width, height)."""
    pad, margin, title_h = 18, 28, 82
    line_heights = (24, 17, 17)
    label_h = sum(line_heights) + 12
    img_w = max(cell[0].width for cell in cells)
    img_h = max(cell[0].height for cell in cells)
    cell_w = max(img_w, 300) + 2 * pad
    cell_h = img_h + label_h + 2 * pad
    columns = grid_columns(len(cells))
    rows = math.ceil(len(cells) / columns)
    width = columns * cell_w + 2 * margin
    probe = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    for text, font in ((title, fonts['title']), (subtitle, fonts['meta'])):
        width = max(width, math.ceil(probe.textlength(text, font=font)) + 2 * margin)
    sheet = Image.new('RGB', (width, title_h + rows * cell_h + margin), SHEET_BG)
    draw = ImageDraw.Draw(sheet)
    draw.text((margin, 20), title, font=fonts['title'], fill=TEXT_MAIN)
    draw.text((margin, 52), subtitle, font=fonts['meta'], fill=TEXT_DIM)
    for index, (image, lines) in enumerate(cells):
        row, col = divmod(index, columns)
        x0, y0 = margin + col * cell_w, title_h + row * cell_h
        draw.rectangle([x0 + 4, y0 + 4, x0 + cell_w - 5, y0 + cell_h - 5],
                       fill=CELL_BG, outline=CELL_BORDER)
        sheet.paste(image, (x0 + (cell_w - image.width) // 2,
                            y0 + pad + (img_h - image.height) // 2))
        ty = y0 + pad + img_h + 12
        for line_index, line in enumerate(lines):
            font = fonts['id'] if line_index == 0 else fonts['meta']
            fill = TEXT_MAIN if line_index == 0 else TEXT_DIM
            draw.text((x0 + 14, ty + sum(line_heights[:line_index])), line, font=font, fill=fill)
    sheet.save(out_path, optimize=True)
    return sheet.size


def cell_labels(piece):
    w, h, d = piece['dims']
    flags = piece['view'].replace('axonometric_', 'axo-')
    if piece['view_fallback']:
        flags += ' (fallback)'
    if piece['half_scale']:
        flags += ' | 1/2 scale'
    return [piece['id'], '%s | %dx%dx%d' % (piece['source_id'], w, h, d), flags]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default=str(ROOT / 'runs' / 'TECHNIQUE-ATLAS-v0.1'),
                        help='run directory; sheets go into <out>/sheets/')
    parser.add_argument('--median-px', type=float, default=300.0,
                        help='rendered px size of the median piece of each category')
    parser.add_argument('--min-ppb', type=float, default=4.0)
    parser.add_argument('--max-ppb', type=float, default=28.0)
    args = parser.parse_args()

    fonts = {'title': load_font(22), 'id': load_font(18), 'meta': load_font(12)}

    pieces = load_pieces()
    categories = {name: [] for name in CATEGORY_ORDER}
    for piece in pieces.values():
        categories[piece['category']].append(piece)
    for group in categories.values():
        group.sort(key=lambda p: (p['source_id'], p['id']))

    # Measure every piece once (crop + current px-per-block) and cache it.
    missing, fallbacks, loose_fit = [], [], []
    for piece in pieces.values():
        if piece['view'] is None:
            missing.append(piece['id'])
            continue
        crop, scale_est, fit = measure_piece(piece)
        piece['crop'], piece['scale_est'] = crop, scale_est
        if piece['view_fallback']:
            fallbacks.append('%s -> %s' % (piece['id'], piece['view']))
        if fit > 1.25:
            loose_fit.append('%s (x/y extent ratio %.2f)' % (piece['id'], fit))

    out_dir = Path(args.out) / 'sheets'
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        'run': Path(args.out).name,
        'tool': 'tools/atlas_sheets.py',
        'libraries': list(LIBRARIES),
        'pieces_total': len(pieces),
        'scale_rule': ('uniform px-per-block per category; baseline = median piece rendered at '
                       '%g px; width > %d blocks renders at 1/2 scale (labelled)'
                       % (args.median_px, HALF_SCALE_MIN_WIDTH)),
        'view_rule': ('street-side axonometric: south/+z/west -> axonometric_back, '
                      'north/-z/east -> axonometric_front; flat view as fallback'),
        'sort_rule': 'cells sorted by source_id then id',
        'categories': [],
        'sheets': [],
        'missing_previews': missing,
        'view_fallbacks': fallbacks,
        'loose_bbox_pieces': loose_fit,
    }

    index_cells = {}
    for category in CATEGORY_ORDER:
        group = categories[category]
        if not group:
            continue
        ids = [p['id'] for p in group]
        # Median baseline on effective (half-adjusted) projected extent.
        metric = [max(p['extent']) * (0.5 if p['half_scale'] else 1.0) for p in group]
        median = statistics.median(metric)
        ppb = min(max(args.median_px / median, args.min_ppb), args.max_ppb)
        for piece, m in zip(group, metric):
            piece['metric'] = m

        chunks = [group] if len(group) <= SPLIT_ABOVE else \
            [group[i:i + SPLIT_ABOVE] for i in range(0, len(group), SPLIT_ABOVE)]
        sheet_files = []
        for part, chunk in enumerate(chunks, start=1):
            name = category if len(chunks) == 1 else '%s-%d' % (category, part)
            cells = []
            for piece in chunk:
                image = scaled_cell_image(piece, piece['crop'], piece['scale_est'], ppb)
                cells.append((image, cell_labels(piece)))
            title = '%s - cross-source technique comparison' % category.upper()
            if len(chunks) > 1:
                title += ' (sheet %d/%d)' % (part, len(chunks))
            subtitle = ('%d items | unified %.1f px/block | street-side axonometric | '
                        'sorted by source, id' % (len(chunk), ppb))
            out_path = out_dir / ('%s.png' % name)
            size = render_sheet(title, subtitle, cells, out_path, fonts)
            sheet_files.append('sheets/%s.png' % name)
            manifest['sheets'].append({
                'file': 'sheets/%s.png' % name,
                'category': category,
                'part': part,
                'parts': len(chunks),
                'count': len(chunk),
                'ids': [p['id'] for p in chunk],
                'px_per_block': round(ppb, 2),
                'half_scale_ids': [p['id'] for p in chunk if p['half_scale']],
                'size_px': list(size),
            })
            print('sheet %-14s part %d/%d  n=%2d  ppb=%5.2f  -> %s'
                  % (category, part, len(chunks), len(chunk), ppb, out_path.name))

        manifest['categories'].append({
            'category': category,
            'count': len(group),
            'ids': ids,
            'sheets': sheet_files,
        })
        representative = min(group, key=lambda p: abs(p['metric'] - median))
        index_cells[category] = (representative, len(group), sheet_files)

    # Cover sheet: one representative per category, class name + piece count.
    cells = []
    for category in CATEGORY_ORDER:
        if category not in index_cells:
            continue
        piece, count, sheet_files = index_cells[category]
        crop, scale_est, _ = measure_piece(piece)
        thumb = crop.copy()
        thumb.thumbnail((280, 200), Image.Resampling.LANCZOS)
        sheet_note = sheet_files[0].split('/')[-1] if len(sheet_files) == 1 \
            else '%d sheets' % len(sheet_files)
        cells.append((thumb, [category, 'n=%d | %s' % (count, sheet_note),
                              'rep: %s' % piece['id']]))
    index_path = out_dir / '_index.png'
    size = render_sheet('TECHNIQUE ATLAS v0.1 - cross-source comparison sheets',
                        '%d categories | %d pieces | one representative per category'
                        % (len(index_cells), len(pieces)),
                        cells, index_path, fonts)
    manifest['sheets'].append({
        'file': 'sheets/_index.png', 'category': '_index', 'part': 1, 'parts': 1,
        'count': len(index_cells),
        'ids': [index_cells[c][0]['id'] for c in CATEGORY_ORDER if c in index_cells],
        'px_per_block': None, 'half_scale_ids': [], 'size_px': list(size),
    })
    print('sheet _index        n=%2d categories -> _index.png' % len(index_cells))

    manifest_path = out_dir / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                             encoding='utf-8')
    print('manifest -> %s' % manifest_path)
    if missing:
        print('WARNING missing previews: %s' % ', '.join(missing))
    if fallbacks:
        print('NOTE view fallbacks: %s' % ', '.join(fallbacks))
    if loose_fit:
        print('NOTE loose bbox (mesh smaller than w/h/d box, scale slightly large): %s'
              % ', '.join(loose_fit))


if __name__ == '__main__':
    main()
