---
name: ders-notu
description: Turn a lecture video into an illustrated study note — slides, transcript and explanations on one page, with PDF, audio and slide downloads. Use when the user gives a lecture or course video and wants notes from it.
argument-hint: <video path> [note language, default tr]
---

# Lecture video → illustrated study note

Claude Code is the note writer; no external LLM API is used. Local scripts do everything mechanical.

## Workflow

Run the commands with the project's virtual environment: `.venv/Scripts/python` on Windows, `.venv/bin/python` on
macOS and Linux (written as `python` below).

1. **Prepare** (audio, local Whisper transcript, slide detection, pairing). Run in the background for long videos:
   `python -m lecturenotes prepare "<video>"`
   - `--transcript file.srt|.vtt|.txt` uses an existing transcript instead of Whisper.
   - `--source-lang en` skips language detection. `--force` redoes cached steps.
   - Output folder: `outputs/<video-slug>/`.
2. **Read** `outputs/<slug>/BRIEF.md` (every slide's time range and transcript) and look at **every** `review/sheet_*.jpg`.
   Open a single `slides/slide_XX.jpg` when a detail is too small to read.
3. **Write** `outputs/<slug>/note.json` in the note language (default English, `en`; use the language the user asks
   for) following the rules below.
4. **Render**: `python -m lecturenotes render "outputs/<slug>"` → `note.html`, `note.pdf`, `slides.zip`.
   Fix any `note.json problem:` message and render again.
5. Report to the user: where the note is, slide count, corrections found, anything uncertain.

## Video types

BRIEF.md states the type. Section times always come from the segments you reference.

- **slides** — one segment per slide. Write one section per slide as described below.
- **camera** (blackboard, operated camera, classroom) — one keyframe per time window, picked for readable
  board or slide content. The speaker may partly block the board and consecutive keyframes often show the same
  board as it fills up: merge them into one section per topic (`"slides": [4, 5, 6]`) and set `narrow` off.
  In **visual**, write out what is on the board — equations in Unicode/Markdown, the steps of a derivation,
  diagrams described in words. Say plainly when writing is too small or blurry to read.
  Keyframes can also be audience shots or cutaway clips. A section that references a segment always shows its
  image, so for those segments give the section `"start"`/`"end"` (seconds from BRIEF.md) instead of `"slides"`.
- **talking_head** — no images. Group consecutive segments into sections by topic (`"slides": [1, 2]` gives the
  times; no image is shown) and leave **visual** out.

## Writing rules

- **One section per slide**, in video order. Merge slides into one section (`"slides": [7, 8]`) only when they are
  steps of the same idea. Every slide should appear in some section; skip only empty or duplicate frames.
- **visual** explains how to *read* the slide: layout, axes and units, colour meaning, labels, arrows, what a table
  says. Describe what is actually there — look at the image, never guess from the transcript.
- **content** is what the speaker said while the slide was on screen, rewritten as clear study prose. Keep the
  speaker's reasoning and examples. Do not put outside knowledge here.
- **callouts**:
  - `extra` — useful background the speaker did not say (definitions, typical values, the study behind a figure).
  - `correction` — transcript or translation errors (quote the timestamp, e.g. `[10:09]`), slide typos, and numbers
    that contradict each other. Show the arithmetic when you flag a number.
  - `key` — short summaries, a lecture's central question, transitions between big ideas.
  - `note` — anything else worth flagging, e.g. that a value was filled in from general knowledge.
- Put terms' original-language names in double parentheses: `Aksiyon potansiyeli ((action potential))`.
  Use this for the first occurrence of important terms, not every word.
- Use Markdown tables for numbers, comparisons and lists of regions/methods; add unit conversions when the slide uses
  imperial or unusual units.
- Never invent numbers, names or citations. If a slide is unreadable, say so.
- Group sections into 4–7 **parts** with short titles. An untitled first part is fine for the introduction.
- **summary**: one-sentence thesis + 4–6 points. **glossary**: 15–25 important terms.

## note.json format

```json
{
  "language": "tr",
  "meta": {
    "title": "Beyin ve Beyin Bilimine Giriş",
    "original_title": "Introduction: The brain and brain science",
    "series": "Neuromatch Academy · Nörobilim Video Serisi",
    "speaker": "Arvind Kumar",
    "affiliation": "KTH, Stockholm"
  },
  "summary": {"thesis": "Markdown, one sentence", "points": ["Markdown", "..."]},
  "parts": [
    {
      "title": null,
      "sections": [
        {
          "slides": [1],
          "title": "Giriş",
          "toc_title": "optional shorter title for the contents list",
          "original_title": "optional slide title in the source language",
          "caption": "optional image credit, Markdown inline",
          "narrow": false,
          "visual": "Markdown",
          "content": "Markdown",
          "callouts": [{"type": "extra", "title": "optional custom label", "body": "Markdown"}]
        }
      ]
    }
  ],
  "glossary": [{"term": "Sinaps", "original": "synapse", "definition": "Markdown inline"}]
}
```

- Section times come from the slides automatically. A section without slides may set `"start"` and `"end"` in seconds.
- `narrow: true` shows a small image (title cards, single portraits).
- `meta.language_label` overrides the language name shown on the cover.
- Interface labels exist for `tr` and `en` in `lecturenotes/i18n.py`; add a language there before writing notes in it.
