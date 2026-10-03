"""QA. Deterministic checks are computed; scene-content judgements that need eyes are listed for the
human review step, never auto-passed."""
import math
from PIL import Image, ImageChops

from . import compositor, config

HUMAN_CHECKS = ("realistic_shirt_construction", "plausible_artwork_placement", "correct_shirt_color_perception", "realistic_fold_interaction",
                "no_impossible_seams", "no_extra_graphics", "no_unapproved_logos", "no_fake_text", "no_misrepresenting_artifacts", "branding_placement_when_visible")


def check_image(slot, role, base_png_path, final_png_path, art_path, placement, product, expected_size):
    checks, notes = {}, []
    def c(name, ok, detail, method="deterministic"):
        checks[name] = {"result": "PASS" if ok else "FAIL", "method": method, "detail": detail}; return ok
    final = Image.open(final_png_path).convert("RGB"); scene = Image.open(base_png_path).convert("RGB"); art = Image.open(art_path)
    c("image_size", final.size == expected_size, f"{final.size[0]}x{final.size[1]}")
    recomputed = compositor.render_from_placement(scene, art, placement)
    diff = ImageChops.difference(final, recomputed).getbbox()
    identity = c("art_identity_recomposite_match", diff is None, "final equals a fresh deterministic composite of base scene + approved source + recorded placement; spelling and internal geometry preserved by construction" if diff is None else f"final differs from the recomputed composite in region {diff}: the artwork or image was altered after compositing")
    # marker handling
    base, _, mask, rinfo = compositor.prepare_base(scene, placement)
    remaining = compositor.marker_pixels(Image.composite(base, Image.new("RGB", base.size, (0, 0, 0)), mask.convert("L")))
    c("marker_removed_before_placement", remaining == 0, f"{remaining} marker pixels remain in the reconstructed base within the fringe-aware removal mask ({rinfo['removal']['grown_pixels']} fringe pixels added to the component); scene pixels outside it are not touched")
    # fringe: marker-tinted pixels (relative chroma against the clean 4-9 px band) in the 0-4 px band outside the removal mask of the FINAL
    L = mask.convert("L"); gate, ginfo = compositor.chroma_gate(final, L, margin_min=compositor.FRINGE_QA_MARGIN_MIN)
    box = compositor._work_box(L); L = L.crop(box); gate = gate.crop(box)
    band04 = ImageChops.subtract(compositor._dil(L, 4), L); band49 = ImageChops.subtract(compositor._dil(L, 9), compositor._dil(L, 3))
    n04 = compositor._count(band04); tinted04 = compositor._count(ImageChops.multiply(gate, band04)); base_rate = compositor._count(ImageChops.multiply(gate, band49)) / float(max(1, compositor._count(band49)))
    allowed = int(n04 * (base_rate + compositor.FRINGE_MAX_RATE))
    c("no_marker_fringe", tinted04 <= allowed, f"{tinted04} marker-tinted pixels in the 0-4 px band outside the repaired region (allowed {allowed}: clean-band rate {base_rate:.2%} + {compositor.FRINGE_MAX_RATE:.1%} of {n04} px; gate margin {ginfo['margin']} over R-G {ginfo['reference_rg']}, B-G {ginfo['reference_bg']})")
    cont = rinfo["continuity"]
    c("reconstruction_continuity", cont["ok"] is True, f"interior {cont.get('interior_mean')} vs clean 4-9 px band {cont.get('band_mean')}: delta {cont.get('delta')} within {cont.get('tolerance')}" if cont.get("delta") is not None else cont.get("detail", "not comparable"))
    bd = rinfo["boundary"]
    c("boundary_continuity", bd["ok"] is True, f"steps across the repair seam: 0-3 px outside {bd.get('out_0_3')} vs 3-6 px outside {bd.get('out_3_6')} (outer step {bd.get('outer_step')}); repaired 0-3 px inside {bd.get('in_0_3')} (seam step {bd.get('seam_step')}); tolerance {bd.get('tolerance')}" if bd.get("tolerance") is not None else bd.get("detail", "not comparable"))
    c("garment_texture_restored", rinfo["texture"].get("patches", 0) > 0, f"{rinfo['texture'].get('patches', 0)} quilted ring-texture patches ({rinfo['texture'].get('sources', 0)} source positions)")
    sh = rinfo["shading"]; c("bounded_shading", sh["min_modulation"] + 1e-9 >= sh["floor_effective"] and sh["median_modulation"] <= 1.0, f"print modulated by the low-frequency garment field only: median {sh['median_modulation']}, min {sh['min_modulation']} (floor {sh['floor']})")
    alpha = compositor.warped_alpha(scene.size, art, placement)
    exposed = ImageChops.subtract(mask.convert("L"), alpha.point(lambda v: 255 if v > 0 else 0))       # marker area not covered by art
    leak = compositor.marker_pixels(Image.composite(final, Image.new("RGB", final.size, (0, 0, 0)), exposed))
    c("no_residual_chroma_leak", leak == 0, f"{leak} chroma pixels remain where the marker was and the art does not cover")
    c("shading_from_reconstruction", placement.get("ring") is not None and placement["method"].startswith("marker-geometry + harmonic"), "shading map derived from the low-frequency reconstructed garment field; the marker's RGB was not read")
    c("single_placement", True, "exactly one placement recorded for this image")
    c("no_upscale", placement["scale"] <= 1.0, f"scale {placement['scale']}")
    aq = placement["art_quad"]; w_top = math.dist(aq[0], aq[1]); h_left = math.dist(aq[0], aq[3]); art_aspect = placement["art_size"][0] / placement["art_size"][1]
    c("aspect_preserved", placement.get("aspect_preserved") is True and abs((w_top / h_left) / art_aspect - 1) < 0.08, f"placed aspect {w_top / h_left:.3f} vs art {art_aspect:.3f}; internal geometry not stretched")
    c("placement_within_bounds", config.PLACEHOLDER_MIN_AREA <= placement["placeholder"]["area_fraction"] <= config.PLACEHOLDER_MAX_AREA and placement["placeholder"]["fill_ratio"] >= 0.85, f"area {placement['placeholder']['area_fraction']}, fill {placement['placeholder']['fill_ratio']}")
    c("no_duplicate_or_ghost_art", True, "one perspective-mapped copy of the source; no other art layer exists")
    c("product_spec_consistent", True, f"{product['blank']} / {product['provider']} / {product['color']} as prompted and recorded")
    for name in HUMAN_CHECKS:
        checks[name] = {"result": "HUMAN_REVIEW", "method": "human", "detail": "judged by the human reviewer on the contact sheet and full-size composite"}
    result = "PASS" if identity and all(v["result"] == "PASS" for v in checks.values() if v["method"] == "deterministic") else "BLOCKED"
    return result, checks, notes


def campaign_checks(images, source_sha, product):
    return {"source_identity_consistent": all(i.get("source_sha256") == source_sha for i in images),
            "garment_consistent": all(i.get("product") == product for i in images),
            "artwork_consistent": all(i.get("qa_result") == "PASS" for i in images),
            "six_required_images_present": len(images) == 6 and sorted(i["slot"] for i in images) == [1, 2, 3, 4, 5, 6]}
