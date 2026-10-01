"""Scene prompts: garment and environment only. The approved artwork is never described for
recreation; the model is asked for a flat magenta placeholder where the print will be composited."""
from . import config

ROLE_TEXT = {
    "hero_lifestyle": "Premium realistic lifestyle photograph, primary listing hero image: a person wearing the shirt in a warm, anticipatory travel-memory moment; strong composition; chest print area fully visible and facing the camera.",
    "secondary_lifestyle_story": "Realistic story-driven lifestyle photograph, a different setting from the hero image: a quiet moment that suggests a trip being remembered or planned; the shirt's chest area visible and unobstructed.",
    "travel_packing": "Realistic travel or packing scene: the shirt on a bed or in an open suitcase among travel items; the chest print area fully visible, flat enough to read.",
    "editorial_flat_lay": "Clean editorial flat-lay product photograph from directly above: the shirt laid flat on a neutral surface with natural folds; chest print area completely visible.",
    "folded_garment_detail": "Close product photograph of the shirt partly folded, showing fabric texture and how a chest print sits on the cloth; the print area visible and in focus.",
    "product_construction_detail": "Close product photograph showing garment construction: collar, stitching, hem or sleeve cuff, fabric weave; part of the chest print area visible at the edge of frame.",
}

PLACEHOLDER = ("On the chest print area of the shirt there is one perfectly flat, uniform, solid magenta rectangle "
               "(pure #FF00FF), sharp-edged, following the fabric's shading, drape and perspective exactly as a printed panel would. "
               "The rectangle is completely blank: no text, no letters, no logo, no graphic, no pattern inside it.")

GUARDS = ("No text anywhere in the image. No logos, brand marks, labels, tags, watermarks or signage. No other graphics on the garment. "
          "No people's faces in close-up. Photorealistic, natural light, no illustration style.")


def scene_prompt(role, product, atmosphere):
    garment = f"The garment is a {product['blank']} by {product['provider']} in the color {product['color']}, with accurate construction for that blank."
    mood = ""
    if atmosphere:
        bits = [f"{k}: {v}" for k, v in atmosphere.items() if v]
        if bits:
            mood = "Atmosphere only (do not render any of this as text or graphics): " + "; ".join(bits) + "."
    return " ".join(x for x in (ROLE_TEXT[role], garment, PLACEHOLDER, mood, GUARDS) if x)
