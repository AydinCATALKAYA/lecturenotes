# Study mode (experimental)

## Why

The normal note has everything in it, and that turned out to be a problem. For a 22-minute lecture it was about 6,600 words, so reading it took longer than watching the video. It was also easy to read the whole thing, feel like I understood it, and then not be able to answer a simple question.

Study mode uses the same material but shows it differently. The default view is shorter, and it asks you to answer questions instead of only reading.

## What's on the page

- **Goals.** Three questions at the top, so you know what you should be able to answer at the end.
- **Main idea.** One sentence at the start of every section.
- **Explanation.** The slide and what the speaker said, explained together, right under the image.
- **Details.** Background, derivations and transcript corrections. They are folded so they don't get in the way; open them if you need them.
- **How well did you understand this?** After each section you choose "I understood", "Not sure" or "I didn't".
- **Check yourself.** One question per section. Write your answer first, then open the answer and mark if you got it right.
- **Where you stand.** At the end, the page lists the sections where you said "I understood" but got the question wrong. Those are the ones to go back to.
- **Flashcards.** Cards on the page, and `cards.csv` for Anki.

Everything you type or click is saved only in your browser (`localStorage`). Nothing is sent anywhere.

The same `study.json` also creates `read.html`: the same text with the details open and no questions. I did this so the two could be compared with the same content.

## Where the idea came from

Two papers:

- **Loksa et al. (2016)** taught beginner programmers the steps of solving a programming problem and had them keep track of which step they were on, including when they asked for help. Compared with a group that didn't get this, they worked more independently, did more work on their own initiative, and ended the camp more confident.
- **Prather et al. (2024)** watched 21 students solve a programming task with Copilot and ChatGPT. Students who were already doing well used the tools to go faster. Many of the students who were struggling finished the task too, but they thought they understood more than they did, and what they said afterwards didn't match what the researchers saw.

Both papers are about programming, with small groups of students. I'm not saying they prove study mode works. The "check yourself" and "where you stand" parts are my attempt to avoid the problem the second paper describes: feeling like you understood when you didn't.

Some other well-known findings point the same way:
- Testing yourself helps you remember longer than reading the same material again (Roediger & Karpicke, 2006).
- People often think they've learned more than they have (Dunlosky & Rawson, 2012).

**Study mode has not been tested with real learners.** I don't know yet if it actually helps.

## Writing a study note

These are the rules I used for the example note:

- **Sections.** One idea per section, usually one to four slides. If a figure is built up over several slides, show only the last one. At most two images per section.
- **Main idea.** One sentence that says something. It shouldn't just repeat the title.
- **Explanation.** Around 80–180 words.
  - Only describe the image where it needs explaining: axes, colours, arrows.
  - Use a table for numbers or comparisons.
  - Don't copy the slide text again.
- **Details.** Formulas, references, background the speaker didn't mention, corrections.
- **Questions.** Make the reader use the idea: new numbers, a new situation, a "why" question. Avoid asking for a definition. The answer should fit in one or two sentences.
- **Stay honest.**
  - Keep what the speaker said separate from extra background.
  - Don't invent numbers, names or references.
  - Say when a value is read off a graph.
- **Length.** The default view should take about a third to half of the video's length to read.

## study.json

```json
{
  "language": "en",
  "meta": {"title": "", "original_title": "", "series": "", "speaker": "", "affiliation": ""},
  "goals": ["Markdown"],
  "summary": {"thesis": "Markdown", "points": ["Markdown"]},
  "parts": [{"title": "Part title or null", "sections": [{
    "slides": [20, 21, 22, 23],
    "images": [23],
    "narrow": false,
    "title": "",
    "original_title": "",
    "idea": "One sentence",
    "explain": "Markdown",
    "details": "Markdown, optional",
    "callouts": [{"type": "key | extra | correction | note", "body": "Markdown"}],
    "checks": [{"q": "Markdown", "a": "Markdown"}]
  }]}],
  "cards": [{"front": "plain text", "back": "plain text"}],
  "glossary": [{"term": "", "original": "", "definition": ""}]
}
```

- `slides` sets the time range of the section. `images` chooses which slides are shown; if you leave it out, all of them are shown.
- `key` callouts are always visible. The other types are folded under "Details" in `study.html`.
- In Markdown fields, `((term))` shows the original term in small letters, for example `Sinaps ((synapse))`.

To build the pages:

```bash
lecturenotes study outputs/<video>
```

For now `study.json` has to be written by hand or with Claude Code. The Gemini writer doesn't produce it yet.

## References

- Loksa, D., Ko, A. J., Jernigan, W., Oleson, A., Mendez, C. J., & Burnett, M. M. (2016). Programming, Problem Solving, and Self-Awareness: Effects of Explicit Guidance. In *Proceedings of the 2016 CHI Conference on Human Factors in Computing Systems* (pp. 1449–1461). https://doi.org/10.1145/2858036.2858252
- Prather, J., Reeves, B. N., Leinonen, J., MacNeil, S., Randrianasolo, A. S., Becker, B. A., Kimmel, B., Wright, J., & Briggs, B. (2024). The Widening Gap: The Benefits and Harms of Generative AI for Novice Programmers. In *Proceedings of the 2024 ACM Conference on International Computing Education Research* (pp. 469–486). https://doi.org/10.1145/3632620.3671116
- Roediger, H. L., & Karpicke, M. C. (2006). Test-enhanced learning: Taking memory tests improves long-term retention. *Psychological Science*, 17(3), 249–255.
- Dunlosky, J., & Rawson, K. A. (2012). Overconfidence produces underachievement: Inaccurate self evaluations undermine students' learning and retention. *Learning and Instruction*, 22(4), 271–280.
