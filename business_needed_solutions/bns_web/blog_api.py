# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""Read-only blog delivery API for external websites (BNS Web).

Consumed server-side (SSR/ISR/SSG) by the brand websites. Authentication is
standard Frappe token auth (``Authorization: token api_key:api_secret``) using
the User linked on BNS Website via ``api_user`` — there is no site parameter;
the website is resolved from the authenticated user and requests that don't
map to an enabled BNS Website fail closed.

The consumer Users need no roles: queries below use frappe.get_all (which
ignores permissions) with server-controlled filters and explicit field lists,
so a leaked secret exposes exactly this module's published-blog reads and
nothing else.
"""

import hashlib
import json
import re

import frappe
from frappe import _
from frappe.utils import cint, get_url
from frappe.website.utils import get_html_content_based_on_type

CACHE_PREFIX = "bns_blog_api"
CACHE_VERSION_KEY = f"{CACHE_PREFIX}:version"
# consumed by web_view_guard; owned here so invalidation lives in one place
WEB_ROUTES_CACHE_KEY = f"{CACHE_PREFIX}:web_routes"
CACHE_TTL = 300  # seconds; also invalidated on Blog Post / BNS Website updates
MAX_LIMIT = 50
# get_changes rows carry full rendered content, so this is far lower than
# MAX_LIMIT's content-free rows: 25 x ~200KB is already a 5MB response.
MAX_CHANGES_LIMIT = 25

LIST_FIELDS = {
	"card": [
		"name",
		"title",
		"route",
		"blog_intro",
		"meta_image",
		"published_on",
		"modified",
		"read_time",
		"blog_category",
		"blogger",
	],
	"headline": ["name", "title", "route", "published_on", "modified"],
}


# ---------------------------------------------------------------------------
# Website resolution (the authorization layer)
# ---------------------------------------------------------------------------


def _resolve_website():
	"""Map the authenticated user to its enabled BNS Website, or fail closed."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Authentication required"), frappe.AuthenticationError)

	website = frappe.db.get_value(
		"BNS Website",
		{"api_user": user, "enabled": 1},
		["name", "base_url"],
		as_dict=True,
	)
	if not website:
		frappe.throw(_("No enabled website is linked to this API user"), frappe.PermissionError)
	return website


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_version():
	version = frappe.cache.get_value(CACHE_VERSION_KEY)
	if version is None:
		version = 1
		frappe.cache.set_value(CACHE_VERSION_KEY, version)
	return version


def _cache_key(website, endpoint, params):
	digest = hashlib.md5(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()
	return f"{CACHE_PREFIX}:v{_cache_version()}:{website}:{endpoint}:{digest}"


def _cached(website, endpoint, params, builder):
	key = _cache_key(website, endpoint, params)
	result = frappe.cache.get_value(key)
	if result is None:
		result = builder()
		frappe.cache.set_value(key, result, expires_in_sec=CACHE_TTL)
	return result


def clear_blog_api_cache(doc=None, method=None):
	"""doc_event on Blog Post (on_update / on_trash) — see hooks.py.

	Bumps a version counter rather than deleting by prefix: frappe's
	delete_keys() runs redis KEYS, an O(keyspace) blocking scan, and this
	fires on every Blog Post save. Orphaned entries expire via CACHE_TTL.
	"""
	# get/set rather than redis INCR: the wrapper's incr isn't namespaced by
	# site, and a lost race here only means two savers pick the same new
	# version — the old entries are abandoned either way.
	frappe.cache.set_value(CACHE_VERSION_KEY, cint(_cache_version()) + 1)

	# single-key delete, no keyspace scan
	frappe.cache.delete_value(WEB_ROUTES_CACHE_KEY)


# ---------------------------------------------------------------------------
# Internal query helpers
# ---------------------------------------------------------------------------


def _base_filters(website_name, category=None):
	filters = [
		["Blog Post", "published", "=", 1],
		["BNS Website Link", "website", "=", website_name],
	]
	if category:
		filters.append(["Blog Post", "blog_category", "=", category])
	return filters


def _absolute(path):
	if not path:
		return None
	if path.startswith(("http://", "https://")):
		return path
	return get_url(path)


def _absolutize_content_urls(html):
	"""Rewrite root-relative URLs (e.g. /files/x.png) to absolute ERP URLs so
	images resolve when the HTML is rendered on another domain.

	Handles srcset separately: it is a comma-separated list of
	"url descriptor" pairs, so a plain attribute rewrite would miss every
	candidate after the first and leave responsive images broken.
	"""
	html = html or ""
	base = get_url()

	# src="/x" / href='/x' — \b stops srcset= from matching here
	html = re.sub(r'\b(src|href)=(["\'])/(?!/)', rf"\1=\2{base}/", html)

	def _fix_srcset(match):
		attr, quote, value = match.group(1), match.group(2), match.group(3)
		candidates = []
		for part in value.split(","):
			part = part.strip()
			if not part:
				continue
			if part.startswith("/") and not part.startswith("//"):
				part = base + part
			candidates.append(part)
		return f"{attr}={quote}{', '.join(candidates)}{quote}"

	return re.sub(r'\b(srcset)=(["\'])(.*?)\2', _fix_srcset, html, flags=re.DOTALL)


MEDIA_URL_RE = re.compile(r'\b(?:src|href)=["\']([^"\']+)["\']')


def _media_urls(html, *extra):
	"""Absolute media URLs referenced by a post.

	Saves the consumer from re-parsing the HTML to find what to download and
	push to its CDN.
	"""
	urls = [u for u in MEDIA_URL_RE.findall(html or "") if u.startswith(("http://", "https://"))]
	urls.extend(u for u in extra if u)
	# order-preserving dedupe keeps output stable for diffing
	return list(dict.fromkeys(urls))


def _category_info(names):
	out = {}
	for name in set(filter(None, names)):
		out[name] = frappe.db.get_value(
			"Blog Category", name, ["name", "title", "route"], as_dict=True
		)
	return out


def _blogger_info(names, with_bio=False):
	fields = ["full_name", "avatar", "bio"] if with_bio else ["full_name", "avatar"]
	out = {}
	for name in set(filter(None, names)):
		info = frappe.db.get_value("Blogger", name, fields, as_dict=True)
		if info:
			info.avatar = _absolute(info.avatar)
		out[name] = info
	return out


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def get_posts(start=0, limit=20, category=None, view="card"):
	"""Paged list of published posts for the authenticated website.

	Returns an envelope: {items, total, start, limit, has_more}.
	``view="card"`` includes intro/image/category/blogger; ``view="headline"``
	is title/route/date only. List responses never include post content.
	"""
	website = _resolve_website()

	start = max(0, cint(start))
	limit = min(max(1, cint(limit) or 20), MAX_LIMIT)
	if view not in LIST_FIELDS:
		view = "card"

	params = {"start": start, "limit": limit, "category": category, "view": view}

	def build():
		filters = _base_filters(website.name, category)

		# distinct: a malformed child table with duplicate website rows must
		# not duplicate posts or skew the count
		all_names = frappe.get_all("Blog Post", filters=filters, pluck="name", limit_page_length=0)
		total = len(set(all_names))

		items = frappe.get_all(
			"Blog Post",
			filters=filters,
			fields=LIST_FIELDS[view],
			order_by="published_on desc, name asc",
			limit_start=start,
			limit_page_length=limit,
			distinct=True,
		)

		if view == "card":
			categories = _category_info([d.blog_category for d in items])
			bloggers = _blogger_info([d.blogger for d in items])
			for d in items:
				d.meta_image = _absolute(d.meta_image)
				d.category = categories.get(d.pop("blog_category", None))
				d.blogger = bloggers.get(d.blogger)

		return {
			"items": items,
			"total": total,
			"start": start,
			"limit": limit,
			"has_more": start + len(items) < total,
		}

	return _cached(website.name, "get_posts", params, build)


FULL_POST_FIELDS = [
	"name",
	"title",
	"route",
	"content",
	"content_md",
	"content_html",
	"content_type",
	"blog_intro",
	"published",
	"published_on",
	"modified",
	"read_time",
	"meta_title",
	"meta_description",
	"meta_image",
	"blog_category",
	"blogger",
]


def _build_payload(post, website, category, blogger):
	content = _absolutize_content_urls(
		get_html_content_based_on_type(post, "content", post.content_type)
	)
	meta_image = _absolute(post.meta_image)

	return {
		"name": post.name,
		"title": post.title,
		"route": post.route,
		"content": content,
		# lets a sync re-process media only when the body actually changed,
		# instead of on every metadata edit
		"content_hash": hashlib.sha256((content or "").encode()).hexdigest(),
		"media": _media_urls(content, meta_image),
		"blog_intro": post.blog_intro,
		"published": cint(post.published),
		"published_on": str(post.published_on) if post.published_on else None,
		"modified": str(post.modified),
		"read_time": post.read_time,
		"meta_title": post.meta_title,
		"meta_description": post.meta_description,
		"meta_image": meta_image,
		"category": category,
		"blogger": blogger,
		"canonical_url": f"{website.base_url}/{post.route}",
	}


def _post_payloads(names, website):
	"""Full payloads for many posts using a fixed number of queries.

	Building these one-by-one costs three round trips each (get_doc plus a
	category and a blogger lookup), which is what made get_changes expensive.
	"""
	if not names:
		return []

	posts = frappe.get_all(
		"Blog Post", filters={"name": ("in", list(names))}, fields=FULL_POST_FIELDS
	)
	categories = _category_info([p.blog_category for p in posts])
	bloggers = _blogger_info([p.blogger for p in posts], with_bio=True)

	by_name = {
		p.name: _build_payload(p, website, categories.get(p.blog_category), bloggers.get(p.blogger))
		for p in posts
	}
	# preserve the caller's ordering (get_changes relies on modified asc)
	return [by_name[n] for n in names if n in by_name]


def _post_payload(name, website):
	"""Full single-post payload."""
	payloads = _post_payloads([name], website)
	return payloads[0] if payloads else None


def _serves_site(name, website_name):
	return bool(
		frappe.db.exists(
			"BNS Website Link",
			{"parenttype": "Blog Post", "parent": name, "website": website_name},
		)
	)


@frappe.whitelist(methods=["GET"])
def get_post(route, include_drafts=0):
	"""One post (full rendered content + meta) by its route.

	``include_drafts=1`` returns unpublished posts too — for the consumer's
	preview route. It is opt-in per call and never affects get_posts, so the
	public listing can't accidentally surface drafts.
	"""
	website = _resolve_website()

	if not route:
		frappe.throw(_("route is required"))

	include_drafts = cint(include_drafts)

	def build():
		filters = {"route": route}
		if not include_drafts:
			filters["published"] = 1

		name = frappe.db.get_value("Blog Post", filters, "name")
		if not name or not _serves_site(name, website.name):
			# same response whether the post doesn't exist or belongs to
			# another website — don't leak which
			frappe.throw(_("Post not found"), frappe.DoesNotExistError)

		return _post_payload(name, website)

	# drafts change constantly during editing; only cache the published read
	if include_drafts:
		return build()

	return _cached(website.name, "get_post", {"route": route}, build)


@frappe.whitelist(methods=["GET"])
def get_changes(since=None, limit=100):
	"""Everything this site must add or drop since ``since``.

	Deliberately reports removals as well as changes. A sync that is only told
	what exists can never delete: "absent" and "withdrawn" look identical from
	the outside, so a post pulled from the site would go on serving from the
	consumer's copy indefinitely.

	Keyed off ``modified`` (database-owned) rather than ``published_on``, which
	is author-controlled and backdatable.

	Store ``next_since`` — not your own clock, and not the newest ``modified``
	you happened to receive — as the cursor for the following call.
	"""
	website = _resolve_website()
	limit = min(max(1, cint(limit) or MAX_CHANGES_LIMIT), MAX_CHANGES_LIMIT)
	now = frappe.utils.now()
	since = _validate_since(since)

	# ---- posts this site should now hold -------------------------------
	names, post_cursor, more_posts = _changed_post_names(website.name, since, now, limit)
	changed = _post_payloads(names, website)

	# ---- posts this site must drop --------------------------------------
	removed, removal_cursor, more_removals = _removed_routes(website.name, since, now, limit)

	has_more = more_posts or more_removals
	# Advance only as far as *both* streams are complete, otherwise the
	# lagging one is skipped. Storing `now` mid-page loses rows permanently.
	next_since = min(post_cursor, removal_cursor) if has_more else now

	return {
		"now": now,
		"next_since": next_since,
		"changed": changed,
		"removed": removed,
		"has_more": has_more,
	}


def _validate_since(since):
	"""Reject an unparseable cursor loudly.

	MariaDB compares a datetime column against a junk string as simply
	non-matching, so a corrupted cursor would otherwise make the sync return
	nothing forever without ever erroring.
	"""
	if not since:
		return None
	if not frappe.utils.get_datetime(str(since).strip()):
		frappe.throw(
			_("Invalid `since` value {0} — expected YYYY-MM-DD HH:MM:SS[.ffffff]").format(since)
		)
	return str(since).strip()


def _page_by_timestamp(rows, limit, field, fallback):
	"""Trim a page so it never splits a group of identical timestamps.

	Paging with `>` on the last row's timestamp drops any sibling row sharing
	that exact value — reachable whenever a patch or bulk edit stamps many
	rows at once. Trimming the trailing group keeps the cursor safe. If the
	whole page shares one timestamp there is nothing to trim, so the group is
	returned intact and the cursor steps past it.
	"""
	has_more = len(rows) > limit
	if not has_more:
		return rows, fallback, False

	rows = rows[:limit]
	last = rows[-1].get(field)
	trimmed = [r for r in rows if r.get(field) != last]
	if trimmed:
		return trimmed, str(trimmed[-1].get(field)), True
	return rows, str(last), True


def _changed_post_names(website_name, since, now, limit):
	"""Names of posts this site should hold that changed since `since`.

	Category and Blogger edits reach consumers because propagation.py stamps
	the affected posts' `modified` at write time — so a single cursor over
	Blog Post stays authoritative, and a rename touching more posts than one
	page can hold simply spans several pages instead of being truncated.
	"""
	filters = [
		["Blog Post", "published", "=", 1],
		["BNS Website Link", "website", "=", website_name],
		["Blog Post", "modified", "<=", now],
	]
	if since:
		filters.append(["Blog Post", "modified", ">", since])

	rows = frappe.get_all(
		"Blog Post",
		filters=filters,
		fields=["name", "modified"],
		order_by="modified asc, name asc",
		limit_page_length=limit + 1,
		distinct=True,
	)
	rows, cursor, has_more = _page_by_timestamp(rows, limit, "modified", now)
	return [r.name for r in rows], cursor, has_more


def _removed_routes(website_name, since, now, limit):
	"""Routes this site must delete, from the removal log.

	Read from BNS Blog Removal rather than inferred by re-querying posts
	without the site filter: inference would hand this site the routes of
	every draft and every other brand's post (see removal_tracker).

	A full export needs no removals — the consumer rebuilds from scratch and
	drops whatever is absent from `changed`.
	"""
	if not since:
		return [], now, False

	rows = frappe.get_all(
		"BNS Blog Removal",
		filters=[
			["website", "=", website_name],
			["creation", ">", since],
			["creation", "<=", now],
		],
		fields=["route", "creation"],
		order_by="creation asc, name asc",
		limit_page_length=limit + 1,
	)
	rows, cursor, has_more = _page_by_timestamp(rows, limit, "creation", now)

	routes = list(dict.fromkeys(r.route for r in rows if r.route))
	return routes, cursor, has_more
