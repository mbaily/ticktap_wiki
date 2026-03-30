# Wiki Markup Reference

This wiki uses a DokuWiki-compatible markup syntax. This document covers every construct the parser understands.

---

## Headings

More equals signs means a bigger heading — the same convention as DokuWiki.

```
====== Page Title ======        → <h1>  (biggest)
===== Section =====             → <h2>  (section boundary, has [edit] button)
==== Sub-section ====           → <h3>
=== Sub-sub-section ===         → <h4>
== Minor heading ==             → <h5>  (smallest)
```

- The equals signs must be **symmetric** and the heading text must have a space inside on each side.
- Each heading generates an `id` anchor: lowercase, spaces replaced by `-`.
- Duplicate anchor names get a `-2`, `-3` suffix automatically.
- `=====` headings (h2) are the **section boundary** — each gets its own `[edit]` button in the reader view.

---

## Inline Formatting

| Markup | Result |
|--------|--------|
| `**bold**` | **bold** |
| `//italic//` | *italic* |
| `__underline__` | underlined text |
| `` `inline code` `` | `inline code` |
| `~~strikethrough~~` | ~~strikethrough~~ |

These can be combined on the same line but cannot span multiple lines.

---

## Paragraphs and Line Breaks

**Blank line → new paragraph** (always):
```
First paragraph.

Second paragraph.
```

**Single newline behaviour** — controlled by `LINEBREAK_ON_NEWLINE` in the config section of `wiki.py`:

| Setting | Effect |
|---------|--------|
| `LINEBREAK_ON_NEWLINE = True` *(default)* | Each newline renders as `<br>` — lines stay visually separate |
| `LINEBREAK_ON_NEWLINE = False` | DokuWiki default — consecutive lines within a blank-line block are merged into one `<p>` with word-wrap |

---

## Lists

Lists require **at least 2 spaces** of indent. Each extra 2 spaces adds one nesting level.
Use `*` for unordered (bullet) lists and `-` for ordered (numbered) lists.

**Unordered (bullet):**
```
  * First item
  * Second item
    * Nested item
      * Deeply nested
```

**Ordered (numbered):**
```
  - First item
  - Second item
    - Nested item
```

**Mixed nesting** (different types at different levels):
```
  * Bullet top-level
    - Numbered sub-list
    - Another numbered
  * Back to bullets
```

Rendering rules:
- Sub-lists are nested **inside** their parent `<li>`, producing correct indented HTML.
- A blank line between list items ends the list — start a fresh list below it.
- **Quick-add**: clicking any list item in the reader view opens the quick-add bar at the bottom of the screen. Press **Enter** or click ✚ Add to insert a new sibling item at the same indent level. The new item is saved immediately.

---

## Todo Checkboxes

```
[ ] Not started
[x] Completed
[~] In progress
```

**Indented / nested todos** — prefix with spaces in multiples of 2:
```
[ ] Top-level task
  [ ] Sub-task (2 spaces)
    [ ] Deeper sub-task (4 spaces)
      [x] Completed deep task (6 spaces)
```

Each 2-space indent adds 1.5 em of visual left-padding in the rendered view.

- **Checkbox toggle**: clicking a checkbox in the browser **immediately saves** the new state (no page reload).
- **Quick-add**: clicking any todo item opens the quick-add bar at the bottom of the screen. The new item is inserted as a **sibling at the same indent level**. Press **Enter** or click ✚ Add.
- The state marker (`[ ]`, `[x]`, `[~]`) only affects the checkbox appearance; quick-add always inserts a new `[ ]` item.

---

## Tables

Tables use DokuWiki syntax: `^` for header cells, `|` for data cells. Every row must start and end with a delimiter.

**Basic table:**
```
^ Heading 1      ^ Heading 2       ^ Heading 3   ^
| Row 1 Col 1    | Row 1 Col 2     | Row 1 Col 3 |
| Row 2 Col 1    | Row 2 Col 2     | Row 2 Col 3 |
```

**Column span** — place consecutive empty cells using `||` (double pipe):
```
^ Heading 1      ^ Heading 2 (spans 2 cols)       ^^
| Row 1 Col 1    | Row 1 Col 2     | Row 1 Col 3  |
| Row 2 Col 1    | some colspan (double pipe)     ||
| Row 3 Col 1    | Row 3 Col 2     | Row 3 Col 3  |
```

Rules:
- A cell whose content is blank and immediately follows another cell is merged left (colspan).
- Inline markup (**bold**, //italic//, links, images) works inside cells.
- Links with labels `[[Page|label]]` are handled correctly — the `|` in the label is never mistaken for a cell boundary.
- Mixed header (`^`) and data (`|`) rows are allowed anywhere in the table.
- Consecutive table rows form a single table; a blank line or any other block element ends the table.

---

## Links

### Internal wiki links

```
[[PageName]]                    link to a page in the current namespace
[[ns:PageName]]                 link into namespace ns
[[ns:sub:PageName]]             nested namespace
[[:PageName]]                   force root namespace (leading colon)
[[PageName|Custom label]]       link with a display label
```

- A bare `[[PageName]]` (no `:`) is resolved relative to the **current page's namespace**.
- A leading `:` forces resolution from the **root namespace**.
- If the target page does not exist, the link is styled with a dashed underline; clicking it opens the editor for that page.

### External links

```
[[https://example.com]]
[[https://example.com|Visit example.com]]
```

External links open in a new tab with `rel="noopener"`.

### File download links

```
[[file:report.pdf|Download report]]
[[file:ns:report.pdf|Download report]]
```

Renders as a 📄 download anchor. If the file does not exist the link is replaced by a broken-file indicator.

---

## Image Embedding

```
{{photo.png}}
{{photo.png|Alt text}}
{{ns:photo.png|Alt text}}
```

- Double-brace syntax embeds the image inline (scales to fit with `max-width: 100%`).
- Namespace prefix uses `:` as separator.
- If the file does not exist, a `📄 Alt text` placeholder is shown.

---

## Code Blocks

Use a triple-backtick fence. The language name is optional; when supplied it activates syntax highlighting.

````
```python
def hello():
    print("Hello, world!")
```
````

````
```
plain text block, no highlighting
```
````

Unclosed code fences at end-of-file are closed automatically.

---

## Horizontal Rule

Four or more dashes on their own line produces a `<hr>`:

```
----
```

---

## Front Matter

An optional metadata block at the very top of a page. It is **never rendered** in the reader view.

```
~~META:
created: 2026-03-29
tags: project, notes
author: alice
~~
```

- Must start on the first line with `~~META:`.
- Closed by `~~` on its own line.
- Content is free-form; no specific keys are required.

---

## Namespace Separators — Markup vs URL

| Context | Separator | Example |
|---------|-----------|---------|
| Wiki markup | `:` | `[[projects:alpha:Home]]` |
| Browser URL | `/` | `/wiki/projects/alpha/Home` |

The server maps between the two automatically.

---

## Quick Reference Card

```
====== H1 ======     ===== H2 =====     ==== H3 ====

**bold**  //italic//  __underline__  `code`  ~~strike~~

  * bullet            - numbered
    * nested            - nested

[ ] todo   [x] done   [~] in progress
  [ ] nested todo (2 spaces indent)
    [ ] deeper todo (4 spaces indent)

^ Header 1  ^ Header 2  ^        (table header row)
| Cell 1    | Cell 2    |        (table data row)
| Spanning  ||                   (colspan — double pipe)

[[Page]]   [[ns:Page|Label]]   [[https://…|Label]]
[[file:doc.pdf|label]]
{{image.png|alt text}}

----     (horizontal rule)
```
