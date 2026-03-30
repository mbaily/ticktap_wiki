"""
test_server_performance.py
==========================
Integration tests that verify the wiki server responds quickly after
keep-alive connections are forcibly reset by the client, and that it
answers on both IPv4 (127.0.0.1) and IPv6 (::1) immediately — avoiding
the ~1 s delay caused by browsers probing ::1 first when the server only
listens on 0.0.0.0.

Background
----------
Two distinct bugs (now both fixed) caused a ~1 second stall:

1. IPv6 fallback delay (affects FIRST load and reloads after DNS cache
   expires, ~60-120 s):
   Browsers resolve "localhost" to ::1 first on modern Windows.  If the
   server only binds to 0.0.0.0 (IPv4), the ::1 probe times out before
   falling back to 127.0.0.1.
   Fix: also bind a companion server on :: / ::1.

2. ProactorEventLoop stall (affects requests after any idle RST):
   Windows's default ProactorEventLoop raises ConnectionResetError
   (WinError 10054) on idle keep-alive teardown, stalling the next request.
   Fix: set WindowsSelectorEventLoopPolicy before asyncio.run(), bypassing
   uvicorn.run() which calls config.setup_event_loop() and can re-override it.

Running
-------
    pip install httpx bcrypt
    pytest test_server_performance.py -v
    pytest test_server_performance.py -v -m "not slow"   # skip the 7-second test
"""

import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx", reason="pip install httpx")

WIKI_PY = Path(__file__).parent / "ticktap_wiki.py"
TEST_PORT = 18081
FAST_MS = 400  # a request slower than this (ms) is considered a failure


# ── fixtures ────────────────────────────────────────────────────────────────────

def _make_htpasswd(path: Path, username: str, password: str) -> None:
    bcrypt = pytest.importorskip("bcrypt", reason="pip install bcrypt")
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()
    path.write_text(f"{username}:{hashed}\n", encoding="utf-8")


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


@pytest.fixture(scope="module")
def wiki_server():
    """
    Spin up a real wiki server in a throw-away temp directory.
    Yields a dict: {"base_url": str, "cookie": dict}.

    The server binds on both 127.0.0.1 and ::1 (dual-stack) so all
    IPv4 and IPv6 response-time tests can run against the same process.
    """
    pytest.importorskip("bcrypt", reason="pip install bcrypt")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        htpasswd_file = tmp / ".htpasswd"
        tokens_file   = tmp / ".wiki_tokens"
        pages_dir     = tmp / "pages"
        files_dir     = tmp / "files"
        attic_dir     = tmp / "attic"

        _make_htpasswd(htpasswd_file, "tester", "s3cr3t")

        # Build the launcher script as a plain string then write it;
        # f-string interpolation fills in the temp paths.
        script_lines = [
            "import sys, pathlib, asyncio, uvicorn",
            f"sys.path.insert(0, {str(WIKI_PY.parent)!r})",
            "import wiki as _w",
            "_w.HTTPS_ENABLED = False",
            f"_w.HTPASSWD_FILE = pathlib.Path({str(htpasswd_file)!r})",
            f"_w.TOKEN_FILE    = pathlib.Path({str(tokens_file)!r})",
            f"_w.PAGES_DIR     = pathlib.Path({str(pages_dir)!r})",
            f"_w.FILES_DIR     = pathlib.Path({str(files_dir)!r})",
            f"_w.ATTIC_DIR     = pathlib.Path({str(attic_dir)!r})",
            "_w.PAGES_DIR.mkdir(parents=True, exist_ok=True)",
            "_w.FILES_DIR.mkdir(parents=True, exist_ok=True)",
            "_w.ATTIC_DIR.mkdir(parents=True, exist_ok=True)",
            "home = _w.PAGES_DIR / 'Home.wiki'",
            "if not home.exists():",
            "    home.write_text(_w.WELCOME, encoding='utf-8', newline='\\n')",
            # Dual-stack: IPv4 on 127.0.0.1 + IPv6 on ::1, same port
            "async def _serve():",
            "    kw = dict(",
            f"        host='127.0.0.1', port={TEST_PORT},",
            "        reload=False, timeout_keep_alive=5, timeout_graceful_shutdown=3)",
            "    servers = [uvicorn.Server(uvicorn.Config(_w.app, **kw)).serve()]",
            "    kw6 = {**kw, 'host': '::1'}",
            "    servers.append(uvicorn.Server(uvicorn.Config(_w.app, **kw6)).serve())",
            "    await asyncio.gather(*servers, return_exceptions=True)",
            "if sys.platform == 'win32':",
            "    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())",
            "asyncio.run(_serve())",
        ]
        launcher = tmp / "_launcher.py"
        launcher.write_text("\n".join(script_lines) + "\n", encoding="utf-8")

        proc = subprocess.Popen(
            [sys.executable, str(launcher)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if not _wait_for_port("127.0.0.1", TEST_PORT):
            proc.terminate()
            out, err = proc.communicate(timeout=5)
            pytest.fail(
                f"Wiki server did not start on port {TEST_PORT} within 10 s.\n"
                f"stdout: {out.decode(errors='replace')}\n"
                f"stderr: {err.decode(errors='replace')}"
            )

        # Authenticate and capture the session cookie.
        base_url = f"http://127.0.0.1:{TEST_PORT}"
        with httpx.Client(base_url=base_url) as client:
            r = client.post(
                "/login",
                data={"username": "tester", "password": "s3cr3t", "next": "/wiki/Home"},
                follow_redirects=True,
            )
            assert r.status_code == 200, f"Login failed (HTTP {r.status_code})"
            token = client.cookies.get("wiki_token")
            assert token, "No wiki_token cookie after login"

        yield {"base_url": base_url, "cookie": {"wiki_token": token}}

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# ── helpers ─────────────────────────────────────────────────────────────────────

def _timed_get(base_url: str, cookies: dict, path: str = "/wiki/Home") -> float:
    """Return wall-clock seconds for a single authenticated GET."""
    with httpx.Client(base_url=base_url, cookies=cookies) as client:
        t0 = time.perf_counter()
        r = client.get(path)
        elapsed = time.perf_counter() - t0
    assert r.status_code == 200, f"GET {path} → HTTP {r.status_code}"
    return elapsed


def _rst_socket(host: str, port: int, cookies: dict) -> None:
    """
    Open a raw HTTP/1.1 keep-alive connection, make a complete request,
    read the full response, then force-close with SO_LINGER=0 so the OS
    sends a TCP RST instead of a FIN.

    This reproduces exactly what a browser does when it drops an idle
    keep-alive connection: the server receives WinError 10054 /
    ECONNRESET.  On ProactorEventLoop the event loop stalls handling
    that error; on SelectorEventLoop it is discarded immediately.
    """
    cookie_hdr = "; ".join(f"{k}={v}" for k, v in cookies.items())
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect((host, port))
    s.sendall(
        (
            f"GET /wiki/Home HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Cookie: {cookie_hdr}\r\n"
            f"Connection: keep-alive\r\n"
            f"\r\n"
        ).encode()
    )

    # Read headers
    raw = b""
    while b"\r\n\r\n" not in raw:
        chunk = s.recv(4096)
        if not chunk:
            break
        raw += chunk

    # Read body using Content-Length
    headers_raw, _, body = raw.partition(b"\r\n\r\n")
    cl = 0
    for line in headers_raw.decode(errors="replace").splitlines():
        if line.lower().startswith("content-length:"):
            try:
                cl = int(line.split(":", 1)[1])
            except ValueError:
                pass
    while len(body) < cl:
        chunk = s.recv(4096)
        if not chunk:
            break
        body += chunk

    # Force RST — server gets WinError 10054 / ECONNRESET
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    s.close()


# ── tests ────────────────────────────────────────────────────────────────────────

FAST = FAST_MS / 1000


class TestResponseTime:
    """
    Response-time tests focused on the keep-alive / RST stall bug on Windows.

    test_baseline               — normal request, no prior RST
    test_fast_after_rst         — one RST then immediate request
    test_fast_after_many_rsts   — five RSTs in a row then request
    test_fast_after_keepalive_timeout — wait > keep-alive timeout (marked slow)
    """

    def test_baseline(self, wiki_server):
        """A completely fresh request should complete well under the threshold."""
        t = _timed_get(wiki_server["base_url"], wiki_server["cookie"])
        assert t < FAST, (
            f"Baseline request took {t * 1000:.0f} ms "
            f"(threshold {FAST_MS} ms) — server may be slow to start."
        )

    def test_fast_after_rst(self, wiki_server):
        """
        After a keep-alive connection is forcibly RST'd, the very next fresh
        request must still complete quickly.

        Failure means the asyncio event loop stalled handling WinError 10054.
        Fix: use WindowsSelectorEventLoopPolicy + asyncio.run() directly.
        """
        _rst_socket("127.0.0.1", TEST_PORT, wiki_server["cookie"])
        time.sleep(0.1)   # let the RST packet reach the server
        t = _timed_get(wiki_server["base_url"], wiki_server["cookie"])
        assert t < FAST, (
            f"Post-RST request took {t * 1000:.0f} ms — "
            "event loop is likely stalling on WinError 10054 (ProactorEventLoop).\n"
            "Ensure WindowsSelectorEventLoopPolicy is set before asyncio.run()."
        )

    def test_fast_after_many_rsts(self, wiki_server):
        """Five successive RSTs must not accumulate stall time."""
        for _ in range(5):
            _rst_socket("127.0.0.1", TEST_PORT, wiki_server["cookie"])
            time.sleep(0.05)
        t = _timed_get(wiki_server["base_url"], wiki_server["cookie"])
        assert t < FAST, (
            f"Request after 5 RSTs took {t * 1000:.0f} ms "
            f"(threshold {FAST_MS} ms)."
        )

    @pytest.mark.slow
    def test_fast_after_keepalive_timeout(self, wiki_server):
        """
        Real-world idle scenario: load a page, wait longer than the server's
        keep-alive timeout (5 s), then reload.  The server closes the idle
        socket during the wait; the reconnect must not stall.

        Marked 'slow' (sleeps 7 s).  Skip with:  pytest -m "not slow"
        """
        base = wiki_server["base_url"]
        cookies = wiki_server["cookie"]

        with httpx.Client(base_url=base, cookies=cookies) as client:
            r1 = client.get("/wiki/Home")
            assert r1.status_code == 200
            time.sleep(7)
            t0 = time.perf_counter()
            r2 = client.get("/wiki/Home")
            t = time.perf_counter() - t0

        assert r2.status_code == 200
        assert t < FAST, (
            f"Request after keep-alive timeout took {t * 1000:.0f} ms "
            f"(threshold {FAST_MS} ms)."
        )


class TestIPv6:
    """
    Confirm the server listens on ::1 (IPv6 loopback) so that browsers
    resolving "localhost" to ::1 first don't stall for ~1 second waiting
    for a timeout before falling back to 127.0.0.1 (IPv4).

    This is the most likely cause of:
      - ~1 s delay on first ever load
      - ~1 s delay after ~60-120 s idle (browser DNS cache expires,
        re-probes ::1 first)
    """

    @staticmethod
    def _ipv6_reachable() -> bool:
        try:
            s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect(("::1", TEST_PORT))
            s.close()
            return True
        except OSError:
            return False

    def test_ipv6_listening(self, wiki_server):
        """Server must accept connections on ::1 (IPv6 loopback)."""
        if not self._ipv6_reachable():
            pytest.skip("::1 not reachable — IPv6 may be disabled on this machine")

        with httpx.Client(cookies=wiki_server["cookie"]) as client:
            t0 = time.perf_counter()
            r = client.get(f"http://[::1]:{TEST_PORT}/wiki/Home")
            t = time.perf_counter() - t0

        assert r.status_code == 200, (
            f"IPv6 request returned HTTP {r.status_code} — "
            "server may not be bound to ::1.\n"
            "Fix: run a companion uvicorn.Server with host='::1' alongside the IPv4 one."
        )
        assert t < FAST, (
            f"IPv6 ([::1]) request took {t * 1000:.0f} ms (threshold {FAST_MS} ms)."
        )

    def test_localhost_resolves_fast(self, wiki_server):
        """
        Simulate what a browser does: connect to 'localhost' and let the
        HTTP client resolve it (may try ::1 first on Windows, then 127.0.0.1).
        The request must complete quickly regardless of which address is tried
        first — proving both IPv4 and IPv6 are served.

        If this fails but test_baseline passes, the browser is probing ::1,
        timing out (~1 s), then falling back to 127.0.0.1.
        """
        with httpx.Client(cookies=wiki_server["cookie"]) as client:
            t0 = time.perf_counter()
            r = client.get(f"http://localhost:{TEST_PORT}/wiki/Home")
            t = time.perf_counter() - t0

        assert r.status_code == 200
        assert t < FAST, (
            f"'localhost' request took {t * 1000:.0f} ms (threshold {FAST_MS} ms).\n"
            "If only IPv4 is served, ::1 probes time out before falling back.\n"
            "Fix: bind a companion server on ::1 alongside 0.0.0.0."
        )
