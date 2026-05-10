"""Pillow image optimization: resize to max 1440px edge, JPEG q85, EXIF stripped."""
from __future__ import annotations

import io

from PIL import Image

MAX_EDGE = 1440
JPEG_QUALITY = 85


def optimize_image(raw: bytes) -> bytes:
    """Return re-encoded JPEG bytes: fits within MAX_EDGE×MAX_EDGE, EXIF stripped."""
    img = Image.open(io.BytesIO(raw))

    # JPEG can only store RGB; also strips EXIF because we don't pass exif= to save()
    if img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > MAX_EDGE:
        if w >= h:
            new_size = (MAX_EDGE, max(1, int(h * MAX_EDGE / w)))
        else:
            new_size = (max(1, int(w * MAX_EDGE / h)), MAX_EDGE)
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()
