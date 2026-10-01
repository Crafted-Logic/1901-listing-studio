"""Fixture builders: a staged Skill #6 handoff in a temp root, live evidence, pricing, provider."""
import hashlib, json, os, tempfile, shutil
from PIL import Image, ImageDraw
from studio import providers

FID = "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
URL = f"https://drive.google.com/file/d/{FID}/view"
NOW = "2026-10-01T02:00:00Z"
JOB = "fixture001"
ASK = "Render the listing campaign for 1901-093."
AUTH = "AUTHORIZE LISTING RENDER 1901-093"
PRODUCT = {"blank": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt", "provider": "Printify / Monster Digital", "color": "Pepper", "garment_rgb": [72, 70, 68], "spec_source": "Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"}
SNAP = {"provider": "mock", "model": "mock-image-1", "captured_at": "2026-10-01T00:00:00Z", "basis": "fixture pricing for tests", "currency": "USD", "per_image_usd": {"high": {"1024x1024": 0.20}, "medium": {"1024x1024": 0.05}}}


def art_png(path, size=(1400, 1000), alpha=True):
    mode = "RGBA" if alpha else "RGB"
    im = Image.new(mode, size, (0, 0, 0, 0) if alpha else (245, 240, 230)); d = ImageDraw.Draw(im)
    d.ellipse([size[0] * 0.07, size[1] * 0.1, size[0] * 0.93, size[1] * 0.9], fill=(180, 30, 40) + ((255,) if alpha else ()))
    d.rectangle([size[0] * 0.21, size[1] * 0.45, size[0] * 0.79, size[1] * 0.55], fill=(250, 240, 220) + ((255,) if alpha else ()))
    im.save(path, format="PNG")
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


class Env:
    def __init__(self, staged=True, size=(1400, 1000), alpha=True, manifest_patch=None):
        self.root = tempfile.mkdtemp(prefix="ls-")
        self.H = os.path.join(self.root, "handoffs") + "/"; self.C = os.path.join(self.root, "campaigns") + "/"
        os.makedirs(self.H)
        self.sha = None
        if staged:
            os.makedirs(os.path.join(self.H, "1901-093/source"))
            self.staged_path = os.path.join(self.H, "1901-093/source/1901-093-B.png")
            self.sha = art_png(self.staged_path, size, alpha)
            m = {"schema_version": "1.0", "design_id": "1901-093", "created_at": "2026-10-01T01:00:00Z",
                 "source": {"drive_file_id": FID, "drive_url": URL, "filename": "1901-093-B.png", "drive_mime_type": "image/png", "sha256": self.sha, "local_path": self.staged_path},
                 "authority": {"status": "Approved", "human_decision": "APPROVE", "render_source_path": URL, "source_resolution": "RESOLVED"},
                 "integrity": {"byte_preserved": True, "hash_verified": True, "artwork_modified": False}, "handoff": {"ready_for_listing_studio": True}, "warnings": []}
            if manifest_patch: manifest_patch(m)
            json.dump(m, open(os.path.join(self.H, "1901-093/manifest.json"), "w"), indent=2)
    def tree(self): return sorted(os.path.relpath(os.path.join(d, f), self.C) for d, _, fs in os.walk(self.C) for f in fs) if os.path.isdir(self.C) else []
    def dirs(self): return sorted(os.path.relpath(d, self.C) for d, _, _ in os.walk(self.C) if os.path.realpath(d) != os.path.realpath(self.C)) if os.path.isdir(self.C) else []
    def done(self): shutil.rmtree(self.root)


def evidence(status="Approved", hd="APPROVE", rsp=URL, resolver_result="RESOLVED", resolver_fid=FID, blockers=None, handoff_status="READY_FOR_PRODUCTION_HANDOFF", mode="production", product_candidates=None, requires_transparency=True, monthly=3.10, queue_result="FOUND", printify=""):
    rec = {"id": "1901-093", "concept": "Porch cat", "season": "Fall", "style": "Stamp", "vibe": "Nostalgic", "status": status, "idea_notes": "", "image_prompt": "", "art_path": URL, "art_gens": "2", "printify_id": printify, "etsy_url": "", "notes": "", "removed_reason": "",
           "human_decision": hd, "render_status": "", "render_source_path": rsp, "render_output_folder": "", "render_notes": "", "render_updated_at": "", "render_qa": ""}
    return {"queue": {"result": queue_result, "source": {"row_number": 95, "matching_rows": [95] if queue_result == "FOUND" else [95, 141]}, "record": rec if queue_result == "FOUND" else None},
            "resolver": {"result": resolver_result, "resolved_file": {"drive_file_id": resolver_fid, "name": "1901-093-B.png", "url": f"https://drive.google.com/file/d/{resolver_fid}/view", "mime_type": "image/png"} if resolver_result == "RESOLVED" else None, "human_action_required": None if resolver_result == "RESOLVED" else "Jody or Ame: record which of the listed files is the approved artwork for this design, then re-run."},
            "handoff": {"validation_mode": mode, "handoff_status": handoff_status, "blockers": blockers or [], "next_action": None},
            "product": {"candidates": [PRODUCT] if product_candidates is None else product_candidates},
            "requires_transparency": requires_transparency, "monthly_recorded_usd": monthly, "atmosphere": {"concept": "Porch cat", "season": "Fall", "vibe": "Nostalgic"}}


def provider(script=None, snap=SNAP, qualities=("high", "medium")):
    return providers.MockProvider(pricing_snapshot=snap, qualities=qualities, script=script)
