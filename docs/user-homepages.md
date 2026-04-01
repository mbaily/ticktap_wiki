# User Homepages

A design outline for per-user home pages, similar to DokuWiki's
[User Homepages plugin](https://www.dokuwiki.org/plugin:userhomepage).

---

## Concept

Each authenticated user gets a personal wiki page under a reserved namespace,
e.g. `user/alice`.  A short redirect (`/me`) takes the logged-in user straight
to their own page.  From markup, `[[user:alice]]` works like any other
namespace link.

---

## Identity source

The auth token already encodes the username.  `_validate_token()` returns it,
and `require_auth` stores it on `request.state.username` for every authenticated
request.  No separate identity layer is needed.

---

## Configuration (new constants)

```python
USER_PAGE_NS        = "user"   # namespace prefix; set "" to disable
USER_PAGE_AUTOCREATE = True    # write a stub page on first login if the page
                               # does not yet exist
USER_PAGE_PRIVATE   = False    # True → only the owner may edit their own page
                               # (all users can still read it)
```

---

## URL design

| URL | Behaviour |
|-----|-----------|
| `/me` | Redirect to `/wiki/user/<username>` for the logged-in user |
| `/wiki/user/alice` | View Alice's homepage (normal page view) |
| `/edit/user/alice` | Edit — guarded by `USER_PAGE_PRIVATE` if enabled |

---

## Auto-creation on first login

In `login_post`, after `_issue_token(username)` succeeds, check whether the
user's page exists and write a stub if not:

```python
if USER_PAGE_NS and USER_PAGE_AUTOCREATE:
    page_name = f"{USER_PAGE_NS}/{username}"
    if read_page(page_name) is None:
        stub = (
            f"====== {username} ======\n\n"
            f"Welcome to my page.\n"
        )
        write_page(page_name, stub)
```

The stub is just a normal wiki page.  The user can then edit it like any other.

---

## `/me` redirect route

```python
@app.get("/me")
def my_page(request: Request, _auth: None = Depends(require_auth)):
    username = request.state.username
    return RedirectResponse(f"/wiki/{USER_PAGE_NS}/{username}", status_code=303)
```

---

## Optional: owner-only editing (`USER_PAGE_PRIVATE = True`)

Add a helper that is called at the top of the edit routes:

```python
def _check_page_owner(request: Request, name: str):
    """Raise HTTPException 403 if the page is in the user namespace and the
    logged-in user is not the owner."""
    if not USER_PAGE_PRIVATE or not USER_PAGE_NS:
        return
    parts = name.split("/")
    if parts[0] != USER_PAGE_NS or len(parts) < 2:
        return
    owner = parts[1]
    if request.state.username != owner:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="You may only edit your own user page.")
```

Call it near the top of `edit_get` and `edit_post` (and section-edit routes if
desired), after `require_auth` has already run.

When `USER_PAGE_PRIVATE = False` (the default), any logged-in user can edit
any user page, which matches DokuWiki's default open-wiki behaviour.

---

## Nav bar link

Add a "My page" link to `nav_bar` when `USER_PAGE_NS` is set and a `username`
is known:

```python
my_page_link = (
    f'<a href="/me">&#128100; My page</a>'
    if (USER_PAGE_NS and username) else ""
)
```

Insert it between the existing nav links, e.g. after the `+ New Page` link.

---

## Sitemap / namespace view

The `user/` namespace appears in `/sitemap` and `/ns/user` automatically
because they walk `PAGES_DIR` recursively — no extra handling needed.

If you want to suppress it from the top-level sitemap (treating it as a
"system" namespace), filter it inside `sitemap()`:

```python
if PAGES_DIR.joinpath(USER_PAGE_NS).resolve() == d.resolve():
    continue  # skip user namespace in root listing
```

---

## Markup linking

Standard DokuWiki-style markup works without changes:

```
[[user:alice]]            → links to user/alice
[[user:alice|Alice's page]]
```

The existing `parse_inline` function already converts `[[ns:page]]` → `/wiki/ns/page`.

---

## File attachments per user

Each user's files would naturally live under `files/user/<username>/` using the
existing upload mechanism.  No changes needed — namespace-scoped upload already
works via `/upload/user/alice`.

---

## Summary of changes required

| Change | Where |
|--------|-------|
| Add `USER_PAGE_NS`, `USER_PAGE_AUTOCREATE`, `USER_PAGE_PRIVATE` constants | config section |
| Auto-create stub page on first login | `login_post` |
| Add `/me` redirect route | routes section |
| Add `_check_page_owner` guard (optional) | edit routes |
| Add "My page" link to nav bar | `nav_bar()` |

All changes are additive.  Setting `USER_PAGE_NS = ""` disables the feature
entirely with no behavioural difference from the current code.
