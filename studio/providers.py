"""Image-generation provider adapter. Business logic never touches a provider directly.

provider.generate_scene(prompt, quality, size, metadata) -> {"png": bytes, "usage": {...}, "model": str, "quality": str, "size": str}
provider.supports_quality(quality) -> bool
provider.pricing_snapshot() -> dict | None   (see pricing.py for the shape)
"""
import base64, io, json, os, urllib.request
from PIL import Image, ImageDraw

from . import config, pricing


class Provider:
    name = "abstract"
    model = ""
    def supports_quality(self, quality): return False
    def pricing_snapshot(self): return None
    def generate_scene(self, prompt, quality, size, metadata): raise NotImplementedError


class MockProvider(Provider):
    """Draws a synthetic garment scene with the magenta print-area placeholder. `script` is a list of
    per-call behaviours: "ok", "no_placeholder" (unusable geometry), "tiny" (placeholder too small),
    "error" (raise). Calls beyond the script are "ok". Nothing leaves the process; cost is fixture."""
    name = "mock"
    model = "mock-image-1"

    def __init__(self, pricing_snapshot=None, qualities=("high", "medium"), script=None):
        self._pricing = pricing_snapshot
        self._qualities = set(qualities)
        self.script = list(script or [])
        self.calls = []

    def supports_quality(self, quality): return quality in self._qualities
    def pricing_snapshot(self): return self._pricing

    def generate_scene(self, prompt, quality, size, metadata):
        behaviour = self.script.pop(0) if self.script else "ok"
        self.calls.append({"prompt": prompt, "quality": quality, "size": size, "metadata": metadata, "behaviour": behaviour})
        if behaviour == "error":
            raise RuntimeError("mock provider: generation error")
        w, h = (int(x) for x in size.split("x"))
        img = Image.new("RGB", (w, h), (214, 206, 194))
        d = ImageDraw.Draw(img)
        color = tuple(metadata.get("garment_rgb", (40, 44, 52)))
        d.polygon([(w * 0.25, h * 0.2), (w * 0.75, h * 0.2), (w * 0.85, h * 0.35), (w * 0.72, h * 0.4), (w * 0.72, h * 0.9), (w * 0.28, h * 0.9), (w * 0.28, h * 0.4), (w * 0.15, h * 0.35)], fill=color)
        slot = metadata.get("slot", 1)
        if behaviour == "ok":
            q = {1: (0.36, 0.38, 0.64, 0.66), 2: (0.34, 0.40, 0.66, 0.70), 3: (0.40, 0.45, 0.60, 0.65), 4: (0.33, 0.36, 0.67, 0.68), 5: (0.38, 0.42, 0.62, 0.66), 6: (0.44, 0.5, 0.64, 0.7)}[slot]
            x0, y0, x1, y1 = (q[0] * w, q[1] * h, q[2] * w, q[3] * h)
            for i in range(int(y0), int(y1)):                       # shaded placeholder: darker toward the bottom (cloth shading)
                t = (i - y0) / max(1, (y1 - y0))
                shade = int(255 - 90 * t)
                d.line([(x0, i), (x1, i)], fill=(shade, 0, shade))
        elif behaviour == "tiny":
            d.rectangle([w * 0.49, h * 0.49, w * 0.52, h * 0.52], fill=config.PLACEHOLDER_RGB)
        # "no_placeholder": garment only, nothing to composite into
        buf = io.BytesIO(); img.save(buf, format="PNG")
        return {"png": buf.getvalue(), "usage": {"images": 1, "quality": quality, "size": size, "mock": True}, "model": self.model, "quality": quality, "size": size}


class OpenAIImagesProvider(Provider):
    """OpenAI Images API (gpt-image-1). The key is read from the environment at call time and never
    stored, printed, or logged. Not exercised by the tests; no live call is made during development."""
    name = "openai"
    model = "gpt-image-1"
    ENDPOINT = "https://api.openai.com/v1/images/generations"

    def __init__(self, pricing_path=None):
        self._pricing_path = pricing_path or config.PRICING_PATH

    def configured(self): return bool(os.environ.get("OPENAI_API_KEY"))
    def supports_quality(self, quality): return quality in ("low", "medium", "high")
    def pricing_snapshot(self): return pricing.load_snapshot(self._pricing_path, self.name, self.model)

    def generate_scene(self, prompt, quality, size, metadata):
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        body = json.dumps({"model": self.model, "prompt": prompt, "n": 1, "size": size, "quality": quality, "output_format": "png"}).encode()
        req = urllib.request.Request(self.ENDPOINT, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.load(resp)
        png = base64.b64decode(data["data"][0]["b64_json"])
        return {"png": png, "usage": data.get("usage", {}), "model": self.model, "quality": quality, "size": size}


def make_provider(name, pricing_snapshot=None, pricing_path=None):
    if name == "mock":
        return MockProvider(pricing_snapshot=pricing_snapshot)
    if name == "openai":
        return OpenAIImagesProvider(pricing_path=pricing_path)
    raise ValueError(f"unknown provider {name}")
