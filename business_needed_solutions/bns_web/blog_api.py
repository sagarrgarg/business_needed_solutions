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

LIST_FIELDS = {
	"card": [
		"name",
		"title",
		"route",
		"blog_intro",
		"meta_image",
		"published_on",
		"read_time",
		"blog_category",
		"blogger",
	],
	"headline": ["name", "title", "route", "published_on"],
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


@frappe.whitelist(methods=["GET"])
def get_post(route):
	"""One published post (full rendered content + meta) by its route."""
	website = _resolve_website()

	if not route:
		frappe.throw(_("route is required"))

	def build():
		name = frappe.db.get_value("Blog Post", {"route": route, "published": 1}, "name")
		if not name or not frappe.db.exists(
			"BNS Website Link",
			{"parenttype": "Blog Post", "parent": name, "website": website.name},
		):
			# same response whether the post doesn't exist or belongs to
			# another website — don't leak which
			frappe.throw(_("Post not found"), frappe.DoesNotExistError)

		post = frappe.get_doc("Blog Post", name)
		content = get_html_content_based_on_type(post, "content", post.content_type)

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
			"content": _absolutize_content_urls(content),
			"blog_intro": post.blog_intro,
			"published_on": str(post.published_on) if post.published_on else None,
			"read_time": post.read_time,
			"meta_title": post.meta_title,
			"meta_description": post.meta_description,
			"meta_image": _absolute(post.meta_image),
			"category": category,
			"blogger": blogger,
			"canonical_url": f"{website.base_url}/{post.route}",
		}

	return _cached(website.name, "get_post", {"route": route}, build)
