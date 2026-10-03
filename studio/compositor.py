"""Deterministic compositing with Pillow only.

Two separate concerns:
  A. geometry: the scene model is asked for a flat chroma (magenta) marker on the print area. The
     marker is used ONLY to locate the print-area quadrilateral.
  B. garment appearance under the marker: reconstructed from the surrounding shirt pixels by
     harmonic interpolation (Laplace fill on a downsampled grid, bilinearly upsampled). The marker's
     own RGB values are never read for shading. The marker is removed completely before placement.
The exact approved artwork is fitted inside the quad with its aspect ratio preserved, mapped by a
perspective transform, and lit by multiplying the reconstructed garment luminance. Pixels of the
art are only moved and lit; never redrawn. Every step is a pure function of (scene, art, placement)
so QA can recompute the composite and compare pixel-for-pixel."""
import hashlib, io, json, math
from PIL import Image, ImageChops, ImageFilter, ImageMath

from . import config

GRID = 56            # harmonic fill grid (long side)
RING = 9             # width in px of the surrounding-shirt ring used as the boundary condition
RING_MAX_CV = 0.35   # max coefficient of variation of ring luminance for a believable reconstruction (unchanged)
# Dark-garment branch (evidence: five real black-shirt rings, job 4c8fda750c, mean 18-26, std 6.5-9.1, texture 2.4-3.2;
# synthetic black/near-black/charcoal good vs mottled/shadow/stripe/background rings). cv = std/mean is scale-biased
# below mean ~28: a plain black shirt's 6-9 luminance levels of drape give cv 0.38-0.49. Below RING_DARK_MEAN_MAX the
# absolute spread and the high-frequency texture decide instead; the spread bound equals what cv allows at mean 28 (0.35*28 = 9.8).
RING_DARK_MEAN_MAX = 28      # luminance mean at or below which the dark branch may apply
RING_DARK_MAX_STD = 9.8      # absolute spread cap = exactly what cv 0.35 allows at mean 28 (0.35*28); real evidence max 9.12
RING_DARK_MAX_TEXTURE = 5    # mean |L - blur(L, 2)| on the ring: random mottle >= +-12 scores >= 5.4; real fabric <= 3.2
MARKER_DOMINANCE = 4.0   # the chest marker must be at least this many times larger than any other plausible component
COMPOSITOR_VERSION = "2026-10-03.5"   # 2026-10-02.3 + ring-level rim removal (5 px bound) + seam feather + boundary-continuity QA
FRINGE_MAX_GROW_PX = 3       # the removal mask may grow at most this far beyond the marker component
FRINGE_MARGIN_MIN = 6.0      # chroma margin (levels) over the clean band's (R-G, B-G); 3x the band's chroma std when larger
RIM_MAX_GROW_PX = 5          # rim rings are absorbed within this bound from the component (approved 2026-10-03: job 863b478926-rc1 scene 06 carries a five-ring rim)
RIM_RING_TOL_ABS = 0.5       # luminance-aware growth: a whole 1 px ring around the component (within the 3 px bound) is absorbed when its MEAN
RIM_RING_TOL_REL = 0.025     # luminance deviates from the clean band by more than max(0.5, 2.5%): the generator's drawn panel outline is a
                             # band-level shift of 1-2 levels, below any per-pixel test against fabric texture
SEAM_FEATHER_PX = 6          # inside the removal mask only: the repaired field ramps from the local outside edge value to its own value over this depth,
                             # continuing a glow that the bounded rim removal cannot reach (it decays outside over ~6-12 px); scene pixels outside are never touched
BOUNDARY_TOL_ABS = 1.0       # QA boundary continuity: adjacent-band STEPS across the seam (a line), not gradients: |0-3 px out - 3-6 px out| and
                             # |0-3 px in (repaired) - 0-3 px out| each <= max(abs, rel * outer mean)
BOUNDARY_TOL_REL = 0.05
FRINGE_QA_MARGIN_MIN = 12.0  # QA counts only VISIBLY tinted pixels (twice the removal margin); removal is deliberately more aggressive than the check
FRINGE_MAX_RATE = 0.002      # QA: marker-tinted pixels allowed in the 0-4 px band of the final, as a fraction of that band (plus the clean band's own rate)
RELAX_MAX_ITERS = 3000       # harmonic fill: Gauss-Seidel until the largest update is below RELAX_TOL (converges in ~100-250 passes on a 56-cell grid)
RELAX_TOL = 0.005
TEXTURE_PATCH = 6            # quilting: residual patches this size, sampled from the ring, overlapped by TEXTURE_OVERLAP and ramp-blended
TEXTURE_OVERLAP = 2
CONTINUITY_TOL_ABS = 1.0     # luminance levels; |interior mean - clean band mean| must not exceed max(abs, rel * band mean)
CONTINUITY_TOL_REL = 0.06
SHADE_FLOOR = 0.70           # bounded dark-garment modulation: the print is never darkened below this fraction of its source intensity


def marker_mask(img):
    r, g, b = img.convert("RGB").split()
    return ImageChops.logical_and(ImageChops.logical_and(r.point(lambda v: 255 if v > 120 else 0).convert("1"), b.point(lambda v: 255 if v > 120 else 0).convert("1")), g.point(lambda v: 255 if v < 80 else 0).convert("1"))


def marker_pixels(img):
    return sum(marker_mask(img).convert("L").point(lambda v: 1 if v else 0).histogram()[1:])


def marker_components(mask):
    """4-connected components of a marker mask. Returns (components sorted largest first, labels, width):
    each component is {"id", "pixels", "bbox"}; labels[y * w + x] is the component id (0 = not marker).
    Deterministic: raster-order discovery (C-speed skipping over unset pixels), iterative flood fill."""
    w, h = mask.size; data = mask.convert("L").tobytes(); labels = bytearray(w * h); comps = []
    big = {}                                                                   # component ids beyond 255 (never expected; kept exact)
    pos = data.find(b"\xff")
    while pos != -1:
        if not labels[pos]:
            cid = len(comps) + 1; tag = cid if cid < 255 else 255
            if tag == 255: big[pos] = cid
            labels[pos] = tag; stack = [pos]; n = 0
            x0 = x2 = pos % w; y1 = y2 = pos // w; x1 = x0
            while stack:
                i = stack.pop(); n += 1; x, y = i % w, i // w
                if x < x1: x1 = x
                if x > x2: x2 = x
                if y < y1: y1 = y
                if y > y2: y2 = y
                if x > 0 and data[i - 1] and not labels[i - 1]: labels[i - 1] = tag; stack.append(i - 1)
                if x < w - 1 and data[i + 1] and not labels[i + 1]: labels[i + 1] = tag; stack.append(i + 1)
                if y > 0 and data[i - w] and not labels[i - w]: labels[i - w] = tag; stack.append(i - w)
                if y < h - 1 and data[i + w] and not labels[i + w]: labels[i + w] = tag; stack.append(i + w)
            comps.append({"id": cid, "pixels": n, "bbox": [x1, y1, x2 + 1, y2 + 1]})
        pos = data.find(b"\xff", pos + 1)
    comps.sort(key=lambda c: (-c["pixels"], c["id"]))
    return comps, labels, w


_ISOLATE_CACHE = {}


def _cached(img):
    key = (img.size, img.mode, hashlib.sha1(img.tobytes()).hexdigest())
    return key, _ISOLATE_CACHE.get(key)


def isolate_marker(img):
    """Select the one chest-marker component from the marker-colour mask, ignoring disconnected background
    pixels that merely share the marker's colour. Returns (component mask as a '1' image, info) or
    (None, reason). Selection is deterministic and by size only: components below the governed minimum
    print-area fraction are noise; among the rest the largest must dominate every other by
    MARKER_DOMINANCE, otherwise the marker cannot be isolated and the scene is unusable (fail closed)."""
    key, hit = _cached(img)
    if hit is not None: return hit
    result = _isolate_marker(img)
    if len(_ISOLATE_CACHE) > 32: _ISOLATE_CACHE.clear()
    _ISOLATE_CACHE[key] = result
    return result


def _isolate_marker(img):
    w, h = img.size
    m = marker_mask(img)
    comps, labels, _ = marker_components(m)
    if not comps:
        return None, "no print-area marker found in the scene"
    min_px = config.PLACEHOLDER_MIN_AREA * w * h
    candidates = [c for c in comps if c["pixels"] >= min_px]
    noise = [c for c in comps if c["pixels"] < min_px]
    if not candidates:
        return None, f"print-area marker too small ({comps[0]['pixels'] / float(w * h):.3%} of the image)"
    if len(candidates) > 1 and candidates[0]["pixels"] < MARKER_DOMINANCE * candidates[1]["pixels"]:
        return None, (f"more than one plausible print-area marker component ({', '.join(str(c['pixels']) for c in candidates[:4])} px); "
                      f"the chest marker cannot be isolated")
    sel = candidates[0]
    frac = sel["pixels"] / float(w * h)
    if frac > config.PLACEHOLDER_MAX_AREA:
        return None, f"print-area marker too large ({frac:.1%} of the image)"
    cid = sel["id"]
    if cid >= 255:
        return None, f"too many marker-coloured components ({len(comps)}); the chest marker cannot be isolated"
    lab = Image.frombytes("L", (w, h), bytes(labels))
    comp = lab.point(lambda v, c=cid: 255 if v == c else 0).convert("1")
    info = {"pixels": sel["pixels"], "area_fraction": round(frac, 4), "bbox": list(sel["bbox"]),
            "components": {"total": len(comps), "plausible": len(candidates), "ignored": len(comps) - 1,
                           "ignored_pixels": sum(c["pixels"] for c in comps) - sel["pixels"],
                           "largest_ignored_pixels": max((c["pixels"] for c in comps if c["id"] != cid), default=0),
                           "dominance": round(sel["pixels"] / float(candidates[1]["pixels"]), 2) if len(candidates) > 1 else None,
                           "selection": "largest component by pixel count; sub-minimum components are background noise"}}
    return comp, info


def _dil(L, k): return L.filter(ImageFilter.MaxFilter(2 * k + 1)) if k else L
def _ero(L, k): return L.filter(ImageFilter.MinFilter(2 * k + 1)) if k else L
def _count(L): return sum(L.point(lambda v: 1 if v else 0).histogram()[1:])


def _mean_std(ch, mask):
    """Mean and std of an L channel over mask pixels (mask L 0/255). Values are offset by +1 so 0 is counted."""
    hh = ImageChops.multiply(ch.point(lambda v: min(255, v + 1)), mask).histogram()[1:]; n = sum(hh)
    if not n: return None, None, 0
    mean = sum(i * k for i, k in enumerate(hh)) / n
    return mean, math.sqrt(sum(k * (i - mean) ** 2 for i, k in enumerate(hh)) / n), n


def _work_box(mask_L, pad=24):
    """Crop box around the mask with padding: every band/dilation operation runs on this crop, not the full image."""
    bb = mask_L.getbbox(); w, h = mask_L.size
    if not bb: return (0, 0, w, h)
    return (max(0, bb[0] - pad), max(0, bb[1] - pad), min(w, bb[2] + pad), min(h, bb[3] + pad))


def chroma_gate(scene, mask_L, margin_min=FRINGE_MARGIN_MIN):
    """Marker-tinted test relative to the clean garment band 4-9 px outside the mask: a pixel is tinted when both
    R-G and B-G exceed the band's mean by a margin (margin_min, or 3x the band's chroma std when larger).
    Returns (gate L, full image size, zero outside the work crop; info)."""
    box = _work_box(mask_L); ml = mask_L.crop(box)
    r, g, b = scene.convert("RGB").crop(box).split(); rg = ImageChops.subtract(r, g); bg = ImageChops.subtract(b, g)
    band = ImageChops.subtract(_dil(ml, 9), _dil(ml, 3))
    mrg, srg, _ = _mean_std(rg, band); mbg, sbg, _ = _mean_std(bg, band)
    gate = Image.new("L", scene.size, 0)
    if mrg is None: return gate, {"reference_rg": None, "reference_bg": None, "chroma_std": None, "margin": None}
    margin = max(margin_min, 3.0 * max(srg, sbg)); tr, tb = mrg + margin, mbg + margin
    gate.paste(ImageChops.multiply(rg.point(lambda v, t=tr: 255 if v > t else 0), bg.point(lambda v, t=tb: 255 if v > t else 0)), box)
    return gate, {"reference_rg": round(mrg, 2), "reference_bg": round(mbg, 2), "chroma_std": round(max(srg, sbg), 2), "margin": round(margin, 2)}


def grow_removal_mask(scene, component_mask):
    """Fringe- and rim-aware removal mask, never a blind dilation: chroma growth within FRINGE_MAX_GROW_PX, rim growth within RIM_MAX_GROW_PX:
    (1) chroma growth: one pixel per pass, only into 4-neighbours the relative chroma gate marks as marker-tinted;
    (2) rim growth: for each 1 px ring r = 1..RIM_MAX_GROW_PX around the component, the ring's not-yet-removed pixels are absorbed whole
        when their mean luminance deviates from the clean 4-9 px band's mean by more than max(RIM_RING_TOL_ABS,
        RIM_RING_TOL_REL x band mean), the generator's drawn panel outline; the first ring that does not deviate stops it.
    Returns (mask '1', info)."""
    L = component_mask.convert("L"); gate_c, cinfo = chroma_gate(scene, L); box = _work_box(L); comp = L.crop(box); cur = comp; gc = gate_c.crop(box); added = []
    for _ in range(FRINGE_MAX_GROW_PX):
        new = ImageChops.multiply(ImageChops.subtract(_dil(cur, 1), cur), gc); n = _count(new); added.append(n)
        if n == 0: break
        cur = ImageChops.lighter(cur, new)
    lum = scene.convert("L").crop(box); rings = []
    for r in range(1, RIM_MAX_GROW_PX + 1):
        band = ImageChops.subtract(_dil(cur, 9), _dil(cur, 3)); bm, _, nb = _mean_std(lum, band)
        ring = ImageChops.multiply(ImageChops.subtract(_dil(comp, r), _dil(comp, r - 1)), ImageChops.invert(cur)); rm_, _, nr = _mean_std(lum, ring)
        if bm is None: break
        if rm_ is None or nr < 50: continue                                 # ring already taken by chroma growth: look at the next one
        tol = max(RIM_RING_TOL_ABS, RIM_RING_TOL_REL * bm); dev = rm_ - bm
        rings.append({"ring": r, "pixels": nr, "delta": round(dev, 2), "tolerance": round(tol, 2), "absorbed": abs(dev) > tol})
        if abs(dev) <= tol: break
        cur = ImageChops.lighter(cur, ring)
    full = Image.new("L", L.size, 0); full.paste(cur, box)
    return full.convert("1"), {"grown_pixels": _count(cur) - _count(comp), "passes": added, "by_chroma": sum(added), "by_rim": sum(x["pixels"] for x in rings if x["absorbed"]), "rim_rings": rings, "max_grow_px": FRINGE_MAX_GROW_PX, "rim_max_grow_px": RIM_MAX_GROW_PX, "gate": cinfo}


def boundary_continuity(scene, base, mask):
    """Step continuity across the repair boundary, measured on adjacent 3 px bands so a soft lighting gradient passes and a
    line fails: (outer step) the scene's 0-3 px band outside the mask against its 3-6 px band; (seam step) the repaired
    base's 0-3 px band inside the mask against the scene's 0-3 px band outside. Returns (ok, info)."""
    L = mask.convert("L"); box = _work_box(L); ml = L.crop(box); sl = scene.convert("L").crop(box); bl = base.convert("L").crop(box)
    out03 = ImageChops.subtract(_dil(ml, 3), ml); out36 = ImageChops.subtract(_dil(ml, 6), _dil(ml, 3)); in03 = ImageChops.subtract(ml, _ero(ml, 3))
    a, _, na = _mean_std(sl, out03); b, _, nb = _mean_std(sl, out36); i, _, ni = _mean_std(bl, in03)
    if a is None or b is None or i is None or min(na, nb, ni) < 50:
        return False, {"out_0_3": a, "out_3_6": b, "in_0_3": i, "tolerance": None, "detail": "bands too small to compare"}
    tol = max(BOUNDARY_TOL_ABS, BOUNDARY_TOL_REL * b); outer_step = a - b; seam_step = i - a
    return abs(outer_step) <= tol and abs(seam_step) <= tol, {"out_0_3": round(a, 2), "out_3_6": round(b, 2), "outer_step": round(outer_step, 2), "in_0_3": round(i, 2), "seam_step": round(seam_step, 2), "tolerance": round(tol, 2)}


def find_marker_quad(img):
    """Geometry only, from the isolated chest-marker component. Returns (quad [TL, TR, BR, BL], info) or (None, reason)."""
    w, h = img.size
    comp, info = isolate_marker(img)
    if comp is None:
        return None, info
    bbox = info["bbox"]; px = comp.load()
    ms = mx = md = Md = None; count = 0
    for y in range(bbox[1], bbox[3]):
        for x in range(bbox[0], bbox[2]):
            if px[x, y]:
                count += 1; s, d = x + y, x - y
                if ms is None or s < ms[0]: ms = (s, x, y)
                if mx is None or s > mx[0]: mx = (s, x, y)
                if md is None or d < md[0]: md = (d, x, y)
                if Md is None or d > Md[0]: Md = (d, x, y)
    quad = [(ms[1], ms[2]), (Md[1] + 1, Md[2]), (mx[1] + 1, mx[2] + 1), (md[1], md[2] + 1)]
    area = _shoelace(quad); fill = count / area if area else 0
    if fill < 0.85: return None, f"print-area marker is not a solid convex panel (fill ratio {fill:.2f})"
    if bbox[0] < RING + 2 or bbox[1] < RING + 2 or bbox[2] > w - RING - 2 or bbox[3] > h - RING - 2:
        return None, "print-area marker touches the image edge; no surrounding garment to reconstruct from"
    info = dict(info, fill_ratio=round(fill, 3))
    return [(float(x), float(y)) for x, y in quad], info


def _shoelace(q):
    return abs(sum(q[i][0] * q[(i + 1) % 4][1] - q[(i + 1) % 4][0] * q[i][1] for i in range(4))) / 2.0


def _solve(A, b):
    n = len(A); M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c])); M[c], M[p] = M[p], M[c]
        if abs(M[c][c]) < 1e-12: raise ValueError("degenerate quad")
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1): M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def perspective_coeffs(dst_quad, src_w, src_h):
    src = [(0, 0), (src_w, 0), (src_w, src_h), (0, src_h)]; A, b = [], []
    for (x, y), (u, v) in zip(dst_quad, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    return _solve(A, b)


def _bilerp(q, u, v):
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = q
    top = (x0 + (x1 - x0) * u, y0 + (y1 - y0) * u); bottom = (x3 + (x2 - x3) * u, y3 + (y2 - y3) * u)
    return (top[0] + (bottom[0] - top[0]) * v, top[1] + (bottom[1] - top[1]) * v)


def fit_art_quad(quad, aw, ah):
    """Largest centred sub-quad of the marker with the art's own aspect ratio; the art is never stretched."""
    wq = max(math.dist(quad[0], quad[1]), math.dist(quad[3], quad[2])); hq = max(math.dist(quad[0], quad[3]), math.dist(quad[1], quad[2]))
    a, qr = aw / float(ah), wq / float(hq)
    us, vs = (1.0, qr / a) if a >= qr else (a / qr, 1.0)
    u0, v0 = (1 - us) / 2, (1 - vs) / 2
    return [_bilerp(quad, u0, v0), _bilerp(quad, u0 + us, v0), _bilerp(quad, u0 + us, v0 + vs), _bilerp(quad, u0, v0 + vs)], wq * us, hq * vs


def ring_stats(scene, mask):
    """Luminance statistics of the garment ring just outside the marker (the boundary condition)."""
    m = mask.convert("L")
    dil = m.filter(ImageFilter.MaxFilter(2 * RING + 1))
    ring = ImageChops.subtract(dil, m)
    lum = scene.convert("L")
    off = lum.point(lambda v: min(255, v + 1))                   # +1 so a luminance of 0 is still counted
    hist = ImageChops.multiply(off, ring).histogram()[1:]
    n = sum(hist)
    if n < 50: return None
    mean = sum(i * c for i, c in enumerate(hist)) / n
    var = sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / n
    std = math.sqrt(var)
    cum = 0; median = 0
    for i, c in enumerate(hist):
        cum += c
        if cum >= n / 2: median = i; break
    # high-frequency texture of the ring, with the marker neutralised to the ring median so the blur never sees magenta
    neutral = Image.composite(Image.new("L", lum.size, median), lum, m)
    hp = ImageChops.difference(neutral, neutral.filter(ImageFilter.GaussianBlur(2))).point(lambda v: min(255, v + 1))
    hh = ImageChops.multiply(hp, ring).histogram()[1:]
    texture = sum(i * c for i, c in enumerate(hh)) / n
    chroma_in_ring = marker_pixels(Image.composite(scene, Image.new("RGB", scene.size, (0, 0, 0)), ring))
    return {"pixels": n, "mean_luminance": round(mean, 2), "std": round(std, 2), "cv": round(std / mean, 4) if mean else 9.0,
            "texture": round(texture, 2), "chroma_pixels_in_ring": chroma_in_ring}


def ring_acceptable(stats):
    """Is the garment ring believable enough to reconstruct the print area from? Returns (ok, reason, rule).
    The cv rule is unchanged. A ring that fails it is re-judged only when its mean luminance is at or below
    RING_DARK_MEAN_MAX, by absolute spread and texture; anything else fails exactly as before."""
    if stats is None:
        return False, "no garment ring around the marker", None
    if stats["chroma_pixels_in_ring"]:
        return False, f"chroma pixels in the surrounding ring ({stats['chroma_pixels_in_ring']})", None
    if stats["cv"] <= RING_MAX_CV:
        return True, "", "cv"
    if stats["mean_luminance"] <= RING_DARK_MEAN_MAX:
        if stats["std"] > RING_DARK_MAX_STD:
            return False, f"surrounding garment is not consistent enough to reconstruct believably (dark garment, luminance std {stats['std']} over the {RING_DARK_MAX_STD} cap; cv {stats['cv']})", None
        if stats["texture"] > RING_DARK_MAX_TEXTURE:
            return False, f"surrounding garment is mottled or noisy, not reconstructable (dark garment, texture {stats['texture']} over the {RING_DARK_MAX_TEXTURE} cap; cv {stats['cv']})", None
        return True, "", "dark-absolute"
    return False, f"surrounding garment is not consistent enough to reconstruct believably (luminance cv {stats['cv']})", None


def reconstruct_garment(scene, mask, bbox):
    """Harmonic interpolation of the shirt under the marker from the surrounding ring. Returns an RGB
    image equal to the scene outside the marker and the reconstructed field inside it."""
    w, h = scene.size
    pad = RING + 4
    x0, y0, x1, y1 = max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(w, bbox[2] + pad), min(h, bbox[3] + pad)
    region = scene.crop((x0, y0, x1, y1)).convert("RGB"); rm = mask.convert("L").crop((x0, y0, x1, y1))
    rw, rh = region.size
    scale = GRID / float(max(rw, rh)); gw, gh = max(4, int(round(rw * scale))), max(4, int(round(rh * scale)))
    small = region.resize((gw, gh), Image.BOX); sm = rm.filter(ImageFilter.MaxFilter(3)).resize((gw, gh), Image.BOX)
    unknown = [[sm.getpixel((x, y)) > 0 for x in range(gw)] for y in range(gh)]
    chans = [list(small.getdata(i)) for i in range(3)]
    fields = []
    for ch in chans:
        f = [[float(ch[y * gw + x]) for x in range(gw)] for y in range(gh)]
        known_mean = [v for y in range(gh) for x in range(gw) for v in [f[y][x]] if not unknown[y][x]]
        seed = sum(known_mean) / len(known_mean) if known_mean else 128.0
        for y in range(gh):
            for x in range(gw):
                if unknown[y][x]: f[y][x] = seed
        for _ in range(RELAX_MAX_ITERS):                       # Gauss-Seidel Laplace relaxation to convergence; deterministic order
            delta = 0.0
            for y in range(gh):
                for x in range(gw):
                    if unknown[y][x]:
                        nb = [f[yy][xx] for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)) if 0 <= yy < gh and 0 <= xx < gw]
                        v = sum(nb) / len(nb); delta = max(delta, abs(v - f[y][x])); f[y][x] = v
            if delta < RELAX_TOL: break
        fields.append(Image.new("L", (gw, gh)).copy())
        fields[-1].putdata([max(0, min(255, int(round(f[y][x])))) for y in range(gh) for x in range(gw)])
    filled = Image.merge("RGB", fields).resize((rw, rh), Image.BILINEAR)
    out = scene.convert("RGB").copy()
    out.paste(Image.composite(filled, region, rm), (x0, y0))
    return out


def _lcg(seed):
    """Deterministic pseudo-random generator (32-bit LCG); seeded from the scene bytes so the result is a pure function of the scene."""
    state = seed & 0xffffffff
    while True:
        state = (state * 1103515245 + 12345) & 0x7fffffff
        yield state


def restore_texture(scene, low, mask):
    """Deterministic high-frequency garment texture under the mask: the residual (pixel minus 2 px blur) of the ring 1-9 px
    outside the mask, on the scene with the low-frequency fill already in place, is quilted into the interior as
    TEXTURE_PATCH-sized patches taken at pseudo-random positions along the ring (seeded from the marker-free image) and
    ramp-blended over TEXTURE_OVERLAP pixels. Returns (textured image, info). Pure function of (scene, low, mask)."""
    L = mask.convert("L"); bbox = L.getbbox()
    if not bbox: return low, {"patches": 0}
    pad = RING + 4; w, h = low.size
    X0, Y0, X1, Y1 = max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(w, bbox[2] + pad), min(h, bbox[3] + pad)
    region = low.crop((X0, Y0, X1, Y1)).convert("RGB"); rm = L.crop((X0, Y0, X1, Y1)); W, H = region.size
    blur = region.filter(ImageFilter.GaussianBlur(2))
    res = [ImageChops.subtract(a, b, 1, 128) for a, b in zip(region.split(), blur.split())]      # signed residual, +128 offset
    ring = ImageChops.subtract(_dil(rm, RING), rm)
    P, O = TEXTURE_PATCH, TEXTURE_OVERLAP
    ring_ok = ring.filter(ImageFilter.MinFilter(P + 1 if P % 2 == 0 else P))                     # pixels whose P x P footprint lies entirely in the ring (odd window, conservative)
    rp = ring_ok.load(); half = P // 2
    sources = [(x, y) for y in range(half, H - half) for x in range(half, W - half) if rp[x, y]]  # raster order: deterministic
    if len(sources) < 8: return low, {"patches": 0, "reason": "ring too thin to sample texture"}
    seed = int(hashlib.sha1(low.tobytes()).hexdigest()[:8], 16); rnd = _lcg(seed)      # seeded from the scene with the marker already replaced: marker pixel values never influence the composite
    rpx = [r.load() for r in res]; mp = rm.load(); out = region.copy(); op = out.load(); lp = region.load()
    acc = {}                                                                                      # (x,y) -> [sum_r, sum_g, sum_b, weight]
    step = P - O
    for ty in range(0, H, step):
        for tx in range(0, W, step):
            if not any(mp[x, y] for y in range(ty, min(H, ty + P)) for x in range(tx, min(W, tx + P))): continue
            sx, sy = sources[next(rnd) % len(sources)]; sx -= half; sy -= half
            for dy in range(P):
                y = ty + dy
                if y >= H: break
                wy = min(dy + 1, P - dy, O + 1) / float(O + 1)
                for dx in range(P):
                    x = tx + dx
                    if x >= W: break
                    if not mp[x, y]: continue
                    wgt = wy * (min(dx + 1, P - dx, O + 1) / float(O + 1))
                    a = acc.get((x, y))
                    if a is None: a = acc[(x, y)] = [0.0, 0.0, 0.0, 0.0]
                    for ch in range(3): a[ch] += wgt * (rpx[ch][sx + dx, sy + dy] - 128)
                    a[3] += wgt
    for (x, y), (sr, sg, sb, wt) in acc.items():
        base_px = lp[x, y]; op[x, y] = tuple(max(0, min(255, int(round(base_px[ch] + (sr, sg, sb)[ch] / wt)))) for ch in range(3))
    full = low.copy(); full.paste(out, (X0, Y0))
    return full, {"patches": len(acc) and (len(range(0, H, step)) * len(range(0, W, step))), "patch": P, "overlap": O, "sources": len(sources), "seed": seed}


def feather_seam(scene, base, mask):
    """Inward seam feather: for pixels inside the mask within SEAM_FEATHER_PX of its edge, blend the repaired value toward
    the local mean of the scene's 0-3 px outside band (normalised box convolution, radius SEAM_FEATHER_PX), with weight
    falling linearly from the edge inward. Pure, deterministic, touches only mask pixels. Returns (image, info)."""
    L = mask.convert("L"); box = _work_box(L, pad=SEAM_FEATHER_PX + 12); ml = L.crop(box); sc = scene.convert("RGB").crop(box); bs = base.convert("RGB").crop(box)
    band = ImageChops.subtract(_dil(ml, 3), ml)                                     # the outside edge band
    inner = ImageChops.subtract(ml, _ero(ml, SEAM_FEATHER_PX))                      # the inside feather zone
    if _count(inner) == 0 or _count(band) < 50: return base, {"feathered_pixels": 0, "depth_px": SEAM_FEATHER_PX}
    r = SEAM_FEATHER_PX
    wsum = band.filter(ImageFilter.BoxBlur(r))                                     # local band coverage (0..255)
    chans = []
    for ch in sc.split():
        num = ImageChops.multiply(ch, band).filter(ImageFilter.BoxBlur(r))          # local band value sum / 255
        ref = ImageMath.lambda_eval(lambda e: e["convert"](e["a"] * 255 / e["max"](e["b"], 1), "L"), a=num.convert("F"), b=wsum.convert("F"))   # normalised local edge mean
        chans.append(ref)
    edge_ref = Image.merge("RGB", chans)
    # weight: 1 at the edge, 0 at depth r. Distance via successive erosions.
    weight = Image.new("L", ml.size, 0)
    for d in range(1, r + 1):
        ring = ImageChops.subtract(_ero(ml, d - 1), _ero(ml, d)); weight = ImageChops.lighter(weight, ring.point(lambda v, w=int(round(255 * (1 - (d - 0.5) / r))): w if v else 0))
    blended = Image.composite(edge_ref, bs, weight)                                # weight 255 → edge reference, 0 → repaired value
    out = base.copy(); out.paste(Image.composite(blended, bs, inner), box)
    return out, {"feathered_pixels": _count(inner), "depth_px": r}


def continuity(scene, base, mask):
    """Luminance continuity of the reconstructed interior (mask eroded by 10 px) against the clean garment band 4-9 px
    outside the mask. Returns (ok, info)."""
    L = mask.convert("L"); box = _work_box(L); ml = L.crop(box); band = ImageChops.subtract(_dil(ml, 9), _dil(ml, 3)); inner = _ero(ml, 10)
    bm, _, nb = _mean_std(scene.convert("L").crop(box), band); im, _, ni = _mean_std(base.convert("L").crop(box), inner)
    if bm is None or im is None or ni < 100:
        return False, {"band_mean": bm, "interior_mean": im, "delta": None, "tolerance": None, "detail": "interior or band too small to compare"}
    tol = max(CONTINUITY_TOL_ABS, CONTINUITY_TOL_REL * bm); delta = im - bm
    return abs(delta) <= tol, {"band_mean": round(bm, 2), "interior_mean": round(im, 2), "delta": round(delta, 2), "tolerance": round(tol, 2)}


def shading_map(low, mask):
    """Bounded illumination map from the LOW-FREQUENCY reconstructed field only (fabric texture never prints through the
    ink): shade = low / p95(low over the print area), floored at SHADE_FLOOR, 1.0 elsewhere. Returns (L map, info)."""
    L = mask.convert("L"); lum = low.convert("L")
    hh = ImageChops.multiply(lum.point(lambda v: min(255, v + 1)), L).histogram()[1:]; n = sum(hh); cum = 0; p95 = 255
    for i, k in enumerate(hh):
        cum += k
        if cum >= 0.95 * n: p95 = max(1, i); break
    floor = int(round(SHADE_FLOOR * 255))
    shade = lum.point(lambda v, p=p95: max(floor, min(255, int(round(255 * v / p)))))
    shade = Image.composite(shade, Image.new("L", low.size, 255), L)
    sh = ImageChops.multiply(shade, L).histogram()[1:]; ns = sum(sh); cum = 0; med = None; mn = None
    for i, k in enumerate(sh):
        if k and mn is None: mn = i + 1
        cum += k
        if med is None and cum >= ns / 2: med = i + 1
    return shade, {"reference_p95": p95, "floor": SHADE_FLOOR, "floor_effective": round(floor / 255, 3), "median_modulation": round((med or 255) / 255, 3), "min_modulation": round((mn or 255) / 255, 3), "source": "low-frequency reconstruction only"}


_BASE_CACHE = {}


def prepare_base(scene, placement):
    """Scene with the marker (and its chroma fringe) removed and the garment reconstructed under it: converged harmonic
    low-frequency field plus quilted ring texture; and the bounded shading map (L, white outside the marker) from the
    low-frequency field only. Pure function of the scene (placement is not read). Returns (base, shade, removal mask, info)."""
    scene = scene.convert("RGB")
    key = (scene.size, hashlib.sha1(scene.tobytes()).hexdigest())
    hit = _BASE_CACHE.get(key)
    if hit is not None: return hit[0].copy(), hit[1].copy(), hit[2].copy(), json.loads(json.dumps(hit[3]))
    result = _prepare_base(scene)
    if len(_BASE_CACHE) > 16: _BASE_CACHE.clear()
    _BASE_CACHE[key] = result
    return result[0].copy(), result[1].copy(), result[2].copy(), json.loads(json.dumps(result[3]))


def _prepare_base(scene):
    comp, why = isolate_marker(scene)          # the chest-marker component only; background chroma is untouched
    if comp is None: raise CompositeError("UNUSABLE_SCENE", why)
    mask, ginfo = grow_removal_mask(scene, comp)
    low = reconstruct_garment(scene, mask, mask.convert("L").getbbox())
    base, tinfo = restore_texture(scene, low, mask)
    base, finfo = feather_seam(scene, base, mask)
    ok, cinfo = continuity(scene, base, mask)
    bok, binfo = boundary_continuity(scene, base, mask)
    shade, sinfo = shading_map(low, mask)
    return base, shade, mask, {"removal": ginfo, "texture": tinfo, "seam_feather": finfo, "continuity": {"ok": ok, **cinfo}, "boundary": {"ok": bok, **binfo}, "shading": sinfo}


def composite(scene_png_bytes, art_png_path, garment_rgb):
    scene = Image.open(io.BytesIO(scene_png_bytes)).convert("RGB")
    quad, info = find_marker_quad(scene)
    if quad is None: raise CompositeError("UNUSABLE_SCENE", info)
    comp = isolate_marker(scene)[0]; removal, _ = grow_removal_mask(scene, comp)
    stats = ring_stats(scene, removal)                                     # the ring is measured outside the fringe-aware removal mask
    ok, why, rule = ring_acceptable(stats)
    if not ok:
        raise CompositeError("UNUSABLE_SCENE", f"local garment field cannot be reconstructed: {why}")
    stats = dict(stats, rule=rule)
    art = Image.open(art_png_path); art_mode = art.mode; has_alpha = "A" in art.getbands(); art = art.convert("RGBA")
    aw, ah = art.size
    sub, fitted_w, fitted_h = fit_art_quad(quad, aw, ah)
    scale = fitted_w / float(aw)
    if scale > 1.0:
        raise CompositeError("RESOLUTION_BLOCK", f"the print area would need the art at {fitted_w:.0f}px wide but the approved source is only {aw}px wide; compositing would upscale the art by {scale:.2f}x")
    placement = {"quad": [[round(x, 2), round(y, 2)] for x, y in quad], "art_quad": [[round(x, 2), round(y, 2)] for x, y in sub], "placeholder": info, "ring": stats, "art_size": [aw, ah], "art_mode": art_mode, "art_has_alpha": has_alpha,
                 "scale": round(scale, 4), "aspect_preserved": True, "rotation_deg": round(math.degrees(math.atan2(quad[1][1] - quad[0][1], quad[1][0] - quad[0][0])), 2), "garment_rgb": list(garment_rgb),
                 "method": "marker-geometry + harmonic garment reconstruction + ring-texture quilting + pillow-perspective + bounded-luminance-multiply", "compositor_version": COMPOSITOR_VERSION}
    base, shade, removal, rinfo = prepare_base(scene, placement)
    if not rinfo["continuity"]["ok"]:
        raise CompositeError("UNUSABLE_SCENE", f"reconstructed garment is not continuous with its surroundings (interior {rinfo['continuity']['interior_mean']} vs band {rinfo['continuity']['band_mean']}, tolerance {rinfo['continuity']['tolerance']})")
    if not rinfo["boundary"]["ok"]:
        b = rinfo["boundary"]; raise CompositeError("UNUSABLE_SCENE", f"repair boundary is not continuous (outer step {b.get('outer_step')}, seam step {b.get('seam_step')}, tolerance {b.get('tolerance')})")
    placement["reconstruction"] = rinfo
    return _render(base, shade, art, placement), placement


def render_from_placement(scene, art, placement):
    """Pure function of (base scene, art, placement). QA calls this again to prove the final was not altered."""
    base, shade, _, _ = prepare_base(scene, placement)
    return _render(base, shade, art, placement)


def _render(base, shade, art, placement):
    art = art.convert("RGBA")
    coeffs = perspective_coeffs([tuple(p) for p in placement["art_quad"]], art.size[0], art.size[1])
    warped = art.transform(base.size, Image.PERSPECTIVE, coeffs, resample=Image.BICUBIC)
    rgb = ImageChops.multiply(warped.convert("RGB"), Image.merge("RGB", (shade, shade, shade)))
    warped = Image.merge("RGBA", (*rgb.split(), warped.split()[3]))
    return Image.alpha_composite(base.convert("RGBA"), warped).convert("RGB")


def warped_alpha(scene_size, art, placement):
    coeffs = perspective_coeffs([tuple(p) for p in placement["art_quad"]], art.size[0], art.size[1])
    return art.convert("RGBA").transform(scene_size, Image.PERSPECTIVE, coeffs, resample=Image.BICUBIC).split()[3]


class CompositeError(Exception):
    def __init__(self, code, detail):
        super().__init__(detail); self.code = code; self.detail = detail
