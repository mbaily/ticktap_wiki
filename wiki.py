import os, re, html, time
from pathlib import Path
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn

PAGES_DIR = Path(os.environ.get("WIKI_PAGES_DIR", "pages"))
HOST = os.environ.get("WIKI_HOST", "127.0.0.1")
PORT = int(os.environ.get("WIKI_PORT", "8080"))
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
    tmp = p.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(p)

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
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

# ── markup parser ──────────────────────────────────────────────────────────────

def parse_inline(text: str, cur_ns: str = "") -> str:
    # Stash [[links]] as null-byte placeholders so inline patterns
    # (especially //italic//) cannot match across URL double-slashes.
    stash: list[str] = []
    def stash_link(m):
        stash.append(m.group(0))
        return f"\x00{len(stash)-1}\x00"
    text = re.sub(r"\[\[.+?\]\]", stash_link, text)

    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"//(.+?)//",     r"<em>\1</em>",         text)
    text = re.sub(r"__(.+?)__",     r"<u>\1</u>",           text)
    text = re.sub(r"`(.+?)`",       r"<code>\1</code>",     text)
    text = re.sub(r"~~(.+?)~~",     r"<s>\1</s>",           text)

    def render_link(raw: str) -> str:
        inner = raw[2:-2]  # strip [[ and ]]
        parts = inner.split("|", 1)
        target, label = parts[0].strip(), (html.escape(parts[1].strip()) if len(parts) > 1 else None)
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
        return f'<a href="/wiki/{url}"{cls}>{lbl}</a>'

    def restore(m):
        return render_link(stash[int(m.group(1))])

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

        # lists
        lm = re.match(r"^( *)([*\-]) (.+)", line)
        if lm:
            indent = len(lm.group(1)) // 2
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
    """Split on ===== (h2) headings, keeping the heading with its content."""
    return re.split(r"(?m)(?=^===== )", src)

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
            mtime = time.strftime("%Y-%m-%d", time.localtime(child.stat().st_mtime))
            items += f'<li>&#128196; <a href="/wiki/{pname}">{html.escape(child.stem)}</a> <small style="color:#888">{mtime}</small></li>'
    return items + "</ul>"

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
    mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(page_path(name).stat().st_mtime))
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
    body = (f'<div class="layout"><div class="content">{breadcrumb(name)}'
            f'<div class="edit-toolbar">'
            f'<strong>{html.escape(name.split("/")[-1])}</strong>'
            f'<button form="ef" type="submit">Save</button>'
            f'<a href="/wiki/{name}">Cancel</a>'
            f'<button type="button" onclick="showPreview()">Preview</button>'
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
    body = (f'<div class="layout"><div class="content">'
            f'<h1>Namespace: {html.escape(ns)}</h1>'
            f'{dir_listing(ns_dir, ns.strip("/"))}'
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
                mtime = time.strftime("%Y-%m-%d", time.localtime(child.stat().st_mtime))
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
                results.append(f'<div class="search-result"><a href="/wiki/{pname}">{html.escape(pname)}</a>'
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
    body = (f'<div class="layout"><div class="content">'
            f'<h1>Delete page</h1>'
            f'<div class="notice">Are you sure you want to delete <strong>{html.escape(name)}</strong>?</div>'
            f'<form method="post" style="margin-top:.8rem">'
            f'<input type="hidden" name="confirm" value="yes">'
            f'<button type="submit" style="background:#c0392b;color:#fff;border-color:#a93226">Yes, delete</button>'
            f'&nbsp;<a href="/wiki/{name}">Cancel</a>'
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
home = PAGES_DIR / "Home.wiki"
if not home.exists():
    home.write_text(WELCOME, encoding="utf-8")

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, reload=False)
