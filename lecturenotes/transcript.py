"""Transcripts: local speech-to-text with Whisper, or import of an existing transcript file."""
from __future__ import annotations

import os
import re
import site
import time
from pathlib import Path

from .util import clock, save_json

DEFAULT_MODEL = "large-v3-turbo"


def _enable_cuda_dlls() -> None:
    """On Windows, CUDA libraries installed from pip (nvidia-cublas/cudnn) are not on the DLL search path."""
    if os.name != "nt":
        return
    roots = list(site.getsitepackages())
    try:
        roots.append(site.getusersitepackages())
    except Exception:
        pass
    for root in roots:
        for lib in ("cublas", "cudnn"):
            bin_dir = Path(root) / "nvidia" / lib / "bin"
            if bin_dir.is_dir():
                os.add_dll_directory(str(bin_dir))
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def transcribe(media: Path, language: str | None = None, model_name: str = DEFAULT_MODEL,
               device: str = "auto", log=print) -> dict:
    _enable_cuda_dlls()
    # Windows without Developer Mode has no symlinks; the model cache still works, the warning is noise.
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from faster_whisper import WhisperModel

    options = [("cuda", "float16"), ("cpu", "int8")] if device == "auto" else \
        [(device, "float16" if device == "cuda" else "int8")]
    model = used = None
    for dev, compute_type in options:
        try:
            model = WhisperModel(model_name, device=dev, compute_type=compute_type)
            used = dev
            break
        except Exception as exc:
            log(f"  Whisper on {dev} unavailable: {exc}")
    if model is None:
        raise RuntimeError("Whisper could not be loaded on any device")
    log(f"  Whisper {model_name} on {used}")

    started = time.time()
    segments, info = model.transcribe(str(media), language=language, beam_size=5, vad_filter=True,
                                      condition_on_previous_text=False)
    result, next_report = [], 120.0
    for seg in segments:
        text = seg.text.strip()
        if text:
            result.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": text})
        if seg.end >= next_report:
            log(f"  transcribed {clock(seg.end)} / {clock(info.duration)}")
            next_report += 120.0
    return {
        "source": "whisper",
        "model": model_name,
        "device": used,
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "seconds": round(time.time() - started, 1),
        "segments": result,
    }


_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?")
_STAMPED_LINE = re.compile(r"^\s*\[?\s*((?:\d+:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?)\s*\]?\s*(.*)$")


def _seconds(match: re.Match) -> float:
    hours, minutes, seconds, fraction = match.groups()
    value = int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)
    return value + (int(fraction.ljust(3, "0")) / 1000 if fraction else 0.0)


def from_file(path: Path, language: str | None = None) -> dict:
    """Import .srt / .vtt cues, or plain lines that start with a timestamp such as `[1:02] text`."""
    text = Path(path).read_text(encoding="utf-8-sig").replace("\r", "")
    segments = _parse_cues(text) if "-->" in text else _parse_stamped_lines(text)
    if not segments:
        raise ValueError(f"No timestamps found in transcript: {path}")
    return {"source": "file", "file": Path(path).name, "language": language, "segments": segments}


def _parse_cues(text: str) -> list[dict]:
    segments = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        for i, line in enumerate(lines):
            if "-->" not in line:
                continue
            left, right = line.split("-->", 1)
            start, end = _TS.search(left), _TS.search(right)
            body = " ".join(re.sub(r"<[^>]+>", "", rest) for rest in lines[i + 1:]).strip()
            if start and end and body:
                segments.append({"start": _seconds(start), "end": _seconds(end), "text": body})
            break
    return segments


def _parse_stamped_lines(text: str) -> list[dict]:
    segments: list[dict] = []
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        match = _STAMPED_LINE.match(raw)
        if match:
            segments.append({"start": _seconds(_TS.match(match.group(1))), "end": None,
                             "text": match.group(2).strip()})
        elif segments:
            segments[-1]["text"] = f"{segments[-1]['text']} {raw.strip()}".strip()
    for current, following in zip(segments, segments[1:]):
        current["end"] = following["start"]
    if segments:
        segments[-1]["end"] = segments[-1]["start"] + 5.0
    return [seg for seg in segments if seg["text"]]


def _srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def save(doc: dict, out: Path) -> None:
    save_json(out / "transcript.json", doc)
    segments = doc["segments"]
    (out / "transcript.txt").write_text(
        "\n".join(f"[{clock(seg['start'])}] {seg['text']}" for seg in segments) + "\n", encoding="utf-8")
    cues = [f"{i}\n{_srt_time(seg['start'])} --> {_srt_time(seg['end'])}\n{seg['text']}\n"
            for i, seg in enumerate(segments, 1)]
    (out / "transcript.srt").write_text("\n".join(cues), encoding="utf-8")
