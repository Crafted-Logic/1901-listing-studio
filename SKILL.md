---
name: 1901-listing-studio
description: Governed Listing Studio render executor for one approved 1901 design; composites the exact staged artwork into generated garment scenes, QA, local campaign package, stops for human review.
---

# 1901 Listing Studio

Skill #7 in the 1901 Main Street production workflow: the governed render
executor. For exactly one approved design it consumes the verified local
handoff created by `1901-stage-render-source`, generates blank garment and
environment scenes, composites the exact approved artwork deterministically,
runs QA, writes the six-image campaign with a manifest, QA record and cost
log, and stops for human review.

It never chooses artwork, never alters the approved artwork's content, never
publishes to Etsy or Printify, never modifies a Printify product, never
authorises downstream release, never infers product specifications, never
bypasses a governance or budget guardrail, and never marks anything
publish-approved.

verified staged master → generated garment scenes → deterministic composite
of the exact artwork → QA → campaign outputs + manifest + cost record → human
review.

Core rule: **VERIFY, DON'T ASSUME.** The Skill #6 staged source is the only
artwork input. The Studio may move and light the artwork geometrically for
realistic compositing (scale, rotation, perspective, warp, masking,
displacement, occlusion, light and shadow) but may never redraw, regenerate,
re-letter, recolor, reinterpret, substitute, respell, "improve", clean up,
simplify, or recreate it with AI. A scene that cannot accept the exact art
believably is rejected and rerolled; the art is never distorted to fit it.

## When to Use

Trigger on requests such as:

- "Render the listing campaign for 1901-093."
- "Make the six listing images for 1901-093."
- "Is 1901-093 rendered?"
- `AUTHORIZE LISTING RENDER 1901-093`

Two steps; every ordinary request is step 1 only.

- **Step 1, proposal.** Runs every live check (queue, approval, source,
  governance, staged handoff, source image, product specification, model and
  quality, pricing, budget, existing campaign) and, when eligible, returns
  `AWAITING_RENDER_AUTHORIZATION` with `render_performed = false`: the
  verified source and staged path, product specification, the planned six
  scenes, model and quality mix, pricing snapshot, estimated cost, current
  and projected monthly spend, and the exact command. No generation call,
  no campaign directory, no spend.
- **Step 2, authorised render.** Only a run whose user message is exactly
  `AUTHORIZE LISTING RENDER <design_id>` renders, after every live check is
  re-run from scratch in that run.

Expected production flow: human approval → source resolution →
`render_source_path` written → production handoff validated → source staged →
**Listing Studio render** → QA → human review → downstream merchandising
later. Use the existing skills for their parts: `1901-read-idea-queue`,
`1901-resolve-production-source`, `1901-prepare-production-handoff`,
`1901-stage-render-source`.

## Authoritative Sources

| Source | Identifier |
|---|---|
| Idea Queue spreadsheet | `1UxnZsA9aWlxZHqMAt17_7HAe86w_cHcMik3xpXQrfq0`, worksheet `Idea Queue`, gid `1283408381` |
| Render Expense Log | same spreadsheet, tab `Render Expense Log` (read for monthly spend; never written by this skill) |
| Governing render standard | `01 — 1901 Listing Render System (CURRENT)` |
| Staged handoff root | `/home/claude/agents/1901/shared/render-handoffs/` |
| Campaign root | `/home/claude/agents/1901/shared/render-campaigns/` |
| Pricing snapshot | `/home/claude/.config/1901-listing-studio/pricing.json` |
| Renderer | `/home/claude/agents/1901/1901-listing-studio/render.py`, run with that folder's `.venv/bin/python` |

## Governing Render Standard

**Standard campaign pack**, exactly six finished images unless the user
explicitly authorises a different count:

| slot | file | role | quality |
|---|---|---|---|
| 1 | `01-hero.png` | Hero lifestyle | high |
| 2 | `02-story.png` | Secondary lifestyle / story scene | high |
| 3 | `03-travel.png` | Travel / packing scene | medium |
| 4 | `04-flatlay.png` | Editorial flat lay | medium |
| 5 | `05-folded.png` | Folded / garment-detail scene | medium |
| 6 | `06-detail.png` | Product / construction detail scene | medium |

Quality mix 2 high, 4 medium. The model and quality used for every scene
are recorded. A quality tier the provider cannot supply is
`MODEL_OR_QUALITY_BLOCK`; nothing is substituted silently.

**Composited Fidelity Mode** (default and only mode here): the image model
generates the scene and garment only, using the governed product
specification, and is never asked to draw the approved artwork. The
artwork is composited afterwards by a deterministic local process that
preserves its identity exactly.

**Production rule in force:** the human-approved artwork master is the
canonical render source. Pre-existing Printify drafts are parked production
artifacts that neither bypass nor block rendering and are never touched.

## Input

Exactly one `design_id`, trimmed, matched exactly. Everything else is read
live in the run and passed to the renderer as evidence (Running the
Renderer). In a step 2 run the id in the command is the target, unless the
run was invoked for a specific design, in which case the command's id must
match it.

## Procedure

Checks run in this order; the first failing check ends the run with its
result, no generation call and no campaign change. Every check is recorded
in `checks` as `{check, status, detail}`.

1. **Queue.** `1901-read-idea-queue` live: `SOURCE_UNAVAILABLE` /
   `SCHEMA_WARNING` → `SOURCE_UNAVAILABLE`; `NOT_FOUND`; `DUPLICATE_ID`.
2. **Approval.** `human_decision` exactly `APPROVE` and `status` exactly
   `Approved`, else `HUMAN_APPROVAL_REQUIRED`.
3. **Source.** `render_source_path` blank → `SOURCE_MISSING`; not a Drive
   file reference → `SOURCE_MISMATCH`. `1901-resolve-production-source` must
   return `RESOLVED` (else `SOURCE_NOT_RESOLVED`) naming the same Drive file
   id (else `SOURCE_MISMATCH`). A non-blank `printify_id` is noted as an
   `INFO` check and changes nothing.
4. **Governance.** `1901-prepare-production-handoff` in production mode.
   Blockers map as in Governance below.
5. **Staged handoff.** The folder `<handoff root>/<design_id>/` must exist
   with `manifest.json` (`HANDOFF_NOT_STAGED` otherwise) and verify in full:
   manifest `design_id` matches, `handoff.ready_for_listing_studio` is true,
   the source file exists and its SHA-256 equals the manifest's,
   `authority.status` is `Approved`, `authority.human_decision` is
   `APPROVE`, `authority.source_resolution` is `RESOLVED`,
   `integrity.byte_preserved` true, `integrity.hash_verified` true,
   `integrity.artwork_modified` false. Any mismatch → `HANDOFF_INVALID`. The
   manifest's Drive file id must equal the id in `render_source_path`, else
   `SOURCE_MISMATCH`. The source must open as an image (else
   `HANDOFF_INVALID`).
6. **Source image.** Long side below 1024 px → `RESOLUTION_BLOCK`. If the
   governing production record requires a transparent background and the
   source has no alpha channel → `ART_PREP_BLOCK`. If the record states no
   requirement and the source is opaque, it is composited as an opaque
   panel with a warning; transparency is never invented and the source is
   never altered.
7. **Product specification.** From the authoritative production record
   only (Product Specification below): none → `PRODUCT_SPEC_BLOCK`;
   conflicting → `PRODUCT_SPEC_BLOCK` naming the conflict.
8. **Model, quality, pricing.** Provider must offer high and medium
   (`MODEL_OR_QUALITY_BLOCK`). A pricing snapshot for the provider, model,
   both quality tiers and the image size must exist before any spend
   (`PRICING_UNAVAILABLE`). The planned cost of the six images is computed
   from it.
9. **Budget.** Monthly recorded spend is read from the Render Expense Log
   (unreadable → `SOURCE_UNAVAILABLE`) and cross-checked against local cost
   logs for the month (the larger figure is used, with a warning). If the
   first call, or the planned six-image campaign, would exceed the $2.00
   per-listing cap or the $25.00 monthly cap → `BUDGET_BLOCK`, no call.
10. **Existing campaign.** Existing Campaign Behaviour below:
    `ALREADY_RENDERED` or `CAMPAIGN_CONFLICT`.
11. **Authorization.** Only now. Exact command or
    `AWAITING_RENDER_AUTHORIZATION` with the full proposal.
12. **Job.** A `render_job_id` and the temporary job directory
    `<campaign root>/.tmp-<design_id>-<render_job_id>/`; the exact source
    bytes, the handoff manifest and `source-reference.json` are recorded;
    then for each of the six slots: budget pre-check for this exact call
    (`STOPPED_BUDGET` before the call if it would exceed a cap) → generate
    (`GENERATION_FAILED`) → find the print area and composite the exact art
    (unusable scene → one controlled reroll while under the cap of 4, else
    `QA_FAILED`; print area wider than the art → `RESOLUTION_BLOCK`; other
    failure → `COMPOSITING_FAILED`) → deterministic QA (`QA_FAILED`). Then
    the contact sheet, `qa/qa.json`, `cost-log.json`, `manifest.json`; the
    package is verified (every expected file present, all six finals
    hash-matched, `publication_authorized` false, source bytes unchanged) or
    `VERIFICATION_FAILED`; then one atomic rename to
    `<campaign root>/<design_id>/` → `READY_FOR_HUMAN_RENDER_REVIEW`.

A failed job keeps its artifacts for diagnosis under
`<campaign root>/_failed/<design_id>-<render_job_id>/` with a `FAILED.json`
and no downstream-ready flag. A previously valid campaign is never deleted
or replaced. The skill never retries on its own; a later attempt needs a new
`AUTHORIZE LISTING RENDER` command in a new run.

## Governance

`1901-prepare-production-handoff` returns one blocker per code:

- `OPEN_ITEM_BLOCK` whose open items are **all** the item that the
  render-stage image-handoff bridge is not built: not a blocker (that bridge
  is `1901-stage-render-source`); recorded as a warning. Any other item in
  that blocker, nothing is waived.
- `STATUS_NOT_APPROVED`, `MISSING_HUMAN_APPROVAL`, `HUMAN_REVISE`,
  `HUMAN_REJECT` → `HUMAN_APPROVAL_REQUIRED`; `MISSING_SOURCE` →
  `SOURCE_MISSING`; `AMBIGUOUS_SOURCE`, `SOURCE_NOT_MASTER`,
  `SOURCE_UNVERIFIED` → `SOURCE_NOT_RESOLVED`; `SOURCE_UNAVAILABLE` →
  `SOURCE_UNAVAILABLE`.
- `DOCUMENTATION_CONFLICT`, `SOFT_IP_BLOCK`, any other `OPEN_ITEM_BLOCK`,
  `BUDGET_BLOCK`, `UNKNOWN_BLOCKER` → `GOVERNANCE_BLOCK`.

The renderer never makes a soft-IP or creative clearance decision. A
reported soft-IP blocker means `GOVERNANCE_BLOCK` and no generation.

## Product Specification

Never assume Comfort Colors 1717, and never assume Gildan 5000 because
current drafts happen to use it. Read the current governed product, blank,
provider and color for this design from the authoritative production
records (the queue row, the governing render standard, the governing product
record) and pass every candidate found, each with its `spec_source`. The
renderer uses the specification only when exactly one distinct candidate
exists and it is complete (blank, provider, color, `garment_rgb` for the
fabric fill, `spec_source`). None → `PRODUCT_SPEC_BLOCK`. Two or more that
differ → `PRODUCT_SPEC_BLOCK` with the conflict named for a human. Nothing
is guessed.

## Pricing and Budget

Caps: $2.00 per listing campaign, $25.00 per month, 4 rerolls per campaign.
They are pre-spend guards. Before every generation call the renderer
computes the job's spend so far, the next call's cost from the pricing
snapshot, the month's recorded spend, and the projected month after the
call; if either cap would be exceeded the call is not made (`BUDGET_BLOCK`
before the job, `STOPPED_BUDGET` during it). Spend is never reported after
the fact.

The pricing snapshot is a JSON file maintained by Jody for the configured
provider and model, with `captured_at`, `basis`, `currency` and
`per_image_usd` by quality and size. No snapshot, or no price for a needed
tier, is `PRICING_UNAVAILABLE`; no per-image cost is ever guessed.

The Render Expense Log is read, never written. The renderer writes
`cost-log.json` locally and returns `proposed_expense_log_row` with the
log's fields (`render_job_id`, `design_id`, `started_at`, `completed_at`,
`model`, `quality_mix`, `images_generated`, `rerolls`, `source_drive_id`,
`source_sha256`, `usage_record`, `pricing_snapshot`,
`estimated_api_cost_usd`, `campaign_folder`, `job_status`, `budget_flag`,
`notes`, `actual_billed_cost_usd`). `actual_billed_cost_usd` is always
`null`; billing is never fabricated. A separate narrow writer skill may
commit the row later.

## Rerolls

A reroll is any generation call beyond the first six, caused by unusable
output. At most 4 per campaign. Each is recorded with its slot, reason,
prior failure and added cost. The renderer rejects a scene whose print area
cannot be found or is implausible and makes one controlled replacement; it
never distorts the art to rescue a scene. At 4 rerolls it stops
(`QA_FAILED` for the slot that still has no usable scene); more needs a new
human authorization under a future override path.

## Scene Generation and Compositing

The scene prompt (recorded per slot in the campaign manifest) describes the
garment and environment only: the governed blank, provider and color with
accurate construction; the slot's role; design concept, season and vibe as
atmosphere words only; no text, logos, brand marks, labels or other graphics
anywhere; and one perfectly flat, uniform, solid magenta rectangle on the
chest print area that follows the fabric's shading and perspective. The
approved artwork is never described for recreation.

The compositor (`studio/compositor.py`, Pillow only, no model call):

1. finds the magenta print-area panel; none, too small, too large or not a
   solid convex panel → the scene is unusable (reroll);
2. derives cloth shading from the panel's brightness;
3. replaces the panel with shaded fabric of the governed garment color;
4. fits the art inside the panel preserving its aspect ratio exactly (never
   stretched), maps it by a perspective transform and multiplies the cloth
   shading into it; the art's alpha channel, if any, is used as-is;
5. refuses to upscale: if the fitted width exceeds the art's width →
   `RESOLUTION_BLOCK`;
6. records the placement (quad, art quad, scale, rotation, shading method)
   so QA can recompute the composite from the base scene, the source and the
   placement and compare pixel-for-pixel.

The generated base scene (with the placeholder) is kept beside each final
composite for audit.

## QA

Every final composite is checked before the campaign is considered
successful. Deterministic checks, computed: image size; art identity
(the final equals a fresh recomposite of base scene + approved source +
recorded placement, so spelling, internal geometry and content are preserved
by construction and any post-edit is caught); no upscale; aspect preserved;
placement within bounds; no placeholder leak; single placement, no duplicate
or ghost art; product specification consistent. Per image: `PASS` or
`BLOCKED` (→ `QA_FAILED`); an unusable scene is `REROLL`.

Judgements that need eyes are never auto-passed: realistic shirt
construction, plausible placement, color perception, fold interaction,
impossible seams, extra graphics, unapproved logos, fake text,
misrepresenting artifacts, branding placement when visible, campaign
consistency. `qa/qa.json` lists them under `human_review` as `HUMAN_REVIEW`.
After a successful job Walter should view the contact sheet and each
composite and report what it sees; the human decides.

Campaign-level checks: source identity consistent, garment consistent,
artwork consistent, six required images present.

## Campaign Layout

```
/home/claude/agents/1901/shared/render-campaigns/<design_id>/
    source/<approved filename>        exact byte copy of the staged source
    source/manifest.json              copy of the Skill #6 handoff manifest
    source/source-reference.json      design_id, SHA-256, staged path, Drive id, filename, URL, lineage
    generated-scenes/NN-key-base.png  the six base scenes (rejected attempts kept as NN-key-rejected-N.png)
    final-composites/NN-key.png       the six finals
    qa/qa.json, qa/contact-sheet.png
    manifest.json                     schema_version, design_id, render_job_id, created_at, source lineage,
                                      staged handoff path, product, rendering (provider, model, size, quality
                                      mix, compositor), scene_slots with prompts and placements, filenames,
                                      final SHA-256s, qa_status, estimated spend, reroll_count,
                                      publication_authorized = false (always), human_review_required = true
    cost-log.json
```

The Skill #6 handoff is only read. Nothing is uploaded to Drive. No render
output is written anywhere else.

## Existing Campaign Behaviour

If `<campaign root>/<design_id>/` exists: `ALREADY_RENDERED` only when its
manifest has the same `design_id`, source SHA-256, product specification
(blank, provider, color) and schema version, all six finals exist, and
`qa_status` is `PASS`; nothing is regenerated. Anything else (different
source hash, different product, incomplete, unreadable, QA not PASS) →
`CAMPAIGN_CONFLICT`, human review, nothing deleted or replaced.

## Authorization

The only user-authored text that authorises a render job is the exact
command:

```
AUTHORIZE LISTING RENDER <design_id>
```

Rules: exact structure; surrounding whitespace trimmed; the three words
compare case-insensitively; the id must equal the target exactly; no
alternate wording; no inference; no prior-turn authorization; consumed by
the run that receives it; after any failed job a new command is required.
A command naming another id authorises nothing for either design.

Not authorisation: `Proceed`, `Do it`, `Render it`, `Yes`,
`AUTHORIZE RENDER 1901-093`, `AUTHORIZE LISTING RENDER` (no id), prose
around the command.

## Running the Renderer

The renderer and its provider adapter live in this skill's local clone
(OpenMausBot imports only `SKILL.md`). Walter gathers the live evidence with
the other skills, writes it to a JSON file in its working folder, then runs
one command; the renderer performs the whole decision chain and prints the
output object.

```bash
cd /home/claude/agents/1901/1901-listing-studio
.venv/bin/python render.py --design-id 1901-093 --evidence /path/evidence.json \
  --message "<the user's message, verbatim>" --provider openai
```

`evidence.json`:

```json
{
  "queue":    { "...the 1901-read-idea-queue result..." : "" },
  "resolver": { "...the 1901-resolve-production-source result..." : "" },
  "handoff":  { "...the 1901-prepare-production-handoff result (validation_mode, handoff_status, blockers, next_action)..." : "" },
  "product":  { "candidates": [ { "blank": "", "provider": "", "color": "", "garment_rgb": [0, 0, 0], "spec_source": "" } ] },
  "requires_transparency": true,
  "monthly_recorded_usd": 3.10,
  "atmosphere": { "concept": "", "season": "", "vibe": "" }
}
```

`monthly_recorded_usd` is the sum of this month's rows in the Render Expense
Log, or `null` if the tab could not be read. `requires_transparency` is what
the governing production record says (`null` if it says nothing).
`--provider openai` uses the OpenAI Images API (`gpt-image-1`) with the key
from the environment at call time, never stored or printed; if no key is
present the renderer reports `MODEL_OR_QUALITY_BLOCK` and does nothing.
`--provider mock` is for fixtures only and never for production.

## Output

Return exactly one JSON object:

```json
{
  "design_id": "", "result": "", "render_performed": false, "render_job_id": "", "timestamp": "",
  "source": { "drive_file_id": "", "filename": "", "sha256": "", "staged_path": "" },
  "product": { "blank": "", "provider": "", "color": "", "spec_source": "" },
  "campaign": { "root": "/home/claude/agents/1901/shared/render-campaigns/", "design_folder": "", "manifest_path": "", "qa_path": "", "contact_sheet_path": "", "images": [] },
  "budget": { "per_listing_limit_usd": 2.0, "monthly_limit_usd": 25.0, "estimated_job_cost_usd": 0, "monthly_recorded_cost_usd": 0, "projected_monthly_cost_usd": 0, "budget_flag": "" },
  "verification": { "queue_verified": false, "human_approval_verified": false, "source_verified": false, "handoff_verified": false, "product_spec_verified": false, "pricing_verified": false, "budget_verified": false, "qa_passed": false, "campaign_verified": false },
  "authorization": { "received": false, "evidence": "" },
  "proposed_expense_log_row": {}, "warnings": [], "checks": [], "human_action_required": null
}
```

`render_performed` is `true` only for `READY_FOR_HUMAN_RENDER_REVIEW`.
`campaign.images` lists the planned or produced final filenames.
`proposed_expense_log_row` is filled for proposals (status `PROPOSED`) and
for every job that ran. `human_action_required` is `null` for
`READY_FOR_HUMAN_RENDER_REVIEW` and `ALREADY_RENDERED`.

## Results

| result | spend | files | meaning |
|---|---|---|---|
| `READY_FOR_HUMAN_RENDER_REVIEW` | yes | campaign | Six composites generated, QA passed, package verified and published; human review next. Not publication approval |
| `ALREADY_RENDERED` | no | none | An identical complete campaign exists |
| `AWAITING_RENDER_AUTHORIZATION` | no | none | Eligible; the exact command is not in this run |
| `NOT_FOUND`, `DUPLICATE_ID`, `HUMAN_APPROVAL_REQUIRED`, `SOURCE_MISSING`, `SOURCE_NOT_RESOLVED`, `SOURCE_MISMATCH`, `GOVERNANCE_BLOCK`, `SOURCE_UNAVAILABLE` | no | none | As in the earlier skills; `SOURCE_UNAVAILABLE` also covers an unreadable Render Expense Log |
| `HANDOFF_NOT_STAGED` | no | none | No Skill #6 handoff folder or manifest |
| `HANDOFF_INVALID` | no | none | The handoff exists but does not verify (hash, authority, integrity, readiness, or unreadable image) |
| `PRODUCT_SPEC_BLOCK` | no | none | No governed product specification, or conflicting ones |
| `ART_PREP_BLOCK` | no | none | Transparency required and the source has none; no derivative exists |
| `RESOLUTION_BLOCK` | ≤1 image | failed job if begun | Source too small for listing composites without upscaling; none performed |
| `PRICING_UNAVAILABLE` | no | none | No usable pricing snapshot before spend |
| `MODEL_OR_QUALITY_BLOCK` | no | none | Provider cannot supply the governed quality mix, or substituted a tier |
| `BUDGET_BLOCK` | no | none | First call or planned campaign would exceed a cap |
| `STOPPED_BUDGET` | partial | failed job | A call during the job would exceed a cap; it was not made |
| `GENERATION_FAILED` | partial | failed job | The provider failed |
| `COMPOSITING_FAILED` | partial | failed job | Deterministic compositing failed |
| `QA_FAILED` | partial | failed job | A composite failed deterministic QA, or a slot has no usable scene after 4 rerolls |
| `CAMPAIGN_CONFLICT` | no | none | An existing campaign differs or is incomplete |
| `MANIFEST_FAILED` | partial | failed job | Records could not be written |
| `VERIFICATION_FAILED` | partial | failed job | The package did not verify; nothing published |

## Pitfalls

- **"Render it" or "Proceed" after a proposal.** Not the command.
- **The handoff is missing but `art_path` points at a file.** Never fetched.
  `HANDOFF_NOT_STAGED`; stage it with Skill #6 first.
- **The queue says Comfort Colors on one row and the Printify draft says
  Gildan.** `PRODUCT_SPEC_BLOCK` with both named. Do not pick.
- **The scene came back with the art already "drawn" by the model.** It
  cannot: the prompt never describes the art. If a scene shows text or
  graphics, that is for the human reviewer; the deterministic composite
  still places the exact art.
- **The hero scene's print area is wider than the source.** `RESOLUTION_BLOCK`.
  Upscaling is a governed derived-asset step, not something to do quietly.
- **Three scenes are mediocre; reroll them all.** Rerolls are for unusable
  scenes, counted, capped at 4, and each costs money. Mediocre goes to human
  review.
- **The campaign folder exists from last week.** `ALREADY_RENDERED` if
  identical and complete, else `CAMPAIGN_CONFLICT`. Never regenerate over it.
- **A pre-existing Printify draft exists.** Parked artifact; neither bypasses
  nor blocks rendering; untouched.

## Live Test Policy

Building, reviewing, importing, or running the fixture tests never
authorises a production render. The tests run the mock provider against
temporary roots only. The first live production render happens through
Walter after this skill is reviewed and imported, Jody inspects the proposal
run, and Jody explicitly sends `AUTHORIZE LISTING RENDER 1901-093`.

## Examples

Fixture outputs from `tests/tests.py` with the mock provider against
temporary roots, shown here under the production roots. Drive ids, hashes,
costs and timestamps are fixtures; live output carries what was actually
read and generated.

### A. Proposal only: AWAITING_RENDER_AUTHORIZATION

Input: `Render the listing campaign for 1901-093.` Zero generation calls, no campaign directory.

```json
{
 "design_id": "1901-093",
 "result": "AWAITING_RENDER_AUTHORIZATION",
 "render_performed": false,
 "render_job_id": "",
 "timestamp": "2026-10-01T02:00:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "filename": "1901-093-B.png",
  "sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "staged_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
 },
 "product": {
  "blank": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt",
  "provider": "Printify / Monster Digital",
  "color": "Pepper",
  "spec_source": "Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
 },
 "campaign": {
  "root": "/home/claude/agents/1901/shared/render-campaigns/",
  "design_folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "manifest_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/manifest.json",
  "qa_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/qa/qa.json",
  "contact_sheet_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/qa/contact-sheet.png",
  "images": [
   "01-hero.png",
   "02-story.png",
   "03-travel.png",
   "04-flatlay.png",
   "05-folded.png",
   "06-detail.png"
  ]
 },
 "budget": {
  "per_listing_limit_usd": 2.0,
  "monthly_limit_usd": 25.0,
  "estimated_job_cost_usd": 0.6,
  "monthly_recorded_cost_usd": 3.1,
  "projected_monthly_cost_usd": 3.7,
  "budget_flag": "OK"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_verified": true,
  "handoff_verified": true,
  "product_spec_verified": true,
  "pricing_verified": true,
  "budget_verified": true,
  "qa_passed": false,
  "campaign_verified": false
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "captured_at": "2026-10-01T00:00:00Z",
   "basis": "fixture pricing for tests",
   "currency": "USD",
   "per_image_usd": {
    "high": {
     "1024x1024": 0.2
    },
    "medium": {
     "1024x1024": 0.05
    }
   }
  },
  "campaign_folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "render_job_id": "",
  "started_at": "",
  "completed_at": "",
  "images_generated": 0,
  "rerolls": 0,
  "usage_record": [],
  "estimated_api_cost_usd": 0.6,
  "job_status": "PROPOSED",
  "budget_flag": "OK",
  "notes": [
   "proposal only; no generation call made"
  ],
  "actual_billed_cost_usd": null
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "staged_handoff",
   "status": "PASS",
   "detail": "handoff valid: manifest, authority, integrity and SHA-256 all verified"
  },
  {
   "check": "source_image",
   "status": "PASS",
   "detail": "1400x1000px, bands RGBA, alpha=yes"
  },
  {
   "check": "product_spec",
   "status": "PASS",
   "detail": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper from Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
  },
  {
   "check": "model_quality",
   "status": "PASS",
   "detail": "mock / mock-image-1 offers high and medium"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per 1024x1024 image (fixture pricing for tests)"
  },
  {
   "check": "budget",
   "status": "PASS",
   "detail": "planned campaign $0.6000 ≤ $2.00; month $3.1000 → $3.7000 ≤ $25.00"
  },
  {
   "check": "existing_campaign",
   "status": "PASS",
   "detail": "no campaign folder exists for this design"
  },
  {
   "check": "authorization",
   "status": "FAIL",
   "detail": "the current run does not contain the exact command AUTHORIZE LISTING RENDER 1901-093; ordinary requests and vague confirmations never authorize rendering"
  }
 ],
 "human_action_required": "No generation call made and no campaign files created. 1901-093 is eligible: source 1901-093-B.png (Drive id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, sha256 5211ed2ff15b…) staged at /home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png; product Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper; six scenes (2 high, 4 medium) on mock/mock-image-1 at an estimated $0.6000, month $3.1000 → $3.7000; output /home/claude/agents/1901/shared/render-campaigns/1901-093. To authorize exactly this render job, send exactly: AUTHORIZE LISTING RENDER 1901-093"
}
```

### B. Authorised render: READY_FOR_HUMAN_RENDER_REVIEW

Input: `AUTHORIZE LISTING RENDER 1901-093`, in a new run. Six scenes, six deterministic composites, QA, package verified, published atomically.

```json
{
 "design_id": "1901-093",
 "result": "READY_FOR_HUMAN_RENDER_REVIEW",
 "render_performed": true,
 "render_job_id": "fixture001",
 "timestamp": "2026-10-01T02:00:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "filename": "1901-093-B.png",
  "sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "staged_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
 },
 "product": {
  "blank": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt",
  "provider": "Printify / Monster Digital",
  "color": "Pepper",
  "spec_source": "Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
 },
 "campaign": {
  "root": "/home/claude/agents/1901/shared/render-campaigns/",
  "design_folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "manifest_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/manifest.json",
  "qa_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/qa/qa.json",
  "contact_sheet_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/qa/contact-sheet.png",
  "images": [
   "01-hero.png",
   "02-story.png",
   "03-travel.png",
   "04-flatlay.png",
   "05-folded.png",
   "06-detail.png"
  ]
 },
 "budget": {
  "per_listing_limit_usd": 2.0,
  "monthly_limit_usd": 25.0,
  "estimated_job_cost_usd": 0.6,
  "monthly_recorded_cost_usd": 3.1,
  "projected_monthly_cost_usd": 3.7,
  "budget_flag": "OK"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_verified": true,
  "handoff_verified": true,
  "product_spec_verified": true,
  "pricing_verified": true,
  "budget_verified": true,
  "qa_passed": true,
  "campaign_verified": true
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE LISTING RENDER 1901-093"
 },
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "captured_at": "2026-10-01T00:00:00Z",
   "basis": "fixture pricing for tests",
   "currency": "USD",
   "per_image_usd": {
    "high": {
     "1024x1024": 0.2
    },
    "medium": {
     "1024x1024": 0.05
    }
   }
  },
  "campaign_folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "render_job_id": "fixture001",
  "started_at": "2026-10-01T02:00:00Z",
  "completed_at": "2026-10-01T02:00:00Z",
  "images_generated": 6,
  "rerolls": 0,
  "usage_record": [
   {
    "slot": 1,
    "quality": "high",
    "size": "1024x1024",
    "estimated_cost_usd": 0.2,
    "reroll": false,
    "reason": "",
    "usage": {
     "images": 1,
     "quality": "high",
     "size": "1024x1024",
     "mock": true
    }
   },
   {
    "slot": 2,
    "quality": "high",
    "size": "1024x1024",
    "estimated_cost_usd": 0.2,
    "reroll": false,
    "reason": "",
    "usage": {
     "images": 1,
     "quality": "high",
     "size": "1024x1024",
     "mock": true
    }
   },
   {
    "slot": 3,
    "quality": "medium",
    "size": "1024x1024",
    "estimated_cost_usd": 0.05,
    "reroll": false,
    "reason": "",
    "usage": {
     "images": 1,
     "quality": "medium",
     "size": "1024x1024",
     "mock": true
    }
   },
   {
    "slot": 4,
    "quality": "medium",
    "size": "1024x1024",
    "estimated_cost_usd": 0.05,
    "reroll": false,
    "reason": "",
    "usage": {
     "images": 1,
     "quality": "medium",
     "size": "1024x1024",
     "mock": true
    }
   },
   {
    "slot": 5,
    "quality": "medium",
    "size": "1024x1024",
    "estimated_cost_usd": 0.05,
    "reroll": false,
    "reason": "",
    "usage": {
     "images": 1,
     "quality": "medium",
     "size": "1024x1024",
     "mock": true
    }
   },
   {
    "slot": 6,
    "quality": "medium",
    "size": "1024x1024",
    "estimated_cost_usd": 0.05,
    "reroll": false,
    "reason": "",
    "usage": {
     "images": 1,
     "quality": "medium",
     "size": "1024x1024",
     "mock": true
    }
   }
  ],
  "estimated_api_cost_usd": 0.6,
  "job_status": "COMPLETED",
  "budget_flag": "OK",
  "notes": [],
  "actual_billed_cost_usd": null
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "staged_handoff",
   "status": "PASS",
   "detail": "handoff valid: manifest, authority, integrity and SHA-256 all verified"
  },
  {
   "check": "source_image",
   "status": "PASS",
   "detail": "1400x1000px, bands RGBA, alpha=yes"
  },
  {
   "check": "product_spec",
   "status": "PASS",
   "detail": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper from Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
  },
  {
   "check": "model_quality",
   "status": "PASS",
   "detail": "mock / mock-image-1 offers high and medium"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per 1024x1024 image (fixture pricing for tests)"
  },
  {
   "check": "budget",
   "status": "PASS",
   "detail": "planned campaign $0.6000 ≤ $2.00; month $3.1000 → $3.7000 ≤ $25.00"
  },
  {
   "check": "existing_campaign",
   "status": "PASS",
   "detail": "no campaign folder exists for this design"
  },
  {
   "check": "authorization",
   "status": "PASS",
   "detail": "current run contains the exact command: AUTHORIZE LISTING RENDER 1901-093"
  },
  {
   "check": "source_copy",
   "status": "PASS",
   "detail": "exact source bytes, the handoff manifest and source-reference.json recorded in the job"
  },
  {
   "check": "scene_1",
   "status": "PASS",
   "detail": "hero_lifestyle (high) generated, composited at scale 0.2057, deterministic QA PASS"
  },
  {
   "check": "scene_2",
   "status": "PASS",
   "detail": "secondary_lifestyle_story (high) generated, composited at scale 0.2343, deterministic QA PASS"
  },
  {
   "check": "scene_3",
   "status": "PASS",
   "detail": "travel_packing (medium) generated, composited at scale 0.1471, deterministic QA PASS"
  },
  {
   "check": "scene_4",
   "status": "PASS",
   "detail": "editorial_flat_lay (medium) generated, composited at scale 0.25, deterministic QA PASS"
  },
  {
   "check": "scene_5",
   "status": "PASS",
   "detail": "folded_garment_detail (medium) generated, composited at scale 0.1757, deterministic QA PASS"
  },
  {
   "check": "scene_6",
   "status": "PASS",
   "detail": "product_construction_detail (medium) generated, composited at scale 0.1471, deterministic QA PASS"
  },
  {
   "check": "manifest",
   "status": "PASS",
   "detail": "qa.json, contact-sheet.png, cost-log.json and manifest.json written"
  },
  {
   "check": "package_verification",
   "status": "PASS",
   "detail": "19 files present, six final composites hash-verified, publication_authorized=false; published atomically to /home/claude/agents/1901/shared/render-campaigns/1901-093"
  }
 ],
 "human_action_required": null
}
```

### C. Wrong design id: AWAITING_RENDER_AUTHORIZATION

Target `1901-093`; input `AUTHORIZE LISTING RENDER 1901-094`.

```json
{
 "design_id": "1901-093",
 "result": "AWAITING_RENDER_AUTHORIZATION",
 "render_performed": false,
 "render_job_id": "",
 "timestamp": "2026-10-01T02:00:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "filename": "1901-093-B.png",
  "sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "staged_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
 },
 "product": {
  "blank": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt",
  "provider": "Printify / Monster Digital",
  "color": "Pepper",
  "spec_source": "Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
 },
 "campaign": {
  "root": "/home/claude/agents/1901/shared/render-campaigns/",
  "design_folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "manifest_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/manifest.json",
  "qa_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/qa/qa.json",
  "contact_sheet_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/qa/contact-sheet.png",
  "images": [
   "01-hero.png",
   "02-story.png",
   "03-travel.png",
   "04-flatlay.png",
   "05-folded.png",
   "06-detail.png"
  ]
 },
 "budget": {
  "per_listing_limit_usd": 2.0,
  "monthly_limit_usd": 25.0,
  "estimated_job_cost_usd": 0.6,
  "monthly_recorded_cost_usd": 3.1,
  "projected_monthly_cost_usd": 3.7,
  "budget_flag": "OK"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_verified": true,
  "handoff_verified": true,
  "product_spec_verified": true,
  "pricing_verified": true,
  "budget_verified": true,
  "qa_passed": false,
  "campaign_verified": false
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "captured_at": "2026-10-01T00:00:00Z",
   "basis": "fixture pricing for tests",
   "currency": "USD",
   "per_image_usd": {
    "high": {
     "1024x1024": 0.2
    },
    "medium": {
     "1024x1024": 0.05
    }
   }
  },
  "campaign_folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "render_job_id": "",
  "started_at": "",
  "completed_at": "",
  "images_generated": 0,
  "rerolls": 0,
  "usage_record": [],
  "estimated_api_cost_usd": 0.6,
  "job_status": "PROPOSED",
  "budget_flag": "OK",
  "notes": [
   "proposal only; no generation call made"
  ],
  "actual_billed_cost_usd": null
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "staged_handoff",
   "status": "PASS",
   "detail": "handoff valid: manifest, authority, integrity and SHA-256 all verified"
  },
  {
   "check": "source_image",
   "status": "PASS",
   "detail": "1400x1000px, bands RGBA, alpha=yes"
  },
  {
   "check": "product_spec",
   "status": "PASS",
   "detail": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper from Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
  },
  {
   "check": "model_quality",
   "status": "PASS",
   "detail": "mock / mock-image-1 offers high and medium"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per 1024x1024 image (fixture pricing for tests)"
  },
  {
   "check": "budget",
   "status": "PASS",
   "detail": "planned campaign $0.6000 ≤ $2.00; month $3.1000 → $3.7000 ≤ $25.00"
  },
  {
   "check": "existing_campaign",
   "status": "PASS",
   "detail": "no campaign folder exists for this design"
  },
  {
   "check": "authorization",
   "status": "FAIL",
   "detail": "the command names 1901-094, not the target 1901-093; it authorizes nothing in this run"
  }
 ],
 "human_action_required": "No generation call made and no campaign files created. 1901-093 is eligible: source 1901-093-B.png (Drive id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, sha256 5211ed2ff15b…) staged at /home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png; product Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper; six scenes (2 high, 4 medium) on mock/mock-image-1 at an estimated $0.6000, month $3.1000 → $3.7000; output /home/claude/agents/1901/shared/render-campaigns/1901-093. To authorize exactly this render job, send exactly: AUTHORIZE LISTING RENDER 1901-093"
}
```

### D. One unusable scene, one controlled reroll

Scene 2 came back with no usable print area; one reroll, counted and costed.

```json
{
 "design_id": "1901-093",
 "result": "READY_FOR_HUMAN_RENDER_REVIEW",
 "render_performed": true,
 "render_job_id": "fixture001",
 "timestamp": "2026-10-01T02:00:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "filename": "1901-093-B.png",
  "sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "staged_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
 },
 "product": {
  "blank": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt",
  "provider": "Printify / Monster Digital",
  "color": "Pepper",
  "spec_source": "Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
 },
 "campaign": {
  "root": "/home/claude/agents/1901/shared/render-campaigns/",
  "design_folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "manifest_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/manifest.json",
  "qa_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/qa/qa.json",
  "contact_sheet_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/qa/contact-sheet.png",
  "images": [
   "01-hero.png",
   "02-story.png",
   "03-travel.png",
   "04-flatlay.png",
   "05-folded.png",
   "06-detail.png"
  ]
 },
 "budget": {
  "per_listing_limit_usd": 2.0,
  "monthly_limit_usd": 25.0,
  "estimated_job_cost_usd": 0.8,
  "monthly_recorded_cost_usd": 3.1,
  "projected_monthly_cost_usd": 3.9,
  "budget_flag": "OK"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_verified": true,
  "handoff_verified": true,
  "product_spec_verified": true,
  "pricing_verified": true,
  "budget_verified": true,
  "qa_passed": true,
  "campaign_verified": true
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE LISTING RENDER 1901-093"
 },
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "captured_at": "2026-10-01T00:00:00Z",
   "basis": "fixture pricing for tests",
   "currency": "USD",
   "per_image_usd": {
    "high": {
     "1024x1024": 0.2
    },
    "medium": {
     "1024x1024": 0.05
    }
   }
  },
  "campaign_folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "render_job_id": "fixture001",
  "started_at": "2026-10-01T02:00:00Z",
  "completed_at": "2026-10-01T02:00:00Z",
  "images_generated": 7,
  "rerolls": 1,
  "usage_record": [
   {
    "slot": 1,
    "quality": "high",
    "size": "1024x1024",
    "estimated_cost_usd": 0.2,
    "reroll": false,
    "reason": "",
    "usage": {
     "images": 1,
     "quality": "high",
     "size": "1024x1024",
     "mock": true
    }
   },
   {
    "slot": 2,
    "quality": "high",
    "size": "1024x1024",
    "estimated_cost_usd": 0.2,
    "reroll": false,
    "reason": "",
    "usage": {
     "images": 1,
     "quality": "high",
     "size": "1024x1024",
     "mock": true
    }
   },
   {
    "slot": 2,
    "quality": "high",
    "size": "1024x1024",
    "estimated_cost_usd": 0.2,
    "reroll": true,
    "reason": "scene 2 unusable: no print-area placeholder found in the scene",
    "usage": {
     "images": 1,
     "quality": "high",
     "size": "1024x1024",
     "mock": true
    }
   },
   {
    "slot": 3,
    "quality": "medium",
    "size": "1024x1024",
    "estimated_cost_usd": 0.05,
    "reroll": false,
    "reason": "",
    "usage": {
     "images": 1,
     "quality": "medium",
     "size": "1024x1024",
     "mock": true
    }
   },
   {
    "slot": 4,
    "quality": "medium",
    "size": "1024x1024",
    "estimated_cost_usd": 0.05,
    "reroll": false,
    "reason": "",
    "usage": {
     "images": 1,
     "quality": "medium",
     "size": "1024x1024",
     "mock": true
    }
   },
   {
    "slot": 5,
    "quality": "medium",
    "size": "1024x1024",
    "estimated_cost_usd": 0.05,
    "reroll": false,
    "reason": "",
    "usage": {
     "images": 1,
     "quality": "medium",
     "size": "1024x1024",
     "mock": true
    }
   },
   {
    "slot": 6,
    "quality": "medium",
    "size": "1024x1024",
    "estimated_cost_usd": 0.05,
    "reroll": false,
    "reason": "",
    "usage": {
     "images": 1,
     "quality": "medium",
     "size": "1024x1024",
     "mock": true
    }
   }
  ],
  "estimated_api_cost_usd": 0.8,
  "job_status": "COMPLETED",
  "budget_flag": "OK",
  "notes": [],
  "actual_billed_cost_usd": null
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "staged_handoff",
   "status": "PASS",
   "detail": "handoff valid: manifest, authority, integrity and SHA-256 all verified"
  },
  {
   "check": "source_image",
   "status": "PASS",
   "detail": "1400x1000px, bands RGBA, alpha=yes"
  },
  {
   "check": "product_spec",
   "status": "PASS",
   "detail": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper from Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
  },
  {
   "check": "model_quality",
   "status": "PASS",
   "detail": "mock / mock-image-1 offers high and medium"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per 1024x1024 image (fixture pricing for tests)"
  },
  {
   "check": "budget",
   "status": "PASS",
   "detail": "planned campaign $0.6000 ≤ $2.00; month $3.1000 → $3.7000 ≤ $25.00"
  },
  {
   "check": "existing_campaign",
   "status": "PASS",
   "detail": "no campaign folder exists for this design"
  },
  {
   "check": "authorization",
   "status": "PASS",
   "detail": "current run contains the exact command: AUTHORIZE LISTING RENDER 1901-093"
  },
  {
   "check": "source_copy",
   "status": "PASS",
   "detail": "exact source bytes, the handoff manifest and source-reference.json recorded in the job"
  },
  {
   "check": "scene_1",
   "status": "PASS",
   "detail": "hero_lifestyle (high) generated, composited at scale 0.2057, deterministic QA PASS"
  },
  {
   "check": "scene_2",
   "status": "INFO",
   "detail": "attempt 1 rejected (no print-area placeholder found in the scene); one controlled reroll (reroll 1 of 4); the art is never distorted to fit a bad scene"
  },
  {
   "check": "scene_2",
   "status": "PASS",
   "detail": "secondary_lifestyle_story (high) generated, composited at scale 0.2343, deterministic QA PASS after 1 reroll(s)"
  },
  {
   "check": "scene_3",
   "status": "PASS",
   "detail": "travel_packing (medium) generated, composited at scale 0.1471, deterministic QA PASS"
  },
  {
   "check": "scene_4",
   "status": "PASS",
   "detail": "editorial_flat_lay (medium) generated, composited at scale 0.25, deterministic QA PASS"
  },
  {
   "check": "scene_5",
   "status": "PASS",
   "detail": "folded_garment_detail (medium) generated, composited at scale 0.1757, deterministic QA PASS"
  },
  {
   "check": "scene_6",
   "status": "PASS",
   "detail": "product_construction_detail (medium) generated, composited at scale 0.1471, deterministic QA PASS"
  },
  {
   "check": "manifest",
   "status": "PASS",
   "detail": "qa.json, contact-sheet.png, cost-log.json and manifest.json written"
  },
  {
   "check": "package_verification",
   "status": "PASS",
   "detail": "19 files present, six final composites hash-verified, publication_authorized=false; published atomically to /home/claude/agents/1901/shared/render-campaigns/1901-093"
  }
 ],
 "human_action_required": null
}
```

### E. Mid-job budget stop: STOPPED_BUDGET

The reroll landed exactly on the monthly cap; the next call would exceed it and was not made. Artifacts kept under `_failed/`.

```json
{
 "design_id": "1901-093",
 "result": "STOPPED_BUDGET",
 "render_performed": false,
 "render_job_id": "fixture001",
 "timestamp": "2026-10-01T02:00:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "filename": "1901-093-B.png",
  "sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "staged_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
 },
 "product": {
  "blank": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt",
  "provider": "Printify / Monster Digital",
  "color": "Pepper",
  "spec_source": "Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
 },
 "campaign": {
  "root": "/home/claude/agents/1901/shared/render-campaigns/",
  "design_folder": "",
  "manifest_path": "",
  "qa_path": "",
  "contact_sheet_path": "",
  "images": []
 },
 "budget": {
  "per_listing_limit_usd": 2.0,
  "monthly_limit_usd": 25.0,
  "estimated_job_cost_usd": 0.6,
  "monthly_recorded_cost_usd": 24.4,
  "projected_monthly_cost_usd": 25.0,
  "budget_flag": "STOPPED"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_verified": true,
  "handoff_verified": true,
  "product_spec_verified": true,
  "pricing_verified": true,
  "budget_verified": true,
  "qa_passed": false,
  "campaign_verified": false
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE LISTING RENDER 1901-093"
 },
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "captured_at": "2026-10-01T00:00:00Z",
   "basis": "fixture pricing for tests",
   "currency": "USD",
   "per_image_usd": {
    "high": {
     "1024x1024": 0.2
    },
    "medium": {
     "1024x1024": 0.05
    }
   }
  },
  "campaign_folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "render_job_id": "fixture001",
  "started_at": "2026-10-01T02:00:00Z",
  "completed_at": "2026-10-01T02:00:00Z",
  "images_generated": 3,
  "rerolls": 1,
  "usage_record": [
   {
    "slot": 1,
    "quality": "high",
    "size": "1024x1024",
    "estimated_cost_usd": 0.2,
    "reroll": false,
    "reason": "",
    "usage": {
     "images": 1,
     "quality": "high",
     "size": "1024x1024",
     "mock": true
    }
   },
   {
    "slot": 2,
    "quality": "high",
    "size": "1024x1024",
    "estimated_cost_usd": 0.2,
    "reroll": false,
    "reason": "",
    "usage": {
     "images": 1,
     "quality": "high",
     "size": "1024x1024",
     "mock": true
    }
   },
   {
    "slot": 2,
    "quality": "high",
    "size": "1024x1024",
    "estimated_cost_usd": 0.2,
    "reroll": true,
    "reason": "scene 2 unusable: no print-area placeholder found in the scene",
    "usage": {
     "images": 1,
     "quality": "high",
     "size": "1024x1024",
     "mock": true
    }
   }
  ],
  "estimated_api_cost_usd": 0.6,
  "job_status": "FAILED:STOPPED_BUDGET",
  "budget_flag": "STOPPED",
  "notes": [],
  "actual_billed_cost_usd": null
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "staged_handoff",
   "status": "PASS",
   "detail": "handoff valid: manifest, authority, integrity and SHA-256 all verified"
  },
  {
   "check": "source_image",
   "status": "PASS",
   "detail": "1400x1000px, bands RGBA, alpha=yes"
  },
  {
   "check": "product_spec",
   "status": "PASS",
   "detail": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper from Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
  },
  {
   "check": "model_quality",
   "status": "PASS",
   "detail": "mock / mock-image-1 offers high and medium"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per 1024x1024 image (fixture pricing for tests)"
  },
  {
   "check": "budget",
   "status": "PASS",
   "detail": "planned campaign $0.6000 ≤ $2.00; month $24.4000 → $25.0000 ≤ $25.00"
  },
  {
   "check": "existing_campaign",
   "status": "PASS",
   "detail": "no campaign folder exists for this design"
  },
  {
   "check": "authorization",
   "status": "PASS",
   "detail": "current run contains the exact command: AUTHORIZE LISTING RENDER 1901-093"
  },
  {
   "check": "source_copy",
   "status": "PASS",
   "detail": "exact source bytes, the handoff manifest and source-reference.json recorded in the job"
  },
  {
   "check": "scene_1",
   "status": "PASS",
   "detail": "hero_lifestyle (high) generated, composited at scale 0.2057, deterministic QA PASS"
  },
  {
   "check": "scene_2",
   "status": "INFO",
   "detail": "attempt 1 rejected (no print-area placeholder found in the scene); one controlled reroll (reroll 1 of 4); the art is never distorted to fit a bad scene"
  },
  {
   "check": "scene_2",
   "status": "PASS",
   "detail": "secondary_lifestyle_story (high) generated, composited at scale 0.2343, deterministic QA PASS after 1 reroll(s)"
  },
  {
   "check": "budget",
   "status": "FAIL",
   "detail": "before scene 3: next call would bring the month to $25.0500, over the $25.00 monthly cap; call not made"
  },
  {
   "check": "failed_job",
   "status": "INFO",
   "detail": "job artifacts kept for diagnosis at /home/claude/agents/1901/shared/render-campaigns/_failed/1901-093-fixture001; no downstream-ready flag; no final campaign folder created"
  }
 ],
 "human_action_required": "Rendering 1901-093 stopped before scene 3: next call would bring the month to $25.0500, over the $25.00 monthly cap. 3 image(s) generated so far; no further spend. A new AUTHORIZE LISTING RENDER 1901-093 command is required after Jody decides on the budget."
}
```

### F. Existing identical campaign: ALREADY_RENDERED

```json
{
 "design_id": "1901-093",
 "result": "ALREADY_RENDERED",
 "render_performed": false,
 "render_job_id": "fixture001",
 "timestamp": "2026-10-01T02:00:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "filename": "1901-093-B.png",
  "sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "staged_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
 },
 "product": {
  "blank": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt",
  "provider": "Printify / Monster Digital",
  "color": "Pepper",
  "spec_source": "Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
 },
 "campaign": {
  "root": "/home/claude/agents/1901/shared/render-campaigns/",
  "design_folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "manifest_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/manifest.json",
  "qa_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/qa/qa.json",
  "contact_sheet_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/qa/contact-sheet.png",
  "images": [
   "01-hero.png",
   "02-story.png",
   "03-travel.png",
   "04-flatlay.png",
   "05-folded.png",
   "06-detail.png"
  ]
 },
 "budget": {
  "per_listing_limit_usd": 2.0,
  "monthly_limit_usd": 25.0,
  "estimated_job_cost_usd": 0.6,
  "monthly_recorded_cost_usd": 3.1,
  "projected_monthly_cost_usd": 3.7,
  "budget_flag": "OK"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_verified": true,
  "handoff_verified": true,
  "product_spec_verified": true,
  "pricing_verified": true,
  "budget_verified": true,
  "qa_passed": true,
  "campaign_verified": true
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "proposed_expense_log_row": {},
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "staged_handoff",
   "status": "PASS",
   "detail": "handoff valid: manifest, authority, integrity and SHA-256 all verified"
  },
  {
   "check": "source_image",
   "status": "PASS",
   "detail": "1400x1000px, bands RGBA, alpha=yes"
  },
  {
   "check": "product_spec",
   "status": "PASS",
   "detail": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper from Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
  },
  {
   "check": "model_quality",
   "status": "PASS",
   "detail": "mock / mock-image-1 offers high and medium"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per 1024x1024 image (fixture pricing for tests)"
  },
  {
   "check": "budget",
   "status": "PASS",
   "detail": "planned campaign $0.6000 ≤ $2.00; month $3.1000 → $3.7000 ≤ $25.00"
  },
  {
   "check": "existing_campaign",
   "status": "PASS",
   "detail": "existing campaign has the same design, source hash, product specification and schema, a complete six-image package and QA PASS"
  }
 ],
 "human_action_required": null
}
```

### G. Existing campaign with a different source hash: CAMPAIGN_CONFLICT

```json
{
 "design_id": "1901-093",
 "result": "CAMPAIGN_CONFLICT",
 "render_performed": false,
 "render_job_id": "",
 "timestamp": "2026-10-01T02:00:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "filename": "1901-093-B.png",
  "sha256": "a944c14548b2399f0d8e6ab8d04a93c82d73695b57bb72d71eb3df1d03125e5b",
  "staged_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
 },
 "product": {
  "blank": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt",
  "provider": "Printify / Monster Digital",
  "color": "Pepper",
  "spec_source": "Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
 },
 "campaign": {
  "root": "/home/claude/agents/1901/shared/render-campaigns/",
  "design_folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "manifest_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/manifest.json",
  "qa_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/qa/qa.json",
  "contact_sheet_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/qa/contact-sheet.png",
  "images": []
 },
 "budget": {
  "per_listing_limit_usd": 2.0,
  "monthly_limit_usd": 25.0,
  "estimated_job_cost_usd": 0.6,
  "monthly_recorded_cost_usd": 3.1,
  "projected_monthly_cost_usd": 3.7,
  "budget_flag": "OK"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_verified": true,
  "handoff_verified": true,
  "product_spec_verified": true,
  "pricing_verified": true,
  "budget_verified": true,
  "qa_passed": false,
  "campaign_verified": false
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "proposed_expense_log_row": {},
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "staged_handoff",
   "status": "PASS",
   "detail": "handoff valid: manifest, authority, integrity and SHA-256 all verified"
  },
  {
   "check": "source_image",
   "status": "PASS",
   "detail": "1500x1100px, bands RGBA, alpha=yes"
  },
  {
   "check": "product_spec",
   "status": "PASS",
   "detail": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper from Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
  },
  {
   "check": "model_quality",
   "status": "PASS",
   "detail": "mock / mock-image-1 offers high and medium"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per 1024x1024 image (fixture pricing for tests)"
  },
  {
   "check": "budget",
   "status": "PASS",
   "detail": "planned campaign $0.6000 ≤ $2.00; month $3.1000 → $3.7000 ≤ $25.00"
  },
  {
   "check": "existing_campaign",
   "status": "FAIL",
   "detail": "existing campaign differs: different source SHA-256"
  }
 ],
 "human_action_required": "A campaign folder for 1901-093 already exists and does not match (existing campaign differs: different source SHA-256); a human must review /home/claude/agents/1901/shared/render-campaigns/1901-093. Nothing was overwritten or regenerated."
}
```

### H. No product specification: PRODUCT_SPEC_BLOCK

```json
{
 "design_id": "1901-093",
 "result": "PRODUCT_SPEC_BLOCK",
 "render_performed": false,
 "render_job_id": "",
 "timestamp": "2026-10-01T02:00:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "filename": "1901-093-B.png",
  "sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "staged_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
 },
 "product": {
  "blank": "",
  "provider": "",
  "color": "",
  "spec_source": ""
 },
 "campaign": {
  "root": "/home/claude/agents/1901/shared/render-campaigns/",
  "design_folder": "",
  "manifest_path": "",
  "qa_path": "",
  "contact_sheet_path": "",
  "images": []
 },
 "budget": {
  "per_listing_limit_usd": 2.0,
  "monthly_limit_usd": 25.0,
  "estimated_job_cost_usd": 0,
  "monthly_recorded_cost_usd": 0,
  "projected_monthly_cost_usd": 0,
  "budget_flag": ""
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_verified": true,
  "handoff_verified": true,
  "product_spec_verified": false,
  "pricing_verified": false,
  "budget_verified": false,
  "qa_passed": false,
  "campaign_verified": false
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "proposed_expense_log_row": {},
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "staged_handoff",
   "status": "PASS",
   "detail": "handoff valid: manifest, authority, integrity and SHA-256 all verified"
  },
  {
   "check": "source_image",
   "status": "PASS",
   "detail": "1400x1000px, bands RGBA, alpha=yes"
  },
  {
   "check": "product_spec",
   "status": "FAIL",
   "detail": "no governed product/blank/provider/color specification is established for this design"
  }
 ],
 "human_action_required": "Record the governed product specification (blank, provider, color) for 1901-093 in the authoritative production record before rendering. Nothing was assumed."
}
```

### I. Conflicting product specifications: PRODUCT_SPEC_BLOCK

```json
{
 "design_id": "1901-093",
 "result": "PRODUCT_SPEC_BLOCK",
 "render_performed": false,
 "render_job_id": "",
 "timestamp": "2026-10-01T02:00:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "filename": "1901-093-B.png",
  "sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "staged_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
 },
 "product": {
  "blank": "",
  "provider": "",
  "color": "",
  "spec_source": ""
 },
 "campaign": {
  "root": "/home/claude/agents/1901/shared/render-campaigns/",
  "design_folder": "",
  "manifest_path": "",
  "qa_path": "",
  "contact_sheet_path": "",
  "images": []
 },
 "budget": {
  "per_listing_limit_usd": 2.0,
  "monthly_limit_usd": 25.0,
  "estimated_job_cost_usd": 0,
  "monthly_recorded_cost_usd": 0,
  "projected_monthly_cost_usd": 0,
  "budget_flag": ""
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_verified": true,
  "handoff_verified": true,
  "product_spec_verified": false,
  "pricing_verified": false,
  "budget_verified": false,
  "qa_passed": false,
  "campaign_verified": false
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "proposed_expense_log_row": {},
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "staged_handoff",
   "status": "PASS",
   "detail": "handoff valid: manifest, authority, integrity and SHA-256 all verified"
  },
  {
   "check": "source_image",
   "status": "PASS",
   "detail": "1400x1000px, bands RGBA, alpha=yes"
  },
  {
   "check": "product_spec",
   "status": "FAIL",
   "detail": "conflicting product specifications: Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper (Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product) vs Gildan 5000 Heavy Cotton / Printify / Monster Digital / Black (existing Printify draft)"
  }
 ],
 "human_action_required": "Authoritative records disagree on the product for 1901-093: Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper (Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product) vs Gildan 5000 Heavy Cotton / Printify / Monster Digital / Black (existing Printify draft). A human must record one governing specification."
}
```

### J. First call exceeds the per-listing cap: BUDGET_BLOCK

```json
{
 "design_id": "1901-093",
 "result": "BUDGET_BLOCK",
 "render_performed": false,
 "render_job_id": "",
 "timestamp": "2026-10-01T02:00:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "filename": "1901-093-B.png",
  "sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "staged_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
 },
 "product": {
  "blank": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt",
  "provider": "Printify / Monster Digital",
  "color": "Pepper",
  "spec_source": "Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
 },
 "campaign": {
  "root": "/home/claude/agents/1901/shared/render-campaigns/",
  "design_folder": "",
  "manifest_path": "",
  "qa_path": "",
  "contact_sheet_path": "",
  "images": []
 },
 "budget": {
  "per_listing_limit_usd": 2.0,
  "monthly_limit_usd": 25.0,
  "estimated_job_cost_usd": 5.2,
  "monthly_recorded_cost_usd": 3.1,
  "projected_monthly_cost_usd": 8.3,
  "budget_flag": "BLOCKED"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_verified": true,
  "handoff_verified": true,
  "product_spec_verified": true,
  "pricing_verified": true,
  "budget_verified": false,
  "qa_passed": false,
  "campaign_verified": false
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "proposed_expense_log_row": {},
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "staged_handoff",
   "status": "PASS",
   "detail": "handoff valid: manifest, authority, integrity and SHA-256 all verified"
  },
  {
   "check": "source_image",
   "status": "PASS",
   "detail": "1400x1000px, bands RGBA, alpha=yes"
  },
  {
   "check": "product_spec",
   "status": "PASS",
   "detail": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper from Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
  },
  {
   "check": "model_quality",
   "status": "PASS",
   "detail": "mock / mock-image-1 offers high and medium"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 captured 2026-10-01T00:00:00Z: high $2.5000, medium $0.0500 per 1024x1024 image (fixture pricing for tests)"
  },
  {
   "check": "budget",
   "status": "FAIL",
   "detail": "next call would bring this campaign to $2.5000, over the $2.00 per-listing cap; no generation call was made"
  }
 ],
 "human_action_required": "Rendering 1901-093 would exceed a governed budget cap (next call would bring this campaign to $2.5000, over the $2.00 per-listing cap). Jody must raise the cap or hold the design. No spend occurred."
}
```

### K. Transparency required, opaque source: ART_PREP_BLOCK

```json
{
 "design_id": "1901-093",
 "result": "ART_PREP_BLOCK",
 "render_performed": false,
 "render_job_id": "",
 "timestamp": "2026-10-01T02:00:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "filename": "1901-093-B.png",
  "sha256": "341851aa2358a778407982146897142df0739fb2100ce3ffd9a1fcb20661cc00",
  "staged_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
 },
 "product": {
  "blank": "",
  "provider": "",
  "color": "",
  "spec_source": ""
 },
 "campaign": {
  "root": "/home/claude/agents/1901/shared/render-campaigns/",
  "design_folder": "",
  "manifest_path": "",
  "qa_path": "",
  "contact_sheet_path": "",
  "images": []
 },
 "budget": {
  "per_listing_limit_usd": 2.0,
  "monthly_limit_usd": 25.0,
  "estimated_job_cost_usd": 0,
  "monthly_recorded_cost_usd": 0,
  "projected_monthly_cost_usd": 0,
  "budget_flag": ""
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_verified": true,
  "handoff_verified": true,
  "product_spec_verified": false,
  "pricing_verified": false,
  "budget_verified": false,
  "qa_passed": false,
  "campaign_verified": false
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "proposed_expense_log_row": {},
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "staged_handoff",
   "status": "PASS",
   "detail": "handoff valid: manifest, authority, integrity and SHA-256 all verified"
  },
  {
   "check": "source_image",
   "status": "FAIL",
   "detail": "the governing record requires a transparent-background source and the staged source has no alpha channel"
  }
 ],
 "human_action_required": "A transparency-prepared derivative of the approved master for 1901-093 is required and does not exist. The canonical source was not altered; produce the derivative through a governed derived-asset step with lineage."
}
```

### L. Source too small: RESOLUTION_BLOCK

```json
{
 "design_id": "1901-093",
 "result": "RESOLUTION_BLOCK",
 "render_performed": false,
 "render_job_id": "",
 "timestamp": "2026-10-01T02:00:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "filename": "1901-093-B.png",
  "sha256": "09fabd091cc1e3d193dcd1933a7885a9b2aa3375ff8361db48082b4b19d017ce",
  "staged_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
 },
 "product": {
  "blank": "",
  "provider": "",
  "color": "",
  "spec_source": ""
 },
 "campaign": {
  "root": "/home/claude/agents/1901/shared/render-campaigns/",
  "design_folder": "",
  "manifest_path": "",
  "qa_path": "",
  "contact_sheet_path": "",
  "images": []
 },
 "budget": {
  "per_listing_limit_usd": 2.0,
  "monthly_limit_usd": 25.0,
  "estimated_job_cost_usd": 0,
  "monthly_recorded_cost_usd": 0,
  "projected_monthly_cost_usd": 0,
  "budget_flag": ""
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_verified": true,
  "handoff_verified": true,
  "product_spec_verified": false,
  "pricing_verified": false,
  "budget_verified": false,
  "qa_passed": false,
  "campaign_verified": false
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "proposed_expense_log_row": {},
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "staged_handoff",
   "status": "PASS",
   "detail": "handoff valid: manifest, authority, integrity and SHA-256 all verified"
  },
  {
   "check": "source_image",
   "status": "FAIL",
   "detail": "source is 600x430px; listing composites need at least 1024px on the long side without upscaling"
  }
 ],
 "human_action_required": "The approved source for 1901-093 is too small for believable listing composites without upscaling. Upscaling is a governed derived-asset step; no automatic upscale was performed."
}
```

### M. Composite altered after placement: QA_FAILED

The hero composite was modified after compositing (simulated re-lettering); the recomposite check caught it and the job was not published.

```json
{
 "design_id": "1901-093",
 "result": "QA_FAILED",
 "render_performed": false,
 "render_job_id": "fixture001",
 "timestamp": "2026-10-01T02:00:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "filename": "1901-093-B.png",
  "sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "staged_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
 },
 "product": {
  "blank": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt",
  "provider": "Printify / Monster Digital",
  "color": "Pepper",
  "spec_source": "Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
 },
 "campaign": {
  "root": "/home/claude/agents/1901/shared/render-campaigns/",
  "design_folder": "",
  "manifest_path": "",
  "qa_path": "",
  "contact_sheet_path": "",
  "images": []
 },
 "budget": {
  "per_listing_limit_usd": 2.0,
  "monthly_limit_usd": 25.0,
  "estimated_job_cost_usd": 0.2,
  "monthly_recorded_cost_usd": 3.1,
  "projected_monthly_cost_usd": 3.3,
  "budget_flag": "OK"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_verified": true,
  "handoff_verified": true,
  "product_spec_verified": true,
  "pricing_verified": true,
  "budget_verified": true,
  "qa_passed": false,
  "campaign_verified": false
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE LISTING RENDER 1901-093"
 },
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "captured_at": "2026-10-01T00:00:00Z",
   "basis": "fixture pricing for tests",
   "currency": "USD",
   "per_image_usd": {
    "high": {
     "1024x1024": 0.2
    },
    "medium": {
     "1024x1024": 0.05
    }
   }
  },
  "campaign_folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "render_job_id": "fixture001",
  "started_at": "2026-10-01T02:00:00Z",
  "completed_at": "2026-10-01T02:00:00Z",
  "images_generated": 1,
  "rerolls": 0,
  "usage_record": [
   {
    "slot": 1,
    "quality": "high",
    "size": "1024x1024",
    "estimated_cost_usd": 0.2,
    "reroll": false,
    "reason": "",
    "usage": {
     "images": 1,
     "quality": "high",
     "size": "1024x1024",
     "mock": true
    }
   }
  ],
  "estimated_api_cost_usd": 0.2,
  "job_status": "FAILED:QA_FAILED",
  "budget_flag": "OK",
  "notes": [],
  "actual_billed_cost_usd": null
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "staged_handoff",
   "status": "PASS",
   "detail": "handoff valid: manifest, authority, integrity and SHA-256 all verified"
  },
  {
   "check": "source_image",
   "status": "PASS",
   "detail": "1400x1000px, bands RGBA, alpha=yes"
  },
  {
   "check": "product_spec",
   "status": "PASS",
   "detail": "Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper from Idea Queue row 95 + 01 — 1901 Listing Render System (CURRENT) §Product"
  },
  {
   "check": "model_quality",
   "status": "PASS",
   "detail": "mock / mock-image-1 offers high and medium"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per 1024x1024 image (fixture pricing for tests)"
  },
  {
   "check": "budget",
   "status": "PASS",
   "detail": "planned campaign $0.6000 ≤ $2.00; month $3.1000 → $3.7000 ≤ $25.00"
  },
  {
   "check": "existing_campaign",
   "status": "PASS",
   "detail": "no campaign folder exists for this design"
  },
  {
   "check": "authorization",
   "status": "PASS",
   "detail": "current run contains the exact command: AUTHORIZE LISTING RENDER 1901-093"
  },
  {
   "check": "source_copy",
   "status": "PASS",
   "detail": "exact source bytes, the handoff manifest and source-reference.json recorded in the job"
  },
  {
   "check": "scene_1",
   "status": "FAIL",
   "detail": "deterministic QA: art_identity_recomposite_match final differs from the recomputed composite in region (470, 500, 560, 540): the artwork or image was altered after compositing"
  },
  {
   "check": "failed_job",
   "status": "INFO",
   "detail": "job artifacts kept for diagnosis at /home/claude/agents/1901/shared/render-campaigns/_failed/1901-093-fixture001; no downstream-ready flag; no final campaign folder created"
  }
 ],
 "human_action_required": "Scene 1 for 1901-093 failed deterministic QA; the campaign was not published. Review the failed job artifacts."
}
```

## Verification

The skill worked if the reply is one JSON object in the shape above; no
generation call was made unless that run's user message was exactly
`AUTHORIZE LISTING RENDER <design_id>` and every live check passed; every
generation call was preceded by a budget check against both caps; every
final composite equals a fresh deterministic recomposite of its base scene,
the staged source and its recorded placement; the campaign's source copy
hashes to the Skill #6 manifest; the design folder appeared only by atomic
rename of a verified job directory; `publication_authorized` is false; and
no sheet cell, Drive file, Printify or Etsy object, or downstream system was
touched.

## Assumptions and Limits

- OpenMausBot imports `SKILL.md` only; `render.py`, `studio/`, the `.venv`
  with Pillow and `tests/` live in this repository's local clone at
  `/home/claude/agents/1901/1901-listing-studio/`. Keep the clone at the
  imported commit. Pillow is installed in that folder's own virtualenv, not
  system-wide.
- No image provider is configured on the VPS today. The OpenAI adapter
  exists and is untested live; configuring a key is a credential decision
  for Jody. Until then every authorised run ends in
  `MODEL_OR_QUALITY_BLOCK` after the read-only checks, with no spend.
- The pricing snapshot file does not exist yet; until Jody records one,
  runs end in `PRICING_UNAVAILABLE`.
- Walter still has no Sheets or Drive connector, so the live checks that
  depend on the other skills return `SOURCE_UNAVAILABLE` until access is
  granted.
- Print-area detection relies on the scene model honouring the magenta
  placeholder instruction. Scenes that do not are rejected and rerolled,
  never patched.
- Scene-content judgements (fake text, logos, construction realism) are
  listed for human review, not auto-passed; the deterministic QA proves the
  artwork's identity and placement only.
