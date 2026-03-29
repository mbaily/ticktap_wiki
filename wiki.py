import os, re, html, time, secrets
from pathlib import Path
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
import uvicorn

PAGES_DIR = Path(os.environ.get("WIKI_PAGES_DIR", "pages"))
HOST = os.environ.get("WIKI_HOST", "127.0.0.1")
PORT = int(os.environ.get("WIKI_PORT", "8080"))
FILES_DIR      = Path(os.environ.get("WIKI_FILES_DIR", "files"))
ALLOWED_EXTS   = {"jpg","jpeg","png","gif","webp","svg","pdf","txt","md","csv","zip"}
IMAGE_EXTS     = {"jpg","jpeg","png","gif","webp","svg"}
MAX_FILE_SIZE  = 20 * 1024 * 1024   # 20 MB per file
MAX_TOTAL_SIZE = 100 * 1024 * 1024  # 100 MB per request
app = FastAPI()

# ── storage helpers ────────────────────────────────────────────────────────────

def page_path(name: str) -> Path:
    parts = name.strip("/").split("/")
    for p in parts:
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", p):
            raise ValueError(f"Invalid segment: {p!r}")
    resolved = PAGES_DIR.joinpath(*parts).with_suffix(".wiki").resolve()
    if not resolved.is_relative_to(PAGES_DIR.resolve()):
        raise ValueError("Path traversal attempt")
    return PAGES_DIR.joinpath(*parts).with_suffix(".wiki")

def read_page(name: str) -> str | None:
    p = page_path(name)
    return p.read_text(encoding="utf-8") if p.exists() else None

def write_page(name: str, content: str):
    p = page_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Normalise line endings: browsers send \r\n; Python text-mode write on
    # Windows would then double-expand \r\n → \r\r\n, blowing up blank lines.
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    tmp.replace(p)

def file_path(ns: str, filename: str) -> Path:
    """Validate and return the Path for a stored file. Raises ValueError on bad input."""
    if ns:
        for seg in ns.strip("/").split("/"):
            if not re.fullmatch(r"[A-Za-z0-9_\-]+", seg):
                raise ValueError(f"Invalid ns segment: {seg!r}")
        base = FILES_DIR.joinpath(*ns.strip("/").split("/"))
    else:
        base = FILES_DIR
    if not re.fullmatch(r"[A-Za-z0-9_\-]+\.[A-Za-z0-9]+", filename):
        raise ValueError(f"Invalid filename: {filename!r}")
    target = base / filename
    if not target.resolve().is_relative_to(FILES_DIR.resolve()):
        raise ValueError("Path traversal attempt")
    return target

def strip_meta(src: str) -> tuple[str, int]:
    """Return (stripped_source, number_of_lines_removed_from_top)."""
    if src.startswith("~~META:"):
        # Closing marker is ~~ on its own line (not ~~ embedded in content)
        m = re.search(r"(?m)^~~$", src[7:])
        if m:
            after = src[7 + m.end():].lstrip("\n")
            offset = src.count("\n") - after.count("\n")
            return after, offset
    return src, 0

def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "heading"

# ── markup parser ──────────────────────────────────────────────────────────────

def parse_inline(text: str, cur_ns: str = "") -> str:
    # Stash [[links]] as null-byte placeholders so inline patterns
    # (especially //italic//) cannot match across URL double-slashes.
    stash: list[str] = []
    def stash_link(m):
        stash.append(m.group(0))
        return f"\x00{len(stash)-1}\x00"
    text = re.sub(r"\{\{.+?\}\}|\[\[.+?\]\]", stash_link, text)

    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"//(.+?)//",     r"<em>\1</em>",         text)
    text = re.sub(r"__(.+?)__",     r"<u>\1</u>",           text)
    text = re.sub(r"`(.+?)`",       r"<code>\1</code>",     text)
    text = re.sub(r"~~(.+?)~~",     r"<s>\1</s>",           text)

    def render_media(raw: str) -> str:
        inner = raw[2:-2]
        pm = inner.split("|", 1)
        target = pm[0].strip()
        alt_text = html.escape(pm[1].strip()) if len(pm) > 1 else None
        if not target:
            return html.escape(raw)
        if target.startswith(":"):
            full = target[1:].replace(":", "/")
        elif ":" in target:
            full = target.replace(":", "/")
        else:
            full = (cur_ns + "/" + target).lstrip("/") if cur_ns else target
        f_ns, f_name = full.rsplit("/", 1) if "/" in full else ("", full)
        alt = alt_text or html.escape(Path(f_name).stem)
        try:
            ok = file_path(f_ns, f_name).exists()
        except (ValueError, OSError):
            ok = False
        if not ok:
            return f'<span class="broken-file">&#128206; {alt}</span>'
        return f'<img src="/files/{html.escape(full)}" alt="{alt}" style="max-width:100%;height:auto">'

    def render_link(raw: str) -> str:
        inner = raw[2:-2]  # strip [[ and ]]
        parts = inner.split("|", 1)
        target, label = parts[0].strip(), (html.escape(parts[1].strip()) if len(parts) > 1 else None)
        if not target:
            return html.escape(raw)  # [[]] or [[ ]] — render as plain text
        if target.startswith("file:"):
            ft = target[5:]
            if ft.startswith(":"):
                full = ft[1:].replace(":", "/")
            elif ":" in ft:
                full = ft.replace(":", "/")
            else:
                full = (cur_ns + "/" + ft).lstrip("/") if cur_ns else ft
            f_ns, f_name = full.rsplit("/", 1) if "/" in full else ("", full)
            lbl = label or html.escape(Path(f_name).stem)
            try:
                ok = file_path(f_ns, f_name).exists()
            except (ValueError, OSError):
                ok = False
            if not ok:
                return f'<span class="broken-file">&#128206; {lbl}</span>'
            return f'<a href="/files/{html.escape(full)}">&#128206; {lbl}</a>'
        if target.startswith(("http://", "https://")):
            return f'<a href="{html.escape(target)}" target="_blank" rel="noopener">{label or html.escape(target)}</a>'
        if target.startswith(":"):
            url = target[1:].replace(":", "/")
        elif ":" in target:
            url = target.replace(":", "/")
        else:
            url = (cur_ns + "/" + target).lstrip("/") if cur_ns else target
        lbl = label or html.escape(target.split(":")[-1])
        try:
            exists = page_path(url).exists()
        except ValueError:
            exists = False
        cls = "" if exists else ' class="new-page"'
        return f'<a href="/wiki/{html.escape(url)}"{cls}>{lbl}</a>'

    def restore(m):
        raw = stash[int(m.group(1))]
        return render_media(raw) if raw.startswith("{{") else render_link(raw)

    return re.sub(r"\x00(\d+)\x00", restore, text)


def parse(src: str, name: str = "", section_edit: bool = True) -> tuple[str, list]:
    src, meta_offset = strip_meta(src)
    lines = src.split("\n")
    out, headings, list_stack = [], [], []
    cur_ns = "/".join(name.split("/")[:-1])
    in_code, code_lang, code_lines = False, "", []
    h2_count = 0
    seen_anchors: dict[str, int] = {}

    def close_lists():
        while list_stack:
            out.append(f"</{list_stack.pop()[1]}>")

    for i, line in enumerate(lines):
        # fenced code blocks
        if line.startswith("```"):
            if not in_code:
                close_lists()
                code_lang, in_code, code_lines = line[3:].strip(), True, []
            else:
                lc = f' class="language-{html.escape(code_lang)}"' if code_lang else ""
                out.append(f'<pre><code{lc}>{html.escape(chr(10).join(code_lines))}</code></pre>')
                in_code = False
            continue
        if in_code:
            code_lines.append(line)
            continue

        # horizontal rule
        if re.fullmatch(r"-{4,}", line.strip()):
            close_lists(); out.append("<hr>"); continue

        # headings — DokuWiki style: more = means bigger (6= → h1, 2= → h5)
        hm = re.fullmatch(r"(={2,6}) (.+?) \1", line.rstrip())
        if hm:
            close_lists()
            level, text = 7 - len(hm.group(1)), hm.group(2)
            base_anchor = slug(text)
            if base_anchor in seen_anchors:
                seen_anchors[base_anchor] += 1
                anchor = f"{base_anchor}-{seen_anchors[base_anchor]}"
            else:
                seen_anchors[base_anchor] = 1
                anchor = base_anchor
            headings.append((level, text, anchor))
            edit_btn = ""
            if level == 2 and section_edit and name:
                edit_btn = f' <a class="sect-edit" href="/sect/{name}/{h2_count}">[edit]</a>'
                h2_count += 1
            out.append(f'<h{level} id="{anchor}">{html.escape(text)}{edit_btn}</h{level}>')
            continue

        # todo checkboxes
        cbm = re.match(r"^(\s*)\[([ x~])\] (.*)", line)
        if cbm:
            close_lists()
            state, text = cbm.group(2), parse_inline(cbm.group(3), cur_ns)
            checked = " checked" if state == "x" else ""
            out.append(f'<p class="todo"><input type="checkbox"{checked} data-line="{i + meta_offset}" data-name="{html.escape(name)}"> {text}</p>')
            continue

        # lists — DokuWiki requires minimum 2-space indent; 2 spaces = top-level
        lm = re.match(r"^( {2,})([*\-]) (.+)", line)
        if lm:
            indent = max(0, len(lm.group(1)) // 2 - 1)
            tag = "ul" if lm.group(2) == "*" else "ol"
            text = parse_inline(lm.group(3), cur_ns)
            while len(list_stack) > indent + 1:
                out.append(f"</{list_stack.pop()[1]}>")
            if list_stack and list_stack[-1][1] != tag and len(list_stack) == indent + 1:
                out.append(f"</{list_stack.pop()[1]}>")
            while len(list_stack) <= indent:
                list_stack.append((len(list_stack), tag)); out.append(f"<{tag}>")
            out.append(f"<li>{text}</li>")
            continue

        close_lists()
        if line.strip() == "":
            out.append("")
        else:
            out.append(f"<p>{parse_inline(line, cur_ns)}</p>")

    close_lists()
    # emit any unclosed fenced code block at EOF
    if in_code:
        lc = f' class="language-{html.escape(code_lang)}"' if code_lang else ""
        out.append(f'<pre><code{lc}>{html.escape(chr(10).join(code_lines))}</code></pre>')
    return "\n".join(out), headings


def split_sections(src: str) -> list[str]:
    """Split on ===== Title ===== (h2) headings, keeping the heading with its
    content. Only fully-formed symmetric headings are split points, matching the
    same pattern that parse() uses. Lines inside fenced code blocks are ignored."""
    # Matches a complete h2 heading (===== ... =====) or a ``` fence toggle
    MARKER = re.compile(r"(?m)^(```|===== .+? =====\s*$)")
    parts = []
    last = 0
    in_code = False
    for m in MARKER.finditer(src):
        if m.group(1).startswith("```"):
            in_code = not in_code
        elif not in_code and m.start() != last:
            parts.append(src[last:m.start()])
            last = m.start()
    parts.append(src[last:])
    return parts if parts else [src]

# ── CSS / JS ───────────────────────────────────────────────────────────────────

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font:16px/1.6 system-ui,sans-serif;color:#222;background:#f5f5f5}
nav{background:#2c3e50;color:#fff;padding:.5rem 1rem;display:flex;gap:1rem;align-items:center}
nav a{color:#ecf0f1;text-decoration:none}nav a:hover{text-decoration:underline}
nav form{margin-left:auto}nav input[type=search]{padding:.3rem .6rem;border-radius:4px;border:none}
.toolbar{background:#ecf0f1;padding:.4rem 1rem;display:flex;gap:.6rem;align-items:center;font-size:.9rem;flex-wrap:wrap}
.toolbar a,.toolbar button{color:#2c3e50;background:none;border:1px solid #aaa;padding:.2rem .5rem;border-radius:3px;cursor:pointer;font-size:.85rem;text-decoration:none}
.layout{display:flex;max-width:1100px;margin:1rem auto;gap:1rem;padding:0 1rem}
.content{flex:1;min-width:0;background:#fff;padding:1rem;border-radius:4px;border:1px solid #ddd}
.toc{width:220px;flex-shrink:0;position:sticky;top:1rem;align-self:flex-start;background:#fff;border:1px solid #ddd;border-radius:4px;padding:.6rem;font-size:.85rem}
.toc h3{font-size:.9rem;margin-bottom:.4rem;display:flex;justify-content:space-between}
.toc ul{list-style:none;padding-left:0}.toc li{padding:.15rem 0}
.toc li.h2{padding-left:.8rem}.toc li.h3{padding-left:1.6rem}.toc li.h4{padding-left:2.4rem}.toc li.h5{padding-left:3.2rem}
.toc a{color:#2c3e50;text-decoration:none}.toc a:hover{text-decoration:underline}
h1,h2,h3,h4,h5{margin:1rem 0 .4rem}
h2{border-bottom:1px solid #ddd;padding-bottom:.2rem;display:flex;justify-content:space-between;align-items:center}
p{margin:.4rem 0}pre{background:#f4f4f4;padding:.8rem;border-radius:4px;overflow-x:auto;margin:.5rem 0}
code{background:#f0f0f0;padding:0 .3rem;border-radius:3px;font-size:.9em}pre code{background:none;padding:0}
hr{border:none;border-top:1px solid #ddd;margin:1rem 0}
a.new-page{color:#c0392b;text-decoration:underline dashed}
.sect-edit{font-size:.75rem;color:#888;border:1px solid #ccc;padding:.1rem .3rem;border-radius:3px;text-decoration:none;margin-left:.5rem}
textarea{width:100%;font-family:monospace;font-size:.95rem;padding:.5rem;border:1px solid #ccc;border-radius:4px}
.edit-toolbar{display:flex;gap:.5rem;margin-bottom:.5rem;flex-wrap:wrap;align-items:center}
.edit-toolbar button,.edit-toolbar a{padding:.3rem .7rem;border-radius:3px;border:1px solid #aaa;cursor:pointer;text-decoration:none;font-size:.9rem}
.preview-box{margin-top:1rem;padding:1rem;border:1px dashed #aaa;border-radius:4px;background:#fff}
.notice{background:#ffeeba;border:1px solid #ffc107;padding:.8rem 1rem;border-radius:4px;margin:1rem 0}
.breadcrumb{font-size:.85rem;color:#666;margin-bottom:.5rem}.breadcrumb a{color:#2c3e50}
input[type=checkbox]{cursor:pointer;width:1.1em;height:1.1em;vertical-align:middle}
.search-result{margin:.6rem 0;padding:.5rem;border:1px solid #ddd;border-radius:3px;background:#fff}
.search-result a{font-weight:bold}
.snippet{font-size:.85rem;color:#555;font-family:monospace}
.sitemap ul{list-style:none;padding-left:1.2rem}.sitemap>ul{padding-left:0}
.broken-file{color:#c0392b;font-style:italic}
.content img{max-width:100%;height:auto}
"""

JS = """
document.querySelectorAll('input[type=checkbox][data-line]').forEach(cb=>{
  cb.addEventListener('change',()=>fetch(`/toggle/${cb.dataset.name}/${cb.dataset.line}`,{method:'POST'}));
});
document.querySelectorAll('textarea').forEach(ta=>{
  ta.addEventListener('keydown',e=>{
    if(e.key==='Tab'){e.preventDefault();const s=e.target.selectionStart;
      e.target.value=e.target.value.slice(0,s)+'  '+e.target.value.slice(e.target.selectionEnd);
      e.target.selectionStart=e.target.selectionEnd=s+2;}
  });
});
"""

# ── HTML helpers ───────────────────────────────────────────────────────────────

def nav_bar(search_q: str = "") -> str:
    q = html.escape(search_q)
    return (f'<nav><a href="/wiki/Home"><strong>&#128366; Wiki</strong></a>'
            f'<a href="/sitemap">Site Map</a><a href="/new">+ New Page</a>'
            f'<a href="/orphans">&#128204; Orphaned Files</a>'
            f'<form method="get" action="/search">'
            f'<input type="search" name="q" placeholder="Search…" value="{q}"></form></nav>')

def shell(title: str, body: str, search_q: str = "") -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)} — Wiki</title>'
            f'<style>{CSS}</style></head><body>'
            f'{nav_bar(search_q)}{body}'
            f'<script>{JS}</script></body></html>')

def breadcrumb(name: str) -> str:
    parts = name.split("/")
    crumbs = [f'<a href="/wiki/Home">root</a>']
    for i, p in enumerate(parts[:-1]):
        crumbs.append(f'<a href="/ns/{"/".join(parts[:i+1])}">{html.escape(p)}</a>')
    crumbs.append(html.escape(parts[-1]))
    return f'<div class="breadcrumb">{" &rsaquo; ".join(crumbs)}</div>'

def toc_html(headings: list) -> str:
    if not headings:
        return ""
    items = "".join(
        f'<li class="h{lvl}"><a href="#{anc}">{html.escape(txt)}</a></li>'
        for lvl, txt, anc in headings
    )
    return (f'<div class="toc"><h3>Contents '
            f'<button onclick="var u=this.closest(\'.toc\').querySelector(\'ul\');u.style.display=u.style.display===\'none\'?\'block\':\'none\'">&#177;</button>'
            f'</h3><ul>{items}</ul></div>')

def dir_listing(d: Path, prefix: str) -> str:
    items = "<ul>"
    for child in sorted(d.iterdir()):
        if child.is_dir() and re.fullmatch(r"[A-Za-z0-9_\-]+", child.name):
            rel = f"{prefix}/{child.name}" if prefix else child.name
            items += f'<li>&#128193; <a href="/ns/{rel}">{html.escape(child.name)}/</a></li>'
        elif child.suffix == ".wiki" and not child.name.startswith("_"):
            pname = f"{prefix}/{child.stem}" if prefix else child.stem
            try:
                mtime = time.strftime("%Y-%m-%d", time.localtime(child.stat().st_mtime))
            except OSError:
                mtime = "unknown"
            items += f'<li>&#128196; <a href="/wiki/{pname}">{html.escape(child.stem)}</a> <small style="color:#888">{mtime}</small></li>'
    return items + "</ul>"
def files_section(ns: str) -> str:
    """Return collapsible HTML listing files attached to namespace ns."""
    ns_dir = (FILES_DIR.joinpath(*ns.split("/")) if ns else FILES_DIR)
    attach_url = f"/upload/{ns}" if ns else "/upload"
    if not ns_dir.is_dir():
        return f'<p style="margin-top:1rem"><a href="{attach_url}" target="_blank">&#128206; Attach files</a></p>'
    items = []
    for child in sorted(ns_dir.iterdir()):
        if not child.is_file():
            continue
        ext = child.suffix.lower().lstrip(".")
        if ext not in ALLOWED_EXTS:
            continue
        try:
            st = child.stat()
            size_str = f"{st.st_size // 1024} KB" if st.st_size >= 1024 else f"{st.st_size} B"
            mtime = time.strftime("%Y-%m-%d", time.localtime(st.st_mtime))
        except OSError:
            size_str, mtime = "?", "unknown"
        ns_c = ns.replace("/", ":") if ns else ""
        lbl = re.sub(r"[|{}\[\]]", "_", child.stem)
        if ns_c:
            markup = (f'{{{{{ns_c}:{child.name}|{lbl}}}}}' if ext in IMAGE_EXTS
                      else f'[[file:{ns_c}:{child.name}|{lbl}]]')
        else:
            markup = (f'{{{{{child.name}|{lbl}}}}}' if ext in IMAGE_EXTS
                      else f'[[file:{child.name}|{lbl}]]')
        fp = f"{ns}/{child.name}" if ns else child.name
        del_btn = (f'<form method="post" action="/file-delete/{html.escape(fp)}" style="display:inline">'
                   f'<button type="submit" title="Delete" '
                   f'style="background:none;border:none;cursor:pointer;color:#c0392b">&#128465;</button></form>')
        items.append(
            f'<li style="padding:.2rem 0">&#128206; '
            f'<a href="/files/{html.escape(fp)}">{html.escape(child.name)}</a> '
            f'<small style="color:#888">{size_str}, {mtime}</small> '
            f'<button data-markup="{html.escape(markup)}" '
            f'onclick="navigator.clipboard.writeText(this.dataset.markup)" '
            f'style="font-size:.75rem;padding:.1rem .3rem;cursor:pointer;border:1px solid #aaa;border-radius:3px;background:none">'
            f'copy link</button> {del_btn}</li>'
        )
    attach_link = f'<a href="{attach_url}" target="_blank" style="font-size:.85rem;font-weight:normal">[+ attach]</a>'
    if not items:
        return f'<p style="margin-top:1rem">&#128206; No files. <a href="{attach_url}" target="_blank">Attach files</a></p>'
    return (f'<details style="margin-top:1rem" open>'
            f'<summary style="cursor:pointer;font-weight:bold">&#128206; Attached files ({len(items)}) {attach_link}</summary>'
            f'<ul style="list-style:none;padding:.4rem 0 0 0">{"" .join(items)}</ul></details>')
# ── routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
def root(): return RedirectResponse("/wiki/Home")


@app.get("/wiki/{name:path}", response_class=HTMLResponse)
def view(name: str):
    try:
        src = read_page(name)
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    if src is None:
        body = (f'<div class="layout"><div class="content">{breadcrumb(name)}'
                f'<div class="notice">This page does not exist &mdash; '
                f'<a href="/edit/{name}">create it?</a></div></div></div>')
        return HTMLResponse(shell(name, body), 200)
    rendered, headings = parse(src, name)
    try:
        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(page_path(name).stat().st_mtime))
    except OSError:
        mtime = "unknown"
    toolbar = (f'<div class="toolbar">{breadcrumb(name)}'
               f'<span style="margin-left:auto;font-size:.8rem;color:#666">Modified: {mtime}</span>'
               f'<a href="/edit/{name}">[edit page]</a>'
               f'<a href="/delete/{name}" style="color:#c0392b">[delete]</a></div>')
    body = f'{toolbar}<div class="layout"><div class="content">{rendered}</div>{toc_html(headings)}</div>'
    return HTMLResponse(shell(name.split("/")[-1], body))


@app.get("/sect/{name:path}/{idx}", response_class=HTMLResponse)
def edit_section_get(name: str, idx: int):
    if idx < 0:
        return HTMLResponse("Section not found", 400)
    try:
        src = read_page(name) or ""
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    sections = split_sections(src)
    h2s = [s for s in sections if s.startswith("===== ")]
    if idx >= len(h2s):
        return HTMLResponse("Section not found", 400)
    content = html.escape(h2s[idx])
    body = (f'<div class="layout"><div class="content">{breadcrumb(name)}'
            f'<h2>Edit section</h2>'
            f'<form method="post"><div class="edit-toolbar">'
            f'<button type="submit">Save section</button>'
            f'<a href="/wiki/{name}">Cancel</a></div>'
            f'<textarea name="content" rows="20">{content}</textarea>'
            f'</form></div></div>')
    return HTMLResponse(shell(f"Edit section \u2014 {name}", body))


@app.post("/sect/{name:path}/{idx}", response_class=HTMLResponse)
async def edit_section_post(name: str, idx: int, content: str = Form("")):
    if idx < 0:
        return HTMLResponse("Section not found", 400)
    try:
        src = read_page(name) or ""
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    sections = split_sections(src)
    h2_indices = [i for i, s in enumerate(sections) if s.startswith("===== ")]
    if idx >= len(h2_indices):
        return HTMLResponse("Section not found", 400)
    sections[h2_indices[idx]] = content
    # Ensure removed sections end with \n so the next heading stays on its own line
    sections = [s if s.endswith("\n") else s + "\n" for s in sections[:-1]] + [sections[-1]]
    write_page(name, "".join(sections))
    return RedirectResponse(f"/wiki/{name}", status_code=303)


@app.get("/edit/{name:path}", response_class=HTMLResponse)
def edit_get(name: str):
    try:
        src = read_page(name)
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    if src is None:
        src = f"====== {name.split('/')[-1]} ======\n\n===== Introduction =====\n\nNew page.\n"
    content = html.escape(src)
    ns_for_upload = "/".join(name.split("/")[:-1])
    upload_href = f"/upload/{ns_for_upload}" if ns_for_upload else "/upload"
    body = (f'<div class="layout"><div class="content">{breadcrumb(name)}'
            f'<div class="edit-toolbar">'
            f'<strong>{html.escape(name.split("/")[-1])}</strong>'
            f'<button form="ef" type="submit">Save</button>'
            f'<a href="/wiki/{name}">Cancel</a>'
            f'<button type="button" onclick="showPreview()">Preview</button>'
            f'<a href="{upload_href}" target="_blank">&#128206; Attach</a>'
            f'</div>'
            f'<form id="ef" method="post">'
            f'<textarea name="content" rows="30" id="ed">{content}</textarea>'
            f'</form>'
            f'<div id="pv" class="preview-box" style="display:none"></div>'
            f'</div></div>'
            f'<script>'
            f'async function showPreview(){{'
            f'  const r=await fetch("/preview",{{method:"POST",'
            f'    body:new URLSearchParams({{name:"{name}",content:document.getElementById("ed").value}})}});'
            f'  const d=document.getElementById("pv");'
            f'  d.innerHTML=await r.text();d.style.display="block";'
            f'}}'
            f'</script>')
    return HTMLResponse(shell(f"Edit — {name}", body))


@app.post("/edit/{name:path}", response_class=HTMLResponse)
async def edit_post(name: str, content: str = Form("")):
    try:
        write_page(name, content)
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    except OSError as e:
        return HTMLResponse(f"Save failed: {html.escape(str(e))}", 500)
    return RedirectResponse(f"/wiki/{name}", status_code=303)


@app.post("/preview", response_class=HTMLResponse)
async def preview(name: str = Form(""), content: str = Form("")):
    rendered, _ = parse(content, name, section_edit=False)
    return HTMLResponse(rendered)


@app.post("/toggle/{name:path}/{line}", response_class=HTMLResponse)
async def toggle(name: str, line: int):
    if line < 0:
        return HTMLResponse("Out of range", 400)
    try:
        src = read_page(name)
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    if src is None:
        return HTMLResponse("Not found", 404)
    lines = src.split("\n")
    if line >= len(lines):
        return HTMLResponse("Out of range", 400)
    ln = lines[line]
    # Target only the leading checkbox marker to avoid matching [x] inside the text
    new_ln = re.sub(r"^(\s*)\[([ x~])\]",
                    lambda m: m.group(1) + ("[x]" if m.group(2) != "x" else "[ ]"),
                    ln)
    if new_ln == ln:
        return HTMLResponse("ok")  # not a checkbox line
    lines[line] = new_ln
    write_page(name, "\n".join(lines))
    return HTMLResponse("ok")


@app.get("/new", response_class=HTMLResponse)
def new_page():
    body = ('<div class="layout"><div class="content"><h1>New Page</h1>'
            '<p>Use <code>:</code> for namespaces, e.g. <code>projects:MyPage</code></p>'
            '<form id="nf" onsubmit="event.preventDefault();location.href=\'/edit/\'+document.getElementById(\'ni\').value.replace(/:/g,\'/'+'\')">'
            '<input type="text" name="n" id="ni" style="width:100%;padding:.4rem;font-size:1rem;margin:.5rem 0"'
            ' placeholder="PageName or ns:PageName" pattern="[A-Za-z0-9_\\-:]+" required><br>'
            '<button type="submit">Create</button>'
            '</form></div></div>')
    return HTMLResponse(shell("New Page", body))


@app.get("/ns/{ns:path}", response_class=HTMLResponse)
def ns_view(ns: str):
    for p in ns.strip("/").split("/"):
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", p):
            return HTMLResponse("Invalid namespace", 400)
    ns_dir = PAGES_DIR.joinpath(*ns.strip("/").split("/"))
    if not ns_dir.is_dir():
        return HTMLResponse("Namespace not found", 404)
    ns_clean = ns.strip("/")
    body = (f'<div class="layout"><div class="content">'
            f'<h1>Namespace: {html.escape(ns)}</h1>'
            f'{dir_listing(ns_dir, ns_clean)}'
            f'{files_section(ns_clean)}'
            f'</div></div>')
    return HTMLResponse(shell(f"ns:{ns}", body))


@app.get("/sitemap", response_class=HTMLResponse)
def sitemap():
    def tree(d: Path, prefix: str) -> str:
        s = "<ul>"
        for child in sorted(d.iterdir()):
            if child.is_dir() and re.fullmatch(r"[A-Za-z0-9_\-]+", child.name):
                rel = f"{prefix}/{child.name}" if prefix else child.name
                s += f'<li>&#128193; <a href="/ns/{rel}"><strong>{html.escape(child.name)}/</strong></a>{tree(child, rel)}</li>'
            elif child.suffix == ".wiki" and not child.name.startswith("_"):
                pname = f"{prefix}/{child.stem}" if prefix else child.stem
                try:
                    mtime = time.strftime("%Y-%m-%d", time.localtime(child.stat().st_mtime))
                except OSError:
                    mtime = "unknown"
                s += f'<li>&#128196; <a href="/wiki/{pname}">{html.escape(child.stem)}</a> <small style="color:#888">{mtime}</small></li>'
        return s + "</ul>"
    body = f'<div class="layout"><div class="content sitemap"><h1>Site Map</h1>{tree(PAGES_DIR, "")}</div></div>'
    return HTMLResponse(shell("Site Map", body))


@app.get("/search", response_class=HTMLResponse)
def search(q: str = ""):
    if not q:
        return RedirectResponse("/")
    results = []
    for f in sorted(PAGES_DIR.rglob("*.wiki")):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            if q.lower() in line.lower():
                pname = str(f.relative_to(PAGES_DIR).with_suffix("")).replace("\\", "/")
                snippet = html.escape(line.strip()[:120])
                results.append(f'<div class="search-result"><a href="/wiki/{html.escape(pname)}">{html.escape(pname)}</a>'
                                f'<br><span class="snippet">&hellip;{snippet}&hellip;</span></div>')
                break
    body = (f'<div class="layout"><div class="content">'
            f'<h1>Search: {html.escape(q)}</h1>'
            f'<p>{len(results)} result{"s" if len(results) != 1 else ""}</p>'
            f'{"".join(results) or "<p>No results found.</p>"}'
            f'</div></div>')
    return HTMLResponse(shell(f"Search: {q}", body, search_q=q))


@app.get("/delete/{name:path}", response_class=HTMLResponse)
def delete_get(name: str):
    try:
        page_path(name)  # validate name; raises ValueError on bad input
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    body = (f'<div class="layout"><div class="content">'
            f'<h1>Delete page</h1>'
            f'<div class="notice">Are you sure you want to delete <strong>{html.escape(name)}</strong>?</div>'
            f'<form method="post" style="margin-top:.8rem">'
            f'<input type="hidden" name="confirm" value="yes">'
            f'<button type="submit" style="background:#c0392b;color:#fff;border-color:#a93226">Yes, delete</button>'
            f'&nbsp;<a href="/wiki/{html.escape(name)}">Cancel</a>'
            f'</form></div></div>')
    return HTMLResponse(shell(f"Delete — {name}", body))


@app.post("/delete/{name:path}", response_class=HTMLResponse)
async def delete_post(name: str, confirm: str = Form("")):
    if confirm != "yes":
        return RedirectResponse(f"/wiki/{name}", status_code=303)
    try:
        p = page_path(name)
        if p.exists():
            p.unlink()
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    return RedirectResponse("/wiki/Home", status_code=303)


# ── file upload helpers ────────────────────────────────────────────────────────

_FILE_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif",  "webp": "image/webp", "svg": "image/svg+xml",
    "pdf": "application/pdf", "txt": "text/plain", "md": "text/plain",
    "csv": "text/csv",   "zip": "application/zip",
}

def _upload_page(ns: str, results: list | None) -> HTMLResponse:
    ns_display = ns.replace("/", ":") if ns else "(root)"
    action = f"/upload/{ns}" if ns else "/upload"
    res_html = ""
    if results:
        has_images = any(r.get("ok") and r.get("is_img") for r in results)
        toggle_html = ""
        if has_images:
            toggle_html = (
                '<label style="font-size:.85rem;cursor:pointer;user-select:none">'
                '<input type="checkbox" id="lnk-toggle" style="margin-right:.3rem" onchange="updateSnippet()">'
                'Use <code>[[file:…]]</code> links instead of <code>{{…}}</code> embeds for images'
                '</label><br>'
            )
        rows = "".join(
            f'<tr>'
            f'<td style="padding:.3rem .6rem">{html.escape(r["name"])}</td>'
            f'<td style="padding:.3rem .6rem">{"&#10003;" if r["ok"] else "&#10007; " + html.escape(r.get("error", ""))}</td>'
            f'<td style="padding:.3rem .6rem;font-family:monospace;font-size:.85rem" '
            f'data-embed="{html.escape(r.get("markup_embed", r.get("markup", "")))}" '
            f'data-link="{html.escape(r.get("markup_link",  r.get("markup", "")))}" '
            f'data-isimg="{"1" if r.get("is_img") else "0"}" '
            f'class="markup-cell">{html.escape(r.get("markup", ""))}</td>'
            f'</tr>'
            for r in results
        )
        snippet = "\n".join(r["markup"] for r in results if r.get("ok") and r.get("markup"))
        snip_esc = html.escape(snippet)
        res_html = (
            f'<table style="width:100%;border-collapse:collapse;border:1px solid #ddd;margin:1rem 0">'
            f'<tr style="background:#ecf0f1">'
            f'<th style="padding:.3rem .6rem;text-align:left">File</th>'
            f'<th style="padding:.3rem .6rem;text-align:left">Status</th>'
            f'<th style="padding:.3rem .6rem;text-align:left">Markup</th></tr>{rows}</table>'
            f'{toggle_html}'
            f'<p><strong>Paste into your page:</strong></p>'
            f'<textarea id="snip" rows="{max(2, snippet.count(chr(10)) + 1)}" '
            f'style="width:100%;font-family:monospace">{snip_esc}</textarea><br>'
            f'<button onclick="navigator.clipboard.writeText(document.getElementById(\'snip\').value).then(()=>window.close())" '
            f'style="margin:.5rem 0;padding:.4rem .8rem;cursor:pointer">&#128203; Copy links &amp; close tab</button>'
            f'<script>'
            f'function updateSnippet(){{'
            f'  var useLink=document.getElementById(\'lnk-toggle\')&&document.getElementById(\'lnk-toggle\').checked;'
            f'  var lines=[];'
            f'  document.querySelectorAll(".markup-cell").forEach(function(td){{'
            f'    var m=(useLink&&td.dataset.isimg==="1")?td.dataset.link:td.dataset.embed;'
            f'    if(m){{td.textContent=m;lines.push(m);}}'
            f'  }});'
            f'  document.getElementById(\'snip\').value=lines.join(\'\\n\');'
            f'}}'
            f'</script>'
        )
    body = (
        f'<div class="layout"><div class="content">'
        f'<h1>&#128206; Attach files</h1>'
        f'<p>Namespace: <strong>{html.escape(ns_display)}</strong></p>'
        f'{res_html}'
        f'<form method="post" action="{html.escape(action)}" enctype="multipart/form-data" style="margin-top:1rem">'
        f'<input type="file" name="files" multiple '
        f'accept=".jpg,.jpeg,.png,.gif,.webp,.svg,.pdf,.txt,.md,.csv,.zip" '
        f'style="display:block;margin:.8rem 0;width:100%">'
        f'<button type="submit" style="padding:.4rem .8rem">&#8593; Upload</button>'
        f'</form></div></div>'
    )
    return HTMLResponse(shell(f"Upload — {html.escape(ns_display)}", body))

async def _do_upload(ns: str, files: list[UploadFile]) -> HTMLResponse:
    if ns:
        for seg in ns.strip("/").split("/"):
            if not re.fullmatch(r"[A-Za-z0-9_\-]+", seg):
                return HTMLResponse("Invalid namespace", 400)
    dest = (FILES_DIR.joinpath(*ns.strip("/").split("/")) if ns else FILES_DIR)
    dest.mkdir(parents=True, exist_ok=True)
    results, total = [], 0
    for f in files:
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower().lstrip(".")
        if ext not in ALLOWED_EXTS:
            results.append({"name": f.filename, "ok": False, "error": f".{ext} not allowed"})
            continue
        data = await f.read(MAX_FILE_SIZE + 1)
        if len(data) > MAX_FILE_SIZE:
            results.append({"name": f.filename, "ok": False, "error": "exceeds 20 MB"})
            continue
        total += len(data)
        if total > MAX_TOTAL_SIZE:
            results.append({"name": f.filename, "ok": False, "error": "total exceeds 100 MB"})
            break
        safe_stem = re.sub(r"[^A-Za-z0-9_\-]", "_", Path(f.filename).stem)[:40] or "file"
        uname = f"{safe_stem}_{secrets.token_hex(4)}.{ext}"
        (dest / uname).write_bytes(data)
        ns_c = ns.replace("/", ":") if ns else ""
        lbl = re.sub(r"[|{}\[\]]", "_", Path(f.filename).stem)
        is_img = ext in IMAGE_EXTS
        if ns_c:
            markup_embed = f'{{{{{ns_c}:{uname}|{lbl}}}}}'
            markup_link  = f'[[file:{ns_c}:{uname}|{lbl}]]'
        else:
            markup_embed = f'{{{{{uname}|{lbl}}}}}'
            markup_link  = f'[[file:{uname}|{lbl}]]'
        markup = markup_embed if is_img else markup_link
        results.append({"name": f.filename, "ok": True, "markup": markup,
                        "markup_embed": markup_embed, "markup_link": markup_link, "is_img": is_img})
    return _upload_page(ns, results)


@app.get("/upload", response_class=HTMLResponse)
def upload_get_root(): return _upload_page("", None)

@app.get("/upload/{ns:path}", response_class=HTMLResponse)
def upload_get(ns: str): return _upload_page(ns, None)

@app.post("/upload", response_class=HTMLResponse)
async def upload_post_root(files: list[UploadFile] = File(default=[])):
    return await _do_upload("", files)

@app.post("/upload/{ns:path}", response_class=HTMLResponse)
async def upload_post(ns: str, files: list[UploadFile] = File(default=[])):
    return await _do_upload(ns, files)


@app.get("/files/{filepath:path}")
def serve_file(filepath: str):
    filepath = filepath.strip("/")
    if not filepath:
        return HTMLResponse("Not found", 404)
    if "/" in filepath:
        f_ns, filename = filepath.rsplit("/", 1)
    else:
        f_ns, filename = "", filepath
    try:
        p = file_path(f_ns, filename)
    except ValueError:
        return HTMLResponse("Not found", 404)
    if not p.exists():
        return HTMLResponse("Not found", 404)
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXTS:
        return HTMLResponse("Not found", 404)
    headers = {"X-Content-Type-Options": "nosniff"}
    if ext == "svg":
        headers["Content-Security-Policy"] = "sandbox"
    return FileResponse(str(p), media_type=_FILE_MIME.get(ext, "application/octet-stream"), headers=headers)


@app.post("/file-delete/{filepath:path}", response_class=HTMLResponse)
async def file_delete(request: Request, filepath: str):
    filepath = filepath.strip("/")
    if "/" in filepath:
        f_ns, filename = filepath.rsplit("/", 1)
    else:
        f_ns, filename = "", filepath
    try:
        p = file_path(f_ns, filename)
        if p.exists():
            p.unlink()
    except ValueError:
        return HTMLResponse("Invalid file path", 400)
    # Redirect back to wherever the delete was triggered from
    ref = request.headers.get("referer", "")
    if ref and ref.startswith(("http://", "https://")):
        # Only follow same-host referers to avoid open redirects
        from urllib.parse import urlparse
        if urlparse(ref).netloc == request.headers.get("host", ""):
            return RedirectResponse(ref, status_code=303)
    return RedirectResponse(f"/ns/{f_ns}" if f_ns else "/orphans", status_code=303)


@app.get("/orphans", response_class=HTMLResponse)
def orphans():
    # Collect every file stored under FILES_DIR
    all_files: set[str] = set()
    if FILES_DIR.is_dir():
        for f in FILES_DIR.rglob("*"):
            if f.is_file() and f.suffix.lower().lstrip(".") in ALLOWED_EXTS:
                rel = f.relative_to(FILES_DIR).as_posix()
                all_files.add(rel)

    # Collect every file reference from all .wiki pages
    # Matches both  {{[ns:]filename.ext[|label]}}  and  [[file:[ns:]filename.ext[|label]]]
    REF_RE = re.compile(r"\{\{([^|{}]+)(?:\|[^}]*)?\}\}|\[\[file:([^|\]]+)(?:\|[^\]]*)?\]\]")
    referenced: set[str] = set()
    for wf in PAGES_DIR.rglob("*.wiki"):
        try:
            text = wf.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in REF_RE.finditer(text):
            raw = (m.group(1) or m.group(2)).strip()
            # strip leading :
            if raw.startswith(":"):
                raw = raw[1:]
            # convert colon-style namespace to slash
            referenced.add(raw.replace(":", "/"))

    orphaned = sorted(all_files - referenced)

    if not orphaned:
        body = ('<div class="layout"><div class="content">'
                '<h1>&#128204; Orphaned Files</h1>'
                '<p>No orphaned files — every file has at least one wiki link.</p>'
                '</div></div>')
        return HTMLResponse(shell("Orphaned Files", body))

    rows = ""
    for rel in orphaned:
        f_ns, filename = rel.rsplit("/", 1) if "/" in rel else ("", rel)
        ext = Path(filename).suffix.lower().lstrip(".")
        try:
            st = (FILES_DIR / rel).stat()
            size_str = f"{st.st_size // 1024} KB" if st.st_size >= 1024 else f"{st.st_size} B"
            mtime = time.strftime("%Y-%m-%d", time.localtime(st.st_mtime))
        except OSError:
            size_str, mtime = "?", "unknown"
        preview = ""
        if ext in IMAGE_EXTS and ext != "svg":
            preview = f'<img src="/files/{html.escape(rel)}" style="max-height:3rem;vertical-align:middle;margin-right:.4rem">'
        del_btn = (f'<form method="post" action="/file-delete/{html.escape(rel)}" style="display:inline">'
                   f'<button type="submit" title="Delete" '
                   f'style="background:none;border:none;cursor:pointer;color:#c0392b;font-size:1.1rem">&#128465;</button></form>')
        rows += (f'<tr>'
                 f'<td style="padding:.4rem .6rem">{preview}<a href="/files/{html.escape(rel)}">{html.escape(filename)}</a></td>'
                 f'<td style="padding:.4rem .6rem;color:#888">{html.escape(f_ns) if f_ns else "(root)"}</td>'
                 f'<td style="padding:.4rem .6rem;color:#888">{size_str}</td>'
                 f'<td style="padding:.4rem .6rem;color:#888">{mtime}</td>'
                 f'<td style="padding:.4rem .6rem">{del_btn}</td>'
                 f'</tr>')

    body = (f'<div class="layout"><div class="content">'
            f'<h1>&#128204; Orphaned Files</h1>'
            f'<p>{len(orphaned)} file{"s" if len(orphaned) != 1 else ""} not referenced by any wiki page:</p>'
            f'<table style="width:100%;border-collapse:collapse;border:1px solid #ddd;margin-top:.8rem">'
            f'<tr style="background:#ecf0f1">'
            f'<th style="padding:.4rem .6rem;text-align:left">File</th>'
            f'<th style="padding:.4rem .6rem;text-align:left">Namespace</th>'
            f'<th style="padding:.4rem .6rem;text-align:left">Size</th>'
            f'<th style="padding:.4rem .6rem;text-align:left">Modified</th>'
            f'<th style="padding:.4rem .6rem"></th>'
            f'</tr>{rows}</table>'
            f'</div></div>')
    return HTMLResponse(shell("Orphaned Files", body))


# ── startup ────────────────────────────────────────────────────────────────────

WELCOME = """\
====== Welcome to Wiki ======

===== Getting Started =====

This is your personal wiki. Edit this page to get started.

===== Markup Quick Reference =====

**bold**  //italic//  __underline__  `code`  ~~strikethrough~~

  * Bullet list item
  * Another item
    * Nested item

  - Ordered item
  - Another

[ ] Todo task
[x] Completed task
[~] In progress

[[AnotherPage]]  [[ns:Page|Custom label]]  [[https://example.com|External link]]

----
"""

PAGES_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)
home = PAGES_DIR / "Home.wiki"
if not home.exists():
    home.write_text(WELCOME, encoding="utf-8", newline="\n")

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, reload=False)
