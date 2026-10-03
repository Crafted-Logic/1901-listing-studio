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
8. **Provider, model, quality, pricing.** All read-only, no generation
   call. Credentials must be present in the runtime environment; the
   configured model must not be reported unavailable; the configured
   capability record must list high and medium and the configured size. Any
   failure → `MODEL_OR_QUALITY_BLOCK`; no model or tier is substituted. A
   pricing snapshot for exactly this provider, model and size with both
   tiers must exist (`PRICING_UNAVAILABLE` otherwise). The planned cost of
   the six images is computed from it.
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

The pricing snapshot is a JSON file maintained by Jody that identifies the
provider, the exact configured model, the size, `captured_at`, `basis`,
`currency` and `per_image_usd` by quality and size. A snapshot for a
different model or size, or missing any of those, is invalid:
`PRICING_UNAVAILABLE`. Stale pricing from another model is never reused and
no per-image cost is ever guessed.

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
output. At most 4 per render job. Each is recorded with its slot, reason,
prior failure and added cost. The renderer rejects a scene whose print area
cannot be found or is implausible and makes one controlled replacement; it
never distorts the art to rescue a scene. At 4 rerolls it stops
(`QA_FAILED` for the slot that still has no usable scene); more needs a new
human authorization.

**Prior failed jobs.** Before proposing or running, the skill lists this
design's failed jobs under `_failed/` (read-only) in `prior_failed_jobs`
and a `prior_failed_jobs` check: result, rerolls, spend and attribution.
Their spend already counts in the monthly floor; their rerolls never carry
into a new job, whose allowance is always the normal 4.

**Validator-defect retry.** A job whose rerolls were consumed by a confirmed
defect in this skill's own validation (job `4c8fda750c`, 2026-10-02: Scene 1
marker validation measured every magenta-coloured pixel in the image, so
purple scenery inflated the inferred polygon) is not a record of four bad
generations. A human may record that ruling beside the failed folder, never
inside it, as `_failed/<design_id>-<render_job_id>.validator-defect.json`:

```json
{ "design_id": "1901-093", "render_job_id": "4c8fda750c",
  "defect": "<what the validator got wrong>", "corrected_in": "<commit that fixed it>",
  "ruled_by": "<human>", "ruled_at": "<date>", "scope": "validator-defect" }
```

The skill then reports that job's attribution as `validator-defect` and
writes the attribution into the new job's cost log and expense-row notes.
That is the whole effect. The record is not a bypass: it must name that
exact job, the defect and the correcting commit, and who ruled; a record
that is incomplete, unreadable, or names another job is ignored with a
warning and the failure stays an ordinary one. The failed job stays in
`_failed/` untouched. The retry is a new job that needs its own exact
`AUTHORIZE LISTING RENDER <design_id>`, starts at 0 rerolls, is capped at
4 like any job, and pays for every call. Ordinary bad generations always
count against the cap; Walter never writes a validator-defect record.

## Scene Generation and Compositing

The scene prompt (recorded per slot in the campaign manifest) describes the
garment and environment only: the governed blank, provider and color with
accurate construction; the slot's role; design concept, season and vibe as
atmosphere words only; no text, logos, brand marks, labels or other graphics
anywhere; and one flat, solid magenta rectangle on the chest print area
whose outline follows the garment's perspective and drape, with plain
continuous shirt around it. The approved artwork is never described for
recreation.

Two separate concerns, deliberately kept apart:

- **A. Print-area geometry.** The magenta rectangle is a chroma marker used
  only to locate the print-area quadrilateral. Its own pixel values are never
  read for anything else. The marker-colour mask is split into 4-connected
  components and the chest marker is isolated before any geometry is
  measured: components smaller than the governed minimum print-area fraction
  are background noise (a purple-lit sky, neon, a sunset) and are ignored;
  among the plausible components the largest must be at least 4× every
  other, otherwise no single marker can be isolated. The quadrilateral,
  its fill ratio (≥ 0.85) and the ring around it are computed from that one
  component only; scene pixels outside it are never counted, removed or
  reconstructed. No marker, too small, too large, more than one plausible
  component, not a solid convex panel, or touching the image edge → the
  scene is unusable (reroll). The placement records the component
  statistics (`placeholder.components`).
- **B. Garment appearance under the marker.** Reconstructed from the
  surrounding shirt pixels by deterministic harmonic interpolation: the ring
  of garment just outside the marker is the boundary condition, a Laplace
  fill on a downsampled grid produces the smooth local luminance and color
  field, and it is upsampled bilinearly under the marker. If the ring is not
  believable garment the scene is rejected and rerolled; the print region is
  never flattened to a flat color. The ring is believable when it contains
  no chroma and either its luminance coefficient of variation is at most
  0.35 (the rule for every garment at mean luminance above 28), or, for a
  dark garment (ring mean luminance at most 28, where that ratio is
  scale-biased: a plain black shirt's six to nine levels of drape give 0.38
  to 0.49), its absolute luminance spread (std) is at most 9.8 and its
  high-frequency texture (mean residual after a 2 px blur, marker
  neutralised) is at most 5. Both dark-branch caps were derived from the five
  real black-shirt rings of job `4c8fda750c` (std 6.5 to 9.1, texture 2.4 to
  3.2) against mottled, striped, hard-shadowed and background-straddling
  fixtures; the spread cap is exactly what the ratio rule allows at mean 28. The
  placement records which rule admitted the ring (`ring.rule`).

The compositor (`studio/compositor.py`, Pillow only, no model call,
`COMPOSITOR_VERSION` recorded in every placement and manifest) then:

1. **removes the marker, its chroma fringe and its drawn rim.** Generated
   scenes anti-alias the marker edge over 1 to 3 px; those blended pixels
   fail the strict marker colour but are visibly magenta. The removal mask
   is the isolated component grown by at most 3 px for chroma and 5 px for
   the drawn rim, never a blind dilation:
   first one pixel per pass into 4-neighbours that a relative chroma gate
   marks as marker-tinted (both R−G and B−G above the clean garment band's
   (4 to 9 px out) mean by 6 levels or three times that band's chroma
   spread); then, ring by ring within a 5 px bound of the component, a whole
   1 px ring is absorbed when its mean luminance deviates from the clean
   band by more than max(0.5, 2.5%), which is the panel outline and glow
   the generator draws as a dark or bright band too faint for any per-pixel
   test; the first ring that does not deviate stops it (the five-ring rim
   of job `863b478926-rc1` scene 06 set the bound). Untinted, un-outlined garment and
   background pixels are never absorbed. The ring statistics and everything
   below use this mask;
2. **reconstructs the garment under it**: the harmonic (Laplace) fill on a
   downsampled grid is relaxed to convergence (largest update below 0.005,
   never a fixed iteration count) so the low-frequency field matches the
   surrounding garment, then the garment's own high-frequency texture is
   restored by quilting: the residual (pixel minus a 2 px blur) of the ring
   1 to 9 px outside the mask is copied into the interior as 6 px patches
   taken at pseudo-random ring positions, seeded from the marker-free image, and
   ramp-blended over 2 px overlaps. A pure deterministic function of the
   scene: QA recomputes it exactly;
3. **feathers the seam and checks continuity**: a glow the generator
   paints around the panel decays over 6 to 12 px, beyond the rim bound,
   so inside the mask only, over the 6 px nearest its edge, the repaired
   field ramps from the local mean of the scene's 0 to 3 px outside band
   (normalised box convolution) to its own value; scene pixels outside the
   mask are never touched. Then two checks: the reconstructed interior's
   mean luminance (mask eroded by 10 px) against the clean band 4 to 9 px
   out within `max(1.0, 6%)` levels, and the step continuity across the
   seam measured on adjacent 3 px bands (the scene's 0 to 3 px band outside
   against its 3 to 6 px band; the repaired 0 to 3 px band inside against
   the 0 to 3 px band outside), each within `max(1.0, 5%)` levels, so a
   soft lighting gradient passes and a line fails. Either failing makes the
   scene unusable (reroll; in a recomposite or scene-reuse job, failure).
   Recorded in `placement.reconstruction.continuity` and `.boundary`;
4. derives the **bounded shading map** from the low-frequency field only
   (fabric texture never prints through the ink): `shade = low / p95(low
   over the print area)`, floored at 0.70, white outside the marker.
   Opaque ink on a dark garment is modulated by the garment's large-scale
   lighting, never by its darkness: on the six 1901-093 scenes this moved
   the print's median intensity from 0.67 to 0.91 of source under the old
   `textured / max` rule to 0.76 to 0.96, with a hard floor at 0.70 instead
   of 0.58;
5. fits the art inside the marker quad preserving its aspect ratio exactly
   (never stretched), maps it by a perspective transform, multiplies the
   shading into it, and alpha-composites it over the reconstructed garment;
   the art's RGB and alpha are otherwise untouched, so opaque art stays
   opaque and anti-aliased edges blend as drawn;
6. refuses to upscale: if the fitted width exceeds the art's width →
   `RESOLUTION_BLOCK`;
7. records the placement (marker quad, art quad, ring statistics, removal
   growth, texture, continuity, shading, scale, rotation, method,
   compositor version) so QA can recompute the composite from the base
   scene, the source and the placement and compare pixel-for-pixel.

The generated base scene (with the marker) is kept beside each final
composite for audit.

## QA

Every final composite is checked before the campaign is considered
successful. Deterministic checks, computed: image size; art identity
(the final equals a fresh recomposite of base scene + approved source +
recorded placement, so spelling, internal geometry and content are preserved
by construction and any post-edit is caught); marker removed before
placement (zero chroma pixels in the reconstructed base within the
fringe-aware removal mask; chroma elsewhere in the scene is scenery); no
residual chroma leak (zero chroma pixels in the final where the marker was
and the art does not cover); **boundary continuity** (adjacent-band steps across the repair seam within
`max(1.0, 5%)`); **no marker fringe** (visibly marker-tinted
pixels, by the relative chroma gate at a 12-level margin, in the 0 to 4 px
band outside the repaired region of the final may not exceed the clean 4 to
9 px band's own rate plus 0.2% of the band, so a scene's natural chroma is
never falsely rejected); **reconstruction continuity**; **garment texture
restored**; **bounded shading** (median at most 1.0, minimum at or above
the floor); shading derived from the low-frequency reconstruction, not the
marker; no upscale; aspect preserved; placement within bounds; single
placement, no duplicate or ghost art; product specification consistent. Per image: `PASS` or
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

## Scene Reuse After a Source Change

When the approved source changes (a newly staged prepared derivative) or
the compositor changes, a **new governed render job** may reuse the six
stored base scenes of the existing reviewed package instead of generating:
`render.py run --reuse-scenes --design-id <id> --evidence … --message
"<verbatim>"`. Every governance check runs exactly as for a render (queue,
approval, source, handoff, staged source, product specification,
transparency); provider, pricing and budget checks are replaced by a
verification of the existing package (result, six finals hash-matched, six
base scenes present) and a zero-cost plan; `ALREADY_CURRENT` when the
package already has this source and compositor. The same exact command
`AUTHORIZE LISTING RENDER <design_id>` authorizes it; the proposal says
"scene-reuse job" and "zero generation calls, zero spend". No provider is
constructed. A stored scene the current compositor cannot use →
`SCENE_REUSE_FAILED`, nothing changed (no reroll without generation). On
success the existing package is superseded exactly as in a recomposite
(whole, by rename, with its `SUPERSEDED.json`), and the new manifest's
`scene_reuse` block records the reused job, every base scene's SHA-256,
the previous and new source hashes, the previous and new compositor
version and commit, the superseded paths and hashes, `generation_calls:
0` and `estimated_api_cost_usd: 0.0`; the cost log records zero images and
zero calls. History for every earlier job stays under `_superseded/`.

## Recomposite and Supersession

When the compositor is corrected after a campaign reached
`READY_FOR_HUMAN_RENDER_REVIEW`, the six stored base scenes can be
recomposited locally with no generation call and no spend. The command:

```
AUTHORIZE LISTING RECOMPOSITE <design_id>
```

Same structure rules as the render command; it is a different command and
neither authorizes the other. Any other message proposes
(`AWAITING_RECOMPOSITE_AUTHORIZATION`) and changes nothing. Run with
`render.py recomposite --design-id <id> --message "<verbatim>"`; no
provider is constructed.

The run verifies the existing package (result, six finals hash-matched, six
base scenes present), that its compositor version differs from the current
one (`ALREADY_CURRENT` otherwise), and that the package's source copy equals
both its manifest hash and the staged Skill #6 handoff (`SOURCE_MISMATCH`
otherwise). It then composites every stored base scene with the current
compositor and runs full deterministic QA in a temporary directory. Any
scene the corrected compositor cannot use → `RECOMPOSITE_FAILED`, nothing
moved; there is no reroll in a recomposite.

Supersession is two renames, never an overwrite or a delete:

```
<campaign root>/_superseded/<design_id>-<original job>/      ← the whole original package, byte-identical
<campaign root>/_superseded/<design_id>-<original job>.SUPERSEDED.json
<campaign root>/<design_id>/                                  ← the recomposited package, job <original job>-rc<N>
```

The `SUPERSEDED.json` record names the original job, the superseding job,
the time, the reason, the original result, the original manifest hash and
the original final hashes. The new manifest carries a `recomposite` block:
original job, reason, superseded package and record paths, superseded
manifest hash, original final hashes, the SHA-256 of every base scene
reused, the source hash, `generation_calls: 0`, `estimated_api_cost_usd:
0.0`, the original job's cost and reroll count; and `rendering` records the
compositor version and commit. `source/recomposite-reference.json` repeats
the lineage; the cost log records zero images, zero calls, zero spend. If
the second rename fails the original is put back. The new package is for
human review like any other; `publication_authorized` stays `false`.

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

## Provider Configuration and Preflight

The image model is never hard-coded. Production configuration (no secrets)
lives at `/home/claude/.config/1901-listing-studio/provider.json`:

```json
{
  "provider": "openai",
  "model": "<the configured image model id, verified current in the provider's docs>",
  "size": "1024x1024",
  "capabilities": { "qualities": ["low", "medium", "high"], "sizes": ["1024x1024", "1536x1024", "1024x1536"],
                    "basis": "<docs URL and date where these capabilities were verified>" },
  "pricing_path": "/home/claude/.config/1901-listing-studio/pricing.json"
}
```

Credentials come only from the runtime environment, read at call time,
never stored, printed or logged, and never committed. The adapter reads
`OPENAI_API_KEY` first and then `LISTING_STUDIO_OPENAI_API_KEY`. The second
name exists because OpenMausBot's Claude launcher deliberately deletes
`OPENAI_API_KEY`, along with every other provider-credential name, from a
bot's environment so that a foreign key can never change a CLI's billing
identity; on this VPS the key therefore reaches Walter only under the
harness-safe name, supplied through the openmausbot service's root-owned
environment file. Preflight reports which name was found, never the value. The adapter verifies at runtime, without any paid call,
that credentials are present, that the configured model is available to
them (a free model-metadata request), and that the configured capability
record lists both governed quality tiers and the configured size. Anything
missing → `MODEL_OR_QUALITY_BLOCK`; no other model or tier is ever chosen
silently. The exact configured model is recorded in the proposal
(`rendering`), the campaign manifest, the cost log, the pricing snapshot
and every usage record entry.

Read-only preflight, no generation call, tells Walter where things stand:

```bash
cd /home/claude/agents/1901/1901-listing-studio && .venv/bin/python render.py preflight
```

It reports: provider configured, model configured, credentials available
(yes/no only) and which variable name supplied them, model available,
quality tiers available, size supported, pricing snapshot available and
which model it is for.

## Running the Renderer

The renderer and its provider adapter live in this skill's local clone
(OpenMausBot imports only `SKILL.md`). Walter gathers the live evidence with
the other skills, writes it to a JSON file in its working folder, then runs
one command; the renderer performs the whole decision chain and prints the
output object.

```bash
cd /home/claude/agents/1901/1901-listing-studio
.venv/bin/python render.py run --design-id 1901-093 --evidence /path/evidence.json \
  --message "<the user's message, verbatim>"
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
The provider and model come from the configuration file above; with no
valid configuration the renderer reports `MODEL_OR_QUALITY_BLOCK` and does
nothing. `--mock` is for fixtures only and never for production.

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
  "rendering": { "provider": "", "model": "", "size": "", "quality_mix": { "high": 2, "medium": 4 }, "mode": "composited_fidelity" },
  "authorization": { "received": false, "evidence": "" },
  "prior_failed_jobs": [ { "render_job_id": "", "folder": "", "result": "", "rerolls": 0, "estimated_api_cost_usd": 0, "attribution": "generation | validator-defect", "validator_defect": null, "warnings": [] } ],
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
| `AWAITING_RECOMPOSITE_AUTHORIZATION` | no | none | Recomposite proposed; the exact command is not in this run |
| `ALREADY_CURRENT` | no | none | The package was composited with the current compositor |
| `CAMPAIGN_NOT_FOUND` | no | none | No package to recomposite |
| `RECOMPOSITE_FAILED` | no | none | A stored scene cannot be composited by the current compositor; original untouched |
| `SCENE_REUSE_FAILED` | no | none | Scene-reuse job: a stored scene cannot be composited; original untouched |

## Pitfalls

- **A faint magenta outline around the print, or a flat dark rectangle
  behind it.** Job `863b478926`, 2026-10-02: the pre-correction compositor
  left the anti-aliased marker fringe in place and filled the print area
  with a texture-free, under-converged field. Corrected by fringe-aware
  removal, converged reconstruction, quilted texture and the fringe and
  continuity QA checks; a reviewed package is repaired by
  `AUTHORIZE LISTING RECOMPOSITE <design_id>`, never by regenerating.

- **The marker was clearly solid but the fill ratio came out 0.3.** Before
  2026-10-02 this was the validator measuring purple scenery as marker. It
  now isolates the connected chest marker first; the scene's other magenta
  pixels are ignored. If a scene still fails, read the reason: too small,
  more than one plausible component, not a solid panel, touching the edge,
  or the separate garment-ring check.
- **A faint line or soft rectangle at the panel edge after the 2026-10-02
  correction.** Two sources, diagnosed on job `863b478926-rc1`: the
  generator's drawn panel outline and glow just outside the marker (now
  removed ring by ring within 5 px and feathered inside), and residual
  alpha haze in the prepared derivative itself (alpha 1 to 31 over its
  whole extent), which the compositor renders faithfully and never clips:
  that is fixed by a cleaned, human-approved derivative staged through
  Skill #6 and a scene-reuse job.
- **The job failed on a validator defect; reroll it for free.** There is no
  free job. A human records the ruling beside the failed folder, and a new
  job runs under a fresh exact authorization with the normal cap and the
  normal budget.

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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": null
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "prior_failed_jobs": [],
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "size": "1024x1024",
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
   "detail": "mock / mock-image-1: credentials present, model verified available, high and medium at 1024x1024 per the configured capability record"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 / 1024x1024 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per image (fixture pricing for tests)"
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
 "human_action_required": "No generation call made and no campaign files created. 1901-093 is eligible: source 1901-093-B.png (Drive id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, sha256 5211ed2ff15b…) staged at /home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png; product Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper; six scenes (2 high, 4 medium) at 1024x1024 on mock / mock-image-1 at an estimated $0.6000, month $3.1000 → $3.7000; output /home/claude/agents/1901/shared/render-campaigns/1901-093. To authorize exactly this render job, send exactly: AUTHORIZE LISTING RENDER 1901-093"
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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": null
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE LISTING RENDER 1901-093"
 },
 "prior_failed_jobs": [],
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "size": "1024x1024",
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
    "model": "mock-image-1",
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
    "model": "mock-image-1",
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
    "model": "mock-image-1",
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
    "model": "mock-image-1",
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
    "model": "mock-image-1",
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
    "model": "mock-image-1",
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
   "detail": "mock / mock-image-1: credentials present, model verified available, high and medium at 1024x1024 per the configured capability record"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 / 1024x1024 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per image (fixture pricing for tests)"
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
   "detail": "hero_lifestyle (high) generated, composited at scale 0.205, deterministic QA PASS"
  },
  {
   "check": "scene_2",
   "status": "PASS",
   "detail": "secondary_lifestyle_story (high) generated, composited at scale 0.2336, deterministic QA PASS"
  },
  {
   "check": "scene_3",
   "status": "PASS",
   "detail": "travel_packing (medium) generated, composited at scale 0.1464, deterministic QA PASS"
  },
  {
   "check": "scene_4",
   "status": "PASS",
   "detail": "editorial_flat_lay (medium) generated, composited at scale 0.2493, deterministic QA PASS"
  },
  {
   "check": "scene_5",
   "status": "PASS",
   "detail": "folded_garment_detail (medium) generated, composited at scale 0.175, deterministic QA PASS"
  },
  {
   "check": "scene_6",
   "status": "PASS",
   "detail": "product_construction_detail (medium) generated, composited at scale 0.1464, deterministic QA PASS"
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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": null
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "prior_failed_jobs": [],
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "size": "1024x1024",
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
   "detail": "mock / mock-image-1: credentials present, model verified available, high and medium at 1024x1024 per the configured capability record"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 / 1024x1024 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per image (fixture pricing for tests)"
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
 "human_action_required": "No generation call made and no campaign files created. 1901-093 is eligible: source 1901-093-B.png (Drive id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, sha256 5211ed2ff15b…) staged at /home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png; product Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper; six scenes (2 high, 4 medium) at 1024x1024 on mock / mock-image-1 at an estimated $0.6000, month $3.1000 → $3.7000; output /home/claude/agents/1901/shared/render-campaigns/1901-093. To authorize exactly this render job, send exactly: AUTHORIZE LISTING RENDER 1901-093"
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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": null
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE LISTING RENDER 1901-093"
 },
 "prior_failed_jobs": [],
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "size": "1024x1024",
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
    "model": "mock-image-1",
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
    "model": "mock-image-1",
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
    "model": "mock-image-1",
    "quality": "high",
    "size": "1024x1024",
    "estimated_cost_usd": 0.2,
    "reroll": true,
    "reason": "scene 2 unusable: no print-area marker found in the scene",
    "usage": {
     "images": 1,
     "quality": "high",
     "size": "1024x1024",
     "mock": true
    }
   },
   {
    "slot": 3,
    "model": "mock-image-1",
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
    "model": "mock-image-1",
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
    "model": "mock-image-1",
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
    "model": "mock-image-1",
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
   "detail": "mock / mock-image-1: credentials present, model verified available, high and medium at 1024x1024 per the configured capability record"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 / 1024x1024 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per image (fixture pricing for tests)"
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
   "detail": "hero_lifestyle (high) generated, composited at scale 0.205, deterministic QA PASS"
  },
  {
   "check": "scene_2",
   "status": "INFO",
   "detail": "attempt 1 rejected (no print-area marker found in the scene); one controlled reroll (reroll 1 of 4); the art is never distorted to fit a bad scene"
  },
  {
   "check": "scene_2",
   "status": "PASS",
   "detail": "secondary_lifestyle_story (high) generated, composited at scale 0.2336, deterministic QA PASS after 1 reroll(s)"
  },
  {
   "check": "scene_3",
   "status": "PASS",
   "detail": "travel_packing (medium) generated, composited at scale 0.1464, deterministic QA PASS"
  },
  {
   "check": "scene_4",
   "status": "PASS",
   "detail": "editorial_flat_lay (medium) generated, composited at scale 0.2493, deterministic QA PASS"
  },
  {
   "check": "scene_5",
   "status": "PASS",
   "detail": "folded_garment_detail (medium) generated, composited at scale 0.175, deterministic QA PASS"
  },
  {
   "check": "scene_6",
   "status": "PASS",
   "detail": "product_construction_detail (medium) generated, composited at scale 0.1464, deterministic QA PASS"
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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": null
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE LISTING RENDER 1901-093"
 },
 "prior_failed_jobs": [],
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "size": "1024x1024",
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
    "model": "mock-image-1",
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
    "model": "mock-image-1",
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
    "model": "mock-image-1",
    "quality": "high",
    "size": "1024x1024",
    "estimated_cost_usd": 0.2,
    "reroll": true,
    "reason": "scene 2 unusable: no print-area marker found in the scene",
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
   "detail": "mock / mock-image-1: credentials present, model verified available, high and medium at 1024x1024 per the configured capability record"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 / 1024x1024 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per image (fixture pricing for tests)"
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
   "detail": "hero_lifestyle (high) generated, composited at scale 0.205, deterministic QA PASS"
  },
  {
   "check": "scene_2",
   "status": "INFO",
   "detail": "attempt 1 rejected (no print-area marker found in the scene); one controlled reroll (reroll 1 of 4); the art is never distorted to fit a bad scene"
  },
  {
   "check": "scene_2",
   "status": "PASS",
   "detail": "secondary_lifestyle_story (high) generated, composited at scale 0.2336, deterministic QA PASS after 1 reroll(s)"
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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": null
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "prior_failed_jobs": [],
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
   "detail": "mock / mock-image-1: credentials present, model verified available, high and medium at 1024x1024 per the configured capability record"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 / 1024x1024 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per image (fixture pricing for tests)"
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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": null
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "prior_failed_jobs": [],
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
   "detail": "mock / mock-image-1: credentials present, model verified available, high and medium at 1024x1024 per the configured capability record"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 / 1024x1024 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per image (fixture pricing for tests)"
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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": null
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "prior_failed_jobs": [],
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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": null
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "prior_failed_jobs": [],
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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": null
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "prior_failed_jobs": [],
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
   "detail": "mock / mock-image-1: credentials present, model verified available, high and medium at 1024x1024 per the configured capability record"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 / 1024x1024 captured 2026-10-01T00:00:00Z: high $2.5000, medium $0.0500 per image (fixture pricing for tests)"
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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": null
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "prior_failed_jobs": [],
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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": null
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "prior_failed_jobs": [],
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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": null
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE LISTING RENDER 1901-093"
 },
 "prior_failed_jobs": [],
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "size": "1024x1024",
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
    "model": "mock-image-1",
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
   "detail": "mock / mock-image-1: credentials present, model verified available, high and medium at 1024x1024 per the configured capability record"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 / 1024x1024 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per image (fixture pricing for tests)"
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

### N. Residual chroma leak: QA_FAILED

The reconstructed base still held marker pixels (simulated); deterministic QA refused the image.

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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": null
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE LISTING RENDER 1901-093"
 },
 "prior_failed_jobs": [],
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "size": "1024x1024",
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
    "model": "mock-image-1",
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
   "detail": "mock / mock-image-1: credentials present, model verified available, high and medium at 1024x1024 per the configured capability record"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 / 1024x1024 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per image (fixture pricing for tests)"
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
   "detail": "deterministic QA: marker_removed_before_placement 169 marker pixels remain in the reconstructed base within the fringe-aware removal mask (0 fringe pixels added to the component); scene pixels outside it are not touched; no_residual_chroma_leak 169 chroma pixels remain where the marker was and the art does not cover"
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

### O. Prior failed job ruled a validator defect: proposal with attribution

`_failed/1901-093-oldjob0001/` holds a job that failed on the marker-validation defect, and a human recorded `1901-093-oldjob0001.validator-defect.json` beside it. The proposal lists it with attribution `validator-defect`; the new job still needs its own exact command, starts at 0 rerolls, and its spend counts.

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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": null
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "prior_failed_jobs": [
  {
   "render_job_id": "oldjob0001",
   "folder": "/home/claude/agents/1901/shared/render-campaigns/_failed/1901-093-oldjob0001",
   "result": "QA_FAILED",
   "rerolls": 4,
   "estimated_api_cost_usd": 0.2884,
   "attribution": "validator-defect",
   "validator_defect": {
    "design_id": "1901-093",
    "render_job_id": "oldjob0001",
    "defect": "Scene 1 marker validation combined every magenta-coloured pixel in the image; background pixels inflated the inferred polygon (fill 0.23-0.37 vs 0.99-1.02 for the connected marker)",
    "corrected_in": "<commit>",
    "ruled_by": "Jody Clements (Architect)",
    "ruled_at": "2026-10-02"
   },
   "warnings": []
  }
 ],
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "size": "1024x1024",
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
   "proposal only; no generation call made",
   "retry after validator defect in job oldjob0001 (Scene 1 marker validation combined every magenta-coloured pixel in the image; background pixels inflated the inferred polygon (fill 0.23-0.37 vs 0.99-1.02 for the connected marker); corrected in <commit>; ruled by Jody Clements (Architect) on 2026-10-02): that job's 4 reroll(s) were caused by the defect, not by generation; this job's reroll allowance is the normal 4 and its spend counts as usual"
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
   "detail": "mock / mock-image-1: credentials present, model verified available, high and medium at 1024x1024 per the configured capability record"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "mock / mock-image-1 / 1024x1024 captured 2026-10-01T00:00:00Z: high $0.2000, medium $0.0500 per image (fixture pricing for tests)"
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
   "check": "prior_failed_jobs",
   "status": "INFO",
   "detail": "oldjob0001: QA_FAILED, 4 reroll(s), $0.2884, attribution validator-defect (corrected in <commit>); artifacts preserved under _failed; a new job needs its own exact authorization"
  },
  {
   "check": "authorization",
   "status": "FAIL",
   "detail": "the current run does not contain the exact command AUTHORIZE LISTING RENDER 1901-093; ordinary requests and vague confirmations never authorize rendering"
  }
 ],
 "human_action_required": "No generation call made and no campaign files created. 1901-093 is eligible: source 1901-093-B.png (Drive id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, sha256 5211ed2ff15b…) staged at /home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png; product Comfort Colors 1717 Garment-Dyed Heavyweight T-Shirt / Printify / Monster Digital / Pepper; six scenes (2 high, 4 medium) at 1024x1024 on mock / mock-image-1 at an estimated $0.6000, month $3.1000 → $3.7000; output /home/claude/agents/1901/shared/render-campaigns/1901-093. To authorize exactly this render job, send exactly: AUTHORIZE LISTING RENDER 1901-093"
}
```

### P. Recomposite proposal: AWAITING_RECOMPOSITE_AUTHORIZATION

Input: `Recomposite the 1901-093 campaign with the corrected compositor.` A reviewed package rendered by an older compositor exists; nothing is changed.

```json
{
 "design_id": "1901-093",
 "result": "AWAITING_RECOMPOSITE_AUTHORIZATION",
 "recomposite_performed": false,
 "render_job_id": "origjob001-rc1",
 "supersedes": {
  "render_job_id": "origjob001",
  "folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "manifest_sha256": "c2328a8d581182396be1e708aa81dd544286931e476bbd98e80ceccd90017e16",
  "original_result": "READY_FOR_HUMAN_RENDER_REVIEW",
  "original_estimated_api_cost_usd": 0.6,
  "original_final_sha256": {
   "01-hero.png": "fa30c1591b5777b7745110bd2ef5122608de0778e03ae9266291ccebceffaf12",
   "02-story.png": "31c84a032b78074760a5a7b24b237ff6e0a3e4b3006ca6675910d42d0a71048a",
   "03-travel.png": "39973e01fc6360f45c538412fc792c2b53e6bae4535e9aacc796d44358a95d6d",
   "04-flatlay.png": "f6c2f23df909b611cf106477e522b0c332dd38db67420616086f08ab403abf5b",
   "05-folded.png": "e7aedadfdee038fbddb9cfe57f2d7b7b79c3f36fe3511dc0c17db5e9bcffd271",
   "06-detail.png": "2cf9da631c09a9c021076566b891faf74f9d80b59a69391c4c3678e9648edab2"
  }
 },
 "generation_calls": 0,
 "estimated_api_cost_usd": 0.0,
 "compositor": {
  "version": "2026-10-03.5",
  "commit": "4a18803ddfd1"
 },
 "timestamp": "2026-10-01T02:00:00Z",
 "campaign": {
  "root": "/home/claude/agents/1901/shared/render-campaigns/",
  "design_folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "manifest_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/manifest.json",
  "superseded_folder": "/home/claude/agents/1901/shared/render-campaigns/_superseded/1901-093-origjob001",
  "superseded_record": "/home/claude/agents/1901/shared/render-campaigns/_superseded/1901-093-origjob001.SUPERSEDED.json"
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "warnings": [],
 "checks": [
  {
   "check": "existing_campaign",
   "status": "PASS",
   "detail": "job origjob001: six finals hash-verified, six base scenes present, result READY_FOR_HUMAN_RENDER_REVIEW"
  },
  {
   "check": "compositor_version",
   "status": "PASS",
   "detail": "package compositor 'old' → current 2026-10-03.5 (commit 4a18803ddfd1)"
  },
  {
   "check": "source",
   "status": "PASS",
   "detail": "exact approved source 1901-093-B.png (sha256 5211ed2ff15b…) equals the staged handoff; it will be reused byte-for-byte"
  },
  {
   "check": "base_scenes",
   "status": "PASS",
   "detail": "six stored base scenes will be reused; no generation call: 01-hero-base.png 70c1fcb2, 02-story-base.png 62496122, 03-travel-base.png 81a6c072, 04-flatlay-base.png 73da421d, 05-folded-base.png 9960602a, 06-detail-base.png f3d8cf62"
  },
  {
   "check": "authorization",
   "status": "FAIL",
   "detail": "the current run does not contain the exact command AUTHORIZE LISTING RECOMPOSITE 1901-093; nothing was changed"
  }
 ],
 "human_action_required": "Nothing changed. Job origjob001 for 1901-093 would be recomposited locally with compositor 2026-10-03.5 from its six stored base scenes and the exact source (sha256 5211ed2ff15b…), with no generation call and no spend, as job origjob001-rc1; the current package would move whole to /home/claude/agents/1901/shared/render-campaigns/_superseded/1901-093-origjob001 with 1901-093-origjob001.SUPERSEDED.json beside it, and the new package would be published at /home/claude/agents/1901/shared/render-campaigns/1901-093 for human review. To authorize exactly this, send exactly: AUTHORIZE LISTING RECOMPOSITE 1901-093"
}
```

### Q. Authorised recomposite: READY_FOR_HUMAN_RENDER_REVIEW

Input: `AUTHORIZE LISTING RECOMPOSITE 1901-093`. The original package moved whole to `_superseded/`, the new package published in its place; zero generation calls, zero spend.

```json
{
 "design_id": "1901-093",
 "result": "READY_FOR_HUMAN_RENDER_REVIEW",
 "recomposite_performed": true,
 "render_job_id": "origjob001-rc1",
 "supersedes": {
  "render_job_id": "origjob001",
  "folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "manifest_sha256": "c2328a8d581182396be1e708aa81dd544286931e476bbd98e80ceccd90017e16",
  "original_result": "READY_FOR_HUMAN_RENDER_REVIEW",
  "original_estimated_api_cost_usd": 0.6,
  "original_final_sha256": {
   "01-hero.png": "fa30c1591b5777b7745110bd2ef5122608de0778e03ae9266291ccebceffaf12",
   "02-story.png": "31c84a032b78074760a5a7b24b237ff6e0a3e4b3006ca6675910d42d0a71048a",
   "03-travel.png": "39973e01fc6360f45c538412fc792c2b53e6bae4535e9aacc796d44358a95d6d",
   "04-flatlay.png": "f6c2f23df909b611cf106477e522b0c332dd38db67420616086f08ab403abf5b",
   "05-folded.png": "e7aedadfdee038fbddb9cfe57f2d7b7b79c3f36fe3511dc0c17db5e9bcffd271",
   "06-detail.png": "2cf9da631c09a9c021076566b891faf74f9d80b59a69391c4c3678e9648edab2"
  }
 },
 "generation_calls": 0,
 "estimated_api_cost_usd": 0.0,
 "compositor": {
  "version": "2026-10-03.5",
  "commit": "4a18803ddfd1"
 },
 "timestamp": "2026-10-01T02:00:00Z",
 "campaign": {
  "root": "/home/claude/agents/1901/shared/render-campaigns/",
  "design_folder": "/home/claude/agents/1901/shared/render-campaigns/1901-093",
  "manifest_path": "/home/claude/agents/1901/shared/render-campaigns/1901-093/manifest.json",
  "superseded_folder": "/home/claude/agents/1901/shared/render-campaigns/_superseded/1901-093-origjob001",
  "superseded_record": "/home/claude/agents/1901/shared/render-campaigns/_superseded/1901-093-origjob001.SUPERSEDED.json"
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE LISTING RECOMPOSITE 1901-093"
 },
 "warnings": [],
 "checks": [
  {
   "check": "existing_campaign",
   "status": "PASS",
   "detail": "job origjob001: six finals hash-verified, six base scenes present, result READY_FOR_HUMAN_RENDER_REVIEW"
  },
  {
   "check": "compositor_version",
   "status": "PASS",
   "detail": "package compositor 'old' → current 2026-10-03.5 (commit 4a18803ddfd1)"
  },
  {
   "check": "source",
   "status": "PASS",
   "detail": "exact approved source 1901-093-B.png (sha256 5211ed2ff15b…) equals the staged handoff; it will be reused byte-for-byte"
  },
  {
   "check": "base_scenes",
   "status": "PASS",
   "detail": "six stored base scenes will be reused; no generation call: 01-hero-base.png 70c1fcb2, 02-story-base.png 62496122, 03-travel-base.png 81a6c072, 04-flatlay-base.png 73da421d, 05-folded-base.png 9960602a, 06-detail-base.png f3d8cf62"
  },
  {
   "check": "authorization",
   "status": "PASS",
   "detail": "current run contains the exact command: AUTHORIZE LISTING RECOMPOSITE 1901-093"
  },
  {
   "check": "scene_1",
   "status": "PASS",
   "detail": "hero_lifestyle recomposited from the stored base scene at scale 0.2079, deterministic QA PASS"
  },
  {
   "check": "scene_2",
   "status": "PASS",
   "detail": "secondary_lifestyle_story recomposited from the stored base scene at scale 0.2364, deterministic QA PASS"
  },
  {
   "check": "scene_3",
   "status": "PASS",
   "detail": "travel_packing recomposited from the stored base scene at scale 0.1493, deterministic QA PASS"
  },
  {
   "check": "scene_4",
   "status": "PASS",
   "detail": "editorial_flat_lay recomposited from the stored base scene at scale 0.2521, deterministic QA PASS"
  },
  {
   "check": "scene_5",
   "status": "PASS",
   "detail": "folded_garment_detail recomposited from the stored base scene at scale 0.1779, deterministic QA PASS"
  },
  {
   "check": "scene_6",
   "status": "PASS",
   "detail": "product_construction_detail recomposited from the stored base scene at scale 0.1493, deterministic QA PASS"
  },
  {
   "check": "manifest",
   "status": "PASS",
   "detail": "qa.json, contact-sheet.png, cost-log.json (zero generation, zero spend) and manifest.json with the recomposite block written"
  },
  {
   "check": "supersession",
   "status": "PASS",
   "detail": "job origjob001 moved whole to /home/claude/agents/1901/shared/render-campaigns/_superseded/1901-093-origjob001 (manifest sha256 unchanged) with 1901-093-origjob001.SUPERSEDED.json beside it; job origjob001-rc1 published at /home/claude/agents/1901/shared/render-campaigns/1901-093"
  },
  {
   "check": "package_verification",
   "status": "PASS",
   "detail": "20 files present, six finals hash-verified, six base scenes byte-identical to the superseded package, publication_authorized=false, generation_calls=0"
  }
 ],
 "human_action_required": null
}
```

### R. Scene-reuse proposal after a source change: AWAITING_RENDER_AUTHORIZATION

Input: `Render the listing campaign for 1901-093.` with `--reuse-scenes`. The staged handoff now carries a new approved source; the existing reviewed package's six base scenes would be reused with zero generation calls.

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
  "sha256": "4ab3e6002affe17f10ed1a38e0f025dabd76b546f9606a3e9bd2781269a6c9d8",
  "staged_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
 },
 "product": {
  "blank": "Unisex Heavy Cotton Tee",
  "provider": "Printify Choice",
  "color": "Black",
  "spec_source": "fixture"
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
  "estimated_job_cost_usd": 0.0,
  "monthly_recorded_cost_usd": 3.1,
  "projected_monthly_cost_usd": 3.1,
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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": {
   "from_render_job_id": "genjob0001",
   "base_scenes_reused": {
    "01-hero-base.png": "4fa17ed5af2bd925014ee8b217b45adac8a0dd45283744b04f41b03d0af3bf41",
    "02-story-base.png": "6249612260907bd27f41f10ca8978301871191f4396ef69e7432fe11702965c7",
    "03-travel-base.png": "76254e04492d8a731a0e2ee0d84ca1d9813a17d6ce329bef95e5eee2ff216e09",
    "04-flatlay-base.png": "2f2e9395ab16ebb810fa4329325b34d33ae371b2b095d90f255ab332b0e297de",
    "05-folded-base.png": "9c06d6a0159824b004960a3b147bd4ff2c7efcbb55bd6f1a56a29ffbd31d2fc1",
    "06-detail-base.png": "e2f4ef7222f9fa9e4b17ed0d6ba7b9dd6388866f2bf073c652b339c7ecf94617"
   },
   "previous_source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
   "previous_compositor_version": "2026-10-03.5",
   "generation_calls": 0
  }
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "prior_failed_jobs": [],
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "4ab3e6002affe17f10ed1a38e0f025dabd76b546f9606a3e9bd2781269a6c9d8",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "size": "1024x1024",
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
  "estimated_api_cost_usd": 0.0,
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
   "detail": "Unisex Heavy Cotton Tee / Printify Choice / Black from fixture"
  },
  {
   "check": "scene_reuse",
   "status": "PASS",
   "detail": "six base scenes of job genjob0001 verified and will be reused (mock / mock-image-1, 1024x1024); previous source 5211ed2ff15b… → 4ab3e6002aff…, compositor '2026-10-03.5' → 2026-10-03.5; no generation call"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "scene reuse: no generation call, no per-image cost"
  },
  {
   "check": "budget",
   "status": "PASS",
   "detail": "planned campaign $0.0000 ≤ $2.00; month $3.1000 → $3.1000 ≤ $25.00"
  },
  {
   "check": "existing_campaign",
   "status": "INFO",
   "detail": "existing package (job genjob0001) will be superseded whole by this job; nothing is overwritten"
  },
  {
   "check": "authorization",
   "status": "FAIL",
   "detail": "the current run does not contain the exact command AUTHORIZE LISTING RENDER 1901-093; ordinary requests and vague confirmations never authorize rendering"
  }
 ],
 "human_action_required": "No generation call made and no campaign files created. 1901-093 is eligible for a scene-reuse job: source 1901-093-B.png (Drive id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, sha256 4ab3e6002aff…) staged at /home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png; product Unisex Heavy Cotton Tee / Printify Choice / Black; the six base scenes of job genjob0001 reused with compositor 2026-10-03.5, zero generation calls, zero spend; the existing package would move whole to _superseded and the new job would be published at /home/claude/agents/1901/shared/render-campaigns/1901-093. To authorize exactly this job, send exactly: AUTHORIZE LISTING RENDER 1901-093"
}
```

### S. Authorised scene-reuse job: READY_FOR_HUMAN_RENDER_REVIEW

Input: `AUTHORIZE LISTING RENDER 1901-093` with `--reuse-scenes`. New job id, new source hash, six scenes reused and hashed in `scene_reuse`, original package superseded whole.

```json
{
 "design_id": "1901-093",
 "result": "READY_FOR_HUMAN_RENDER_REVIEW",
 "render_performed": true,
 "render_job_id": "reusejob01",
 "timestamp": "2026-10-01T02:00:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "filename": "1901-093-B.png",
  "sha256": "4ab3e6002affe17f10ed1a38e0f025dabd76b546f9606a3e9bd2781269a6c9d8",
  "staged_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
 },
 "product": {
  "blank": "Unisex Heavy Cotton Tee",
  "provider": "Printify Choice",
  "color": "Black",
  "spec_source": "fixture"
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
  "estimated_job_cost_usd": 0.0,
  "monthly_recorded_cost_usd": 3.1,
  "projected_monthly_cost_usd": 3.1,
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
 "rendering": {
  "provider": "mock",
  "model": "mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "mode": "composited_fidelity",
  "compositor_version": "2026-10-03.5",
  "scene_reuse": {
   "from_render_job_id": "genjob0001",
   "base_scenes_reused": {
    "01-hero-base.png": "4fa17ed5af2bd925014ee8b217b45adac8a0dd45283744b04f41b03d0af3bf41",
    "02-story-base.png": "6249612260907bd27f41f10ca8978301871191f4396ef69e7432fe11702965c7",
    "03-travel-base.png": "76254e04492d8a731a0e2ee0d84ca1d9813a17d6ce329bef95e5eee2ff216e09",
    "04-flatlay-base.png": "2f2e9395ab16ebb810fa4329325b34d33ae371b2b095d90f255ab332b0e297de",
    "05-folded-base.png": "9c06d6a0159824b004960a3b147bd4ff2c7efcbb55bd6f1a56a29ffbd31d2fc1",
    "06-detail-base.png": "e2f4ef7222f9fa9e4b17ed0d6ba7b9dd6388866f2bf073c652b339c7ecf94617"
   },
   "previous_source_sha256": "5211ed2ff15b370ae478caafe34bb2d55abb60a4fdd8f79521af2a8d416f2916",
   "previous_compositor_version": "2026-10-03.5",
   "generation_calls": 0
  }
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE LISTING RENDER 1901-093"
 },
 "prior_failed_jobs": [],
 "proposed_expense_log_row": {
  "design_id": "1901-093",
  "model": "mock/mock-image-1",
  "size": "1024x1024",
  "quality_mix": {
   "high": 2,
   "medium": 4
  },
  "source_drive_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "source_sha256": "4ab3e6002affe17f10ed1a38e0f025dabd76b546f9606a3e9bd2781269a6c9d8",
  "pricing_snapshot": {
   "provider": "mock",
   "model": "mock-image-1",
   "size": "1024x1024",
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
  "render_job_id": "reusejob01",
  "started_at": "2026-10-01T02:00:00Z",
  "completed_at": "2026-10-01T02:00:00Z",
  "images_generated": 0,
  "rerolls": 0,
  "usage_record": [],
  "estimated_api_cost_usd": 0.0,
  "job_status": "COMPLETED",
  "budget_flag": "OK",
  "notes": [
   "scene reuse from job genjob0001: no generation call; no spend"
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
   "detail": "Unisex Heavy Cotton Tee / Printify Choice / Black from fixture"
  },
  {
   "check": "scene_reuse",
   "status": "PASS",
   "detail": "six base scenes of job genjob0001 verified and will be reused (mock / mock-image-1, 1024x1024); previous source 5211ed2ff15b… → 4ab3e6002aff…, compositor '2026-10-03.5' → 2026-10-03.5; no generation call"
  },
  {
   "check": "pricing",
   "status": "PASS",
   "detail": "scene reuse: no generation call, no per-image cost"
  },
  {
   "check": "budget",
   "status": "PASS",
   "detail": "planned campaign $0.0000 ≤ $2.00; month $3.1000 → $3.1000 ≤ $25.00"
  },
  {
   "check": "existing_campaign",
   "status": "INFO",
   "detail": "existing package (job genjob0001) will be superseded whole by this job; nothing is overwritten"
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
   "detail": "hero_lifestyle (high) generated, composited at scale 0.205, deterministic QA PASS"
  },
  {
   "check": "scene_2",
   "status": "PASS",
   "detail": "secondary_lifestyle_story (high) generated, composited at scale 0.2364, deterministic QA PASS"
  },
  {
   "check": "scene_3",
   "status": "PASS",
   "detail": "travel_packing (medium) generated, composited at scale 0.1464, deterministic QA PASS"
  },
  {
   "check": "scene_4",
   "status": "PASS",
   "detail": "editorial_flat_lay (medium) generated, composited at scale 0.2521, deterministic QA PASS"
  },
  {
   "check": "scene_5",
   "status": "PASS",
   "detail": "folded_garment_detail (medium) generated, composited at scale 0.175, deterministic QA PASS"
  },
  {
   "check": "scene_6",
   "status": "PASS",
   "detail": "product_construction_detail (medium) generated, composited at scale 0.1464, deterministic QA PASS"
  },
  {
   "check": "manifest",
   "status": "PASS",
   "detail": "qa.json, contact-sheet.png, cost-log.json and manifest.json written"
  },
  {
   "check": "supersession",
   "status": "PASS",
   "detail": "job genjob0001 moved whole to /home/claude/agents/1901/shared/render-campaigns/_superseded/1901-093-genjob0001 (manifest sha256 unchanged) with 1901-093-genjob0001.SUPERSEDED.json beside it"
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

- **Source edge matte, known limitation (stable as of 2026-10-03).** The
  compositor renders the prepared derivative's semi-transparent edge
  pixels exactly as drawn and never modifies source alpha or RGB. A
  derivative whose transparency prep left a light edge matte (the approved
  v2 of 1901-093 carries a 2 to 4 px band, mean luminance 156 against
  content of 85) or a residual alpha haze shows a pale fringe or faint
  rectangle over a dark garment. That is corrected only by a cleaned,
  human-approved derivative staged through Skill #6 (proposals v3 and v4
  for 1901-093 exist under `render-handoffs/_proposed/`, built by
  `tools/alpha_clean.py` and `tools/defringe.py`), followed by a
  scene-reuse job. No further edge processing is planned in this skill.
- **Dark-garment ring rule, known limits.** On a near-black garment a
  hard-edged shadow of up to about 14 luminance levels in the ring is
  statistically indistinguishable from legitimate drape (a real crease in
  one of the `4c8fda750c` rings scores higher on every edge metric tried),
  so it is admitted; the human checks `realistic_fold_interaction` and
  `plausible_artwork_placement` remain the control. Hard shadows of 27
  levels or more, random mottle of ±12 or more, stripes and background
  intrusion are rejected. The coefficient-of-variation rule above mean 28
  is unchanged by this review and remains lenient on midtone and light
  garments (random ±20 mottle or 12 px stripes on a mid-grey shirt pass
  it); that is pre-existing behaviour, recorded here, not widened.

- OpenMausBot imports `SKILL.md` only; `render.py`, `studio/`, the `.venv`
  with Pillow and `tests/` live in this repository's local clone at
  `/home/claude/agents/1901/1901-listing-studio/`. Keep the clone at the
  imported commit. Pillow is installed in that folder's own virtualenv, not
  system-wide.
- No provider configuration, credential, or pricing snapshot exists on the
  VPS today. The OpenAI adapter exists and is untested live. Until Jody
  writes `provider.json` (choosing a current image model and recording its
  capabilities), provides a key in Walter's environment, and records a
  pricing snapshot for exactly that model and size, every authorised run
  ends in `MODEL_OR_QUALITY_BLOCK` or `PRICING_UNAVAILABLE` after the
  read-only checks, with no spend.
- Walter still has no Sheets or Drive connector, so the live checks that
  depend on the other skills return `SOURCE_UNAVAILABLE` until access is
  granted.
- Print-area detection relies on the scene model honouring the magenta
  marker instruction, and garment reconstruction relies on plain shirt
  around it. Scenes that do not provide either are rejected and rerolled,
  never patched.
- Scene-content judgements (fake text, logos, construction realism) are
  listed for human review, not auto-passed; the deterministic QA proves the
  artwork's identity and placement only.
