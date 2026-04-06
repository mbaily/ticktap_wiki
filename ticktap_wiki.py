import os, re, html, time, secrets, json, math, shutil, hashlib, base64, logging, sqlite3, threading, asyncio
from urllib.parse import quote
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
import uvicorn

PAGES_DIR = Path(os.environ.get("WIKI_PAGES_DIR", "pages"))
HOST = os.environ.get("WIKI_HOST", "0.0.0.0")
PORT = int(os.environ.get("WIKI_PORT", "8080"))
FILES_DIR      = Path(os.environ.get("WIKI_FILES_DIR", "files"))
ALLOWED_EXTS   = {"jpg","jpeg","png","gif","webp","svg","pdf","txt","md","csv","zip"}
IMAGE_EXTS     = {"jpg","jpeg","png","gif","webp","svg"}
MAX_FILE_SIZE  = 20 * 1024 * 1024   # 20 MB per file
MAX_TOTAL_SIZE = 100 * 1024 * 1024  # 100 MB per request

# ── config ──────────────────────────────────────────────────────────────────────
AUTH_ENABLED      = True          # set True to require login
HTPASSWD_FILE     = Path(".htpasswd")
TOKEN_EXPIRY_DAYS = 30             # how long a login token stays valid
TOKEN_FILE        = Path(__file__).parent / ".wiki_tokens"

HTTPS_ENABLED     = True          # set True to enable TLS
TLS_CERT_FILE     = "cert.pem"
TLS_KEY_FILE      = "key.pem"

# Set to the IP(s) of your reverse proxy (nginx, Caddy, etc.) so the rate-limiter
# uses the real client IP from X-Forwarded-For rather than 127.0.0.1.
# Example: TRUSTED_PROXY = {"127.0.0.1", "::1"}
TRUSTED_PROXY: set[str] = set()

DARK_MODE         = True         # set True to use dark colour scheme
SITE_TITLE        = "TickTap Wiki"        # site-wide title shown in nav bar, page titles, and login page

VERSIONING_ENABLED = True          # set False to disable page history
ATTIC_DIR          = Path(os.environ.get("WIKI_ATTIC_DIR", "attic"))
VERSION_BASE_SECS  = 30            # T — base unit for e^i × T retention formula
VERSION_SLOTS      = 10            # K — number of retention bands
DISPLAY_TIMEZONE   = "Australia/Melbourne"         # IANA timezone for history timestamps, e.g. "Europe/London", "America/New_York"

LINEBREAK_ON_NEWLINE = True        # set True to render a single newline as <br> (like GitHub MD); False = DokuWiki default (lines merge into paragraph)

TODO_CYCLE_3STATE = False           # True = cycle [ ]→[x]→[~]→[ ]; False = toggle [ ]↔[x] only (no in-progress state)

ITEM_SPACING      = "0.00rem"        # vertical gap between todo items and list items (CSS length, e.g. "0.1rem", "0.5rem", "4px")

INLINE_DELETE     = False             # show ❌ delete buttons on todo and list items in reader view

TRACE_ENABLED     = True             # show DokuWiki-style recently-visited pages trace bar
TRACE_MAX         = 10               # how many recent pages to remember per user

SECTION_EDIT_MIN  = 1              # minimum heading level to show [edit] section buttons (1 is h1 is ======)
SECTION_EDIT_MAX  = 4              # maximum heading level to show [edit] section buttons (5 is h5 is ==)

TOC_MAX_LEVEL     = 4              # deepest heading level included in the TOC (1=h1 only … 5=h1–h5); typical values: 3 or 4

MARKUP_BAR_DESKTOP = True          # show the editor markup toolbar on desktop
MARKUP_BAR_MOBILE  = True          # show the editor markup toolbar on mobile (≤700 px)

# Nav-bar items that should show only their icon (no label text), saving space.
# Recognised values: "new", "today", "tags", "orphans", "mypage"
# Example: NAV_ICON_ONLY = {"new", "today", "tags", "orphans", "mypage"}
# NAV_ICON_ONLY: set[str] = set()
NAV_ICON_ONLY = {"new", "today", "tags", "orphans", "mypage"}

EDIT_PAGE_PADDING  = "2px"        # left/right padding of the edit page layout (CSS length, e.g. "0rem", "1rem", "16px")
READ_PAGE_PADDING  = "2px"       # left/right padding of the read page layout (CSS length, e.g. "0rem", "1rem", "16px")

# ── colours ──────────────────────────────────────────────────────────────────
# Light-mode palette
LIGHT_NAV_BG       = "#2c3e50"   # navigation bar background; also used for links & toolbar text
LIGHT_TOOLBAR_BG   = "#ecf0f1"   # reader toolbar background & table header fill
# Dark-mode palette  (only used when DARK_MODE = True)
DARK_PAGE_BG       = "#0d0d0d"   # html/body background; also used for input field backgrounds
DARK_PANEL_BG      = "#000000"   # content area, TOC, search cards, login box, preview panel
DARK_PANEL_BORDER  = "#2a2a2a"   # content area and TOC border
DARK_NAV_BG        = "#111111"   # navigation bar background; also used for login button
DARK_TOOLBAR_BG    = "#222222"   # reader toolbar background, code block background, table headers
DARK_BORDER        = "#333333"   # general border and separator colour (used throughout)
DARK_ACCENT        = "#8ab4f8"   # link text, icon-button text, snippet text, tag pill text
DARK_ACCENT_HOVER  = "#aecbfa"   # link hover colour
DARK_PIN_BAR_BG    = "#0a0a0a"   # pinned-pages bar background
DARK_TRACE_BAR_BG  = "#0d1117"   # recently-visited trace bar background (dark mode)
DARK_PRE_BG        = "#141414"   # fenced code block (<pre>) background
DARK_TABLE_ALT     = "#1e1e1e"   # alternating table row background
DARK_TAG_BG        = "#252525"   # tag pill background
DARK_TAG_HOVER     = "#2e2e2e"   # tag pill hover background
# Accent colour used in both modes (hover highlight bar, drag-over indicator, selection outline)
ACCENT_COLOR       = "#3498db"

# Page-name template for the /today redirect.  Uses wiki link notation (colons for namespaces),
# same as [[ns:PageName]] in markup.  Available tokens:
#   {yyyy}=4-digit year  {yy}=2-digit year
#   {mmmm}=full month name (March)   {mmm}=short month name (Mar)
#   {mm}=zero-padded month (01-12)   {m}=month without padding (1-12)
#   {dd}=zero-padded day (01-31)     {d}=day without padding (1-31)
#   {www}=weekday name (Monday…)     {ww}=short weekday (Mon…)
#   {wn}=ISO week number (01-53)     {q}=quarter (1-4)
# Examples:
#   "journal:{yyyy}-{mm}-{dd}"    → [[journal:2026-03-30]]  (default, daily pages)
#   "journal:{yyyy}:W{wn}"        → [[journal:2026:W14]]    (weekly pages)
#   "journal:{yyyy}:{mm}:{dd}"    → [[journal:2026:03:30]]  (daily, nested namespaces)
#   "{yyyy}-{mm}"                 → [[2026-03]]              (monthly pages, root namespace)
JOURNAL_PAGE_FORMAT = "Todo {yyyy} {mmmm}"

USER_PAGE_NS         = "user"  # namespace for per-user homepages; set "" to disable
USER_PAGE_AUTOCREATE = True    # write a stub on first login if the page doesn't exist
USER_PAGE_PRIVATE    = True   # True → only the owner may edit their own user page
USER_PAGE_HIDDEN     = True   # True → only the owner may read/view their own user pages and files
USER_HOME_PAGE       = "Home"  # page name for the user's landing page within their sub-namespace
USER_SETTINGS_FILE   = Path(__file__).parent / "wiki_user_settings.sqlite3"  # SQLite file for per-user preferences

app = FastAPI()

# ── user settings helpers ─────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    """Open (and initialise if needed) the user-settings SQLite database."""
    con = sqlite3.connect(str(USER_SETTINGS_FILE), check_same_thread=False)
    con.execute(
        "CREATE TABLE IF NOT EXISTS user_settings "
        "(username TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
        "PRIMARY KEY (username, key))"
    )
    con.commit()
    return con


def _get_user_setting(username: str, key: str, default: str = "") -> str:
    """Return a per-user setting value from the SQLite store."""
    if not username:
        return default
    try:
        con = _get_db()
        try:
            row = con.execute(
                "SELECT value FROM user_settings WHERE username=? AND key=?",
                (username, key),
            ).fetchone()
        finally:
            con.close()
        return row[0] if row else default
    except Exception:
        return default


def _set_user_settings(username: str, pairs: dict[str, str]) -> None:
    """Persist multiple per-user settings atomically in the SQLite store."""
    if not username or not pairs:
        return
    try:
        con = _get_db()
        try:
            con.executemany(
                "INSERT INTO user_settings (username, key, value) VALUES (?,?,?) "
                "ON CONFLICT(username, key) DO UPDATE SET value=excluded.value",
                [(username, k, v) for k, v in pairs.items()],
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        pass


def _set_user_setting(username: str, key: str, value: str) -> None:
    """Persist a single per-user setting value in the SQLite store."""
    _set_user_settings(username, {key: value})


def _apply_journal_format(fmt: str, now: datetime) -> str:
    """Substitute date tokens in a journal page format string and return the page name."""
    return (
        fmt
        .replace("{yyyy}", now.strftime("%Y"))
        .replace("{yy}",   now.strftime("%y"))
        .replace("{mmmm}", now.strftime("%B"))
        .replace("{mmm}",  now.strftime("%b"))
        .replace("{mm}",   now.strftime("%m"))
        .replace("{m}",    str(now.month))
        .replace("{dd}",   now.strftime("%d"))
        .replace("{d}",    str(now.day))
        .replace("{www}",  now.strftime("%A"))
        .replace("{ww}",   now.strftime("%a"))
        .replace("{wn}",   now.strftime("%V"))
        .replace("{q}",    str((now.month - 1) // 3 + 1))
        .replace("{hh}",   now.strftime("%H"))
        .replace("{HH}",   now.strftime("%I"))
        .replace("{p}",    now.strftime("%p").lower())
    )



def normalize_name(name: str) -> str:
    """Replace spaces with underscores in each path segment (DokuWiki-style encoding)."""
    return "/".join(seg.replace(" ", "_") for seg in name.strip("/").split("/"))

def page_path(name: str) -> Path:
    """Resolve a wiki page name to its filesystem Path inside PAGES_DIR.

    Normalises the name with ``normalize_name``, then validates every
    path segment against the pattern ``[A-Za-z0-9_-]+``.  Raises
    ``ValueError`` on an invalid segment or a path-traversal attempt.
    The returned path is *not* guaranteed to exist — callers should
    check ``Path.exists()`` themselves.

    Args:
        name: Wiki page name, optionally containing ``/`` namespace
              separators (e.g. ``"projects/MyPage"``).

    Returns:
        Absolute ``Path`` object pointing to ``<PAGES_DIR>/<…>.wiki``.

    Raises:
        ValueError: If any segment is invalid or the resolved path
                    would fall outside PAGES_DIR (path-traversal).
    """
    name = normalize_name(name)
    parts = name.split("/")
    for p in parts:
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", p):
            raise ValueError(f"Invalid segment: {p!r}")
    resolved = PAGES_DIR.joinpath(*parts).with_suffix(".wiki").resolve()
    if not resolved.is_relative_to(PAGES_DIR.resolve()):
        raise ValueError("Path traversal attempt")
    return PAGES_DIR.joinpath(*parts).with_suffix(".wiki")

def read_page(name: str) -> str | None:
    """Read the raw wiki markup of a page from disk.

    Args:
        name: Wiki page name (e.g. ``"Home"`` or ``"projects/MyPage"``).

    Returns:
        Full file contents as a UTF-8 string, or ``None`` if the page
        does not exist yet.
    """
    p = page_path(name)
    return p.read_text(encoding="utf-8") if p.exists() else None

def write_page(name: str, content: str, snapshot: bool = True):
    """Write wiki markup to disk atomically, optionally snapshotting the previous version.

    Steps performed:

    1. Resolve and validate the page path (raises ``ValueError`` on bad name).
    2. Normalise line endings to ``\\n`` and strip NUL bytes.
    3. If ``snapshot=True`` and the page already exists, call
       ``_save_snapshot`` followed by ``_prune_attic``; versioning
       failures are silently suppressed so they never block a save.
    4. Write to a temp file in the same directory, then atomically
       rename it over the target — preventing torn writes.

    Args:
        name:     Wiki page name.
        content:  New page markup (``\\r\\n`` is accepted and normalised).
        snapshot: When ``True`` (default), save the previous version to
                  the attic before overwriting.  Pass ``False`` for
                  in-place mutations (toggle, add-todo, reorder) that
                  should not generate history entries.

    Raises:
        ValueError: If the page name is invalid.
        OSError:    If the underlying file-system write fails.
    """
    p = page_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Normalise line endings: browsers send \r\n; Python text-mode write on
    # Windows would then double-expand \r\n → \r\r\n, blowing up blank lines.
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    # Strip null bytes — they break the stash/restore mechanism in parse_inline.
    content = content.replace("\x00", "")
    if VERSIONING_ENABLED and snapshot and p.exists():
        try:
            _save_snapshot(name, p.read_text(encoding="utf-8"))
            _prune_attic(name)
        except Exception:
            pass  # versioning failure never blocks a save
    tmp = p.with_suffix(f".{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8", newline="\n")
        tmp.replace(p)
    finally:
        tmp.unlink(missing_ok=True)

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

# ── attic / versioning helpers ────────────────────────────────────────────────

def _attic_page_dir(name: str) -> Path:
    name = normalize_name(name)
    parts = name.split("/")
    for p in parts:
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", p):
            raise ValueError(f"Invalid segment: {p!r}")
    target = ATTIC_DIR.joinpath(*parts)
    if not target.resolve().is_relative_to(ATTIC_DIR.resolve()):
        raise ValueError("Path traversal attempt")
    return target

def _save_snapshot(name: str, content: str):
    """Write a timestamped snapshot of *content* to the attic directory.

    The snapshot filename is ``YYYYmmdd_HHMMSS_microseconds.wiki``,
    derived from the current UTC time.  If a file with the same stem
    already exists (same-second save race), the existing snapshot is
    kept and the new one is silently discarded.

    The write is atomic: the content is written to a ``.tmp`` file
    that is then renamed over the final path.

    Args:
        name:    Wiki page name used to determine the attic sub-directory.
        content: Page markup to store verbatim.
    """
    d = _attic_page_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    _now = datetime.now(timezone.utc)
    ts = _now.strftime("%Y%m%d_%H%M%S") + f"_{_now.microsecond:06d}"
    snap = d / f"{ts}.wiki"
    if snap.exists():
        return  # same-second save: keep the first snapshot of this second
    tmp = snap.with_suffix(".tmp")
    try:
        tmp.write_text(content, encoding="utf-8", newline="\n")
        tmp.replace(snap)
    finally:
        tmp.unlink(missing_ok=True)

def _prune_attic(name: str):
    """Thin the version history for a page using an exponential retention formula.

    Retention strategy (mirrors a logarithmic time-decay approach):

    * Any snapshot older than ``exp(K) * T`` seconds is deleted.
    * Remaining snapshots are assigned to a band
      ``i = floor(log(age / T))`` capped at ``K-1``.
    * Within each band only the **newest** snapshot is kept (it records
      the state at the *end* of that time interval).
    * Snapshots younger than ``T`` seconds keep only the **oldest** one
      (it records the pre-edit state at the start of a rapid-edit session).

    Configuration constants: ``VERSION_BASE_SECS`` (T) and
    ``VERSION_SLOTS`` (K).

    Orphaned ``.tmp`` files left by a previous crashed save are also
    removed as part of cleanup.

    Args:
        name: Wiki page name whose attic directory should be pruned.
    """
    d = _attic_page_dir(name)
    if not d.is_dir():
        return
    # Clean up any .tmp files left by a crashed previous save
    for tmp_f in d.glob("*.tmp"):
        tmp_f.unlink(missing_ok=True)
    now = datetime.now(timezone.utc)
    T, K = VERSION_BASE_SECS, VERSION_SLOTS
    max_age = math.exp(K) * T
    entries = []
    for f in sorted(d.glob("*.wiki")):
        try:
            dt = datetime.strptime(f.stem[:15], "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        age = (now - dt).total_seconds()
        if age >= max_age:
            f.unlink(missing_ok=True)
            continue
        entries.append((dt, age, f))
    # Keep only the oldest snapshot younger than T (it records the pre-edit state at the
    # start of a rapid-edit session and ages into band 0 after T seconds).
    # For snapshots >= T, keep only the newest in each band [e^i*T, e^(i+1)*T).
    # Band i: floor(log(age / T)), capped at K-1.
    band_newest: dict[int, tuple] = {}
    for dt, age, f in entries:
        if age < T:
            continue
        band = min(int(math.log(age / T)), K - 1)
        if band not in band_newest or dt > band_newest[band][0]:
            band_newest[band] = (dt, age, f)
    sub_t = [(dt, age, f) for dt, age, f in entries if age < T]
    sub_t_keep = {min(sub_t, key=lambda x: x[0])[2]} if sub_t else set()
    keep = {v[2] for v in band_newest.values()} | sub_t_keep
    for dt, age, f in entries:
        if f not in keep:
            f.unlink(missing_ok=True)

def _snap_ts_to_display(ts: str) -> str:
    """Convert a snapshot filename stem (YYYYmmdd_HHMMSS) to a display string in DISPLAY_TIMEZONE."""
    try:
        dt = datetime.strptime(ts[:15], "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        tz = ZoneInfo(DISPLAY_TIMEZONE)
        dt_local = dt.astimezone(tz)
        tz_label = DISPLAY_TIMEZONE if DISPLAY_TIMEZONE != "UTC" else "UTC"
        return dt_local.strftime(f"%Y-%m-%d %H:%M:%S {tz_label}")
    except Exception:
        return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]} UTC"

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


def parse_meta(src: str) -> dict[str, str]:
    """Extract key:value pairs from the ~~META: block at the top of a page."""
    if not src.startswith("~~META:"):
        return {}
    m = re.search(r"(?m)^~~$", src[7:])
    if not m:
        return {}
    block = src[7:7 + m.start()]
    result: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            result[k.strip().lower()] = v.strip()
    return result


def slug(text: str) -> str:
    """Convert a heading text string into a URL-safe anchor slug.

    Lowercases the text, replaces runs of non-alphanumeric characters
    with hyphens, and strips leading/trailing hyphens.  Returns
    ``"heading"`` if the result would otherwise be empty.

    Args:
        text: Raw heading text (not HTML-escaped).

    Returns:
        Slug string suitable for use as an HTML ``id`` attribute.
    """
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "heading"

# ── markup macros ─────────────────────────────────────────────────────────────

def _expand_date_macros(text: str) -> str:
    """Expand {{date}}, {{datetime}}, and {{date:fmt}} macros to plain text.

    Called after inline-code spans have already been stashed in parse_inline,
    so macros inside backtick code are never expanded.
    """
    tz = ZoneInfo(DISPLAY_TIMEZONE)
    now = datetime.now(tz)

    def _replace(m: re.Match) -> str:
        token = m.group(1)
        if token == "datetime":
            return now.strftime("%Y-%m-%d %H:%M")
        elif token.startswith("date:"):
            fmt = token[5:].strip() or "%Y-%m-%d"
            return now.strftime(fmt)
        else:  # bare "date"
            return now.strftime("%Y-%m-%d")

    return re.sub(r"\{\{(date(?::[^}]*)?|datetime)\}\}", _replace, text)


def _pageindex_collect(d: Path, prefix: str) -> list[tuple[str, str]]:
    """Recursively collect all wiki pages under *d* as ``(pname, mtime)`` tuples.

    Only descends into directories whose names match ``[A-Za-z0-9_-]+``.
    Pages whose filename starts with ``_`` are excluded.
    Results are returned in filesystem order (sorted by name at each level);
    callers may re-sort as needed.
    """
    results: list[tuple[str, str]] = []
    for child in sorted(d.iterdir()):
        if child.is_dir() and not child.is_symlink() and re.fullmatch(r"[A-Za-z0-9_\-]+", child.name):
            rel = f"{prefix}/{child.name}" if prefix else child.name
            results.extend(_pageindex_collect(child, rel))
        elif child.suffix == ".wiki" and not child.name.startswith("_"):
            pname = f"{prefix}/{child.stem}" if prefix else child.stem
            try:
                mtime = time.strftime("%Y-%m-%d", time.localtime(child.stat().st_mtime))
            except OSError:
                mtime = ""
            results.append((pname, mtime))
    return results


def _pageindex_ul(d: Path, prefix: str, desc: bool) -> str:
    """Build a shallow ``<ul>`` for ``_render_pageindex`` (flat/non-deep mode).

    Lists immediate children of *d*: sub-namespaces as folder links followed
    by wiki pages.  Pass ``desc=True`` to reverse the sort order.

    Returns an empty string when there are no eligible items.
    """
    items = []
    children = sorted(d.iterdir(), reverse=desc)
    for child in children:
        if child.is_dir() and re.fullmatch(r"[A-Za-z0-9_\-]+", child.name):
            rel = f"{prefix}/{child.name}" if prefix else child.name
            items.append(f'<li>&#128193; <a href="/ns/{html.escape(rel)}">{html.escape(child.name)}/</a></li>')
        elif child.suffix == ".wiki" and not child.name.startswith("_"):
            pname = f"{prefix}/{child.stem}" if prefix else child.stem
            try:
                mtime = time.strftime("%Y-%m-%d", time.localtime(child.stat().st_mtime))
            except OSError:
                mtime = ""
            items.append(
                f'<li>&#128196; <a href="/wiki/{html.escape(pname)}">{html.escape(child.stem)}</a>'
                + (f' <small style="color:#888">{mtime}</small>' if mtime else "")
                + "</li>"
            )
    if not items:
        return ""
    return '<ul style="list-style:none;padding-left:0">' + "".join(items) + "</ul>"


def _render_pageindex(ns_key: str, deep: bool = False, desc: bool = False) -> str:
    """Return an HTML ``<ul>`` listing pages (and sub-namespaces) for *ns_key*.

    Args:
        ns_key: Namespace path using ``/`` separators (e.g. ``"projects/sub"``).
                Pass ``""`` for the wiki root.
        deep:   When ``True``, recurse into all sub-namespaces and produce a
                single flat list.  Each page label shows its full path relative
                to *ns_key* (e.g. ``journal/2026-04-04``) so the namespace
                hierarchy is visible in the labels.  No folder icons are shown.
                When ``False`` (default), only immediate children are listed and
                sub-namespaces appear as folder links.
        desc:   When ``True``, reverse the sort order (Z→A / newest first).
                Default is ascending (A→Z).

    Returns:
        HTML ``<ul>…</ul>`` string, or a short error paragraph if the namespace
        directory is invalid or does not exist.
    """
    parts = [p for p in ns_key.split("/") if p]
    for p in parts:
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", p):
            return f'<p><em>Invalid namespace: <code>{html.escape(ns_key)}</code></em></p>'
    target_dir = PAGES_DIR.joinpath(*parts) if parts else PAGES_DIR
    try:
        if not target_dir.resolve().is_relative_to(PAGES_DIR.resolve()):
            return f'<p><em>Invalid namespace: <code>{html.escape(ns_key)}</code></em></p>'
    except OSError:
        return f'<p><em>Invalid namespace: <code>{html.escape(ns_key)}</code></em></p>'
    if not target_dir.is_dir():
        return f'<p><em>No pages found in namespace <code>{html.escape(ns_key or "root")}</code>.</em></p>'
    prefix = "/".join(parts)

    if deep:
        pages = _pageindex_collect(target_dir, prefix)
        pages.sort(key=lambda t: t[0], reverse=desc)
        if not pages:
            return f'<p><em>No pages in namespace <code>{html.escape(ns_key or "root")}</code>.</em></p>'
        items = []
        for pname, mtime in pages:
            # Label: path relative to the index root (strip the ns_key prefix)
            rel_label = pname[len(prefix) + 1:] if prefix and pname.startswith(prefix + "/") else pname
            rel_label = rel_label.replace("/", ":")
            items.append(
                f'<li>&#128196; <a href="/wiki/{html.escape(pname)}">{html.escape(rel_label)}</a>'
                + (f' <small style="color:#888">{mtime}</small>' if mtime else "")
                + "</li>"
            )
        return '<ul style="list-style:none;padding-left:0">' + "".join(items) + "</ul>"

    result = _pageindex_ul(target_dir, prefix, desc)
    if not result:
        return f'<p><em>No pages in namespace <code>{html.escape(ns_key or "root")}</code>.</em></p>'
    return result


def _resolve_relative_ns(target: str, cur_ns: str) -> str:
    """Resolve a DokuWiki relative link target against the current namespace.

    DokuWiki relative syntax uses colon-separated leading dot/double-dot
    segments to navigate the namespace hierarchy:

    * ``.:sub:Page``   — current namespace + sub-namespace + Page
    * ``..:Page``      — parent namespace + Page  (one level up)
    * ``..:..:Page``   — grandparent namespace + Page (two levels up)
    * ``.Page``        — same as a bare relative link (current ns + Page)

    Returns the resolved path using ``/`` separators, suitable for use as
    a URL path segment.
    """
    segs = target.split(":")
    ns_parts = [p for p in cur_ns.split("/") if p]
    i = 0
    while i < len(segs):
        if segs[i] == ".":
            i += 1  # stay at current namespace level
        elif segs[i] == "..":
            if ns_parts:
                ns_parts.pop()  # go up one namespace level
            i += 1
        else:
            break
    remaining = "/".join(segs[i:])
    base = "/".join(ns_parts)
    return (base + "/" + remaining).strip("/") if base else remaining


# ── markup parser ──────────────────────────────────────────────────────────────

def parse_inline(text: str, cur_ns: str = "") -> str:
    """Render inline DokuWiki markup in *text* to an HTML fragment.

    Handles the following inline constructs (in order of processing):

    * ``[[WikiLinks]]`` and ``{{media}}`` tokens are *stashed* first
      (replaced with NUL-byte placeholders) so that their contents
      cannot accidentally match later patterns such as ``//italic//``
      over a URL's double-slash.  They are restored after all other
      substitutions are applied.
    * HTML-escaping of the remaining text.
    * Bold (``**...**``), italic (``//...//``), underline (``__...__``),
      inline code (\u0060...\u0060), strikethrough (``~~...~~``).
    * ``{{ns:file.ext|alt}}`` — embedded media.  Resolves the namespace
      relative to *cur_ns* when no explicit namespace qualifier is given.
      Renders as ``<img>`` for image extensions; shows a
      ``broken-file`` span if the file is not found on disk.
    * ``[[target|label]]`` — wiki links.  Supports:

      - Absolute links prefixed with ``:`` (root namespace).
      - Cross-namespace links with ``:``-separated components.
      - Relative links resolved against *cur_ns*.
      - External ``http://`` / ``https://`` links (open in new tab).
      - ``[[file:...]]`` links to attached files.
      - Adds ``class="new-page"`` when the target page does not exist.

    Args:
        text:    Raw wiki markup string (a single paragraph/line).
        cur_ns:  Namespace of the page being rendered, used to resolve
                 relative links and media paths (e.g. ``"projects/sub"``).

    Returns:
        HTML string ready for insertion into the page body.
    """
    # Step 1: Stash `inline code` spans first so their contents are never
    # processed by date expansion, HTML escaping, or formatting patterns.
    # Inner text (without backticks) is captured; restored as <code>...</code>
    # at the very end after html-escaping.  Uses \x01 as placeholder, which is
    # distinct from the \x00 placeholder used by the link/media stash below.
    code_stash: list[str] = []
    def stash_code(m: re.Match) -> str:
        code_stash.append(m.group(1))
        return f"\x01{len(code_stash)-1}\x01"
    text = re.sub(r"`([^`\n]+)`", stash_code, text)

    # Step 1b: Stash %%nowiki%% spans — rendered as plain escaped text, no
    # macro expansion or markup processing.  Uses \x02 as placeholder.
    nowiki_stash: list[str] = []
    def stash_nowiki(m: re.Match) -> str:
        nowiki_stash.append(m.group(1))
        return f"\x02{len(nowiki_stash)-1}\x02"
    text = re.sub(r"%%(.+?)%%", stash_nowiki, text, flags=re.DOTALL)

    # Step 2: Expand date macros so they work inside [[link targets]] and labels.
    # Inline code spans are already stashed so their contents survive unexpanded.
    text = _expand_date_macros(text)

    # Step 3: Stash [[links]] and {{media}} as null-byte placeholders so inline
    # patterns (especially //italic//) cannot match across URL double-slashes.
    # Non-greedy is correct: wiki syntax forbids nesting, so the first closing
    # delimiter always ends the token.
    stash: list[str] = []
    def stash_link(m):
        stash.append(m.group(0))
        return f"\x00{len(stash)-1}\x00"
    text = re.sub(r"\{\{.+?\}\}|\[\[.+?\]\]", stash_link, text)

    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"//(.+?)//",     r"<em>\1</em>",         text)
    text = re.sub(r"__(.+?)__",     r"<u>\1</u>",           text)
    text = re.sub(r"~~(.+?)~~",     r"<s>\1</s>",           text)

    def render_media(raw: str) -> str:
        inner = raw[2:-2]
        pm = inner.split("|", 1)
        target = pm[0].strip()
        alt_text = html.escape(pm[1].strip()) if len(pm) > 1 else None
        if not target:
            return html.escape(raw)
        if target.startswith((".:" , "..:" )):
            full = _resolve_relative_ns(target, cur_ns)
        elif target.startswith(":"):
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
        if target.startswith((".:" , "..:" )):
            url = _resolve_relative_ns(target, cur_ns)
        elif target.startswith(":"):
            url = target[1:].replace(":", "/")
        elif ":" in target:
            url = target.replace(":", "/")
        else:
            url = (cur_ns + "/" + target).lstrip("/") if cur_ns else target
        url = normalize_name(url)
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

    text = re.sub(r"\x00(\d+)\x00", restore, text)

    # Step 6: Restore inline code spans. The inner content is html-escaped here
    # (the surrounding text was already escaped in the html.escape() call above).
    def restore_code(m: re.Match) -> str:
        return f"<code>{html.escape(code_stash[int(m.group(1))])}</code>"
    text = re.sub(r"\x01(\d+)\x01", restore_code, text)

    # Step 7: Restore %%nowiki%% spans as plain escaped text.
    def restore_nowiki(m: re.Match) -> str:
        return html.escape(nowiki_stash[int(m.group(1))])
    return re.sub(r"\x02(\d+)\x02", restore_nowiki, text)


def _parse_table_row(line: str) -> list | None:
    """Parse a DokuWiki table row into [[cell_type, content, colspan], ...] or None."""
    stripped = line.strip()
    if not stripped or stripped[0] not in '|^':
        return None
    # Stash [[links|with labels]] and {{media|with alt}} so that | or ^ inside
    # them is not mistaken for a cell delimiter.
    stash: list[str] = []
    def _stash(m: re.Match) -> str:
        stash.append(m.group(0))
        return f"\x00{len(stash)-1}\x00"
    safe = re.sub(r"\{\{.+?\}\}|\[\[.+?\]\]", _stash, stripped)
    cells: list = []
    i, current_delim = 1, safe[0]
    while i <= len(safe):
        j = i
        while j < len(safe) and safe[j] not in '|^':
            j += 1
        if j >= len(safe):
            break
        raw = safe[i:j]
        # Restore stashed tokens inside the cell content
        content = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], raw)
        cells.append(['th' if current_delim == '^' else 'td', content.strip(), 1])
        current_delim, i = safe[j], j + 1
    merged: list = []
    for cell in cells:
        if cell[1] == '' and merged:
            merged[-1][2] += 1
        else:
            merged.append(cell)
    return merged or None


def parse(src: str, name: str = "", section_edit: bool = True) -> tuple[str, list]:
    """Convert a full block of DokuWiki-style wiki markup to HTML.

    Processes the source line-by-line, maintaining state machines for
    fenced code blocks, ordered/unordered lists, tables, and paragraph
    accumulation.  Calls ``parse_inline`` for all inline content.

    Supported block-level constructs:

    * **Fenced code blocks** — triple-backtick delimiters with optional
      language hint (e.g. ````` ````python`````).  Rendered as
      ``<pre><code class="language-...">``.
    * **Headings** — DokuWiki style (``====== h1 ======`` down to
      ``== h5 ==``); the number of ``=`` signs determines the level.
      Duplicate heading texts receive disambiguating suffixes
      (``-2``, ``-3``, …).  Optional ``[edit]`` / block-editor links
      are injected when ``section_edit=True`` and *name* is set.
    * **Horizontal rules** — four or more dashes on a line.
    * **Todo checkboxes** — lines beginning with ``[ ]``, ``[x]``, or
      ``[~]`` (with optional leading spaces for nesting).
    * **Tables** — DokuWiki pipe/caret syntax; header cells (``^``) and
      data cells (``|``) with colspan support.
    * **Ordered and unordered lists** — lines indented with two-or-more
      spaces + ``*`` (bullet) or ``-`` (numbered); nesting is handled
      by changing indent depth.
    * **Paragraphs** — non-blank lines not matching any other pattern
      are accumulated and wrapped in ``<p>``; within a paragraph,
      consecutive lines are joined with ``<br>`` (when
      ``LINEBREAK_ON_NEWLINE=True``) or a space.
    * **``~~META:`` blocks** — stripped before parsing via ``strip_meta``;
      the removed line count is tracked so that ``data-line`` attributes
      reference the original source line numbers (used by the quick-todo
      and section-edit features).

    Args:
        src:          Raw wiki markup (as stored in ``.wiki`` files).
        name:         Wiki page name; used to build ``[edit]`` links and
                      resolve relative links.  Pass ``""`` to disable.
        section_edit: When ``True`` (default), inject section-edit
                      buttons next to qualifying headings.

    Returns:
        A ``(html_body, headings)`` tuple where:

        * ``html_body`` is the full HTML string for the page body.
        * ``headings`` is a list of ``(level, text, anchor)`` tuples in
          document order; used to build the table-of-contents.
    """
    src, meta_offset = strip_meta(src)
    lines = src.split("\n")
    out, headings, list_stack = [], [], []
    cur_ns = "/".join(name.split("/")[:-1])
    in_code, code_lang, code_lines = False, "", []
    sect_count = 0
    seen_anchors: dict[str, int] = {}
    table_rows: list = []
    para_lines: list = []  # (source_line_idx, rendered_html) — current paragraph accumulator

    def close_lists():
        while list_stack:
            entry = list_stack.pop()
            if entry[1]:   # parent <li> was left open for this sub-list
                out.append("</li>")
            out.append(f"</{entry[0]}>")

    def flush_para():
        """Emit accumulated paragraph lines as a single <p> and clear the buffer."""
        if not para_lines:
            return
        last_idx = para_lines[-1][0]
        sep = "<br>" if LINEBREAK_ON_NEWLINE else " "
        content = sep.join(h for _, h in para_lines)
        out.append(f'<p data-line="{last_idx}">{content}</p>')
        para_lines.clear()

    def close_table():
        if not table_rows:
            return
        out.append('<table class="wiki-table">')
        for row in table_rows:
            out.append('<tr>')
            for cell_type, content, colspan in row:
                cs = f' colspan="{colspan}"' if colspan > 1 else ''
                out.append(f'<{cell_type}{cs}>{parse_inline(content, cur_ns)}</{cell_type}>')
            out.append('</tr>')
        out.append('</table>')
        table_rows.clear()

    for i, line in enumerate(lines):
        # fenced code blocks
        if line.startswith("```"):
            if not in_code:
                flush_para()
                close_table()
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
            flush_para(); close_table(); close_lists(); out.append("<hr>"); continue

        # headings — DokuWiki style: more = means bigger (6= → h1, 2= → h5)
        hm = re.fullmatch(r"(={2,6}) (.+?) \1", line.rstrip())
        if hm:
            flush_para()
            close_table()
            close_lists()
            level, text = 7 - len(hm.group(1)), hm.group(2)
            base_anchor = slug(text)
            if base_anchor in seen_anchors:
                # Find a suffix that doesn't collide with any other heading slug
                while True:
                    seen_anchors[base_anchor] += 1
                    candidate = f"{base_anchor}-{seen_anchors[base_anchor]}"
                    if candidate not in seen_anchors:
                        break
                anchor = candidate
                seen_anchors[anchor] = 1
            else:
                seen_anchors[base_anchor] = 1
                anchor = base_anchor
            headings.append((level, text, anchor))
            edit_btn = ""
            if SECTION_EDIT_MIN <= level <= SECTION_EDIT_MAX and section_edit and name:
                edit_btn = (f' <span class="sect-edit-btns">'
                            f'<a class="sect-edit" title="Block editor" href="/block-sect/{name}/{sect_count}">&#9783;</a>'
                            f' <a class="sect-edit" href="/sect/{name}/{sect_count}">[edit]</a>'
                            f'</span>')
                sect_count += 1
            out.append(f'<h{level} id="{anchor}" data-line="{i + meta_offset}">{html.escape(text)}{edit_btn}</h{level}>')
            continue

        # todo checkboxes
        cbm = re.match(r"^(\s*)\[([ x~])\] (.*)", line)
        if cbm:
            flush_para()
            close_table()
            close_lists()
            todo_indent = len(cbm.group(1))
            todo_level = todo_indent // 2
            state, text = cbm.group(2), parse_inline(cbm.group(3), cur_ns)
            checked = " checked" if state == "x" else ""
            state_cls = " todo-done" if state == "x" else (" todo-inprogress" if state == "~" else "")
            indent_style = f' style="padding-left:{todo_level * 1.5}em"' if todo_level else ''
            del_btn = f' <a class="line-del" href="#" data-line="{i + meta_offset}" data-name="{html.escape(name)}">\u274c</a>' if INLINE_DELETE and section_edit and name else ''
            out.append(f'<p class="todo{state_cls}" data-line="{i + meta_offset}" data-state="{state}" data-indent="{todo_indent}" data-prefix="[ ] "{indent_style}><input type="checkbox"{checked} data-line="{i + meta_offset}" data-name="{html.escape(name)}"> {text}{del_btn}</p>')
            continue

        # table rows — DokuWiki syntax: lines starting with | or ^
        trow = _parse_table_row(line)
        if trow is not None:
            flush_para()
            close_lists()
            table_rows.append(trow)
            continue

        # lists — DokuWiki requires minimum 2-space indent; 2 spaces = top-level
        lm = re.match(r"^( {2,})([*\-]) (.+)", line)
        if lm:
            flush_para()
            close_table()
            indent = max(0, len(lm.group(1)) // 2 - 1)
            tag = "ul" if lm.group(2) == "*" else "ol"
            text = parse_inline(lm.group(3), cur_ns)
            # Pop stacks that are too deep
            while len(list_stack) > indent + 1:
                entry = list_stack.pop()
                if entry[1]:
                    out.append("</li>")
                out.append(f"</{entry[0]}>")
            # Switch list type at same level
            if list_stack and list_stack[-1][0] != tag and len(list_stack) == indent + 1:
                entry = list_stack.pop()
                if entry[1]:
                    out.append("</li>")
                out.append(f"</{entry[0]}>")
            # If returning to a level where a <li> was left open for nesting, close it
            if list_stack and list_stack[-1][1]:
                out.append("</li>")
                list_stack[-1][1] = False
            # Push new depth levels — nest <ul>/<ol> inside the last <li> when going deeper
            while len(list_stack) <= indent:
                if list_stack and out and out[-1].endswith("</li>"):
                    # Strip the closing </li> so the sub-list lives inside it
                    list_stack[-1][1] = True
                    out[-1] = out[-1][:-5]
                list_stack.append([tag, False])
                out.append(f"<{tag}>")
            li_indent = len(lm.group(1))
            li_prefix = lm.group(2) + " "
            del_btn = f' <a class="line-del" href="#" data-line="{i + meta_offset}" data-name="{html.escape(name)}">\u274c</a>' if INLINE_DELETE and section_edit and name else ''
            out.append(f'<li data-line="{i + meta_offset}" data-indent="{li_indent}" data-prefix="{li_prefix}">{text}{del_btn}</li>')
            continue

        # block macros — whole-line {{pageindex}}, {{pageindex:ns}}, with optional |deep and/or |desc flags
        bm = re.fullmatch(r"\{\{pageindex(?::([A-Za-z0-9/_:\-]*))?(?:\|([a-zA-Z|]*))?\}\}", line.strip())
        if bm:
            flush_para(); close_table(); close_lists()
            raw_ns = (bm.group(1) or "").replace(":", "/").strip("/")
            flags = set((bm.group(2) or "").lower().split("|"))
            deep = "deep" in flags
            desc = "desc" in flags
            out.append(_render_pageindex(raw_ns or cur_ns, deep=deep, desc=desc))
            continue

        close_table()
        close_lists()
        if line.strip() == "":
            flush_para()
        else:
            para_lines.append((i + meta_offset, parse_inline(line, cur_ns)))

    flush_para()
    close_table()
    close_lists()
    # emit any unclosed fenced code block at EOF
    if in_code:
        lc = f' class="language-{html.escape(code_lang)}"' if code_lang else ""
        out.append(f'<pre><code{lc}>{html.escape(chr(10).join(code_lines))}</code></pre>')
    return "\n".join(out), headings


def find_editable_sections(src: str, min_level: int = 1, max_level: int = 3) -> list[tuple[int, int, int]]:
    """Find hierarchical editable sections in wiki source.

    Returns a list of (level, start_line, end_line) for each editable heading.
    lines[start_line:end_line] gives the heading and all content underneath it
    until the next heading of equal or higher importance (lower or equal level
    number), considering ALL headings — not just editable ones — as potential
    boundaries.  Headings inside fenced code blocks are ignored.
    """
    lines = src.split("\n")
    all_headings: list[tuple[int, int]] = []   # (level, line_index)
    editable_indices: list[int] = []           # indices into all_headings
    in_code = False

    for i, line in enumerate(lines):
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        hm = re.fullmatch(r"(={2,6}) (.+?) \1", line.rstrip())
        if hm:
            level = 7 - len(hm.group(1))
            all_headings.append((level, i))
            if min_level <= level <= max_level:
                editable_indices.append(len(all_headings) - 1)

    sections: list[tuple[int, int, int]] = []
    for ei in editable_indices:
        level, start = all_headings[ei]
        end = len(lines)
        # End at the next heading of equal or higher importance (any heading, not just editable)
        for j in range(ei + 1, len(all_headings)):
            if all_headings[j][0] <= level:
                end = all_headings[j][1]
                break
        sections.append((level, start, end))
    return sections

def _compute_anchor_for_line(src: str, target_line: int) -> str:
    """Compute the deduplicated anchor that parse() would assign to the heading at target_line.

    Replicates the same seen_anchors logic used in parse() so that duplicate
    heading names get the correct -2, -3, … suffix.
    """
    lines = src.split("\n")
    seen_anchors: dict[str, int] = {}
    in_code = False
    for i, line in enumerate(lines):
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        hm = re.fullmatch(r"(={2,6}) (.+?) \1", line.rstrip())
        if hm:
            base_anchor = slug(hm.group(2))
            if base_anchor in seen_anchors:
                while True:
                    seen_anchors[base_anchor] += 1
                    candidate = f"{base_anchor}-{seen_anchors[base_anchor]}"
                    if candidate not in seen_anchors:
                        break
                anchor = candidate
                seen_anchors[anchor] = 1
            else:
                seen_anchors[base_anchor] = 1
                anchor = base_anchor
            if i == target_line:
                return anchor
    return ""

# ── CSS / JS ───────────────────────────────────────────────────────────────────

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font:16px/1.6 system-ui,sans-serif;color:#222;background:#f5f5f5}
nav{background:#2c3e50;color:#fff;padding:.5rem 1rem;display:flex;gap:1rem;align-items:center}
nav a{color:#ecf0f1;text-decoration:none}nav a:hover{text-decoration:underline}
nav form{margin-left:0}nav input[type=search]{padding:.3rem .6rem;border-radius:4px;border:none}
.toolbar{background:#ecf0f1;padding:.4rem 1rem;display:flex;gap:.6rem;align-items:center;font-size:.9rem;flex-wrap:wrap}
.toolbar .breadcrumb{margin-bottom:0}
.toolbar a,.toolbar button{color:#2c3e50;background:none;border:1px solid #aaa;padding:.2rem .5rem;border-radius:3px;cursor:pointer;font-size:.85rem;text-decoration:none}
.layout{display:flex;max-width:1100px;margin:.15rem auto 1rem;gap:1rem;padding:0 1rem}
.content{flex:1;min-width:0;background:#fff;padding:1rem;border-radius:4px;border:1px solid #ddd}
.content.edit-page{padding:0;border:none;background:transparent}
.layout.edit-layout{padding:0 __EDIT_PAD__}
.layout.read-layout{padding:0 __READ_PAD__}
.toc{width:220px;flex-shrink:0;position:sticky;top:1rem;align-self:flex-start;background:#fff;border:1px solid #ddd;border-radius:4px;padding:.6rem;font-size:.85rem}
.toc h3{font-size:.9rem;margin-bottom:.4rem;display:flex;justify-content:space-between}
.toc ul{list-style:none;padding-left:0}.toc li{padding:.15rem 0}
.toc li.h2{padding-left:.8rem}.toc li.h3{padding-left:1.6rem}.toc li.h4{padding-left:2.4rem}.toc li.h5{padding-left:3.2rem}
.toc a{color:#2c3e50;text-decoration:none}.toc a:hover{text-decoration:underline}
h1,h2,h3,h4,h5{margin:1rem 0 .4rem}
h2{border-bottom:1px solid #ddd;padding-bottom:.2rem;display:flex;justify-content:space-between;align-items:center}
p{margin:.8rem 0}pre{background:#f4f4f4;padding:.8rem;border-radius:4px;overflow-x:auto;margin:.5rem 0}
code{background:#f0f0f0;padding:0 .3rem;border-radius:3px;font-size:.9em}pre code{background:none;padding:0}
hr{border:none;border-top:1px solid #ddd;margin:1rem 0}
.content ul,.content ol{padding-left:1.5em;margin:.3rem 0}
.content li{margin:__ITEM_SP__ 0}
p.todo{margin:__ITEM_SP__ 0}
.wiki-table{border-collapse:collapse;margin:.8rem 0;width:auto;max-width:100%}
.wiki-table td,.wiki-table th{border:1px solid #ddd;padding:.4rem .6rem;text-align:left;vertical-align:top}
.wiki-table th{background:#ecf0f1;font-weight:bold}
.wiki-table tr:nth-child(even) td{background:#f9f9f9}
a.new-page{color:#c0392b;text-decoration:underline dashed}
.sect-edit{font-size:.75rem;color:#888;border:1px solid #ccc;padding:.1rem .3rem;border-radius:3px;text-decoration:none;margin-left:.5rem}
.sect-edit-btns{display:inline-flex;align-items:center;gap:.25rem;white-space:nowrap;flex-shrink:0}
textarea{width:100%;font-family:monospace;font-size:.95rem;padding:.5rem;border:1px solid #ccc;border-radius:4px}
.edit-toolbar{display:flex;gap:.5rem;margin-bottom:.5rem;flex-wrap:wrap;align-items:center}
.edit-toolbar button,.edit-toolbar a{padding:.3rem .7rem;border-radius:3px;border:1px solid #aaa;cursor:pointer;text-decoration:none;font-size:.9rem}
.markup-bar{display:__MB_DESKTOP__;gap:.2rem;margin-bottom:.4rem;flex-wrap:wrap;align-items:center}
.markup-bar button{padding:.15rem .4rem;border-radius:3px;border:1px solid #bbb;cursor:pointer;font-size:.82rem;background:none;line-height:1.5;font-family:inherit}
.preview-box{margin-top:1rem;padding:1rem;border:1px dashed #aaa;border-radius:4px;background:#fff}
.notice{background:#ffeeba;border:1px solid #ffc107;padding:.8rem 1rem;border-radius:4px;margin:1rem 0}
.breadcrumb{font-size:.85rem;color:#666;margin-bottom:.5rem}.breadcrumb a{color:#2c3e50}
input[type=checkbox]{cursor:pointer;width:1.1em;height:1.1em;vertical-align:middle;-webkit-appearance:none;appearance:none;border:2px solid #e74c3c;border-radius:3px;background:#fff;position:relative;top:-.2em}
input[type=checkbox]:checked{background:#e74c3c;border-color:#e74c3c}
input[type=checkbox]:checked::after{content:'';position:absolute;left:25%;top:5%;width:35%;height:60%;border:solid #fff;border-width:0 2px 2px 0;transform:rotate(45deg)}
.todo-done{color:#aaa}
.todo-inprogress{font-style:italic}
.search-result{margin:.6rem 0;padding:.5rem;border:1px solid #ddd;border-radius:3px;background:#fff}
.search-result a{font-weight:bold}
.snippet{font-size:.85rem;color:#555;font-family:monospace}
.sitemap ul{list-style:none;padding-left:1.2rem}.sitemap>ul{padding-left:0}
.broken-file{color:#c0392b;font-style:italic}
.content img{max-width:100%;height:auto}
.content [data-line]:hover:not(.line-del){box-shadow:inset 3px 0 0 #3498db}
.content [data-line].qtodo-sel{outline:2px solid #3498db;outline-offset:2px;border-radius:2px;background:rgba(52,152,219,.07)}
.login-box{max-width:360px;margin:3rem auto;background:#fff;border:1px solid #ddd;border-radius:6px;padding:2rem}
.login-box h1{font-size:1.3rem;margin-bottom:1rem}
.login-box input[type=text],.login-box input[type=password]{width:100%;padding:.4rem .6rem;margin:.3rem 0 .8rem;border:1px solid #ccc;border-radius:4px;font-size:1rem}
.login-box button{width:100%;padding:.5rem;font-size:1rem;background:#2c3e50;color:#fff;border:none;border-radius:4px;cursor:pointer}
.login-error{background:#fde;border:1px solid #c0392b;padding:.5rem .8rem;border-radius:4px;margin-bottom:.8rem;font-size:.9rem}
@media(max-width:700px){
  nav{flex-wrap:wrap;gap:.5rem}
  nav form{width:100%;margin-left:0!important}
  nav input[type=search]{width:100%}
  .layout{flex-direction:column;padding:0 .5rem}
  .layout.edit-layout{padding:0 __EDIT_PAD__}
  .layout.read-layout{padding:0 __READ_PAD__}
  .toc{width:100%;position:static;order:-1}
  .toc ul{display:none}
  .toc h3 button{transform:scale(2,1.5);transform-origin:center;margin-right:.5rem}
  .toolbar{flex-wrap:wrap;gap:.4rem}
  .content{padding:.7rem}
  .login-box{margin:1rem auto;padding:1.2rem}
  input[type=checkbox]{width:1.4em;height:1.4em}
  .markup-bar{display:__MB_MOBILE__;gap:.35rem}
  .markup-bar button{font-size:1.1rem;padding:.4rem .65rem;min-width:2.4rem}
}
.tag-pill{display:inline-block;background:#e8f4f8;color:#2c3e50;border-radius:10px;padding:.1rem .5rem;font-size:.8rem;text-decoration:none;margin:.1rem .1rem;vertical-align:middle}
.tag-pill:hover{background:#d0e8f0}
mark{background:#fff3cd;padding:0 .1rem;border-radius:2px}
.search-page-result{margin:.8rem 0;padding:.6rem;border:1px solid #ddd;border-radius:3px;background:#fff}
.search-page-result h3{font-size:1rem;margin:0 0 .3rem}
.search-hit{font-size:.85rem;font-family:monospace;color:#444;padding:.15rem .3rem;border-left:3px solid #ddd;margin:.2rem 0}
.pin-bar{background:#243447;padding:.3rem 1rem;display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;font-size:.85rem}
.pin-bar a{color:#8ab4f8;text-decoration:none;background:rgba(255,255,255,.08);padding:.15rem .5rem;border-radius:3px}.pin-bar a:hover{text-decoration:underline}
.trace-bar{background:#e5eaee;padding:.2rem 1rem;font-size:.78rem;color:#666;display:flex;flex-wrap:wrap;gap:0 .15rem;align-items:center}
.trace-bar .trace-label{font-weight:600;margin-right:.3rem;color:#555;white-space:nowrap}
.trace-bar a{color:#2c3e50;text-decoration:none}.trace-bar a:hover{text-decoration:underline}
.line-del{font-size:.7rem;color:#c0392b;text-decoration:none;margin-left:.4rem;opacity:.3;vertical-align:middle;position:relative;top:-.2em}@media(hover:hover){.line-del:hover{opacity:1}}
.line-del.confirm{opacity:1;font-size:.75rem;background:#c0392b;color:#fff;padding:.1rem .4rem;border-radius:3px}
"""

CSS_DARK = """
html{color-scheme:dark;background:#1a1a2e}
body{color:#cdd;background:#1a1a2e}
.content{background:#16213e;border-color:#2a2a4a;color:#cdd}
.toc{background:#16213e;border-color:#2a2a4a}
.toc a{color:#8ab4f8}.toc a:hover{color:#aecbfa}
nav{background:#0f3460}
.toolbar{background:#1e2a45}
.toolbar a,.toolbar button{color:#8ab4f8;border-color:#2a3f6f}
.edit-toolbar button,.edit-toolbar a{color:#cdd;border-color:#2a3f6f}
.markup-bar button{color:#cdd;border-color:#2a3f6f}
textarea{-webkit-appearance:none;background:#000000;color:#cdd;border-color:#2a3f6f}
input[type=text],input[type=password],input[type=search]{-webkit-appearance:none;background:#1a1a2e;color:#cdd;border-color:#2a3f6f}
.preview-box{background:#16213e;border-color:#2a3f6f}
.notice{background:#3a2e00;border-color:#7a6000;color:#ffd}
pre{background:#111827}code{background:#1e2a45}
h2{border-bottom-color:#2a3f6f}
hr{border-top-color:#2a3f6f}
.breadcrumb{color:#8ab4f8}.breadcrumb a{color:#8ab4f8}
.search-result{background:#16213e;border-color:#2a3f6f}
.snippet{color:#8ab4f8}
a.new-page{color:#f87171}
.sect-edit{color:#8ab4f8;border-color:#2a3f6f}
.login-box{background:#16213e;border-color:#2a3f6f;color:#cdd}
.login-box input[type=text],.login-box input[type=password]{-webkit-appearance:none;background:#1a1a2e;color:#cdd;border-color:#2a3f6f}
.login-box button{background:#0f3460}
.login-error{background:#3a0000;border-color:#c0392b}
.wiki-table td,.wiki-table th{border-color:#2a3f6f}
.wiki-table th{background:#1e2a45}
.wiki-table tr:nth-child(even) td{background:#14192e}
.tag-pill{background:#1e3a4a;color:#8ab4f8}.tag-pill:hover{background:#254a5e}
mark{background:#5a4a00;color:#ffd}
.search-page-result{background:#16213e;border-color:#2a3f6f}
.search-hit{color:#8ab4f8;border-left-color:#2a3f6f}
.pin-bar{background:#0e1f33}
.trace-bar{background:#0d1117;color:#555}.trace-bar .trace-label{color:#666}.trace-bar a{color:#7a9fd4}
.todo-done{color:#8a9a9a}
input[type=checkbox]{background:#1a1a2e;border-color:#e74c3c}
input[type=checkbox]:checked{background:#e74c3c;border-color:#e74c3c}
input[type=checkbox]:checked::after{border-color:#fff}
.line-del{color:#f87171}
.line-del.confirm{background:#c0392b;color:#fff}
"""

JS = """
document.querySelectorAll('input[type=checkbox][data-line]').forEach(cb=>{
  cb.addEventListener('click',async e=>{
    e.preventDefault();
    const p=cb.closest('p.todo');
    const newState=await fetch(`/toggle/${cb.dataset.name}/${cb.dataset.line}`,{method:'POST'}).then(r=>r.text());
    p.dataset.state=newState;
    cb.checked=(newState==='x');
    p.classList.remove('todo-done','todo-inprogress');
    if(newState==='x')p.classList.add('todo-done');
    else if(newState==='~')p.classList.add('todo-inprogress');
  });
});
document.querySelectorAll('textarea').forEach(ta=>{
  ta.addEventListener('keydown',e=>{
    if(e.key==='Tab'){e.preventDefault();const s=e.target.selectionStart;
      e.target.value=e.target.value.slice(0,s)+'  '+e.target.value.slice(e.target.selectionEnd);
      e.target.selectionStart=e.target.selectionEnd=s+2;return;}
    // Smart list continuation only for the main markup editor
    if(ta.id!=='ed')return;
    const v=ta.value,pos=ta.selectionStart;
    if(ta.selectionStart!==ta.selectionEnd)return;
    // Find the start of the current line
    const lineStart=v.lastIndexOf('\\n',pos-1)+1;
    const lineText=v.slice(lineStart,pos);
    // Detect list prefix: optional indent spaces + (bullet/ordered/todo marker)
    const m=lineText.match(/^( *)(\\* |- |\\[ \\] |\\[x\\] |\\[~\\] )/);
    if(!m)return;
    const indent=m[1],prefix=m[2];
    const afterPrefix=lineStart+indent.length+prefix.length;
    if(e.key==='Enter'&&!e.shiftKey){
      e.preventDefault();
      // If the line contains only the prefix (empty item), clear the line instead
      if(pos===afterPrefix&&lineText===indent+prefix){
        // Remove the entire line (including its trailing newline if present)
        ta.value=v.slice(0,lineStart)+v.slice(pos+(v[pos]==='\\n'?1:0));
        ta.selectionStart=ta.selectionEnd=lineStart;
      }else{
        // Normalise todo prefix to empty state
        const newPrefix=prefix==='[x] '||prefix==='[~] '?'[ ] ':prefix;
        const ins='\\n'+indent+newPrefix;
        ta.value=v.slice(0,pos)+ins+v.slice(pos);
        ta.selectionStart=ta.selectionEnd=pos+ins.length;
      }
      ta.dispatchEvent(new Event('input'));
      return;
    }
    if(e.key===' '&&pos===afterPrefix){
      e.preventDefault();
      // Insert 2-space indent at the line start
      ta.value=v.slice(0,lineStart)+'  '+v.slice(lineStart);
      ta.selectionStart=ta.selectionEnd=pos+2;
      ta.dispatchEvent(new Event('input'));
      return;
    }
    if(e.key==='Backspace'&&pos===afterPrefix&&indent.length>=2){
      e.preventDefault();
      ta.value=v.slice(0,lineStart)+v.slice(lineStart+2);
      ta.selectionStart=ta.selectionEnd=pos-2;
      ta.dispatchEvent(new Event('input'));
      return;
    }
  });
});
document.addEventListener('click',function(e){
  var a=e.target.closest('a.line-del');if(!a)return;
  e.preventDefault();e.stopPropagation();
  if(!a.classList.contains('confirm')){
    a.classList.add('confirm');a._origText=a.textContent;a.textContent='delete?';
    a._cTimer=setTimeout(function(){a.classList.remove('confirm');a.textContent=a._origText;},3000);
    return;
  }
  clearTimeout(a._cTimer);
  var line=parseInt(a.dataset.line,10),name=a.dataset.name,el=a.closest('p.todo,li');
  if(el){el.style.transition='opacity .25s';el.style.opacity='0';}
  fetch('/delete-line/'+encodeURIComponent(name)+'/'+line,{method:'POST'})
    .then(function(r){return r.json();})
    .then(function(data){
      if(!data.ok){alert(data.error||'Delete failed');if(el){el.style.opacity='';}return;}
      if(el)el.remove();
      document.querySelectorAll('[data-line]').forEach(function(se){
        var dl=parseInt(se.dataset.line,10);if(dl>line)se.dataset.line=dl-1;
      });
    }).catch(function(){alert('Network error');if(el){el.style.opacity='';}});
});
"""

# ── static asset hashing (computed once at startup) ─────────────────────────────
# Minimal 1×1 ICO — BGRA pixel #2c3e50 (matches nav colour)
_FAVICON = bytes([
    0,0,1,0,1,0,                    # ICONDIR (reserved, type=1, count=1)
    1,1,0,0,1,0,32,0,48,0,0,0,     # ICONDIRENTRY (w,h,clrs,res,planes,bpp,size=48)
    22,0,0,0,                       # ICONDIRENTRY image offset (6+16=22)
    40,0,0,0,                       # BITMAPINFOHEADER size
    1,0,0,0,2,0,0,0,                # width=1, height=2 (ICO doubles for XOR+AND)
    1,0,32,0,                       # planes=1, bpp=32
    0,0,0,0,0,0,0,0,                # compression=BI_RGB, imageSize=0
    0,0,0,0,0,0,0,0,                # XPelsPerMeter, YPelsPerMeter
    0,0,0,0,0,0,0,0,                # clrUsed, clrImportant
    80,62,44,255,                   # pixel BGRA: #2c3e50 fully opaque
    0,0,0,0,                        # AND mask row (1px, DWORD-aligned)
])
MARKUP_BAR_JS = """
function wrapSel(b,a,ph){
  var ta=document.getElementById('ed');
  var s=ta.selectionStart,e=ta.selectionEnd;
  var sel=ta.value.slice(s,e)||(ph||'text');
  ta.value=ta.value.slice(0,s)+b+sel+a+ta.value.slice(e);
  ta.selectionStart=s+b.length;ta.selectionEnd=s+b.length+sel.length;
  ta.focus();
}
function wrapHeading(m){
  var ta=document.getElementById('ed');
  var s=ta.selectionStart;
  var ls=ta.value.lastIndexOf('\\n',s-1)+1;
  var le=ta.value.indexOf('\\n',s);
  var end=le===-1?ta.value.length:le;
  var cur=ta.value.slice(ls,end).replace(/^[=\\s]+|[=\\s]+$/g,'').trim()||'Heading';
  var nl=m+' '+cur+' '+m;
  ta.value=ta.value.slice(0,ls)+nl+ta.value.slice(end);
  ta.selectionStart=ls+m.length+1;ta.selectionEnd=ls+m.length+1+cur.length;
  ta.focus();
}
function prefixLine(p){
  var ta=document.getElementById('ed');
  var s=ta.selectionStart;
  var ls=ta.value.lastIndexOf('\\n',s-1)+1;
  ta.value=ta.value.slice(0,ls)+p+ta.value.slice(ls);
  ta.selectionStart=ta.selectionEnd=s+p.length;
  ta.focus();
}
function insertText(t){
  var ta=document.getElementById('ed');
  var s=ta.selectionStart;
  ta.value=ta.value.slice(0,s)+t+ta.value.slice(s);
  ta.selectionStart=ta.selectionEnd=s+t.length;
  ta.focus();
}
function indentLine(){
  var ta=document.getElementById('ed');
  var s=ta.selectionStart;
  var ls=ta.value.lastIndexOf('\\n',s-1)+1;
  ta.value=ta.value.slice(0,ls)+'  '+ta.value.slice(ls);
  ta.selectionStart=ta.selectionEnd=s+2;
  ta.focus();
}
function outdentLine(){
  var ta=document.getElementById('ed');
  var s=ta.selectionStart;
  var ls=ta.value.lastIndexOf('\\n',s-1)+1;
  var lead=ta.value.slice(ls,ls+2);
  if(lead==='  '){
    ta.value=ta.value.slice(0,ls)+ta.value.slice(ls+2);
    ta.selectionStart=ta.selectionEnd=Math.max(ls,s-2);
  }else{
    ta.selectionStart=ta.selectionEnd=s;
  }
  ta.focus();
}
"""

MARKUP_BAR_HTML = (
    '<div class="markup-bar">'
    '<button type="button" title="Heading 1 (====== Text ======)" onclick="wrapHeading(&apos;======&apos;)">H1</button>'
    '<button type="button" title="Heading 2 (===== Text =====)" onclick="wrapHeading(&apos;=====&apos;)">H2</button>'
    '<button type="button" title="Heading 3 (==== Text ====)" onclick="wrapHeading(&apos;====&apos;)">H3</button>'
    '<button type="button" title="Heading 4 (=== Text ===)" onclick="wrapHeading(&apos;===&apos;)">H4</button>'
    '<button type="button" title="Heading 5 (== Text ==)" onclick="wrapHeading(&apos;==&apos;)">H5</button>'
    '<button type="button" title="Bold (**text**)" onclick="wrapSel(&apos;**&apos;,&apos;**&apos;,&apos;bold text&apos;)"><b>B</b></button>'
    '<button type="button" title="Italic (//text//)" onclick="wrapSel(&apos;//&apos;,&apos;//&apos;,&apos;italic text&apos;)"><i>I</i></button>'
    '<button type="button" title="Underline (__text__)" onclick="wrapSel(&apos;__&apos;,&apos;__&apos;,&apos;underlined text&apos;)"><u>U</u></button>'
    '<button type="button" title="Strikethrough (~~text~~)" onclick="wrapSel(&apos;~~&apos;,&apos;~~&apos;,&apos;strikethrough&apos;)"><s>S</s></button>'
    '<button type="button" title="Inline code" onclick="wrapSel(&apos;`&apos;,&apos;`&apos;,&apos;code&apos;)">&#96;&hellip;&#96;</button>'
    '<button type="button" title="Outdent (remove 2 spaces)" onclick="outdentLine()">&#8676;</button>'
    '<button type="button" title="Indent (add 2 spaces)" onclick="indentLine()">&#8677;</button>'
    '<button type="button" title="Bullet list item (  * item)" onclick="prefixLine(&apos;  * &apos;)">&#8226;</button>'
    '<button type="button" title="Numbered list item (  - item)" onclick="prefixLine(&apos;  - &apos;)">1.</button>'
    '<button type="button" title="Todo checkbox item ([ ] item)" onclick="prefixLine(&apos;[ ] &apos;)">&#9744;</button>'
    '<button type="button" title="Horizontal rule (----)" onclick="insertText(&apos;\\n----\\n&apos;)">&#8212;</button>'
    '<button type="button" title="Internal link ([[PageName]])" onclick="wrapSel(&apos;[[&apos;,&apos;]]&apos;,&apos;PageName&apos;)">[[&hellip;]]</button>'
    '<button type="button" title="Code block (``` fences)" onclick="wrapSel(&apos;```\\n&apos;,&apos;\\n```&apos;,&apos;code here&apos;)">&lt;/&gt;</button>'
    '</div>'
)

# ── block editor static asset ────────────────────────────────────────────────
_BE_JS_PATH = Path(__file__).parent / "block_editor.js"
BLOCK_EDITOR_JS = _BE_JS_PATH.read_text(encoding="utf-8") if _BE_JS_PATH.exists() else "/* block_editor.js not found */"
BLOCK_EDITOR_JS_HASH = hashlib.sha256(BLOCK_EDITOR_JS.encode()).hexdigest()[:12]
BLOCK_EDITOR_JS_URL  = f"/static/block-editor-{BLOCK_EDITOR_JS_HASH}.js"

_CSS_FINAL  = (CSS
    .replace('__ITEM_SP__', ITEM_SPACING)
    .replace('__MB_DESKTOP__', 'flex' if MARKUP_BAR_DESKTOP else 'none')
    .replace('__MB_MOBILE__',  'flex' if MARKUP_BAR_MOBILE  else 'none')
    .replace('__EDIT_PAD__',   EDIT_PAGE_PADDING)
    .replace('__READ_PAD__',   READ_PAGE_PADDING)
    .replace('#2c3e50', LIGHT_NAV_BG)
    .replace('#ecf0f1', LIGHT_TOOLBAR_BG)
    .replace('#3498db', ACCENT_COLOR)
) + (
    CSS_DARK
    .replace('#1a1a2e', DARK_PAGE_BG)
    .replace('#16213e', DARK_PANEL_BG)
    .replace('#2a2a4a', DARK_PANEL_BORDER)
    .replace('#0f3460', DARK_NAV_BG)
    .replace('#1e2a45', DARK_TOOLBAR_BG)
    .replace('#2a3f6f', DARK_BORDER)
    .replace('#8ab4f8', DARK_ACCENT)
    .replace('#aecbfa', DARK_ACCENT_HOVER)
    .replace('#0e1f33', DARK_PIN_BAR_BG)
    .replace('#0d1117', DARK_TRACE_BAR_BG)
    .replace('#111827', DARK_PRE_BG)
    .replace('#14192e', DARK_TABLE_ALT)
    .replace('#1e3a4a', DARK_TAG_BG)
    .replace('#254a5e', DARK_TAG_HOVER)
    if DARK_MODE else ""
)
_CSS_HASH   = hashlib.sha256(_CSS_FINAL.encode()).hexdigest()[:12]
_JS_HASH    = hashlib.sha256(JS.encode()).hexdigest()[:12]
_ICON_ETAG  = '"' + hashlib.sha256(_FAVICON).hexdigest()[:12] + '"'
_ICON_DATA  = "data:image/x-icon;base64," + base64.b64encode(_FAVICON).decode()
CSS_URL     = f"/static/style-{_CSS_HASH}.css"
JS_URL      = f"/static/app-{_JS_HASH}.js"

@app.get("/static/style-{h}.css")
def serve_css(h: str):
    """Serve the pre-compiled stylesheet with an immutable cache header.

    The URL path embeds the first 12 hex characters of the SHA-256 hash
    of the CSS content.  Requests for a stale hash (e.g. after a server
    restart with changed config) receive a 404 so the browser fetches
    the new URL.

    Args:
        h: Hash segment extracted from the URL path.
    """
    from fastapi.responses import Response
    if h != _CSS_HASH:
        return Response(status_code=404)
    return Response(content=_CSS_FINAL, media_type="text/css",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})

@app.get("/static/app-{h}.js")
def serve_js(h: str):
    """Serve the main client-side JavaScript bundle with an immutable cache header.

    Uses the same hash-in-URL cache-busting strategy as ``serve_css``.
    Returns 404 when the hash does not match the currently loaded JS.

    Args:
        h: Hash segment extracted from the URL path.
    """
    from fastapi.responses import Response
    if h != _JS_HASH:
        return Response(status_code=404)
    return Response(content=JS, media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})

@app.get("/static/block-editor-{h}.js")
def serve_block_editor_js(h: str):
    """Serve the block-editor JavaScript bundle with an immutable cache header.

    The bundle is loaded from ``block_editor.js`` at startup.  Returns
    404 when the hash does not match the file that was loaded.

    Args:
        h: Hash segment extracted from the URL path.
    """
    from fastapi.responses import Response
    if h != BLOCK_EDITOR_JS_HASH:
        return Response(status_code=404)
    return Response(content=BLOCK_EDITOR_JS, media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})

# ── HTML helpers ───────────────────────────────────────────────────────────────

def nav_bar(search_q: str = "", username: str = "") -> str:
    """Build the top navigation bar HTML string.

    Renders the site title, standard nav links (Site Map, New Page,
    Today, Tags, Orphaned Files), an optional “My page” link when
    ``USER_PAGE_NS`` is set and the user is logged in, a settings
    gear icon, a search form, and a logout button.

    Links listed in ``NAV_ICON_ONLY`` are rendered with only their
    icon character and a ``title`` tooltip rather than icon + text,
    saving horizontal space.

    Args:
        search_q: Pre-filled search query value (HTML-escaped).
        username: Authenticated username, used to show logout and
                  personal-page links.  Empty string for anonymous.

    Returns:
        HTML ``<nav>`` element string.
    """
    q = html.escape(search_q)

    def _lnk(key: str, href: str, icon: str, label: str) -> str:
        """Return a nav <a> that is icon-only (with title tooltip) or icon+label."""
        if key in NAV_ICON_ONLY:
            return f'<a href="{href}" title="{html.escape(label)}">{icon}</a>'
        return f'<a href="{href}">{icon} {label}</a>'

    my_page_link = (
        _lnk("mypage", "/me", "&#128100;", "My page")
        if (USER_PAGE_NS and username) else ""
    )
    settings_link = (
        f'<a href="/settings" title="Settings">&#9881;</a>'
        if username else ""
    )
    logout = (
        f'<form method="post" action="/logout" style="margin-left:auto;display:inline">'
        f'<button type="submit" style="background:none;border:none;cursor:pointer;'
        f'color:#ecf0f1;font-size:.85rem;padding:0">&#128274; logout ({html.escape(username)})</button>'
        f'</form>'
    ) if username else ""
    return (
        f'<nav><a href="/"><strong>&#128366; {html.escape(SITE_TITLE)}</strong></a>'
        f'<a href="/sitemap">Site Map</a>'
        + _lnk("new",     "/new",     "&#10133;",  "New Page")
        + _lnk("today",   "/today",   "&#128197;",  "Today")
        + _lnk("tags",    "/tags",    "&#127991;",  "Tags")
        + _lnk("orphans", "/orphans", "&#128204;",  "Orphaned Files")
        + my_page_link
        + settings_link
        + logout
        + f'<form method="get" action="/search" {"" if username else "style=\"margin-left:auto\""}'
        + f'><input type="search" name="q" placeholder="Search\u2026" value="{q}"></form></nav>'
    )


def _get_pins(request: Request | None) -> list[str]:
    """Return the validated list of pinned page names.

    For authenticated users pins are stored in the dbm (server-side, per-user).
    For non-auth mode the legacy browser cookie is used as a fallback.
    """
    if request is None:
        return []
    username = getattr(request.state, "username", "") or ""
    if username:
        raw = _get_user_setting(username, "pins")
        if not raw:
            return []
        try:
            pins = json.loads(raw)
            if not isinstance(pins, list):
                return []
        except Exception:
            return []
    else:
        # Non-auth fallback: read from cookie
        raw = request.cookies.get("wiki_pins", "")
        if not raw:
            return []
        try:
            pins = json.loads(raw)
            if not isinstance(pins, list):
                return []
        except Exception:
            return []
    valid = []
    for p in pins[:20]:
        if not isinstance(p, str):
            continue
        try:
            norm = normalize_name(p)
            page_path(norm)  # validates characters
            valid.append(norm)
        except ValueError:
            continue
    return valid


def _save_pins(username: str, response, pins: list[str]) -> None:
    """Persist pin list: dbm for authenticated users, cookie fallback otherwise."""
    if username:
        _set_user_setting(username, "pins", json.dumps(pins))
    else:
        _set_pins_cookie(response, pins)


def _set_pins_cookie(response, pins: list[str]):
    """Write pins to browser cookie (non-auth fallback only)."""
    response.set_cookie("wiki_pins", json.dumps(pins), max_age=365 * 86400,
                        httponly=True, samesite="strict", secure=HTTPS_ENABLED, path="/")


# ── trace (recently-visited) helpers ─────────────────────────────────────────

def _get_trace(username: str) -> list[str]:
    """Return the user's recently-visited page list (most recent first)."""
    raw = _get_user_setting(username, "trace")
    if not raw:
        return []
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def _update_trace(username: str, name: str) -> None:
    """Append name to the user's trace list and persist it, capped at TRACE_MAX."""
    if not username or not TRACE_ENABLED or TRACE_MAX <= 0:
        return
    trace = _get_trace(username)
    trace = [p for p in trace if p != name]  # remove existing occurrence
    trace.append(name)                        # most recent goes last
    _set_user_setting(username, "trace", json.dumps(trace[-TRACE_MAX:]))


def trace_bar(request: Request | None) -> str:
    """Return DokuWiki-style trace bar HTML, or '' if disabled/unavailable."""
    if not TRACE_ENABLED:
        return ""
    username = (getattr(request.state, "username", "") or "") if request is not None else ""
    if not username:
        return ""
    trace = _get_trace(username)
    if not trace:
        return ""
    items = " \u2022 ".join(
        f'<a href="/wiki/{html.escape(p)}">{html.escape(p.split("/")[-1])}</a>'
        for p in trace
    )
    return f'<div class="trace-bar"><span class="trace-label">Trace:</span> \u2022 {items}</div>'


def pins_bar(request: Request | None) -> str:
    """Build the pinned-pages bar HTML string.

    Reads the current user’s pin list via ``_get_pins``.  If
    ``USER_PAGE_HIDDEN`` is enabled, pins belonging to other users’
    namespaces are filtered out before rendering.

    When there are no visible pins the element is still emitted but
    with ``style="display:none"`` so that client-side pin-toggle
    JavaScript can find and show it without a page reload.

    Args:
        request: The current HTTP request (used to read cookies /
                 user settings).  May be ``None``.

    Returns:
        HTML ``<div id="pin-bar" …>`` element string.
    """
    pins = _get_pins(request)
    if USER_PAGE_HIDDEN and USER_PAGE_NS:
        requester = (getattr(request.state, "username", "") or "") if request is not None else ""
        pins = [p for p in pins
                if not (_is_user_ns(p)[0] and _is_user_ns(p)[1] != requester)]
    if not pins:
        return '<div id="pin-bar" class="pin-bar" style="display:none"></div>'
    links = "".join(
        f'<a href="/wiki/{html.escape(p)}">&#128204; {html.escape(p.split("/")[-1])}</a>'
        for p in pins
    )
    return f'<div id="pin-bar" class="pin-bar">{links}</div>'


def shell(title: str, body: str, search_q: str = "", request: Request | None = None) -> str:
    """Wrap *body* in a full HTML page, including the navigation and pin bar.

    Produces a complete ``<!doctype html>`` document with:

    * A ``<title>`` of ``“{title} — {SITE_TITLE}”``.
    * The versioned CSS and JS ``<link>``/``<script>`` references
      (cache-busted by content hash).
    * The site navigation bar (via ``nav_bar``) and pinned-pages bar
      (via ``pins_bar``).
    * *body* injected verbatim between the bars and the closing
      ``</body>`` tag.

    When ``AUTH_ENABLED`` is ``True`` the authenticated username is
    resolved from the request state (or the token cookie) and passed
    to ``nav_bar`` so the logout button shows the correct name.

    Args:
        title:     Page-specific title string (not HTML-escaped —
                   callers should escape if needed).
        body:      Pre-rendered HTML body content.
        search_q:  Value to pre-fill in the nav search box.
        request:   Current HTTP request; ``None`` is safe (yields an
                   anonymous nav bar).

    Returns:
        Full HTML document string.
    """
    username = ""
    if AUTH_ENABLED and request is not None:
        username = getattr(request.state, "username", None)
        if username is None:
            username = _validate_token(_get_token(request)) or ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)} \u2014 {html.escape(SITE_TITLE)}</title>'
            f'<link rel="icon" href="{_ICON_DATA}">'
            f'<link rel="stylesheet" href="{CSS_URL}"></head><body>'
            f'{nav_bar(search_q, username)}{pins_bar(request)}{body}'
            f'<script src="{JS_URL}"></script></body></html>')

def breadcrumb(name: str) -> str:
    """Build a DokuWiki-style breadcrumb navigation trail for a page.

    Produces a ``<div class="breadcrumb">`` with links for each
    namespace component, anchored to the namespace index (``/ns/…``),
    plus a plain-text current page name at the end.  The root link
    always points to ``/wiki/Home``.

    Example for page ``"projects/sub/MyPage"``:

    .. code-block:: text

        root › projects › sub › MyPage

    Args:
        name: Wiki page name with ``/`` namespace separators.

    Returns:
        HTML ``<div class="breadcrumb">…</div>`` string.
    """
    parts = name.split("/")
    crumbs = [f'<a href="/wiki/Home">root</a>']
    for i, p in enumerate(parts[:-1]):
        crumbs.append(f'<a href="/ns/{"/".join(parts[:i+1])}">{html.escape(p)}</a>')
    crumbs.append(html.escape(parts[-1]))
    return f'<div class="breadcrumb">{" &rsaquo; ".join(crumbs)}</div>'


def _toc_max(meta: dict) -> int | None:
    """Return per-page TOC max level from meta, or None to use the site default."""
    raw = meta.get("toc_max_level", "").strip()
    if raw.isdigit():
        return max(1, min(5, int(raw)))
    return None


def toc_html(headings: list, max_level: int | None = None) -> str:
    """Build a collapsible Table of Contents HTML block.

    Filters the headings list to those whose level does not exceed
    *max_level* (or ``TOC_MAX_LEVEL`` when *max_level* is ``None``).
    Returns an empty string when no headings survive the filter.

    The TOC ``<ul>`` is rendered with per-level CSS classes
    (``h2``, ``h3``, …) that drive indentation.  A toggle button
    collapses or expands the list via inline JavaScript.

    Args:
        headings:  List of ``(level, text, anchor)`` tuples as returned
                   by ``parse``.
        max_level: Deepest heading level to include (1–5).  ``None``
                   uses the site-wide ``TOC_MAX_LEVEL`` setting.

    Returns:
        HTML ``<div class="toc">…</div>`` string, or ``""`` when there
        are no headings at or above the requested depth.
    """
    cap = max_level if max_level is not None else TOC_MAX_LEVEL
    visible = [(lvl, txt, anc) for lvl, txt, anc in headings if lvl <= cap]
    if not visible:
        return ""
    items = "".join(
        f'<li class="h{lvl}"><a href="#{anc}">{html.escape(txt)}</a></li>'
        for lvl, txt, anc in visible
    )
    return (f'<div class="toc"><h3 style="cursor:pointer" onclick="var u=this.closest(\'.toc\').querySelector(\'ul\');u.style.display=u.style.display===\'none\'?\'block\':\'none\'">Contents '
            f'<button onclick="event.stopPropagation();var u=this.closest(\'.toc\').querySelector(\'ul\');u.style.display=u.style.display===\'none\'?\'block\':\'none\'">&#177;</button>'
            f'</h3><ul>{items}</ul></div>')

def dir_listing(d: Path, prefix: str, hide_fn=None) -> str:
    """Build an HTML ``<ul>`` listing sub-directories and wiki pages in *d*.

    Directories are shown with a folder icon and link to ``/ns/<rel>``.
    Wiki files (``.wiki`` extension, excluding names starting with
    ``_``) are shown with a page icon, a link to ``/wiki/<name>``, and
    a faint last-modified date.

    The optional *hide_fn* callable receives each item’s relative path
    string and should return ``True`` to suppress the item from the
    listing (used to hide other users’ private pages when
    ``USER_PAGE_HIDDEN`` is enabled).

    Args:
        d:       Directory to list (a ``pathlib.Path``).
        prefix:  Namespace prefix string to prepend to child names
                 (e.g. ``"projects/sub"``).  Pass ``""`` for the root.
        hide_fn: Optional callable ``(relative_path: str) -> bool``.
                 Items for which it returns ``True`` are omitted.

    Returns:
        HTML ``<ul>…</ul>`` string.
    """
    items = '<ul style="list-style:none;padding-left:0">'
    for child in sorted(d.iterdir()):
        if child.is_dir() and re.fullmatch(r"[A-Za-z0-9_\-]+", child.name):
            rel = f"{prefix}/{child.name}" if prefix else child.name
            if hide_fn and hide_fn(rel):
                continue
            items += f'<li>&#128193; <a href="/ns/{rel}">{html.escape(child.name)}/</a></li>'
        elif child.suffix == ".wiki" and not child.name.startswith("_"):
            pname = f"{prefix}/{child.stem}" if prefix else child.stem
            if hide_fn and hide_fn(pname):
                continue
            try:
                mtime = time.strftime("%Y-%m-%d", time.localtime(child.stat().st_mtime))
            except OSError:
                mtime = "unknown"
            items += f'<li>&#128196; <a href="/wiki/{html.escape(pname)}">{html.escape(child.stem)}</a> <small style="color:#888">{mtime}</small></li>'
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
# ── auth helpers ──────────────────────────────────────────────────────────────

# ---- token store ----

def _now() -> datetime:
    """Return the current UTC time as a timezone-aware ``datetime``."""
    return datetime.now(timezone.utc)

def _load_tokens() -> dict:
    """Load the token store from ``TOKEN_FILE`` and return it as a dict.

    The file is a JSON object mapping token strings to dicts with
    ``"user"``, ``"issued"``, and ``"expires"`` ISO-8601 fields.
    Returns an empty dict if the file does not exist or cannot be
    parsed.
    """
    if TOKEN_FILE.exists():
        try:
            data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}

def _save_tokens(tokens: dict):
    """Persist the token store dict atomically to ``TOKEN_FILE``.

    Writes to a randomly-named temp file with mode ``0o600``, renames
    it over the target, then ensures the target also has mode ``0o600``.
    The temp file is removed in a ``finally`` block even if an error
    occurs mid-write.

    Args:
        tokens: Dict mapping token strings to their metadata dicts.
    """
    tmp = TOKEN_FILE.parent / f"{TOKEN_FILE.name}.{secrets.token_hex(4)}.tmp"
    try:
        tmp.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(TOKEN_FILE)
        TOKEN_FILE.chmod(0o600)
    finally:
        tmp.unlink(missing_ok=True)

_token_lock = threading.Lock()

def _issue_token(username: str) -> str:
    """Create, persist, and return a new authentication token for *username*.

    Generates a 64-character hex token using ``secrets.token_hex``.
    Before writing, expired tokens are pruned from the store.
    The token is valid for ``TOKEN_EXPIRY_DAYS`` days from issuance.

    The load-prune-add-save cycle is protected by a module-level
    ``threading.Lock`` to prevent concurrent writers from corrupting
    the file.

    Args:
        username: The authenticated username to associate with the token.

    Returns:
        The newly issued token string (64 hex characters).
    """
    token = secrets.token_hex(32)
    now = _now()
    def _is_valid_unexpired(v: object) -> bool:
        try:
            return isinstance(v, dict) and datetime.fromisoformat(v["expires"]) > now
        except (KeyError, ValueError, TypeError):
            return False
    with _token_lock:
        tokens = _load_tokens()
        # prune expired — skip any malformed entries rather than crashing
        tokens = {k: v for k, v in tokens.items() if _is_valid_unexpired(v)}
        tokens[token] = {
            "user": username,
            "issued": now.isoformat(),
            "expires": (now + timedelta(days=TOKEN_EXPIRY_DAYS)).isoformat(),
        }
        _save_tokens(tokens)
    return token

def _validate_token(token: str) -> str | None:
    """Return username if token is valid, else None."""
    if not token:
        return None
    tokens = _load_tokens()
    entry = tokens.get(token)
    if not entry or not isinstance(entry, dict):
        return None
    try:
        if datetime.fromisoformat(entry["expires"]) <= _now():
            return None
        return entry["user"] or None
    except (KeyError, ValueError, TypeError):
        return None

def _revoke_token(token: str):
    """Remove *token* from the persistent token store.

    Called on logout.  The operation is a no-op if the token does not
    exist in the store (e.g. already expired and pruned).  Thread-safe
    via the module-level ``_token_lock``.

    Args:
        token: Token string to revoke.
    """
    with _token_lock:
        tokens = _load_tokens()
        tokens.pop(token, None)
        _save_tokens(tokens)

def _get_token(request: Request) -> str:
    """Extract token from cookie, then query param, then Authorization header."""
    t = request.cookies.get("wiki_token", "")
    if not t:
        t = request.query_params.get("wiki_token", "")
    if not t:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            t = auth[7:].strip()
    return t

# ---- rate limiter ----

_fail_log: dict[str, list[float]] = {}  # ip -> [timestamp, ...]
_FAIL_WINDOW = 60      # seconds
_FAIL_MAX    = 5       # attempts before lockout

def _real_ip(request: Request) -> str:
    """Return the real client IP, honouring X-Forwarded-For when the connection
    comes from a trusted proxy address (TRUSTED_PROXY config set)."""
    peer = request.client.host if request.client else "unknown"
    if TRUSTED_PROXY and peer in TRUSTED_PROXY:
        xff = request.headers.get("x-forwarded-for", "").split(",")
        # Take the rightmost entry — added by the trusted proxy, not client-controllable
        candidate = xff[-1].strip()
        if candidate:
            return candidate
    return peer

def _check_rate(ip: str) -> bool:
    """Return True if the IP is allowed to attempt login, False if locked out."""
    now = time.monotonic()
    hits = [t for t in _fail_log.get(ip, []) if now - t < _FAIL_WINDOW]
    if hits:
        _fail_log[ip] = hits
    else:
        _fail_log.pop(ip, None)
    return len(hits) < _FAIL_MAX

def _record_fail(ip: str):
    """Record a failed login attempt for *ip* in the in-memory rate-limit log.

    Args:
        ip: Client IP address string (as returned by ``_real_ip``).
    """
    now = time.monotonic()
    _fail_log.setdefault(ip, []).append(now)

# ---- htpasswd checker ----

def _check_password(username: str, password: str) -> bool:
    """Verify username/password against HTPASSWD_FILE. Supports bcrypt hashes only."""
    try:
        import bcrypt as _bcrypt  # type: ignore
    except ImportError:
        return False
    # Dummy hash used for constant-time comparison when username is not found,
    # preventing timing-based username enumeration.
    # Must be exactly 60 bytes — a valid bcrypt hash length.
    _DUMMY = b"$2b$12$aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    try:
        lines = HTPASSWD_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        _bcrypt.checkpw(password.encode(), _DUMMY)
        return False
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        u, h = line.split(":", 1)
        if u != username:
            continue
        hb = h.encode()
        # Apache uses $2y$; Python bcrypt uses $2b$ — identical algorithm
        if hb.startswith(b"$2y$"):
            hb = b"$2b$" + hb[4:]
        try:
            return _bcrypt.checkpw(password.encode(), hb)
        except Exception:
            return False
    # Username not found — run bcrypt against a dummy hash to equalise response time
    _bcrypt.checkpw(password.encode(), _DUMMY)
    return False

def _htpasswd_set(username: str, password: str, htfile: Path):
    """Add or update a user entry in an htpasswd file using bcrypt."""
    import bcrypt as _bcrypt  # type: ignore
    hashed = _bcrypt.hashpw(password.encode(), _bcrypt.gensalt(rounds=12)).decode()
    lines: list[str] = []
    if htfile.exists():
        for line in htfile.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#") and ":" in line:
                if line.split(":", 1)[0] == username:
                    continue  # overwrite below
            lines.append(line)
    lines.append(f"{username}:{hashed}")
    tmp = htfile.parent / f"{htfile.name}.{secrets.token_hex(4)}.tmp"
    try:
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(htfile)
        htfile.chmod(0o600)
    finally:
        tmp.unlink(missing_ok=True)

# ---- FastAPI dependency ----

_auth_log = logging.getLogger("ticktap_wiki.auth")

def require_auth(request: Request):
    """FastAPI dependency that enforces authentication when ``AUTH_ENABLED`` is ``True``.

    If the request carries a valid token (via cookie, query parameter,
    or ``Authorization: Bearer`` header), the resolved username is
    stored on ``request.state.username`` and the dependency returns
    normally.

    If authentication is disabled (``AUTH_ENABLED=False``),
    ``request.state.username`` is set to ``""`` and the dependency
    always succeeds.

    When the request is unauthenticated, raises ``_LoginRedirect``,
    which is caught by the registered exception handler and turned into
    a ``303 See Other`` redirect to ``/login?next=<original_url>``.

    Args:
        request: The current FastAPI ``Request`` object (injected by
                 the dependency system).
    """
    if not AUTH_ENABLED:
        request.state.username = ""
        return
    token = _get_token(request)
    username = _validate_token(token)
    _auth_log.info("require_auth %s token=%s valid=%s",
                   request.url.path, bool(token), bool(username))
    if username:
        request.state.username = username
        return
    # Preserve the original URL so we can redirect back after login
    next_url = str(request.url)
    raise _LoginRedirect(next_url)

class _LoginRedirect(Exception):
    def __init__(self, next_url: str):
        self.next_url = next_url

@app.exception_handler(_LoginRedirect)
async def _login_redirect_handler(request: Request, exc: _LoginRedirect):
    from urllib.parse import quote, urlparse
    # Extract only path+query so the next= param works under both HTTP and HTTPS
    parsed = urlparse(exc.next_url)
    path_qs = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return RedirectResponse(f"/login?next={quote(path_qs, safe='')}", status_code=303)

# ── routes ─────────────────────────────────────────────────────────────────────

@app.get("/favicon.ico")
def favicon(request: Request):
    from fastapi.responses import Response
    if request.headers.get("if-none-match") == _ICON_ETAG:
        return Response(status_code=304, headers={"ETag": _ICON_ETAG,
                        "Cache-Control": "public, max-age=31536000, immutable"})
    return Response(content=_FAVICON, media_type="image/x-icon",
                    headers={"Cache-Control": "public, max-age=31536000, immutable",
                             "ETag": _ICON_ETAG})

@app.get("/")
def root(request: Request, _auth: None = Depends(require_auth)):
    """Redirect to the appropriate landing page for the current user.

    Resolution order:

    1. If logged in and the user has a ``home_page`` setting, redirect
       there (after validating it as a legal page name).
    2. If ``USER_PAGE_NS`` is configured and the username forms a valid
       page-name segment, redirect to
       ``<USER_PAGE_NS>/<username>/<USER_HOME_PAGE>``.
    3. Fall through to ``/wiki/Home``.
    """
    username = getattr(request.state, "username", "") or ""
    if username:
        saved = _get_user_setting(username, "home_page")
        if saved:
            # Convert colon-form to slash-form for the URL
            target = normalize_name(saved.replace(":", "/"))
            try:
                page_path(target)  # validate
                return RedirectResponse(f"/wiki/{target}")
            except ValueError:
                pass  # invalid saved setting, fall through to default
        # No explicit setting — derive from USER_PAGE_NS/username/USER_HOME_PAGE (same as /me)
        if USER_PAGE_NS and re.fullmatch(r"[A-Za-z0-9_\-]+", username):
            target = normalize_name(f"{USER_PAGE_NS}/{username}/{USER_HOME_PAGE}")
            try:
                page_path(target)  # validate segments
                return RedirectResponse(f"/wiki/{target}")
            except ValueError:
                pass
    return RedirectResponse("/wiki/Home")


@app.get("/me")
def my_page(request: Request, _auth: None = Depends(require_auth)):
    """Redirect the logged-in user to their personal homepage.

    Constructs the path ``<USER_PAGE_NS>/<username>/<USER_HOME_PAGE>``
    and issues a 303 redirect.  Redirects to ``/wiki/Home`` when
    ``USER_PAGE_NS`` is not configured, when the user is not
    authenticated, or when the username contains characters illegal
    in a page-name segment.
    """
    if not USER_PAGE_NS:
        return RedirectResponse("/wiki/Home", status_code=303)
    username = request.state.username
    if not username:
        return RedirectResponse("/wiki/Home", status_code=303)
    # Validate that the username forms a valid page-name segment; usernames with
    # dots, @ or other special chars can't be used as wiki page segments.
    for _seg in [USER_PAGE_NS.split("/")[0], username]:
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", _seg):
            return RedirectResponse("/wiki/Home", status_code=303)
    return RedirectResponse(f"/wiki/{USER_PAGE_NS}/{quote(username, safe='')}/{quote(USER_HOME_PAGE, safe='')}", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
def settings_get(request: Request, saved: str = "", _auth: None = Depends(require_auth)):
    """Render the user settings page (GET).

    Displays two fieldsets:

    * **Navigation** — home page override (colon-separated page name).
    * **Today link** — journal page format template with a live
      JavaScript preview updated as the user types.

    Shows a “saved” banner when the ``saved=1`` query parameter is
    present (set by ``settings_post`` after a successful save).

    Redirects to ``/wiki/Home`` when the user is not authenticated.

    Args:
        request: Current HTTP request.
        saved:   ``"1"`` to display the success banner.
    """
    username = getattr(request.state, "username", "") or ""
    if not username:
        return RedirectResponse("/wiki/Home", status_code=303)
    # Build defaults
    if USER_PAGE_NS and re.fullmatch(r"[A-Za-z0-9_\-]+", username):
        default_home = f"{USER_PAGE_NS.replace('/', ':')}:{username}:{USER_HOME_PAGE}"
    else:
        default_home = "Home"
    current_home = _get_user_setting(username, "home_page") or default_home
    current_journal = _get_user_setting(username, "journal_format") or JOURNAL_PAGE_FORMAT
    # Compute a live preview of the journal format using the current time
    try:
        tz = ZoneInfo(DISPLAY_TIMEZONE)
    except Exception:
        tz = timezone.utc
    now = datetime.now(tz)
    try:
        journal_preview = _apply_journal_format(current_journal, now)
    except Exception:
        journal_preview = "(invalid)"
    saved_banner = ('<div class="notice" style="background:#d4edda;border-color:#28a745;color:#155724;margin-bottom:.8rem">'
                   '&#10003; Settings saved.</div>') if saved == "1" else ""
    _tok = '<table style="border-collapse:collapse;font-size:.8rem;margin-top:.5rem">'
    _tok += '<tr><th style="text-align:left;padding:.15rem .4rem;border:1px solid #ccc">Token</th><th style="text-align:left;padding:.15rem .4rem;border:1px solid #ccc">Meaning</th><th style="text-align:left;padding:.15rem .4rem;border:1px solid #ccc">Example</th></tr>'
    for tok, meaning, example in [
        ("{yyyy}", "4-digit year",          now.strftime("%Y")),
        ("{yy}",   "2-digit year",          now.strftime("%y")),
        ("{mmmm}", "Full month name",       now.strftime("%B")),
        ("{mmm}",  "Short month name",      now.strftime("%b")),
        ("{mm}",   "Month, zero-padded",    now.strftime("%m")),
        ("{m}",    "Month, no padding",     str(now.month)),
        ("{dd}",   "Day, zero-padded",      now.strftime("%d")),
        ("{d}",    "Day, no padding",       str(now.day)),
        ("{www}",  "Full weekday name",     now.strftime("%A")),
        ("{ww}",   "Short weekday name",    now.strftime("%a")),
        ("{wn}",   "ISO week number",       now.strftime("%V")),
        ("{q}",    "Quarter (1\u20134)",     str((now.month - 1) // 3 + 1)),
        ("{hh}",   "Hour, 24h zero-padded", now.strftime("%H")),
        ("{HH}",   "Hour, 12h zero-padded", now.strftime("%I")),
        ("{p}",    "am / pm",               now.strftime("%p").lower()),
    ]:
        _tok += (f'<tr><td style="padding:.15rem .4rem;border:1px solid #ccc;font-family:monospace">{tok}</td>'
                 f'<td style="padding:.15rem .4rem;border:1px solid #ccc">{meaning}</td>'
                 f'<td style="padding:.15rem .4rem;border:1px solid #ccc">{example}</td></tr>')
    _tok += '</table>'
    _jf_tokens = json.dumps({
        "yyyy": now.strftime("%Y"), "yy": now.strftime("%y"),
        "mmmm": now.strftime("%B"), "mmm": now.strftime("%b"),
        "mm": now.strftime("%m"), "m": str(now.month),
        "dd": now.strftime("%d"), "d": str(now.day),
        "www": now.strftime("%A"), "ww": now.strftime("%a"),
        "wn": now.strftime("%V"), "q": str((now.month - 1) // 3 + 1),
        "hh": now.strftime("%H"), "HH": now.strftime("%I"),
        "p": now.strftime("%p").lower(),
    })
    body = (
        f'<div class="layout"><div class="content">'
        f'<h1>&#9881; Settings</h1>'
        f'{saved_banner}'
        f'<form method="post" action="/settings" style="max-width:560px">'
        f'<fieldset style="border:1px solid #ccc;border-radius:4px;padding:1rem;margin-bottom:1rem">'
        f'<legend style="padding:0 .4rem;font-weight:bold">Navigation</legend>'
        f'<label style="display:block;margin-bottom:.4rem;font-size:.9rem">'
        f'Home page (shown when you open the site):'
        f'<input type="text" name="home_page" value="{html.escape(current_home)}" '
        f'pattern="[A-Za-z0-9_\\-:]+" '
        f'style="display:block;width:100%;margin-top:.3rem;padding:.35rem .5rem;font-size:1rem;'
        f'box-sizing:border-box" '
        f'placeholder="e.g. {html.escape(default_home)}">'
        f'<small style="color:#888">Use <code>:</code> for namespaces. '
        f'Leave blank to use the site default (<code>Home</code>).</small>'
        f'</label>'
        f'</fieldset>'
        f'<fieldset style="border:1px solid #ccc;border-radius:4px;padding:1rem;margin-bottom:1rem">'
        f'<legend style="padding:0 .4rem;font-weight:bold">Today link</legend>'
        f'<label style="display:block;margin-bottom:.6rem;font-size:.9rem">'
        f'Page format template:'
        f'<input type="text" name="journal_format" id="jf" value="{html.escape(current_journal)}" '
        f'style="display:block;width:100%;margin-top:.3rem;padding:.35rem .5rem;font-size:1rem;'
        f'font-family:monospace;box-sizing:border-box" '
        f'placeholder="e.g. {html.escape(JOURNAL_PAGE_FORMAT)}">'
        f'<small style="color:#888">Use <code>:</code> for namespaces. '
        f'Leave blank to use the site default.'
        f'<br>Current page: <code id="jfprev">{html.escape(journal_preview)}</code></small>'
        f'</label>'
        f'{_tok}'
        f'</fieldset>'
        f'<button type="submit" style="padding:.4rem .9rem;background:#2980b9;color:#fff;'
        f'border:1px solid #1a5276;border-radius:3px;cursor:pointer">Save</button>'
        f'&nbsp;<a href="/">Cancel</a>'
        f'</form>'
        f'<script>'
        f'(function(){{'
        f'  var inp=document.getElementById("jf");'
        f'  var prev=document.getElementById("jfprev");'
        f'  if(!inp||!prev)return;'
        f'  var tokens={_jf_tokens};'
        f'  function update(){{'
        f'    var v=inp.value;'
        f'    Object.entries(tokens).forEach(function(e){{v=v.split("{{"+ e[0] +"}}").join(e[1]);}});'
        f'    prev.textContent=v;'
        f'  }}'
        f'  inp.addEventListener("input",update);'
        f'}})();'
        f'</script>'
        f'</div></div>'
    )
    return HTMLResponse(shell("Settings", body, request=request))


@app.post("/settings", response_class=HTMLResponse)
def settings_post(request: Request, home_page: str = Form(""), journal_format: str = Form(""), _auth: None = Depends(require_auth)):
    """Save user settings (POST).

    Validates the submitted home-page name and journal-format template,
    then persists them together as a single atomic write.  On
    validation error returns a 400 page with an error message.
    On success redirects to ``/settings?saved=1``.

    Args:
        request:        Current HTTP request.
        home_page:      New home-page setting (colon-separated page
                        name, or empty to use the site default).
        journal_format: New journal page format template string, or
                        empty to use the site default.
    """
    username = getattr(request.state, "username", "") or ""
    if not username:
        return RedirectResponse("/wiki/Home", status_code=303)

    def _err(msg: str) -> HTMLResponse:
        body = (
            f'<div class="layout"><div class="content">'
            f'<h1>&#9881; Settings</h1>'
            f'<div class="notice" style="background:#f8d7da;border-color:#f5c6cb;color:#721c24">'
            f'{msg}</div>'
            f'<p><a href="/settings">&larr; Back</a></p>'
            f'</div></div>'
        )
        return HTMLResponse(shell("Settings", body, request=request), status_code=400)

    home_page = home_page.strip()
    if home_page:
        target = normalize_name(home_page.replace(":", "/"))
        try:
            page_path(target)
        except ValueError:
            return _err("Invalid home page name — use only letters, digits, hyphens, underscores and "
                        "<code>:</code> for namespaces.")

    journal_format = journal_format.strip()
    new_journal: str | None = None
    if journal_format:
        # Validate by rendering with a fixed date and checking each resulting path segment
        try:
            tz = ZoneInfo(DISPLAY_TIMEZONE)
        except Exception:
            tz = timezone.utc
        rendered = _apply_journal_format(journal_format, datetime.now(tz))
        test_target = normalize_name(rendered.replace(":", "/"))
        try:
            page_path(test_target)
        except ValueError:
            return _err("Invalid journal format — the resulting page name contains invalid characters. "
                        "Only letters, digits, hyphens, underscores and <code>:</code> (namespace separators) are allowed.")
        new_journal = journal_format

    # All validation passed — persist both settings atomically
    _set_user_settings(username, {
        "home_page": home_page,
        "journal_format": new_journal if new_journal is not None else "",
    })

    return RedirectResponse("/settings?saved=1", status_code=303)


@app.get("/wiki/{name:path}", response_class=HTMLResponse)
def view(request: Request, name: str, _auth: None = Depends(require_auth)):
    """Render and display a wiki page.

    Flow:

    1. Normalise and access-check the page name.
    2. Read the raw markup with ``read_page``; if missing, show a
       “page does not exist” notice with a create link.
    3. Parse the markup with ``parse`` to produce HTML and a headings
       list for the TOC.
    4. Build the reader toolbar (edit, history, rename, pin, delete
       links), the quick-todo floating bar, and the floating add-todo
       button.
    5. Update the user’s recently-visited trace via ``_update_trace``.
    6. Wrap everything in ``shell`` and return an ``HTMLResponse``.

    Args:
        request: Current HTTP request.
        name:    Wiki page name from the URL path (may include ``/``
                 namespace separators).
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    try:
        src = read_page(name)
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    if src is None:
        body = (f'<div class="layout"><div class="content">{breadcrumb(name)}'
                f'<div class="notice">This page does not exist &mdash; '
                f'<a href="/edit/{name}">create it?</a></div></div></div>')
        return HTMLResponse(shell(name, body, request=request), 200)
    rendered, headings = parse(src, name)
    try:
        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(page_path(name).stat().st_mtime))
    except OSError:
        mtime = "unknown"
    meta = parse_meta(src)
    tags = [t.strip() for t in meta.get("tags", "").split(",") if t.strip()]
    tags_html = "".join(
        f'<a href="/tags/{quote(t, safe="")}" class="tag-pill">{html.escape(t)}</a>'
        for t in tags
    )
    pins = _get_pins(request)
    is_pinned = name in pins
    pin_icon = "&#128204;" if is_pinned else "&#128205;"
    pin_title = "Unpin page" if is_pinned else "Pin page"
    toolbar = (f'<div class="toolbar">{breadcrumb(name)}'
               f'{tags_html}'
               f'<span style="margin-left:auto;font-size:.8rem;color:#666">Modified: {mtime}</span>'
               f'<a href="/block-edit/{name}" class="sect-edit" title="Block editor">&#9783;</a>'
               f'<a href="/edit/{name}">[edit page]</a>'
               + (f'<a href="/history/{name}" title="History" style="font-size:1rem">&#128336;</a>' if VERSIONING_ENABLED else '') +
               f'<a href="/rename/{html.escape(name)}" title="Rename page" style="font-size:1rem">&#9999;</a>'
               f'<form method="post" action="/pin/{html.escape(name)}" style="display:inline">'
               f'<button type="submit" title="{pin_title}" style="padding:.2rem .4rem;font-size:.9rem;background:none;border:1px solid #aaa;border-radius:3px;cursor:pointer">{pin_icon}</button>'
               f'</form>'
               f'<a href="/delete/{name}" title="Delete page" style="color:#c0392b;font-size:1rem">&#128465;</a></div>')
    todo_bar = (
        f'<div id="qtodo-bar" style="display:none;position:fixed;bottom:0;left:0;right:0;'
        f'background:#2c3e50;color:#fff;padding:.5rem 1rem;align-items:center;'
        f'gap:.5rem;z-index:100;flex-wrap:wrap;box-shadow:0 -3px 10px rgba(0,0,0,.25)">'
        f'<span style="font-size:.85rem;white-space:nowrap">After: '
        f'<em id="qtodo-preview" style="font-style:normal;color:#8ab4f8;max-width:220px;'
        f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'
        f'display:inline-block;vertical-align:middle"></em></span>'
        f'<div style="display:flex;flex:1;gap:.5rem;flex-wrap:wrap;align-items:center">'
        f'<input type="text" id="qtodo-text" autocomplete="off" '
        f'placeholder="Todo description\u2026" style="flex:1;min-width:160px;padding:.35rem .6rem;'
        f'border-radius:3px;border:none;font-size:.9rem">'
        f'<button id="qtodo-add" onclick="qtodoSubmit()" style="padding:.35rem .7rem;border-radius:3px;border:none;'
        f'cursor:pointer;background:#27ae60;color:#fff;white-space:nowrap">&#10010; Add</button>'
        f'<button type="button" onclick="qtodoCancel()" style="padding:.35rem .6rem;'
        f'border-radius:3px;border:1px solid #777;cursor:pointer;background:none;color:#ddd">&times;</button>'
        f'</div></div>'
        f'<script>'
        f'var _wikiPage="{html.escape(name)}";'
        f'var _qtodoEl=null,_qtodoLine=-1,_qtodoIndent=0,_qtodoPrefix="[ ] ";'
        f'function qtodoSelect(el){{'
        f'if(_qtodoEl)_qtodoEl.classList.remove("qtodo-sel");'
        f'_qtodoEl=el;_qtodoLine=parseInt(el.dataset.line,10);'
        f'_qtodoIndent=parseInt(el.dataset.indent||"0",10);'
        f'_qtodoPrefix=el.dataset.prefix||"[ ] ";'
        f'el.classList.add("qtodo-sel");'
        f'var p=el.cloneNode(true);var _ds=p.querySelectorAll(".line-del");_ds.forEach(function(d){{d.remove();}});p=p.innerText.replace(/^\\s*\\[.\\]\\s*/,"").replace(/\\s+/g," ").trim();'
        f'if(p.length>50)p=p.slice(0,50)+"\u2026";'
        f'document.getElementById("qtodo-preview").textContent=p;'
        f'document.getElementById("qtodo-bar").style.display="flex";'
        f'var inp=document.getElementById("qtodo-text");inp.value="";inp.focus();'
        f'}}'
        f'function qtodoCancel(){{'
        f'if(_qtodoEl)_qtodoEl.classList.remove("qtodo-sel");'
        f'_qtodoEl=null;_qtodoLine=-1;_qtodoIndent=0;_qtodoPrefix="[ ] ";'
        f'document.getElementById("qtodo-bar").style.display="none";'
        f'}}'
        f'function qtodoOpenBottom(){{'
        f'if(_qtodoEl)_qtodoEl.classList.remove("qtodo-sel");'
        f'_qtodoEl=null;_qtodoLine=999999;_qtodoIndent=0;_qtodoPrefix="[ ] ";'
        f'var allEls=document.querySelectorAll(".content [data-line]");'
        f'if(allEls.length){{var lastEl=allEls[allEls.length-1];var lp=lastEl.dataset.prefix||"";'
        f'if(lp==="* "||lp==="- "){{_qtodoPrefix=lp;_qtodoIndent=parseInt(lastEl.dataset.indent||"0",10);_qtodoEl=lastEl;}}}}'
        f'document.getElementById("qtodo-preview").textContent="end of page";'
        f'document.getElementById("qtodo-bar").style.display="flex";'
        f'var inp=document.getElementById("qtodo-text");inp.value="";inp.focus();'
        f'}}'
        f'async function qtodoSubmit(){{'
        f'var text=document.getElementById("qtodo-text").value.trim();'
        f'if(!text||_qtodoLine<0)return;'
        f'var btn=document.getElementById("qtodo-add");'
        f'btn.disabled=true;'
        f'try{{'
        f'var resp=await fetch("/add-todo/{html.escape(name)}",{{'
        f'  method:"POST",'
        f'  headers:{{"Content-Type":"application/json"}},'
        f'  body:JSON.stringify({{after_line:_qtodoLine,text:text,indent:_qtodoIndent,prefix:_qtodoPrefix}})'
        f'}});'
        f'var data=await resp.json();'
        f'if(!resp.ok||!data.ok){{alert(data.error||"Save failed");btn.disabled=false;return;}}'
        f'document.querySelectorAll(".content [data-line]").forEach(function(se){{var dl=parseInt(se.dataset.line,10);if(dl>=data.line)se.dataset.line=dl+1;}});'
        f'if(_qtodoPrefix[0]==="["){{'
        f'var newEl=document.createElement("p");'
        f'newEl.className="todo";'
        f'newEl.dataset.line=data.line;'
        f'newEl.dataset.indent=_qtodoIndent;'
        f'newEl.dataset.prefix=_qtodoPrefix;'
        f'if(_qtodoIndent>0)newEl.style.paddingLeft=(_qtodoIndent/2*1.5)+"em";'
        f'var cb=document.createElement("input");'
        f'cb.type="checkbox";cb.dataset.line=data.line;cb.dataset.name="{html.escape(name)}";'
        f'cb.addEventListener("click",async function(e){{'
        f'  e.preventDefault();var p=cb.closest("p.todo");'
        f'  var ns=await fetch("/toggle/{html.escape(name)}/"+cb.dataset.line,{{method:"POST"}}).then(r=>r.text());'
        f'  p.dataset.state=ns;cb.checked=(ns==="x");'
        f'  p.classList.remove("todo-done","todo-inprogress");'
        f'  if(ns==="x")p.classList.add("todo-done");'
        f'  else if(ns==="~")p.classList.add("todo-inprogress");'
        f'}});'
        f'newEl.appendChild(cb);'
        f'newEl.appendChild(document.createTextNode(" "+text));'
        + (f'var _dl=document.createElement("a");_dl.className="line-del";_dl.href="#";'
        f'_dl.dataset.line=data.line;_dl.dataset.name="{html.escape(name)}";_dl.textContent="\u274c";'
        f'newEl.appendChild(document.createTextNode(" "));newEl.appendChild(_dl);' if INLINE_DELETE else '') +
        f'var content=document.querySelector(".content");'
        f'if(_qtodoEl){{var anchor=_qtodoEl;while(anchor.parentElement&&anchor.parentElement!==content)anchor=anchor.parentElement;anchor.insertAdjacentElement("afterend",newEl);}}'
        f'else{{content.appendChild(newEl);}}'
        f'newEl.style.background="rgba(39,174,96,.15)";'
        f'setTimeout(function(){{newEl.style.background="";}},800);'
        f'}}else{{'
        f'var newLi=document.createElement("li");'
        f'newLi.dataset.line=data.line;'
        f'newLi.dataset.indent=_qtodoIndent;'
        f'newLi.dataset.prefix=_qtodoPrefix;'
        f'newLi.appendChild(document.createTextNode(text));'
        + (f'var _dl2=document.createElement("a");_dl2.className="line-del";_dl2.href="#";'
        f'_dl2.dataset.line=data.line;_dl2.dataset.name="{html.escape(name)}";_dl2.textContent="\u274c";'
        f'newLi.appendChild(document.createTextNode(" "));newLi.appendChild(_dl2);' if INLINE_DELETE else '') +
        f'if(_qtodoEl){{_qtodoEl.insertAdjacentElement("afterend",newLi);}}'
        f'else{{var content2=document.querySelector(".content");if(content2)content2.appendChild(newLi);}}'
        f'newLi.style.background="rgba(39,174,96,.15)";'
        f'setTimeout(function(){{newLi.style.background="";}},800);'
        f'}}'
        f'qtodoCancel();'
        f'}}catch(e){{alert("Network error");}}'
        f'finally{{btn.disabled=false;}}'
        f'}}'
        f'document.addEventListener("keydown",function(e){{'
        f'if(e.key==="Enter"&&document.activeElement&&document.activeElement.id==="qtodo-text"){{e.preventDefault();qtodoSubmit();}}'
        f'if(e.key==="Escape")qtodoCancel();'
        f'}});'
        f'document.addEventListener("DOMContentLoaded",function(){{'
        f'document.querySelector(".content").addEventListener("click",function(e){{'
        f'if(window.getSelection&&window.getSelection().toString().length>0)return;'
        f'var t=e.target;'
        f'while(t&&t!==this){{if(t.tagName==="A")return;if(t.tagName==="INPUT"&&t.type==="checkbox")return;t=t.parentElement;}}'
        f'var el=e.target;'
        f'while(el&&el!==this){{if(el.dataset&&el.dataset.line!==undefined){{qtodoSelect(el);return;}}el=el.parentElement;}}'
        f'}});}});'
        f'</script>'
    )
    fab = (
        f'<button onclick="qtodoOpenBottom()" title="Quick-add todo at end of page" '
        f'style="position:fixed;bottom:4.5rem;right:1rem;z-index:99;width:3rem;height:3rem;'
        f'border-radius:50%;background:#27ae60;color:#fff;border:none;font-size:1.5rem;'
        f'cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.3);line-height:1">+</button>'
    )
    username = (getattr(request.state, "username", "") or "") if request is not None else ""
    _update_trace(username, name)
    body = f'{toolbar}{trace_bar(request)}{todo_bar}{fab}<div class="layout read-layout"><div class="content">{rendered}</div>{toc_html(headings, _toc_max(meta))}</div>'
    return HTMLResponse(shell(name.split("/")[-1], body, request=request))


@app.get("/sect/{name:path}/{idx}", response_class=HTMLResponse)
def edit_section_get(request: Request, name: str, idx: int, _auth: None = Depends(require_auth)):
    """Render the section editor for a single editable heading section.

    Locates section *idx* using ``find_editable_sections``, extracts the
    corresponding source lines, and renders a ``<textarea>`` editor
    pre-populated with just those lines.  The heading’s deduplicated
    anchor is passed as a hidden form field so that the save handler
    can redirect back to the correct section heading even after
    concurrent edits have shifted line numbers.

    Args:
        request: Current HTTP request.
        name:    Wiki page name.
        idx:     0-based section index to edit.
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    _check_page_owner(request, name)
    if idx < 0:
        return HTMLResponse("Section not found", 400)
    try:
        src = read_page(name) or ""
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    sections = find_editable_sections(src, SECTION_EDIT_MIN, SECTION_EDIT_MAX)
    if idx >= len(sections):
        return HTMLResponse("Section not found", 400)
    _level, start_line, end_line = sections[idx]
    src_lines = src.split("\n")
    # Compute the deduplicated anchor so cancel and save redirect back to this section
    anchor = _compute_anchor_for_line(src, start_line)
    content = html.escape("\n".join(src_lines[start_line:end_line]))
    frag = f"#{anchor}" if anchor else ""
    body = (f'<div class="layout edit-layout"><div class="content edit-page">{breadcrumb(name)}'
            f'<h2>Edit section</h2>'
            f'<form method="post"><div class="edit-toolbar">'
            f'<button type="submit">Save section</button>'
            f'<a href="/wiki/{name}{frag}">Cancel</a></div>'
            f'{MARKUP_BAR_HTML}'
            f'<textarea name="content" rows="20" id="ed">{content}</textarea>'
            f'<input type="hidden" name="anchor" value="{html.escape(anchor)}">'
            f'</form></div></div>'
            f'<script>{MARKUP_BAR_JS}</script>')
    return HTMLResponse(shell(f"Edit section \u2014 {name}", body, request=request))


@app.post("/sect/{name:path}/{idx}", response_class=HTMLResponse)
async def edit_section_post(request: Request, name: str, idx: int, content: str = Form(""), anchor: str = Form(""), _auth: None = Depends(require_auth)):
    """Accept a posted section edit and splice it back into the full page.

    Replaces lines ``[start_line:end_line]`` of the existing source with
    the posted *content*.  When an *anchor* is provided the section is
    located by anchor match (robust to concurrent edits changing line
    numbers) rather than purely by *idx*.  After saving, redirects to
    the page anchored at the edited heading.

    Args:
        request: Current HTTP request.
        name:    Wiki page name.
        idx:     0-based section index (used as a fallback when *anchor*
                 doesn’t match).
        content: New markup for the section only.
        anchor:  Heading anchor slug from the GET form’s hidden field.
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    _check_page_owner(request, name)
    if idx < 0:
        return HTMLResponse("Section not found", 400)
    try:
        src = read_page(name) or ""
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    sections = find_editable_sections(src, SECTION_EDIT_MIN, SECTION_EDIT_MAX)
    if idx >= len(sections):
        return HTMLResponse("Section not found", 400)
    # Prefer locating the section by its heading anchor (more robust under concurrent edits).
    # Fall back to idx if the anchor is absent or doesn't match any section.
    target_idx = idx
    if anchor:
        for i, (_, sl, _el) in enumerate(sections):
            if _compute_anchor_for_line(src, sl) == anchor:
                target_idx = i
                break
    _level, start_line, end_line = sections[target_idx]
    src_lines = src.split("\n")
    new_content = content.replace("\r\n", "\n").replace("\r", "\n")
    src_lines[start_line:end_line] = new_content.split("\n")
    # Recompute deduplicated anchor from the full new source
    new_src = "\n".join(src_lines)
    new_anchor = _compute_anchor_for_line(new_src, start_line)
    frag = f"#{new_anchor}" if new_anchor else (f"#{anchor}" if anchor else "")
    try:
        write_page(name, "\n".join(src_lines))
    except OSError:
        return HTMLResponse("Save failed", 500)
    return RedirectResponse(f"/wiki/{name}{frag}", status_code=303)


def _is_user_ns(path: str) -> tuple[bool, str]:
    """Return (True, owner_username) if path falls within USER_PAGE_NS, else (False, "")."""
    if not USER_PAGE_NS:
        return False, ""
    ns_parts = USER_PAGE_NS.split("/")
    ns_depth = len(ns_parts)
    parts = path.strip("/").split("/")
    if parts[:ns_depth] != ns_parts or len(parts) <= ns_depth:
        return False, ""
    return True, parts[ns_depth]


def _check_page_owner(request: Request, name: str):
    """If USER_PAGE_PRIVATE is enabled, forbid editing another user's page."""
    if not USER_PAGE_PRIVATE or not USER_PAGE_NS:
        return
    requester = getattr(request.state, "username", "") or ""
    if not requester:
        # Auth is disabled or no identity — ownership cannot be determined, allow.
        return
    in_user_ns, owner = _is_user_ns(name)
    if not in_user_ns:
        return
    if requester != owner:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="You may only edit your own user page.")


def _check_page_reader(request: Request, name: str):
    """If USER_PAGE_HIDDEN is enabled, only the owner may read their user pages."""
    if not USER_PAGE_HIDDEN or not USER_PAGE_NS:
        return
    in_user_ns, owner = _is_user_ns(name)
    if not in_user_ns:
        return
    requester = getattr(request.state, "username", "") or ""
    if not requester:
        return  # auth disabled — ownership indeterminate, allow
    if requester != owner:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="This page is private.")


def _check_file_ns_owner(request: Request, ns: str):
    """If USER_PAGE_PRIVATE or USER_PAGE_HIDDEN is enabled, only the owner may upload/delete files in their user namespace."""
    if not (USER_PAGE_PRIVATE or USER_PAGE_HIDDEN) or not USER_PAGE_NS:
        return
    in_user_ns, owner = _is_user_ns(ns)
    if not in_user_ns:
        return
    requester = getattr(request.state, "username", "") or ""
    if not requester:
        return  # auth disabled
    if requester != owner:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="You may only manage files in your own user namespace.")


@app.get("/edit/{name:path}", response_class=HTMLResponse)
def edit_get(request: Request, name: str, _auth: None = Depends(require_auth)):
    """Render the full-page markup editor for a wiki page.

    Loads existing content (or generates a default skeleton for new
    pages) and renders a ``<textarea>`` editor with the markup toolbar
    and a live-preview button.  An “Attach” button opens the file
    upload popup in a new tab, pre-seeded with the namespace of the
    current page.

    Args:
        request: Current HTTP request.
        name:    Wiki page name to edit.
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    _check_page_owner(request, name)
    try:
        src = read_page(name)
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    if src is None:
        src = f"====== {name.split('/')[-1].replace('_', ' ')} ======\n\n===== Introduction =====\n\nNew page.\n"
    content = html.escape(src)
    ns_for_upload = "/".join(name.split("/")[:-1])
    upload_href = f"/upload/{ns_for_upload}" if ns_for_upload else "/upload"
    body = (f'<div class="layout edit-layout"><div class="content edit-page">{breadcrumb(name)}'
            f'<div class="edit-toolbar">'
            f'<strong>{html.escape(name.split("/")[-1])}</strong>'
            f'<button form="ef" type="submit">Save</button>'
            f'<a href="/wiki/{name}">Cancel</a>'
            f'<button type="button" onclick="showPreview()">Preview</button>'
            f'<button type="button" onclick="openAttach()">&#128206; Attach</button>'
            f'</div>'
            f'{MARKUP_BAR_HTML}'
            f'<form id="ef" method="post">'
            f'<textarea name="content" rows="30" id="ed">{content}</textarea>'
            f'</form>'
            f'<div id="pv" class="preview-box" style="display:none"></div>'
            f'</div></div>'
            f'<script>'
            f'{MARKUP_BAR_JS}'
            f'async function showPreview(){{'
            f'  const r=await fetch("/preview",{{method:"POST",'
            f'    body:new URLSearchParams({{name:"{name}",content:document.getElementById("ed").value}})}});'
            f'  const d=document.getElementById("pv");'
            f'  d.innerHTML=await r.text();d.style.display="block";'
            f'}}'
            f'function openAttach(){{'
            f'  var pos=document.getElementById("ed").selectionStart;'
            f'  window.open("{upload_href}?pos="+pos,"_blank");'
            f'}}'
            f'</script>')
    return HTMLResponse(shell(f"Edit — {name}", body, request=request))


@app.post("/edit/{name:path}", response_class=HTMLResponse)
async def edit_post(request: Request, name: str, content: str = Form(""), _auth: None = Depends(require_auth)):
    """Accept a posted full-page edit and save it.

    Validates the page name, writes the new content via ``write_page``
    (which handles line-ending normalisation, atomic replace, and
    snapshotting), then redirects to the reader view.

    Args:
        request: Current HTTP request.
        name:    Wiki page name to save.
        content: New raw wiki markup from the editor ``<textarea>``.
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    _check_page_owner(request, name)
    try:
        write_page(name, content)
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    except OSError:
        return HTMLResponse("Save failed", 500)
    return RedirectResponse(f"/wiki/{name}", status_code=303)


@app.post("/preview", response_class=HTMLResponse)
async def preview(name: str = Form(""), content: str = Form(""), _auth: None = Depends(require_auth)):
    """Render a preview of wiki markup and return the HTML fragment.

    Called via ``fetch`` from the editor page.  Parses *content* with
    ``section_edit=False`` (no [edit] buttons) and returns the
    resulting HTML string directly — not wrapped in a full shell page.

    Args:
        name:    Page name (used for resolving relative links).
        content: Raw wiki markup to render.
    """
    rendered, _ = parse(content, name, section_edit=False)
    return HTMLResponse(rendered)


@app.post("/toggle/{name:path}/{line}", response_class=HTMLResponse)
async def toggle(request: Request, name: str, line: int, _auth: None = Depends(require_auth)):
    """Toggle or cycle the checkbox state of a single todo line.

    Reads the page source, locates line number *line*, and applies
    the state cycle defined by ``TODO_CYCLE_3STATE``:

    * When ``TODO_CYCLE_3STATE=False`` (default): ``[ ]`` ↔ ``[x]``.
    * When ``TODO_CYCLE_3STATE=True``: ``[ ]`` → ``[x]`` → ``[~]`` → ``[ ]``.

    The write is done with ``snapshot=False`` to avoid polluting the
    version history with every checkbox click.

    Returns the new single-character state (``' '``, ``'x'``, or
    ``'~'``) as plain text so the client can update the DOM.

    Args:
        request: Current HTTP request.
        name:    Wiki page name.
        line:    0-based line number of the checkbox to toggle.
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    _check_page_owner(request, name)
    if line < 0:
        return HTMLResponse("Out of range", 400)
    try:
        src = read_page(name)
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    if src is None:
        return HTMLResponse("Not found", 404)
    lines = src.splitlines(keepends=True)
    if line >= len(lines):
        return HTMLResponse("Out of range", 400)
    ln = lines[line].rstrip("\r\n")
    # Target only the leading checkbox marker to avoid matching [x] inside the text
    # Cycle: [ ] → [x] → [~] → [ ] when TODO_CYCLE_3STATE, else toggle [ ] ↔ [x]
    _cycle = {" ": "x", "x": "~", "~": " "} if TODO_CYCLE_3STATE else {" ": "x", "x": " ", "~": " "}
    new_ln = re.sub(r"^(\s*)\[([ x~])\]",
                    lambda m: m.group(1) + "[" + _cycle[m.group(2)] + "]",
                    ln)
    if new_ln == ln:
        return HTMLResponse("ok")  # not a checkbox line
    # Preserve original line ending
    eol = lines[line][len(ln):] or "\n"
    lines[line] = new_ln + eol
    try:
        write_page(name, "".join(lines), snapshot=False)
    except OSError:
        return HTMLResponse("write failed", 500)
    # Return the new state character so the client can update the DOM
    m = re.search(r"\[([ x~])\]", ln)
    new_state = _cycle.get(m.group(1), " ") if m else " "
    return HTMLResponse(new_state)


@app.post("/add-todo/{name:path}")
async def add_todo(name: str, request: Request, _auth: None = Depends(require_auth)):
    """Insert a new todo or list item into a wiki page via JSON.

    The JSON request body must contain:

    * ``after_line`` (int): Insert the new item *after* this 0-based
      line number.  Use a large value (e.g. 999999) to append at the
      end of the page.
    * ``text`` (str): Todo/item text (newlines collapsed to spaces).
    * ``indent`` (int, 0–20): Indentation level in units of 2 spaces.
    * ``prefix`` (str): One of ``"[ ] "``, ``"* "``, or ``"- "``.

    The write uses ``snapshot=False`` to avoid generating a history
    entry for each item addition.

    Returns JSON ``{"ok": true, "line": <inserted_line_number>}`` on
    success, or ``{"ok": false, "error": "..."}`` on failure.

    Args:
        name:    Wiki page name.
        request: Current HTTP request (body read as JSON).
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    _check_page_owner(request, name)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)
    after_line = body.get("after_line", -1)
    text = body.get("text", "")
    indent = body.get("indent", 0)
    prefix = body.get("prefix", "[ ] ")
    if not isinstance(after_line, int) or not isinstance(text, str):
        return JSONResponse({"ok": False, "error": "Bad request"}, status_code=400)
    if not isinstance(indent, int) or indent < 0 or indent > 20:
        return JSONResponse({"ok": False, "error": "Bad request"}, status_code=400)
    if prefix not in ("[ ] ", "* ", "- "):
        return JSONResponse({"ok": False, "error": "Bad request"}, status_code=400)
    text = text.replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "Empty text"}, status_code=400)
    if after_line < 0:
        return JSONResponse({"ok": False, "error": "Invalid line"}, status_code=400)
    try:
        src = read_page(name)
    except ValueError:
        return JSONResponse({"ok": False, "error": "Invalid page name"}, status_code=400)
    if src is None:
        src = ""
    lines = src.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    insert_at = max(0, min(after_line + 1, len(lines)))
    lines.insert(insert_at, f"{' ' * indent}{prefix}{text}\n")
    try:
        write_page(name, "".join(lines), snapshot=False)
    except OSError:
        return JSONResponse({"ok": False, "error": "Save failed"}, status_code=500)
    return JSONResponse({"ok": True, "line": insert_at})


@app.post("/delete-line/{name:path}/{line}")
async def delete_line(request: Request, name: str, line: int, _auth: None = Depends(require_auth)):
    """Delete a single todo or list item line from a wiki page.

    Only lines matching the todo pattern (``[ ]``, ``[x]``, ``[~]``)
    or the list-item pattern (two-or-more leading spaces + ``*``/``-``)
    may be deleted via this endpoint.  Attempting to delete any other
    line returns a 400 error.

    The write uses ``snapshot=False`` since inline deletions are
    considered minor edits that should not generate history entries.

    Returns JSON ``{"ok": true, "deleted_line": <N>}`` on success.

    Args:
        request: Current HTTP request.
        name:    Wiki page name.
        line:    0-based index of the line to delete.
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    _check_page_owner(request, name)
    if line < 0:
        return JSONResponse({"ok": False, "error": "Invalid line"}, status_code=400)
    try:
        src = read_page(name)
    except ValueError:
        return JSONResponse({"ok": False, "error": "Invalid page name"}, status_code=400)
    if src is None:
        return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
    lines = src.splitlines(keepends=True)
    if line >= len(lines):
        return JSONResponse({"ok": False, "error": "Out of range"}, status_code=400)
    ln = lines[line].rstrip("\r\n")
    if not re.match(r"^\s*\[[ x~]\] ", ln) and not re.match(r"^ {2,}[*\-] ", ln):
        return JSONResponse({"ok": False, "error": "Not a todo or list item"}, status_code=400)
    del lines[line]
    try:
        write_page(name, "".join(lines), snapshot=False)
    except OSError:
        return JSONResponse({"ok": False, "error": "Save failed"}, status_code=500)
    return JSONResponse({"ok": True, "deleted_line": line})


# ── block editor routes ────────────────────────────────────────────────────────

@app.get("/raw/{name:path}")
def raw_page(request: Request, name: str, _auth: None = Depends(require_auth)):
    """Return the raw wiki markup of a page as JSON.

    Used by the block editor JavaScript to load page content without
    a full HTML render.  Returns ``{"content": "<markup>"}`` with an
    empty string when the page does not exist yet.

    Args:
        request: Current HTTP request.
        name:    Wiki page name.
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    try:
        src = read_page(name)
    except ValueError:
        return JSONResponse({"error": "Invalid page name"}, status_code=400)
    return JSONResponse({"content": src or ""})


@app.get("/raw-sect/{name:path}/{idx}")
def raw_section(request: Request, name: str, idx: int, _auth: None = Depends(require_auth)):
    """Return the raw markup for a single editable section as JSON.

    Locates section number *idx* using ``find_editable_sections`` and
    returns ``{"content": "<section_markup>", "anchor": "<slug>"}``.
    Used by the block-editor to load individual sections.

    Args:
        request: Current HTTP request.
        name:    Wiki page name.
        idx:     0-based section index (as assigned by
                 ``find_editable_sections``).
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    if idx < 0:
        return JSONResponse({"error": "Section not found"}, status_code=404)
    try:
        src = read_page(name) or ""
    except ValueError:
        return JSONResponse({"error": "Invalid page name"}, status_code=400)
    sections = find_editable_sections(src, SECTION_EDIT_MIN, SECTION_EDIT_MAX)
    if idx >= len(sections):
        return JSONResponse({"error": "Section not found"}, status_code=404)
    _level, start_line, end_line = sections[idx]
    anchor = _compute_anchor_for_line(src, start_line)
    content = "\n".join(src.split("\n")[start_line:end_line])
    return JSONResponse({"content": content, "anchor": anchor})


@app.get("/block-edit/{name:path}", response_class=HTMLResponse)
def block_edit(request: Request, name: str, _auth: None = Depends(require_auth)):
    """Render the block-editor UI for a full wiki page.

    Emits a minimal shell page containing only a ``<div
    id="block-editor-root" data-page="...">`` mount point and a
    ``<script>`` tag loading ``block_editor.js``.  The JavaScript
    bundle takes over from there and fetches the page content via
    ``/raw/<name>``.

    Args:
        request: Current HTTP request.
        name:    Wiki page name to edit.
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    _check_page_owner(request, name)
    try:
        page_path(name)  # validate
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    body = (f'<div id="block-editor-root" data-page="{html.escape(name)}"></div>'
            f'<script src="{BLOCK_EDITOR_JS_URL}" defer></script>')
    return HTMLResponse(shell(f"Block Edit \u2014 {name}", body, request=request))


@app.get("/block-sect/{name:path}/{idx}", response_class=HTMLResponse)
def block_sect(request: Request, name: str, idx: int, _auth: None = Depends(require_auth)):
    """Render the block-editor UI scoped to a single section.

    Like ``block_edit`` but adds a ``data-sect="{idx}"`` attribute on
    the root element so the JavaScript knows to operate on one section
    rather than the full page.  Content is fetched via
    ``/raw-sect/<name>/<idx>``.

    Args:
        request: Current HTTP request.
        name:    Wiki page name.
        idx:     0-based section index to edit.
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    _check_page_owner(request, name)
    if idx < 0:
        return HTMLResponse("Section not found", 400)
    try:
        src = read_page(name) or ""
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    sections = find_editable_sections(src, SECTION_EDIT_MIN, SECTION_EDIT_MAX)
    if idx >= len(sections):
        return HTMLResponse("Section not found", 400)
    body = (f'<div id="block-editor-root" data-page="{html.escape(name)}" data-sect="{idx}"></div>'
            f'<script src="{BLOCK_EDITOR_JS_URL}" defer></script>')
    return HTMLResponse(shell(f"Block Edit section \u2014 {name}", body, request=request))


@app.get("/new", response_class=HTMLResponse)
def new_page(request: Request, _auth: None = Depends(require_auth)):
    """Render the new-page creation form.

    Displays a text input for the page name (colon-separated namespace
    notation is accepted).  On submit the browser navigates directly to
    ``/edit/<name>`` via client-side JavaScript (no server round-trip
    for the redirect).
    """
    body = ('<div class="layout"><div class="content"><h1>New Page</h1>'
            '<p>Use <code>:</code> for namespaces, e.g. <code>projects:MyPage</code></p>'
            '<form id="nf" onsubmit="event.preventDefault();location.href=\'/edit/\'+document.getElementById(\'ni\').value.replace(/ /g,\'_\').replace(/:/g,\'/'+'\')">'
            '<input type="text" name="n" id="ni" style="width:100%;padding:.4rem;font-size:1rem;margin:.5rem 0"'
            ' placeholder="PageName or ns:PageName" pattern="[A-Za-z0-9_ \\-:]+" required><br>'
            '<button type="submit">Create</button>'
            '</form></div></div>')
    return HTMLResponse(shell("New Page", body, request=request))


@app.get("/ns/{ns:path}", response_class=HTMLResponse)
def ns_view(request: Request, ns: str, _auth: None = Depends(require_auth)):
    """Render a directory listing for a wiki namespace.

    Shows all sub-namespaces and wiki pages inside the corresponding
    sub-directory of ``PAGES_DIR``, along with the file attachment
    section for the namespace.  Respects ``USER_PAGE_HIDDEN``: other
    users’ namespaces are hidden from the listing and inaccessible
    directly.

    Args:
        request: Current HTTP request.
        ns:      Namespace path (e.g. ``"projects/sub"``), extracted
                 from the URL.
    """
    ns = normalize_name(ns)
    for p in ns.split("/"):
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", p):
            return HTMLResponse("Invalid namespace", 400)
    # Block access to another user's namespace when USER_PAGE_HIDDEN is enabled
    if USER_PAGE_HIDDEN:
        _in_ns, _owner = _is_user_ns(ns)
        if _in_ns and (getattr(request.state, "username", "") or "") != _owner:
            return HTMLResponse("Not found", 404)
    ns_dir = PAGES_DIR.joinpath(*ns.split("/"))
    if not ns_dir.is_dir():
        return HTMLResponse("Namespace not found", 404)
    ns_clean = ns.strip("/")
    ns_display = ns_clean.replace("/", ":")
    requester = getattr(request.state, "username", "") or ""
    _hide = (lambda p: _is_user_ns(p)[0] and _is_user_ns(p)[1] != requester) if USER_PAGE_HIDDEN else None
    # When USER_PAGE_HIDDEN is active, suppress the files section for a user sub-namespace
    # that doesn't belong to the current user (e.g. /ns/user visits files/user/).
    _in_ns, _ns_owner = _is_user_ns(ns_clean) if ns_clean else (False, "")
    _hide_files = USER_PAGE_HIDDEN and _in_ns and _ns_owner != requester
    body = (f'<div class="layout"><div class="content">'
            f'<h1>Namespace: {html.escape(ns_display)}</h1>'
            f'{dir_listing(ns_dir, ns_clean, _hide)}'
            f'{"" if _hide_files else files_section(ns_clean)}'
            f'</div></div>')
    return HTMLResponse(shell(f"ns:{ns_display}", body, request=request))


@app.get("/sitemap", response_class=HTMLResponse)
def sitemap(request: Request, _auth: None = Depends(require_auth)):
    """Render the full site map as a recursive HTML tree.

    Walks all directories and ``.wiki`` files under ``PAGES_DIR`` and
    builds a nested ``<ul>`` tree.  When ``USER_PAGE_HIDDEN`` is
    enabled, other users’ pages and namespaces are omitted from the
    tree for the current requester.

    Args:
        request: Current HTTP request.
    """
    requester = getattr(request.state, "username", "") or ""
    def tree(d: Path, prefix: str) -> str:
        s = '<ul style="list-style:none;padding-left:1.2rem">'
        for child in sorted(d.iterdir()):
            if child.is_dir() and re.fullmatch(r"[A-Za-z0-9_\-]+", child.name):
                rel = f"{prefix}/{child.name}" if prefix else child.name
                if USER_PAGE_HIDDEN:
                    _in_ns, _owner = _is_user_ns(rel)
                    if _in_ns and _owner != requester:
                        continue
                s += f'<li>&#128193; <a href="/ns/{rel}"><strong>{html.escape(child.name)}:</strong></a>{tree(child, rel)}</li>'
            elif child.suffix == ".wiki" and not child.name.startswith("_"):
                pname = f"{prefix}/{child.stem}" if prefix else child.stem
                if USER_PAGE_HIDDEN:
                    _in_ns, _owner = _is_user_ns(pname)
                    if _in_ns and _owner != requester:
                        continue
                try:
                    mtime = time.strftime("%Y-%m-%d", time.localtime(child.stat().st_mtime))
                except OSError:
                    mtime = "unknown"
                s += f'<li>&#128196; <a href="/wiki/{html.escape(pname)}">{html.escape(child.stem)}</a> <small style="color:#888">{mtime}</small></li>'
        return s + "</ul>"
    body = f'<div class="layout"><div class="content sitemap"><h1>Site Map</h1>{tree(PAGES_DIR, "")}</div></div>'
    return HTMLResponse(shell("Site Map", body, request=request))


@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = "", _auth: None = Depends(require_auth)):
    """Full-text search across all wiki pages.

    Case-insensitive substring search performed in Python (no index).
    For each matching page, up to a few context lines around each hit
    are shown with the matching text highlighted via ``<mark>``.
    Results are sorted alphabetically by page name.  Pages in other
    users’ private namespaces are excluded when ``USER_PAGE_HIDDEN``
    is enabled.

    Redirects to ``/`` when the query is empty.

    Args:
        request: Current HTTP request.
        q:       Search query string.
    """
    q = q.strip()
    if not q:
        return RedirectResponse("/")
    ql = q.lower()

    def _highlight(text: str) -> str:
        parts, lo, start = [], text.lower(), 0
        while True:
            idx = lo.find(ql, start)
            if idx == -1:
                parts.append(html.escape(text[start:]))
                break
            parts.append(html.escape(text[start:idx]))
            parts.append(f'<mark>{html.escape(text[idx:idx + len(q)])}</mark>')
            start = idx + len(q)
        return "".join(parts)

    results = []
    for f in sorted(PAGES_DIR.rglob("*.wiki")):
        try:
            raw = f.read_text(encoding="utf-8")
        except Exception:
            continue
        text, _ = strip_meta(raw)  # skip ~~META: block so it doesn't pollute results
        lines = text.splitlines()
        hit_indices = [i for i, ln in enumerate(lines) if ql in ln.lower()]
        if not hit_indices:
            continue
        pname = str(f.relative_to(PAGES_DIR).with_suffix("")).replace("\\", "/")
        if USER_PAGE_HIDDEN:
            _in_ns, _owner = _is_user_ns(pname)
            if _in_ns and _owner != (getattr(request.state, "username", "") or ""):
                continue
        shown: set[int] = set()
        snippets = []
        for hi in hit_indices:
            for ci in range(max(0, hi - 1), min(len(lines), hi + 2)):
                if ci not in shown:
                    shown.add(ci)
                    line_h = _highlight(lines[ci].strip()[:180]) if ci == hi else html.escape(lines[ci].strip()[:180])
                    bg = ' style="background:rgba(52,152,219,.07)"' if ci == hi else ''
                    snippets.append(f'<div class="search-hit"{bg}>{line_h}</div>')
        results.append(
            f'<div class="search-page-result">'
            f'<h3><a href="/wiki/{html.escape(pname)}">{html.escape(pname.replace("/", ":"))}</a>'
            f' <small style="color:#888;font-weight:normal">({len(hit_indices)} match{"es" if len(hit_indices) != 1 else ""})</small></h3>'
            f'{"".join(snippets)}</div>'
        )
    body = (f'<div class="layout"><div class="content">'
            f'<h1>&#128269; Search: {html.escape(q)}</h1>'
            f'<p>{len(results)} page{"s" if len(results) != 1 else ""} matched</p>'
            f'{"".join(results) or "<p>No results found.</p>"}'
            f'</div></div>')
    return HTMLResponse(shell(f"Search: {q}", body, search_q=q, request=request))


@app.get("/rename/{name:path}", response_class=HTMLResponse)
def rename_get(request: Request, name: str, _auth: None = Depends(require_auth)):
    """Render the rename form for a wiki page (GET).

    Displays the current page name in an editable input.  Submitting
    the form posts to ``rename_post``.

    Args:
        request: Current HTTP request.
        name:    Current wiki page name.
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    _check_page_owner(request, name)
    try:
        p = page_path(name)
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    if not p.exists():
        return HTMLResponse("Page not found", 404)
    display = html.escape(name.replace("/", ":"))
    display_slash = html.escape(name)  # used in href only
    body = (f'<div class="layout"><div class="content">'
            f'<h1>&#9999; Rename page</h1>'
            f'<p>Current name: <strong>{display}</strong></p>'
            f'<form method="post" style="margin-top:.8rem">'
            f'<label style="display:block;margin-bottom:.5rem">New name:'
            f'<input type="text" name="new_name" value="{display}" required autofocus '
            f'pattern="[A-Za-z0-9_ \\-:]+" '
            f'style="margin-left:.5rem;padding:.3rem .5rem;font-size:1rem;width:320px;max-width:100%">'
            f'</label>'
            f'<p class="notice" style="margin:.6rem 0;font-size:.85rem;color:#555">'
            f'Use <code>:</code> for namespaces, e.g. <code>projects:MyPage</code>. '
            f'All links in all pages pointing to this page will be updated automatically.</p>'
            f'<button type="submit" style="background:#2980b9;color:#fff;border-color:#1a5276">'
            f'Rename</button>'
            f'&nbsp;<a href="/wiki/{display_slash}">Cancel</a>'
            f'</form></div></div>')
    return HTMLResponse(shell(f"Rename \u2014 {name}", body, request=request))


@app.post("/rename/{name:path}", response_class=HTMLResponse)
async def rename_post(request: Request, name: str, new_name: str = Form(""), _auth: None = Depends(require_auth)):
    """Rename a wiki page and update all internal links (POST).

    Steps performed:

    1. Validate both the old and new page names.
    2. Scan every ``.wiki`` file and rewrite any ``[[...]]`` links that
       resolve to the old page name, choosing the shortest unambiguous
       link form (relative if the pages share a namespace, absolute
       colon-form otherwise).  Code-fenced and inline-code content
       is protected from rewriting.
    3. Atomically rename the ``.wiki`` file.
    4. Remove the now-empty source namespace directory if appropriate.
    5. Move attic snapshot files to the new path (best-effort; a
       warning is shown on failure but the rename itself still succeeds).
    6. Update the trace history for all users via
       ``_rewrite_trace_all_users``.

    Args:
        request:  Current HTTP request.
        name:     Current wiki page name.
        new_name: Desired new wiki page name.
    """
    name = normalize_name(name)
    new_name = normalize_name(new_name.strip().replace(":", "/"))
    try:
        old_path = page_path(name)
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    _check_page_reader(request, name)
    _check_page_owner(request, name)
    if not old_path.exists():
        return HTMLResponse("Page not found", 404)
    if not new_name:
        return HTMLResponse("New name is required", 400)
    try:
        new_path = page_path(new_name)
    except ValueError:
        return HTMLResponse("Invalid new page name — use only letters, digits, hyphens, underscores and <code>:</code> for namespaces", 400)
    if name == new_name:
        return RedirectResponse(f"/wiki/{name}", status_code=303)
    if new_path.exists():
        return HTMLResponse(f"A page named \u2018{html.escape(new_name)}\u2019 already exists", 400)
    _check_page_owner(request, new_name)

    # Rewrite all [[...]] links across all pages that resolve to `name`
    # For root pages (new_ns==""), cross-namespace links must use [[:NewPage]].
    # For namespaced pages, [[ns:SubPage]] is unambiguous from any namespace.
    new_ns    = "/".join(new_name.split("/")[:-1])
    new_colon = (":" + new_name) if not new_ns else new_name.replace("/", ":")

    def _rewrite_content(content: str, page_ns: str) -> str:
        # Stash fenced code blocks and inline code so links inside them are not rewritten
        stash: list[str] = []
        def _hide(m: re.Match) -> str:
            stash.append(m.group(0))
            return f"\x00{len(stash)-1}\x00"
        safe = re.sub(r"```[\s\S]*?```", _hide, content)
        safe = re.sub(r"`[^`\n]+`", _hide, safe)

        def repl(m: re.Match) -> str:
            inner = m.group(1)
            parts = inner.split("|", 1)
            target = parts[0].strip()
            label  = parts[1] if len(parts) > 1 else None
            # Skip external and file links
            if not target or target.startswith(("http://", "https://", "file:")):
                return m.group(0)
            # Resolve target to canonical page name
            if target.startswith(":"):
                url = target[1:].replace(":", "/")
            elif ":" in target:
                url = target.replace(":", "/")
            else:
                url = (page_ns + "/" + target).lstrip("/") if page_ns else target
            try:
                url = normalize_name(url)
            except Exception:
                return m.group(0)
            if url != name:
                return m.group(0)
            # Choose minimal link form: relative if new page is in same namespace
            if page_ns == new_ns:
                new_target = new_name.split("/")[-1]
            else:
                new_target = new_colon
            lbl = f"|{label}" if label is not None else ""
            return f"[[{new_target}{lbl}]]"

        result = re.sub(r"\[\[(.+?)\]\]", repl, safe)
        # Restore stashed code blocks
        return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], result)

    for wiki_file in sorted(PAGES_DIR.rglob("*.wiki")):
        try:
            content = wiki_file.read_text(encoding="utf-8")
        except OSError:
            continue
        page_rel = str(wiki_file.relative_to(PAGES_DIR).with_suffix("")).replace("\\", "/")
        page_ns  = "/".join(page_rel.split("/")[:-1])
        new_content = _rewrite_content(content, page_ns)
        if new_content != content:
            tmp = None
            try:
                tmp = wiki_file.with_suffix(f".{secrets.token_hex(4)}.tmp")
                tmp.write_text(new_content, encoding="utf-8", newline="\n")
                tmp.replace(wiki_file)
            except OSError:
                pass  # best-effort; don't abort the rename for a failed rewrite
            finally:
                if tmp is not None:
                    tmp.unlink(missing_ok=True)

    # Move the page file
    new_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.rename(new_path)
    # Remove empty source namespace directory (best-effort)
    try:
        old_dir = old_path.parent
        if old_dir != PAGES_DIR and old_dir.is_dir() and not any(old_dir.iterdir()):
            old_dir.rmdir()
    except OSError:
        pass

    # Move attic snapshots (best-effort — failure doesn't block the rename)
    attic_warning = ""
    try:
        old_attic = _attic_page_dir(name)
        if old_attic.is_dir():
            new_attic = _attic_page_dir(new_name)
            new_attic.parent.mkdir(parents=True, exist_ok=True)
            old_attic.rename(new_attic)
    except Exception as exc:
        attic_warning = (f'<div class="notice" style="background:#fff3cd;border-color:#ffc107;margin-top:.8rem">'
                         f'&#9888; Page renamed successfully, but history snapshots could not be moved '
                         f'(<code>{html.escape(str(exc))}</code>). '
                         f'Old snapshots remain at <code>attic/{html.escape(name)}/</code>.</div>')

    if attic_warning:
        body = (f'<div class="layout"><div class="content">'
                f'<h1>Page renamed</h1>'
                f'<p><strong>{html.escape(name.replace("/", ":"))}</strong> \u2192 '
                f'<a href="/wiki/{html.escape(new_name)}">{html.escape(new_name.replace("/", ":"))}</a></p>'
                f'{attic_warning}'
                f'</div></div>')
        _rewrite_trace_all_users(name, new_name)
        return HTMLResponse(shell(f"Renamed \u2014 {new_name}", body, request=request))

    _rewrite_trace_all_users(name, new_name)
    return RedirectResponse(f"/wiki/{new_name}", status_code=303)


def _rewrite_trace_all_users(old_name: str, new_name: str) -> None:
    """Update trace history for all users after a page rename (best-effort)."""
    if not TRACE_ENABLED:
        return
    try:
        con = _get_db()
        try:
            rows = con.execute(
                "SELECT username, value FROM user_settings WHERE key='trace'"
            ).fetchall()
            updates = []
            for (uname, raw) in rows:
                try:
                    trace = json.loads(raw)
                    if not isinstance(trace, list):
                        continue
                    new_trace = [new_name if p == old_name else p for p in trace]
                    if new_trace != trace:
                        updates.append((json.dumps(new_trace), uname))
                except Exception:
                    continue
            if updates:
                con.executemany(
                    "UPDATE user_settings SET value=? WHERE username=? AND key='trace'",
                    updates,
                )
                con.commit()
        finally:
            con.close()
    except Exception:
        pass  # best-effort; don't block the rename response


@app.get("/delete/{name:path}", response_class=HTMLResponse)
def delete_get(request: Request, name: str, _auth: None = Depends(require_auth)):
    """Render the delete-confirmation page for a wiki page.

    Shows a warning notice and a confirmation form.  The actual
    deletion is performed by ``delete_post`` when the form is
    submitted with ``confirm=yes``.

    Args:
        request: Current HTTP request.
        name:    Wiki page name to delete.
    """
    name = normalize_name(name)
    try:
        page_path(name)  # validate name; raises ValueError on bad input
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    _check_page_reader(request, name)
    _check_page_owner(request, name)
    body = (f'<div class="layout"><div class="content">'
            f'<h1>Delete page</h1>'
            f'<div class="notice">Are you sure you want to delete <strong>{html.escape(name.replace("/", ":"))}</strong>?</div>'
            f'<form method="post" style="margin-top:.8rem">'
            f'<input type="hidden" name="confirm" value="yes">'
            f'<button type="submit" style="background:#c0392b;color:#fff;border-color:#a93226">Yes, delete</button>'
            f'&nbsp;<a href="/wiki/{html.escape(name)}">Cancel</a>'
            f'</form></div></div>')
    return HTMLResponse(shell(f"Delete — {name}", body, request=request))


@app.post("/delete/{name:path}", response_class=HTMLResponse)
async def delete_post(request: Request, name: str, confirm: str = Form(""), _auth: None = Depends(require_auth)):
    """Delete a wiki page after confirmation.

    Removes the ``.wiki`` file, cleans up its empty parent namespace
    directory tree, and deletes all attic snapshots for the page.
    Redirects to ``/wiki/Home`` on success.

    Args:
        request: Current HTTP request.
        name:    Wiki page name to delete.
        confirm: Must equal ``"yes"`` (posted from the confirmation
                 form) to proceed; otherwise redirects back to the page.
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    _check_page_owner(request, name)
    if confirm != "yes":
        return RedirectResponse(f"/wiki/{name}", status_code=303)
    try:
        p = page_path(name)
        if p.exists():
            p.unlink()
        # Remove empty parent namespace directory
        try:
            parent = p.parent
            if parent != PAGES_DIR and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass
        # Clean up attic snapshots so deleted pages don't leave orphaned history
        try:
            attic_dir = _attic_page_dir(name)
            if attic_dir.is_dir():
                shutil.rmtree(attic_dir)
        except Exception:
            pass  # don't block the delete on attic cleanup failure
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    return RedirectResponse("/wiki/Home", status_code=303)


# ── login / logout ─────────────────────────────────────────────────────────────

def _login_page(next_url: str, error: str = "") -> HTMLResponse:
    """Render the standalone HTML login form page.

    Produces a self-contained document (no site nav) containing the
    login form, an optional error message banner, and a hidden
    ``next`` field that records the URL to redirect to after successful
    authentication.

    Args:
        next_url: URL to redirect to after login (HTML-escaped in the
                  form’s hidden field).
        error:    Optional human-readable error message to display
                  (e.g. ``"Invalid credentials"``).  Empty string
                  suppresses the error banner.

    Returns:
        An ``HTMLResponse`` with the login page HTML.
    """
    err_html = f'<div class="login-error">{html.escape(error)}</div>' if error else ""
    next_safe = html.escape(next_url)
    body = (f'<div class="login-box">'
            f'<h1>&#128274; {html.escape(SITE_TITLE)} Login</h1>'
            f'{err_html}'
            f'<form method="post" action="/login">'
            f'<input type="hidden" name="next" value="{next_safe}">'
            f'<label>Username<input type="text" name="username" autocomplete="username" required></label>'
            f'<label>Password<input type="password" name="password" autocomplete="current-password" required></label>'
            f'<button type="submit">Log in</button>'
            f'</form></div>')
    return HTMLResponse(f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                        f'<title>Login \u2014 {html.escape(SITE_TITLE)}</title>'
                        f'<link rel="icon" href="{_ICON_DATA}">'
                        f'<link rel="stylesheet" href="{CSS_URL}"></head>'
                        f'<body>{body}</body></html>')

@app.get("/login", response_class=HTMLResponse)
def login_get(next: str = "/wiki/Home"):
    """Render the login form (GET).

    Args:
        next: URL to redirect to after successful login (default:
              ``/wiki/Home``).
    """
    return _login_page(next)

@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, username: str = Form(""), password: str = Form(""), next: str = Form("/wiki/Home")):
    """Authenticate a user and issue a session token (POST).

    Flow:

    1. Enforce the per-IP rate-limit (5 attempts per 60 s window).
    2. Validate *username* and *password* against the htpasswd file via
       bcrypt (run in a thread pool to avoid blocking the event loop).
    3. On success, call ``_issue_token`` and set the ``wiki_token``
       cookie (``HttpOnly``, ``SameSite=Lax``, ``Secure`` when HTTPS
       is in use).
    4. Auto-create the user’s homepage if ``USER_PAGE_AUTOCREATE`` is
       enabled and the page doesn’t yet exist.
    5. Redirect to *next* (sanitised to prevent open-redirect attacks).

    Args:
        request:  Current HTTP request (used for IP extraction).
        username: Posted username.
        password: Posted password (plaintext; compared against bcrypt hash).
        next:     URL to redirect to after login.
    """
    ip = _real_ip(request)
    if not _check_rate(ip):
        return HTMLResponse("Too many login attempts. Wait 60 seconds.", status_code=429)
    if not username or not password:
        _record_fail(ip)
        return _login_page(next, "Invalid credentials")
    # Run bcrypt in a thread so it doesn't block the event loop (~100 ms)
    if not await asyncio.to_thread(_check_password, username, password):
        _record_fail(ip)
        return _login_page(next, "Invalid credentials")
    token = _issue_token(username)
    if USER_PAGE_NS and USER_PAGE_AUTOCREATE:
        try:
            _user_page = f"{USER_PAGE_NS}/{username}/{USER_HOME_PAGE}"
            if read_page(_user_page) is None:
                write_page(_user_page,
                           f"====== {username} ======\n\nWelcome to my page.\n")
        except (ValueError, OSError):
            pass  # username not valid as a page-name segment, or disk error — don't block login
    safe_next = next if re.fullmatch(r'/[^/\\\r\n][^\r\n]*', next) else "/wiki/Home"
    resp = RedirectResponse(safe_next, status_code=303)
    secure_cookie = HTTPS_ENABLED or request.url.scheme == "https"
    _auth_log.info("login_post: user=%s scheme=%s secure=%s next=%s",
                   username, request.url.scheme, secure_cookie, safe_next)
    resp.set_cookie("wiki_token", token, max_age=TOKEN_EXPIRY_DAYS * 86400,
                    httponly=True, samesite="lax", secure=secure_cookie, path="/")
    return resp

@app.get("/logout")
async def logout_get(request: Request):
    """Redirect GET /logout to login page without revoking (guards against CSRF forced-logout)."""
    return RedirectResponse("/login", status_code=303)

@app.post("/logout")
async def logout(request: Request):
    """Revoke the current session token and redirect to the login page.

    Reads the token from the request (cookie / query param / header),
    revokes it from the persistent store, deletes the ``wiki_token``
    cookie, and issues a 303 redirect to ``/login``.
    """
    token = _get_token(request)
    if token:
        _revoke_token(token)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("wiki_token", path="/")
    return resp


# ── file upload helpers ────────────────────────────────────────────────────────

_FILE_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif",  "webp": "image/webp", "svg": "image/svg+xml",
    "pdf": "application/pdf", "txt": "text/plain", "md": "text/plain",
    "csv": "text/csv",   "zip": "application/zip",
}

def _upload_page(ns: str, results: list | None, request: Request | None = None, insert_pos: int = -1) -> HTMLResponse:
    """Render the file-upload page, optionally showing results from a prior upload.

    When *results* is ``None`` (GET requests) only the upload form is shown.
    When *results* is a list of result dicts (POST responses), a table of
    uploaded filenames, statuses, and copy-able wiki markup snippets is also
    rendered above the form.  Image results include a toggle to choose between
    ``{{embed}}`` and ``[[file:link]]`` markup.

    An “Insert into page” button uses ``window.opener`` to inject the markup
    directly into the editor ``<textarea>`` at *insert_pos* and then closes
    the upload window.  If the editor is not accessible it falls back to
    copying to the clipboard.

    Args:
        ns:         Namespace that uploaded files will belong to (e.g.
                    ``"projects/sub"``).  Empty string for the root namespace.
        results:    List of result dicts with keys ``name``, ``ok``,
                    ``markup``, ``markup_embed``, ``markup_link``,
                    ``is_img``, and optionally ``error``.  ``None`` renders
                    the empty form only.
        request:    Current HTTP request (for the page shell).
        insert_pos: Cursor position in the caller’s editor ``<textarea>``;
                    ``-1`` means “append”.

    Returns:
        Full ``HTMLResponse`` with the upload page HTML.
    """
    ns_display = ns.replace("/", ":") if ns else "(root)"
    pos_qs = f"?pos={insert_pos}" if insert_pos >= 0 else ""
    action = (f"/upload/{ns}" if ns else "/upload") + pos_qs
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
            f'<button id="insert-btn" onclick="insertAndClose()" '
            f'style="margin:.5rem 0;padding:.4rem .8rem;cursor:pointer">&#10549; Insert into page</button>'
            f'<script>'
            f'var _insertPos={insert_pos};'
            f'function insertAndClose(){{'
            f'  var markup=document.getElementById("snip").value;'
            f'  var ed=window.opener&&window.opener.document.getElementById("ed");'
            f'  if(ed){{'
            f'    var pos=(_insertPos>=0)?_insertPos:ed.selectionStart;'
            f'    var v=ed.value;'
            f'    var before=v.slice(0,pos);'
            f'    var after=v.slice(pos);'
            f'    if(before.length&&!before.endsWith("\\n")){{before+="\\n";}}'
            f'    if(after.length&&!after.startsWith("\\n")){{markup+="\\n";}}'
            f'    ed.value=before+markup+after;'
            f'    ed.selectionStart=ed.selectionEnd=before.length+markup.length;'
            f'    ed.focus();'
            f'    document.getElementById("insert-btn").textContent="✓ Inserted!";'
            f'    setTimeout(()=>window.close(),400);'
            f'  }}else{{'
            f'    /* opener gone or opened from outside edit page — copy instead */'
            f'    navigator.clipboard.writeText(markup).catch(()=>{{}});'
            f'    document.getElementById("insert-btn").textContent="✓ Copied to clipboard";'
            f'  }}'
            f'}}'
            f'function updateSnippet(){{'
            f'  var useLink=document.getElementById(\'lnk-toggle\')&&document.getElementById(\'lnk-toggle\').checked;'
            f'  var lines=[];'
            f'  document.querySelectorAll(".markup-cell").forEach(function(td){{'
            f'    var isImg=td.dataset.isimg==="1";'
            f'    var m=(isImg&&!useLink)?td.dataset.embed:td.dataset.link;'
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
    return HTMLResponse(shell(f"Upload \u2014 {html.escape(ns_display)}", body, request=request))

async def _do_upload(ns: str, files: list[UploadFile], request: Request | None = None, insert_pos: int = -1) -> HTMLResponse:
    """Validate and persist uploaded files, then return the upload result page.

    Performs the following checks before saving:

    * At most 20 files per request.
    * Namespace path segments must match ``[A-Za-z0-9_-]+``.
    * File extension must be in ``ALLOWED_EXTS``.
    * Individual file size must not exceed ``MAX_FILE_SIZE`` (20 MB).
    * Cumulative total for the request must not exceed ``MAX_TOTAL_SIZE``
      (100 MB).

    Accepted files are written to ``FILES_DIR/<ns>/<safe_stem>_<rand>.<ext>``
    where the stem is sanitised to alphanumerics/hyphens/underscores and
    truncated to 40 characters.  The random 8-hex-char suffix prevents
    collisions when the same filename is uploaded twice.

    Args:
        ns:         Target namespace (empty string for the root).
        files:      List of ``UploadFile`` objects from the multipart form.
        request:    Current HTTP request (used for access-checks and the
                    page shell).
        insert_pos: Cursor position hint passed through to ``_upload_page``.

    Returns:
        ``HTMLResponse`` from ``_upload_page`` with upload results.
    """
    if len(files) > 20:
        return HTMLResponse("Too many files in one request (max 20)", 400)
    if ns:
        ns = normalize_name(ns)
        for seg in ns.split("/"):
            if not re.fullmatch(r"[A-Za-z0-9_\-]+", seg):
                return HTMLResponse("Invalid namespace", 400)
    if request is not None:
        _check_file_ns_owner(request, ns)
    dest = (FILES_DIR.joinpath(*ns.split("/")) if ns else FILES_DIR)
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
        await asyncio.to_thread((dest / uname).write_bytes, data)
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
    return _upload_page(ns, results, request, insert_pos)


@app.get("/upload", response_class=HTMLResponse)
def upload_get_root(request: Request, pos: int = -1, _auth: None = Depends(require_auth)): return _upload_page("", None, request, pos)

@app.get("/upload/{ns:path}", response_class=HTMLResponse)
def upload_get(request: Request, ns: str, pos: int = -1, _auth: None = Depends(require_auth)):
    if ns:
        _check_file_ns_owner(request, normalize_name(ns))
    return _upload_page(ns, None, request, pos)

@app.post("/upload", response_class=HTMLResponse)
async def upload_post_root(request: Request, pos: int = -1, files: list[UploadFile] = File(default=[]), _auth: None = Depends(require_auth)):
    return await _do_upload("", files, request, pos)

@app.post("/upload/{ns:path}", response_class=HTMLResponse)
async def upload_post(request: Request, ns: str, pos: int = -1, files: list[UploadFile] = File(default=[]), _auth: None = Depends(require_auth)):
    return await _do_upload(ns, files, request, pos)


@app.get("/files/{filepath:path}")
def serve_file(request: Request, filepath: str, _auth: None = Depends(require_auth)):
    """Serve an attached file from ``FILES_DIR``.

    Validates the path against ``file_path`` (disallows traversal and
    non-whitelisted extensions).  Applies ``X-Content-Type-Options:
    nosniff`` on all files and ``Content-Security-Policy: sandbox`` on
    SVG files to mitigate XSS via uploaded SVGs.

    Args:
        request:  Current HTTP request.
        filepath: Relative path inside ``FILES_DIR`` extracted from the
                  URL (e.g. ``"projects/sub/image.png"``).
    """
    filepath = filepath.strip("/")
    if not filepath:
        return HTMLResponse("Not found", 404)
    if "/" in filepath:
        f_ns, filename = filepath.rsplit("/", 1)
    else:
        f_ns, filename = "", filepath
    if USER_PAGE_HIDDEN:
        _in_ns, _owner = _is_user_ns(f_ns)
        if _in_ns and (getattr(request.state, "username", "") or "") != _owner:
            return HTMLResponse("Not found", 404)
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
async def file_delete(request: Request, filepath: str, _auth: None = Depends(require_auth)):
    """Delete an attached file from ``FILES_DIR``.

    After deletion, redirects to the referring page (if the referer
    is the same host) or to the namespace listing / orphans page as a
    fallback.  Access is restricted by ``_check_file_ns_owner``.

    Args:
        request:  Current HTTP request.
        filepath: Relative path of the file to delete (e.g.
                  ``"projects/sub/image_abc123.png"``).
    """
    filepath = filepath.strip("/")
    if "/" in filepath:
        f_ns, filename = filepath.rsplit("/", 1)
    else:
        f_ns, filename = "", filepath
    _check_file_ns_owner(request, f_ns)
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
def orphans(request: Request, _auth: None = Depends(require_auth)):
    """List all files in ``FILES_DIR`` that are not referenced by any wiki page.

    Scans every ``.wiki`` file for ``{{embed}}`` and ``[[file:link]]``
    references, then computes the set difference against all files on
    disk.  Each orphaned file is shown in a table with its size,
    modification date, and a delete button.

    References inside fenced and inline code blocks are excluded so
    that example markup doesn’t accidentally mark a file as referenced.

    Args:
        request: Current HTTP request.
    """
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
        # Strip fenced code blocks so references inside examples don't count
        text = re.sub(r"```[\s\S]*?```", "", text)
        text = re.sub(r"`[^`\n]+`", "", text)
        for m in REF_RE.finditer(text):
            raw = (m.group(1) or m.group(2)).strip()
            # strip leading :
            if raw.startswith(":"):
                raw = raw[1:]
            # convert colon-style namespace to slash
            referenced.add(raw.replace(":", "/"))

    orphaned = sorted(all_files - referenced)
    requester = getattr(request.state, "username", "") or ""
    if USER_PAGE_HIDDEN:
        orphaned = [r for r in orphaned
                    if not (_is_user_ns(r)[0] and _is_user_ns(r)[1] != requester)]

    if not orphaned:
        body = ('<div class="layout"><div class="content">'
                '<h1>&#128204; Orphaned Files</h1>'
                '<p>No orphaned files — every file has at least one wiki link.</p>'
                '</div></div>')
        return HTMLResponse(shell("Orphaned Files", body, request=request))

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
                 f'<td style="padding:.4rem .6rem;color:#888">{html.escape(f_ns.replace("/", ":")) if f_ns else "(root)"}</td>'
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
    return HTMLResponse(shell("Orphaned Files", body, request=request))


# ── history / versioning routes ───────────────────────────────────────────────

_SNAP_RE = re.compile(r"^\d{8}_\d{6}(_\d{6})?$")

@app.get("/history/{name:path}", response_class=HTMLResponse)
def history(request: Request, name: str, snap: str = "", view: str = "", _auth: None = Depends(require_auth)):
    """Display version history for a wiki page, or render a specific snapshot.

    Without query parameters: shows a table listing all retained
    snapshots with view and restore buttons.

    With ``?snap=<stem>``: renders the chosen snapshot.  When
    ``?view=source`` is also present, the raw markup is shown instead
    of the rendered HTML.

    Snapshot stems are validated against the pattern
    ``^\\d{8}_\\d{6}(_\\d{6})?$`` before accessing the attic
    directory.

    Args:
        request: Current HTTP request.
        name:    Wiki page name whose history to display.
        snap:    Optional snapshot filename stem (without ``.wiki``).
        view:    ``"source"`` to show raw markup instead of rendered
                 HTML for a single snapshot.
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    if not VERSIONING_ENABLED:
        return HTMLResponse(shell("History", '<div class="layout"><div class="content">'
                                  '<div class="notice">Versioning is disabled '
                                  '(<code>VERSIONING_ENABLED = False</code> in config).</div>'
                                  '</div></div>', request=request))
    try:
        d = _attic_page_dir(name)
    except ValueError:
        return HTMLResponse("Invalid page name", 400)

    if snap:
        # View a specific snapshot
        if not _SNAP_RE.match(snap):
            return HTMLResponse("Invalid snapshot id", 400)
        snap_file = d / f"{snap}.wiki"
        if not snap_file.resolve().is_relative_to(ATTIC_DIR.resolve()):
            return HTMLResponse("Invalid snapshot id", 400)
        if not snap_file.exists():
            return HTMLResponse("Snapshot not found", 404)
        src = snap_file.read_text(encoding="utf-8")
        ts_display = _snap_ts_to_display(snap)
        name_esc = html.escape(name)
        snap_esc = html.escape(snap)
        show_source = (view == "source")
        if show_source:
            toggle_link = f'<a href="/history/{name_esc}?snap={snap_esc}">View Rendered</a>'
            content_html = f'<pre style="white-space:pre-wrap;word-wrap:break-word;padding:1rem;font-size:.9rem;line-height:1.5;overflow-x:auto">{html.escape(src)}</pre>'
            toc = ""
        else:
            toggle_link = f'<a href="/history/{name_esc}?snap={snap_esc}&amp;view=source">View Source</a>'
            rendered, headings = parse(src, name, section_edit=False)
            content_html = rendered
            toc = toc_html(headings, _toc_max(parse_meta(src)))
        body = (f'<div class="layout"><div class="content">{breadcrumb(name)}'
                f'<div class="toolbar" style="margin-bottom:.5rem">'
                f'<a href="/history/{name_esc}">&larr; History</a>'
                f'{toggle_link}'
                f'<span style="color:#888;font-size:.85rem">Snapshot: {html.escape(ts_display)}</span>'
                f'<form method="post" action="/restore/{name_esc}" style="display:inline">'
                f'<input type="hidden" name="snap" value="{snap_esc}">'
                f'<button type="submit">Restore this version</button>'
                f'</form></div>'
                f'<div class="notice">This is a historical snapshot \u2014 read-only.</div>'
                f'{content_html}</div>{toc}</div>')
        return HTMLResponse(shell(f"Snapshot {ts_display} \u2014 {name}", body, request=request))

    # List snapshots
    snaps = []
    if d.is_dir():
        for f in sorted(d.glob("*.wiki"), reverse=True):
            if not _SNAP_RE.match(f.stem):
                continue
            ts = f.stem
            ts_display = _snap_ts_to_display(ts)
            snaps.append((ts, ts_display))
    if not snaps:
        content = '<div class="notice">No history snapshots yet. Snapshots are created on each save once a previous version exists.</div>'
    else:
        rows = "".join(
            f'<tr>'
            f'<td style="padding:.4rem .6rem">{html.escape(ts_disp)}</td>'
            f'<td style="padding:.4rem .6rem"><a href="/history/{html.escape(name)}?snap={html.escape(ts)}">View</a></td>'
            f'<td style="padding:.4rem .6rem">'
            f'<form method="post" action="/restore/{html.escape(name)}" style="display:inline">'
            f'<input type="hidden" name="snap" value="{html.escape(ts)}">'
            f'<button type="submit" style="font-size:.85rem;padding:.2rem .5rem">Restore</button>'
            f'</form></td></tr>'
            for ts, ts_disp in snaps
        )
        content = (f'<table style="width:100%;border-collapse:collapse;border:1px solid #ddd">'
                   f'<tr style="background:#ecf0f1">'
                   f'<th style="padding:.4rem .6rem;text-align:left">Timestamp ({html.escape(DISPLAY_TIMEZONE)})</th>'
                   f'<th style="padding:.4rem .6rem;text-align:left">View</th>'
                   f'<th style="padding:.4rem .6rem;text-align:left">Restore</th>'
                   f'</tr>{rows}</table>')
    body = (f'<div class="layout"><div class="content">{breadcrumb(name)}'
            f'<div class="toolbar" style="margin-bottom:.5rem">'
            f'<a href="/wiki/{html.escape(name)}">&larr; Back to page</a></div>'
            f'<h1>&#128337; History: {html.escape(name.split("/")[-1])}</h1>'
            f'<p style="font-size:.85rem;color:#888;margin:.4rem 0">'
            f'{len(snaps)} snapshot{"s" if len(snaps) != 1 else ""} retained</p>'
            f'{content}</div></div>')
    return HTMLResponse(shell(f"History \u2014 {name}", body, request=request))


@app.post("/restore/{name:path}", response_class=HTMLResponse)
async def restore_snapshot(request: Request, name: str, snap: str = Form(""), _auth: None = Depends(require_auth)):
    """Restore a wiki page to a historical snapshot.

    Reads the snapshot file from the attic, writes its content as the
    new current page version (which itself creates a new attic snapshot
    of the pre-restore state), then redirects to the reader view.

    Args:
        request: Current HTTP request.
        name:    Wiki page name to restore.
        snap:    Snapshot filename stem (from the history page form).
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    _check_page_owner(request, name)
    if not VERSIONING_ENABLED:
        return HTMLResponse("Versioning is disabled", 400)
    if not _SNAP_RE.match(snap):
        return HTMLResponse("Invalid snapshot id", 400)
    try:
        d = _attic_page_dir(name)
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    snap_file = d / f"{snap}.wiki"
    if not snap_file.resolve().is_relative_to(ATTIC_DIR.resolve()):
        return HTMLResponse("Invalid snapshot id", 400)
    if not snap_file.exists():
        return HTMLResponse("Snapshot not found", 404)
    content = snap_file.read_text(encoding="utf-8")
    try:
        write_page(name, content)
    except (ValueError, OSError):
        return HTMLResponse("Restore failed", 500)
    return RedirectResponse(f"/wiki/{name}", status_code=303)


# ── today / pin / tags / reorder routes ───────────────────────────────────────

@app.get("/today")
def today(request: Request, _auth: None = Depends(require_auth)):
    """Redirect to the journal page for today’s date.

    Applies the user’s ``journal_format`` setting (falling back to
    the site-wide ``JOURNAL_PAGE_FORMAT``) by substituting date tokens
    via ``_apply_journal_format``.  The resulting page name is
    normalised and redirected to with a 303.

    Args:
        request: Current HTTP request (used to read the user’s format
                 preference and the display timezone).
    """
    try:
        tz = ZoneInfo(DISPLAY_TIMEZONE)
    except Exception:
        tz = timezone.utc
    now = datetime.now(tz)
    username = getattr(request.state, "username", "") or ""
    fmt = _get_user_setting(username, "journal_format") or JOURNAL_PAGE_FORMAT
    page_name = _apply_journal_format(fmt, now)
    # Convert colon namespace separators to slashes for the URL
    page_name = page_name.replace(":", "/")
    page_name = normalize_name(page_name)
    return RedirectResponse(f"/wiki/{page_name}", status_code=303)


@app.post("/pin/{name:path}")
def pin_toggle(name: str, request: Request, _auth: None = Depends(require_auth)):
    """Toggle a wiki page in or out of the current user’s pinned-pages list.

    Reads the current pin list, adds or removes *name*, persists it,
    and redirects back to the page.  The list is capped at 20 entries;
    adding a 21st drops the oldest non-matching pin.

    Persistence uses server-side user settings for authenticated users
    and a browser cookie for unauthenticated (non-auth mode) users.

    Args:
        name:    Wiki page name to pin or unpin.
        request: Current HTTP request.
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    try:
        page_path(name)
    except ValueError:
        return HTMLResponse("Invalid page name", 400)
    username = getattr(request.state, "username", "") or ""
    pins = _get_pins(request)
    if name in pins:
        pins = [p for p in pins if p != name]
    else:
        pins = [p for p in pins if p != name][:19]
        pins.append(name)
    resp = RedirectResponse(f"/wiki/{name}", status_code=303)
    _save_pins(username, resp, pins)
    return resp


@app.get("/tags", response_class=HTMLResponse)
def tags_index(request: Request, _auth: None = Depends(require_auth)):
    """Display an index of all tags used across wiki pages.

    Scans every ``.wiki`` file for a ``~~META:`` block containing a
    ``tags:`` line, collects the tag–page mappings, and renders them
    as a list of tagged pages grouped by tag.  Pages in other users’
    private namespaces are excluded when ``USER_PAGE_HIDDEN`` is
    enabled.

    Args:
        request: Current HTTP request.
    """
    requester = getattr(request.state, "username", "") or ""
    tag_map: dict[str, list[str]] = {}
    for f in sorted(PAGES_DIR.rglob("*.wiki")):
        try:
            src = f.read_text(encoding="utf-8")
        except Exception:
            continue
        meta = parse_meta(src)
        pname = str(f.relative_to(PAGES_DIR).with_suffix("")).replace("\\", "/")
        if USER_PAGE_HIDDEN:
            _in_ns, _owner = _is_user_ns(pname)
            if _in_ns and _owner != requester:
                continue
        for t in (x.strip() for x in meta.get("tags", "").split(",") if x.strip()):
            tag_map.setdefault(t, []).append(pname)
    if not tag_map:
        body = ('<div class="layout"><div class="content"><h1>&#127991; Tags</h1>'
                '<div class="notice">No tags found. Add <code>tags: topic, another</code> '
                'to a page\'s <code>~~META:</code> block.</div></div></div>')
    else:
        items = "".join(
            f'<li style="margin:.4rem 0"><a href="/tags/{quote(t, safe="")}" class="tag-pill">{html.escape(t)}</a>'
            f' <small style="color:#888">{len(pages)} page{"s" if len(pages) != 1 else ""}</small>'
            f' &mdash; ' + ", ".join(
                f'<a href="/wiki/{html.escape(p)}">{html.escape(p.replace("/", ":"))}</a>'
                for p in pages[:8]
            ) + ('&hellip;' if len(pages) > 8 else '') + '</li>'
            for t, pages in sorted(tag_map.items())
        )
        body = (f'<div class="layout"><div class="content">'
                f'<h1>&#127991; Tags ({len(tag_map)})</h1>'
                f'<ul style="list-style:none;padding:0">{items}</ul></div></div>')
    return HTMLResponse(shell("Tags", body, request=request))


@app.get("/tags/{tag}", response_class=HTMLResponse)
def tag_pages(request: Request, tag: str, _auth: None = Depends(require_auth)):
    """Display all wiki pages tagged with a specific tag.

    Scans every ``.wiki`` file and filters those whose ``~~META:``
    ``tags:`` list contains an exact-match for *tag*.  Results are
    sorted alphabetically and filtered by the ``USER_PAGE_HIDDEN``
    rule.

    Args:
        request: Current HTTP request.
        tag:     Tag string to filter by (max 80 characters).
    """
    tag = tag.strip()
    if not tag or len(tag) > 80:
        return HTMLResponse("Invalid tag", 400)
    requester = getattr(request.state, "username", "") or ""
    results = []
    for f in sorted(PAGES_DIR.rglob("*.wiki")):
        try:
            src = f.read_text(encoding="utf-8")
        except Exception:
            continue
        page_tags = [x.strip() for x in parse_meta(src).get("tags", "").split(",") if x.strip()]
        if tag not in page_tags:
            continue
        pname = str(f.relative_to(PAGES_DIR).with_suffix("")).replace("\\", "/")
        if USER_PAGE_HIDDEN:
            _in_ns, _owner = _is_user_ns(pname)
            if _in_ns and _owner != requester:
                continue
        try:
            mtime = time.strftime("%Y-%m-%d", time.localtime(f.stat().st_mtime))
        except OSError:
            mtime = ""
        results.append(
            f'<li><a href="/wiki/{html.escape(pname)}">{html.escape(pname.replace("/", ":"))}</a>'
            f'<small style="color:#888;margin-left:.4rem">{mtime}</small></li>'
        )
    body = (
        f'<div class="layout"><div class="content">'
        f'<h1>&#127991; Tag: {html.escape(tag)}</h1>'
        f'<p><a href="/tags">&larr; All tags</a></p>'
        + (f'<ul>{"" .join(results)}</ul>' if results
           else '<div class="notice">No pages with this tag.</div>') +
        f'</div></div>'
    )
    return HTMLResponse(shell(f"Tag: {tag}", body, request=request))


@app.post("/reorder-todos/{name:path}")
async def reorder_todos(name: str, request: Request, _auth: None = Depends(require_auth)):
    """Reorder todo (and list) items within a wiki page.

    Accepts a JSON body ``{"order": [<line_no>, …]}``, a permutation
    of the original line numbers of the items to reorder.  The items
    are re-emitted into those same positions in the new display order
    while all other lines remain unchanged.

    Validation ensures:

    * ``order`` is a list of unique non-negative integers.
    * Every listed line is a valid todo-checkbox or list-item line.
    * The list has at most 500 entries.

    Uses ``snapshot=False`` so reordering doesn’t generate a history
    entry.

    Args:
        name:    Wiki page name.
        request: HTTP request with JSON body ``{"order": [int, …]}``.
    """
    name = normalize_name(name)
    _check_page_reader(request, name)
    _check_page_owner(request, name)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)
    order = body.get("order", [])
    if not isinstance(order, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in order):
        return JSONResponse({"ok": False, "error": "Bad request"}, status_code=400)
    if len(order) > 500 or len(set(order)) != len(order):
        return JSONResponse({"ok": False, "error": "Bad request"}, status_code=400)
    try:
        src = read_page(name)
    except ValueError:
        return JSONResponse({"ok": False, "error": "Invalid page name"}, status_code=400)
    if src is None:
        return JSONResponse({"ok": True}, status_code=200)
    lines = src.splitlines(keepends=True)
    todo_re = re.compile(r"^\s*\[[ x~]\] ")
    for ln in order:
        if ln < 0 or ln >= len(lines) or not todo_re.match(lines[ln]):
            return JSONResponse({"ok": False, "error": "Invalid line"}, status_code=400)
    # Rebuild the file: walk through every line; when we hit one of the positions
    # from `order`, emit the todos in the new display sequence instead.
    # This correctly handles non-contiguous todo blocks.
    sorted_positions = sorted(order)
    new_contents = [lines[ln] for ln in order]  # todos in new display order
    new_lines = list(lines)
    for i, pos in enumerate(sorted_positions):
        new_lines[pos] = new_contents[i]
    try:
        write_page(name, "".join(new_lines), snapshot=False)
    except OSError:
        return JSONResponse({"ok": False, "error": "Save failed"}, status_code=500)
    return JSONResponse({"ok": True})


# ── startup ────────────────────────────────────────────────────────────────────

WELCOME = """\
====== Welcome to TickTap Wiki ======

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
if VERSIONING_ENABLED:
    ATTIC_DIR.mkdir(parents=True, exist_ok=True)
home = PAGES_DIR / "Home.wiki"
if not home.exists():
    home.write_text(WELCOME, encoding="utf-8", newline="\n")

if __name__ == "__main__":
    import sys, getpass, argparse
    ap = argparse.ArgumentParser(
        description="ticktap_wiki.py — personal wiki server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
MODES
  Start the server (default):
    python ticktap_wiki.py

  Add or update a user in the htpasswd file, then exit:
    python ticktap_wiki.py --adduser alice
    python ticktap_wiki.py --adduser alice --htpasswd /path/to/.htpasswd

  Generate a self-signed TLS certificate + key, then exit:
    python ticktap_wiki.py --gencert
    python ticktap_wiki.py --gencert --cert server.pem --key server.key --days 3650 --host mywiki.local

CONFIGURATION
  Edit the '# ── config ──' block near the top of ticktap_wiki.py to change:
    AUTH_ENABLED      enable login (requires .htpasswd)
    HTPASSWD_FILE     path to htpasswd file (default: .htpasswd)
    TOKEN_EXPIRY_DAYS login token lifetime in days (default: 30)
    HTTPS_ENABLED     enable TLS
    TLS_CERT_FILE     path to TLS certificate (default: cert.pem)
    TLS_KEY_FILE      path to TLS private key  (default: key.pem)
    HOST / PORT       listening address (default: 127.0.0.1:8080)
"""
    )
    ap.add_argument("--adduser", metavar="USERNAME",
                    help="Add or update a user in the htpasswd file and exit")
    ap.add_argument("--htpasswd", metavar="FILE", default=str(HTPASSWD_FILE),
                    help=f"htpasswd file to use (default: {HTPASSWD_FILE})")
    ap.add_argument("--gencert", action="store_true",
                    help="Generate a self-signed TLS cert+key and exit")
    ap.add_argument("--cert", metavar="FILE", default=TLS_CERT_FILE,
                    help=f"cert output path for --gencert (default: {TLS_CERT_FILE})")
    ap.add_argument("--key", metavar="FILE", default=TLS_KEY_FILE,
                    help=f"key output path for --gencert (default: {TLS_KEY_FILE})")
    ap.add_argument("--days", metavar="N", type=int, default=3650,
                    help="cert validity in days for --gencert (default: 3650)")
    ap.add_argument("--cn", metavar="HOSTNAME", default="localhost",
                    help="Common Name / SAN hostname for --gencert (default: localhost)")
    args = ap.parse_args()

    if args.gencert:
        try:
            import ipaddress
            from datetime import timezone as _tz
            from cryptography import x509  # type: ignore
            from cryptography.x509.oid import NameOID  # type: ignore
            from cryptography.hazmat.primitives import hashes, serialization  # type: ignore
            from cryptography.hazmat.primitives.asymmetric import rsa  # type: ignore
        except ImportError:
            raise SystemExit("cryptography package required: pip install cryptography")
        print(f"Generating 2048-bit RSA key and self-signed cert ({args.days} days, CN={args.cn!r})...")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, args.cn)])
        # If --cn looks like an IP address, add it as IPAddress SAN; otherwise DNSName
        try:
            cn_ip = ipaddress.ip_address(args.cn)
            cn_san = x509.IPAddress(cn_ip)
        except ValueError:
            cn_san = x509.DNSName(args.cn)
        # Always include localhost + 127.0.0.1 as extras; deduplicate if cn is one of them
        san_entries: list = [cn_san]
        if args.cn != "localhost":
            san_entries.append(x509.DNSName("localhost"))
        if args.cn != "127.0.0.1":
            san_entries.append(x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")))
        san = x509.SubjectAlternativeName(san_entries)
        now = datetime.now(_tz.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=args.days))
            .add_extension(san, critical=False)
            .sign(key, hashes.SHA256())
        )
        Path(args.key).write_bytes(
            key.private_bytes(serialization.Encoding.PEM,
                              serialization.PrivateFormat.TraditionalOpenSSL,
                              serialization.NoEncryption()))
        Path(args.cert).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        print(f"  Key : {args.key}")
        print(f"  Cert: {args.cert}")
        print("Done. Set HTTPS_ENABLED=True and update TLS_CERT_FILE/TLS_KEY_FILE in ticktap_wiki.py.")
        sys.exit(0)

    if args.adduser:
        try:
            import bcrypt as _chk  # noqa: F401
        except ImportError:
            raise SystemExit("bcrypt is required: pip install bcrypt")
        htfile = Path(args.htpasswd)
        pw1 = getpass.getpass(f"Password for {args.adduser!r}: ")
        pw2 = getpass.getpass("Confirm password: ")
        if not pw1:
            raise SystemExit("Password must not be empty.")
        if pw1 != pw2:
            raise SystemExit("Passwords do not match.")
        existed = htfile.exists()
        _htpasswd_set(args.adduser, pw1, htfile)
        action = "Updated" if existed else "Created"
        print(f"{action} entry for {args.adduser!r} in {htfile}")
        sys.exit(0)

    # Server mode — run startup validation then start uvicorn
    if AUTH_ENABLED:
        try:
            import bcrypt as _chk2  # noqa: F401
        except ImportError:
            raise SystemExit("AUTH_ENABLED=True requires bcrypt: pip install bcrypt")
        if not HTPASSWD_FILE.exists():
            raise SystemExit(f"AUTH_ENABLED=True but {HTPASSWD_FILE} not found.\n"
                             f"Create it with: python ticktap_wiki.py --adduser USERNAME")
    if HTTPS_ENABLED:
        if not Path(TLS_CERT_FILE).exists():
            raise SystemExit(f"HTTPS_ENABLED=True but cert file not found: {TLS_CERT_FILE}\n"
                             f"Generate one with: python ticktap_wiki.py --gencert")
        if not Path(TLS_KEY_FILE).exists():
            raise SystemExit(f"HTTPS_ENABLED=True but key file not found: {TLS_KEY_FILE}\n"
                             f"Generate one with: python ticktap_wiki.py --gencert")

    kwargs: dict = {"host": HOST, "port": PORT, "reload": False,
                    "timeout_keep_alive": 5, "timeout_graceful_shutdown": 3}
    if HTTPS_ENABLED:
        kwargs["ssl_certfile"] = TLS_CERT_FILE
        kwargs["ssl_keyfile"]  = TLS_KEY_FILE
    import asyncio

    # Dual-stack: browsers resolve "localhost" to ::1 (IPv6) first on modern
    # Windows/Mac.  If the server only binds to 0.0.0.0 (IPv4), the ::1 probe
    # times out (~1 s) before falling back to 127.0.0.1 — causing a delay on
    # every first load and after the browser's DNS cache expires (~60-120 s).
    # Fix: run a companion IPv6 server on :: / ::1 alongside the IPv4 one.
    #
    # On Windows, ProactorEventLoop logs ConnectionResetError (WinError 10054)
    # to the console whenever a browser drops an idle keep-alive connection.
    # Switching to SelectorEventLoop suppresses that noise.  We must set the
    # policy before asyncio.run() because uvicorn.run() calls
    # setup_event_loop() internally which would re-override it.
    _IPV4_TO_IPV6 = {"0.0.0.0": "::", "127.0.0.1": "::1"}

    async def _serve(kw: dict):
        import logging
        servers = [uvicorn.Server(uvicorn.Config(app, **kw)).serve()]
        ipv6_host = _IPV4_TO_IPV6.get(kw.get("host", ""))
        if ipv6_host:
            kw6 = {**kw, "host": ipv6_host}
            try:
                # Quick probe: does the OS accept IPv6 sockets at all?
                import socket as _sock
                s = _sock.socket(_sock.AF_INET6, _sock.SOCK_STREAM)
                s.close()
                servers.append(uvicorn.Server(uvicorn.Config(app, **kw6)).serve())
            except OSError:
                logging.getLogger("ticktap_wiki").warning(
                    "IPv6 unavailable on this system — only binding IPv4 (%s). "
                    "Use http://127.0.0.1:%d/ to avoid browser DNS fallback delay.",
                    kw.get("host"), kw.get("port"),
                )
        results = await asyncio.gather(*servers, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logging.getLogger("ticktap_wiki").error("Server error: %s", r)

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_serve(kwargs))
