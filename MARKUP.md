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

## Lists

Lists require **at least 2 spaces** of indent. Each extra 2 spaces adds one nesting level (max 3).

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

Use `*` for bullet lists and `-` for numbered lists. The two types can be mixed at different indent levels.

---

## Todo Checkboxes

```
[ ] Not started
[x] Completed
[~] In progress
```

- Clicking a checkbox in the browser **immediately saves** the new state — no page reload required.
- Checkboxes can appear on their own line or inside a list item.

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
- If the target page does not exist, the link is styled with a dashed underline and clicking it opens the editor for that page.

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

Use a triple-backtick fence. The language name is optional; when supplied it activates highlight.js syntax colouring.

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

[[Page]]   [[ns:Page|Label]]   [[https://…|Label]]
[[file:doc.pdf|label]]
{{image.png|alt text}}

```python
code block
```

----   (horizontal rule)
```
