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

## Notes

- The consumer Users need no roles: queries use `frappe.get_all`
  (permission-ignoring) with server-controlled filters, so a leaked secret
  exposes only this module's published-blog reads.
- Responses are cached in redis for 5 minutes and also cleared explicitly on
  Blog Post / BNS Website changes (doc_events in hooks.py).
- Deleting a BNS Website is blocked while Blog Posts link it — retire sites
  with Enabled = 0 instead.
