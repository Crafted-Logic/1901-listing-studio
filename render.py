#!/usr/bin/env python3
"""1901-listing-studio CLI. Run with the repo's venv: .venv/bin/python render.py <command> ...

  run       --design-id 1901-093 --evidence evidence.json --message "<the user's message, verbatim>"
            [--provider-config PATH] [--handoff-root R] [--campaign-root R]
  preflight [--provider-config PATH]        read-only: provider, model, credentials, tiers, size, pricing; no generation call
  recomposite --design-id 1901-093 --message "<verbatim>" [--handoff-root R] [--campaign-root R]
            local recomposite of the existing reviewed package with the current compositor; no provider, no generation
            call, no spend; only the exact command AUTHORIZE LISTING RECOMPOSITE <design_id> performs it
  Fixtures only: --mock [--mock-pricing PATH] [--mock-model NAME]

Prints exactly one JSON object. An ordinary message proposes; only the exact command
AUTHORIZE LISTING RENDER <design_id> in --message renders. The provider API key is read from the
environment at call time by the adapter and is never printed or logged."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from studio import config, job, providers, pricing


def build_provider(a):
    if a.mock:
        snap = pricing.load_snapshot(a.mock_pricing, "mock", a.mock_model, config.IMAGE_SIZE) if a.mock_pricing else None
        return providers.MockProvider(pricing_snapshot=snap, model=a.mock_model), None
    cfg = providers.load_provider_config(a.provider_config)
    if cfg is None:
        return None, {"provider_configured": False, "provider_config_path": a.provider_config, "detail": "no valid provider configuration (provider + model required); nothing assumed", "generation_call_made": False}
    try:
        return providers.make_provider(cfg), None
    except ValueError as e:
        return None, {"provider_configured": False, "provider_config_path": a.provider_config, "detail": str(e), "generation_call_made": False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("run", "preflight"):
        s = sub.add_parser(name)
        s.add_argument("--provider-config", default=config.PROVIDER_CONFIG_PATH); s.add_argument("--mock", action="store_true"); s.add_argument("--mock-pricing"); s.add_argument("--mock-model", default="mock-image-1")
        if name == "run":
            s.add_argument("--design-id", required=True); s.add_argument("--evidence", required=True); s.add_argument("--message", default="")
            s.add_argument("--handoff-root", default=config.HANDOFF_ROOT); s.add_argument("--campaign-root", default=config.CAMPAIGN_ROOT)
            s.add_argument("--reuse-scenes", action="store_true", help="new governed job reusing the existing package's six base scenes: no provider, no generation call, no spend")
    r = sub.add_parser("recomposite"); r.add_argument("--design-id", required=True); r.add_argument("--message", default=""); r.add_argument("--handoff-root", default=config.HANDOFF_ROOT); r.add_argument("--campaign-root", default=config.CAMPAIGN_ROOT)
    a = p.parse_args(argv)
    if a.cmd == "recomposite":
        print(json.dumps(job.recomposite(a.design_id, a.message, handoff_root=a.handoff_root, campaign_root=a.campaign_root), indent=1, ensure_ascii=False)); return 0
    if a.cmd == "run" and a.reuse_scenes:
        evidence = json.load(open(a.evidence, encoding="utf-8"))
        print(json.dumps(job.run(a.design_id, evidence, a.message, None, handoff_root=a.handoff_root, campaign_root=a.campaign_root, reuse_scenes=True), indent=1, ensure_ascii=False)); return 0
    prov, problem = build_provider(a)
    if a.cmd == "preflight":
        print(json.dumps(problem if problem else prov.preflight(), indent=1, ensure_ascii=False)); return 0
    if problem:
        print(json.dumps({"design_id": a.design_id, "result": "MODEL_OR_QUALITY_BLOCK", "render_performed": False, "checks": [{"check": "model_quality", "status": "FAIL", "detail": problem["detail"]}], "human_action_required": f"Write a provider configuration at {a.provider_config} (provider, model, size, capabilities, pricing_path). No model was assumed."}, indent=1, ensure_ascii=False)); return 0
    evidence = json.load(open(a.evidence, encoding="utf-8"))
    print(json.dumps(job.run(a.design_id, evidence, a.message, prov, handoff_root=a.handoff_root, campaign_root=a.campaign_root), indent=1, ensure_ascii=False)); return 0


if __name__ == "__main__":
    sys.exit(main())
