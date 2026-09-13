"""Small shared helpers: JSON files, time labels, unicode-safe image IO and folder names."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import cv2
import numpy as np

# NFKD cannot decompose these, so they would be dropped from slugs.
_TRANSLIT = str.maketrans({"ı": "i", "İ": "I", "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "ß": "ss"})


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def clock(seconds: float) -> str:
    """00:43 or 1:02:05 — floor, so a label never points past the moment it names."""
    total = int(max(0.0, seconds))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name.translate(_TRANSLIT)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "video"


def imread(path: Path):
    """cv2.imread cannot open non-ASCII paths on Windows; decode from bytes instead."""
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def imwrite(path: Path, image, quality: int = 90) -> None:
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError(f"Could not encode image for {path}")
    buf.tofile(str(path))
