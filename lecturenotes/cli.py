"""Command line: `prepare <video>`, then `write <folder>` (Gemini) or a hand-written note.json, then `render <folder>`."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import align, media, render, slides, transcript
from .util import clock, save_json, slugify


def log(message: str) -> None:
    print(message, flush=True)


def _elapsed(started: float) -> str:
    minutes, seconds = divmod(int(time.time() - started), 60)
    return f"{minutes}m {seconds:02d}s"


def prepare(args) -> None:
    video = Path(args.video).resolve()
    if not video.is_file():
        sys.exit(f"Video not found: {video}")
    out = Path(args.out).resolve() if args.out else Path.cwd() / "outputs" / slugify(video.stem)
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()

    info = media.probe(video)
    info["source"] = str(video)
    save_json(out / "video.json", info)
    log(f"Video: {info['name']} · {clock(info['duration'])} · {info['width']}x{info['height']}")
    log(f"Output: {out}")

    if info["has_audio"] and (args.force or not (out / "audio.m4a").exists()):
        step = time.time()
        log("[1/4] Audio")
        media.extract_audio(video, out / "audio.m4a")
        log(f"  done in {_elapsed(step)}")

    if args.force or not (out / "transcript.json").exists():
        step = time.time()
        if args.transcript:
            log(f"[2/4] Transcript from {args.transcript}")
            doc = transcript.from_file(Path(args.transcript), language=args.source_lang)
        else:
            if not info["has_audio"]:
                sys.exit("The video has no audio track; pass --transcript to use a transcript file.")
            log("[2/4] Transcript (Whisper, local)")
            doc = transcript.transcribe(out / "audio.m4a", language=args.source_lang, model_name=args.model,
                                        device=args.device, log=log)
        transcript.save(doc, out)
        log(f"  {len(doc['segments'])} segments, language {doc.get('language')}, done in {_elapsed(step)}")

    if args.force or not (out / "slides.json").exists():
        step = time.time()
        log("[3/4] Slides")
        doc = slides.detect(video, out, info["duration"], log=log)
        log(f"  {len(doc['slides'])} slides ({doc['kind']}), overlay {'removed' if doc['overlay'] else 'none'}, "
            f"done in {_elapsed(step)}")

    log("[4/4] Pairing slides with the transcript")
    doc = align.build(out)
    log(f"\nReady in {_elapsed(started)}: {len(doc['slides'])} slides.")
    log(f"Next: python -m lecturenotes write \"{out}\"   (or write note.json by hand, then render)")


def write_note(args) -> None:
    from . import writer

    out = Path(args.folder).resolve()
    if not (out / "segments.json").exists():
        sys.exit(f"{out} has not been prepared yet; run prepare first.")
    log(f"Writing note ({args.lang})")
    try:
        writer.write(out, language=args.lang, model=args.model, thinking=args.thinking,
                     plan_thinking=args.plan_thinking, resolution=args.resolution, single=args.single, log=log)
    except writer.WriterError as exc:
        sys.exit(str(exc))
    except ImportError:
        sys.exit('Gemini support is not installed. Install it with: pip install -e ".[gemini]"')
    if not args.no_render:
        try:
            render.render(out, pdf=True, log=log)
        except render.NoteError as exc:
            sys.exit(f"note.json problem: {exc}")


def main(argv=None) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(prog="lecturenotes", description="Lecture video -> illustrated study note.")
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("prepare", help="Extract audio, transcript and slides, and write BRIEF.md.")
    p.add_argument("video")
    p.add_argument("--transcript", help="Use an existing transcript (.srt, .vtt or '[m:ss] text' lines).")
    p.add_argument("--source-lang", help="Spoken language code such as en. Detected automatically if omitted.")
    p.add_argument("--model", default=transcript.DEFAULT_MODEL, help="Whisper model name.")
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    p.add_argument("--out", help="Output folder (default: outputs/<video-name>).")
    p.add_argument("--force", action="store_true", help="Redo every step even if its results exist.")

    w = commands.add_parser("write", help="Write note.json with the Gemini API, then render it.")
    w.add_argument("folder")
    w.add_argument("--lang", default="en", help="Note language code, e.g. en, tr (default: en).")
    w.add_argument("--model", default="gemini-3.5-flash")
    w.add_argument("--thinking", default="medium", choices=["minimal", "low", "medium", "high"],
                   help="Thinking level for writing sections (default: medium).")
    w.add_argument("--plan-thinking", default="low", choices=["minimal", "low", "medium", "high"],
                   help="Thinking level for the outline pass (default: low).")
    w.add_argument("--resolution", default="medium", choices=["low", "medium", "high"],
                   help="Image resolution sent with sections (default: medium).")
    w.add_argument("--single", action="store_true", help="One request for the whole note instead of plan + sections.")
    w.add_argument("--no-render", action="store_true", help="Only write note.json.")

    r = commands.add_parser("render", help="Turn note.json into note.html, note.pdf and slides.zip.")
    r.add_argument("folder")
    r.add_argument("--no-pdf", action="store_true", help="Skip PDF generation.")

    s = commands.add_parser("study", help="Turn study.json into study.html (study mode), read.html and cards.csv.")
    s.add_argument("folder")

    args = parser.parse_args(argv)
    if args.command == "prepare":
        prepare(args)
    elif args.command == "write":
        write_note(args)
    elif args.command == "study":
        from .study import render_study

        try:
            render_study(Path(args.folder).resolve(), log=log)
        except render.NoteError as exc:
            sys.exit(f"study.json problem: {exc}")
    else:
        try:
            render.render(Path(args.folder).resolve(), pdf=not args.no_pdf, log=log)
        except render.NoteError as exc:
            sys.exit(f"note.json problem: {exc}")
