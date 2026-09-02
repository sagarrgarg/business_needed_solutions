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
CACHE_TTL = 300  # seconds; also cleared explicitly on Blog Post / BNS Website updates
MAX_LIMIT = 50
MAX_CHANGES_LIMIT = 200  # get_changes rows carry full content; keep the page bounded

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


def _cache_key(website, endpoint, params):
	digest = hashlib.md5(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()
	return f"{CACHE_PREFIX}:{website}:{endpoint}:{digest}"


def _cached(website, endpoint, params, builder):
	key = _cache_key(website, endpoint, params)
	result = frappe.cache.get_value(key)
	if result is None:
		result = builder()
		frappe.cache.set_value(key, result, expires_in_sec=CACHE_TTL)
	return result


def clear_blog_api_cache(doc=None, method=None):
	"""doc_event on Blog Post (on_update / on_trash) — see hooks.py."""
	frappe.cache.delete_keys(CACHE_PREFIX)


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
	"""Rewrite root-relative src/href (e.g. /files/x.png) to absolute ERP URLs
	so images resolve when the HTML is rendered on another domain."""
	base = get_url()
	return re.sub(r'(src|href)=(["\'])/(?!/)', rf"\1=\2{base}/", html or "")


def _category_info(names):
	out = {}
	for name in set(filter(None, names)):
		out[name] = frappe.db.get_value(
			"Blog Category", name, ["name", "title", "route"], as_dict=True
		)
	return out


def _blogger_info(names):
	out = {}
	for name in set(filter(None, names)):
		info = frappe.db.get_value("Blogger", name, ["full_name", "avatar"], as_dict=True)
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


def _post_payload(name, website):
	"""Full single-post payload. Shared by get_post and get_changes."""
	post = frappe.get_doc("Blog Post", name)
	content = _absolutize_content_urls(
		get_html_content_based_on_type(post, "content", post.content_type)
	)

	category = frappe.db.get_value(
		"Blog Category", post.blog_category, ["name", "title", "route"], as_dict=True
	)
	blogger = frappe.db.get_value(
		"Blogger", post.blogger, ["full_name", "avatar", "bio"], as_dict=True
	)
	if blogger:
		blogger.avatar = _absolute(blogger.avatar)

	return {
		"name": post.name,
		"title": post.title,
		"route": post.route,
		"content": content,
		# lets a sync re-process media only when the body actually changed,
		# instead of on every metadata edit
		"content_hash": hashlib.sha256((content or "").encode()).hexdigest(),
		"blog_intro": post.blog_intro,
		"published": cint(post.published),
		"published_on": str(post.published_on) if post.published_on else None,
		"modified": str(post.modified),
		"read_time": post.read_time,
		"meta_title": post.meta_title,
		"meta_description": post.meta_description,
		"meta_image": _absolute(post.meta_image),
		"category": category,
		"blogger": blogger,
		"canonical_url": f"{website.base_url}/{post.route}",
	}


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
	limit = min(max(1, cint(limit) or 100), MAX_CHANGES_LIMIT)
	now = frappe.utils.now()

	filters = {}
	if since:
		filters["modified"] = (">", since)

	# No published/site filter here — that is the point. Posts are fetched
	# regardless of state and partitioned below, so a post that no longer
	# qualifies surfaces as a removal instead of silently vanishing.
	rows = frappe.get_all(
		"Blog Post",
		filters=filters,
		fields=["name", "route", "published", "modified"],
		order_by="modified asc",
		limit_page_length=limit + 1,
	)
	has_more = len(rows) > limit
	rows = rows[:limit]

	serving = set(
		frappe.get_all(
			"BNS Website Link",
			filters={"website": website.name, "parenttype": "Blog Post"},
			pluck="parent",
		)
	)

	changed, removed = [], []
	for row in rows:
		if row.published and row.name in serving:
			changed.append(_post_payload(row.name, website))
		elif since:
			# On a full export the client rebuilds from scratch and deletes
			# whatever isn't in `changed`, so removals are unnecessary there —
			# and omitting them avoids handing this site the routes of every
			# draft and every other brand's post.
			removed.append(row.route)

	# Hard deletes leave no Blog Post row at all; Frappe keeps the corpse here.
	if since:
		for doc in frappe.get_all(
			"Deleted Document",
			filters={"deleted_doctype": "Blog Post", "creation": (">", since)},
			fields=["data"],
		):
			route = (frappe.parse_json(doc.data) or {}).get("route")
			if route:
				removed.append(route)

	return {
		"now": now,
		# While paging, advance by the last row's modified — storing `now`
		# mid-page would skip every row after this batch, permanently.
		"next_since": str(rows[-1].modified) if (has_more and rows) else now,
		"changed": changed,
		"removed": sorted(set(removed)),
		"has_more": has_more,
	}
