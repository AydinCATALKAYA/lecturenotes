"""Pair visual segments with the transcript and prepare the material the note writer works from."""
from __future__ import annotations

import bisect
from pathlib import Path

import cv2
import numpy as np

from .util import clock, imread, imwrite, load_json, save_json

SHEET_WIDTH = 1280
SLIDES_PER_SHEET = 2
_BRIEF_KINDS = {
    "slides": "slide video: one segment per slide",
    "camera": "camera footage: one keyframe per time window, chosen for readable board/slide content",
    "talking_head": "talking head: no readable visuals, write from the transcript only",
}


def build(out: Path) -> dict:
    video = load_json(out / "video.json")
    slides_doc = load_json(out / "slides.json")
    transcript = load_json(out / "transcript.json")

    slides = [dict(slide, transcript=[]) for slide in slides_doc["slides"]]
    starts = [slide["start"] for slide in slides]
    for seg in transcript["segments"]:
        middle = (seg["start"] + seg["end"]) / 2
        slides[max(0, bisect.bisect_right(starts, middle) - 1)]["transcript"].append(seg)

    doc = {
        "video": video,
        "kind": slides_doc["kind"],
        "transcript_source": transcript.get("source"),
        "transcript_language": transcript.get("language"),
        "slides": slides,
    }
    save_json(out / "segments.json", doc)
    _write_brief(out, doc)
    _write_sheets(out, slides)
    return doc


def _write_brief(out: Path, doc: dict) -> None:
    video = doc["video"]
    images = sum(1 for slide in doc["slides"] if slide.get("image"))
    unit = "Slide" if doc["kind"] == "slides" else "Segment"
    lines = [
        f"# Writing brief: {video['name']}",
        "",
        f"- Duration {clock(video['duration'])} · {len(doc['slides'])} segments, {images} with an image",
        f"- Video type: {_BRIEF_KINDS.get(doc['kind'], doc['kind'])}",
        f"- Transcript: {doc['transcript_source']}, language `{doc['transcript_language']}`",
        "- Look at every `review/sheet_*.jpg` (two images each, labelled with number and start time)"
        if images else "- There are no images to review",
        "- Writing rules and the note.json format: `.claude/skills/ders-notu/SKILL.md`",
        f"- After writing note.json: `python -m lecturenotes render \"{out}\"`",
    ]
    for slide in doc["slides"]:
        image = f"`{slide['image']}`" if slide.get("image") else "no image"
        lines += ["", f"## {unit} {slide['no']} · {clock(slide['start'])}–{clock(slide['end'])} · {image}", ""]
        lines += [f"[{clock(seg['start'])}] {seg['text']}" for seg in slide["transcript"]] or ["_(no speech)_"]
    (out / "BRIEF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_sheets(out: Path, slides: list[dict]) -> None:
    sheets = out / "review"
    sheets.mkdir(exist_ok=True)
    for old in sheets.glob("sheet_*.jpg"):
        old.unlink()
    with_images = [slide for slide in slides if slide.get("image")]
    for k in range(0, len(with_images), SLIDES_PER_SHEET):
        tiles = []
        for slide in with_images[k:k + SLIDES_PER_SHEET]:
            image = imread(out / slide["image"])
            height, width = image.shape[:2]
            image = cv2.resize(image, (SHEET_WIDTH, round(height * SHEET_WIDTH / width)), interpolation=cv2.INTER_AREA)
            cv2.rectangle(image, (0, 0), (190, 42), (90, 60, 150), -1)
            cv2.putText(image, f"{slide['no']}  {clock(slide['start'])}", (12, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2, cv2.LINE_AA)
            tiles.append(image)
        imwrite(sheets / f"sheet_{k // SLIDES_PER_SHEET + 1:02d}.jpg", np.vstack(tiles), quality=85)
