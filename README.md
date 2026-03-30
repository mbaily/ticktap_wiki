# TickTap Wiki

A lightweight personal wiki built for fast task management from your phone browser.

One Python file. No database. No JavaScript framework. Just tap and go.

## Why TickTap?

Most wikis are designed for desktops and long-form documentation. TickTap is built for the way you actually use a personal wiki on your phone:

- **Tap a checkbox** to toggle a task done — no edit mode, no save button
- **Quick-add tasks** from a floating button — type and hit Enter
- **Drag to reorder** your todo list with touch or mouse
- **Daily journal pages** — tap "Today" to jump straight to your current task list
- **Works on any phone browser** — responsive layout, big tap targets, no app install needed

## Features

- **Single-file server** — `python ticktap_wiki.py` and you're running
- **Togglable checkboxes** — `[ ]`, `[x]`, `[~]` cycle states with a tap, saved instantly
- **Quick-add bar** — tap any task, then add a new one right after it
- **Drag-and-drop reorder** — rearrange todos without opening the editor
- **DokuWiki-compatible markup** — headings, lists, tables, bold/italic, links, code blocks
- **Section editing** — edit just one section without touching the rest of the page
- **File attachments** — upload images and files, embed with wiki syntax
- **Page versioning** — automatic snapshots with exponential-decay retention
- **Full-text search** — find anything across all pages
- **Tags** — categorise pages with `~~META:` tags
- **Pinned pages** — bookmark frequently used pages to the nav bar
- **Dark mode** — easy on the eyes at night
- **HTTPS + authentication** — bcrypt passwords, token-based login, rate limiting
- **Zero dependencies beyond Python** — FastAPI + Uvicorn (pip install)

## Quick Start

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
python ticktap_wiki.py
```

Open `http://localhost:8080` in your browser.

### With authentication (recommended)

```bash
python ticktap_wiki.py --adduser alice
python ticktap_wiki.py
```

### With HTTPS

```bash
python ticktap_wiki.py --gencert
python ticktap_wiki.py
```

## Configuration

Edit the `# ── config ──` block at the top of `ticktap_wiki.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `SITE_TITLE` | `"TickTap Wiki"` | Name shown in nav bar and page titles |
| `AUTH_ENABLED` | `True` | Require login |
| `HTTPS_ENABLED` | `True` | Enable TLS |
| `DARK_MODE` | `True` | Dark colour scheme |
| `TODO_CYCLE_3STATE` | `False` | `True` = cycle `[ ]→[x]→[~]→[ ]`; `False` = toggle `[ ]↔[x]` |
| `JOURNAL_PAGE_FORMAT` | `"Todo {yyyy} {mmmm}"` | Template for the "Today" button |
| `DISPLAY_TIMEZONE` | `"Australia/Melbourne"` | Timezone for history timestamps |

## Markup

TickTap uses DokuWiki-compatible syntax:

```
====== Page Title ======
===== Section =====

**bold**  //italic//  `code`  ~~strikethrough~~

[ ] Todo item
[x] Done
[~] In progress

  * Bullet list
  - Numbered list

[[AnotherPage]]  [[ns:Page|Custom label]]  [[https://example.com|Link]]

| Header 1 ^ Header 2 ^
| Cell     | Cell     |
```

See [MARKUP.md](MARKUP.md) for the full reference.

## Requirements

- Python 3.11+
- `pip install fastapi uvicorn`
- `pip install bcrypt` (if using authentication)
- `pip install cryptography` (if generating self-signed certs)

## License

[MIT](LICENSE)
