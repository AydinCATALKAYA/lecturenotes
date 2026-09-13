"""Interface strings of the rendered note. The note body itself is written in the target language."""
from __future__ import annotations

STRINGS = {
    "en": {
        "language_name": "English",
        "contents": "Contents",
        "main_idea": "The lecture in brief",
        "what_on_slide": "What's on the slide",
        "what_was_said": "What was said",
        "callout_key": "Key point",
        "callout_extra": "Additional context",
        "callout_correction": "Correction",
        "callout_note": "Note",
        "glossary": "Glossary",
        "slide": "Slide",
        "slides": "slides",
        "frame": "Frame",
        "frames": "frames",
        "part": "Part",
        "speaker": "Speaker",
        "duration": "Length",
        "note_language": "Note language",
        "download_pdf": "Download PDF",
        "print": "Print",
        "download_audio": "Download audio",
        "transcript": "Transcript",
        "slides_zip": "Slides (ZIP)",
        "frames_zip": "Frames (ZIP)",
        "play_section": "Play this section",
        "zoom": "Enlarge image",
        "close_hint": "Click or press Esc to close",
        "how_to_read": "The time label on each section is when that part of the lecture took place; click it to "
                       "play the audio from there. Click an image to enlarge it. <b>Additional context</b> boxes "
                       "hold background the speaker did not say; <b>Correction</b> boxes flag errors in the "
                       "transcript or on the slides.",
    },
    "tr": {
        "language_name": "Türkçe",
        "contents": "İçindekiler",
        "main_idea": "Dersin ana fikri",
        "what_on_slide": "Görselde ne var?",
        "what_was_said": "Anlatılanlar",
        "callout_key": "Özetle",
        "callout_extra": "Ek bilgi",
        "callout_correction": "Düzeltme",
        "callout_note": "Not",
        "glossary": "Terimler sözlüğü",
        "slide": "Slayt",
        "slides": "slayt",
        "frame": "Kare",
        "frames": "kare",
        "part": "Bölüm",
        "speaker": "Anlatan",
        "duration": "Süre",
        "note_language": "Not dili",
        "download_pdf": "PDF indir",
        "print": "Yazdır",
        "download_audio": "Sesi indir",
        "transcript": "Transkript",
        "slides_zip": "Slaytlar (ZIP)",
        "frames_zip": "Kareler (ZIP)",
        "play_section": "Bu bölümü dinle",
        "zoom": "Görseli büyüt",
        "close_hint": "Kapatmak için tıkla veya Esc'ye bas",
        "how_to_read": "Her bölümdeki zaman etiketi, dersin o kısmının videodaki aralığıdır; tıklayınca ses o "
                       "saniyeden çalar. Görsellere tıklayınca büyürler. <b>Ek bilgi</b> kutuları konuşmacının "
                       "söylemediği arka plan bilgileridir; <b>Düzeltme</b> kutuları transkriptteki veya "
                       "slaytlardaki hataları gösterir.",
    },
}


def ui_strings(language: str) -> dict:
    strings = dict(STRINGS["en"])
    strings.update(STRINGS.get(language.split("-")[0].lower(), {}))
    return strings
