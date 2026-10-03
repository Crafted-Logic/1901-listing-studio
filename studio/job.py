"""The governed render job. `run()` is the whole skill's decision chain; the CLI and tests call it.

evidence (everything Walter read live in this run, as JSON):
  queue:      1901-read-idea-queue result
  resolver:   1901-resolve-production-source result
  handoff:    1901-prepare-production-handoff result (blockers with code/detail/open_items)
  product:    {"candidates": [{"blank","provider","color","garment_rgb","spec_source"}, ...]}
  requires_transparency: true | false | null  (what the governing production record says)
  monthly_recorded_usd: number | null         (sum of this month's Render Expense Log rows; null = log unreadable)
  atmosphere: {"concept","season","vibe"}      (metadata used only as mood words in prompts)
"""
import datetime, hashlib, io, json, os, re, shutil, uuid
from PIL import Image

from . import budget as budget_mod, compositor, config, contact_sheet, handoff as handoff_mod, pricing, prompts, qa

BRIDGE = re.compile(r"image.handoff bridge|render.stage bridge|handoff bridge", re.I)
GOVERNANCE = {"DOCUMENTATION_CONFLICT", "SOFT_IP_BLOCK", "OPEN_ITEM_BLOCK", "BUDGET_BLOCK", "UNKNOWN_BLOCKER"}
APPROVAL = {"STATUS_NOT_APPROVED", "MISSING_HUMAN_APPROVAL", "HUMAN_REVISE", "HUMAN_REJECT"}
SOURCEISH = {"AMBIGUOUS_SOURCE", "SOURCE_NOT_MASTER", "SOURCE_UNVERIFIED"}


RECOMPOSITE_WORDS = ("AUTHORIZE", "LISTING", "RECOMPOSITE")


def compositor_commit():
    """Commit of this skill's local clone, read from .git without running git (pure file reads). None if unknown."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        head = open(os.path.join(root, ".git", "HEAD"), encoding="utf-8").read().strip()
        if not head.startswith("ref: "): return head[:12]
        ref = head[5:]; path = os.path.join(root, ".git", ref)
        if os.path.isfile(path): return open(path, encoding="utf-8").read().strip()[:12]
        for line in open(os.path.join(root, ".git", "packed-refs"), encoding="utf-8"):
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref: return parts[0][:12]
    except Exception:  # noqa: BLE001
        return None
    return None


def recomposite_command(message, design_id):
    if not isinstance(message, str): return None
    parts = message.strip().split()
    if len(parts) != 4 or tuple(w.upper() for w in parts[:3]) != RECOMPOSITE_WORDS: return None
    return ("OK", message.strip()) if parts[3] == design_id else ("OTHER_ID", parts[3])


def recomposite(design_id, message, handoff_root=config.HANDOFF_ROOT, campaign_root=config.CAMPAIGN_ROOT, now=None, new_job_id=None):
    """Local recomposite of an existing reviewed campaign with the current compositor: the six stored base scenes and the
    exact source are reused, NO provider is constructed, no generation call is possible, no spend. The existing package
    is never overwritten or deleted: it is moved whole to _superseded/<design_id>-<render_job_id>/ beside a
    SUPERSEDED.json record, and the new package takes its place at <campaign root>/<design_id>/ in one rename each.
    Proposal-before-authorization: only the exact command AUTHORIZE LISTING RECOMPOSITE <design_id> performs it."""
    now = now or now_iso()
    did = design_id.strip() if isinstance(design_id, str) else ""
    out = {"design_id": did, "result": "", "recomposite_performed": False, "render_job_id": "", "supersedes": None, "generation_calls": 0, "estimated_api_cost_usd": 0.0,
           "compositor": {"version": compositor.COMPOSITOR_VERSION, "commit": compositor_commit()}, "timestamp": now,
           "campaign": {"root": campaign_root, "design_folder": "", "manifest_path": "", "superseded_folder": "", "superseded_record": ""},
           "authorization": {"received": False, "evidence": ""}, "warnings": [], "checks": [], "human_action_required": None}
    checks, warnings = out["checks"], out["warnings"]
    def chk(name, status, detail): checks.append({"check": name, "status": status, "detail": detail})
    def done(result, action=None): out["result"] = result; out["human_action_required"] = action; return out
    auth = recomposite_command(message, did)
    if not did or any(ch.isspace() for ch in did):
        chk("input", "FAIL", "no single usable design_id"); return done("NOT_FOUND", "Supply exactly one design_id, then re-run.")
    folder = os.path.join(campaign_root, did); mpath = os.path.join(folder, "manifest.json")
    if not os.path.isfile(mpath):
        chk("existing_campaign", "FAIL", f"no reviewed campaign package at {folder}"); return done("CAMPAIGN_NOT_FOUND", f"There is no campaign package for {did} to recomposite; render one first.")
    try:
        m = json.load(open(mpath, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        chk("existing_campaign", "FAIL", f"manifest unreadable ({e.__class__.__name__})"); return done("CAMPAIGN_CONFLICT", f"The campaign manifest for {did} is unreadable; a human must review {folder}.")
    orig = m.get("render_job_id", ""); m_sha = sha256_bytes(open(mpath, "rb").read())
    bad = [n for n, h in (m.get("final_sha256") or {}).items() if not os.path.isfile(os.path.join(folder, "final-composites", n)) or sha256_bytes(open(os.path.join(folder, "final-composites", n), "rb").read()) != h]
    scenes = m.get("generated_scenes") or []
    missing = [n for n in scenes if not os.path.isfile(os.path.join(folder, "generated-scenes", n))]
    if m.get("result") != "READY_FOR_HUMAN_RENDER_REVIEW" or len(scenes) != 6 or bad or missing or m.get("design_id") != did:
        chk("existing_campaign", "FAIL", f"package does not verify: result {m.get('result')!r}, scenes {len(scenes)}, missing {missing}, hash mismatches {bad}")
        return done("CAMPAIGN_CONFLICT", f"The campaign package for {did} does not verify; a human must review {folder}. Nothing was changed.")
    chk("existing_campaign", "PASS", f"job {orig}: six finals hash-verified, six base scenes present, result READY_FOR_HUMAN_RENDER_REVIEW")
    if (m.get("rendering") or {}).get("compositor_version") == compositor.COMPOSITOR_VERSION:
        chk("compositor_version", "FAIL", f"the package was already composited with compositor {compositor.COMPOSITOR_VERSION}")
        return done("ALREADY_CURRENT", f"The campaign for {did} is already composited with the current compositor; nothing to redo.")
    chk("compositor_version", "PASS", f"package compositor {(m.get('rendering') or {}).get('compositor_version', 'unversioned')!r} → current {compositor.COMPOSITOR_VERSION} (commit {out['compositor']['commit']})")
    # source: the package copy must equal the manifest's hash and the staged handoff's
    src_name = m["source"]["filename"]; art_path = os.path.join(folder, "source", src_name)
    try:
        src_bytes = open(art_path, "rb").read()
    except OSError:
        chk("source", "FAIL", "package source file missing"); return done("CAMPAIGN_CONFLICT", f"The source copy in the campaign package for {did} is missing; a human must review {folder}.")
    staged = os.path.join(handoff_root, did, "manifest.json")
    try:
        staged_sha = json.load(open(staged, encoding="utf-8"))["source"]["sha256"]
    except Exception:  # noqa: BLE001
        staged_sha = None
    if sha256_bytes(src_bytes) != m["source"]["sha256"] or staged_sha != m["source"]["sha256"]:
        chk("source", "FAIL", f"package source sha {sha256_bytes(src_bytes)[:12]}…, manifest {m['source']['sha256'][:12]}…, staged handoff {str(staged_sha)[:12]}…")
        return done("SOURCE_MISMATCH", f"The approved source for {did} no longer matches the campaign's source; a human must review before any recomposite.")
    chk("source", "PASS", f"exact approved source {src_name} (sha256 {m['source']['sha256'][:12]}…) equals the staged handoff; it will be reused byte-for-byte")
    product = m["product"]; garment_rgb = product["garment_rgb"]
    sup_root = os.path.join(campaign_root, "_superseded"); sup_folder = os.path.join(sup_root, f"{did}-{orig}"); sup_record = sup_folder + ".SUPERSEDED.json"
    if os.path.exists(sup_folder) or os.path.exists(sup_record):
        chk("supersession", "FAIL", f"{sup_folder} already exists"); return done("CAMPAIGN_CONFLICT", f"A superseded package for job {orig} already exists; a human must review {sup_root}.")
    n = 1 + sum(1 for d in (os.listdir(sup_root) if os.path.isdir(sup_root) else []) if d.startswith(f"{did}-{orig}-rc"))
    job_id = new_job_id or f"{orig}-rc{n}"
    out["render_job_id"] = job_id; out["campaign"].update(design_folder=folder, manifest_path=mpath, superseded_folder=sup_folder, superseded_record=sup_record)
    out["supersedes"] = {"render_job_id": orig, "folder": folder, "manifest_sha256": m_sha, "original_result": m.get("result"), "original_estimated_api_cost_usd": m.get("estimated_api_cost_usd"), "original_final_sha256": m.get("final_sha256")}
    scene_shas = {n_: sha256_bytes(open(os.path.join(folder, "generated-scenes", n_), "rb").read()) for n_ in scenes}
    chk("base_scenes", "PASS", "six stored base scenes will be reused; no generation call: " + ", ".join(f"{k} {v[:8]}" for k, v in scene_shas.items()))
    if not (auth and auth[0] == "OK"):
        if auth: chk("authorization", "FAIL", f"the command names {auth[1]}, not the target {did}; it authorizes nothing in this run")
        else: chk("authorization", "FAIL", f"the current run does not contain the exact command AUTHORIZE LISTING RECOMPOSITE {did}; nothing was changed")
        return done("AWAITING_RECOMPOSITE_AUTHORIZATION", f"Nothing changed. Job {orig} for {did} would be recomposited locally with compositor {compositor.COMPOSITOR_VERSION} from its six stored base scenes and the exact source (sha256 {m['source']['sha256'][:12]}…), with no generation call and no spend, as job {job_id}; the current package would move whole to {sup_folder} with {os.path.basename(sup_record)} beside it, and the new package would be published at {folder} for human review. To authorize exactly this, send exactly: AUTHORIZE LISTING RECOMPOSITE {did}")
    out["authorization"].update(received=True, evidence=auth[1]); chk("authorization", "PASS", f"current run contains the exact command: {auth[1]}")
    tmp = os.path.join(campaign_root, f".tmp-{did}-{job_id}")
    for sub in ("source", "generated-scenes", "final-composites", "qa"): os.makedirs(os.path.join(tmp, sub), exist_ok=False)
    def fail(code, action):
        shutil.rmtree(tmp, ignore_errors=True); chk("recomposite", "INFO", "temporary directory removed; the existing package was not touched"); return done(code, action)
    try:
        for f in os.listdir(os.path.join(folder, "source")): shutil.copyfile(os.path.join(folder, "source", f), os.path.join(tmp, "source", f))
        for f in os.listdir(os.path.join(folder, "generated-scenes")): shutil.copyfile(os.path.join(folder, "generated-scenes", f), os.path.join(tmp, "generated-scenes", f))
        new_art = os.path.join(tmp, "source", src_name)
        if sha256_bytes(open(new_art, "rb").read()) != m["source"]["sha256"]: raise ValueError("source copy hash changed")
        json.dump({"design_id": did, "recomposite_of_render_job_id": orig, "source_sha256": m["source"]["sha256"], "base_scenes_reused": scene_shas, "compositor_version": compositor.COMPOSITOR_VERSION, "compositor_commit": out["compositor"]["commit"], "lineage": "exact byte copies of the superseded package's source and generated scenes; nothing regenerated"}, open(os.path.join(tmp, "source", "recomposite-reference.json"), "w", encoding="utf-8"), indent=2)
    except Exception as e:  # noqa: BLE001
        chk("source_copy", "FAIL", f"{e.__class__.__name__}: {e}"); return fail("VERIFICATION_FAILED", f"The package could not be copied for {did}; nothing was changed.")
    images = []; size = tuple(int(x) for x in (m.get("rendering") or {}).get("size", "1024x1024").split("x"))
    for slot_rec in m["scene_slots"]:
        slot, role, key = slot_rec["slot"], slot_rec["role"], config.SLOTS[slot_rec["slot"] - 1][1]
        base_name = f"{slot:02d}-{key}-base.png"; final_name = f"{slot:02d}-{key}.png"; base_path = os.path.join(tmp, "generated-scenes", base_name)
        try:
            final_img, placement = compositor.composite(open(base_path, "rb").read(), new_art, garment_rgb)
        except compositor.CompositeError as ce:
            chk(f"scene_{slot}", "FAIL", f"{ce.code}: {ce.detail}; no reroll is possible in a recomposite"); return fail("RECOMPOSITE_FAILED", f"Scene {slot} of job {orig} cannot be composited by compositor {compositor.COMPOSITOR_VERSION} ({ce.detail}). The existing package is unchanged; a new render would need its own authorization.")
        except Exception as e:  # noqa: BLE001
            chk(f"scene_{slot}", "FAIL", f"compositing error ({e.__class__.__name__}: {e})"); return fail("RECOMPOSITE_FAILED", f"Deterministic compositing failed on scene {slot} for {did}; the existing package is unchanged.")
        final_path = os.path.join(tmp, "final-composites", final_name); final_img.save(final_path, format="PNG")
        result, qchecks, notes = qa.check_image(slot, role, base_path, final_path, new_art, placement, product, size)
        rec = {"slot": slot, "role": role, "quality": slot_rec["quality"], "model": slot_rec["model"], "base_scene": f"generated-scenes/{base_name}", "final_composite": f"final-composites/{final_name}", "final_sha256": sha256_bytes(open(final_path, "rb").read()), "placement": placement, "qa_result": result, "checks": qchecks, "notes": notes, "source_sha256": m["source"]["sha256"], "product": {k: product[k] for k in ("blank", "provider", "color")}, "rerolls_used_here": slot_rec.get("rerolls_used_here", 0), "prompt": slot_rec.get("prompt", "")}
        images.append(rec)
        if result != "PASS":
            chk(f"scene_{slot}", "FAIL", "deterministic QA: " + "; ".join(f"{k} {v['detail']}" for k, v in qchecks.items() if v["result"] == "FAIL")); return fail("QA_FAILED", f"Scene {slot} for {did} failed deterministic QA under compositor {compositor.COMPOSITOR_VERSION}; the existing package is unchanged.")
        chk(f"scene_{slot}", "PASS", f"{role} recomposited from the stored base scene at scale {placement['scale']}, deterministic QA PASS")
    try:
        contact_sheet.build([(os.path.join(tmp, i["final_composite"]), f"{i['slot']:02d} {i['role']} ({i['quality']})") for i in images], os.path.join(tmp, "qa", "contact-sheet.png"))
        cchecks = qa.campaign_checks(images, m["source"]["sha256"], {k: product[k] for k in ("blank", "provider", "color")})
        qa_doc = {"design_id": did, "render_job_id": job_id, "recomposite_of_render_job_id": orig, "campaign_result": "PASS" if all(cchecks.values()) else "FAIL", "images": [{k: i[k] for k in ("slot", "role", "base_scene", "final_composite", "qa_result", "checks", "notes")} for i in images], "campaign_checks": cchecks, "human_review": {"required": True, "items": list(qa.HUMAN_CHECKS)}}
        json.dump(qa_doc, open(os.path.join(tmp, "qa", "qa.json"), "w", encoding="utf-8"), indent=2)
        if qa_doc["campaign_result"] != "PASS": chk("campaign_qa", "FAIL", json.dumps(cchecks)); return fail("QA_FAILED", f"Campaign-level QA failed for {did}; the existing package is unchanged.")
        cost = {"render_job_id": job_id, "design_id": did, "recomposite_of_render_job_id": orig, "started_at": now, "completed_at": now, "model": (m.get("rendering") or {}).get("model"), "size": (m.get("rendering") or {}).get("size"), "quality_mix": config.QUALITY_MIX, "images_generated": 0, "generation_calls": 0, "rerolls": 0, "source_drive_id": m["source"].get("drive_file_id"), "source_sha256": m["source"]["sha256"], "usage_record": [], "estimated_api_cost_usd": 0.0, "campaign_folder": folder, "job_status": "COMPLETED", "budget_flag": "OK", "notes": [f"local recomposite of job {orig} with compositor {compositor.COMPOSITOR_VERSION} (commit {out['compositor']['commit']}); no generation call; no spend; that job's own cost log is preserved under _superseded"], "actual_billed_cost_usd": None}
        json.dump(cost, open(os.path.join(tmp, "cost-log.json"), "w", encoding="utf-8"), indent=2)
        manifest = {**{k: v for k, v in m.items() if k not in ("scene_slots", "final_composites", "final_sha256", "qa_status", "estimated_api_cost_usd", "reroll_count", "created_at", "render_job_id", "rendering")},
                    "render_job_id": job_id, "created_at": now, "result": "READY_FOR_HUMAN_RENDER_REVIEW",
                    "rendering": {**(m.get("rendering") or {}), "compositor": "marker-geometry + fringe-aware removal + converged harmonic reconstruction + ring-texture quilting + pillow-perspective + bounded-luminance-multiply", "compositor_version": compositor.COMPOSITOR_VERSION, "compositor_commit": out["compositor"]["commit"], "artwork_transformations": "geometric and bounded lighting only"},
                    "recomposite": {"of_render_job_id": orig, "reason": "compositor revision; the first package reached READY_FOR_HUMAN_RENDER_REVIEW but required compositor correction", "superseded_package": os.path.relpath(sup_folder, campaign_root), "superseded_record": os.path.relpath(sup_record, campaign_root), "superseded_manifest_sha256": m_sha, "original_final_sha256": m.get("final_sha256"), "base_scenes_reused": scene_shas, "source_sha256": m["source"]["sha256"], "generation_calls": 0, "estimated_api_cost_usd": 0.0, "original_estimated_api_cost_usd": m.get("estimated_api_cost_usd"), "original_reroll_count": m.get("reroll_count")},
                    "scene_slots": [{"slot": i["slot"], "role": i["role"], "quality": i["quality"], "model": i["model"], "prompt": i["prompt"], "placement": i["placement"], "rerolls_used_here": i["rerolls_used_here"]} for i in images],
                    "generated_scenes": scenes, "final_composites": [i["final_composite"].split("/", 1)[1] for i in images], "final_sha256": {i["final_composite"].split("/", 1)[1]: i["final_sha256"] for i in images},
                    "qa_status": qa_doc["campaign_result"], "qa_path": "qa/qa.json", "contact_sheet": "qa/contact-sheet.png", "estimated_api_cost_usd": 0.0, "reroll_count": 0, "cost_log": "cost-log.json", "publication_authorized": False, "human_review_required": True}
        json.dump(manifest, open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8"), indent=2)
    except Exception as e:  # noqa: BLE001
        chk("manifest", "FAIL", f"{e.__class__.__name__}: {e}"); return fail("MANIFEST_FAILED", f"The recomposite records for {did} could not be written; the existing package is unchanged.")
    chk("manifest", "PASS", "qa.json, contact-sheet.png, cost-log.json (zero generation, zero spend) and manifest.json with the recomposite block written")
    m2 = json.load(open(os.path.join(tmp, "manifest.json"), encoding="utf-8"))
    expected = [os.path.join("source", src_name), "source/manifest.json", "source/source-reference.json", "source/recomposite-reference.json", "qa/qa.json", "qa/contact-sheet.png", "cost-log.json", "manifest.json"] + [f"generated-scenes/{n_}" for n_ in scenes] + [f"final-composites/{n_}" for n_ in m2["final_composites"]]
    missing = [f for f in expected if not os.path.isfile(os.path.join(tmp, f))]
    bad_hash = [n_ for n_, h in m2["final_sha256"].items() if sha256_bytes(open(os.path.join(tmp, "final-composites", n_), "rb").read()) != h]
    if missing or bad_hash or len(m2["final_composites"]) != 6 or m2["publication_authorized"] is not False or sha256_bytes(open(new_art, "rb").read()) != m["source"]["sha256"] or any(sha256_bytes(open(os.path.join(tmp, "generated-scenes", n_), "rb").read()) != h for n_, h in scene_shas.items()):
        chk("package_verification", "FAIL", f"missing {missing}, hash mismatches {bad_hash}"); return fail("VERIFICATION_FAILED", f"The recomposited package for {did} did not verify; the existing package is unchanged.")
    # publish: supersede the existing package whole (one rename), record it, then put the new package in place (one rename)
    os.makedirs(sup_root, exist_ok=True)
    if sha256_bytes(open(mpath, "rb").read()) != m_sha:
        chk("supersession", "FAIL", "the existing manifest changed during the recomposite"); return fail("CAMPAIGN_CONFLICT", f"The campaign for {did} changed while the recomposite ran; a human must review.")
    os.rename(folder, sup_folder)
    try:
        json.dump({"design_id": did, "render_job_id": orig, "superseded_by": job_id, "superseded_at": now, "reason": "compositor revision; the first composite package reached READY_FOR_HUMAN_RENDER_REVIEW but required compositor correction", "original_result": m.get("result"), "original_manifest_sha256": m_sha, "original_final_sha256": m.get("final_sha256"), "original_estimated_api_cost_usd": m.get("estimated_api_cost_usd"), "folder": os.path.relpath(sup_folder, campaign_root), "preserved": "whole package moved by rename; no file inside it was modified"}, open(sup_record, "w", encoding="utf-8"), indent=2)
        os.rename(tmp, folder)
    except Exception as e:  # noqa: BLE001
        try:
            if os.path.isfile(sup_record): os.remove(sup_record)
            if not os.path.exists(folder): os.rename(sup_folder, folder)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        chk("supersession", "FAIL", f"publish failed ({e.__class__.__name__}: {e}); the original package was restored"); return done("VERIFICATION_FAILED", f"The recomposited package for {did} could not be published; the original package is back in place.")
    if sha256_bytes(open(os.path.join(sup_folder, "manifest.json"), "rb").read()) != m_sha:
        chk("supersession", "FAIL", "superseded manifest hash changed"); return done("VERIFICATION_FAILED", f"The superseded package for {did} did not verify after the move; a human must review {sup_root}.")
    out["recomposite_performed"] = True
    chk("supersession", "PASS", f"job {orig} moved whole to {sup_folder} (manifest sha256 unchanged) with {os.path.basename(sup_record)} beside it; job {job_id} published at {folder}")
    chk("package_verification", "PASS", f"{len(expected)} files present, six finals hash-verified, six base scenes byte-identical to the superseded package, publication_authorized=false, generation_calls=0")
    return done("READY_FOR_HUMAN_RENDER_REVIEW", None)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_id_of(url):
    m = re.search(r"/d/([^/?#]+)", url or "") or re.search(r"[?&]id=([^&#]+)", url or "")
    return m.group(1) if m else None


def authorization_command(message, design_id):
    if not isinstance(message, str): return None
    parts = message.strip().split()
    if len(parts) != 4 or tuple(w.upper() for w in parts[:3]) != config.COMMAND_WORDS: return None
    return ("OK", message.strip()) if parts[3] == design_id else ("OTHER_ID", parts[3])


def sha256_bytes(b): return hashlib.sha256(b).hexdigest()


def local_month_spend(campaign_root, month_prefix):
    """Floor for monthly spend from local cost logs (final and failed campaigns) started this month."""
    total = 0.0
    if not os.path.isdir(campaign_root):
        return 0.0
    for dirpath, _, files in os.walk(campaign_root):
        if "cost-log.json" in files:
            try:
                c = json.load(open(os.path.join(dirpath, "cost-log.json"), encoding="utf-8"))
                if str(c.get("started_at", "")).startswith(month_prefix):
                    total += float(c.get("estimated_api_cost_usd") or 0)
            except Exception:  # noqa: BLE001
                continue
    return round(total, 6)


DEFECT_KEYS = ("design_id", "render_job_id", "defect", "corrected_in", "ruled_by", "ruled_at")


def prior_failed_jobs(campaign_root, design_id):
    """Failed jobs of this design under _failed/, read-only, each with its FAILED.json result, its reroll count
    and spend from cost-log.json, and its attribution. Attribution is "generation" unless a human has recorded a
    validator-defect ruling beside the folder as <design_id>-<render_job_id>.validator-defect.json naming that
    exact job, the defect, the commit that corrected it, who ruled and when; anything less is ignored with a
    warning. The failed folder itself is never modified."""
    failed_root = os.path.join(campaign_root, "_failed"); jobs = []
    if not os.path.isdir(failed_root):
        return jobs
    for name in sorted(os.listdir(failed_root)):
        folder = os.path.join(failed_root, name)
        if not name.startswith(design_id + "-") or not os.path.isdir(folder):
            continue
        job_id = name[len(design_id) + 1:]
        rec = {"render_job_id": job_id, "folder": folder, "result": None, "rerolls": None, "estimated_api_cost_usd": None, "attribution": "generation", "validator_defect": None, "warnings": []}
        try:
            rec["result"] = json.load(open(os.path.join(folder, "FAILED.json"), encoding="utf-8")).get("result")
        except Exception:  # noqa: BLE001
            rec["warnings"].append("FAILED.json unreadable")
        try:
            c = json.load(open(os.path.join(folder, "cost-log.json"), encoding="utf-8")); rec["rerolls"] = c.get("rerolls"); rec["estimated_api_cost_usd"] = c.get("estimated_api_cost_usd")
        except Exception:  # noqa: BLE001
            rec["warnings"].append("cost-log.json unreadable")
        dpath = folder + ".validator-defect.json"
        if os.path.isfile(dpath):
            try:
                d = json.load(open(dpath, encoding="utf-8"))
            except Exception:  # noqa: BLE001
                d = None; rec["warnings"].append("validator-defect record unreadable; treated as an ordinary failure")
            if isinstance(d, dict):
                missing = [k for k in DEFECT_KEYS if not isinstance(d.get(k), str) or not d.get(k).strip()]
                if missing or d["design_id"] != design_id or d["render_job_id"] != job_id:
                    rec["warnings"].append("validator-defect record does not name this exact job with design_id, render_job_id, defect, corrected_in, ruled_by and ruled_at; treated as an ordinary failure")
                else:
                    rec["attribution"] = "validator-defect"; rec["validator_defect"] = {k: d[k].strip() for k in DEFECT_KEYS}
            elif d is not None:
                rec["warnings"].append("validator-defect record is not a JSON object; treated as an ordinary failure")
        jobs.append(rec)
    return jobs


def inspect_existing(campaign_root, design_id, source_sha, product):
    folder = os.path.join(campaign_root, design_id)
    if not os.path.isdir(folder):
        return "NONE", "no campaign folder exists", None
    mp = os.path.join(folder, "manifest.json")
    try:
        m = json.load(open(mp, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return "CAMPAIGN_CONFLICT", f"campaign folder exists but manifest.json is missing or unreadable ({e.__class__.__name__})", None
    problems = []
    if m.get("design_id") != design_id: problems.append("different design_id")
    if (m.get("source") or {}).get("sha256") != source_sha: problems.append("different source SHA-256")
    if {k: (m.get("product") or {}).get(k) for k in ("blank", "provider", "color")} != {k: product.get(k) for k in ("blank", "provider", "color")}: problems.append("different product specification")
    if m.get("schema_version") != config.SCHEMA_VERSION: problems.append("different campaign schema")
    finals = [os.path.join(folder, "final-composites", f) for f in (m.get("final_composites") or [])]
    if len(finals) != 6 or not all(os.path.isfile(f) for f in finals): problems.append("six-image package incomplete")
    if m.get("qa_status") != "PASS": problems.append("QA status is not PASS")
    if problems:
        return "CAMPAIGN_CONFLICT", "existing campaign differs: " + ", ".join(problems), m
    return "ALREADY_RENDERED", "existing campaign has the same design, source hash, product specification and schema, a complete six-image package and QA PASS", m


def verify_package_for_reuse(campaign_root, design_id):
    """The existing reviewed package whose six base scenes a new job may reuse. Returns (info, problem)."""
    folder = os.path.join(campaign_root, design_id); mpath = os.path.join(folder, "manifest.json")
    if not os.path.isfile(mpath): return None, f"no reviewed campaign package at {folder} to reuse scenes from"
    try: m = json.load(open(mpath, encoding="utf-8"))
    except Exception as e: return None, f"manifest unreadable ({e.__class__.__name__})"  # noqa: BLE001
    scenes = m.get("generated_scenes") or []; missing = [n for n in scenes if not os.path.isfile(os.path.join(folder, "generated-scenes", n))]
    bad = [n for n, h in (m.get("final_sha256") or {}).items() if not os.path.isfile(os.path.join(folder, "final-composites", n)) or sha256_bytes(open(os.path.join(folder, "final-composites", n), "rb").read()) != h]
    if m.get("design_id") != design_id or m.get("result") != "READY_FOR_HUMAN_RENDER_REVIEW" or len(scenes) != 6 or missing or bad or len(m.get("scene_slots") or []) != 6:
        return None, f"package does not verify: result {m.get('result')!r}, scenes {len(scenes)}, missing {missing}, hash mismatches {bad}"
    return {"render_job_id": m.get("render_job_id"), "folder": folder, "manifest": m, "manifest_sha256": sha256_bytes(open(mpath, "rb").read()),
            "base_scenes": {n: sha256_bytes(open(os.path.join(folder, "generated-scenes", n), "rb").read()) for n in scenes}}, None


def supersede_and_publish(campaign_root, design_id, folder, tmp, old_manifest, old_manifest_sha, new_job_id, now, reason):
    """Move the existing package whole to _superseded/<design>-<job>/ (one rename), write the SUPERSEDED record beside it,
    then rename the new package into place. On failure the original is put back. Returns (ok, detail, sup_folder, sup_record)."""
    sup_root = os.path.join(campaign_root, "_superseded"); orig = old_manifest.get("render_job_id", ""); sup_folder = os.path.join(sup_root, f"{design_id}-{orig}"); sup_record = sup_folder + ".SUPERSEDED.json"
    if os.path.exists(sup_folder) or os.path.exists(sup_record): return False, f"{sup_folder} already exists", sup_folder, sup_record
    os.makedirs(sup_root, exist_ok=True)
    if sha256_bytes(open(os.path.join(folder, "manifest.json"), "rb").read()) != old_manifest_sha: return False, "the existing manifest changed during the job", sup_folder, sup_record
    os.rename(folder, sup_folder)
    try:
        json.dump({"design_id": design_id, "render_job_id": orig, "superseded_by": new_job_id, "superseded_at": now, "reason": reason, "original_result": old_manifest.get("result"), "original_manifest_sha256": old_manifest_sha, "original_final_sha256": old_manifest.get("final_sha256"), "original_estimated_api_cost_usd": old_manifest.get("estimated_api_cost_usd"), "original_source_sha256": (old_manifest.get("source") or {}).get("sha256"), "folder": os.path.relpath(sup_folder, campaign_root), "preserved": "whole package moved by rename; no file inside it was modified"}, open(sup_record, "w", encoding="utf-8"), indent=2)
        os.rename(tmp, folder)
    except Exception as e:  # noqa: BLE001
        try:
            if os.path.isfile(sup_record): os.remove(sup_record)
            if not os.path.exists(folder): os.rename(sup_folder, folder)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return False, f"publish failed ({e.__class__.__name__}: {e}); the original package was restored", sup_folder, sup_record
    if sha256_bytes(open(os.path.join(sup_folder, "manifest.json"), "rb").read()) != old_manifest_sha: return False, "superseded manifest hash changed after the move", sup_folder, sup_record
    return True, "", sup_folder, sup_record


def run(design_id, evidence, message, provider, handoff_root=config.HANDOFF_ROOT, campaign_root=config.CAMPAIGN_ROOT, now=None, job_id=None, reuse_scenes=False):
    """reuse_scenes=True: a new governed job that reuses the six stored base scenes of the existing reviewed package for
    this design instead of generating (zero generation calls, zero spend), e.g. after the approved source changed or the
    compositor was corrected. Every governance check runs as usual; provider checks, pricing and budget are not needed
    (provider may be None); the existing package is superseded whole, never overwritten."""
    now = now or now_iso()
    out = {"design_id": "", "result": "", "render_performed": False, "render_job_id": "", "timestamp": now,
           "source": {"drive_file_id": "", "filename": "", "sha256": "", "staged_path": ""},
           "product": {"blank": "", "provider": "", "color": "", "spec_source": ""},
           "campaign": {"root": campaign_root, "design_folder": "", "manifest_path": "", "qa_path": "", "contact_sheet_path": "", "images": []},
           "budget": {"per_listing_limit_usd": config.PER_LISTING_LIMIT_USD, "monthly_limit_usd": config.MONTHLY_LIMIT_USD, "estimated_job_cost_usd": 0, "monthly_recorded_cost_usd": 0, "projected_monthly_cost_usd": 0, "budget_flag": ""},
           "verification": {"queue_verified": False, "human_approval_verified": False, "source_verified": False, "handoff_verified": False, "product_spec_verified": False, "pricing_verified": False, "budget_verified": False, "qa_passed": False, "campaign_verified": False},
           "rendering": {"provider": provider.name if provider else None, "model": provider.model if provider else None, "size": provider.size if provider else None, "quality_mix": config.QUALITY_MIX, "mode": "composited_fidelity", "compositor_version": compositor.COMPOSITOR_VERSION, "scene_reuse": None},
           "authorization": {"received": False, "evidence": ""}, "prior_failed_jobs": [], "proposed_expense_log_row": {}, "warnings": [], "checks": [], "human_action_required": None}
    checks, warnings, ver = out["checks"], out["warnings"], out["verification"]
    def chk(name, status, detail): checks.append({"check": name, "status": status, "detail": detail})
    def done(result, action=None): out["result"] = result; out["human_action_required"] = action; return out
    auth = authorization_command(message, design_id)

    did = design_id.strip() if isinstance(design_id, str) else ""
    out["design_id"] = did
    if not did or any(ch.isspace() for ch in did):
        chk("input", "FAIL", "no single usable design_id was supplied"); return done("NOT_FOUND", "Supply exactly one design_id, then re-run.")
    chk("input", "PASS", f"design_id '{did}' (trimmed)")

    # 1 queue
    q = evidence.get("queue") or {}
    r = q.get("result")
    if r in (None, "SOURCE_UNAVAILABLE", "SCHEMA_WARNING"):
        chk("queue_read", "FAIL", "the authoritative Idea Queue could not be read as expected; nothing substituted"); return done("SOURCE_UNAVAILABLE", "Restore read access to the authoritative Idea Queue, then re-run.")
    if r == "NOT_FOUND":
        chk("queue_read", "FAIL", f"no row has id exactly equal to {did}"); return done("NOT_FOUND", f"Correct the Idea Queue so exactly one row carries id {did}, then re-run.")
    if r == "DUPLICATE_ID":
        rows = (q.get("source") or {}).get("matching_rows", [])
        chk("queue_read", "FAIL", f"rows {rows} all carry id {did}; none chosen"); return done("DUPLICATE_ID", f"Resolve the duplicate Idea Queue rows for {did} (rows {', '.join(map(str, rows))}), then re-run.")
    rec, row = q["record"], (q.get("source") or {}).get("row_number")
    if any(rec.get(k) is None for k in ("status", "human_decision", "render_source_path")):
        chk("queue_read", "FAIL", "a required column is missing or duplicated in the live header row"); return done("SOURCE_UNAVAILABLE", "Repair the Idea Queue header row so status, human_decision and render_source_path each appear exactly once, then re-run.")
    ver["queue_verified"] = True; chk("queue_read", "PASS", f"exactly one row (sheet row {row}) carries id {did}")

    # 2 approval
    if rec["human_decision"] != "APPROVE":
        chk("human_approval", "FAIL", f"human_decision is '{rec['human_decision']}', not exactly APPROVE"); return done("HUMAN_APPROVAL_REQUIRED", f"A human must set human_decision to APPROVE for {did} in the live Idea Queue before it can be rendered.")
    if rec["status"] != "Approved":
        chk("human_approval", "FAIL", f"status is '{rec['status']}', not exactly Approved"); return done("HUMAN_APPROVAL_REQUIRED", f"Move {did} to status Approved through the normal approval workflow before it can be rendered.")
    ver["human_approval_verified"] = True; chk("human_approval", "PASS", "human_decision is exactly APPROVE and status is exactly Approved")

    # 3 source: render_source_path + resolver
    rsp = rec["render_source_path"]
    if rsp == "":
        chk("render_source_path", "FAIL", "render_source_path is blank"); return done("SOURCE_MISSING", f"Record the exact approved source file in render_source_path for {did} through 1901-set-production-source, then stage it with 1901-stage-render-source.")
    rsp_id = file_id_of(rsp)
    if not rsp_id:
        chk("render_source_path", "FAIL", f"render_source_path '{rsp}' does not identify a Drive file"); return done("SOURCE_MISMATCH", f"render_source_path for {did} is not a Drive file reference; a human must correct it through an authorized workflow.")
    res = (evidence.get("resolver") or {})
    rf = res.get("resolved_file") or {}
    if res.get("result") == "SOURCE_UNAVAILABLE":
        chk("source_resolution", "FAIL", "1901-resolve-production-source could not read a required live source"); return done("SOURCE_UNAVAILABLE", "Restore read access to the sources 1901-resolve-production-source needs, then re-run.")
    if res.get("result") != "RESOLVED" or not rf.get("drive_file_id"):
        chk("source_resolution", "FAIL", f"1901-resolve-production-source returned {res.get('result')}; only RESOLVED permits rendering"); return done("SOURCE_NOT_RESOLVED", res.get("human_action_required") or f"Resolve the production source for {did} before re-running.")
    if rsp_id != rf["drive_file_id"]:
        chk("source_identity", "FAIL", f"render_source_path names Drive file {rsp_id} but the resolver resolved {rf['drive_file_id']}"); return done("SOURCE_MISMATCH", f"render_source_path and the resolved production source for {did} name different Drive files; a human must reconcile them.")
    ver["source_verified"] = True; chk("source_identity", "PASS", f"render_source_path and the resolver name the same Drive file {rsp_id}")
    if rec.get("printify_id"):
        chk("printify_draft", "INFO", f"printify_id '{rec['printify_id']}' present: a parked production artifact; it does not bypass or block the render stage and is not touched by this skill")

    # 4 governance
    ho = evidence.get("handoff") or {}
    if ho.get("validation_mode") == "test_fixture" or ho.get("handoff_status") in (None, "SOURCE_UNAVAILABLE"):
        chk("governance", "FAIL", "1901-prepare-production-handoff produced no production evidence"); return done("SOURCE_UNAVAILABLE", "Restore read access to the sources 1901-prepare-production-handoff needs, then re-run.")
    remaining = []
    for b in ho.get("blockers") or []:
        if b["code"] == "OPEN_ITEM_BLOCK" and b.get("open_items") and all(BRIDGE.search(i) for i in b["open_items"]):
            w = "Readiness reported OPEN_ITEM_BLOCK solely for the open item that the image-handoff bridge is not built; that bridge exists (1901-stage-render-source), so the item was not treated as a blocker. No other Open Item was waived."
            warnings.append(w); chk("governance", "INFO", w); continue
        remaining.append(b)
    if remaining:
        codes = [b["code"] for b in remaining]; detail = "; ".join(f"{b['code']}: {b.get('detail', '')}" for b in remaining); chk("governance", "FAIL", detail)
        if any(c in APPROVAL for c in codes): return done("HUMAN_APPROVAL_REQUIRED", ho.get("next_action"))
        if "MISSING_SOURCE" in codes: return done("SOURCE_MISSING", ho.get("next_action"))
        if any(c in SOURCEISH for c in codes): return done("SOURCE_NOT_RESOLVED", ho.get("next_action"))
        if "SOURCE_UNAVAILABLE" in codes: return done("SOURCE_UNAVAILABLE", ho.get("next_action"))
        return done("GOVERNANCE_BLOCK", ho.get("next_action") or "Resolve the governance blocker named in checks and record the decision, then re-run.")
    chk("governance", "PASS", "1901-prepare-production-handoff reports no unresolved blocker for this design")

    # 5 staged handoff
    code, detail, info = handoff_mod.verify(handoff_root, did)
    if code:
        chk("staged_handoff", "FAIL", detail)
        return done(code, f"Stage the approved source for {did} with 1901-stage-render-source (two-step), then re-run." if code == "HANDOFF_NOT_STAGED" else f"The staged handoff for {did} does not verify ({detail}); a human must review it. Never repaired or re-staged automatically.")
    if info["drive_file_id"] != rsp_id:
        chk("staged_handoff", "FAIL", f"staged handoff is for Drive file {info['drive_file_id']}, but render_source_path names {rsp_id}"); return done("SOURCE_MISMATCH", f"The staged handoff for {did} is not the file render_source_path names; a human must review the handoff before rendering.")
    ver["handoff_verified"] = True; chk("staged_handoff", "PASS", detail)
    out["source"].update(drive_file_id=info["drive_file_id"], filename=info["filename"], sha256=info["sha256"], staged_path=info["staged_path"])
    try:
        art = Image.open(info["staged_path"]); art.load(); art_size, art_bands = art.size, art.getbands()
    except Exception as e:  # noqa: BLE001
        chk("source_image", "FAIL", f"staged source is not a readable image ({e.__class__.__name__})"); return done("HANDOFF_INVALID", f"The staged source for {did} cannot be opened as an image; a human must review the handoff.")
    if max(art_size) < config.MIN_SOURCE_LONG_SIDE_PX:
        chk("source_image", "FAIL", f"source is {art_size[0]}x{art_size[1]}px; listing composites need at least {config.MIN_SOURCE_LONG_SIDE_PX}px on the long side without upscaling")
        return done("RESOLUTION_BLOCK", f"The approved source for {did} is too small for believable listing composites without upscaling. Upscaling is a governed derived-asset step; no automatic upscale was performed.")
    has_alpha = "A" in art_bands
    req_t = evidence.get("requires_transparency")
    if req_t is True and not has_alpha:
        chk("source_image", "FAIL", "the governing record requires a transparent-background source and the staged source has no alpha channel")
        return done("ART_PREP_BLOCK", f"A transparency-prepared derivative of the approved master for {did} is required and does not exist. The canonical source was not altered; produce the derivative through a governed derived-asset step with lineage.")
    if req_t is None and not has_alpha:
        w = "The governing record states no transparency requirement and the source has no alpha channel; it was composited as an opaque panel. No transparency was invented."
        warnings.append(w)
    chk("source_image", "PASS", f"{art_size[0]}x{art_size[1]}px, bands {''.join(art_bands)}, alpha={'yes' if has_alpha else 'no'}")

    # 6 product specification
    cands = (evidence.get("product") or {}).get("candidates") or []
    distinct = []
    for cnd in cands:
        key = {k: cnd.get(k) for k in ("blank", "provider", "color")}
        if key not in [ {k: d.get(k) for k in ("blank", "provider", "color")} for d in distinct]: distinct.append(cnd)
    if not distinct:
        chk("product_spec", "FAIL", "no governed product/blank/provider/color specification is established for this design"); return done("PRODUCT_SPEC_BLOCK", f"Record the governed product specification (blank, provider, color) for {did} in the authoritative production record before rendering. Nothing was assumed.")
    if len(distinct) > 1:
        desc = " vs ".join(f"{d.get('blank')} / {d.get('provider')} / {d.get('color')} ({d.get('spec_source')})" for d in distinct)
        chk("product_spec", "FAIL", f"conflicting product specifications: {desc}"); return done("PRODUCT_SPEC_BLOCK", f"Authoritative records disagree on the product for {did}: {desc}. A human must record one governing specification.")
    product = distinct[0]
    if not all(product.get(k) for k in ("blank", "provider", "color", "spec_source")) or not product.get("garment_rgb"):
        chk("product_spec", "FAIL", "the product specification is incomplete (blank, provider, color, garment_rgb, spec_source all required)"); return done("PRODUCT_SPEC_BLOCK", f"The product specification for {did} is incomplete; a human must complete it in the authoritative production record.")
    out["product"] = {k: product[k] for k in ("blank", "provider", "color", "spec_source")}
    ver["product_spec_verified"] = True; chk("product_spec", "PASS", f"{product['blank']} / {product['provider']} / {product['color']} from {product['spec_source']}")

    # 7 provider: credentials, configured model, quality tiers, size, pricing (all read-only; no generation call)
    reuse = None
    if reuse_scenes:
        reuse, problem = verify_package_for_reuse(campaign_root, did)
        if reuse is None:
            chk("scene_reuse", "FAIL", problem); return done("CAMPAIGN_NOT_FOUND" if "no reviewed campaign" in problem else "CAMPAIGN_CONFLICT", f"Scenes cannot be reused for {did}: {problem}. Nothing was changed.")
        old = reuse["manifest"]; old_src = (old.get("source") or {}).get("sha256"); old_cv = (old.get("rendering") or {}).get("compositor_version")
        if old_src == info["sha256"] and old_cv == compositor.COMPOSITOR_VERSION:
            chk("scene_reuse", "FAIL", f"the existing package (job {reuse['render_job_id']}) already uses source {info['sha256'][:12]}… and compositor {compositor.COMPOSITOR_VERSION}"); return done("ALREADY_CURRENT", f"The campaign for {did} already has this source and compositor; nothing to redo.")
        size = (old.get("rendering") or {}).get("size", config.IMAGE_SIZE); model = (old.get("rendering") or {}).get("model"); pname = (old.get("rendering") or {}).get("provider")
        out["rendering"].update(provider=pname, model=model, size=size, scene_reuse={"from_render_job_id": reuse["render_job_id"], "base_scenes_reused": reuse["base_scenes"], "previous_source_sha256": old_src, "previous_compositor_version": old_cv, "generation_calls": 0})
        chk("scene_reuse", "PASS", f"six base scenes of job {reuse['render_job_id']} verified and will be reused ({pname} / {model}, {size}); previous source {str(old_src)[:12]}… → {info['sha256'][:12]}…, compositor {old_cv!r} → {compositor.COMPOSITOR_VERSION}; no generation call")
        snap = (old.get("rendering") or {}).get("pricing_snapshot"); prices = {qlt: 0.0 for qlt in config.QUALITY_MIX}
        plan = [{"slot": s_, "key": k, "role": role, "quality": qlt, "size": size, "model": model, "estimated_cost_usd": 0.0} for s_, k, role, qlt in config.SLOTS]; estimate = 0.0
        ver["pricing_verified"] = True; chk("pricing", "PASS", "scene reuse: no generation call, no per-image cost")
    else:
      size = provider.size
    if not reuse_scenes and not provider.credentials_available():
        chk("model_quality", "FAIL", f"no credentials are available in the runtime environment for provider {provider.name}"); return done("MODEL_OR_QUALITY_BLOCK", f"No image-provider credential is available to Walter for {provider.name}. Providing one is a credential decision for Jody; nothing was assumed and nothing was called.")
    avail = provider.model_available() if not reuse_scenes else None
    if not reuse_scenes and avail is False:
        chk("model_quality", "FAIL", f"configured model '{provider.model}' is not available to these credentials"); return done("MODEL_OR_QUALITY_BLOCK", f"The configured image model {provider.model} is not available on {provider.name}. Configure an available model; no substitute was chosen.")
    missing = [qlt for qlt in config.QUALITY_MIX if not provider.supports_quality(qlt)] if not reuse_scenes else []
    if not reuse_scenes and (missing or not provider.supports_size(size)):
        chk("model_quality", "FAIL", f"configured model '{provider.model}' capability record lacks " + (", ".join(f"quality '{q}'" for q in missing) if missing else f"size {size}")); return done("MODEL_OR_QUALITY_BLOCK", f"The configured model {provider.model} on {provider.name} is not recorded as supporting the governed quality mix (2 high, 4 medium) at {size}. A substitute model or tier needs explicit human authorization; none was assumed.")
    if not reuse_scenes: chk("model_quality", "PASS", f"{provider.name} / {provider.model}: credentials present, model {'verified available' if avail else 'availability not checked offline'}, high and medium at {size} per the configured capability record")
    if not reuse_scenes:
        snap = provider.pricing_snapshot()
        prices = {qlt: (pricing.cost_of(snap, qlt, size) if snap else None) for qlt in config.QUALITY_MIX}
    if not reuse_scenes and (snap is None or any(v is None for v in prices.values())):
        chk("pricing", "FAIL", f"no usable pricing snapshot for exactly {provider.name} / {provider.model} / {size} with both quality tiers before spend"); return done("PRICING_UNAVAILABLE", f"Record a current pricing snapshot for exactly {provider.name} / {provider.model} / {size} (provider, model, size, captured_at, basis, currency, per_image_usd by quality). A snapshot for another model is invalid; no per-image cost was guessed.")
    if not reuse_scenes:
        ver["pricing_verified"] = True; chk("pricing", "PASS", f"{snap['provider']} / {snap['model']} / {snap['size']} captured {snap['captured_at']}: high ${prices['high']:.4f}, medium ${prices['medium']:.4f} per image ({snap['basis']})")
        plan = [{"slot": s, "key": k, "role": role, "quality": qlt, "size": size, "model": provider.model, "estimated_cost_usd": prices[qlt]} for s, k, role, qlt in config.SLOTS]
        estimate = round(sum(p["estimated_cost_usd"] for p in plan), 6)

    # 8 budget
    mr = evidence.get("monthly_recorded_usd")
    if mr is None:
        chk("budget", "FAIL", "the Render Expense Log could not be read; monthly spend unknown"); return done("SOURCE_UNAVAILABLE", "Restore read access to the Render Expense Log tab, then re-run. No spend is allowed while monthly spend is unknown.")
    local = local_month_spend(campaign_root, now[:7])
    monthly = max(round(float(mr), 6), local)
    if local > float(mr) + 1e-9:
        warnings.append(f"Local cost logs for {now[:7]} total ${local:.4f}, more than the ${float(mr):.4f} recorded in the Render Expense Log; the larger figure was used.")
    guard = budget_mod.BudgetGuard(monthly)
    first = guard.check(prices["high"]); whole = guard.check(estimate)
    out["budget"].update(estimated_job_cost_usd=estimate, monthly_recorded_cost_usd=monthly, projected_monthly_cost_usd=whole["projected_monthly"])
    if not first["ok"] or not whole["ok"]:
        reason = first["reason"] if not first["ok"] else "the planned six-image campaign " + whole["reason"].split("next call ", 1)[-1]
        out["budget"]["budget_flag"] = "BLOCKED"; chk("budget", "FAIL", reason + "; no generation call was made")
        return done("BUDGET_BLOCK", f"Rendering {did} would exceed a governed budget cap ({reason}). Jody must raise the cap or hold the design. No spend occurred.")
    out["budget"]["budget_flag"] = "OK"; ver["budget_verified"] = True
    chk("budget", "PASS", f"planned campaign ${estimate:.4f} ≤ ${config.PER_LISTING_LIMIT_USD:.2f}; month ${monthly:.4f} → ${whole['projected_monthly']:.4f} ≤ ${config.MONTHLY_LIMIT_USD:.2f}")

    # 9 existing campaign
    folder = os.path.join(campaign_root, did)
    out["campaign"].update(design_folder=folder, manifest_path=os.path.join(folder, "manifest.json"), qa_path=os.path.join(folder, "qa", "qa.json"), contact_sheet_path=os.path.join(folder, "qa", "contact-sheet.png"))
    ex, exdetail, exm = inspect_existing(campaign_root, did, info["sha256"], product) if not reuse_scenes else (None, "", None)
    if reuse_scenes: chk("existing_campaign", "INFO", f"existing package (job {reuse['render_job_id']}) will be superseded whole by this job; nothing is overwritten")
    if ex == "CAMPAIGN_CONFLICT":
        chk("existing_campaign", "FAIL", exdetail); return done("CAMPAIGN_CONFLICT", f"A campaign folder for {did} already exists and does not match ({exdetail}); a human must review {folder}. Nothing was overwritten or regenerated.")
    if ex == "ALREADY_RENDERED":
        out["render_job_id"] = exm.get("render_job_id", ""); out["campaign"]["images"] = exm.get("final_composites", []); ver.update(qa_passed=True, campaign_verified=True)
        chk("existing_campaign", "PASS", exdetail); return done("ALREADY_RENDERED", None)
    if not reuse_scenes: chk("existing_campaign", "PASS", "no campaign folder exists for this design")

    # 9b prior failed jobs of this design (read-only): their spend already counts in the monthly floor above; their
    # rerolls never carry into a new job. A human-recorded validator-defect ruling marks a job whose rerolls were
    # consumed by a corrected internal defect rather than by generation; it is reported, never acted on automatically.
    prior = prior_failed_jobs(campaign_root, did); out["prior_failed_jobs"] = prior
    retry_notes = []
    for pj in prior:
        for w in pj["warnings"]: warnings.append(f"failed job {pj['render_job_id']}: {w}")
        if pj["attribution"] == "validator-defect":
            vd = pj["validator_defect"]
            retry_notes.append(f"retry after validator defect in job {pj['render_job_id']} ({vd['defect']}; corrected in {vd['corrected_in']}; ruled by {vd['ruled_by']} on {vd['ruled_at']}): that job's {pj['rerolls']} reroll(s) were caused by the defect, not by generation; this job's reroll allowance is the normal {config.MAX_REROLLS} and its spend counts as usual")
    if prior:
        chk("prior_failed_jobs", "INFO", "; ".join(f"{pj['render_job_id']}: {pj['result']}, {pj['rerolls']} reroll(s), ${float(pj['estimated_api_cost_usd'] or 0):.4f}, attribution {pj['attribution']}" + (f" (corrected in {pj['validator_defect']['corrected_in']})" if pj["validator_defect"] else "") for pj in prior) + "; artifacts preserved under _failed; a new job needs its own exact authorization")

    row_base = {"design_id": did, "model": f"{out['rendering']['provider']}/{out['rendering']['model']}", "size": size, "quality_mix": config.QUALITY_MIX, "source_drive_id": info["drive_file_id"], "source_sha256": info["sha256"], "pricing_snapshot": snap, "campaign_folder": folder}

    # 10 authorization
    if not (auth and auth[0] == "OK"):
        if auth: chk("authorization", "FAIL", f"the command names {auth[1]}, not the target {did}; it authorizes nothing in this run")
        else: chk("authorization", "FAIL", f"the current run does not contain the exact command AUTHORIZE LISTING RENDER {did}; ordinary requests and vague confirmations never authorize rendering")
        out["proposed_expense_log_row"] = {**row_base, "render_job_id": "", "started_at": "", "completed_at": "", "images_generated": 0, "rerolls": 0, "usage_record": [], "estimated_api_cost_usd": estimate, "job_status": "PROPOSED", "budget_flag": "OK", "notes": ["proposal only; no generation call made"] + retry_notes, "actual_billed_cost_usd": None}
        out["campaign"]["images"] = [f"{p['slot']:02d}-{p['key']}.png" for p in plan]
        if reuse_scenes:
            return done("AWAITING_RENDER_AUTHORIZATION", f"No generation call made and no campaign files created. {did} is eligible for a scene-reuse job: source {info['filename']} (Drive id {info['drive_file_id']}, sha256 {info['sha256'][:12]}…) staged at {info['staged_path']}; product {product['blank']} / {product['provider']} / {product['color']}; the six base scenes of job {reuse['render_job_id']} reused with compositor {compositor.COMPOSITOR_VERSION}, zero generation calls, zero spend; the existing package would move whole to _superseded and the new job would be published at {folder}. To authorize exactly this job, send exactly: AUTHORIZE LISTING RENDER {did}")
        return done("AWAITING_RENDER_AUTHORIZATION", f"No generation call made and no campaign files created. {did} is eligible: source {info['filename']} (Drive id {info['drive_file_id']}, sha256 {info['sha256'][:12]}…) staged at {info['staged_path']}; product {product['blank']} / {product['provider']} / {product['color']}; six scenes (2 high, 4 medium) at {size} on {provider.name} / {provider.model} at an estimated ${estimate:.4f}, month ${monthly:.4f} → ${whole['projected_monthly']:.4f}; output {folder}. To authorize exactly this render job, send exactly: AUTHORIZE LISTING RENDER {did}")
    out["authorization"].update(received=True, evidence=auth[1]); chk("authorization", "PASS", f"current run contains the exact command: {auth[1]}")

    # 11 the job
    job_id = job_id or uuid.uuid4().hex[:10]
    out["render_job_id"] = job_id
    tmp = os.path.join(campaign_root, f".tmp-{did}-{job_id}")
    for sub in ("source", "generated-scenes", "final-composites", "qa"):
        os.makedirs(os.path.join(tmp, sub), exist_ok=False)
    started = now
    cost = {"render_job_id": job_id, "design_id": did, "started_at": started, "completed_at": "", "model": row_base["model"], "size": size, "quality_mix": config.QUALITY_MIX, "images_generated": 0, "generation_calls": 0, "rerolls": 0,
            "source_drive_id": info["drive_file_id"], "source_sha256": info["sha256"], "usage_record": [], "pricing_snapshot": snap, "estimated_api_cost_usd": 0, "campaign_folder": folder, "job_status": "RUNNING", "budget_flag": "OK", "notes": list(retry_notes) + ([f"scene reuse from job {reuse['render_job_id']}: no generation call; no spend"] if reuse_scenes else []), "actual_billed_cost_usd": None}
    images, scene_prompts = [], {}

    def write_cost(status, flag="OK"):
        cost.update(images_generated=len(guard.usage), generation_calls=len(guard.usage), rerolls=guard.rerolls, usage_record=guard.usage, estimated_api_cost_usd=guard.job_cost, job_status=status, budget_flag=flag, completed_at=now_iso() if now is None else now)
        json.dump(cost, open(os.path.join(tmp, "cost-log.json"), "w", encoding="utf-8"), indent=2)
        out["budget"].update(estimated_job_cost_usd=guard.job_cost, projected_monthly_cost_usd=round(monthly + guard.job_cost, 6), budget_flag=flag)
        out["proposed_expense_log_row"] = {**row_base, **{k: cost[k] for k in ("render_job_id", "started_at", "completed_at", "images_generated", "rerolls", "usage_record", "estimated_api_cost_usd", "job_status", "budget_flag", "notes", "actual_billed_cost_usd")}}

    def fail(code, action, flag="OK"):
        write_cost("FAILED:" + code, flag)
        failed_root = os.path.join(campaign_root, "_failed"); os.makedirs(failed_root, exist_ok=True)
        dest = os.path.join(failed_root, f"{did}-{job_id}")
        json.dump({"result": code, "detail": checks[-1]["detail"], "design_id": did, "render_job_id": job_id, "downstream_ready": False}, open(os.path.join(tmp, "FAILED.json"), "w", encoding="utf-8"), indent=2)
        shutil.move(tmp, dest)
        out["campaign"].update(design_folder="", manifest_path="", qa_path="", contact_sheet_path="")
        chk("failed_job", "INFO", f"job artifacts kept for diagnosis at {dest}; no downstream-ready flag; no final campaign folder created")
        return done(code, action)

    try:
        src_bytes = open(info["staged_path"], "rb").read()
        if sha256_bytes(src_bytes) != info["sha256"]: raise ValueError("source bytes changed between verification and copy")
        open(os.path.join(tmp, "source", info["filename"]), "wb").write(src_bytes)
        shutil.copyfile(info["manifest_path"], os.path.join(tmp, "source", "manifest.json"))
        json.dump({"design_id": did, "source_sha256": info["sha256"], "staged_path": info["staged_path"], "staged_manifest": info["manifest_path"], "drive_file_id": info["drive_file_id"], "drive_url": info["drive_url"], "filename": info["filename"], "drive_mime_type": info["drive_mime_type"], "render_source_path": info["render_source_path"], "lineage": "exact byte copy of the 1901-stage-render-source handoff; the Skill #6 handoff was not altered"}, open(os.path.join(tmp, "source", "source-reference.json"), "w", encoding="utf-8"), indent=2)
    except Exception as e:  # noqa: BLE001
        chk("source_copy", "FAIL", f"could not record the source ({e.__class__.__name__}: {e})"); return fail("VERIFICATION_FAILED", f"The source could not be copied into the job for {did}; nothing was generated.")
    chk("source_copy", "PASS", "exact source bytes, the handoff manifest and source-reference.json recorded in the job")
    art_path = os.path.join(tmp, "source", info["filename"])
    atmosphere = evidence.get("atmosphere") or {}

    for p in plan:
        slot, key, role, qlt = p["slot"], p["key"], p["role"], p["quality"]
        prompt = prompts.scene_prompt(role, product, atmosphere); scene_prompts[f"{slot:02d}-{key}"] = prompt
        attempt, reroll_reason = 0, ""
        while True:
            is_reroll = attempt > 0
            b = guard.check(prices[qlt])
            if not b["ok"]:
                flag = "STOPPED"; chk("budget", "FAIL", f"before scene {slot}{' reroll' if is_reroll else ''}: {b['reason']}; call not made")
                return fail("STOPPED_BUDGET", f"Rendering {did} stopped before scene {slot}: {b['reason']}. {len(guard.usage)} image(s) generated so far; no further spend. A new AUTHORIZE LISTING RENDER {did} command is required after Jody decides on the budget.", "STOPPED")
            if reuse_scenes:
                src_name = f"{slot:02d}-{key}-base.png"; src_path = os.path.join(reuse["folder"], "generated-scenes", src_name); old_slot = next((x for x in reuse["manifest"]["scene_slots"] if x["slot"] == slot), {})
                g = {"png": open(src_path, "rb").read(), "usage": {}, "quality": old_slot.get("quality", qlt), "size": size, "model": old_slot.get("model")}
                if sha256_bytes(g["png"]) != reuse["base_scenes"].get(src_name): chk(f"scene_{slot}", "FAIL", "stored base scene changed since verification"); return fail("VERIFICATION_FAILED", f"The stored base scene for slot {slot} changed while the job ran; nothing published.")
                qlt = g["quality"]
            else:
                try:
                    g = provider.generate_scene(prompt, qlt, size, {"design_id": did, "slot": slot, "role": role, "garment_rgb": product["garment_rgb"], "render_job_id": job_id, "reroll": is_reroll})
                except Exception as e:  # noqa: BLE001
                    chk(f"scene_{slot}", "FAIL", f"generation call failed ({e.__class__.__name__}: {e})"); return fail("GENERATION_FAILED", f"The image provider failed on scene {slot} for {did}. Check the provider, then re-run with a fresh AUTHORIZE LISTING RENDER {did}.")
                guard.record(prices[qlt], g["usage"], slot, g["quality"], g["size"], reroll=is_reroll, reason=reroll_reason, model=g.get("model"))
            if not reuse_scenes and (g.get("quality") != qlt or g.get("model") != provider.model or g.get("size") != size):
                chk(f"scene_{slot}", "FAIL", f"provider returned model '{g.get('model')}' quality '{g.get('quality')}' size '{g.get('size')}' instead of '{provider.model}' '{qlt}' '{size}'"); return fail("MODEL_OR_QUALITY_BLOCK", f"The provider substituted a different model, quality tier or size on scene {slot}; a substitute needs explicit human authorization.")
            base_name = f"{slot:02d}-{key}-base.png"; final_name = f"{slot:02d}-{key}.png"
            base_path = os.path.join(tmp, "generated-scenes", base_name); open(base_path, "wb").write(g["png"])
            try:
                final_img, placement = compositor.composite(g["png"], art_path, product["garment_rgb"])
            except compositor.CompositeError as ce:
                if ce.code == "UNUSABLE_SCENE" and reuse_scenes:
                    chk(f"scene_{slot}", "FAIL", f"stored scene unusable under compositor {compositor.COMPOSITOR_VERSION} ({ce.detail}); no reroll is possible without generation"); return fail("SCENE_REUSE_FAILED", f"Scene {slot} of job {reuse['render_job_id']} cannot be composited by the current compositor ({ce.detail}). The existing package is unchanged; a fresh render would need its own authorization and spend.")
                if ce.code == "UNUSABLE_SCENE":
                    if not guard.can_reroll():
                        chk(f"scene_{slot}", "FAIL", f"scene unusable ({ce.detail}) and the reroll cap of {config.MAX_REROLLS} is reached; the art was not distorted to compensate")
                        return fail("QA_FAILED", f"Scene {slot} for {did} is unusable and all {config.MAX_REROLLS} rerolls are spent. Further rerolls need a new human authorization under a future override path.")
                    attempt += 1; reroll_reason = f"scene {slot} unusable: {ce.detail}"
                    chk(f"scene_{slot}", "INFO", f"attempt {attempt} rejected ({ce.detail}); one controlled reroll (reroll {guard.rerolls + 1} of {config.MAX_REROLLS}); the art is never distorted to fit a bad scene")
                    os.replace(base_path, os.path.join(tmp, "generated-scenes", f"{slot:02d}-{key}-rejected-{attempt}.png"))
                    continue
                chk(f"scene_{slot}", "FAIL", ce.detail)
                return fail(ce.code if ce.code == "RESOLUTION_BLOCK" else "COMPOSITING_FAILED", f"Scene {slot} for {did}: {ce.detail}. No automatic upscale or art alteration was performed.")
            except Exception as e:  # noqa: BLE001
                chk(f"scene_{slot}", "FAIL", f"compositing error ({e.__class__.__name__}: {e})"); return fail("COMPOSITING_FAILED", f"Deterministic compositing failed on scene {slot} for {did}.")
            final_path = os.path.join(tmp, "final-composites", final_name); final_img.save(final_path, format="PNG")
            result, qchecks, notes = qa.check_image(slot, role, base_path, final_path, art_path, placement, product, tuple(int(x) for x in size.split("x")))
            img_rec = {"slot": slot, "role": role, "quality": qlt, "model": g["model"], "base_scene": f"generated-scenes/{base_name}", "final_composite": f"final-composites/{final_name}", "final_sha256": sha256_bytes(open(final_path, "rb").read()), "placement": placement, "qa_result": result, "checks": qchecks, "notes": notes, "source_sha256": info["sha256"], "product": {k: product[k] for k in ("blank", "provider", "color")}, "rerolls_used_here": attempt}
            if result != "PASS":
                images.append(img_rec); chk(f"scene_{slot}", "FAIL", "deterministic QA: " + "; ".join(f"{k} {v['detail']}" for k, v in qchecks.items() if v["result"] == "FAIL"))
                return fail("QA_FAILED", f"Scene {slot} for {did} failed deterministic QA; the campaign was not published. Review the failed job artifacts.")
            images.append(img_rec); chk(f"scene_{slot}", "PASS", f"{role} ({qlt}) generated, composited at scale {placement['scale']}, deterministic QA PASS" + (f" after {attempt} reroll(s)" if attempt else ""))
            break

    # 12 QA record, contact sheet, cost log, manifest
    try:
        contact_sheet.build([(os.path.join(tmp, i["final_composite"]), f"{i['slot']:02d} {i['role']} ({i['quality']})") for i in images], os.path.join(tmp, "qa", "contact-sheet.png"))
        cchecks = qa.campaign_checks(images, info["sha256"], {k: product[k] for k in ("blank", "provider", "color")})
        qa_doc = {"design_id": did, "render_job_id": job_id, "campaign_result": "PASS" if all(cchecks.values()) else "FAIL", "images": [{k: i[k] for k in ("slot", "role", "base_scene", "final_composite", "qa_result", "checks", "notes")} for i in images], "campaign_checks": cchecks, "human_review": {"required": True, "items": list(qa.HUMAN_CHECKS)}}
        json.dump(qa_doc, open(os.path.join(tmp, "qa", "qa.json"), "w", encoding="utf-8"), indent=2)
        if qa_doc["campaign_result"] != "PASS":
            chk("campaign_qa", "FAIL", json.dumps(cchecks)); return fail("QA_FAILED", f"Campaign-level QA failed for {did}.")
        write_cost("COMPLETED")
        manifest = {"schema_version": config.SCHEMA_VERSION, "design_id": did, "render_job_id": job_id, "created_at": now, "result": "READY_FOR_HUMAN_RENDER_REVIEW",
                    "source": {"drive_file_id": info["drive_file_id"], "drive_url": info["drive_url"], "filename": info["filename"], "sha256": info["sha256"], "staged_handoff_path": info["folder"], "staged_source_path": info["staged_path"], "campaign_copy": f"source/{info['filename']}", "lineage": "1901-stage-render-source handoff → exact byte copy → deterministic perspective composite"},
                    "product": {**{k: product[k] for k in ("blank", "provider", "color", "spec_source")}, "garment_rgb": list(product["garment_rgb"])},
                    "rendering": {"mode": "composited_fidelity", "provider": out["rendering"]["provider"], "model": out["rendering"]["model"], "size": size, "quality_mix": config.QUALITY_MIX, "pricing_snapshot": snap, "compositor": "marker-geometry + fringe-and-rim-aware removal + converged harmonic reconstruction + ring-texture quilting + seam feather + pillow-perspective + bounded-luminance-multiply", "compositor_version": compositor.COMPOSITOR_VERSION, "compositor_commit": compositor_commit(), "artwork_transformations": "geometric and bounded lighting only"},
                    **({"scene_reuse": {"from_render_job_id": reuse["render_job_id"], "reason": "new governed job on reused base scenes: the approved source and/or the compositor changed; zero generation calls, zero spend", "base_scenes_reused": reuse["base_scenes"], "previous_source_sha256": (reuse["manifest"].get("source") or {}).get("sha256"), "source_sha256": info["sha256"], "previous_compositor_version": (reuse["manifest"].get("rendering") or {}).get("compositor_version"), "compositor_version": compositor.COMPOSITOR_VERSION, "compositor_commit": compositor_commit(), "superseded_package": f"_superseded/{did}-{reuse['render_job_id']}", "superseded_record": f"_superseded/{did}-{reuse['render_job_id']}.SUPERSEDED.json", "superseded_manifest_sha256": reuse["manifest_sha256"], "original_final_sha256": reuse["manifest"].get("final_sha256"), "generation_calls": 0, "estimated_api_cost_usd": 0.0}} if reuse_scenes else {}),
                    "scene_slots": [{"slot": i["slot"], "role": i["role"], "quality": i["quality"], "model": i["model"], "prompt": scene_prompts[f"{i['slot']:02d}-{config.SLOTS[i['slot'] - 1][1]}"], "placement": i["placement"], "rerolls_used_here": i["rerolls_used_here"]} for i in images],
                    "generated_scenes": [i["base_scene"].split("/", 1)[1] for i in images], "final_composites": [i["final_composite"].split("/", 1)[1] for i in images], "final_sha256": {i["final_composite"].split("/", 1)[1]: i["final_sha256"] for i in images},
                    "qa_status": qa_doc["campaign_result"], "qa_path": "qa/qa.json", "contact_sheet": "qa/contact-sheet.png", "estimated_api_cost_usd": guard.job_cost, "reroll_count": guard.rerolls, "cost_log": "cost-log.json",
                    "publication_authorized": False, "human_review_required": True}
        json.dump(manifest, open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8"), indent=2)
    except Exception as e:  # noqa: BLE001
        chk("manifest", "FAIL", f"could not write the campaign records ({e.__class__.__name__}: {e})"); return fail("MANIFEST_FAILED", f"The campaign manifest or QA record for {did} could not be written; the job was not published.")
    chk("manifest", "PASS", "qa.json, contact-sheet.png, cost-log.json and manifest.json written")

    # 13 verify package, then publish atomically
    m2 = json.load(open(os.path.join(tmp, "manifest.json"), encoding="utf-8"))
    expected = [os.path.join("source", info["filename"]), "source/manifest.json", "source/source-reference.json", "qa/qa.json", "qa/contact-sheet.png", "cost-log.json", "manifest.json"] + [f"generated-scenes/{n}" for n in m2["generated_scenes"]] + [f"final-composites/{n}" for n in m2["final_composites"]]
    missing = [f for f in expected if not os.path.isfile(os.path.join(tmp, f))]
    bad_hash = [n for n, h in m2["final_sha256"].items() if not os.path.isfile(os.path.join(tmp, "final-composites", n)) or sha256_bytes(open(os.path.join(tmp, "final-composites", n), "rb").read()) != h]
    if missing or bad_hash or len(m2["final_composites"]) != 6 or m2["publication_authorized"] is not False or sha256_bytes(open(art_path, "rb").read()) != info["sha256"]:
        chk("package_verification", "FAIL", f"missing {missing}, hash mismatches {bad_hash}, finals {len(m2['final_composites'])}"); return fail("VERIFICATION_FAILED", f"The campaign package for {did} did not verify; it was not published.")
    if reuse_scenes:
        ok_, detail_, sup_folder, sup_record = supersede_and_publish(campaign_root, did, folder, tmp, reuse["manifest"], reuse["manifest_sha256"], job_id, now, "superseded by a scene-reuse job: the approved source and/or the compositor changed; the first package reached READY_FOR_HUMAN_RENDER_REVIEW")
        if not ok_:
            chk("supersession", "FAIL", detail_); return done("VERIFICATION_FAILED", f"The scene-reuse package for {did} could not be published ({detail_}); the original package is in place.") if os.path.exists(folder) else fail("CAMPAIGN_CONFLICT", detail_)
        chk("supersession", "PASS", f"job {reuse['render_job_id']} moved whole to {sup_folder} (manifest sha256 unchanged) with {os.path.basename(sup_record)} beside it")
    else:
        if os.path.exists(folder):
            chk("package_verification", "FAIL", "campaign folder appeared during the job; not overwritten"); return fail("CAMPAIGN_CONFLICT", f"A campaign folder for {did} appeared while the job ran; a human must review it.")
        os.rename(tmp, folder)
    ver.update(qa_passed=True, campaign_verified=True); out["render_performed"] = True
    out["campaign"]["images"] = m2["final_composites"]
    chk("package_verification", "PASS", f"{len(expected)} files present, six final composites hash-verified, publication_authorized=false; published atomically to {folder}")
    return done("READY_FOR_HUMAN_RENDER_REVIEW", None)
