"""QR codes as PNG images: the owner bot sends invite links as pictures to show people."""

import io

import segno


def png(data: str, *, scale: int = 12, border: int = 4) -> bytes:
    """Black on white, error correction Q: it still reads with a quarter of it creased, smudged
    or behind a cracked phone screen."""
    buffer = io.BytesIO()
    segno.make(data, error="q", micro=False).save(buffer, kind="png", scale=scale, border=border)
    return buffer.getvalue()
