# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""Record when a Blog Post stops qualifying for a website.

A consumer sync must be told what to *drop*, not just what exists — "absent"
and "withdrawn" are indistinguishable from outside, so a post pulled from a
site would otherwise serve from the consumer's local copy forever.

Inferring removals by re-querying posts without the published/site filters
(the obvious approach) forces the API to hand every site the routes of every
draft and every other brand's post. Recording removals at the moment they
happen keeps get_changes both precise and leak-free: a site is only ever told
about posts it actually had.

Wired as Blog Post doc_events in hooks.py. Bulk/direct-SQL writes bypass
document events and so bypass this — a full re-export (get_changes with no
`since`) is the recovery path.
"""

import frappe

REASON_UNPUBLISHED = "Unpublished"
REASON_UNSERVED = "Unserved"
REASON_DELETED = "Deleted"
REASON_ROUTE_CHANGED = "Route Changed"


def _sites_of(doc):
	"""Website names tagged on a Blog Post document (saved or in-memory)."""
	return {row.website for row in (doc.get("bns_websites") or []) if row.website}


def _log(website, route, blog_post, reason):
	if not (website and route):
		return
	frappe.get_doc(
		{
			"doctype": "BNS Blog Removal",
			"website": website,
			"route": route,
			"blog_post": blog_post,
			"reason": reason,
		}
	).insert(ignore_permissions=True)


def track_blog_post_removals(doc, method=None):
	"""on_update: log every site that lost this post, and why."""
	before = doc.get_doc_before_save()
	if not before:
		# first insert — nothing can have been removed yet
		return

	was_published = bool(before.get("published"))
	is_published = bool(doc.get("published"))
	old_sites = _sites_of(before)
	new_sites = _sites_of(doc)
	old_route = before.get("route")

	for website in old_sites:
		if not was_published:
			# the consumer never had it, so there is nothing to withdraw
			continue

		if website not in new_sites:
			_log(website, old_route, doc.name, REASON_UNSERVED)
		elif not is_published:
			_log(website, old_route, doc.name, REASON_UNPUBLISHED)
		elif old_route and old_route != doc.get("route"):
			# the old URL is now dead on the consumer; the new one arrives as
			# a normal change in the same sync
			_log(website, old_route, doc.name, REASON_ROUTE_CHANGED)


def track_blog_post_deletion(doc, method=None):
	"""on_trash: every site currently serving this post loses it."""
	if not doc.get("published"):
		return
	for website in _sites_of(doc):
		_log(website, doc.get("route"), doc.name, REASON_DELETED)
