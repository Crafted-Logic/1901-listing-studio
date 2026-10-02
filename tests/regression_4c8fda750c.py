"""Regression fixtures: the five Scene 1 hero attempts of failed render job 4c8fda750c (1901-093), rejected
by the pre-patch detector with fill ratios 0.23-0.37 because unrelated magenta/purple background pixels
contaminated the global extrema. Read-only on the failed job: scenes and the source art are read, composites
are built in memory and QA'd in a temporary directory, nothing is written to the campaign root, no provider
is constructed, no generation call is possible. Skipped (exit 0, with a note) when the artifacts are absent."""
import json, os, sys, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
from PIL import Image
from studio import compositor, qa, config

JOB = os.path.join(config.CAMPAIGN_ROOT, "_failed", "1901-093-4c8fda750c")
SCENES = ["01-hero-base.png"] + [f"01-hero-rejected-{i}.png" for i in range(1, 5)]
PRE_PATCH = {"01-hero-base.png": 0.33, "01-hero-rejected-1.png": 0.31, "01-hero-rejected-2.png": 0.24, "01-hero-rejected-3.png": 0.23, "01-hero-rejected-4.png": 0.37}
ART = os.path.join(JOB, "source", "1901-093-B-transparent-prep-v2.png")
PRODUCT = {"blank": "Unisex Heavy Cotton Tee", "provider": "Printify Choice", "color": "Black", "garment_rgb": [0, 0, 0], "spec_source": "regression fixture"}


def main():
    if not os.path.isdir(JOB) or not os.path.isfile(ART):
        print(f"SKIP: failed-job artifacts not present at {JOB}"); return 0
    before = sorted(os.path.join(d, f) for d, _, fs in os.walk(config.CAMPAIGN_ROOT) for f in fs)
    stat_before = {p: os.stat(p).st_mtime_ns for p in before}
    tmp = tempfile.mkdtemp(prefix="rg-4c8fda750c-")
    rows = []
    try:
        for name in SCENES:
            path = os.path.join(JOB, "generated-scenes", name)
            scene = Image.open(path).convert("RGB")
            quad, info = compositor.find_marker_quad(scene)
            assert quad is not None, (name, info)
            comp = info["components"]
            assert comp["plausible"] == 1 and comp["ignored_pixels"] > 0 and info["fill_ratio"] >= 0.85, (name, info)
            # background chroma must not move the quad: blank out every non-selected marker-coloured pixel and re-detect
            mask, _ = compositor.isolate_marker(scene); full = compositor.marker_mask(scene)
            from PIL import ImageChops
            other = ImageChops.subtract(full.convert("L"), mask.convert("L"))
            cleaned = Image.composite(Image.new("RGB", scene.size, (40, 40, 40)), scene, other)
            quad2, info2 = compositor.find_marker_quad(cleaned)
            assert quad2 == quad and info2["pixels"] == info["pixels"] and info2["components"]["ignored_pixels"] == 0, (name, "background pixels influenced the quad")
            removal, _g = compositor.grow_removal_mask(scene, mask)
            ring = compositor.ring_stats(scene, removal)                 # the ring is measured outside the fringe-aware removal mask, as the compositor does
            ring_ok, ring_why, ring_rule = compositor.ring_acceptable(ring)
            assert ring_ok, (name, ring, ring_why)                       # dark-garment rule (review after 735f67d): all five real black-shirt rings are reconstructable
            final, placement = compositor.composite(open(path, "rb").read(), ART, PRODUCT["garment_rgb"])
            base_p = os.path.join(tmp, name); final_p = os.path.join(tmp, "final-" + name)
            shutil.copyfile(path, base_p); final.save(final_p, "PNG")
            result, checks, _ = qa.check_image(1, "hero_lifestyle", base_p, final_p, ART, placement, PRODUCT, scene.size)
            det = {k: v for k, v in checks.items() if v["method"] == "deterministic"}
            failed = [k for k, v in det.items() if v["result"] != "PASS"]
            assert result == "PASS" and not failed and placement["placeholder"]["fill_ratio"] == info["fill_ratio"] and placement["ring"]["rule"] == ring_rule, (name, failed, {k: det[k]["detail"] for k in failed})
            rec = placement["reconstruction"]
            assert rec["continuity"]["ok"] and rec["texture"]["patches"] > 0 and rec["removal"]["grown_pixels"] > 0 and len(rec["removal"]["passes"]) <= 3, rec
            assert checks["no_marker_fringe"]["result"] == "PASS" and checks["bounded_shading"]["result"] == "PASS", checks["no_marker_fringe"]["detail"]
            outcome = f"ring {ring_rule}; fringe grown {rec['removal']['grown_pixels']} px; continuity {rec['continuity']['delta']:+} (tol {rec['continuity']['tolerance']}); shade med {rec['shading']['median_modulation']} min {rec['shading']['min_modulation']}; composite+QA {result}"
            rows.append((name, PRE_PATCH[name], info["fill_ratio"], info["pixels"], comp["total"], comp["ignored_pixels"], outcome))
        print(f"{'scene':24} {'pre-patch fill':>14} {'fill now':>9} {'marker px':>10} {'comps':>6} {'ignored px':>10}  outcome")
        for r in rows:
            print(f"{r[0]:24} {r[1]:>14.2f} {r[2]:>9.3f} {r[3]:>10} {r[4]:>6} {r[5]:>10}  {r[6]}")
        assert all(r[2] >= 0.85 for r in rows)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    after = sorted(os.path.join(d, f) for d, _, fs in os.walk(config.CAMPAIGN_ROOT) for f in fs)
    assert after == before and all(os.stat(p).st_mtime_ns == stat_before[p] for p in before), "campaign root changed"
    assert sorted(os.listdir(config.CAMPAIGN_ROOT)) == sorted(set(p.split(os.sep)[len(config.CAMPAIGN_ROOT.rstrip(os.sep).split(os.sep))] for p in before)), "a new top-level entry appeared in the campaign root"
    print("REGRESSION PASS: five chest markers isolated (one plausible component each), all >= 0.85 fill, background chroma does not move the quad; all five rings accepted (dark-garment rule) and every composite passes deterministic QA; campaign root unchanged; no provider constructed, no generation call")
    return 0


if __name__ == "__main__":
    sys.exit(main())
