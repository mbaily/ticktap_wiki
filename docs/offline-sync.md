# Offline Sync — Design Proposal

> **Motivation:** You walk into a supermarket, your iPhone loses 4G/5G, and your
> shopping-list wiki page is unreachable.  You need to read *and* tick off items
> without a server connection, then have every tap you made sync up automatically
> when you walk back outside.

---

## 1. Overview

TickTap already runs as a server-rendered app — the browser is a thin client.
To support offline use we bolt on two standard browser primitives:

| Primitive | Role |
|-----------|------|
| **Service Worker** | Intercepts every fetch; serves cached pages when offline; queues writes |
| **IndexedDB** | Persists the page cache and the pending-operations queue across page reloads |

No app install, no Electron, no React — the same Safari/Chrome phone browser
that already runs TickTap gains offline capability via a single `.js` file and
a few new server endpoints.

---

## 2. Architecture

```
┌────────────────────────────────────────────────────┐
│  Phone browser (Safari / Chrome)                   │
│                                                    │
│  ┌──────────────┐      fetch()     ┌────────────┐  │
│  │  Page JS /   │ ──────────────►  │  Service   │  │
│  │  toggle/edit │                  │  Worker    │  │
│  └──────────────┘ ◄────────────── └─────┬──────┘  │
│                     cached response      │          │
│                                    ┌────▼──────┐   │
│                                    │ IndexedDB │   │
│                                    │ • pages   │   │
│                                    │ • op_queue│   │
│                                    └───────────┘   │
└────────────────────────────────────────────────────┘
         ▲  online only
         │  TOSP sync protocol
┌────────▼──────────────────────────────┐
│  TickTap server (ticktap_wiki.py)      │
│  • existing endpoints (unchanged)     │
│  • /sync/manifest                     │
│  • /sync/page/{name}                  │
│  • /sync/push                         │
└───────────────────────────────────────┘
```

The **TickTap Offline Sync Protocol (TOSP)** is a tiny JSON protocol layered on
top of the existing plain-HTTP API.  All new endpoints live under `/sync/`.

---

## 3. Data Models

### 3.1 Page cache entry (IndexedDB `pages` store)

```jsonc
{
  "name":      "Home",               // normalised page name (key)
  "raw":       "[ ] Milk\n[x] Eggs", // raw .wiki content
  "html":      "<p>…</p>",           // pre-rendered HTML for instant display
  "hash":      "sha256:a3f9…",       // hash of raw at the time of last pull
  "pulled_at": 1743600000,           // Unix timestamp of last successful pull
  "pinned":    true                  // true → always pre-fetched, never evicted
}
```

### 3.2 Pending operation (IndexedDB `op_queue` store)

```jsonc
{
  "id":         "op_01jq…",          // client-generated ULID (key, sortable)
  "page":       "Home",
  "base_hash":  "sha256:a3f9…",      // page hash at the moment the op was created
  "timestamp":  1743600042,          // Unix timestamp (ms)
  "type":       "toggle",            // see §3.3
  "data":       { "line": 3, "content": "[ ] Milk", "target": "[x] Milk" }
}
```

### 3.3 Operation types

| `type` | `data` fields | Server endpoint |
|--------|--------------|-----------------|
| `toggle` | `line`, `content`, `target` | `POST /toggle/{name}/{line}` |
| `add_todo` | `after_line`, `text` | `POST /add-todo/{name}` |
| `delete_line` | `line`, `content` | `POST /delete-line/{name}/{line}` |
| `edit_section` | `idx`, `body` | `POST /sect/{name}/{idx}` |
| `edit_page` | `body` | `POST /edit/{name}` |

`content` is the *expected* text of the target line.  The server uses it as a
fallback lookup when `line` no longer matches (see §6.2).

---

## 4. New Server Endpoints

### 4.1 `GET /sync/manifest`

Returns a lightweight JSON map of every page the authenticated user can read.

```jsonc
// Response 200
{
  "pages": {
    "Home":        { "hash": "sha256:a3f9…", "mtime": 1743598000 },
    "AnotherPage": { "hash": "sha256:7bc1…", "mtime": 1743510000 }
  }
}
```

This lets the client detect which cached pages are stale without downloading
all of them.

---

### 4.2 `GET /sync/page/{name}`

Returns the raw content + rendering metadata for a single page.

```jsonc
// Response 200
{
  "name":   "Home",
  "raw":    "[ ] Milk\n[x] Eggs\n[ ] Bread",
  "html":   "<ul class=\"todo\">…</ul>",
  "hash":   "sha256:a3f9…",
  "mtime":  1743598000
}
```

The `html` field removes the need for a client-side markup parser.  The
Service Worker stores both and serves the `html` directly into the page shell.

---

### 4.3 `POST /sync/push`

The main sync endpoint.  Called when the device comes back online.  Accepts a
batch of queued operations and returns per-operation results.

```jsonc
// Request body
{
  "ops": [
    {
      "id":        "op_01jq…",
      "page":      "Home",
      "base_hash": "sha256:a3f9…",
      "timestamp": 1743600042,
      "type":      "toggle",
      "data":      { "line": 3, "content": "[ ] Milk", "target": "[x] Milk" }
    }
  ]
}
```

```jsonc
// Response 200
{
  "results": [
    {
      "id":      "op_01jq…",
      "status":  "ok",           // ok | conflict | error
      "detail":  null,
      "new_hash": "sha256:9d2a…" // updated page hash after the op was applied
    }
  ],
  "updated_pages": {
    // Pages that changed on the server while the client was offline.
    // Only pages that either (a) have ops in this push, or (b) are in the
    // client's pinned list are returned here.
    "Home": {
      "raw":  "[ ] Milk\n[x] Eggs\n✓ whatever",
      "html": "…",
      "hash": "sha256:9d2a…",
      "mtime": 1743600101
    }
  }
}
```

The server processes ops **in `id` order** (ULID ordering = chronological order
of offline actions).  After applying each op, the updated hash is returned so
the client can update its cache.

---

## 5. Service Worker Behaviour

The Service Worker (`sw-offline.js`) is registered once, on first authenticated
page load.

### 5.1 Cache strategy per route

| Route pattern | Online | Offline |
|---------------|--------|---------|
| `/wiki/*` | Network-first; update cache on success | Serve from `pages` IndexedDB store |
| `/toggle/*` | Network-first | Queue op in `op_queue`; optimistically update cached HTML |
| `/add-todo/*` | Network-first | Queue op; optimistically update cached HTML |
| `/delete-line/*` | Network-first | Queue op; optimistically update cached HTML |
| `/sect/*` (POST) | Network-first | Queue `edit_section` op; update cache |
| `/edit/*` (POST) | Network-first | Queue `edit_page` op; update cache |
| `/static/*` | Cache-first (versioned hashes already in URL) | Serve from cache |
| Everything else | Network-only | Return a friendly offline error page |

### 5.2 Optimistic updates

When a `toggle` is queued offline, the Service Worker immediately rewrites the
cached HTML for that page (flipping `[ ]` to `[x]`, updating the checkbox
class, etc.) so the UI feels instant — exactly like the online path.  No second
render pass or page reload is needed.

### 5.3 Sync trigger

On every `online` event (network restored), the Service Worker:

1. Calls `GET /sync/manifest` to find stale cached pages.
2. Calls `POST /sync/push` with all pending ops in `op_queue`.
3. Processes results (see §6).
4. Pulls `updated_pages` from the push response and refreshes the cache.
5. If the visible page was updated, posts a `BroadcastChannel` message
   `{ type: "page_updated", name }` so the page JS can refresh without a
   full reload.

---

## 6. Conflict Resolution

### 6.1 Clean applies (the common case)

For `toggle`, `add_todo`, and `delete_line` ops, the server attempts a
**content-match apply**:

1. Check if `base_hash` matches the current server content hash.
   - If yes → apply at `line` directly.  Done.
2. If the hash differs (someone else edited the page while you were offline):
   - Scan the current raw content for a line whose text matches `op.data.content`.
   - If found → apply the mutation to that line.  Return `status: "ok"`.
   - If not found → return `status: "conflict"`.

This means ticking off `[ ] Milk` works correctly even if your partner added
`[ ] Butter` above it while you were underground — the line numbers shifted but
the content match finds the right line.

### 6.2 Full-page edit conflicts

For `edit_page` and `edit_section` ops, content-match is insufficient.  The
server performs a **3-way merge**:

- *Base*: the raw content at `base_hash` (retrieved from the attic/versioning system).
- *Theirs*: the current server content.
- *Yours*: `op.data.body`.

Python's `difflib.unified_diff` is used to produce a line-level merge.  If the
merge is clean, it is applied and `status: "ok"` is returned.  If there are
conflicting hunks, `status: "conflict"` is returned and both versions are
preserved in the response so the UI can present a conflict view.

### 6.3 Client-side conflict UI

When any op returns `status: "conflict"`:

- A persistent banner appears: **"Sync conflict on [PageName] — tap to resolve"**.
- Tapping opens a side-by-side diff view (your version vs server version).
- The user picks "keep mine", "keep theirs", or edits the merged result.
- The resolution is saved immediately.

For the shopping-list use case this view should almost never appear.

---

## 7. Pre-fetch Strategy

To ensure pages are available offline *before* you lose signal:

### 7.1 Automatic pre-fetch

On every page view, the Service Worker checks whether the current page's hash
has changed since the last pull and refreshes it in the background.

Pinned pages (those in the nav bar) are **always** refreshed in the background
on app start.

### 7.2 Manual "take offline" button

A small cloud-with-down-arrow icon (⬇︎) appears in the reader toolbar for each
page.  Tapping it:

1. Saves the page and all its linked pages (one level deep) to the `pages` store.
2. Marks them as `pinned: true`.
3. Shows a toast: **"Home saved for offline use"**.

This is the recommended action for important lists before a trip.

### 7.3 Today page

The journal/"Today" page is always kept in the offline cache.  The Service
Worker pre-fetches it on app start and after midnight (using a `setTimeout`
keyed to the next day boundary).

---

## 8. Implementation Plan

### Phase 1 — Read-only offline (low risk)

1. Add `GET /sync/page/{name}` and `GET /sync/manifest` to `ticktap_wiki.py`.
2. Write `sw-offline.js`:
   - Cache static assets on install.
   - Intercept `GET /wiki/*` and serve from IndexedDB when offline.
   - Refresh cache on network success.
3. Register the SW from the main page HTML.
4. Add the "take offline" toolbar button.

**Result:** pages load offline; writes fail gracefully with a toast message.

### Phase 2 — Optimistic writes offline

5. Intercept `POST /toggle/*`, `POST /add-todo/*`, `POST /delete-line/*` in
   the SW.
6. When offline: queue to `op_queue`, optimistically patch cached HTML.
7. When online: flush queue via `POST /sync/push` (content-match logic only —
   no 3-way merge yet).

**Result:** checkbox tapping works fully offline, including the shopping-list
scenario.

### Phase 3 — Full conflict resolution

8. Implement `edit_page` / `edit_section` queuing with 3-way merge on the server.
9. Implement the conflict UI in the browser.

---

## 9. File Changes Summary

| File | Change |
|------|--------|
| `ticktap_wiki.py` | Add `/sync/manifest`, `/sync/page/{name}`, `/sync/push` endpoints |
| `sw-offline.js` *(new)* | Service Worker — cache, queue, sync logic |
| `ticktap_wiki.py` (HTML) | Register SW; add ⬇︎ toolbar button; offline status indicator in nav bar |

No new Python dependencies are needed.  The Service Worker and IndexedDB APIs
are built into every modern mobile browser (Safari ≥ 15.4, Chrome ≥ 100).

---

## 10. Security Considerations

- The auth token (cookie or `Authorization` header) is forwarded by the Service
  Worker on every request; no separate offline auth scheme is needed.
- The `op_queue` is stored in **origin-scoped** IndexedDB — inaccessible to
  other origins.
- The `/sync/push` endpoint honours the same `require_auth` guard as all other
  write endpoints.
- Page HTML is stored in IndexedDB, **not** in the HTTP Cache or localStorage,
  so it is not accessible to the browser's cache inspector in shared-device
  scenarios (`USER_PAGE_PRIVATE` pages must not be cached if `USER_PAGE_PRIVATE`
  is `True`).
- The Service Worker script itself is served over HTTPS (enforced by
  `HTTPS_ENABLED = True`) so it cannot be tampered with in transit.

---

## Appendix A — TOSP at a Glance

```
Client                                    Server
  │                                          │
  │  (online — normal use)                   │
  │──── GET /wiki/Home ────────────────────►│
  │◄─── HTML + set cache ───────────────────│
  │                                          │
  │  (signal drops)                          │
  │──── POST /toggle/Home/3 ─── (SW) ──✗    │
  │     SW queues op, patches cache          │
  │◄─── synthetic 200 from SW ──────────────│(fake)
  │                                          │
  │  (signal restored)                       │
  │──── POST /sync/push ────────────────────►│
  │     { ops: [ toggle op ] }               │
  │◄─── { results: [ok], updated_pages } ───│
  │     SW updates cache, notifies page JS   │
  │──── BroadcastChannel: page_updated ─────►│(page JS refreshes DOM)
```

---

## Appendix B — Why Not a Native App / PWA Install?

A PWA install prompt could optionally be enabled later, but it is **not
required** for this design.  The Service Worker works in Safari's "Add to Home
Screen" mode *and* in a regular browser tab.  Keeping TickTap as a web page
avoids App Store review cycles and keeps the single-file philosophy intact.
