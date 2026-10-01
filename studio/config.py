"""Constants. Everything governed lives here so the rest of the code reads like the rulebook."""
HANDOFF_ROOT = "/home/claude/agents/1901/shared/render-handoffs/"
CAMPAIGN_ROOT = "/home/claude/agents/1901/shared/render-campaigns/"
PRICING_PATH = "/home/claude/.config/1901-listing-studio/pricing.json"
PROVIDER_CONFIG_PATH = "/home/claude/.config/1901-listing-studio/provider.json"
SCHEMA_VERSION = "1.0"
COMMAND_WORDS = ("AUTHORIZE", "LISTING", "RENDER")

PER_LISTING_LIMIT_USD = 2.00
MONTHLY_LIMIT_USD = 25.00
MAX_REROLLS = 4

IMAGE_SIZE = "1024x1024"
MIN_SOURCE_LONG_SIDE_PX = 1024          # below this, deterministic compositing at listing resolution needs an upscale: RESOLUTION_BLOCK
PLACEHOLDER_RGB = (255, 0, 255)         # chroma marker the scene model is asked for; used for print-area GEOMETRY only
PLACEHOLDER_MIN_AREA = 0.02             # fraction of the image
PLACEHOLDER_MAX_AREA = 0.45

# (slot, key, role, quality)
SLOTS = (
    (1, "hero", "hero_lifestyle", "high"),
    (2, "story", "secondary_lifestyle_story", "high"),
    (3, "travel", "travel_packing", "medium"),
    (4, "flatlay", "editorial_flat_lay", "medium"),
    (5, "folded", "folded_garment_detail", "medium"),
    (6, "detail", "product_construction_detail", "medium"),
)
QUALITY_MIX = {"high": 2, "medium": 4}
