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
import hashlib, io, math
from PIL import Image, ImageChops, ImageFilter

from . import config

GRID = 56            # harmonic fill grid (long side)
RING = 9             # width in px of the surrounding-shirt ring used as the boundary condition
RING_MAX_CV = 0.35   # max coefficient of variation of ring luminance for a believable reconstruction
MARKER_DOMINANCE = 4.0   # the chest marker must be at least this many times larger than any other plausible component


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
    dil = mask.convert("L").filter(ImageFilter.MaxFilter(2 * RING + 1))
    ring = ImageChops.subtract(dil, mask.convert("L"))
    lum = scene.convert("L")
    hist = ImageChops.multiply(lum, ring).histogram()[1:]       # luminance histogram of ring pixels (0 excluded)
    n = sum(hist)
    if n < 50: return None
    mean = sum((i + 1) * c for i, c in enumerate(hist)) / n
    var = sum(c * ((i + 1) - mean) ** 2 for i, c in enumerate(hist)) / n
    chroma_in_ring = marker_pixels(Image.composite(scene, Image.new("RGB", scene.size, (0, 0, 0)), ring))
    return {"pixels": n, "mean_luminance": round(mean, 2), "cv": round(math.sqrt(var) / mean, 4) if mean else 9.0, "chroma_pixels_in_ring": chroma_in_ring}


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
        for _ in range(400):                                   # Gauss-Seidel Laplace relaxation; deterministic order
            delta = 0.0
            for y in range(gh):
                for x in range(gw):
                    if unknown[y][x]:
                        nb = [f[yy][xx] for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)) if 0 <= yy < gh and 0 <= xx < gw]
                        v = sum(nb) / len(nb); delta = max(delta, abs(v - f[y][x])); f[y][x] = v
            if delta < 0.05: break
        fields.append(Image.new("L", (gw, gh)).copy())
        fields[-1].putdata([max(0, min(255, int(round(f[y][x])))) for y in range(gh) for x in range(gw)])
    filled = Image.merge("RGB", fields).resize((rw, rh), Image.BILINEAR)
    out = scene.convert("RGB").copy()
    out.paste(Image.composite(filled, region, rm), (x0, y0))
    return out


def prepare_base(scene, placement):
    """Scene with the marker removed and the garment reconstructed under it, plus the shading map
    (L, white outside the marker) derived from the reconstruction, never from the marker."""
    scene = scene.convert("RGB"); mask, _ = isolate_marker(scene)          # the chest-marker component only; background chroma is untouched
    if mask is None: raise CompositeError("UNUSABLE_SCENE", _)
    base = reconstruct_garment(scene, mask, tuple(placement["placeholder"]["bbox"]))
    lum = base.convert("L")
    hist = ImageChops.multiply(lum, mask.convert("L")).histogram()[1:]
    peak = max((i + 1 for i, c in enumerate(hist) if c), default=255)
    shade = lum.point(lambda v, p=peak: max(64, min(255, int(255 * v / p))))
    shade = Image.composite(shade, Image.new("L", scene.size, 255), mask.convert("L"))
    return base, shade, mask


def composite(scene_png_bytes, art_png_path, garment_rgb):
    scene = Image.open(io.BytesIO(scene_png_bytes)).convert("RGB")
    quad, info = find_marker_quad(scene)
    if quad is None: raise CompositeError("UNUSABLE_SCENE", info)
    stats = ring_stats(scene, isolate_marker(scene)[0])
    if stats is None or stats["chroma_pixels_in_ring"] > 0 or stats["cv"] > RING_MAX_CV:
        why = "no garment ring around the marker" if stats is None else (f"chroma pixels in the surrounding ring ({stats['chroma_pixels_in_ring']})" if stats["chroma_pixels_in_ring"] else f"surrounding garment is not consistent enough to reconstruct believably (luminance cv {stats['cv']})")
        raise CompositeError("UNUSABLE_SCENE", f"local garment field cannot be reconstructed: {why}")
    art = Image.open(art_png_path); art_mode = art.mode; has_alpha = "A" in art.getbands(); art = art.convert("RGBA")
    aw, ah = art.size
    sub, fitted_w, fitted_h = fit_art_quad(quad, aw, ah)
    scale = fitted_w / float(aw)
    if scale > 1.0:
        raise CompositeError("RESOLUTION_BLOCK", f"the print area would need the art at {fitted_w:.0f}px wide but the approved source is only {aw}px wide; compositing would upscale the art by {scale:.2f}x")
    placement = {"quad": [[round(x, 2), round(y, 2)] for x, y in quad], "art_quad": [[round(x, 2), round(y, 2)] for x, y in sub], "placeholder": info, "ring": stats, "art_size": [aw, ah], "art_mode": art_mode, "art_has_alpha": has_alpha,
                 "scale": round(scale, 4), "aspect_preserved": True, "rotation_deg": round(math.degrees(math.atan2(quad[1][1] - quad[0][1], quad[1][0] - quad[0][0])), 2), "garment_rgb": list(garment_rgb),
                 "method": "marker-geometry + harmonic garment reconstruction + pillow-perspective + luminance-multiply"}
    return render_from_placement(scene, art, placement), placement


def render_from_placement(scene, art, placement):
    """Pure function of (base scene, art, placement). QA calls this again to prove the final was not altered."""
    base, shade, _ = prepare_base(scene, placement)
    art = art.convert("RGBA")
    coeffs = perspective_coeffs([tuple(p) for p in placement["art_quad"]], art.size[0], art.size[1])
    warped = art.transform(scene.size, Image.PERSPECTIVE, coeffs, resample=Image.BICUBIC)
    rgb = ImageChops.multiply(warped.convert("RGB"), Image.merge("RGB", (shade, shade, shade)))
    warped = Image.merge("RGBA", (*rgb.split(), warped.split()[3]))
    return Image.alpha_composite(base.convert("RGBA"), warped).convert("RGB")


def warped_alpha(scene_size, art, placement):
    coeffs = perspective_coeffs([tuple(p) for p in placement["art_quad"]], art.size[0], art.size[1])
    return art.convert("RGBA").transform(scene_size, Image.PERSPECTIVE, coeffs, resample=Image.BICUBIC).split()[3]


class CompositeError(Exception):
    def __init__(self, code, detail):
        super().__init__(detail); self.code = code; self.detail = detail
