# BNS Web

Serves ERPNext Blog Posts to multiple external brand websites (e.g. playnova,
cockcolours, gginnovative.com) from one ERP, with per-website distribution
control. The websites fetch **server-side** (SSR/ISR/SSG) — visitors' browsers
never touch the ERP, so there is no CORS setup and ERP load stays at the
frontends' revalidation rate, not visitor traffic.

## Architecture

```
Layer 4  DELIVERY   brand sites fetch server-side, secret kept in env vars
Layer 3  SERVICE    blog_api.py — get_posts / get_post, envelope responses,
                    redis cache per (site, params), cleared on Blog Post update
Layer 2  ACCESS     native Frappe token auth; BNS Website.api_user mapping is
                    the ACL — no mapping, no data (fail closed)
Layer 1  DATA       BNS Website + BNS Website Link child table on Blog Post
                    (custom field `bns_websites`, "Serving Websites")
```

## Setup per website (data-only, no deploy)

1. Create a User (e.g. `api.playnova@yourdomain`), no roles needed.
   Generate **API Key + API Secret** on the User form (Settings → API Access).
2. Create a **BNS Website**: site key (`playnova`), base URL
   (`https://playnova.com`), link the User as **API User**, keep **Enabled**.
3. Give the key/secret to that site's team; they call with header
   `Authorization: token <api_key>:<api_secret>`.
4. Tag Blog Posts via the **Serving Websites** field. Untagged posts are
   served nowhere (fail closed).

Rotate = regenerate the User's API Secret. Revoke = untick Enabled (or
disable the User). Audit = standard Frappe request log.

## API

Base: `/api/method/business_needed_solutions.bns_web.blog_api.<fn>`

`get_posts(start=0, limit=20, category=None, view="card")`
→ `{items, total, start, limit, has_more}`. `view="card"` includes
intro/image/category/blogger; `view="headline"` is title/route/date only.
`limit` is capped at 50; list responses never include post content.

`get_post(route)`
→ full rendered content (root-relative image URLs rewritten to absolute ERP
URLs), meta title/description/image, category, blogger, and `canonical_url`
built from the website's base URL.

Both derive the website from the authenticated user — there is no site
parameter, and an unmapped/disabled caller gets a permission error, never
another site's posts.

`get_changes(since=None, limit=25)` — **the canonical delivery endpoint**
→ `{now, next_since, changed, removed, has_more}`. The sync endpoint: everything
this site must add or drop. Omit `since` for a full export; pass the previous
call's **`next_since`** thereafter.

- Keyed off `modified` (database-owned), never `published_on` (author-controlled
  and backdatable). `since` is validated — a junk cursor throws instead of
  silently matching nothing forever.
- `limit` caps at 25, not 50: these rows carry full rendered content.
- `removed` comes from the **BNS Blog Removal** log, written by
  `removal_tracker` when a post is unpublished, un-served, re-routed or
  deleted. Recording removals as they happen (rather than inferring them by
  re-querying posts without the site filter) keeps the response precise and
  stops one site being handed the routes of every draft and every other
  brand's posts.
- **Store `next_since`, not `now` and not the newest `modified` you received.**
  It advances only as far as *both* the change and removal streams are
  complete, and never splits a group of rows sharing one timestamp.
- Full export returns no `removed` — the client rebuilds from scratch and
  deletes whatever isn't in `changed`. This also avoids handing one site the
  routes of every draft and every other brand's posts.

`get_post` accepts `include_drafts=1` for a preview route (opt-in per call,
never affects `get_posts`, uncached). All payloads carry `modified`,
`content_hash` (sha256 of rendered content) and `media` (absolute URLs to
download) so a sync can skip media re-processing when only metadata changed.

`get_posts` / `get_post` remain for preview and ad-hoc reads; `get_changes` is
what a site should sync from.

Blog Category and Blogger edits are stamped onto the posts that embed them
(`propagation.py`), so they travel on the same `modified` cursor instead of
needing a second one.

### Consumer sync loop

Persist `{"since": "<last next_since>"}`. Each run: call `get_changes(since)`,
looping while `has_more`; write each `changed` post; delete each `removed`
route; save the final `next_since`. First run (no `since`) is a full export,
every run after is a usually-empty delta.

## Notes

- The consumer Users need no roles: queries use `frappe.get_all`
  (permission-ignoring) with server-controlled filters, so a leaked secret
  exposes only this module's published-blog reads.
- Responses are cached in redis for 5 minutes and also cleared explicitly on
  Blog Post / BNS Website changes (doc_events in hooks.py).
- Deleting a BNS Website is blocked while Blog Posts link it — retire sites
  with Enabled = 0 instead.

## Blogs are not served on the ERP domain

Posts must be `published=1` for the API to deliver them, which would normally
also make Frappe serve them at `<erp-host>/blog/...`. Two mechanisms prevent
that, so posts only appear on the brand websites:

- **`web_view_guard.BlogWebViewGuard`** (`page_renderer` hook) — 404s the blog
  index, post routes, category routes and `rss.xml` for **guests**. Logged-in
  staff can still preview posts on the ERP. `has_web_view` cannot be disabled
  with a Property Setter: `get_doctypes_with_web_view()` reads `tabDocType`
  directly, bypassing meta — hence a renderer.
- **`setup.ensure_blog_not_in_sitemap`** — Property Setter
  `allow_guest_to_view = 0` on Blog Post / Blog Category, so `sitemap.xml`
  stops advertising URLs the guard 404s (that path *does* read meta).

Escape hatch: set `bns_allow_erp_blog_web_view: 1` in `site_config.json` to
turn the guard off.
