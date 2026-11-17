"""Image validation and preparation. Deterministic; no generative enhancement."""

from __future__ import annotations

import hashlib
import io
import math
from decimal import Decimal

from PIL import Image, ImageOps, UnidentifiedImageError

PREPROCESSING_VERSION = "pre-2"  # pre-2: embedded comments and profiles removed; MPO accepted

# MPO is the multi-picture JPEG many phones and cameras write; its first frame is the photo.
ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP"}
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 50_000_000  # refuse decompression bombs
MIN_SIDE = 64
STORED_MAX_SIDE = 4096
ROLES = ("garment", "label", "detail")
MAX_IMAGES_PER_ITEM = 3

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class ImageRejected(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _encode(img: Image.Image, quality: int) -> bytes:
    out = io.BytesIO()
    # Copy the pixels into a blank image so nothing travels with them: no EXIF,
    # GPS, XMP, ICC profile or embedded text comment (Pillow would otherwise
    # carry a JPEG comment over into the new file).
    bare = Image.new("RGB", img.size)
    bare.paste(img)
    bare.save(out, format="JPEG", quality=quality, subsampling=0, optimize=False)
    return out.getvalue()


def _fit(img: Image.Image, max_side: int) -> Image.Image:
    if max(img.size) <= max_side:
        return img
    scale = max_side / max(img.size)
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.resize(size, Image.LANCZOS)


def clean_upload(data: bytes) -> tuple[bytes, int, int]:
    """Check an uploaded file really is an allowed image and return a
    metadata-free JPEG copy with its size. Raises ImageRejected otherwise."""
    if not data:
        raise ImageRejected("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageRejected(f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            probe.verify()  # detects truncated or disguised files
        if fmt not in ALLOWED_FORMATS:
            raise ImageRejected("Only JPEG, PNG and WEBP images are accepted.")
        img = Image.open(io.BytesIO(data))
        if fmt == "MPO":
            img.seek(0)  # the main photo; extra embedded frames are dropped
        elif getattr(img, "is_animated", False):
            raise ImageRejected("Animated images are not accepted.")
        img = ImageOps.exif_transpose(img)  # apply the camera rotation, then drop the metadata
        img.load()
    except ImageRejected:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError) as exc:
        raise ImageRejected("The file is not a readable image.") from exc
    if min(img.size) < MIN_SIDE:
        raise ImageRejected(f"The image is too small; each side must be at least {MIN_SIDE} pixels.")
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        img = flat
    else:
        img = img.convert("RGB")
    img = _fit(img, STORED_MAX_SIDE)
    return _encode(img, 92), img.width, img.height


def validate_crop(crop: dict | None) -> dict | None:
    if crop is None:
        return None
    try:
        x, y, w, h = (float(crop[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        raise ImageRejected("A crop needs x, y, w and h.") from None
    if not (0 <= x < 1 and 0 <= y < 1 and 0.02 <= w <= 1 and 0.02 <= h <= 1 and x + w <= 1.0001 and y + h <= 1.0001):
        raise ImageRejected("The crop must lie inside the image.")
    return {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)}


def prepare(stored: bytes, crop: dict | None, max_side: int) -> tuple[bytes, int, int, str]:
    """The exact bytes sent to a provider: cropped, scaled, metadata-free."""
    img = Image.open(io.BytesIO(stored)).convert("RGB")
    if crop:
        box = (round(crop["x"] * img.width), round(crop["y"] * img.height),
               round((crop["x"] + crop["w"]) * img.width), round((crop["y"] + crop["h"]) * img.height))
        img = img.crop(box)
    img = _fit(img, max_side)
    data = _encode(img, 90)  # high quality on purpose: label text must stay readable
    return data, img.width, img.height, sha256(data)


def image_tokens(width: int, height: int, multiplier: Decimal) -> int:
    """Vendor patch rule: 32px patches times a model multiplier, assuming the
    provider does NOT shrink the image further (the higher figure)."""
    patches = math.ceil(width / 32) * math.ceil(height / 32)
    return math.ceil(patches * multiplier)
