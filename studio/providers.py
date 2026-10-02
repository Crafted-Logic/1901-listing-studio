"""Image-generation provider adapter. Business logic never touches a provider directly.

Production configuration (no secrets) lives at config.PROVIDER_CONFIG_PATH:
{
  "provider": "openai",
  "model": "<the configured image model id>",
  "size": "1024x1024",
  "capabilities": {"qualities": ["low", "medium", "high"], "sizes": ["1024x1024", "1536x1024", "1024x1536"],
                   "basis": "where these capabilities were verified (docs URL + date)"},
  "pricing_path": "/home/claude/.config/1901-listing-studio/pricing.json"
}
The model is never hard-coded. Credentials come only from the runtime environment and are never
stored, printed or logged. The adapter reads OPENAI_API_KEY first, then LISTING_STUDIO_OPENAI_API_KEY:
OpenMausBot's Claude launcher deliberately deletes OPENAI_API_KEY (and every other provider-credential
name) from a bot's environment so a foreign key cannot change a CLI's billing identity, so the
harness-safe name is the one that actually reaches Walter.

provider.generate_scene(prompt, quality, size, metadata) -> {"png", "usage", "model", "quality", "size"}
provider.supports_quality(q) / supports_size(s) -> bool      (from the configured capability record)
provider.credentials_available() -> bool
provider.model_available() -> True | False | None            (None = could not be checked; no paid call)
provider.pricing_snapshot() -> dict | None
provider.preflight() -> dict                                  (read-only, no generation call)
"""
import base64, io, json, os, urllib.error, urllib.request
from PIL import Image, ImageDraw

from . import config, pricing


def load_provider_config(path=None):
    path = path or config.PROVIDER_CONFIG_PATH
    if not os.path.isfile(path):
        return None
    try:
        cfg = json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(cfg, dict) or not cfg.get("provider") or not cfg.get("model"):
        return None
    cfg.setdefault("size", config.IMAGE_SIZE); cfg.setdefault("capabilities", {}); cfg.setdefault("pricing_path", config.PRICING_PATH)
    return cfg


class Provider:
    name = "abstract"; model = ""; size = config.IMAGE_SIZE
    def supports_quality(self, quality): return False
    def supports_size(self, size): return False
    def credentials_available(self): return False
    def model_available(self): return None
    def pricing_snapshot(self): return None
    def generate_scene(self, prompt, quality, size, metadata): raise NotImplementedError
    def credential_env_name(self): return None
    def preflight(self):
        snap = self.pricing_snapshot()
        return {"provider_configured": True, "provider": self.name, "model_configured": self.model, "size": self.size,
                "credentials_available": self.credentials_available(), "credential_env_name": self.credential_env_name(), "model_available": self.model_available(),
                "quality_tiers_available": {q: self.supports_quality(q) for q in config.QUALITY_MIX}, "size_supported": self.supports_size(self.size),
                "pricing_snapshot_available": snap is not None, "pricing_snapshot": {k: snap.get(k) for k in ("provider", "model", "size", "captured_at", "basis", "currency")} if snap else None,
                "generation_call_made": False}


class MockProvider(Provider):
    """Draws a synthetic garment scene with real shading and a UNIFORM chroma marker (the marker carries
    no shading information). `script` lists per-call behaviours: "ok", "no_marker", "tiny", "edge", "purple_bg", "hollow", "fragmented"
    (marker straddling the shirt edge: ring inconsistent), "error". Beyond the script: "ok".
    marker_pattern "uniform" | "noisy" controls the marker's own pixel values (for the test proving
    shading does not depend on them)."""
    name = "mock"

    def __init__(self, pricing_snapshot=None, qualities=("high", "medium"), script=None, model="mock-image-1", size=config.IMAGE_SIZE, sizes=None, credentials=True, available=True, marker_pattern="uniform"):
        self._pricing = pricing_snapshot; self._qualities = set(qualities); self.script = list(script or []); self.model = model; self.size = size
        self._sizes = set(sizes or [size]); self._credentials = credentials; self._available = available; self.marker_pattern = marker_pattern; self.calls = []

    def supports_quality(self, quality): return quality in self._qualities
    def supports_size(self, size): return size in self._sizes
    def credentials_available(self): return self._credentials
    def model_available(self): return self._available
    def pricing_snapshot(self): return self._pricing if self._pricing and pricing.validate(self._pricing, self.name, self.model, self.size) else None

    def generate_scene(self, prompt, quality, size, metadata):
        behaviour = self.script.pop(0) if self.script else "ok"
        self.calls.append({"prompt": prompt, "quality": quality, "size": size, "metadata": metadata, "behaviour": behaviour, "model": self.model})
        if behaviour == "error": raise RuntimeError("mock provider: generation error")
        buf = io.BytesIO(); draw_scene(size, metadata.get("garment_rgb", (40, 44, 52)), metadata.get("slot", 1), behaviour, self.marker_pattern).save(buf, format="PNG")
        return {"png": buf.getvalue(), "usage": {"images": 1, "quality": quality, "size": size, "mock": True}, "model": self.model, "quality": quality, "size": size}


def draw_scene(size, color, slot, behaviour="ok", marker_pattern="uniform"):
    w, h = (int(x) for x in size.split("x"))
    img = Image.new("RGB", (w, h), (214, 206, 194)); d = ImageDraw.Draw(img)
    shirt = [(w * 0.25, h * 0.2), (w * 0.75, h * 0.2), (w * 0.85, h * 0.35), (w * 0.72, h * 0.4), (w * 0.72, h * 0.9), (w * 0.28, h * 0.9), (w * 0.28, h * 0.4), (w * 0.15, h * 0.35)]
    # garment with real shading: vertical falloff plus a diagonal fold highlight
    for y in range(int(h * 0.2), int(h * 0.9)):
        t = (y - h * 0.2) / (h * 0.7); k = 1.15 - 0.45 * t
        d.line([(0, y), (w, y)], fill=tuple(max(0, min(255, int(c * k))) for c in color))
    shirt_mask = Image.new("L", (w, h), 0); ImageDraw.Draw(shirt_mask).polygon(shirt, fill=255)
    bg = Image.new("RGB", (w, h), (214, 206, 194)); img = Image.composite(img, bg, shirt_mask); d = ImageDraw.Draw(img)
    for i in range(-40, 40):
        k = 1.0 + 0.18 * (1 - abs(i) / 40.0)
        for y in range(int(h * 0.2), int(h * 0.9), 1):
            x = int(w * 0.3 + (y - h * 0.2) * 0.35) + i
            if 0 <= x < w and shirt_mask.getpixel((x, y)):
                px = img.getpixel((x, y)); img.putpixel((x, y), tuple(min(255, int(c * k)) for c in px))
    q = {1: (0.36, 0.38, 0.64, 0.66), 2: (0.34, 0.40, 0.66, 0.70), 3: (0.40, 0.45, 0.60, 0.65), 4: (0.33, 0.36, 0.67, 0.68), 5: (0.38, 0.42, 0.62, 0.66), 6: (0.44, 0.5, 0.64, 0.7)}[slot]
    if behaviour == "edge": q = (0.55, 0.38, 0.95, 0.66)                 # straddles the sleeve edge and the background
    if behaviour in ("ok", "edge"):
        x0, y0, x1, y1 = int(q[0] * w), int(q[1] * h), int(q[2] * w), int(q[3] * h)
        d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=config.PLACEHOLDER_RGB)
        if marker_pattern == "noisy":                                      # arbitrary magenta variants: must not influence the composite
            for y in range(y0, y1):
                v = 150 + ((y * 7) % 100)
                d.line([(x0, y), (x1 - 1, y)], fill=(v, (y * 3) % 60, 255 - (y % 80)))
    elif behaviour == "tiny":
        d.rectangle([w * 0.49, h * 0.49, w * 0.52, h * 0.52], fill=config.PLACEHOLDER_RGB)
    elif behaviour == "purple_bg":                                         # good marker + unrelated magenta/purple scenery outside the shirt
        x0, y0, x1, y1 = int(q[0] * w), int(q[1] * h), int(q[2] * w), int(q[3] * h)
        d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=config.PLACEHOLDER_RGB)
        for i, (bx, by, bw, bh) in enumerate(((0.02, 0.03, 0.08, 0.10), (0.88, 0.05, 0.10, 0.08), (0.90, 0.80, 0.07, 0.15), (0.03, 0.70, 0.10, 0.06), (0.80, 0.02, 0.05, 0.05))):
            d.rectangle([bx * w, by * h, (bx + bw) * w - 1, (by + bh) * h - 1], fill=(180 + 10 * i, 60 - 5 * i, 200 + 8 * i))   # passes the marker-colour mask
        for i in range(60):                                                 # scattered single purple pixels in the sky
            img.putpixel((int(w * 0.05 + (i * 37) % int(w * 0.9)), int(h * 0.02 + (i * 13) % int(h * 0.15))), (170, 40, 230))
    elif behaviour == "hollow":                                            # a magenta frame: not a solid panel
        x0, y0, x1, y1 = int(q[0] * w), int(q[1] * h), int(q[2] * w), int(q[3] * h)
        d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=config.PLACEHOLDER_RGB); d.rectangle([x0 + 40, y0 + 40, x1 - 41, y1 - 41], fill=tuple(color))
    elif behaviour == "fragmented":                                        # two comparable magenta blocks with a gap: no single dominant marker
        x0, y0, x1, y1 = int(q[0] * w), int(q[1] * h), int(q[2] * w), int(q[3] * h); xm = (x0 + x1) // 2
        d.rectangle([x0, y0, xm - 12, y1 - 1], fill=config.PLACEHOLDER_RGB); d.rectangle([xm + 12, y0, x1 - 1, y1 - 1], fill=config.PLACEHOLDER_RGB)
    return img


CREDENTIAL_ENV_NAMES = ("OPENAI_API_KEY", "LISTING_STUDIO_OPENAI_API_KEY")


def _api_key_env_name():
    """Name of the first non-empty credential variable, or None. The value is never returned here."""
    for name in CREDENTIAL_ENV_NAMES:
        if os.environ.get(name):
            return name
    return None


def _api_key():
    name = _api_key_env_name()
    return os.environ.get(name) if name else None


class OpenAIImagesProvider(Provider):
    """OpenAI Images API with the model taken from the provider configuration. The key is read from
    the environment at call time (see CREDENTIAL_ENV_NAMES) and never stored, printed, or logged.
    Not exercised live by tests."""
    name = "openai"
    ENDPOINT = "https://api.openai.com/v1/images/generations"
    MODELS = "https://api.openai.com/v1/models/"

    def __init__(self, cfg):
        self.cfg = cfg; self.model = cfg["model"]; self.size = cfg.get("size", config.IMAGE_SIZE)
        caps = cfg.get("capabilities") or {}; self._qualities = set(caps.get("qualities") or []); self._sizes = set(caps.get("sizes") or []); self._pricing_path = cfg.get("pricing_path")

    def supports_quality(self, quality): return quality in self._qualities
    def supports_size(self, size): return size in self._sizes
    def credentials_available(self): return _api_key() is not None
    def credential_env_name(self): return _api_key_env_name()
    def pricing_snapshot(self): return pricing.load_snapshot(self._pricing_path, self.name, self.model, self.size)

    def model_available(self):
        """GET /v1/models/<model>: free metadata call; True/False, or None if it could not be checked."""
        key = _api_key()
        if not key: return None
        try:
            req = urllib.request.Request(self.MODELS + self.model, headers={"Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp).get("id") == self.model
        except urllib.error.HTTPError as e:
            return False if e.code == 404 else None
        except Exception:  # noqa: BLE001
            return None

    def generate_scene(self, prompt, quality, size, metadata):
        key = _api_key()
        if not key: raise RuntimeError("no image-provider credential in the environment (OPENAI_API_KEY or LISTING_STUDIO_OPENAI_API_KEY)")
        if not self.supports_quality(quality) or not self.supports_size(size): raise RuntimeError("requested quality or size is not in the configured capability record")
        body = json.dumps({"model": self.model, "prompt": prompt, "n": 1, "size": size, "quality": quality, "output_format": "png"}).encode()
        req = urllib.request.Request(self.ENDPOINT, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.load(resp)
        return {"png": base64.b64decode(data["data"][0]["b64_json"]), "usage": data.get("usage", {}), "model": self.model, "quality": quality, "size": size}


def make_provider(cfg):
    if cfg["provider"] == "openai": return OpenAIImagesProvider(cfg)
    raise ValueError(f"unknown provider {cfg['provider']!r}")
