#!/usr/bin/env python3
"""Propose a defringed prepared derivative: replace background-contaminated RGB in semi-transparent edge pixels with
colour derived from the adjacent solid artwork; alpha unchanged; solid pixels byte-identical.

Deterministic, Pillow only. For every pixel with 0 < alpha < 255 a reference colour is the normalised box-convolution
of the SOLID content's RGB (alpha == 255) at the smallest radius in RADII that reaches it (i.e. the mean of the nearest
solid artwork). The pixel's RGB is replaced by that reference only when the pixel is lighter than the reference by more
than CONTAMINATION_MARGIN luminance levels (the signature of the removed light background bleeding into the edge);
soft pixels that are not lighter than their surroundings (glows, highlights) are left as drawn. Alpha is never changed.
No redraw, resample, sharpen or recolour of solid content. Writes the proposed file and a lineage JSON; never overwrites.

usage: defringe.py --source <v3 png> --out <v4 png> --lineage <json> --master-id ID --master-name NAME --source-id ID --source-name NAME
"""
import argparse, datetime, hashlib, json, os, sys
from PIL import Image, ImageChops, ImageFilter, ImageMath

RADII = (3, 6, 12, 24, 48)
CONTAMINATION_MARGIN = 8.0


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()


def reference_colour(rgb, solid_mask):
    """Per-channel mean of solid content near each pixel: normalised box convolution on 8-bit planes (BoxBlur supports L only),
    smallest covering radius wins; a radius covers a pixel when at least 5% of its window is solid content."""
    ref = Image.new("RGB", rgb.size, (0, 0, 0)); covered = Image.new("L", rgb.size, 0)
    for r in RADII:
        wsum = solid_mask.filter(ImageFilter.BoxBlur(r))                                   # 255 x coverage
        chans = []
        for ch in rgb.split():
            num = ImageChops.multiply(ch, solid_mask).filter(ImageFilter.BoxBlur(r))      # mean(ch over solid) x coverage
            chans.append(ImageMath.lambda_eval(lambda e: e["convert"](e["a"] * 255 / e["max"](e["b"], 1), "L"), a=num.convert("F"), b=wsum.convert("F")))
        this = Image.merge("RGB", chans); has = wsum.point(lambda v: 255 if v >= 13 else 0)
        new = ImageChops.multiply(has, ImageChops.invert(covered))
        ref = Image.composite(this, ref, new); covered = ImageChops.lighter(covered, new)
    return ref, covered


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("--source", "--out", "--lineage", "--master-id", "--master-name", "--source-id", "--source-name"): ap.add_argument(name, required=True)
    a = ap.parse_args(argv)
    if os.path.exists(a.out) or os.path.exists(a.lineage):
        print(json.dumps({"result": "REFUSED", "detail": "output already exists; never overwritten"})); return 1
    src = Image.open(a.source)
    if src.mode != "RGBA":
        print(json.dumps({"result": "REFUSED", "detail": f"source mode is {src.mode}, not RGBA"})); return 1
    w, h = src.size; r, g, b, al = src.split(); rgb = Image.merge("RGB", (r, g, b))
    solid = al.point(lambda v: 255 if v == 255 else 0); soft = al.point(lambda v: 255 if 0 < v < 255 else 0)
    ref, covered = reference_colour(rgb, solid)
    lum = rgb.convert("L"); ref_lum = ref.convert("L")
    lighter = ImageMath.lambda_eval(lambda e: e["convert"]((e["a"] - e["b"]) > CONTAMINATION_MARGIN, "L"), a=lum.convert("F"), b=ref_lum.convert("F")).point(lambda v: 255 if v else 0)
    replace = ImageChops.multiply(ImageChops.multiply(soft, lighter), covered)
    out_rgb = Image.composite(ref, rgb, replace)
    out = Image.merge("RGBA", (*out_rgb.split(), al))
    # verification before writing
    sp, op, rp, ap_ = src.load(), out.load(), replace.load(), al.load(); changed = 0; max_d = 0
    dist = {}
    for d in (1, 2, 3, 4, 6, 8, 12, 16, 24, 32):
        dist[d] = solid.filter(ImageFilter.MaxFilter(2 * d + 1))
    for y in range(h):
        for x in range(w):
            s_, o_ = sp[x, y], op[x, y]
            assert s_[3] == o_[3], "alpha changed"
            if s_[3] == 255 or s_[3] == 0: assert s_ == o_, (x, y, s_, o_)
            elif rp[x, y]:
                changed += 1
                if s_[:3] != o_[:3]:
                    for d in sorted(dist):
                        if dist[d].getpixel((x, y)): max_d = max(max_d, d); break
                    else: max_d = max(max_d, 33)
            else: assert s_ == o_
    out.save(a.out, format="PNG"); back = Image.open(a.out); assert back.mode == "RGBA" and back.size == (w, h) and list(back.getdata()) == list(out.getdata())
    hist = al.histogram(); n_soft = sum(hist[1:255])
    lineage = {"proposed_file": os.path.basename(a.out), "status": "PROPOSED — requires human approval and 1901-stage-render-source staging before it can be a render source",
               "created_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
               "lineage": {"canonical_creative_master": {"drive_file_id": a.master_id, "filename": a.master_name},
                           "prepared_from": {"drive_file_id": a.source_id, "filename": a.source_name, "sha256": sha256_of(a.source), "note": "v3 (haze cleanup, alpha 1..31 -> 0) is the direct source; v2 is v3's source"}},
               "operation": f"soft-edge defringe: for pixels with 0 < alpha < 255 that are lighter than the mean of the nearest solid artwork by more than {CONTAMINATION_MARGIN} luminance levels, RGB replaced by that mean (normalised box convolution, radii {RADII}); alpha unchanged for every pixel; solid (alpha 255) and transparent (alpha 0) pixels byte-identical; no redraw, resample, sharpen or recolour of solid content",
               "size": [w, h], "mode": "RGBA",
               "pixels": {"total": w * h, "alpha_255_solid": hist[255], "alpha_0": hist[0], "soft_edge_alpha_1_254": n_soft, "soft_edge_rgb_replaced": changed, "soft_edge_rgb_kept": n_soft - changed, "alpha_values_changed": 0, "max_distance_from_solid_content_px": max_d},
               "sha256": {"source": sha256_of(a.source), "proposed": sha256_of(a.out)}, "tool": "1901-listing-studio/tools/defringe.py"}
    json.dump(lineage, open(a.lineage, "w", encoding="utf-8"), indent=2)
    print(json.dumps({"result": "PROPOSED", **{k: lineage[k] for k in ("proposed_file", "pixels", "sha256")}}, indent=1)); return 0


if __name__ == "__main__":
    sys.exit(main())
