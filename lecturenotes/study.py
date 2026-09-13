"""Study mode: render study.json as an interactive study page (study.html) and, from exactly the same text, a
passive reading page (read.html), so the two formats can be compared with the content held constant."""
from __future__ import annotations

import csv
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .i18n import ui_strings
from .render import CALLOUT_TYPES, ROMAN, TEMPLATES, NoteError, _embed, _md
from .util import clock, load_json

WORDS_PER_MINUTE = 200
_WORD = re.compile(r"\w+")

STUDY_UI = {
    "en": {
        "goals_title": "After this lecture you should be able to answer",
        "goals_hint": "Ask yourself these before reading, and come back to them at the end.",
        "more": "Details, corrections and additional context",
        "rate_q": "How well did you understand this section?",
        "rate_ok": "I understood it",
        "rate_unsure": "Not sure",
        "rate_no": "I didn't",
        "check": "Check yourself",
        "your_answer": "Your answer",
        "answer_placeholder": "Write it in your own words first, then reveal the answer.",
        "reveal": "Show answer",
        "grade_q": "Did your answer match?",
        "right": "I got it",
        "wrong": "Wrong or incomplete",
        "calib_title": "Where you stand",
        "calib_how": "Compares the sections you marked as understood with how you answered their questions. Everything feels "
                     "familiar while reading; recalling and explaining it is a different thing.",
        "calib_line": "You rated {rated} of {total} sections. In {confident} sections you marked as understood and answered, "
                      "you got everything right in {right}.",
        "cat_illusion": "Marked as understood but missed a question — review these first",
        "cat_shaky": "Marked as not sure or not understood",
        "cat_under": "Not sure, but answered correctly",
        "cat_solid": "Understood and answered correctly",
        "cat_pending": "Rated, questions not answered yet",
        "cat_open": "Not rated yet",
        "reset": "Reset my study",
        "reset_confirm": "Delete all your answers and ratings?",
        "cards_title": "Flashcards",
        "cards_hint": "Read the front, say the answer to yourself, then flip.",
        "front": "Question",
        "back": "Answer",
        "flip": "Flip",
        "known": "I know it",
        "again": "Show again",
        "cards_done": "You know all the cards.",
        "cards_count": "{known}/{total} cards done",
        "cards_csv": "Download cards (CSV for Anki)",
        "reading": "Reading time",
        "minutes": "~{min} min",
        "how_study": "The first sentence of each section is its main idea; details are folded away. At the end of each "
                     "section rate your understanding and answer the question yourself before revealing it. Your work is "
                     "saved in this browser; at the end you get a summary of where you stand and flashcards.",
        "how_read": "The time label on each section is when that part of the lecture took place; click it to play the "
                    "audio from there. Click an image to enlarge it.",
    },
    "tr": {
        "goals_title": "Bu dersten sonra cevaplayabilmen gerekenler",
        "goals_hint": "Okumaya başlamadan önce kendine sor; en sonda tekrar dön.",
        "more": "Ayrıntılar, düzeltmeler ve ek bilgiler",
        "rate_q": "Bu bölümü ne kadar anladın?",
        "rate_ok": "Anladım",
        "rate_unsure": "Emin değilim",
        "rate_no": "Anlamadım",
        "check": "Kendini yokla",
        "your_answer": "Cevabın",
        "answer_placeholder": "Önce kendi cümlelerinle yaz, sonra cevabı aç.",
        "reveal": "Cevabı göster",
        "grade_q": "Cevabın buna uyuyor muydu?",
        "right": "Doğru bildim",
        "wrong": "Yanlış ya da eksik",
        "calib_title": "Nerede olduğunu gör",
        "calib_how": "“Anladım” dediğin bölümleri, o bölümlerin sorularını nasıl cevapladığınla karşılaştırır. Okurken her şey "
                     "tanıdık gelir; hatırlayıp açıklayabilmek başka bir şeydir.",
        "calib_line": "{total} bölümün {rated} tanesini değerlendirdin. “Anladım” deyip sorusunu cevapladığın {confident} "
                      "bölümün {right} tanesinde hepsini doğru bildin.",
        "cat_illusion": "“Anladım” dedin ama soruyu kaçırdın — önce bunları tekrar et",
        "cat_shaky": "Emin değilim ya da anlamadım dedin",
        "cat_under": "Emin değildin ama doğru bildin",
        "cat_solid": "Anladın ve doğru bildin",
        "cat_pending": "Değerlendirdin, sorusunu henüz cevaplamadın",
        "cat_open": "Henüz değerlendirmediğin bölümler",
        "reset": "Çalışmamı sıfırla",
        "reset_confirm": "Bütün cevapların ve değerlendirmelerin silinsin mi?",
        "cards_title": "Bilgi kartları",
        "cards_hint": "Kartın önünü oku, cevabı içinden söyle, sonra çevir.",
        "front": "Soru",
        "back": "Cevap",
        "flip": "Çevir",
        "known": "Biliyorum",
        "again": "Tekrar göster",
        "cards_done": "Bütün kartları bildin.",
        "cards_count": "{known}/{total} kart tamam",
        "cards_csv": "Kartları indir (Anki için CSV)",
        "reading": "Okuma süresi",
        "minutes": "~{min} dk",
        "how_study": "Her bölümün ilk cümlesi ana fikir; ayrıntılar kapalı, gerekirse aç. Bölüm sonunda ne kadar anladığını "
                     "işaretle ve soruyu cevabı açmadan önce kendin cevapla. Çalışman bu tarayıcıda saklanır; en sonda "
                     "nerede eksik olduğunu gösteren bir özet ve bilgi kartları var.",
        "how_read": "Her bölümdeki zaman etiketi, dersin o kısmının videodaki aralığıdır; tıklayınca ses o saniyeden "
                    "çalar. Görsellere tıklayınca büyürler.",
    },
}

# Strings the page script needs at runtime.
_SCRIPT_KEYS = ("calib_line", "cat_illusion", "cat_shaky", "cat_under", "cat_solid", "cat_pending", "cat_open",
                "reset_confirm", "front", "back", "cards_done", "cards_count")


def _words(*texts) -> int:
    return sum(len(_WORD.findall(text or "")) for text in texts)


def _callout(callout: dict, ui: dict, section: str) -> dict:
    kind = callout.get("type", "note")
    if kind not in CALLOUT_TYPES:
        raise NoteError(f"Unknown callout type '{kind}' in section '{section}'")
    return {"type": kind, "title": callout.get("title") or ui[f"callout_{kind}"], "body": _md(callout.get("body"))}


def _context(out: Path, study: dict, segments: dict) -> dict:
    language = study.get("language") or "tr"
    ui = ui_strings(language)
    ui.update(STUDY_UI["en"])
    ui.update(STUDY_UI.get(language.split("-")[0].lower(), {}))
    slides = {slide["no"]: slide for slide in segments["slides"]}
    embedded: dict[int, dict] = {}

    def image(number: int) -> dict:
        if number not in embedded:
            embedded[number] = {"src": _embed(out / slides[number]["image"]), "alt": f"{ui['slide']} {number}"}
        return embedded[number]

    parts, count, titled, core_words, all_words = [], 0, 0, 0, 0
    for part in study.get("parts") or []:
        sections = []
        for sec in part.get("sections") or []:
            count += 1
            numbers = sec.get("slides") or []
            shown = sec.get("images", numbers)
            if not sec.get("title") or not numbers or not sec.get("idea"):
                raise NoteError(f"Section {count} needs a title, an idea and slides")
            unknown = sorted({n for n in numbers + shown if n not in slides})
            if unknown:
                raise NoteError(f"Section '{sec['title']}' refers to unknown slides {unknown}")
            callouts = sec.get("callouts") or []
            key = [c for c in callouts if c.get("type") == "key"]
            more = [c for c in callouts if c.get("type") != "key"]
            core = _words(sec.get("idea"), sec.get("explain"), *(c.get("body") for c in key))
            core_words += core
            all_words += core + _words(sec.get("details"), *(c.get("body") for c in more))
            start = min(slides[n]["start"] for n in numbers)
            end = max(slides[n]["end"] for n in numbers)
            sections.append({
                "id": f"s{count:02d}",
                "title": sec["title"],
                "toc_title": sec.get("toc_title") or sec["title"],
                "original_title": sec.get("original_title"),
                "start": start,
                "start_label": clock(start),
                "time_label": f"{clock(start)}–{clock(end)}",
                "slide_label": ", ".join(str(n) for n in numbers),
                "images": [image(n) for n in shown if slides[n].get("image")],
                "narrow": bool(sec.get("narrow")),
                "idea": _md(sec.get("idea"), inline=True),
                "explain": _md(sec.get("explain")),
                "details": _md(sec.get("details")),
                "key_callouts": [_callout(c, ui, sec["title"]) for c in key],
                "more_callouts": [_callout(c, ui, sec["title"]) for c in more],
                "has_more": bool(sec.get("details") or more),
                "checks": [{"q": _md(check["q"], inline=True), "a": _md(check["a"])} for check in sec.get("checks") or []],
            })
        label = None
        if part.get("title"):
            label = f"{ui['part']} {ROMAN[titled] if titled < len(ROMAN) else titled + 1}"
            titled += 1
        parts.append({"title": part.get("title"), "label": label, "sections": sections})

    meta = study.get("meta") or {}
    summary = study.get("summary") or {}
    has_audio = (out / "audio.m4a").exists()
    minutes = lambda words: ui["minutes"].replace("{min}", str(max(1, round(words / WORDS_PER_MINUTE))))
    return {
        "lang": language,
        "ui": ui,
        "script_ui": {key: ui[key] for key in _SCRIPT_KEYS},
        "meta": meta,
        "title": meta.get("title") or segments["video"]["name"],
        "storage_key": out.name,
        "duration_label": clock(segments["video"]["duration"]),
        "goals": [_md(goal, inline=True) for goal in study.get("goals") or []],
        "summary": {"thesis": _md(summary.get("thesis"), inline=True),
                    "points": [_md(point, inline=True) for point in summary.get("points") or []]},
        "parts": parts,
        "section_count": count,
        "cards": [{"front": card["front"], "back": card["back"]} for card in study.get("cards") or []],
        "glossary": [{"term": item["term"], "original": item.get("original"),
                      "definition": _md(item.get("definition"), inline=True)} for item in study.get("glossary") or []],
        "has_audio": has_audio,
        "has_transcript": (out / "transcript.txt").exists(),
        "core_words": core_words,
        "all_words": all_words,
        "reading_study": minutes(core_words),
        "reading_read": minutes(all_words),
    }


def render_study(out: Path, log=print) -> list[Path]:
    study_path = out / "study.json"
    if not study_path.exists():
        raise NoteError(f"{study_path} not found.")
    study = load_json(study_path)
    segments = load_json(out / "segments.json")
    template = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True,
                           trim_blocks=True, lstrip_blocks=True).get_template("study.html.j2")
    context = _context(out, study, segments)

    written = []
    for is_study, name in ((True, "study.html"), (False, "read.html")):
        path = out / name
        path.write_text(template.render(**context, study=is_study), encoding="utf-8")
        written.append(path)
    cards_path = out / "cards.csv"
    with cards_path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows([card["front"], card["back"]] for card in context["cards"])
    written.append(cards_path)

    checks = sum(len(sec["checks"]) for part in context["parts"] for sec in part["sections"])
    log(f"Study page: {written[0]}")
    log(f"Reading page: {written[1]}")
    log(f"  {context['section_count']} sections, {checks} questions, {len(context['cards'])} cards · "
        f"default view {context['core_words']} words ({context['reading_study']}), "
        f"everything {context['all_words']} words ({context['reading_read']})")
    return written
