"""Pricing snapshot. Shape:
{"provider": "openai", "model": "gpt-image-1", "captured_at": "ISO", "basis": "where it came from",
 "currency": "USD", "per_image_usd": {"high": {"1024x1024": 0.167}, "medium": {"1024x1024": 0.042}}}
No snapshot, or no price for the requested quality/size, means PRICING_UNAVAILABLE. Nothing is guessed."""
import json, os


def load_snapshot(path, provider, model):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            snap = json.load(f)
    except Exception:  # noqa: BLE001
        return None
    if snap.get("provider") != provider or snap.get("model") != model:
        return None
    return snap if validate(snap) else None


def validate(snap):
    try:
        return bool(snap["captured_at"]) and bool(snap["basis"]) and snap.get("currency", "USD") == "USD" and isinstance(snap["per_image_usd"], dict)
    except (KeyError, TypeError):
        return False


def cost_of(snap, quality, size):
    try:
        v = snap["per_image_usd"][quality][size]
        return round(float(v), 6) if v is not None and float(v) >= 0 else None
    except (KeyError, TypeError, ValueError):
        return None
