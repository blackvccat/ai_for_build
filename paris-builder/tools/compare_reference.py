"""Put a reference elevation beside a generated design at the same scale.

The workflow requires comparing every generation against the standard reference images.
Doing that by opening two files and remembering one of them is how a facade drifts: the
eye adapts. This builds one image with a strip of the reference above a strip of the
generated elevation, scaled so a block is the same size in both, and prints the numbers
each side was built from.

The reference renders are of the user's own builds. `标准_巴黎民居街区3` is a street wall
200 blocks long and 50 tall; the scale below is derived from the known build dimensions,
so the comparison is at true relative size rather than at whatever looks convenient.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from paris_builder import design  # noqa: E402
from paris_builder.exporter import write_schematic  # noqa: E402
from paris_builder.fonts import load_font  # noqa: E402
from paris_builder.preview3d import render_previews  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT.parent / '参考图'

#: Reference builds and their measured envelope, from the measurement of the sources.
REFERENCES = {
    'street3': ('标准_巴黎民居街区3_外立面_正视.png', 200, 50),
    'street3_axo': ('标准_巴黎民居街区3_外立面_轴测.png', 200, 50),
    'material2': ('标准_巴黎建筑素材2_外立面_正视.png', None, None),
    'material2_axo': ('标准_巴黎建筑素材2_外立面_轴测.png', None, None),
}


def reference_strip(name: str, blocks_wide: int, blocks_high: int, target_px_per_block: float,
                    x_frac: float = 0.0, crop_blocks: int = 60, crop_top: float = 0.0,
                    crop_bottom: float = 1.0):
    """A crop of the reference, scaled so one block is `target_px_per_block` pixels.

    The crop is given in *blocks*, not pixels: the point of the comparison is to see the
    same number of houses at the same size, so the window of the reference has to be
    chosen in the units the design is built in.
    """
    path = ASSETS / REFERENCES[name][0]
    image = Image.open(path).convert('RGB')
    px_per_block = None
    strip = image
    if blocks_wide and blocks_high:
        # The build fills the frame horizontally in these renders, so the scale follows
        # from the known envelope rather than from a guess.
        px_per_block = image.width / float(blocks_wide)
        crop_w = int(round(crop_blocks * px_per_block))
        crop_w = max(8, min(crop_w, image.width))
        x0 = int(x_frac * max(0, image.width - crop_w))
        y0 = int(crop_top * image.height)
        y1 = int(crop_bottom * image.height)
        strip = image.crop((x0, y0, x0 + crop_w, max(y0 + 8, y1)))
    if px_per_block:
        scale = target_px_per_block / px_per_block
        strip = strip.resize((max(1, int(strip.width * scale)),
                              max(1, int(strip.height * scale))),
                             Image.Resampling.NEAREST)
    return strip, px_per_block


def generated_strip(form: str, scheme: str, seed: int, width: int, depth: int,
                    storeys: int, work: Path, target_px_per_block: float,
                    max_size: int = 1800):
    """A render of one generated design, scaled to the same pixels-per-block."""
    plan = design.plan_for(form, seed=seed, scheme=scheme, width=width, depth=depth,
                           storeys=storeys)
    scene, manifest = design.build(plan)
    tag = '%s_%s' % (form, scheme)
    schem = work / ('%s.schem' % tag)
    write_schematic(schem, scene.volume, scene.palette, name=tag)
    paths = render_previews(schem, work / tag, max_size=max_size)
    render = Image.open(paths['front']).convert('RGB')
    # The render fits the model into its canvas; the model's width in blocks gives the
    # scale once the drawn extent is known. A margin of 50 px is the renderer's own.
    drawn = render.width - 100
    px_per_block = drawn / float(manifest['scene_whd'][0])
    scale = target_px_per_block / px_per_block
    render = render.resize((max(1, int(render.width * scale)), max(1, int(render.height * scale))),
                           Image.Resampling.NEAREST)
    return render, manifest, px_per_block, paths['front']


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='HOUSE-COMPARE-v0.1')
    parser.add_argument('--reference', default='street3', choices=sorted(REFERENCES))
    parser.add_argument('--form', default='street_house')
    parser.add_argument('--scheme', default='haussmann_apartment')
    parser.add_argument('--seed', type=int, default=1900)
    parser.add_argument('--width', type=int, default=14)
    parser.add_argument('--depth', type=int, default=28)
    parser.add_argument('--storeys', type=int, default=6)
    parser.add_argument('--px-per-block', type=float, default=6.0)
    parser.add_argument('--crop-blocks', type=int, default=60,
                        help='how much of the reference to show, in blocks')
    parser.add_argument('--x-frac', type=float, default=0.0,
                        help='where along the reference to start, 0..1')
    parser.add_argument('--crop-top', type=float, default=0.0)
    parser.add_argument('--crop-bottom', type=float, default=1.0)
    args = parser.parse_args()

    out = ROOT / 'runs' / args.run
    work = out / 'build'
    work.mkdir(parents=True, exist_ok=True)

    blocks_wide, blocks_high = REFERENCES[args.reference][1], REFERENCES[args.reference][2]
    ref, ref_scale = reference_strip(args.reference, blocks_wide, blocks_high,
                                     args.px_per_block, args.x_frac, args.crop_blocks,
                                     args.crop_top, args.crop_bottom)
    gen, manifest, gen_scale, gen_path = generated_strip(
        args.form, args.scheme, args.seed, args.width, args.depth, args.storeys, work,
        args.px_per_block)

    width = max(ref.width, gen.width)
    band = 24
    sheet = Image.new('RGB', (width, ref.height + gen.height + band * 2 + 8),
                      (229, 235, 239))
    draw = ImageDraw.Draw(sheet)
    font = load_font(13)
    draw.text((6, 4), 'REFERENCE  %s  (%.2f px/block)' % (args.reference, args.px_per_block),
              font=font, fill=(20, 28, 34))
    sheet.paste(ref, (0, band))
    y = band + ref.height + band
    draw.text((6, y - band + 4),
              'GENERATED  %s + %s  %dx%d  storeys=%d' % (args.form, args.scheme, args.width,
                                                         args.depth, args.storeys),
              font=font, fill=(20, 28, 34))
    sheet.paste(gen, (0, y))
    path = out / ('compare_%s.png' % args.reference)
    sheet.save(path, optimize=True)
    print('reference scale: %.3f px/block   generated scale: %.3f px/block'
          % (ref_scale or 0, gen_scale))
    print('generated render: %s' % gen_path)
    print('comparison: %s' % path.resolve())
    print('generated techniques: %s' % manifest['techniques'])
    return


if __name__ == '__main__':
    raise SystemExit(main())
