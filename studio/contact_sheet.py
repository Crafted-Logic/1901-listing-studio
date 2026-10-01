"""Contact sheet from the six final composites. The finals are only read."""
from PIL import Image, ImageDraw


def build(final_paths_with_labels, out_path, thumb=340, cols=3):
    rows = (len(final_paths_with_labels) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb + (cols + 1) * 12, rows * (thumb + 28) + 12), (245, 243, 240))
    d = ImageDraw.Draw(sheet)
    for i, (path, label) in enumerate(final_paths_with_labels):
        im = Image.open(path).convert("RGB")
        im.thumbnail((thumb, thumb))           # operates on an in-memory copy only
        x = 12 + (i % cols) * (thumb + 12); y = 12 + (i // cols) * (thumb + 28)
        sheet.paste(im, (x, y))
        d.text((x, y + thumb + 6), label, fill=(40, 40, 40))
    sheet.save(out_path, format="PNG")
    return out_path
