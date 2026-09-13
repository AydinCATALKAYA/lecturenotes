"""Write note.json with the Gemini API from the prepared material (BRIEF.md and the segment images).

Default is two passes, because one request for a long lecture lets the model regroup slides freely:
1. Plan: the whole transcript plus low-resolution images -> meta, summary, glossary, the section outline and a
   list of transcript errors (only this pass sees the whole transcript at once). The code enforces the outline:
   every segment exactly once, in order, at most 3 per section.
2. Sections: the outline split into chunks of ~10 segments, written in parallel, each with its own images and
   transcript. Transcript errors from the plan are attached to the section whose time range contains them.
`single=True` keeps the one-request mode for comparison.

Every successful response is cached in `<folder>/.write_cache/`, so a run stopped by a quota or network error
continues where it left off when the same command is run again.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2

from .util import clock, imread, load_json, save_json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILL = PROJECT_ROOT / ".claude" / "skills" / "ders-notu" / "SKILL.md"
DEFAULT_MODEL = "gemini-3.5-flash"
# USD per 1M tokens (input, output incl. thinking), ai.google.dev/gemini-api/docs/pricing, September 2026.
# On the free tier the calls cost nothing but are limited (gemini-3.5-flash: 20 requests per day).
PRICES = {"gemini-3.5-flash": (1.50, 9.00), "gemini-3.5-flash-lite": (0.30, 2.50)}
IMAGE_MAX_WIDTH = 1600
MAX_SLIDES_PER_SECTION = 3
SEGMENTS_PER_CALL = 10
PARALLEL_CALLS = 4
RETRIES = 3
LANGUAGE_NAMES = {"tr": "Turkish", "en": "English", "de": "German", "fr": "French", "es": "Spanish"}

_TEXT = {"type": "string"}
_OPTIONAL_TEXT = {"type": ["string", "null"]}
_META = {
    "type": "object",
    "properties": {name: _OPTIONAL_TEXT for name in ("title", "original_title", "series", "speaker", "affiliation")},
    "required": ["title"],
}
_SUMMARY = {
    "type": "object",
    "properties": {"thesis": _TEXT, "points": {"type": "array", "items": _TEXT}},
    "required": ["thesis", "points"],
}
_GLOSSARY = {"type": "array", "items": {
    "type": "object",
    "properties": {"term": _TEXT, "original": _OPTIONAL_TEXT, "definition": _TEXT},
    "required": ["term", "definition"],
}}
_SECTION = {
    "type": "object",
    "properties": {
        "slides": {"type": "array", "items": {"type": "integer"}},
        "start": {"type": "number"},
        "end": {"type": "number"},
        "title": _TEXT,
        "toc_title": _OPTIONAL_TEXT,
        "original_title": _OPTIONAL_TEXT,
        "caption": _OPTIONAL_TEXT,
        "narrow": {"type": "boolean"},
        "visual": _OPTIONAL_TEXT,
        "content": _TEXT,
        "callouts": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["key", "extra", "correction", "note"]},
                "title": _OPTIONAL_TEXT,
                "body": _TEXT,
            },
            "required": ["type", "body"],
        }},
    },
    "required": ["title", "content"],
}
NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "language": _TEXT, "meta": _META, "summary": _SUMMARY, "glossary": _GLOSSARY,
        "parts": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": _OPTIONAL_TEXT, "sections": {"type": "array", "items": _SECTION}},
            "required": ["sections"],
        }},
    },
    "required": ["language", "meta", "summary", "parts", "glossary"],
}
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "language": _TEXT, "meta": _META, "summary": _SUMMARY, "glossary": _GLOSSARY,
        "parts": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "title": _OPTIONAL_TEXT,
                "sections": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"slides": {"type": "array", "items": {"type": "integer"}}, "title": _TEXT},
                    "required": ["slides", "title"],
                }},
            },
            "required": ["sections"],
        }},
        "transcript_errors": {"type": "array", "items": {
            "type": "object",
            "properties": {"time": _TEXT, "heard": _TEXT, "correct": _TEXT, "body": _TEXT},
            "required": ["time", "heard", "correct", "body"],
        }},
    },
    "required": ["language", "meta", "summary", "parts", "glossary", "transcript_errors"],
}
SECTIONS_SCHEMA = {
    "type": "object",
    "properties": {"sections": {"type": "array", "items": _SECTION}},
    "required": ["sections"],
}

DEPTH_RULES = (
    "Depth: the reader will not watch the video, so the note must carry everything in it.\n"
    "- `visual`: 3–8 sentences on how to read the slide — axes and units, colours, labels, arrows, what each "
    "build adds. Use a Markdown table when the slide has numbers, categories or a comparison.\n"
    "- `content`: everything the speaker said in that time range, as 1–3 paragraphs or a list, keeping their "
    "examples, numbers and reasoning.\n"
    "- `correction` callouts are only for errors: words the speech recognition misheard, typos on a slide, "
    "numbers that contradict each other. Quote the timestamp. A clarification of, or disagreement with, what "
    "the speaker meant is a `note`, not a correction.\n"
    "- Add `extra` callouts where background knowledge helps, clearly separate from what the speaker said.\n"
)
ERROR_RULES = (
    "`transcript_errors`: compare the whole transcript with the slide text and the lecture's subject, and list "
    "every word, name or term the speech recognition got wrong (for example a misheard surname, a technical "
    "term turned into an ordinary word, an acronym written out as letters). Give `time` exactly as the "
    "transcript line's timestamp, `heard` exactly as written in the transcript, `correct` as it should be, and "
    "`body` as one sentence in the note language that quotes the timestamp and both forms. Only real "
    "mishearings; never disagreements with the speaker. Return an empty list if there are none.\n\n"
)


class WriterError(RuntimeError):
    """The note could not be written (missing key, quota, empty or invalid model response)."""


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    for env_file in (Path.cwd() / ".env", PROJECT_ROOT / ".env"):
        if key or not env_file.exists():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "GEMINI_API_KEY":
                key = value.strip().strip("\"'")
    if not key:
        raise WriterError("GEMINI_API_KEY is empty. Add your key to .env as GEMINI_API_KEY=...")
    return key


def _rules() -> str:
    """The writing rules and note format shared with the Claude Code skill, without its command workflow."""
    text = SKILL.read_text(encoding="utf-8")
    start = text.find("## Video types")
    return text[start:] if start >= 0 else text


def _jpeg(path: Path) -> bytes:
    image = imread(path)
    height, width = image.shape[:2]
    if width > IMAGE_MAX_WIDTH:
        image = cv2.resize(image, (IMAGE_MAX_WIDTH, round(height * IMAGE_MAX_WIDTH / width)), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()


def _segment_text(slide: dict) -> str:
    lines = [f"## Segment {slide['no']} · {clock(slide['start'])}–{clock(slide['end'])}"
             f"{'' if slide.get('image') else ' · no image'}"]
    lines += [f"[{clock(seg['start'])}] {seg['text']}" for seg in slide["transcript"]] or ["(no speech)"]
    return "\n".join(lines)


def _seconds(label: str) -> float | None:
    match = re.search(r"(?:(\d+):)?(\d{1,2}):(\d{2})", label or "")
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)


class _Session:
    """One Gemini client, token accounting, retries and a response cache across calls."""

    def __init__(self, model: str, out: Path, log):
        from google import genai
        from google.genai import errors, types

        self.types, self.errors, self.model, self.log = types, errors, model, log
        self.client = genai.Client(api_key=_api_key(), http_options=types.HttpOptions(timeout=900_000))
        self.cache = out / ".write_cache"
        self.usage = {"calls": 0, "cached_calls": 0, "prompt_tokens": 0, "thought_tokens": 0, "output_tokens": 0}

    def images(self, out: Path, slides: list[dict]) -> list:
        parts = []
        for slide in slides:
            if slide.get("image"):
                parts.append(self.types.Part.from_text(
                    text=f"Image of segment {slide['no']} ({clock(slide['start'])}–{clock(slide['end'])}):"))
                parts.append(self.types.Part.from_bytes(data=_jpeg(out / slide["image"]), mime_type="image/jpeg"))
        return parts

    def _call(self, contents: list, config, label: str):
        for attempt in range(RETRIES + 1):
            try:
                return self.client.models.generate_content(model=self.model, contents=contents, config=config)
            except self.errors.APIError as exc:
                message = str(exc)
                if exc.code == 429 and "PerDay" in message:
                    raise WriterError(
                        f"Daily request limit reached for {self.model} (free tier: 20 requests per day). Finished "
                        "calls are cached; run the same command again after the limit resets, or enable billing "
                        "in Google AI Studio.") from exc
                if exc.code in (429, 500, 502, 503, 504) and attempt < RETRIES:
                    wait = re.search(r"retry in ([\d.]+)s", message)
                    delay = float(wait.group(1)) + 1 if wait else 15.0 * (attempt + 1)
                    self.log(f"  {label}: error {exc.code}, retrying in {delay:.0f} s")
                    time.sleep(delay)
                    continue
                raise WriterError(f"{label}: API error {exc.code}: {message[:300]}") from exc

    def generate(self, system: str, contents: list, schema: dict, thinking: str, resolution: str, label: str,
                 cache_material: str) -> dict:
        key = hashlib.sha256(json.dumps([self.model, system, thinking, resolution, schema, cache_material],
                                        sort_keys=True).encode("utf-8")).hexdigest()[:24]
        cached = self.cache / f"{key}.json"
        if cached.exists():
            self.usage["cached_calls"] += 1
            self.log(f"  {label}: from cache")
            return load_json(cached)

        types = self.types
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel(thinking.upper())),
            media_resolution=getattr(types.MediaResolution, f"MEDIA_RESOLUTION_{resolution.upper()}"),
            max_output_tokens=65_536,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),  # no tools
        )
        started = time.time()
        response = self._call(contents, config, label)
        candidate = response.candidates[0] if response.candidates else None
        finish = getattr(candidate, "finish_reason", None)
        if not response.text:
            raise WriterError(f"{label}: the model returned no text (finish reason: {finish}).")
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise WriterError(f"{label}: invalid JSON ({exc}; finish reason: {finish}).") from exc
        usage = response.usage_metadata
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += usage.prompt_token_count or 0
        self.usage["thought_tokens"] += usage.thoughts_token_count or 0
        self.usage["output_tokens"] += usage.candidates_token_count or 0
        self.log(f"  {label}: {time.time() - started:.0f} s, {usage.prompt_token_count or 0} in, "
                 f"{usage.thoughts_token_count or 0} thinking, {usage.candidates_token_count or 0} out")
        self.cache.mkdir(exist_ok=True)
        save_json(cached, data)
        return data

    def cost(self) -> float:
        price_in, price_out = PRICES.get(self.model, PRICES[DEFAULT_MODEL])
        u = self.usage
        return u["prompt_tokens"] / 1e6 * price_in + (u["output_tokens"] + u["thought_tokens"]) / 1e6 * price_out


def _language_rule(language: str) -> str:
    name = LANGUAGE_NAMES.get(language, language)
    return (f"Write every title and every text field in {name} (language code `{language}`). "
            "Refer only to segment numbers that exist in the material.\n\n")


def _image_names(slides: list[dict]) -> str:
    return " ".join(slide["image"] for slide in slides if slide.get("image"))


def _normalise_plan(plan: dict, numbers: list[int]) -> list[dict]:
    """Every segment exactly once, in video order, at most MAX_SLIDES_PER_SECTION per section."""
    known, seen, parts = set(numbers), set(), []
    for part in plan.get("parts") or []:
        sections = []
        for sec in part.get("sections") or []:
            picked = sorted(n for n in dict.fromkeys(sec.get("slides") or []) if n in known and n not in seen)
            for i in range(0, len(picked), MAX_SLIDES_PER_SECTION):
                chunk = picked[i:i + MAX_SLIDES_PER_SECTION]
                seen.update(chunk)
                sections.append({"slides": chunk, "title": sec.get("title") or ""})
        if sections:
            parts.append({"title": part.get("title"), "sections": sections})
    if not parts:
        parts = [{"title": None, "sections": []}]
    for n in (n for n in numbers if n not in seen):
        target = next((p for p in reversed(parts) if any(s["slides"][0] < n for s in p["sections"])), parts[0])
        target["sections"].append({"slides": [n], "title": ""})
    for part in parts:
        part["sections"].sort(key=lambda s: s["slides"][0])
    parts.sort(key=lambda p: p["sections"][0]["slides"][0] if p["sections"] else 0)
    return parts


def _attach_transcript_errors(parts: list[dict], errors: list[dict], by_no: dict, transcript_text: str) -> int:
    """Put each transcript error from the plan into the section whose time range contains it. Errors whose
    'heard' text is not actually in the transcript are dropped, so the model cannot invent them."""
    sections = [sec for part in parts for sec in part["sections"]]
    attached = 0
    for error in errors:
        heard = (error.get("heard") or "").strip()
        at = _seconds(error.get("time"))
        if not heard or at is None or heard.lower() not in transcript_text.lower():
            continue
        target = next((sec for sec in sections
                       if min(by_no[n]["start"] for n in sec["slides"]) <= at < max(by_no[n]["end"] for n in sec["slides"])),
                      sections[-1] if sections else None)
        if target is None:
            continue
        callouts = target.setdefault("callouts", [])
        if any(c.get("type") == "correction" and heard.lower() in c.get("body", "").lower() for c in callouts):
            continue
        callouts.append({"type": "correction", "body": error["body"]})
        attached += 1
    return attached


def _write_two_pass(session: _Session, out: Path, segments: dict, language: str, thinking: str,
                    plan_thinking: str, resolution: str) -> dict:
    slides = segments["slides"]
    by_no = {slide["no"]: slide for slide in slides}
    rules = _rules()

    plan_system = (
        "You plan an illustrated study note for a lecture video. You receive every segment's transcript and a "
        "low-resolution image of each segment. Return the note's metadata, summary, glossary (15–25 terms), "
        "the list of transcript errors, and the outline: parts of consecutive sections, each section listing its "
        "segment numbers and a working title. Use one section per slide; merge only slides that are builds of the "
        f"same figure, never more than {MAX_SLIDES_PER_SECTION}. Cover every segment exactly once, in order.\n\n"
        + _language_rule(language) + ERROR_RULES + "Rules:\n\n" + rules
    )
    brief = "\n\n".join([f"Video type: {segments['kind']}"] + [_segment_text(slide) for slide in slides])
    plan = session.generate(plan_system, [session.types.Part.from_text(text=brief)] + session.images(out, slides),
                            PLAN_SCHEMA, plan_thinking, "low", "plan", brief + _image_names(slides))
    parts = _normalise_plan(plan, [slide["no"] for slide in slides])

    sections = [sec for part in parts for sec in part["sections"]]
    outline = "\n".join(f"- {part.get('title') or '(untitled)'}: " +
                        "; ".join(f"{sec['slides']} {sec['title']}" for sec in part["sections"]) for part in parts)
    chunks, current = [], []
    for sec in sections:
        if current and sum(len(s["slides"]) for s in current) + len(sec["slides"]) > SEGMENTS_PER_CALL:
            chunks.append(current)
            current = []
        current.append(sec)
    if current:
        chunks.append(current)

    section_system = (
        "You write sections of an illustrated study note for a lecture video. You receive the whole note's "
        "outline for context, then the transcript and image of the segments to write. Write exactly the listed "
        "sections, keeping their segment numbers. Look at each image carefully before describing it.\n\n"
        + _language_rule(language) + DEPTH_RULES + "\nRules:\n\n" + rules
    )

    def write_chunk(index_chunk):
        index, chunk = index_chunk
        chunk_slides = [by_no[n] for sec in chunk for n in sec["slides"]]
        request = ("Outline of the whole note:\n" + outline + "\n\nWrite these sections now:\n" +
                   "\n".join(f"- segments {sec['slides']}: {sec['title']}" for sec in chunk) + "\n\n" +
                   "\n\n".join(_segment_text(slide) for slide in chunk_slides))
        data = session.generate(section_system, [session.types.Part.from_text(text=request)] +
                                session.images(out, chunk_slides), SECTIONS_SCHEMA, thinking, resolution,
                                f"sections {index + 1}/{len(chunks)}", request + _image_names(chunk_slides))
        written = {tuple(sorted(sec.get("slides") or [])): sec for sec in data.get("sections") or []}
        result = []
        for position, sec in enumerate(chunk):
            match = written.get(tuple(sec["slides"]))
            if match is None and len(data.get("sections") or []) == len(chunk):
                match = data["sections"][position]
            result.append(dict(match or {"title": sec["title"], "content": ""}, slides=sec["slides"]))
        return result

    with ThreadPoolExecutor(PARALLEL_CALLS) as pool:
        written = [sec for chunk in pool.map(write_chunk, enumerate(chunks)) for sec in chunk]
    lookup = {tuple(sec["slides"]): sec for sec in written}
    for part in parts:
        part["sections"] = [lookup[tuple(sec["slides"])] for sec in part["sections"]]

    transcript_text = " ".join(seg["text"] for slide in slides for seg in slide["transcript"])
    errors = plan.get("transcript_errors") or []
    attached = _attach_transcript_errors(parts, errors, by_no, transcript_text)
    session.log(f"  transcript errors: {len(errors)} proposed, {attached} attached")
    return {"language": language, "meta": plan.get("meta") or {}, "summary": plan.get("summary") or {},
            "parts": parts, "glossary": plan.get("glossary") or []}


def _write_single(session: _Session, out: Path, segments: dict, language: str, thinking: str,
                  plan_thinking: str, resolution: str) -> dict:
    system = (
        "You write illustrated study notes from lecture videos. You receive a brief listing the video's segments "
        "(number, time range, transcript) followed by the image of every segment that has one. Look at each image "
        "carefully before describing it. Return the note as JSON matching the response schema.\n\n"
        + _language_rule(language) + "- One section per slide. Merge only slides that are builds of the same "
        "figure, never more than 3.\n" + DEPTH_RULES + "- `glossary`: 15–25 terms.\n\nRules:\n\n" + _rules()
    )
    brief = (out / "BRIEF.md").read_text(encoding="utf-8")
    note = session.generate(system, [session.types.Part.from_text(text=brief)] +
                            session.images(out, segments["slides"]), NOTE_SCHEMA, thinking, resolution, "note",
                            brief + _image_names(segments["slides"]))
    note["language"] = language
    return note


def write(out: Path, language: str = "en", model: str = DEFAULT_MODEL, thinking: str = "medium",
          plan_thinking: str = "low", resolution: str = "medium", single: bool = False, log=print) -> dict:
    segments = load_json(out / "segments.json")
    session = _Session(model, out, log)
    mode = "single" if single else "two-pass"
    pictured = sum(1 for slide in segments["slides"] if slide.get("image"))
    log(f"  {model}, {mode}, thinking {thinking} (plan {plan_thinking}), images {resolution}, "
        f"{len(segments['slides'])} segments, {pictured} images")
    started = time.time()
    note = (_write_single if single else _write_two_pass)(session, out, segments, language, thinking,
                                                          plan_thinking, resolution)

    note_path = out / "note.json"
    if note_path.exists():
        note_path.replace(out / f"note.{time.strftime('%Y%m%d-%H%M%S')}.json")
    save_json(note_path, note)
    record = dict(session.usage, model=model, mode=mode, thinking=thinking, plan_thinking=plan_thinking,
                  resolution=resolution, language=language, images=pictured,
                  seconds=round(time.time() - started, 1), cost_usd=round(session.cost(), 4))
    save_json(out / "write_log.json", record)
    log(f"  {record['seconds']:.0f} s · {record['calls']} calls ({record['cached_calls']} from cache) · tokens: "
        f"{record['prompt_tokens']} in, {record['thought_tokens']} thinking, {record['output_tokens']} out · "
        f"≈ ${record['cost_usd']:.3f} at paid-tier prices")
    return record
