#!/usr/bin/env python3
"""Propose a cleaned prepared derivative: clear residual alpha haze (alpha 1..31) to alpha 0, change nothing else.

Deterministic, Pillow only. Every pixel with alpha >= 32 is preserved exactly (RGBA); pixels with alpha 1..31 get
alpha 0 with their RGB left as stored. No redraw, recolor, resample, resize or metadata edit. Writes the proposed file
and a lineage JSON beside it; never touches the Idea Queue, Drive, the staging root or the campaign root.

usage: alpha_clean.py --source <approved derivative png> --out <proposed png> --lineage <json> \
       --master-id <Drive id of the canonical creative master> --master-name <name> --source-id <Drive id of the source derivative>
"""
import argparse, datetime, hashlib, json, os, sys
from PIL import Image

HAZE_MAX = 31


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("--source", "--out", "--lineage", "--master-id", "--master-name", "--source-id"): ap.add_argument(name, required=True)
    a = ap.parse_args(argv)
    if os.path.exists(a.out) or os.path.exists(a.lineage):
        print(json.dumps({"result": "REFUSED", "detail": "output already exists; never overwritten"})); return 1
    src = Image.open(a.source); mode, size = src.mode, src.size
    if mode != "RGBA":
        print(json.dumps({"result": "REFUSED", "detail": f"source mode is {mode}, not RGBA; nothing to clean"})); return 1
    r, g, b, al = src.split(); hist = al.histogram()
    cleared = sum(hist[1:HAZE_MAX + 1]); kept_opaque = hist[255]; kept_partial = sum(hist[HAZE_MAX + 1:255]); zero = hist[0]
    al2 = al.point(lambda v: 0 if 0 < v <= HAZE_MAX else v)
    out = Image.merge("RGBA", (r, g, b, al2))
    # verification before writing: every pixel with alpha >= 32 identical in RGBA; every pixel with alpha 1..31 now 0 with RGB unchanged
    src_px, out_px = src.load(), out.load(); changed = 0; w, h = size
    for y in range(h):
        for x in range(w):
            s_, o_ = src_px[x, y], out_px[x, y]
            if s_[3] > HAZE_MAX: assert s_ == o_, (x, y, s_, o_)
            elif s_[3] > 0: assert o_ == (s_[0], s_[1], s_[2], 0), (x, y, s_, o_); changed += 1
            else: assert s_ == o_
    assert changed == cleared
    out.save(a.out, format="PNG"); back = Image.open(a.out); assert back.mode == "RGBA" and back.size == size and list(back.getdata()) == list(out.getdata())
    lineage = {"proposed_file": os.path.basename(a.out), "status": "PROPOSED — requires human approval and 1901-stage-render-source staging before it can be a render source",
               "created_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
               "lineage": {"canonical_creative_master": {"drive_file_id": a.master_id, "filename": a.master_name},
                           "prepared_from": {"drive_file_id": a.source_id, "filename": os.path.basename(a.source), "sha256": sha256_of(a.source)}},
               "operation": f"alpha in 1..{HAZE_MAX} set to 0; RGB of those pixels unchanged; every pixel with alpha >= {HAZE_MAX + 1} preserved exactly; no redraw, recolor, sharpen, resize or resample",
               "size": list(size), "mode": mode, "pixels": {"total": w * h, "alpha_0_before": zero, "alpha_1_31_cleared": cleared, "alpha_32_254_preserved": kept_partial, "alpha_255_preserved": kept_opaque, "alpha_0_after": zero + cleared},
               "alpha_histogram_cleared": {str(v): hist[v] for v in range(1, HAZE_MAX + 1) if hist[v]},
               "sha256": {"source": sha256_of(a.source), "proposed": sha256_of(a.out)}, "tool": "1901-listing-studio/tools/alpha_clean.py"}
    json.dump(lineage, open(a.lineage, "w", encoding="utf-8"), indent=2)
    print(json.dumps({"result": "PROPOSED", **{k: lineage[k] for k in ("proposed_file", "pixels", "sha256")}}, indent=1)); return 0


if __name__ == "__main__":
    sys.exit(main())
