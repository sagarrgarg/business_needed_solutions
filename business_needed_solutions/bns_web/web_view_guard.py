# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""Stop the ERP from serving blog content on its own domain.

Blog Posts must be published (published=1) for the BNS Web API to deliver
them, but publishing also makes Frappe serve them at <erp-host>/blog/... .
This renderer 404s those web views for guests so the posts only ever appear
on the brand websites configured in BNS Website.

Registered via the ``page_renderer`` hook, so it is consulted before Frappe's
own DocumentPage/ListPage renderers (see frappe/website/path_resolver.py).

Logged-in users are unaffected — staff can still preview posts on the ERP.
Set ``bns_allow_erp_blog_web_view: 1`` in site_config.json to disable this
guard entirely.

Note: has_web_view cannot be turned off with a Property Setter — Frappe reads
it straight from tabDocType in get_doctypes_with_web_view(), bypassing meta.
Hence a renderer rather than a customization.
"""

import frappe
from frappe.website.page_renderers.not_found_page import NotFoundPage

from business_needed_solutions.bns_web.blog_api import WEB_ROUTES_CACHE_KEY

ROUTES_CACHE_TTL = 300

# Endpoints that expose blog content without being a document route:
# "Blog Post" is what /blog resolves to via the DocType route rule, and
# frappe's rss.xml lists every published post. Blog Category is deliberately
# absent — its DocType-level `route` is empty, so no such endpoint is ever
# produced; its *document* routes are covered by _blog_web_routes() below.
STATIC_BLOCKED_ENDPOINTS = {"Blog Post", "rss.xml", "rss"}


class BlogWebViewGuard:
	def __init__(self, path, http_status_code=None):
		self.path = path
		self.http_status_code = http_status_code

	def can_render(self):
		if frappe.session.user != "Guest":
			# staff preview stays available
			return False

		if frappe.conf.get("bns_allow_erp_blog_web_view"):
			return False

		path = (self.path or "").strip("/")
		if path in STATIC_BLOCKED_ENDPOINTS:
			return True

		return path in _blog_web_routes()

	def render(self):
		return NotFoundPage(self.path, http_status_code=404).render()


def _blog_web_routes():
	"""Published Blog Post routes + Blog Category routes, cached."""
	routes = frappe.cache.get_value(WEB_ROUTES_CACHE_KEY)
	if routes is None:
		routes = [
			r
			for r in (
				(frappe.get_all("Blog Post", filters={"published": 1}, pluck="route") or [])
				+ (frappe.get_all("Blog Category", pluck="route") or [])
			)
			if r
		]
		frappe.cache.set_value(WEB_ROUTES_CACHE_KEY, routes, expires_in_sec=ROUTES_CACHE_TTL)
	return set(routes)
