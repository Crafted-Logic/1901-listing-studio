"""Pricing snapshot, bound to the exact provider, model and size. Shape:
{"provider": "openai", "model": "<exact configured model id>", "size": "1024x1024", "captured_at": "ISO",
 "basis": "where it came from", "currency": "USD", "per_image_usd": {"high": {"1024x1024": 0.0}, "medium": {"1024x1024": 0.0}}}
A snapshot for a different model or size, or missing any field, is PRICING_UNAVAILABLE. Nothing is guessed."""
import json, os


def load_snapshot(path, provider, model, size):
    if not path or not os.path.isfile(path): return None
    try:
        snap = json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return snap if validate(snap, provider, model, size) else None


def validate(snap, provider, model, size):
    try:
        return (snap["provider"] == provider and snap["model"] == model and snap["size"] == size and bool(snap["captured_at"]) and bool(snap["basis"])
                and snap["currency"] == "USD" and isinstance(snap["per_image_usd"], dict))
    except (KeyError, TypeError):
        return False


def cost_of(snap, quality, size):
    try:
        v = snap["per_image_usd"][quality][size]
        return round(float(v), 6) if v is not None and float(v) >= 0 else None
    except (KeyError, TypeError, ValueError):
        return None
