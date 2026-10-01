"""Verification of the Skill #6 handoff. Read-only. Any mismatch blocks rendering."""
import hashlib, json, os


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(handoff_root, design_id):
    """Returns (code, detail, info). code is None when valid, else HANDOFF_NOT_STAGED or HANDOFF_INVALID."""
    folder = os.path.join(handoff_root, design_id)
    manifest_path = os.path.join(folder, "manifest.json")
    if not os.path.isdir(folder):
        return "HANDOFF_NOT_STAGED", f"no staged handoff folder at {folder}", None
    if not os.path.isfile(manifest_path):
        return "HANDOFF_NOT_STAGED", f"handoff folder exists but has no manifest.json ({folder})", None
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            m = json.load(f)
    except Exception as e:  # noqa: BLE001
        return "HANDOFF_INVALID", f"manifest.json is unreadable ({e.__class__.__name__})", None
    src, auth, integ, ho = (m.get(k) or {} for k in ("source", "authority", "integrity", "handoff"))
    problems = []
    if m.get("design_id") != design_id: problems.append(f"manifest design_id is {m.get('design_id')!r}")
    if ho.get("ready_for_listing_studio") is not True: problems.append("handoff.ready_for_listing_studio is not true")
    if auth.get("status") != "Approved": problems.append(f"authority.status is {auth.get('status')!r}")
    if auth.get("human_decision") != "APPROVE": problems.append(f"authority.human_decision is {auth.get('human_decision')!r}")
    if auth.get("source_resolution") != "RESOLVED": problems.append(f"authority.source_resolution is {auth.get('source_resolution')!r}")
    if integ.get("byte_preserved") is not True: problems.append("integrity.byte_preserved is not true")
    if integ.get("hash_verified") is not True: problems.append("integrity.hash_verified is not true")
    if integ.get("artwork_modified") is not False: problems.append("integrity.artwork_modified is not false")
    staged = src.get("local_path") or os.path.join(folder, "source", src.get("filename") or "")
    if not os.path.isfile(staged):
        problems.append(f"staged source file missing at {staged}")
    else:
        actual = sha256_of(staged)
        if actual != src.get("sha256"):
            problems.append(f"staged source SHA-256 {actual[:12]}… does not match manifest {str(src.get('sha256'))[:12]}…")
    if problems:
        return "HANDOFF_INVALID", "; ".join(problems), None
    return None, "handoff valid: manifest, authority, integrity and SHA-256 all verified", {
        "folder": folder, "manifest_path": manifest_path, "staged_path": staged, "sha256": src["sha256"],
        "drive_file_id": src.get("drive_file_id"), "drive_url": src.get("drive_url"), "filename": src.get("filename"),
        "drive_mime_type": src.get("drive_mime_type"), "render_source_path": auth.get("render_source_path"), "manifest": m}
