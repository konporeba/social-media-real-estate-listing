"""Pillow image optimization: resize to max 1440px edge, JPEG q85, EXIF stripped."""

from __future__ import annotations

import io
from math import ceil

import structlog
from PIL import Image, ImageFilter

log = structlog.get_logger()

MAX_EDGE = 1440
JPEG_QUALITY = 85

# Instagram rejects any image outside 4:5 (0.80) .. 1.91:1 with error_subcode 2207009.
# Listing photos are often wide-angle panoramas well beyond 1.91:1, so they must be
# padded before publishing.
IG_MIN_RATIO = 0.80
IG_MAX_RATIO = 1.91

# When padding *is* required, aim just inside the window rather than at its edge:
# landing on 0.80/1.91 exactly leaves no room for Meta's own rounding to reject us.
IG_PAD_MIN_RATIO = 0.81
IG_PAD_MAX_RATIO = 1.90

IG_BACKDROP_BLUR = 28


def optimize_image(raw: bytes) -> bytes:
    """Return re-encoded JPEG bytes: fits within MAX_EDGE×MAX_EDGE, EXIF stripped."""
    try:
        img = Image.open(io.BytesIO(raw))
    except Exception as exc:
        raise ValueError(f"Cannot decode image data: {exc}") from exc

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


def fit_instagram_aspect(raw: bytes) -> bytes | None:
    """Pad `raw` onto an Instagram-legal canvas, or None if it is already legal.

    Returns None — meaning "reuse the original" — for the common case, so callers
    skip a redundant upload.  Facebook and LinkedIn accept any ratio and keep the
    unpadded image; only Instagram gets this variant.

    Pads rather than crops: a centre-crop on a wide interior shot cuts away the
    room, which is the whole point of the listing.  The bars are a blurred,
    zoomed copy of the photo itself rather than flat colour — the conventional
    Instagram treatment, and it keeps the post from looking letterboxed.
    """
    img = Image.open(io.BytesIO(raw))
    if img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    ratio = w / h
    if IG_MIN_RATIO <= ratio <= IG_MAX_RATIO:
        return None

    # ceil, not round: rounding down lands the canvas fractionally *outside* the
    # window it was meant to enter (a 720x1440 photo rounds to 0.8097 < 0.81).
    # Ceiling always overshoots into the legal range.
    if ratio > IG_MAX_RATIO:  # too wide — grow the canvas vertically
        canvas_w, canvas_h = w, ceil(w / IG_PAD_MAX_RATIO)
    else:  # too tall — grow the canvas horizontally
        canvas_w, canvas_h = ceil(h * IG_PAD_MIN_RATIO), h

    # Backdrop: scale-to-cover the canvas, blur, then lay the untouched photo on top.
    cover = max(canvas_w / w, canvas_h / h)
    backdrop = img.resize(
        (max(1, round(w * cover)), max(1, round(h * cover))), Image.Resampling.LANCZOS
    )
    left = (backdrop.width - canvas_w) // 2
    top = (backdrop.height - canvas_h) // 2
    backdrop = backdrop.crop((left, top, left + canvas_w, top + canvas_h))
    backdrop = backdrop.filter(ImageFilter.GaussianBlur(IG_BACKDROP_BLUR))
    backdrop.paste(img, ((canvas_w - w) // 2, (canvas_h - h) // 2))

    log.info(
        "instagram_aspect_padded",
        original=f"{w}x{h}",
        ratio=round(ratio, 3),
        padded=f"{canvas_w}x{canvas_h}",
        new_ratio=round(canvas_w / canvas_h, 3),
    )

    out = io.BytesIO()
    backdrop.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()
