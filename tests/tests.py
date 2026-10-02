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
base, shade, mask, _ri = _c.prepare_base(Image.open(u), pu); assert _c.marker_pixels(base) == 0
bb = pu["placeholder"]["bbox"]; inside = base.getpixel(((bb[0] + bb[2]) // 2, bb[1] + 3)); outside = base.getpixel(((bb[0] + bb[2]) // 2, bb[1] - 6))
assert all(abs(a - b) < 12 for a, b in zip(inside, outside)), (inside, outside)
assert shade.getpixel(((bb[0] + bb[2]) // 2, bb[1] + 3)) > shade.getpixel(((bb[0] + bb[2]) // 2, bb[3] - 3)), "reconstructed shading follows the garment falloff (lighter at top)"
print(" M3. PASS marker removed before placement; reconstructed garment continuous with surrounding shirt; shading follows the garment, not the marker"); e.done()
# M4 residual chroma leak → QA failure
real_prep = _c.prepare_base
def leaky(scene, placement):
    b, s, m, ri = real_prep(scene, placement); d = ImageDraw.Draw(b); bb = placement["placeholder"]["bbox"]; d.rectangle([bb[0], bb[1], bb[0] + 12, bb[1] + 12], fill=config.PLACEHOLDER_RGB); return b, s, m, ri
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
# ---- marker isolation patch (job 4c8fda750c false positives): connected-component selection ----
# M15 background magenta/purple pixels never move the quad: purple_bg scene detects the same quad and pixel count as the clean scene
clean = _pv.draw_scene("1024x1024", (72, 70, 68), 1); noisy = _pv.draw_scene("1024x1024", (72, 70, 68), 1, behaviour="purple_bg")
qc, ic = _c.find_marker_quad(clean); qn, inf = _c.find_marker_quad(noisy)
assert _c.marker_pixels(noisy) > _c.marker_pixels(clean) + 1000, "fixture must contain background chroma"
assert qn == qc and inf["pixels"] == ic["pixels"] and inf["fill_ratio"] == ic["fill_ratio"] >= 0.95 and inf["components"]["plausible"] == 1 and inf["components"]["ignored"] >= 5 and inf["components"]["ignored_pixels"] > 1000 and ic["components"]["ignored"] == 0, (qn, qc, inf)
print(" M15. PASS background chroma components are ignored: identical quad, pixel count and fill ratio as the clean scene")
# M15b full run with a purple-background hero: no reroll, QA PASS (marker removed within the component; background chroma untouched and not a leak)
e, p = Env(), provider(script=["purple_bg"]); o = run(e, evidence(), AUTH, p)
T("M15b", "purple-background hero renders without a reroll", o, "READY_FOR_HUMAN_RENDER_REVIEW", True, e, p, calls=6, extra=lambda o, e: (o["proposed_expense_log_row"]["rerolls"] == 0 and json.load(open(os.path.join(e.C, "1901-093/qa/qa.json")))["images"][0]["checks"]["marker_removed_before_placement"]["result"] == "PASS") or sys.exit("M15b"))
# M16 malformed / fragmented / missing / tiny / edge markers still fail closed → reroll, with the specific reason
for beh, needle in (("hollow", "not a solid convex panel"), ("fragmented", "cannot be isolated"), ("no_marker", "no print-area marker"), ("tiny", "too small"), ("edge", "cannot be reconstructed")):
    e, p = Env(), provider(script=[beh]); o = run(e, evidence(), AUTH, p)
    T(f"M16-{beh}", f"{beh} marker rerolls", o, "READY_FOR_HUMAN_RENDER_REVIEW", True, e, p, calls=7, extra=lambda o, e, n=needle: (o["proposed_expense_log_row"]["rerolls"] == 1 and n in [c for c in o["checks"] if c["check"] == "scene_1"][0]["detail"]) or sys.exit("M16 " + n))
# M16b fragmented + background noise: still ambiguous (two plausible components, dominance below 4x), not rescued by the noise filter
img = _pv.draw_scene("1024x1024", (72, 70, 68), 1, behaviour="fragmented"); q, why = _c.find_marker_quad(img); assert q is None and "more than one plausible" in why, why
print(" M16b. PASS two comparable components: no dominant marker, fail closed")
# M16c the dominance rule: a second plausible component just under 1/4 of the marker is ignored; at 1/3 it is ambiguous
from PIL import ImageDraw as _ID
for frac, expect in ((0.20, True), (0.34, False)):
    img = _pv.draw_scene("1024x1024", (72, 70, 68), 1); d = _ID.Draw(img); mp = _c.find_marker_quad(img)[1]["pixels"]; side = int((mp * frac) ** 0.5)
    d.rectangle([40, 40, 40 + side, 40 + side], fill=config.PLACEHOLDER_RGB); q, info = _c.find_marker_quad(img)
    assert (q is not None) is expect, (frac, info)
    if expect: assert info["pixels"] == mp and info["components"]["plausible"] == 1 and info["components"]["ignored"] == 1 and info["components"]["largest_ignored_pixels"] == (side + 1) ** 2, info
    else: assert "more than one plausible" in info, info
print(" M16c. PASS a second magenta block below the 2% floor is noise and ignored; above it (1/3 of the marker, dominance < 4) the scene is unusable")
# M17 the five failed hero attempts of job 4c8fda750c (read-only on the failed job; skipped when absent)
import regression_4c8fda750c as _rg; assert _rg.main() == 0
print(" M17. PASS regression on job 4c8fda750c artifacts (or SKIP when absent)")
# ---- reroll accounting after a confirmed validator defect ----
def failed_fixture(e, job_id="oldjob0001", rerolls=4, cost=0.2884, defect=True, **over):
    fr = os.path.join(e.C, "_failed", f"1901-093-{job_id}"); os.makedirs(os.path.join(fr, "generated-scenes"))
    json.dump({"result": "QA_FAILED", "detail": "scene unusable (print-area marker is not a solid convex panel (fill ratio 0.33)) and the reroll cap of 4 is reached", "design_id": "1901-093", "render_job_id": job_id, "downstream_ready": False}, open(os.path.join(fr, "FAILED.json"), "w"))
    json.dump({"render_job_id": job_id, "design_id": "1901-093", "started_at": NOW, "rerolls": rerolls, "estimated_api_cost_usd": cost, "images_generated": 1 + rerolls, "job_status": "FAILED:QA_FAILED"}, open(os.path.join(fr, "cost-log.json"), "w"))
    open(os.path.join(fr, "generated-scenes", "01-hero-base.png"), "wb").write(b"fixture")
    if defect is not None:
        d = {"design_id": "1901-093", "render_job_id": job_id, "defect": "Scene 1 marker validation combined every magenta-coloured pixel in the image; background pixels inflated the inferred polygon (fill 0.23-0.37 vs 0.99-1.02 for the connected marker)", "corrected_in": "<commit>", "ruled_by": "Jody Clements (Architect)", "ruled_at": "2026-10-02", "scope": "validator-defect"}
        d.update(over); json.dump(d, open(fr + ".validator-defect.json", "w"))
    return fr
def snapshot(fr): return {p_: (open(p_, "rb").read(), os.stat(p_).st_mtime_ns) for d_, _, fs in os.walk(fr) for f in fs for p_ in [os.path.join(d_, f)]}
# R1 proposal lists the prior failed job with validator-defect attribution; spend still counts; nothing in _failed touched
e, p = Env(), provider(); fr = failed_fixture(e); snap_ = snapshot(fr); o = run(e, evidence(monthly=3.10), ASK, p)
pj = o["prior_failed_jobs"]; assert len(pj) == 1 and pj[0]["render_job_id"] == "oldjob0001" and pj[0]["attribution"] == "validator-defect" and pj[0]["rerolls"] == 4 and pj[0]["validator_defect"]["corrected_in"] == "<commit>" and pj[0]["warnings"] == []
assert o["budget"]["monthly_recorded_cost_usd"] == 3.10 and any("validator defect" in n for n in o["proposed_expense_log_row"]["notes"]) and any(c["check"] == "prior_failed_jobs" and "attribution validator-defect" in c["detail"] for c in o["checks"])
assert o["result"] == "AWAITING_RENDER_AUTHORIZATION" and len(p.calls) == 0 and snapshot(fr) == snap_
examples["R1"] = o; print(" R1. PASS proposal reports the prior failed job as validator-defect attributed; no call; failed artifacts untouched")
# R1b the retry still needs the exact command; then runs with a fresh allowance of 4, its cost log carrying the attribution note
o = run(e, evidence(monthly=3.10), "Proceed.", p); assert o["result"] == "AWAITING_RENDER_AUTHORIZATION" and len(p.calls) == 0
o = run(e, evidence(monthly=3.10), AUTH, p, jid="newjob0001"); assert o["result"] == "READY_FOR_HUMAN_RENDER_REVIEW" and len(p.calls) == 6 and o["proposed_expense_log_row"]["rerolls"] == 0
c = json.load(open(os.path.join(e.C, "1901-093/cost-log.json"))); assert any("validator defect in job oldjob0001" in n for n in c["notes"]) and c["rerolls"] == 0 and snapshot(fr) == snap_ and os.path.isdir(fr)
print(" R1b. PASS retry needs a fresh exact authorization; new job starts at 0 rerolls; attribution recorded in its cost log; prior failed job preserved"); e.done()
# R2 the reroll cap is unchanged on a retry: four ordinary bad generations and a fifth still stop the job
e, p = Env(), provider(script=["hollow", "fragmented", "no_marker", "tiny", "hollow"]); failed_fixture(e); o = run(e, evidence(), AUTH, p)
T("R2", "retry after a defect ruling still caps ordinary rerolls at 4", o, "QA_FAILED", False, e, p, calls=5, extra=lambda o, e: (o["proposed_expense_log_row"]["rerolls"] == 4 and "reroll cap" in [c for c in o["checks"] if c["check"] == "scene_1"][-1]["detail"]) or sys.exit("R2"))
# R3 no ruling → ordinary attribution; a ruling naming another job, missing fields, or unreadable → ordinary with a warning; never a bypass
for label, kw in (("no record", {"defect": None}), ("other job id", {"render_job_id": "someoneelse"}), ("missing corrected_in", {"corrected_in": ""}), ("missing ruler", {"ruled_by": ""})):
    e, p = Env(), provider(); fr = failed_fixture(e, **kw); o = run(e, evidence(), ASK, p)
    assert o["prior_failed_jobs"][0]["attribution"] == "generation" and o["prior_failed_jobs"][0]["validator_defect"] is None and not any("validator defect" in n for n in o["proposed_expense_log_row"]["notes"]), label
    assert (o["prior_failed_jobs"][0]["warnings"] == []) == (label == "no record"), label
    e.done()
e, p = Env(), provider(); fr = failed_fixture(e, defect=None); open(fr + ".validator-defect.json", "w").write("{not json"); o = run(e, evidence(), ASK, p)
assert o["prior_failed_jobs"][0]["attribution"] == "generation" and any("unreadable" in w for w in o["prior_failed_jobs"][0]["warnings"]); e.done()
print(" R3. PASS attribution is validator-defect only with a complete ruling naming the exact job; otherwise ordinary, with a warning")
# R4 a failed job's spend stays in the monthly floor whatever its attribution
e, p = Env(), provider(); failed_fixture(e, cost=5.0); o = run(e, evidence(monthly=1.0), ASK, p); assert o["budget"]["monthly_recorded_cost_usd"] == 5.0 and any("Local cost logs" in w for w in o["warnings"]); e.done()
print(" R4. PASS a validator-defect job's spend still counts toward the monthly cap")
# ---- dark-garment ring rule (review of the cv limitation found in 735f67d) ----
# K1 the rule itself over real and synthetic rings: cv rule unchanged above mean 28; below it, absolute spread + texture
def ring_judge(scene):
    mask, _ = _c.isolate_marker(scene); st = _c.ring_stats(scene, mask); ok, why, rule = _c.ring_acceptable(st); return st, ok, why, rule
DARK = {"black": (8, 8, 10), "near-black": (20, 20, 22)}; LIGHTER = {"charcoal": (40, 40, 44), "dark gray": (72, 70, 68), "mid": (128, 128, 128), "light": (200, 200, 196)}
for name, col in DARK.items():
    for beh, expect in (("ok", True), ("grain", True), ("mottled", False), ("stripes", False), ("edge", False)):
        st, ok, why, rule = ring_judge(_pv.draw_scene("1024x1024", col, 1, behaviour=beh)); assert ok is expect and st["mean_luminance"] <= _c.RING_DARK_MEAN_MAX or beh in ("stripes", "edge"), (name, beh, st, why)
        if beh == "mottled" and st["std"] <= _c.RING_DARK_MAX_STD: assert "mottled or noisy" in why, why
    st, ok, why, rule = ring_judge(_pv.draw_scene("1024x1024", col, 1, behaviour="hard_shadow"))
    assert ok and rule == "dark-absolute", (name, st)                           # documented limitation: <= ~14-level hard shadow on near-black is indistinguishable from drape
st, ok, why, rule = ring_judge(_pv.draw_scene("1024x1024", (40, 40, 44), 1, behaviour="hard_shadow")); assert not ok and st["mean_luminance"] <= 28 and "std" in why, (st, why)   # a 27-level hard shadow drops the ring into the dark regime and the spread cap rejects it
for name, col in LIGHTER.items():
    for beh in ("ok", "grain", "mottled", "hard_shadow", "stripes", "edge"):
        st, ok, why, rule = ring_judge(_pv.draw_scene("1024x1024", col, 1, behaviour=beh))
        if beh == "hard_shadow" and st["mean_luminance"] <= _c.RING_DARK_MEAN_MAX: assert not ok, (name, st); continue
        assert ok == (st["cv"] <= _c.RING_MAX_CV) and (rule in (None, "cv")), (name, beh, st)   # exactly the pre-existing cv behaviour at mean > 28 (incl. its leniency to mottle on midtones), dark branch never used
print(" K1. PASS ring rule: cv unchanged at mean > 28 (midtone leniency included); dark branch accepts plain/grainy black, rejects mottle, stripes, background and a 27-level hard shadow")
# K2 the branch never loosens the spread: at the boundary the absolute cap (10) is below what cv allows at mean 28 (9.8 ~ 10) and above it only cv applies
assert abs(_c.RING_DARK_MAX_STD - _c.RING_MAX_CV * _c.RING_DARK_MEAN_MAX) < 1e-9 and _c.RING_DARK_MEAN_MAX == 28
def fake(mean, std, texture=1.0, chroma=0): return {"pixels": 5000, "mean_luminance": mean, "std": std, "cv": round(std / mean, 4), "texture": texture, "chroma_pixels_in_ring": chroma}
assert _c.ring_acceptable(fake(28.5, 9.0))[0] is True and _c.ring_acceptable(fake(28.5, 9.0))[2] == "cv"
assert _c.ring_acceptable(fake(29.0, 10.5))[0] is False                                  # just above the dark regime: cv 0.36 rejects as before
assert _c.ring_acceptable(fake(27.0, 10.5))[0] is False                                  # inside it: spread cap rejects
assert _c.ring_acceptable(fake(27.0, 9.9))[0] is False                                   # 9.9 > 9.8: spread cap rejects
assert _c.ring_acceptable(fake(27.0, 9.5, texture=5.2))[0] is False                      # texture cap rejects
ok_, _, rule_ = _c.ring_acceptable(fake(27.0, 9.5, texture=4.9)); assert ok_ and rule_ == "dark-absolute"
assert _c.ring_acceptable(fake(27.0, 9.5, texture=4.9, chroma=1))[0] is False            # chroma always rejects
assert _c.ring_acceptable(None)[0] is False
print(" K2. PASS boundary behaviour: no loosening above mean 28; spread, texture and chroma caps all fail closed")
# K3 full runs on a near-black governed garment: grainy hero renders with no reroll and records the rule; mottled hero rerolls
NB = [{"blank": "Unisex Heavy Cotton Tee", "provider": "Printify Choice", "color": "Black", "garment_rgb": [20, 20, 22], "spec_source": "fixture"}]
e, p = Env(), provider(script=["grain"]); o = run(e, evidence(product_candidates=NB), AUTH, p)
def dark_ok(o, e):
    m = json.load(open(os.path.join(e.C, "1901-093/manifest.json"))); r = m["scene_slots"][0]["placement"]["ring"]
    assert o["proposed_expense_log_row"]["rerolls"] == 0 and r["rule"] in ("cv", "dark-absolute") and "std" in r and "texture" in r, r
T("K3", "near-black garment, grainy hero: no reroll", o, "READY_FOR_HUMAN_RENDER_REVIEW", True, e, p, calls=6, extra=dark_ok)
e, p = Env(), provider(script=["mottled"]); o = run(e, evidence(product_candidates=NB), AUTH, p)
T("K3b", "near-black garment, mottled hero rerolls", o, "READY_FOR_HUMAN_RENDER_REVIEW", True, e, p, calls=7, extra=lambda o, e: (o["proposed_expense_log_row"]["rerolls"] == 1 and "cannot be reconstructed" in [c for c in o["checks"] if c["check"] == "scene_1"][0]["detail"]) or sys.exit("K3b"))
CH = [dict(NB[0], garment_rgb=[40, 40, 44], color="Charcoal")]
e, p = Env(), provider(script=["hard_shadow"]); o = run(e, evidence(product_candidates=CH), AUTH, p)
T("K3c", "charcoal garment, hard-shadowed hero rerolls", o, "READY_FOR_HUMAN_RENDER_REVIEW", True, e, p, calls=7, extra=lambda o, e: (o["proposed_expense_log_row"]["rerolls"] == 1) or sys.exit("K3c"))
e, p = Env(), provider(script=["stripes"]); o = run(e, evidence(product_candidates=NB), AUTH, p)
T("K3d", "near-black striped garment rerolls", o, "READY_FOR_HUMAN_RENDER_REVIEW", True, e, p, calls=7)
e, p = Env(), provider(script=["edge"]); o = run(e, evidence(product_candidates=NB), AUTH, p)
T("K3e", "near-black marker straddling the background rerolls", o, "READY_FOR_HUMAN_RENDER_REVIEW", True, e, p, calls=7)
# K4 determinism of the new statistics
sc = _pv.draw_scene("1024x1024", (20, 20, 22), 1, behaviour="grain"); a = ring_judge(sc)[0]; b = ring_judge(sc.copy())[0]; assert a == b
print(" K4. PASS ring statistics are deterministic")
import tempfile as _tf
def _scene_png(img):
    path = os.path.join(_tf.mkdtemp(prefix="sc-"), "scene.png"); img.save(path, "PNG"); return path
# ---- compositor correction for job 863b478926: fringe-aware removal, texture, continuity, bounded shading, recomposite ----
from PIL import ImageFilter as _IF
def fringe_count(img, mask_L):
    gate, _ = _c.chroma_gate(img, mask_L, margin_min=_c.FRINGE_QA_MARGIN_MIN); box = _c._work_box(mask_L); L = mask_L.crop(box)
    return _c._count(ImageChops.multiply(gate.crop(box), ImageChops.subtract(_c._dil(L, 4), L)))
def tex_energy(img, mask_L):
    lum = img.convert("L"); hp = ImageChops.difference(lum, lum.filter(_IF.GaussianBlur(2))); v, _, _ = _c._mean_std(hp, mask_L); return v
BLACK = [{"blank": "Unisex Heavy Cotton Tee", "provider": "Printify Choice", "color": "Black", "garment_rgb": [20, 20, 22], "spec_source": "fixture"}]
# F1 anti-aliased fringe on a black garment: the removal mask grows only into tinted pixels (<= 3 px), and the final shows no visible perimeter
for beh, label in (("fringe", "smooth black"), ("fringe_grain", "textured black")):
    sc = _pv.draw_scene("1024x1024", (20, 20, 22), 1, behaviour=beh); comp, info = _c.isolate_marker(sc); grown, ginfo = _c.grow_removal_mask(sc, comp)
    gL, cL = grown.convert("L"), comp.convert("L")
    assert ginfo["grown_pixels"] > 0 and len(ginfo["passes"]) <= 3, ginfo
    assert _c._count(ImageChops.multiply(gL, ImageChops.invert(_c._dil(cL, 3)))) == 0, "grew beyond 3 px"
    before = fringe_count(sc, cL); assert before > 200, before
    e = Env(); final, pl = _c.composite(open(_scene_png(sc), "rb").read(), e.staged_path, (20, 20, 22))
    after = fringe_count(final, gL); assert after == 0, (label, after)
    assert _c._count(gL) < _c._count(_c._dil(cL, 3)), "blind dilation"
    print(f" F1-{beh}. PASS {label}: fringe removed by gated growth ({ginfo['grown_pixels']} px, passes {ginfo['passes']}); {before} visible fringe px before, 0 after; not a blind dilation"); e.done()
# F2 texture restoration and continuity: textured black fabric regains high-frequency energy; smooth black stays smooth; interior mean within tolerance
for beh, expect_tex in (("fringe_grain", True), ("fringe", False)):
    sc = _pv.draw_scene("1024x1024", (20, 20, 22), 1, behaviour=beh); base, shade, mask, rinfo = _c.prepare_base(sc, None); L = mask.convert("L")
    band = ImageChops.subtract(_c._dil(L, 9), _c._dil(L, 3)); inner = _c._ero(L, 10); tb, ti = tex_energy(sc, band), tex_energy(base, inner)
    if expect_tex: assert ti >= 0.5 * tb and rinfo["texture"]["patches"] > 0, (tb, ti, rinfo["texture"])
    else: assert ti <= max(0.6, tb + 0.3), (tb, ti)
    assert rinfo["continuity"]["ok"] and abs(rinfo["continuity"]["delta"]) <= rinfo["continuity"]["tolerance"], rinfo["continuity"]
    assert _c.marker_pixels(Image.composite(base, Image.new("RGB", base.size, (0, 0, 0)), L)) == 0
    print(f" F2-{beh}. PASS texture band {tb:.2f} → interior {ti:.2f}; continuity delta {rinfo['continuity']['delta']} within {rinfo['continuity']['tolerance']}")
# F2b no rectangular reconstruction panel: no luminance step across the repaired boundary and no chroma on either side of it
sc = _pv.draw_scene("1024x1024", (20, 20, 22), 1, behaviour="fringe_grain"); base, _, mask, rinfo = _c.prepare_base(sc, None); L = mask.convert("L")
band = ImageChops.subtract(_c._dil(L, 9), _c._dil(L, 3)); edge_in = ImageChops.subtract(L, _c._ero(L, 3)); edge_out = ImageChops.subtract(_c._dil(L, 3), L)
bm, bs, _ = _c._mean_std(sc.convert("L"), band); ei, _, _ = _c._mean_std(base.convert("L"), edge_in); eo, _, _ = _c._mean_std(base.convert("L"), edge_out)
assert abs(ei - eo) <= max(1.0, bs), (ei, eo, bs)
assert fringe_count(base, L) == 0 and _c._count(ImageChops.multiply(_c.chroma_gate(base, L)[0], edge_in)) == 0
print(" F2b. PASS no rectangular panel: no luminance step across the repaired boundary, no chroma on either side of it")
# F3 continuity fails closed: a reconstruction that lands off the band is rejected (forced by patching the fill)
real_recon = _c.reconstruct_garment
def dark_recon(scene, mask, bbox):
    out = real_recon(scene, mask, bbox); return Image.composite(out.point(lambda v: max(0, v - 12)), out, mask.convert("L"))
_c._BASE_CACHE.clear(); _c.reconstruct_garment = dark_recon
try:
    _c.composite(open(_scene_png(sc), "rb").read(), Env().staged_path, (20, 20, 22)); raise AssertionError("continuity did not fail closed")
except _c.CompositeError as ce: assert ce.code == "UNUSABLE_SCENE" and "not continuous" in ce.detail, ce.detail
finally: _c.reconstruct_garment = real_recon; _c._BASE_CACHE.clear()
print(" F3. PASS continuity check fails closed when the reconstructed interior drifts from the clean band")
# F4 exact artwork fidelity: art pixels only moved and lit; alpha untouched; final recomposites byte-exact; opaque art equals art x shade exactly
e, p = Env(), provider(script=["fringe_grain"]); o = run(e, evidence(product_candidates=BLACK), AUTH, p)
def fidelity(o, e):
    m = json.load(open(os.path.join(e.C, "1901-093/manifest.json"))); pl = m["scene_slots"][0]["placement"]; assert pl["compositor_version"] == _c.COMPOSITOR_VERSION and m["rendering"]["compositor_version"] == _c.COMPOSITOR_VERSION
    sc = Image.open(os.path.join(e.C, "1901-093/generated-scenes/01-hero-base.png")).convert("RGB"); fin = Image.open(os.path.join(e.C, "1901-093/final-composites/01-hero.png")).convert("RGB"); art = Image.open(e.staged_path)
    assert ImageChops.difference(fin, _c.render_from_placement(sc, art, pl)).getbbox() is None
    base, shade, mask, rinfo = _c.prepare_base(sc, pl); alpha = _c.warped_alpha(sc.size, art, pl); opaque = alpha.point(lambda v: 255 if v == 255 else 0)
    coeffs = _c.perspective_coeffs([tuple(q) for q in pl["art_quad"]], art.size[0], art.size[1]); warped = art.convert("RGBA").transform(sc.size, Image.PERSPECTIVE, coeffs, resample=Image.BICUBIC).convert("RGB")
    expect = ImageChops.multiply(warped, Image.merge("RGB", (shade, shade, shade))); diff = ImageChops.difference(Image.composite(fin, Image.new("RGB", sc.size), opaque), Image.composite(expect, Image.new("RGB", sc.size), opaque))
    assert diff.getbbox() is None, "opaque art pixels were blended with the garment"
    q = json.load(open(os.path.join(e.C, "1901-093/qa/qa.json")))["images"][0]["checks"]; bad = {k: q[k]["detail"] for k in q if q[k]["result"] == "FAIL"}; assert not bad, bad
    assert all(k in q for k in ("no_marker_fringe", "reconstruction_continuity", "garment_texture_restored", "bounded_shading"))
T("F4", "black textured garment with fringe: full run; art only moved and lit; opaque stays opaque; new QA checks PASS", o, "READY_FOR_HUMAN_RENDER_REVIEW", True, e, p, calls=6, extra=fidelity)
# F5 dark-garment shading rule: floor <= min <= median <= 1, low-frequency source, white outside the print area; black is modulated less than the old rule would
for col, beh in (((20, 20, 22), "fringe_grain"), ((8, 8, 10), "grain"), ((72, 70, 68), "ok"), ((200, 200, 196), "ok")):
    sc = _pv.draw_scene("1024x1024", col, 1, behaviour=beh); _, shade, mask, rinfo = _c.prepare_base(sc, None); sh = rinfo["shading"]
    assert sh["floor_effective"] - 1e-9 <= sh["min_modulation"] <= sh["median_modulation"] <= 1.0 and sh["source"] == "low-frequency reconstruction only", sh
    assert _c._count(ImageChops.multiply(shade.point(lambda v: 255 if v < 255 else 0), ImageChops.invert(mask.convert("L")))) == 0, "shading leaked outside the print area"
print(" F5. PASS bounded shading: floor <= min <= median <= 1 on black, near-black, mid and light garments; white outside the print area")
# F6 no regression: the fringe fixture still isolates one component with fill >= 0.95 and its ring is still accepted
sc = _pv.draw_scene("1024x1024", (20, 20, 22), 1, behaviour="fringe"); q_, info = _c.find_marker_quad(sc); assert q_ and info["components"]["plausible"] == 1 and info["fill_ratio"] >= 0.95
st = _c.ring_stats(sc, _c.grow_removal_mask(sc, _c.isolate_marker(sc)[0])[0]); assert _c.ring_acceptable(st)[0]
print(" F6. PASS marker detection and ring validation unchanged under the fringe fixture")
# F7 determinism: the same scene twice gives byte-identical base and shade (quilting is seeded from the marker-free image)
_c._BASE_CACHE.clear(); b1, s1, _, i1 = _c.prepare_base(sc, None); _c._BASE_CACHE.clear(); b2, s2, _, i2 = _c.prepare_base(sc, None)
assert ImageChops.difference(b1, b2).getbbox() is None and ImageChops.difference(s1, s2).getbbox() is None and i1 == i2
print(" F7. PASS reconstruction is a pure, deterministic function of the scene")
# ---- recomposite / supersession ----
RC_AUTH = "AUTHORIZE LISTING RECOMPOSITE 1901-093"; RC_ASK = "Recomposite the 1901-093 campaign with the corrected compositor."
def old_package(e, p=None):
    p = p or provider(script=["fringe_grain"] * 6); o = run(e, evidence(product_candidates=BLACK), AUTH, p, jid="origjob001"); assert o["result"] == "READY_FOR_HUMAN_RENDER_REVIEW", o["checks"][-1]
    mp = os.path.join(e.C, "1901-093/manifest.json"); m = json.load(open(mp)); m["rendering"]["compositor_version"] = "old"; json.dump(m, open(mp, "w"), indent=2)
    return {f: open(os.path.join(e.C, f), "rb").read() for f in e.tree()}
def rc(e, msg, **kw): return job.recomposite("1901-093", msg, e.H, e.C, now=NOW, **kw)
e = Env(); snap_ = old_package(e); o = rc(e, RC_ASK)
assert o["result"] == "AWAITING_RECOMPOSITE_AUTHORIZATION" and o["recomposite_performed"] is False and o["render_job_id"] == "origjob001-rc1" and o["supersedes"]["render_job_id"] == "origjob001" and o["generation_calls"] == 0 and "AUTHORIZE LISTING RECOMPOSITE 1901-093" in o["human_action_required"], o["checks"][-1]
assert {f: open(os.path.join(e.C, f), "rb").read() for f in e.tree()} == snap_ and not any(d.startswith(".tmp-") or d.startswith("_superseded") for d in e.dirs()); examples["RC1"] = o
assert rc(e, "Proceed.")["result"] == "AWAITING_RECOMPOSITE_AUTHORIZATION" and rc(e, "AUTHORIZE LISTING RECOMPOSITE 1901-094")["result"] == "AWAITING_RECOMPOSITE_AUTHORIZATION"
assert rc(e, "AUTHORIZE LISTING RENDER 1901-093")["result"] == "AWAITING_RECOMPOSITE_AUTHORIZATION", "the render command must not authorize a recomposite"
print(" RC1. PASS recomposite proposal: nothing changed; the render command, vague words and another id never authorize it")
o = rc(e, RC_AUTH); assert o["result"] == "READY_FOR_HUMAN_RENDER_REVIEW" and o["recomposite_performed"] is True, o["checks"][-1]
sup = os.path.join(e.C, "_superseded/1901-093-origjob001"); rec = json.load(open(sup + ".SUPERSEDED.json")); newm = json.load(open(os.path.join(e.C, "1901-093/manifest.json")))
assert os.path.isdir(sup) and all(open(os.path.join(sup, f[len("1901-093/"):]), "rb").read() == b for f, b in snap_.items()), "superseded package not byte-identical"
assert rec["render_job_id"] == "origjob001" and rec["superseded_by"] == "origjob001-rc1" and rec["original_result"] == "READY_FOR_HUMAN_RENDER_REVIEW" and rec["original_final_sha256"] == json.loads(snap_["1901-093/manifest.json"])["final_sha256"]
r_ = newm["recomposite"]; assert r_["of_render_job_id"] == "origjob001" and r_["generation_calls"] == 0 and r_["estimated_api_cost_usd"] == 0.0 and r_["superseded_package"] == "_superseded/1901-093-origjob001" and r_["source_sha256"] == e.sha and len(r_["base_scenes_reused"]) == 6 and r_["original_final_sha256"] == rec["original_final_sha256"]
assert newm["render_job_id"] == "origjob001-rc1" and newm["rendering"]["compositor_version"] == _c.COMPOSITOR_VERSION and newm["rendering"]["compositor_commit"] == job.compositor_commit() and newm["publication_authorized"] is False and newm["final_sha256"] == rec["original_final_sha256"]   # same compositor in the fixture: a recomposite reproduces the finals byte-for-byte (determinism)
for n_ in newm["generated_scenes"]: assert open(os.path.join(e.C, "1901-093/generated-scenes", n_), "rb").read() == snap_["1901-093/generated-scenes/" + n_]
cl = json.load(open(os.path.join(e.C, "1901-093/cost-log.json"))); assert cl["images_generated"] == 0 and cl["generation_calls"] == 0 and cl["estimated_api_cost_usd"] == 0.0 and cl["recomposite_of_render_job_id"] == "origjob001"
assert os.path.isfile(os.path.join(e.C, "1901-093/source/recomposite-reference.json")) and json.load(open(os.path.join(e.C, "1901-093/qa/qa.json")))["campaign_result"] == "PASS" and not any(d.startswith(".tmp-") for d in e.dirs())
examples["RC2"] = o; print(" RC2. PASS authorized recomposite: original moved whole and byte-identical to _superseded with a SUPERSEDED record; new package carries the recomposite block, zero generation, zero spend")
o = rc(e, RC_AUTH); assert o["result"] == "ALREADY_CURRENT" and o["recomposite_performed"] is False
o = run(e, evidence(product_candidates=BLACK), AUTH, provider(), jid="x"); assert o["result"] == "ALREADY_RENDERED" and o["render_job_id"] == "origjob001-rc1"
print(" RC3. PASS a second recomposite is ALREADY_CURRENT; a render request on the new package is ALREADY_RENDERED; no call made"); e.done()
# RC4 a scene the corrected compositor cannot use fails closed: nothing moved, nothing published
e = Env(); old_package(e); _pv.draw_scene("1024x1024", (20, 20, 22), 3, behaviour="no_marker").save(os.path.join(e.C, "1901-093/generated-scenes/03-travel-base.png"), "PNG"); snap_ = {f: open(os.path.join(e.C, f), "rb").read() for f in e.tree()}
o = rc(e, RC_AUTH); assert o["result"] == "RECOMPOSITE_FAILED" and o["recomposite_performed"] is False and {f: open(os.path.join(e.C, f), "rb").read() for f in e.tree()} == snap_ and not os.path.isdir(os.path.join(e.C, "_superseded")) and not any(d.startswith(".tmp-") for d in e.dirs())
print(" RC4. PASS unusable stored scene: RECOMPOSITE_FAILED, original package untouched, no temp left"); e.done()
# RC5 source drift: the staged handoff no longer matches the package source
e = Env(); old_package(e); hm = os.path.join(e.H, "1901-093/manifest.json"); hmj = json.load(open(hm)); hmj["source"]["sha256"] = "0" * 64; json.dump(hmj, open(hm, "w"))
o = rc(e, RC_AUTH); assert o["result"] == "SOURCE_MISMATCH" and not os.path.isdir(os.path.join(e.C, "_superseded")); print(" RC5. PASS source drift blocks the recomposite"); e.done()
# RC6 no package / missing base scene
e = Env(); assert rc(e, RC_AUTH)["result"] == "CAMPAIGN_NOT_FOUND"; old_package(e); os.remove(os.path.join(e.C, "1901-093/generated-scenes/02-story-base.png")); assert rc(e, RC_AUTH)["result"] == "CAMPAIGN_CONFLICT"; e.done()
print(" RC6. PASS missing package or missing base scene fails closed")
print("ALL PATCH TESTS PASS")
if "--dump" in sys.argv:
    for n in (1, 2, 4, 14, 13, 22, 23, 8, 9, 11, 18, 19, 20, "M4", "R1", "RC1", "RC2"):
        open(os.path.join(HERE, f"ex{n}.json"), "w").write(json.dumps(examples[n], indent=1, ensure_ascii=False) + "\n")
