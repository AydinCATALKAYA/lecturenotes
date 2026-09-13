# lecturenotes

Turns a lecture video into an illustrated study note: slides are detected and cleaned, paired with a timestamped
transcript, and a note is written that connects what is on each slide with what was said. A weekend open-source
project (MIT). Personal instructions, if any, live in the git-ignored `CLAUDE.local.md`.

## Commands

```
lecturenotes prepare "inputs/<video>.mp4"   # audio, transcript, slides, BRIEF.md → outputs/<slug>/
lecturenotes write "outputs/<slug>"         # Gemini writes note.json, then renders (needs .[gemini] and .env)
lecturenotes render "outputs/<slug>"        # note.json → note.html, note.pdf, slides.zip
lecturenotes study "outputs/<slug>"         # study.json → study.html, read.html, cards.csv
python -m pytest                            # tests (no network, no GPU needed)
```

Without installing the package, use `python -m lecturenotes ...` from the project root.

## Layout

- `lecturenotes/media.py` audio via PyAV · `transcript.py` Whisper or subtitle import · `slides.py` visual
  segmentation · `person.py` MediaPipe person mask · `align.py` pairing, `BRIEF.md`, review sheets ·
  `render.py` note rendering and PDF · `study.py` study mode · `writer.py` Gemini note writer · `i18n.py` UI strings
- `lecturenotes/templates/` Jinja templates; `_style.css` is shared by `note.html.j2` and `study.html.j2`
- `.claude/skills/ders-notu/SKILL.md` note-writing rules and `note.json` format, shared with `writer.py`
  (it reads the rules from "## Video types" on)
- `docs/` study-mode design and images for the README
- `inputs/`, `outputs/`, `examples/`, `private/` are git-ignored: videos and everything derived from them stay local

## Conventions

- Decode video with PyAV, not `cv2.VideoCapture`.
- OpenCV cannot open non-ASCII paths on Windows; read and write images through `util.imread` / `util.imwrite`.
- OpenCV 5 has no `CascadeClassifier`; person and close-up detection use MediaPipe (`person.py`, model downloaded
  to `lecturenotes/models/` on first use). MediaPipe needs `opencv-contrib-python`; never install
  `opencv-python-headless` beside it.
- On Windows, CUDA DLLs come from the pip `nvidia-*` wheels (`transcript._enable_cuda_dlls`).
- Never add a video downloader. Inputs are files the user may use.

## Slide detection tuning

Thresholds are module constants at the top of `slides.py`, each with a comment on how it was chosen. They were tuned on
eight lectures covering: slides + webcam box, full-screen slides with handwriting (360p), blackboard with an operated
camera, live coding with a keyed presenter, a Turkish lecture with a keyed presenter, a 320×180 blackboard lecture and
a TED talk. Stroke density cannot tell a low-resolution blackboard from a stage; a text detector would be the next
step. When changing thresholds, re-check several video types, not just one.

## Gemini writer

- Two passes: a plan call (whole transcript + low-res images → meta, summary, glossary, outline, transcript errors),
  then parallel section calls of ~10 segments. The code enforces the outline (each segment once, ≤3 per section)
  and drops transcript errors whose “heard” text does not occur in the transcript. `--single` is one request.
- One request for a long lecture regroups slides freely and varies between runs; two-pass was clearly better.
- Responses are cached in `outputs/<slug>/.write_cache/`, so a run stopped by a quota resumes with the same command.
