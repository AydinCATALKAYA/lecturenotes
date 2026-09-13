"""Render note.json into an illustrated HTML note, a PDF and an image bundle."""
from __future__ import annotations

import base64
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import cv2
import markdown
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from .i18n import ui_strings
from .util import clock, imread, load_json

TEMPLATES = Path(__file__).parent / "templates"
CALLOUT_TYPES = {"key", "extra", "correction", "note"}
IMAGE_MAX_WIDTH = 1600
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV"]
_TERM = re.compile(r"\(\((.+?)\)\)")
_BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


class NoteError(ValueError):
    """note.json is missing or does not match the expected format."""


def _md(text, inline: bool = False) -> Markup:
    if not text:
        return Markup("")
    html = markdown.markdown(str(text), extensions=["tables", "sane_lists"])
    html = _TERM.sub(r'<span class="term">\1</span>', html)
    html = html.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    if inline and html.startswith("<p>") and html.endswith("</p>") and html.count("<p>") == 1:
        html = html[3:-4]
    return Markup(html)


def _embed(path: Path) -> str:
    image = imread(path)
    if image is None:
        raise NoteError(f"Image not readable: {path}")
    height, width = image.shape[:2]
    if width > IMAGE_MAX_WIDTH:
        image = cv2.resize(image, (IMAGE_MAX_WIDTH, round(height * IMAGE_MAX_WIDTH / width)),
                           interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def _context(out: Path, note: dict, segments: dict) -> dict:
    language = note.get("language") or "en"
    ui = ui_strings(language)
    if segments.get("kind", "slides") != "slides":
        ui = dict(ui, slide=ui["frame"], slides=ui["frames"], slides_zip=ui["frames_zip"])
    slides = {slide["no"]: slide for slide in segments["slides"]}
    parts, count, titled = [], 0, 0

    for part in note.get("parts") or []:
        sections = []
        for sec in part.get("sections") or []:
            count += 1
            if not sec.get("title"):
                raise NoteError(f"Section {count} has no title")
            numbers = sec.get("slides") or []
            unknown = [n for n in numbers if n not in slides]
            if unknown:
                raise NoteError(f"Section '{sec['title']}' refers to unknown slides {unknown}")
            pictured = [n for n in numbers if slides[n].get("image")]
            start = sec.get("start", min((slides[n]["start"] for n in numbers), default=None))
            end = sec.get("end", max((slides[n]["end"] for n in numbers), default=None))
            callouts = []
            for callout in sec.get("callouts") or []:
                kind = callout.get("type", "note")
                if kind not in CALLOUT_TYPES:
                    raise NoteError(f"Unknown callout type '{kind}' in section '{sec['title']}'")
                callouts.append({"type": kind, "title": callout.get("title") or ui[f"callout_{kind}"],
                                 "body": _md(callout.get("body"))})
            sections.append({
                "id": sec.get("id") or f"s{count:02d}",
                "title": sec["title"],
                "toc_title": sec.get("toc_title") or sec["title"],
                "original_title": sec.get("original_title"),
                "start": start,
                "start_label": clock(start) if start is not None else "—",
                "time_label": f"{clock(start)}–{clock(end)}" if start is not None and end is not None else None,
                "slide_label": ", ".join(str(n) for n in pictured),
                "images": [{"src": _embed(out / slides[n]["image"]), "alt": f"{ui['slide']} {n}"} for n in pictured],
                "caption": _md(sec.get("caption"), inline=True),
                "narrow": bool(sec.get("narrow")),
                "visual": _md(sec.get("visual")),
                "content": _md(sec.get("content")),
                "callouts": callouts,
            })
        label = None
        if part.get("title"):
            label = part.get("label") or f"{ui['part']} {ROMAN[titled] if titled < len(ROMAN) else titled + 1}"
            titled += 1
        parts.append({"title": part.get("title"), "label": label, "sections": sections})

    meta = note.get("meta") or {}
    summary = note.get("summary") or {}
    has_audio = (out / "audio.m4a").exists()
    image_count = sum(1 for slide in segments["slides"] if slide.get("image"))
    return {
        "lang": language,
        "ui": ui,
        "meta": meta,
        "title": meta.get("title") or segments["video"]["name"],
        "duration_label": clock(segments["video"]["duration"]),
        "image_count": image_count,
        "summary": {"thesis": _md(summary.get("thesis"), inline=True),
                    "points": [_md(point, inline=True) for point in summary.get("points") or []]},
        "parts": parts,
        "glossary": [{"term": item["term"], "original": item.get("original"),
                      "definition": _md(item.get("definition"), inline=True)} for item in note.get("glossary") or []],
        "has_audio": has_audio,
        "downloads": {"pdf": False, "audio": has_audio, "transcript": (out / "transcript.txt").exists(),
                      "slides": image_count > 0},
    }


def _find_browser() -> str | None:
    for name in ("msedge", "chrome", "google-chrome", "chromium"):
        if found := shutil.which(name):
            return found
    return next((path for path in _BROWSERS if Path(path).exists()), None)


def _print_pdf(browser: str, html_path: Path, pdf_path: Path) -> bool:
    pdf_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        command = [browser, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
                   "--no-pdf-header-footer", "--virtual-time-budget=15000",
                   f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()]
        try:
            subprocess.run(command, capture_output=True, timeout=240)
        except subprocess.TimeoutExpired:
            return False
    return pdf_path.exists() and pdf_path.stat().st_size > 1000


def _zip_slides(out: Path, segments: dict) -> None:
    images = [slide["image"] for slide in segments["slides"] if slide.get("image")]
    (out / "slides.zip").unlink(missing_ok=True)
    if not images:
        return
    with zipfile.ZipFile(out / "slides.zip", "w", zipfile.ZIP_STORED) as bundle:
        for image in images:
            bundle.write(out / image, Path(image).name)


def render(out: Path, pdf: bool = True, log=print) -> Path:
    note_path = out / "note.json"
    if not note_path.exists():
        raise NoteError(f"{note_path} not found. Write the note first (see BRIEF.md).")
    note = load_json(note_path)
    segments = load_json(out / "segments.json")

    template = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True,
                           trim_blocks=True, lstrip_blocks=True).get_template("note.html.j2")
    context = _context(out, note, segments)
    _zip_slides(out, segments)
    html_path = out / "note.html"

    browser = _find_browser() if pdf else None
    context["downloads"]["pdf"] = bool(browser)
    html_path.write_text(template.render(**context), encoding="utf-8")
    log(f"HTML: {html_path}")
    if browser:
        if _print_pdf(browser, html_path, out / "note.pdf"):
            log(f"PDF:  {out / 'note.pdf'}")
        else:
            log("PDF could not be created; the note's Print button still works.")
            context["downloads"]["pdf"] = False
            html_path.write_text(template.render(**context), encoding="utf-8")
    elif pdf:
        log("No Edge or Chrome found; skipped the PDF.")
    return html_path
