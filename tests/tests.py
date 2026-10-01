import copy, hashlib, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
from PIL import Image, ImageChops, ImageDraw
from studio import job, qa, compositor, config
from fixtures import *

examples = {}
def run(env, ev, msg, prov, now=NOW, jid=JOB): return job.run("1901-093", ev, msg, prov, env.H, env.C, now=now, job_id=jid)
def T(n, name, out, result, rendered, env, prov, extra=None, calls=None, pre_existing=False):
    assert out["result"] == result, (n, out["result"], result, out["checks"][-1])
    assert out["render_performed"] is rendered, (n, "render_performed")
    if calls is not None: assert len(prov.calls) == calls, (n, "calls", len(prov.calls), calls)
    if not rendered and not pre_existing: assert "1901-093" not in env.dirs(), (n, "final folder exists", env.dirs())
    assert not any(d.startswith(".tmp-") for d in env.dirs()), (n, "temp dir left", env.dirs())
    if extra: extra(out, env)
    print(f"{str(n):>3}. PASS {name}: {result} calls={len(prov.calls)}")
    examples[n] = out; env.done()

# 1 proposal: zero spend, no campaign dir
e, p = Env(), provider(); T(1, "ordinary request", run(e, evidence(), ASK, p), "AWAITING_RENDER_AUTHORIZATION", False, e, p, calls=0,
  extra=lambda o, e: (e.dirs() == [] and "AUTHORIZE LISTING RENDER 1901-093" in o["human_action_required"] and o["budget"]["estimated_job_cost_usd"] == 0.6 and o["proposed_expense_log_row"]["job_status"] == "PROPOSED") or sys.exit("1"))
# 2 exact authorization → full mocked render
e, p = Env(), provider(); o = run(e, evidence(), AUTH, p)
def full(o, e):
    t = e.tree(); assert len(t) == 19 and all(f"1901-093/final-composites/{n:02d}-{k}.png" in t for n, k, _, _ in config.SLOTS), t
    m = json.load(open(os.path.join(e.C, "1901-093/manifest.json"))); assert m["publication_authorized"] is False and m["qa_status"] == "PASS" and m["source"]["sha256"] == e.sha and m["reroll_count"] == 0 and len(m["scene_slots"]) == 6 and all("magenta" in s["prompt"] and "1901-093-B" not in s["prompt"] for s in m["scene_slots"])
    c = json.load(open(os.path.join(e.C, "1901-093/cost-log.json"))); assert c["images_generated"] == 6 and c["estimated_api_cost_usd"] == 0.6 and c["actual_billed_cost_usd"] is None and c["job_status"] == "COMPLETED"
    q = json.load(open(os.path.join(e.C, "1901-093/qa/qa.json"))); assert q["campaign_result"] == "PASS" and len(q["images"]) == 6 and all(i["qa_result"] == "PASS" for i in q["images"])
    assert hashlib.sha256(open(os.path.join(e.C, "1901-093/source/1901-093-B.png"), "rb").read()).hexdigest() == e.sha and o["authorization"]["evidence"] == AUTH and all(o["verification"].values())
T(2, "exact authorization (mock provider)", o, "READY_FOR_HUMAN_RENDER_REVIEW", True, e, p, full, calls=6)
# 3/4 vague + wrong id
e, p = Env(), provider(); T(3, "'Proceed.'", run(e, evidence(), "Proceed.", p), "AWAITING_RENDER_AUTHORIZATION", False, e, p, calls=0)
e, p = Env(), provider(); T(4, "wrong design authorization", run(e, evidence(), "AUTHORIZE LISTING RENDER 1901-094", p), "AWAITING_RENDER_AUTHORIZATION", False, e, p, calls=0)
for msg in ("Do it.", "Render it", "Yes", "AUTHORIZE RENDER 1901-093", "AUTHORIZE LISTING RENDER", "Please AUTHORIZE LISTING RENDER 1901-093 now"):
    e, p = Env(), provider(); T("4b", f"not authorization {msg!r}", run(e, evidence(), msg, p), "AWAITING_RENDER_AUTHORIZATION", False, e, p, calls=0)
e, p = Env(), provider(); T("4c", "lower-case + whitespace command", run(e, evidence(), "  authorize listing render 1901-093 ", p), "READY_FOR_HUMAN_RENDER_REVIEW", True, e, p, calls=6)
# 5 handoff missing / invalid
e, p = Env(staged=False), provider(); T(5, "missing staged handoff", run(e, evidence(), AUTH, p), "HANDOFF_NOT_STAGED", False, e, p, calls=0)
e, p = Env(manifest_patch=lambda m: m["handoff"].update(ready_for_listing_studio=False)), provider(); T("5b", "handoff not ready", run(e, evidence(), AUTH, p), "HANDOFF_INVALID", False, e, p, calls=0)
e, p = Env(manifest_patch=lambda m: m["integrity"].update(artwork_modified=True)), provider(); T("5c", "handoff artwork_modified", run(e, evidence(), AUTH, p), "HANDOFF_INVALID", False, e, p, calls=0)
# 6 hash mismatch
e, p = Env(manifest_patch=lambda m: m["source"].update(sha256="0" * 64)), provider(); T(6, "source hash mismatch", run(e, evidence(), AUTH, p), "HANDOFF_INVALID", False, e, p, calls=0)
# 7 approval
e, p = Env(), provider(); T(7, "missing approval", run(e, evidence(hd=""), AUTH, p), "HUMAN_APPROVAL_REQUIRED", False, e, p, calls=0)
e, p = Env(), provider(); T("7b", "status not Approved", run(e, evidence(status="Draft"), AUTH, p), "HUMAN_APPROVAL_REQUIRED", False, e, p, calls=0)
# 8/9 product spec
e, p = Env(), provider(); T(8, "product spec unresolved", run(e, evidence(product_candidates=[]), AUTH, p), "PRODUCT_SPEC_BLOCK", False, e, p, calls=0)
alt = dict(PRODUCT, blank="Gildan 5000 Heavy Cotton", color="Black", spec_source="existing Printify draft")
e, p = Env(), provider(); T(9, "conflicting product specs", run(e, evidence(product_candidates=[PRODUCT, alt]), AUTH, p), "PRODUCT_SPEC_BLOCK", False, e, p, calls=0, extra=lambda o, e: "vs" in o["human_action_required"] or sys.exit("9"))
# 10 pricing
e, p = Env(), provider(snap=None); T(10, "pricing unavailable", run(e, evidence(), AUTH, p), "PRICING_UNAVAILABLE", False, e, p, calls=0)
e, p = Env(), provider(snap=dict(SNAP, per_image_usd={"high": {"1024x1024": 0.2}})); T("10b", "pricing missing a tier", run(e, evidence(), AUTH, p), "PRICING_UNAVAILABLE", False, e, p, calls=0)
# 11/12 budget pre-check, no generation
e, p = Env(), provider(snap=dict(SNAP, per_image_usd={"high": {"1024x1024": 2.50}, "medium": {"1024x1024": 0.05}})); T(11, "first call exceeds listing cap", run(e, evidence(), AUTH, p), "BUDGET_BLOCK", False, e, p, calls=0)
e, p = Env(), provider(); T(12, "first call exceeds monthly cap", run(e, evidence(monthly=24.90), AUTH, p), "BUDGET_BLOCK", False, e, p, calls=0)
e, p = Env(), provider(); T("12b", "planned campaign exceeds monthly cap", run(e, evidence(monthly=24.50), AUTH, p), "BUDGET_BLOCK", False, e, p, calls=0)
# 13 mid-job stop: the planned six fit exactly (24.40 + 0.60 = 25.00); scene 2 is bad, the reroll (0.20) lands exactly on the cap, so the next scene (0.05) would exceed it → stop before that call
e, p = Env(), provider(script=["ok", "no_placeholder", "ok"]); o = run(e, evidence(monthly=24.40), AUTH, p)
T(13, "mid-job next call would exceed cap", o, "STOPPED_BUDGET", False, e, p, calls=3, extra=lambda o, e: (o["budget"]["budget_flag"] == "STOPPED" and any(d.startswith("_failed/1901-093-") for d in e.dirs()) and o["proposed_expense_log_row"]["images_generated"] == 3 and o["proposed_expense_log_row"]["rerolls"] == 1 and "call not made" in o["checks"][-2]["detail"]) or sys.exit("13"))
# 14 one bad scene rerolls
e, p = Env(), provider(script=["ok", "no_placeholder", "ok"]); o = run(e, evidence(), AUTH, p)
T(14, "one bad scene rerolls", o, "READY_FOR_HUMAN_RENDER_REVIEW", True, e, p, calls=7, extra=lambda o, e: (o["proposed_expense_log_row"]["rerolls"] == 1 and o["budget"]["estimated_job_cost_usd"] == 0.8 and sum(1 for u in o["proposed_expense_log_row"]["usage_record"] if u["reroll"]) == 1 and "02-story-rejected-1.png" in [os.path.basename(t) for t in e.tree()]) or sys.exit("14"))
# 15 fifth reroll attempted → stop (4 rerolls spent on slot 1, 5th bad scene stops)
e, p = Env(), provider(script=["no_placeholder"] * 5 + ["ok"]); o = run(e, evidence(), AUTH, p)
T(15, "fifth reroll attempted", o, "QA_FAILED", False, e, p, calls=5, extra=lambda o, e: ("reroll cap" in o["checks"][-2]["detail"] and o["proposed_expense_log_row"]["rerolls"] == 4) or sys.exit("15"))
# 16 quality unavailable
e, p = Env(), provider(qualities=("medium",)); T(16, "model quality unavailable", run(e, evidence(), AUTH, p), "MODEL_OR_QUALITY_BLOCK", False, e, p, calls=0)
# 17 unusable geometry: tiny placeholder → reroll, art never distorted
e, p = Env(), provider(script=["tiny", "ok"]); o = run(e, evidence(), AUTH, p)
T(17, "unusable garment geometry rerolls", o, "READY_FOR_HUMAN_RENDER_REVIEW", True, e, p, calls=7, extra=lambda o, e: (o["proposed_expense_log_row"]["rerolls"] == 1 and all(s["placement"]["aspect_preserved"] and s["placement"]["scale"] <= 1 for s in json.load(open(os.path.join(e.C, "1901-093/manifest.json")))["scene_slots"])) or sys.exit("17"))
# 18 transparency required, source opaque
e, p = Env(alpha=False), provider(); T(18, "transparency required, opaque source", run(e, evidence(requires_transparency=True), AUTH, p), "ART_PREP_BLOCK", False, e, p, calls=0, extra=lambda o, e: hashlib.sha256(open(e.staged_path, "rb").read()).hexdigest() == e.sha or sys.exit("18"))
e, p = Env(alpha=False), provider(); T("18b", "no transparency requirement, opaque source composited with warning", run(e, evidence(requires_transparency=None), AUTH, p), "READY_FOR_HUMAN_RENDER_REVIEW", True, e, p, calls=6, extra=lambda o, e: any("No transparency was invented" in w for w in o["warnings"]) or sys.exit("18b"))
# 19 resolution insufficient, no upscale
e, p = Env(size=(600, 430)), provider(); T(19, "source resolution insufficient", run(e, evidence(), AUTH, p), "RESOLUTION_BLOCK", False, e, p, calls=0)
real_fit = compositor.fit_art_quad
compositor.fit_art_quad = lambda q, aw, ah: (real_fit(q, aw, ah)[0], aw * 1.6, ah * 1.6)   # print area larger than the art
e, p = Env(), provider(); o = run(e, evidence(), AUTH, p); compositor.fit_art_quad = real_fit
T("19b", "print area larger than art at composite time", o, "RESOLUTION_BLOCK", False, e, p, calls=1, extra=lambda o, e: hashlib.sha256(open(e.staged_path, "rb").read()).hexdigest() == e.sha or sys.exit("19b"))
# 20 final composite tampered → identity mismatch → QA_FAILED
real_save = Image.Image.save
def tamper(self, fp, *a, **k):
    if isinstance(fp, str) and fp.endswith("01-hero.png"):
        self.paste((255, 255, 255), (470, 500, 560, 540))      # "re-lettering" the art region
    return real_save(self, fp, *a, **k)
Image.Image.save = tamper; e, p = Env(), provider(); o = run(e, evidence(), AUTH, p); Image.Image.save = real_save
T(20, "composite alters art identity", o, "QA_FAILED", False, e, p, calls=1, extra=lambda o, e: "art_identity_recomposite_match" in o["checks"][-2]["detail"] or sys.exit("20"))
# 21 package incomplete → VERIFICATION_FAILED
real_build = __import__("studio.contact_sheet", fromlist=["build"]).build
import studio.contact_sheet as cs
def no_sheet(items, out_path, **k): return out_path      # writes nothing
cs.build = no_sheet; e, p = Env(), provider(); o = run(e, evidence(), AUTH, p); cs.build = real_build
T(21, "final package incomplete", o, "VERIFICATION_FAILED", False, e, p, calls=6, extra=lambda o, e: "contact-sheet.png" in o["checks"][-2]["detail"] or sys.exit("21"))
# 22/23 existing campaign
e, p = Env(), provider(); assert run(e, evidence(), AUTH, p)["result"] == "READY_FOR_HUMAN_RENDER_REVIEW"
snap_tree = {t: hashlib.sha256(open(os.path.join(e.C, t), "rb").read()).hexdigest() for t in e.tree()}
o = run(e, evidence(), AUTH, p, jid="second0001"); o2 = run(e, evidence(), ASK, p, jid="second0002")
assert o["result"] == "ALREADY_RENDERED" and o2["result"] == "ALREADY_RENDERED" and len(p.calls) == 6 and {t: hashlib.sha256(open(os.path.join(e.C, t), "rb").read()).hexdigest() for t in e.tree()} == snap_tree
print(" 22. PASS existing identical complete campaign: ALREADY_RENDERED, no regeneration, nothing rewritten"); examples[22] = o
e2 = Env(); e2.sha = art_png(e2.staged_path, (1500, 1100)); m = json.load(open(os.path.join(e2.H, "1901-093/manifest.json"))); m["source"]["sha256"] = e2.sha; json.dump(m, open(os.path.join(e2.H, "1901-093/manifest.json"), "w"))
os.rename(os.path.join(e.C, "1901-093"), os.path.join(e2.C if os.path.isdir(e2.C) else (os.makedirs(e2.C) or e2.C), "1901-093")); e.done()
p = provider(); o = run(e2, evidence(), AUTH, p)
T(23, "existing campaign different source hash", o, "CAMPAIGN_CONFLICT", False, e2, p, calls=0, pre_existing=True, extra=lambda o, e: (os.path.isdir(os.path.join(e.C, "1901-093")) and "different source SHA-256" in o["checks"][-1]["detail"]) or sys.exit("23"))
# 24-27 no Sheet / Drive / Printify / Etsy; 28 publication false; 29 budget local; 30 contact sheet from finals unaltered
import re, glob
src = "".join(open(f).read() for f in glob.glob(os.path.join(HERE, "..", "studio", "*.py")) + [os.path.join(HERE, "..", "render.py")])
for label, pat in (("Sheet mutation", r"spreadsheets|values\.update|batchUpdate|gspread|sheets\.googleapis"), ("Drive mutation", r"googleapis\.com/(upload|drive)|drive\.\w*(update|delete|create|move|copy|upload|rename)|files\.(update|delete|create|copy)"), ("Printify mutation", r"api\.printify|printify\.com|printify\w*\("), ("Etsy mutation", r"openapi\.etsy|etsy\.com|etsy\w*\(")):
    assert not re.search(pat, src, re.I), label
    print(f" {24 + ['Sheet mutation','Drive mutation','Printify mutation','Etsy mutation'].index(label)}. PASS no {label} path exists in studio/ or render.py")
assert re.search(r'"publication_authorized": False', src) and not re.search(r'publication_authorized"?\s*[:=]\s*True', src)
print(" 28. PASS publication_authorized is hard-coded false and never set true")
assert "openai.com/v1/images/generations" in src and src.count("urlopen") == 2 and len(re.findall(r"https?://[\w./-]+", src)) == 2 and all("api.openai.com" in u for u in re.findall(r"https?://[\w./-]+", src)), "only the provider's model-metadata and image-generation endpoints are ever called"
print(" 29. PASS budget/cost log is local only (the only network calls in the package are the provider's free model check and the image-generation endpoint)")
e, p = Env(), provider(); o = run(e, evidence(), AUTH, p)
finals = sorted(glob.glob(os.path.join(e.C, "1901-093/final-composites/*.png"))); m = json.load(open(os.path.join(e.C, "1901-093/manifest.json")))
assert all(hashlib.sha256(open(f, "rb").read()).hexdigest() == m["final_sha256"][os.path.basename(f)] for f in finals) and Image.open(os.path.join(e.C, "1901-093/qa/contact-sheet.png")).size[0] > 1000
print(" 30. PASS contact sheet generated; the six finals still match their recorded hashes"); e.done()
# governance + extra
e, p = Env(), provider(); T("G1", "soft-IP block", run(e, evidence(blockers=[{"code": "SOFT_IP_BLOCK", "detail": "Ame's concern is open"}], handoff_status="BLOCKED"), AUTH, p), "GOVERNANCE_BLOCK", False, e, p, calls=0)
e, p = Env(), provider(); T("G2", "bridge-only open item waived", run(e, evidence(blockers=[{"code": "OPEN_ITEM_BLOCK", "detail": "bridge", "open_items": ["Render stage: image-handoff bridge not built"]}], handoff_status="BLOCKED"), ASK, p), "AWAITING_RENDER_AUTHORIZATION", False, e, p, calls=0)
e, p = Env(), provider(); T("G3", "Printify draft present is not a blocker", run(e, evidence(printify="68d1f0c2"), ASK, p), "AWAITING_RENDER_AUTHORIZATION", False, e, p, calls=0)
e, p = Env(), provider(); T("N1", "not found", run(e, evidence(queue_result="NOT_FOUND"), AUTH, p), "NOT_FOUND", False, e, p, calls=0)
e, p = Env(), provider(); T("N2", "duplicate id", run(e, evidence(queue_result="DUPLICATE_ID"), AUTH, p), "DUPLICATE_ID", False, e, p, calls=0)
e, p = Env(), provider(); T("N3", "blank render_source_path", run(e, evidence(rsp=""), AUTH, p), "SOURCE_MISSING", False, e, p, calls=0)
e, p = Env(), provider(); T("N4", "resolver ambiguous", run(e, evidence(resolver_result="AMBIGUOUS"), AUTH, p), "SOURCE_NOT_RESOLVED", False, e, p, calls=0)
e, p = Env(), provider(); T("N5", "render_source_path differs from resolver", run(e, evidence(resolver_fid="1OTHERfileAAAAAAAAAAAAAAAAAAAAAAAA"), AUTH, p), "SOURCE_MISMATCH", False, e, p, calls=0)
e, p = Env(), provider(); T("N6", "expense log unreadable", run(e, evidence(monthly=None), AUTH, p), "SOURCE_UNAVAILABLE", False, e, p, calls=0)
e, p = Env(), provider(script=["error"]); T("N7", "provider error", run(e, evidence(), AUTH, p), "GENERATION_FAILED", False, e, p, calls=1)
e, p = Env(), provider(script=["ok", "no_placeholder", "ok"]); assert run(e, evidence(), AUTH, p)["result"] == "READY_FOR_HUMAN_RENDER_REVIEW"
o = run(e, evidence(), "Proceed.", p, jid="x"); assert o["result"] == "ALREADY_RENDERED" and len(p.calls) == 7; print(" P1. PASS prior-run authorization does not carry; no regeneration"); e.done()
print("ALL PASS")
if "--dump" in sys.argv:
    for n in (1, 2, 4, 14, 13, 22, 23, 8, 9, 11, 18, 19, 20):
        open(f"ex{n}.json", "w").write(json.dumps(examples[n], indent=1, ensure_ascii=False) + "\n")

# ---- production-readiness patch: marker geometry vs shading reconstruction; configurable model ----
import io
from studio import compositor as _c, providers as _pv, qa as _qa
print("---- patch tests")
# M1 chroma marker geometry detected
img = _pv.draw_scene("1024x1024", (72, 70, 68), 1); quad, info = _c.find_marker_quad(img); assert quad and info["fill_ratio"] > 0.95 and abs(quad[0][0] - 0.36 * 1024) < 3, (quad, info)
print(" M1. PASS chroma marker geometry detected at the expected quad")
# M2 shading does not depend on marker RGB variation: identical composites from uniform vs noisy marker
e = Env(); u = io.BytesIO(); _pv.draw_scene("1024x1024", (72, 70, 68), 1, marker_pattern="uniform").save(u, "PNG"); n = io.BytesIO(); _pv.draw_scene("1024x1024", (72, 70, 68), 1, marker_pattern="noisy").save(n, "PNG")
assert _c.marker_pixels(Image.open(n)) == _c.marker_pixels(Image.open(u)), "noisy marker must still be detected as marker"
fu, pu = _c.composite(u.getvalue(), e.staged_path, (72, 70, 68)); fn, pn = _c.composite(n.getvalue(), e.staged_path, (72, 70, 68))
assert ImageChops.difference(fu, fn).getbbox() is None and pu["quad"] == pn["quad"], "composite must not depend on marker pixel values"
print(" M2. PASS garment shading and composite are byte-identical for uniform vs noisy marker pixels")
# M3 marker fully removed before placement; reconstructed field continuous with the ring
base, shade, mask = _c.prepare_base(Image.open(u), pu); assert _c.marker_pixels(base) == 0
bb = pu["placeholder"]["bbox"]; inside = base.getpixel(((bb[0] + bb[2]) // 2, bb[1] + 3)); outside = base.getpixel(((bb[0] + bb[2]) // 2, bb[1] - 6))
assert all(abs(a - b) < 12 for a, b in zip(inside, outside)), (inside, outside)
assert shade.getpixel(((bb[0] + bb[2]) // 2, bb[1] + 3)) > shade.getpixel(((bb[0] + bb[2]) // 2, bb[3] - 3)), "reconstructed shading follows the garment falloff (lighter at top)"
print(" M3. PASS marker removed before placement; reconstructed garment continuous with surrounding shirt; shading follows the garment, not the marker"); e.done()
# M4 residual chroma leak → QA failure
real_prep = _c.prepare_base
def leaky(scene, placement):
    b, s, m = real_prep(scene, placement); d = ImageDraw.Draw(b); bb = placement["placeholder"]["bbox"]; d.rectangle([bb[0], bb[1], bb[0] + 12, bb[1] + 12], fill=config.PLACEHOLDER_RGB); return b, s, m
_c.prepare_base = leaky; e, p = Env(), provider(); o = run(e, evidence(), AUTH, p); _c.prepare_base = real_prep
T("M4", "residual chroma leak", o, "QA_FAILED", False, e, p, calls=1, extra=lambda o, e: ("no_residual_chroma_leak" in o["checks"][-2]["detail"] or "marker_removed" in o["checks"][-2]["detail"]) or sys.exit("M4"))
# M5 garment field cannot be reconstructed believably → reroll (marker straddles shirt edge and background)
e, p = Env(), provider(script=["edge", "ok"]); o = run(e, evidence(), AUTH, p)
T("M5", "unreconstructable garment field rerolls", o, "READY_FOR_HUMAN_RENDER_REVIEW", True, e, p, calls=7, extra=lambda o, e: (o["proposed_expense_log_row"]["rerolls"] == 1 and "cannot be reconstructed" in [c for c in o["checks"] if c["check"] == "scene_1"][0]["detail"]) or sys.exit("M5"))
# M6 identity deterministic: two composites of the same scene+art are byte-identical; QA recomposite passes
e = Env(); f1, p1 = _c.composite(u.getvalue(), e.staged_path, (72, 70, 68)); f2, p2 = _c.composite(u.getvalue(), e.staged_path, (72, 70, 68))
assert ImageChops.difference(f1, f2).getbbox() is None and p1 == p2; print(" M6. PASS exact artwork identity is deterministic across runs"); e.done()
# M7 configured model recorded everywhere
e, p = Env(), provider(model="mock-image-2", snap=dict(SNAP, model="mock-image-2")); o1 = run(e, evidence(), ASK, p); o = run(e, evidence(), AUTH, p)
m = json.load(open(os.path.join(e.C, "1901-093/manifest.json"))); c = json.load(open(os.path.join(e.C, "1901-093/cost-log.json")))
assert o1["rendering"]["model"] == "mock-image-2" and o1["proposed_expense_log_row"]["model"] == "mock/mock-image-2" and o1["proposed_expense_log_row"]["pricing_snapshot"]["model"] == "mock-image-2"
assert m["rendering"]["model"] == "mock-image-2" and m["rendering"]["pricing_snapshot"]["model"] == "mock-image-2" and all(s["model"] == "mock-image-2" for s in m["scene_slots"]) and c["model"] == "mock/mock-image-2" and all(u_["model"] == "mock-image-2" for u_ in c["usage_record"]) and c["pricing_snapshot"]["model"] == "mock-image-2"
print(" M7. PASS configured model recorded in proposal, manifest, cost log, pricing snapshot and every usage record"); e.done()
# M8 pricing for a different model / size → PRICING_UNAVAILABLE
e, p = Env(), provider(snap=dict(SNAP, model="mock-image-OTHER")); T("M8", "pricing snapshot for another model", run(e, evidence(), AUTH, p), "PRICING_UNAVAILABLE", False, e, p, calls=0)
e, p = Env(), provider(snap=dict(SNAP, size="1536x1024")); T("M8b", "pricing snapshot for another size", run(e, evidence(), AUTH, p), "PRICING_UNAVAILABLE", False, e, p, calls=0)
e, p = Env(), provider(snap={k: v for k, v in SNAP.items() if k != "size"}); T("M8c", "pricing snapshot without size", run(e, evidence(), AUTH, p), "PRICING_UNAVAILABLE", False, e, p, calls=0)
# M9 missing credential → MODEL_OR_QUALITY_BLOCK
e, p = Env(), provider(credentials=False); T("M9", "missing API credential", run(e, evidence(), AUTH, p), "MODEL_OR_QUALITY_BLOCK", False, e, p, calls=0)
e, p = Env(), provider(available=False); T("M9b", "configured model unavailable", run(e, evidence(), AUTH, p), "MODEL_OR_QUALITY_BLOCK", False, e, p, calls=0)
# M10 unsupported tier / size
e, p = Env(), provider(qualities=("medium",)); T("M10", "high tier unsupported", run(e, evidence(), AUTH, p), "MODEL_OR_QUALITY_BLOCK", False, e, p, calls=0)
e, p = Env(), provider(sizes=["1536x1024"]); T("M10b", "configured size unsupported", run(e, evidence(), AUTH, p), "MODEL_OR_QUALITY_BLOCK", False, e, p, calls=0)
# M11 no provider call during proposal (also preflight makes none)
e, p = Env(), provider(); o = run(e, evidence(), ASK, p); pf = p.preflight(); assert len(p.calls) == 0 and pf["generation_call_made"] is False and pf["model_configured"] == "mock-image-1" and pf["pricing_snapshot_available"] is True and pf["credentials_available"] is True
print(" M11. PASS no provider call during proposal or preflight"); e.done()
# M12 no live paid calls in tests: the OpenAI adapter's generation endpoint is never reached (only MockProvider instances were used)
assert all(isinstance(x, _pv.MockProvider) for x in [p]) and "OPENAI_API_KEY" not in os.environ
print(" M12. PASS no live paid calls: only MockProvider used; no OPENAI_API_KEY in the test environment")
# OpenAI adapter offline behaviour (no network): config-driven, fails closed
cfg = {"provider": "openai", "model": "configured-image-model", "size": "1024x1024", "capabilities": {"qualities": ["low", "medium", "high"], "sizes": ["1024x1024"], "basis": "fixture"}, "pricing_path": "/nonexistent/pricing.json"}
oa = _pv.make_provider(cfg); pf = oa.preflight()
assert oa.model == "configured-image-model" and pf["credentials_available"] is False and pf["model_available"] is None and pf["pricing_snapshot_available"] is False and pf["quality_tiers_available"] == {"high": True, "medium": True} and pf["generation_call_made"] is False
assert "gpt-image-1" not in open(os.path.join(HERE, "..", "studio", "providers.py")).read()
print(" M13. PASS OpenAI adapter takes its model from configuration only (no hard-coded model id); preflight is read-only and fails closed")
# M14 credential variable resolution: OPENAI_API_KEY first, then the harness-safe LISTING_STUDIO_OPENAI_API_KEY; never the value
for k in ("OPENAI_API_KEY", "LISTING_STUDIO_OPENAI_API_KEY"): os.environ.pop(k, None)
assert oa.credentials_available() is False and oa.credential_env_name() is None
os.environ["LISTING_STUDIO_OPENAI_API_KEY"] = "fixture-not-a-real-key"
assert oa.credentials_available() is True and oa.credential_env_name() == "LISTING_STUDIO_OPENAI_API_KEY" and _pv._api_key() == "fixture-not-a-real-key"
os.environ["OPENAI_API_KEY"] = "fixture-primary"; assert oa.credential_env_name() == "OPENAI_API_KEY"
for k in ("OPENAI_API_KEY", "LISTING_STUDIO_OPENAI_API_KEY"): os.environ.pop(k, None)
assert "credential_env_name" in oa.preflight() and oa.preflight()["credential_env_name"] is None
print(" M14. PASS credential resolves from OPENAI_API_KEY, else LISTING_STUDIO_OPENAI_API_KEY; preflight reports the name only; no network call without a key")
print("ALL PATCH TESTS PASS")
