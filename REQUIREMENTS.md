# Wiki Software — Requirements

## 1. Goals

- Single-file application — the entire server is one `.py` file.
- Minimal lines of code (target: < 120 LOC excluding blank lines and comments).
- No build step, no bundler, no database — runs with `python wiki.py`.
- Browser-based UI; no JavaScript framework required.
- Feature parity with DokuWiki's core authoring experience.

---

## 2. Technology Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Language | Python 3.11+ | Concise, batteries-included |
| Web framework | FastAPI + Uvicorn | Async, typed, auto `/docs`, ~5 extra LOC vs Bottle |
| Markup parser | Custom (target < 60 LOC) | No external dep; full control over syntax |
| Storage | Plain `.wiki` files on disk | Human-readable, git-friendly |
| Templating | f-strings / inline HTML | Avoids Jinja2 dependency |
| Styling | Inline `<style>` block | No external stylesheet file |

---

## 3. Markup Language

### 3.1 Design Principles

- Human-readable in raw form.
- DokuWiki-compatible heading syntax (`=`) so existing DokuWiki content is portable.
- No ambiguity: each construct has exactly one syntax.

### 3.2 Headings

DokuWiki convention: **more equals signs = bigger heading**.

| Syntax | Output | Role |
|--------|--------|------|
| `====== Title ======` | `<h1>` | Page title (biggest) |
| `===== Section =====` | `<h2>` | Independently editable section boundary |
| `==== Sub-section ====` | `<h3>` | Sub-section |
| `=== Sub-sub-section ===` | `<h4>` | |
| `== Minor heading ==` | `<h5>` | Smallest heading |

- Headings must occupy their own line.
- Each heading generates an `id` anchor derived from its text (lowercase, spaces → `-`).
- Section editing applies to `=====` (h2) headings, matching DokuWiki behaviour.

### 3.3 Lists

```
  * Bullet item        (unordered)
    * Nested bullet
  - Numbered item      (ordered)
    - Nested numbered
```

- 2 spaces per indent level; max 3 levels.

### 3.4 Todo Checkboxes

```
[ ] Task not started
[x] Task complete
[~] Task in progress
```

- May appear standalone or inside a list item.
- Clicking the checkbox in the rendered view toggles its state and persists it immediately (no full-page save).

### 3.5 Inline Formatting

| Syntax | Result |
|--------|--------|
| `**bold**` | **bold** |
| `//italic//` | *italic* |
| `__underline__` | underlined |
| `` `code` `` | inline code |
| `~~strikethrough~~` | ~~struck~~ |

### 3.6 Links

| Syntax | Behaviour |
|--------|-----------|
| `[[PageName]]` | Internal wiki link (current namespace) |
| `[[ns:PageName]]` | Internal link into namespace `ns` |
| `[[ns:sub:PageName]]` | Nested namespace link |
| `[[:PageName]]` | Explicit root-namespace link |
| `[[PageName\|Label]]` | Internal link with custom label |
| `[[https://…]]` | External link (opens new tab) |
| `[[https://…\|Label]]` | External link with label |

- `:` is the namespace separator (DokuWiki-compatible).
- A bare `[[PageName]]` without `:` resolves relative to the current page's namespace.
- A leading `:` forces resolution from the root namespace.
- Non-existent internal pages render as a styled "create" link.

### 3.7 Code Blocks

````
```python
code here
```
````

- Language tag optional; enables syntax highlighting via highlight.js (CDN).

### 3.8 Horizontal Rule

`----` (four dashes on their own line) → `<hr>`.

---

## 4. Page Storage

- Each page stored as `pages/<PageName>.wiki` (UTF-8 plain text).
- Namespaced pages stored in subdirectories: `ns:sub:Page` → `pages/ns/sub/Page.wiki`.
- Namespace segment rules: same character set as page names (`[A-Za-z0-9_-]`); each segment becomes one directory level.
- Optional front-matter block (not rendered):
  ```
  ~~META:
  created: 2026-03-29
  tags: project, notes
  ~~
  ```
- Page names: alphanumeric + underscores + hyphens; case-sensitive.
- `Home` (root namespace) is the default landing page.
- Each namespace directory may contain a special `_index.wiki` page that is shown when browsing the namespace.

---

## 5. Server Endpoints

| Method | Path | Description |
|--------|------|-------------|
- `{name}` in all routes is a **full page path** that may contain `/` as the namespace separator on the URL (mapped from `:` in markup), e.g. `/wiki/projects/alpha/Home`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Redirect → `/wiki/Home` |
| GET | `/wiki/{name:path}` | Render page (`:path` allows slashes) |
| GET | `/edit/{name:path}` | Full-page edit form |
| POST | `/edit/{name:path}` | Save full page |
| GET | `/edit/{name:path}/section/{idx}` | Edit single section by heading index |
| POST | `/edit/{name:path}/section/{idx}` | Save single section back into page |
| POST | `/toggle/{name:path}/{line}` | Toggle checkbox state (AJAX, no page reload) |
| GET | `/new` | Create new page form |
| GET | `/ns/{ns:path}` | Browse a namespace (list pages + sub-namespaces) |
| GET | `/sitemap` | Site map: tree of all pages and namespaces |
| GET | `/search?q={query}` | Full-text search results page |
| POST | `/delete/{name:path}` | Delete a page (with confirmation) |

---

## 6. Page Reader View (`GET /wiki/{name}`)

The default view for every page. Raw markup is never shown here.

- Renders the full page as HTML with all markup interpreted.
- **Navigation bar** (top): wiki name/logo, search box, **[new page]** button.
- **Page toolbar** (below nav): page name, last-modified timestamp, **[edit page]** button.
- **Table of Contents sidebar** (right side): auto-generated from all headings on the page; floated to the right of the page body.
  - Each entry is an `<a href="#anchor">` jump link to the corresponding heading.
  - Entries are indented to reflect heading level (h1 → h2 → h3).
  - Collapsible (toggle button at the top of the sidebar).
  - Stays visible while scrolling (CSS `position: sticky`).
- Each `==` section heading has an inline **[edit]** button on the right.
- Todo checkboxes are rendered as clickable `<input type="checkbox">`; toggling one persists the change immediately via a background POST (no page reload).
- Internal links to non-existent pages are styled distinctly (e.g. dashed underline) and navigate to the editor for that page.
- Non-existent page: reader shows a *"This page does not exist — [create it?]"* notice instead of an error.

---

## 7. Page Editor View (`GET /edit/{name}`)

A separate, dedicated editing mode — never mixed into the reader view.

- **Full-page editor**: a single `<textarea>` containing the complete raw `.wiki` source of the page.
- **Toolbar** above the textarea:
  - Page name (editable for rename, v2)
  - **[save]** button → `POST /edit/{name}` → redirects back to reader.
  - **[cancel]** button → returns to reader without saving.
  - **[preview]** button → renders a live preview below the textarea (same parser, no save).
- **Section editor** (inline, within reader): clicking an **[edit]** button beside a `==` heading replaces that section in the reader with a smaller `<textarea>` containing only that section's markup.
  - **[save section]** → `POST /edit/{name}/section/{idx}` → splices content back into the file; re-renders full page.
  - **[cancel]** → collapses editor back to rendered view without saving.
- Editor textarea uses a monospace font; tab key inserts two spaces.
- On `GET /edit/{name}` for a non-existent page, the textarea is pre-filled with a starter template.

---

## 8. General UI / UX

- Responsive single-column layout; readable on mobile.
- Full-text search across all `.wiki` files (`str.find`; no index needed for personal scale).
- Search results page lists matching pages with the matched line shown as a snippet.
- Consistent header across both views; active mode (read / edit) visually indicated.
- No JavaScript framework — vanilla JS only for checkbox toggle and section editor toggle.

---

## 9. Namespaces

- Namespaces map directly to subdirectory trees under `pages/`.
- Namespace separator in markup and URLs: `:` in wiki syntax, `/` in URLs.
- Conversion: `ns:sub:Page` ↔ URL `/wiki/ns/sub/Page` ↔ file `pages/ns/sub/Page.wiki`.
- **Namespace index** (`GET /ns/{path}`): shows all pages and sub-namespaces within that namespace, with last-modified dates.
- The site map (`GET /sitemap`) links to both individual pages and namespace indexes.
- **Breadcrumb trail** in the reader/editor header reflects the full namespace path, e.g. `root > projects > alpha > Home`; each segment links to its namespace index.
- Creating a page in a new namespace automatically creates the required directories.
- Deleting the last page in a namespace does **not** automatically remove the directory (avoids accidental data loss).
- `_index.wiki` in any namespace directory is shown automatically when browsing that namespace.

---

## 10. Site Map

- `GET /sitemap` renders a tree of all namespaces and `.wiki` files under `pages/`, sorted alphabetically.
- Each page entry links to the reader view; each namespace entry links to its namespace index.
- Shows last-modified date beside each page name.
- Accessible from the navigation bar on every page.

---

## 11. Startup Behaviour

- On first run, automatically create `pages/` directory if it does not exist.
- If `pages/Home.wiki` does not exist, create it with a default welcome template.
- Host and port configurable via environment variables `WIKI_HOST` (default `127.0.0.1`) and `WIKI_PORT` (default `8080`).
- Pages directory path configurable via `WIKI_PAGES_DIR` (default `pages/`).

---

## 12. Security

- **Page name validation**: each namespace segment and page name must match `[A-Za-z0-9_-]`; reject all other characters with HTTP 400. This prevents path traversal (e.g. `../../etc/passwd`). The resolved file path must always be confirmed to lie within `pages/` before any read or write.
- **HTML escaping**: all user-supplied content (page source) must be HTML-escaped before being inserted into any template, then selectively un-escaped only for the parser's own output. Raw user strings must never be interpolated directly into HTML.
- **XSS in markup**: the parser must sanitise rendered output — no raw `<script>` or event attributes allowed through link or formatting syntax.
- **File write safety**: page saves must write to a temporary file then atomically rename to prevent partial writes.
- **No shell execution**: the server must never pass user input to a shell command.

---

## 13. Error Handling

| Situation | Behaviour |
|-----------|-----------|
| Page not found | Reader shows "does not exist" notice with create link (not HTTP 404) |
| Invalid page name | HTTP 400 with plain error message |
| Disk write failure | HTTP 500; error shown in editor; original file untouched |
| Section index out of range | HTTP 400 |
| Unknown route | HTTP 404 plain text |

- Errors in the editor never discard the user's unsaved content — error is shown above the textarea.

---

---

## 14. Non-Goals (v1)

- User authentication or access control.
- Version history / diff / rollback.
- File or image uploads.
- Tables in markup.
- Plugin or extension system.
- Multi-user conflict resolution.
- Page rename (post-creation).
- WYSIWYG / rich-text editor.

---

## 15. Open Questions

1. **Heading syntax**: keep DokuWiki-style `=` or switch to Markdown `#` to reuse `mistune`/`markdown-it` and save ~40 parser LOC?
2. **Checkbox persistence**: toggle in-place inside the `.wiki` file (mutates source) or sidecar `.state` file?
3. **highlight.js**: CDN include (zero LOC, requires internet) or omit syntax highlighting to stay fully offline?
4. **Search**: substring scan is simple but slow at scale — acceptable for a personal wiki?
