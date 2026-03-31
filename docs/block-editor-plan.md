# Block Editor — Design Plan

## Overview

A visual block-based editor that lets users edit a wiki page **entirely in the browser** without touching raw markup.  
Every edit is performed client-side; the server is contacted only once (on load via a JSON endpoint) and once (on save via an existing form endpoint), after which the browser redirects to the reader view.

The block editor supports two modes:

| Mode | Route | Edits | Saves to |
|---|---|---|---|
| **Whole page** | `/block-edit/{name}` | All blocks in the page | `POST /edit/{name}` |
| **Section** | `/block-sect/{name}/{idx}` | Only the blocks within one section (any heading level h1–h5, configurable via `SECTION_EDIT_MIN`/`SECTION_EDIT_MAX`) | `POST /sect/{name}/{idx}` |

Both modes share the same JS file and the same editor UI — the only difference is the scope of markup loaded and the endpoint used on save.

Section editing mirrors the existing raw-markup section editor exactly:
- Sections are identified by `find_editable_sections(src, SECTION_EDIT_MIN, SECTION_EDIT_MAX)`, which supports **h1–h5** (default: h1–h4). Each section spans from its heading down to the next heading of equal or higher importance.
- Sections can be **nested** — e.g., clicking `[block edit]` on an h3 inside an h2 edits only the h3 block and its content, not the surrounding h2 section.
- The `idx` in the route is the sequential index into the `find_editable_sections` result list, exactly as used by the existing `/sect/{name}/{idx}` routes.

Each mode has a corresponding **lightweight HTML shell** that:
1. Mounts `<div id="block-editor-root" data-page="{name}" [data-sect="{idx}"]></div>`.
2. Loads the single **cacheable JS file** (`/static/block-editor-{hash}.js`).
3. The JS, once loaded, detects whether `data-sect` is present and calls either `GET /raw/{name}` or `GET /raw-sect/{name}/{idx}` to fetch the markup scope. The editor then builds itself entirely in the browser.

The JS file is hashed and served with `Cache-Control: immutable` exactly like the existing `app-{hash}.js`.  
The HTML shell carries **no markup content** — it is truly cacheable and decoupled from the page data.

---

## What a "Block" Is

The markup is split into a flat list of **blocks**. A block is one logical unit that maps to one or a few raw markup lines.

| Block type | Raw markup example |
|---|---|
| `heading` | `====== Page Title ======` |
| `paragraph` | One or more consecutive non-blank text lines (each line is individually editable) |
| `todo` | `[ ] Task text` / `[x]` / `[~]` (with optional leading indent; one block per line) |
| `bullet` | `  * Item` (2-space indented `*`; one block per line; indent level adjustable) |
| `ordered` | `  - Item` (2-space indented `-`; one block per line; indent level adjustable) |
| `hr` | `----` |
| `code_fence` | ` ```lang … ``` ` (multi-line, treated as a single block; language field is unlabeled by default) |
| `table` | Consecutive `^…^` / `|…|` rows (edited as raw textarea) |
| `image` | `{{image.png\|alt}}` (a paragraph that is solely an image embed) |
| `meta` | `~~META: … ~~` front-matter block (edited as raw textarea) |
| `blank` | One or more blank lines (preserved as spacing between blocks) |

A **raw/other** fallback type exists for lines that don't fit the above — displayed as a textarea the user can edit directly.

---

## Parsing — Markup → Blocks (client-side)

The JS parser reads the raw markup string top-to-bottom and groups lines into blocks.

**Rules (in priority order):**

1. `~~META:` at line 0 → consume until `~~` → `meta` block.
2. Four or more dashes alone on a line → `hr` block.
3. Triple-backtick line → consume until closing triple-backtick → `code_fence` block.
4. A line matching `^={2,6}\s+.+\s+={2,6}$` → `heading` block.
5. A line matching `^\s*\[[ x~]\] ` → `todo` block (one block per line).
6. A line matching `^ {2,}\* ` → `bullet` block (one block per line).
7. A line matching `^ {2,}- ` → `ordered` block (one block per line).
8. A line starting with `^` or `|` → `table` block (consume until the row pattern breaks or a blank line).
9. A line matching `^\{\{.+\}\}$` (sole image on line) → `image` block.
10. Blank line → collect consecutive blanks; emit one `blank` block (preserving blank-line count for round-trip fidelity).
11. Everything else → `paragraph` block; consume consecutive non-blank lines that don't match any of the above patterns. **Each line is stored individually** as a sub-row within the paragraph block.

### Round-trip guarantee

Each block stores its **original raw line(s)** alongside the parsed representation.  
On save, the reconstructed markup is built by serializing each block — blank lines between blocks are preserved via the `blank` blocks.

---

## Serializing — Blocks → Markup (client-side)

Each block type has a `serialize()` function:

| Block type | Serialization rule |
|---|---|
| `meta` | Emit lines verbatim |
| `heading` | `${'='.repeat(level)} ${text} ${'='.repeat(level)}` |
| `paragraph` | Each sub-row joined with `\n` |
| `todo` | `${' '.repeat(indent)}[${state}] ${text}` |
| `bullet` | `${' '.repeat(indent + 2)}* ${text}` |
| `ordered` | `${' '.repeat(indent + 2)}- ${text}` |
| `hr` | `----` |
| `code_fence` | Emit lines verbatim (including the fence lines) |
| `table` | Emit rows verbatim |
| `image` | `{{${src}\|${alt}}}` |
| `blank` | Empty string × blank-line count (joined by `\n`) |
| `raw` | Lines verbatim |

The full markup is `blocks.map(b => b.serialize()).join('\n')`.

---

## Editor UI

### Layout

```
┌────────────────────────────────────────────────────────┐
│  [← Cancel]   PageName   [💾 Save]   [↩ Undo] [↷ Redo]│  ← toolbar (sticky top)
├────────────────────────────────────────────────────────┤
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │  ⠿  ====== Page Title ======              [h1]  │  │  ← heading block
│  └──────────────────────────────────────────────────┘  │
│  [+] ▼ insert block here                               │
│  ┌──────────────────────────────────────────────────┐  │
│  │  ⠿  [ ] Task one              [⬅] [➡]     [☐]  │  │  ← todo block (indent controls)
│  └──────────────────────────────────────────────────┘  │
│  [+] ▼ insert block here                               │
│  ...                                                   │
└────────────────────────────────────────────────────────┘
```

### Block card

Each block is rendered as a **card** with:
- **Drag handle** (⠿ grip icon) on the left → drag-and-drop to reorder (mouse and touch).
- **Content area** in the middle, which is *editable in place*.
- **Type badge** label on the right (small pill: `h2`, `todo`, `bullet`, etc.) — clicking it opens a **type-change menu**.
- **Delete button** (×) — visible on hover/focus.

### Inline editing per block type

| Block type | Edit widget |
|---|---|
| `heading` | Single `<input type="text">` (text only; level changed via type badge H1–H5) |
| `paragraph` | Each line is its own auto-growing single-line `<input type="text">`. Enter appends a new line-row; Backspace on empty line-row removes it. |
| `todo` | `<input type="text">` + checkbox (cycles `[ ]`→`[x]`→`[~]` locally) + ⬅ (outdent) / ➡ (indent) buttons |
| `bullet` / `ordered` | `<input type="text">` + ⬅ (outdent) / ➡ (indent) buttons |
| `hr` | Read-only "— Horizontal rule —" label |
| `code_fence` | `<textarea>` (monospace) with an unlabeled language `<input>` above it |
| `table` | Raw `<textarea>` |
| `image` | `<input>` for filename + `<input>` for alt text |
| `meta` | Raw `<textarea>` |
| `blank` | Visual spacer; not directly editable (blank blocks are created/removed via the "insert block" menu) |
| `raw` | `<textarea>` |

### Paragraph line rows

Because `LINEBREAK_ON_NEWLINE = True` by default (each `\n` renders as `<br>`), every line within a paragraph is meaningful. The paragraph block therefore shows them as a **stack of individual text inputs**, one per line:

```
┌─────────────────────────────────────────────┐
│ ⠿  [Line one text input              ]  [p] │
│    [Line two text input              ]       │
│    [Line three text input            ]       │
└─────────────────────────────────────────────┘
```

- **Enter** in a line-row → inserts a new empty row below and focuses it.
- **Backspace** on an empty (or at position 0) line-row → merges with the row above (or removes it if it was the last row).

### Insert block

Between every pair of adjacent blocks (and at the very top and bottom) there is a subtle **"+ Add block"** seam. Clicking it opens a **block-type picker** popup:

- Paragraph
- Heading (H1 … H5 sub-menu)
- ☐ Todo item
- • Bullet item
- 1. Ordered item
- `</>` Code block
- — Horizontal rule
- Table (inserts a 2×2 skeleton)
- 🖼 Image

The new block is inserted at that position, immediately pushed onto the undo stack, and focused.

### Drag-and-drop reorder (mouse + touch)

Blocks can be dragged by their grip handle to reorder (within the editable scope — whole page or single section).

**Mouse:** HTML5 `dragstart` / `dragover` / `drop` events (same pattern as the existing todo reorder in the reader view).

**Touch:** `touchstart` / `touchmove` / `touchend` events on the grip handle:
- `touchstart` → record the block being dragged, add a floating clone of the card to follow the finger.
- `touchmove` → move the clone, hit-test other block cards to determine the drop target.
- `touchend` → splice the dragged block into the new position, destroy the clone, push to undo stack.

---

## Undo / Redo

A **custom undo stack** tracks structural changes to the block list. Each undoable action is a snapshot of the entire `blocks` array (serialized to markup strings, so memory cost is proportional to page size × history depth).

| Action | Pushed to undo stack |
|---|---|
| Insert block | ✓ |
| Delete block | ✓ |
| Move block (drag reorder) | ✓ |
| Change block type | ✓ |
| Indent / outdent | ✓ |
| Text edit (on blur / debounced) | ✓ (debounced 800 ms after last keystroke) |

- **Ctrl+Z / Cmd+Z** → undo; **Ctrl+Shift+Z / Cmd+Shift+Z** → redo.
- Toolbar Undo / Redo buttons also provided.
- Max stack depth: 100 entries.
- When a new action is taken after an undo, the redo branch is discarded (standard linear undo model).

---

## Save flow

### Whole-page mode

1. User clicks **Save**.
2. JS serializes all blocks back to markup text.
3. JS creates a hidden `<form>` posting to `POST /edit/{name}` with `<textarea name="content">` and submits.
4. Server writes the file, redirects to `/wiki/{name}`.

### Section mode

1. User clicks **Save section**.
2. JS serializes only the section blocks back to markup text.
3. JS creates a hidden `<form>` posting to `POST /sect/{name}/{idx}` with `<textarea name="content">` and `<input name="anchor">` (the section anchor received from `GET /raw-sect`) and submits.
4. Server splices the section back into the full page using the existing `edit_section_post` logic, which correctly handles any heading level h1–h5 and nested sections. Redirects to `/wiki/{name}#{anchor}`.
5. No new save endpoints needed — both `POST /edit/{name}` and `POST /sect/{name}/{idx}` already exist.

**Cancel** navigates back to `/wiki/{name}` (whole-page mode) or `/wiki/{name}#{anchor}` (section mode).

---

## Server changes

Six small additions to `ticktap_wiki.py`:

### 1. `GET /raw/{name}` — whole-page raw markup JSON endpoint

```python
@app.get("/raw/{name:path}")
def raw_page(name: str, _auth=Depends(require_auth)):
    name = normalize_name(name)
    src = read_page(name) or ""
    return JSONResponse({"content": src})
```

Response: `{"content": "<full raw markup>"}`.

### 2. `GET /raw-sect/{name}/{idx}` — section raw markup JSON endpoint

```python
@app.get("/raw-sect/{name:path}/{idx}")
def raw_section(name: str, idx: int, _auth=Depends(require_auth)):
    name = normalize_name(name)
    src = read_page(name) or ""
    sections = find_editable_sections(src, SECTION_EDIT_MIN, SECTION_EDIT_MAX)
    if idx >= len(sections):
        return JSONResponse({"error": "Section not found"}, status_code=404)
    _level, start_line, end_line = sections[idx]
    anchor = _compute_anchor_for_line(src, start_line)
    content = "\n".join(src.split("\n")[start_line:end_line])
    return JSONResponse({"content": content, "anchor": anchor})
```

Response: `{"content": "<section markup>", "anchor": "section-heading-id"}`.

### 3. `GET /block-edit/{name}` — whole-page block editor shell

```python
@app.get("/block-edit/{name:path}", response_class=HTMLResponse)
def block_edit(request: Request, name: str, _auth=Depends(require_auth)):
    name = normalize_name(name)
    body = (f'<div id="block-editor-root" data-page="{html.escape(name)}"></div>'
            f'<script src="{BLOCK_EDITOR_JS_URL}" defer></script>')
    return HTMLResponse(shell(f"Block Edit — {name}", body, request=request))
```

### 4. `GET /block-sect/{name}/{idx}` — section block editor shell

```python
@app.get("/block-sect/{name:path}/{idx}", response_class=HTMLResponse)
def block_sect(request: Request, name: str, idx: int, _auth=Depends(require_auth)):
    name = normalize_name(name)
    body = (f'<div id="block-editor-root" data-page="{html.escape(name)}" data-sect="{idx}"></div>'
            f'<script src="{BLOCK_EDITOR_JS_URL}" defer></script>')
    return HTMLResponse(shell(f"Block Edit section — {name}", body, request=request))
```

### 5. `GET /static/block-editor-{h}.js` — immutable JS

Hashed and served with `Cache-Control: public, max-age=31536000, immutable`:

```python
BLOCK_EDITOR_JS      = open("block_editor.js").read()   # or inline as a string
BLOCK_EDITOR_JS_HASH = hashlib.sha256(BLOCK_EDITOR_JS.encode()).hexdigest()[:12]
BLOCK_EDITOR_JS_URL  = f"/static/block-editor-{BLOCK_EDITOR_JS_HASH}.js"

@app.get("/static/block-editor-{h}.js")
def serve_block_editor_js(h: str):
    if h != BLOCK_EDITOR_JS_HASH:
        return Response(status_code=404)
    return Response(content=BLOCK_EDITOR_JS, media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})
```

### 6. Links in the reader view

**Page toolbar** — a small block-editor icon link placed immediately to the left of the existing `[edit page]` text link, pointing to `/block-edit/{name}`. One icon, no extra label text.

**Section `[edit]` buttons** — a small block-editor icon placed immediately to the left of each existing `[edit]` text link (at every heading level h1–h5), pointing to `/block-sect/{name}/{idx}`. Same approach: one icon, no label.

The icon itself (e.g. `⊞` or a small SVG grid) is chosen during implementation. Both render as `<a class="sect-edit block-edit-icon" href="/block-…">…</a>` so they inherit the existing `.sect-edit` styling with no new CSS needed.

The block editor JS is kept **separate from the existing `app-{h}.js`** so no hash invalidation occurs for existing users.

---

## JS architecture (block-editor JS file)

```
block-editor.js  (single self-contained file, vanilla JS, no bundler)
│
├── PARSER          markupToBlocks(rawText) → Block[]
│     Rules applied top-to-bottom as documented in the Parsing section.
│
├── SERIALIZER      blocksToMarkup(blocks) → string
│     Each block type has serialize(); joined with '\n'.
│
├── BLOCK TYPES     Plain JS objects / classes:
│     HeadingBlock, ParagraphBlock, TodoBlock,
│     BulletBlock, OrderedBlock, HrBlock,
│     CodeFenceBlock, TableBlock, ImageBlock,
│     MetaBlock, BlankBlock, RawBlock
│
├── UNDO STACK      push(snapshot) / undo() / redo()
│     Snapshots are blocksToMarkup() strings.
│     On restore: markupToBlocks() + re-render.
│
├── BLOCK CARD      renderCard(block) → DOM element
│     Grip handle, type badge, content widget, delete button.
│     Emits: change, delete, indent-change, type-change events.
│
├── INSERT HANDLE   renderInsertHandle(index) → DOM element
│     Type picker popup; emits: insert(type, index) event.
│
├── DRAG/DROP       initDragDrop(root)
│     Mouse: HTML5 drag events.
│     Touch: touchstart/move/end on grip handles; floating clone.
│
└── APP             init()
      1. Read data-page (and optional data-sect) from #block-editor-root.
      2. If data-sect present:
           fetch('/raw-sect/' + page + '/' + sect) → store anchor
           mode = 'section', saveAction = '/sect/' + page + '/' + sect
         Else:
           fetch('/raw/' + page)
           mode = 'page', saveAction = '/edit/' + page
      3. Parse markup → render all cards.
      4. Wire Save button → serialize → hidden form submit to saveAction.
           Section mode also includes hidden <input name="anchor"> field.
      5. Wire Cancel → navigate to '/wiki/' + page [+ '#' + anchor if section mode].
      6. Wire Undo/Redo buttons + keyboard shortcuts.
      7. Wire insert / delete / reorder events → undo stack push.
```

---

## Decisions log

| # | Question | Decision |
|---|---|---|
| 1 | Paragraph multi-line | Each line shown as its own `<input>` row |
| 2 | List nesting | One card per line; indent adjustable via ⬅/➡ buttons |
| 3 | Table editing | Raw `<textarea>` fallback |
| 4 | Front-matter | Raw `<textarea>` |
| 5 | Code fence language | Unlabeled; user types the language in a plain input |
| 6 | Undo/redo | Custom undo stack (structural + debounced text changes) |
| 7 | Conflict detection | Silent overwrite (no ETag check) |
| 8 | Mobile reorder | Implemented via touch events |
| 9 | Raw markup loading | JS fetches `GET /raw/{name}` (or `GET /raw-sect/{name}/{idx}`) after page load |
| 10 | Section editing | Supported via `/block-sect/{name}/{idx}`; covers h1–h5 (configurable); nested sections behave identically to the raw editor |
| 11 | Block editor entry points | Small icon to the left of `[edit page]` (whole page) and each `[edit]` section button (all heading levels); no label text, no extra clutter |
