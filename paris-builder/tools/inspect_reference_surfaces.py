"""Coordinate maps for source decomposition; cubes locate cells, not block models."""
from pathlib import Path
import sys
import json
import hashlib
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from paris_builder.schematic import load_schematic
from paris_builder.render import project, palette_colors
from paris_builder.exporter import dump_json


def main():
    out = ROOT / 'runs/REFERENCE-DECOMPOSITION-v1'
    out.mkdir(parents=True, exist_ok=True)
    for key, name, side in [('street3', '巴黎民居街区3', 'south'),
                            ('building2', '巴黎建筑素材2', 'north')]:
        path = ROOT.parent / '巴黎建筑素材' / (name + '.schem')
        data = load_schematic(path)
        raw = np.flipud(project(data.volume, data.nonair_mask(), 1,
                                side == 'south', palette_colors(data)))
        scale, margin = 8, 40
        im = Image.new('RGB', (data.width * scale + margin * 2,
                              data.height * scale + margin * 2), '#ecf1f4')
        im.paste(Image.fromarray(raw).resize((data.width * scale, data.height * scale),
                                           Image.Resampling.NEAREST), (margin, margin))
        draw = ImageDraw.Draw(im)
        for x in range(0, data.width, 5):
            px = margin + x * scale
            draw.line((px, margin, px, im.height - margin), fill='#9caaa8')
            draw.text((px, 18), str(x), fill='black')
        for y in range(0, data.height, 5):
            py = margin + (data.height - y) * scale
            draw.line((margin, py, im.width - margin, py), fill='#9caaa8')
            draw.text((4, py - 5), str(y), fill='black')
        draw.text((margin, im.height - 18), key + ': x increases right; y increases up; ' + side, fill='black')
        im.save(out / (key + '-coordinates.png'))
        dump_json(out / (key + '-surface.json'), {
            'source': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'dimensions_whd': [data.width, data.height, data.length],
            'palette_zero': data.id_to_state[0], 'air_ids': data.air_ids.tolist(),
            'nonair': int(data.nonair_mask().sum()),
            'top_blocks': data.base_block_counts().most_common(30),
            'x_stateful': [int(sum('[' in data.id_to_state[int(v)] for v in data.volume[:, :, x].ravel()))
                           for x in range(data.width)]})
        print(key, path.name, 'written', flush=True)


if __name__ == '__main__':
    main()
