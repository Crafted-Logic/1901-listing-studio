#!/usr/bin/env python3
"""1901-listing-studio CLI. Run with the repo's venv: .venv/bin/python render.py ...

  render.py --design-id 1901-093 --evidence evidence.json --message "<the user's message>" [--provider mock|openai]
            [--handoff-root R] [--campaign-root R] [--pricing PATH] [--mock-pricing PATH]

Prints exactly one JSON object (the skill's output). An ordinary message proposes; only the exact
command AUTHORIZE LISTING RENDER <design_id> in --message renders. No secret is read except the
provider's API key from the environment at call time, and it is never printed."""
import argparse, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from studio import config, job, providers, pricing


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--design-id", required=True); p.add_argument("--evidence", required=True); p.add_argument("--message", default="")
    p.add_argument("--provider", default="mock", choices=("mock", "openai")); p.add_argument("--handoff-root", default=config.HANDOFF_ROOT); p.add_argument("--campaign-root", default=config.CAMPAIGN_ROOT)
    p.add_argument("--pricing", default=config.PRICING_PATH, help="pricing snapshot for the openai provider"); p.add_argument("--mock-pricing", help="pricing snapshot JSON for the mock provider (fixtures only)")
    a = p.parse_args(argv)
    evidence = json.load(open(a.evidence, encoding="utf-8"))
    if a.provider == "openai":
        prov = providers.OpenAIImagesProvider(pricing_path=a.pricing)
        if not prov.configured():
            print(json.dumps({"design_id": a.design_id, "result": "MODEL_OR_QUALITY_BLOCK", "render_performed": False, "human_action_required": "No image provider is configured on this machine (OPENAI_API_KEY absent). Configuring one is a credential decision for Jody."}, indent=1)); return 0
    else:
        snap = pricing.load_snapshot(a.mock_pricing, "mock", "mock-image-1") if a.mock_pricing else None
        prov = providers.MockProvider(pricing_snapshot=snap)
    out = job.run(a.design_id, evidence, a.message, prov, handoff_root=a.handoff_root, campaign_root=a.campaign_root)
    print(json.dumps(out, indent=1, ensure_ascii=False)); return 0


if __name__ == "__main__":
    sys.exit(main())
