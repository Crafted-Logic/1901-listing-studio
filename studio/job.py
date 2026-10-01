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


def run(design_id, evidence, message, provider, handoff_root=config.HANDOFF_ROOT, campaign_root=config.CAMPAIGN_ROOT, now=None, job_id=None):
    now = now or now_iso()
    out = {"design_id": "", "result": "", "render_performed": False, "render_job_id": "", "timestamp": now,
           "source": {"drive_file_id": "", "filename": "", "sha256": "", "staged_path": ""},
           "product": {"blank": "", "provider": "", "color": "", "spec_source": ""},
           "campaign": {"root": campaign_root, "design_folder": "", "manifest_path": "", "qa_path": "", "contact_sheet_path": "", "images": []},
           "budget": {"per_listing_limit_usd": config.PER_LISTING_LIMIT_USD, "monthly_limit_usd": config.MONTHLY_LIMIT_USD, "estimated_job_cost_usd": 0, "monthly_recorded_cost_usd": 0, "projected_monthly_cost_usd": 0, "budget_flag": ""},
           "verification": {"queue_verified": False, "human_approval_verified": False, "source_verified": False, "handoff_verified": False, "product_spec_verified": False, "pricing_verified": False, "budget_verified": False, "qa_passed": False, "campaign_verified": False},
           "authorization": {"received": False, "evidence": ""}, "proposed_expense_log_row": {}, "warnings": [], "checks": [], "human_action_required": None}
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

    # 7 model / quality / pricing
    for qlt in config.QUALITY_MIX:
        if not provider.supports_quality(qlt):
            chk("model_quality", "FAIL", f"provider {provider.name} ({provider.model}) does not offer quality tier '{qlt}'"); return done("MODEL_OR_QUALITY_BLOCK", f"The configured image provider cannot produce the governed quality mix (2 high, 4 medium). A substitute needs explicit human authorization; none was assumed.")
    chk("model_quality", "PASS", f"{provider.name} / {provider.model} offers high and medium")
    snap = provider.pricing_snapshot()
    prices = {qlt: (pricing.cost_of(snap, qlt, config.IMAGE_SIZE) if snap else None) for qlt in config.QUALITY_MIX}
    if snap is None or any(v is None for v in prices.values()):
        chk("pricing", "FAIL", "no usable pricing snapshot for the configured provider/model/quality/size before spend"); return done("PRICING_UNAVAILABLE", f"Record a current pricing snapshot for {provider.name} / {provider.model} at {config.PRICING_PATH} (captured_at, basis, per_image_usd by quality and size). No per-image cost was guessed.")
    ver["pricing_verified"] = True; chk("pricing", "PASS", f"{snap['provider']} / {snap['model']} captured {snap['captured_at']}: high ${prices['high']:.4f}, medium ${prices['medium']:.4f} per {config.IMAGE_SIZE} image ({snap['basis']})")
    plan = [{"slot": s, "key": k, "role": role, "quality": qlt, "size": config.IMAGE_SIZE, "estimated_cost_usd": prices[qlt]} for s, k, role, qlt in config.SLOTS]
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
    ex, exdetail, exm = inspect_existing(campaign_root, did, info["sha256"], product)
    if ex == "CAMPAIGN_CONFLICT":
        chk("existing_campaign", "FAIL", exdetail); return done("CAMPAIGN_CONFLICT", f"A campaign folder for {did} already exists and does not match ({exdetail}); a human must review {folder}. Nothing was overwritten or regenerated.")
    if ex == "ALREADY_RENDERED":
        out["render_job_id"] = exm.get("render_job_id", ""); out["campaign"]["images"] = exm.get("final_composites", []); ver.update(qa_passed=True, campaign_verified=True)
        chk("existing_campaign", "PASS", exdetail); return done("ALREADY_RENDERED", None)
    chk("existing_campaign", "PASS", "no campaign folder exists for this design")

    row_base = {"design_id": did, "model": f"{provider.name}/{provider.model}", "quality_mix": config.QUALITY_MIX, "source_drive_id": info["drive_file_id"], "source_sha256": info["sha256"], "pricing_snapshot": snap, "campaign_folder": folder}

    # 10 authorization
    if not (auth and auth[0] == "OK"):
        if auth: chk("authorization", "FAIL", f"the command names {auth[1]}, not the target {did}; it authorizes nothing in this run")
        else: chk("authorization", "FAIL", f"the current run does not contain the exact command AUTHORIZE LISTING RENDER {did}; ordinary requests and vague confirmations never authorize rendering")
        out["proposed_expense_log_row"] = {**row_base, "render_job_id": "", "started_at": "", "completed_at": "", "images_generated": 0, "rerolls": 0, "usage_record": [], "estimated_api_cost_usd": estimate, "job_status": "PROPOSED", "budget_flag": "OK", "notes": ["proposal only; no generation call made"], "actual_billed_cost_usd": None}
        out["campaign"]["images"] = [f"{p['slot']:02d}-{p['key']}.png" for p in plan]
        return done("AWAITING_RENDER_AUTHORIZATION", f"No generation call made and no campaign files created. {did} is eligible: source {info['filename']} (Drive id {info['drive_file_id']}, sha256 {info['sha256'][:12]}…) staged at {info['staged_path']}; product {product['blank']} / {product['provider']} / {product['color']}; six scenes (2 high, 4 medium) on {provider.name}/{provider.model} at an estimated ${estimate:.4f}, month ${monthly:.4f} → ${whole['projected_monthly']:.4f}; output {folder}. To authorize exactly this render job, send exactly: AUTHORIZE LISTING RENDER {did}")
    out["authorization"].update(received=True, evidence=auth[1]); chk("authorization", "PASS", f"current run contains the exact command: {auth[1]}")

    # 11 the job
    job_id = job_id or uuid.uuid4().hex[:10]
    out["render_job_id"] = job_id
    tmp = os.path.join(campaign_root, f".tmp-{did}-{job_id}")
    for sub in ("source", "generated-scenes", "final-composites", "qa"):
        os.makedirs(os.path.join(tmp, sub), exist_ok=False)
    started = now
    cost = {"render_job_id": job_id, "design_id": did, "started_at": started, "completed_at": "", "model": row_base["model"], "quality_mix": config.QUALITY_MIX, "images_generated": 0, "rerolls": 0,
            "source_drive_id": info["drive_file_id"], "source_sha256": info["sha256"], "usage_record": [], "pricing_snapshot": snap, "estimated_api_cost_usd": 0, "campaign_folder": folder, "job_status": "RUNNING", "budget_flag": "OK", "notes": [], "actual_billed_cost_usd": None}
    images, scene_prompts = [], {}

    def write_cost(status, flag="OK"):
        cost.update(images_generated=len(guard.usage), rerolls=guard.rerolls, usage_record=guard.usage, estimated_api_cost_usd=guard.job_cost, job_status=status, budget_flag=flag, completed_at=now_iso() if now is None else now)
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
            try:
                g = provider.generate_scene(prompt, qlt, config.IMAGE_SIZE, {"design_id": did, "slot": slot, "role": role, "garment_rgb": product["garment_rgb"], "render_job_id": job_id, "reroll": is_reroll})
            except Exception as e:  # noqa: BLE001
                chk(f"scene_{slot}", "FAIL", f"generation call failed ({e.__class__.__name__}: {e})"); return fail("GENERATION_FAILED", f"The image provider failed on scene {slot} for {did}. Check the provider, then re-run with a fresh AUTHORIZE LISTING RENDER {did}.")
            guard.record(prices[qlt], g["usage"], slot, g["quality"], g["size"], reroll=is_reroll, reason=reroll_reason)
            if g.get("quality") != qlt:
                chk(f"scene_{slot}", "FAIL", f"provider returned quality '{g.get('quality')}' instead of '{qlt}'"); return fail("MODEL_OR_QUALITY_BLOCK", f"The provider substituted a different quality tier on scene {slot}; a substitute needs explicit human authorization.")
            base_name = f"{slot:02d}-{key}-base.png"; final_name = f"{slot:02d}-{key}.png"
            base_path = os.path.join(tmp, "generated-scenes", base_name); open(base_path, "wb").write(g["png"])
            try:
                final_img, placement = compositor.composite(g["png"], art_path, product["garment_rgb"])
            except compositor.CompositeError as ce:
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
            result, qchecks, notes = qa.check_image(slot, role, base_path, final_path, art_path, placement, product, tuple(int(x) for x in config.IMAGE_SIZE.split("x")))
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
                    "rendering": {"mode": "composited_fidelity", "provider": provider.name, "model": provider.model, "size": config.IMAGE_SIZE, "quality_mix": config.QUALITY_MIX, "compositor": "pillow-perspective+shading-multiply", "artwork_transformations": "geometric and lighting only"},
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
    if os.path.exists(folder):
        chk("package_verification", "FAIL", "campaign folder appeared during the job; not overwritten"); return fail("CAMPAIGN_CONFLICT", f"A campaign folder for {did} appeared while the job ran; a human must review it.")
    os.rename(tmp, folder)
    ver.update(qa_passed=True, campaign_verified=True); out["render_performed"] = True
    out["campaign"]["images"] = m2["final_composites"]
    chk("package_verification", "PASS", f"{len(expected)} files present, six final composites hash-verified, publication_authorized=false; published atomically to {folder}")
    return done("READY_FOR_HUMAN_RENDER_REVIEW", None)
