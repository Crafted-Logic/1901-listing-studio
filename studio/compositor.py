"""Deterministic compositing with Pillow only.

The scene model is asked for a flat magenta placeholder on the print area. This module finds that
placeholder, derives the cloth shading from it, replaces it with shaded fabric of the governed garment
color, and maps the exact approved artwork into the placeholder quad by a perspective transform with
the shading multiplied in. The artwork's pixels are only ever moved and lit; never redrawn.
Everything is recorded in a placement dict so QA can recompute the composite and compare."""
import io, math
from PIL import Image, ImageChops

from . import config


def _mask_of_placeholder(img):
    r, g, b = img.convert("RGB").split()
    m = ImageChops.logical_and(ImageChops.logical_and(r.point(lambda v: 255 if v > 120 else 0).convert("1"), b.point(lambda v: 255 if v > 120 else 0).convert("1")), g.point(lambda v: 255 if v < 80 else 0).convert("1"))
    return m


def find_placeholder(img):
    """Returns (quad, info) or (None, reason). quad = [TL, TR, BR, BL] as (x, y) floats."""
    w, h = img.size
    m = _mask_of_placeholder(img)
    bbox = m.getbbox()
    if not bbox:
        return None, "no print-area placeholder found in the scene"
    px = m.load()
    pts_minsum = pts_maxsum = pts_mindiff = pts_maxdiff = None
    count = 0
    for y in range(bbox[1], bbox[3]):
        for x in range(bbox[0], bbox[2]):
            if px[x, y]:
                count += 1
                s, d = x + y, x - y
                if pts_minsum is None or s < pts_minsum[0]: pts_minsum = (s, x, y)
                if pts_maxsum is None or s > pts_maxsum[0]: pts_maxsum = (s, x, y)
                if pts_mindiff is None or d < pts_mindiff[0]: pts_mindiff = (d, x, y)
                if pts_maxdiff is None or d > pts_maxdiff[0]: pts_maxdiff = (d, x, y)
    frac = count / float(w * h)
    if frac < config.PLACEHOLDER_MIN_AREA:
        return None, f"print-area placeholder too small ({frac:.3%} of the image)"
    if frac > config.PLACEHOLDER_MAX_AREA:
        return None, f"print-area placeholder too large ({frac:.1%} of the image)"
    quad = [(pts_minsum[1], pts_minsum[2]), (pts_maxdiff[1] + 1, pts_maxdiff[2]), (pts_maxsum[1] + 1, pts_maxsum[2] + 1), (pts_mindiff[1], pts_mindiff[2] + 1)]
    area = _shoelace(quad)
    fill = count / area if area else 0
    if fill < 0.85:
        return None, f"print-area placeholder is not a solid convex panel (fill ratio {fill:.2f})"
    return [(float(x), float(y)) for x, y in quad], {"pixels": count, "area_fraction": round(frac, 4), "fill_ratio": round(fill, 3), "bbox": bbox}


def _shoelace(q):
    return abs(sum(q[i][0] * q[(i + 1) % 4][1] - q[(i + 1) % 4][0] * q[i][1] for i in range(4))) / 2.0


def _solve(A, b):
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        if abs(M[c][c]) < 1e-12:
            raise ValueError("degenerate quad")
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def perspective_coeffs(dst_quad, src_w, src_h):
    """Coefficients for Image.transform(PERSPECTIVE) mapping output quad -> source rectangle."""
    src = [(0, 0), (src_w, 0), (src_w, src_h), (0, src_h)]
    A, b = [], []
    for (x, y), (u, v) in zip(dst_quad, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    return _solve(A, b)


def shading_from_placeholder(img, mask):
    """Grey image: placeholder brightness relative to its brightest pixel (cloth shading); white outside."""
    r = img.convert("RGB").split()[0]
    hist = ImageChops.multiply(r, mask.convert("L")).histogram()
    peak = max(i for i, c in enumerate(hist) if c and i > 0) or 255
    shade = r.point(lambda v, p=peak: max(90, min(255, int(255 * v / p))))
    white = Image.new("L", img.size, 255)
    return Image.composite(shade, white, mask.convert("L"))


def composite(scene_png_bytes, art_png_path, garment_rgb):
    """Returns (final RGB Image, placement dict) or raises CompositeError(code, detail)."""
    scene = Image.open(io.BytesIO(scene_png_bytes)).convert("RGB")
    quad, info = find_placeholder(scene)
    if quad is None:
        raise CompositeError("UNUSABLE_SCENE", info)
    art = Image.open(art_png_path)
    art_mode = art.mode
    has_alpha = "A" in art.getbands()
    art = art.convert("RGBA")           # no alpha in the source -> fully opaque; transparency is never invented
    aw, ah = art.size
    sub, fitted_w, fitted_h = fit_art_quad(quad, aw, ah)
    scale = fitted_w / float(aw)
    if scale > 1.0:
        raise CompositeError("RESOLUTION_BLOCK", f"the print area would need the art at {fitted_w:.0f}px wide but the approved source is only {aw}px wide; compositing would upscale the art by {scale:.2f}x")
    placement = {"quad": [[round(x, 2), round(y, 2)] for x, y in quad], "art_quad": [[round(x, 2), round(y, 2)] for x, y in sub], "placeholder": info, "art_size": [aw, ah], "art_mode": art_mode, "art_has_alpha": has_alpha,
                 "scale": round(scale, 4), "aspect_preserved": True, "rotation_deg": round(math.degrees(math.atan2(quad[1][1] - quad[0][1], quad[1][0] - quad[0][0])), 2), "garment_rgb": list(garment_rgb), "method": "pillow-perspective+shading-multiply"}
    final = render_from_placement(scene, art, placement)
    return final, placement


def _bilerp(q, u, v):
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = q
    top = (x0 + (x1 - x0) * u, y0 + (y1 - y0) * u); bottom = (x3 + (x2 - x3) * u, y3 + (y2 - y3) * u)
    return (top[0] + (bottom[0] - top[0]) * v, top[1] + (bottom[1] - top[1]) * v)


def fit_art_quad(quad, aw, ah):
    """Largest centred sub-quad of the placeholder with the art's own aspect ratio. The art is never
    stretched to the placeholder; the uncovered placeholder area becomes shaded fabric."""
    wq = max(math.dist(quad[0], quad[1]), math.dist(quad[3], quad[2])); hq = max(math.dist(quad[0], quad[3]), math.dist(quad[1], quad[2]))
    a, qr = aw / float(ah), wq / float(hq)
    if a >= qr:
        us, vs = 1.0, qr / a
    else:
        us, vs = a / qr, 1.0
    u0, v0 = (1 - us) / 2, (1 - vs) / 2
    sub = [_bilerp(quad, u0, v0), _bilerp(quad, u0 + us, v0), _bilerp(quad, u0 + us, v0 + vs), _bilerp(quad, u0, v0 + vs)]
    return sub, wq * us, hq * vs


def render_from_placement(scene, art, placement):
    """Pure function of (base scene, art, placement). QA calls this again to prove the final was not altered."""
    scene = scene.convert("RGB"); art = art.convert("RGBA")
    quad = [tuple(p) for p in placement["art_quad"]]
    mask = _mask_of_placeholder(scene)
    shade = shading_from_placeholder(scene, mask)
    fabric = Image.new("RGB", scene.size, tuple(placement["garment_rgb"]))
    fabric = ImageChops.multiply(fabric, Image.merge("RGB", (shade, shade, shade)))
    base = Image.composite(fabric, scene, mask.convert("L"))
    coeffs = perspective_coeffs(quad, art.size[0], art.size[1])
    warped = art.transform(scene.size, Image.PERSPECTIVE, coeffs, resample=Image.BICUBIC)
    rgb = ImageChops.multiply(warped.convert("RGB"), Image.merge("RGB", (shade, shade, shade)))
    warped = Image.merge("RGBA", (*rgb.split(), warped.split()[3]))
    return Image.alpha_composite(base.convert("RGBA"), warped).convert("RGB")


def placeholder_pixels(img):
    return sum(_mask_of_placeholder(img).convert("L").point(lambda v: 1 if v else 0).histogram()[1:])


class CompositeError(Exception):
    def __init__(self, code, detail):
        super().__init__(detail); self.code = code; self.detail = detail
