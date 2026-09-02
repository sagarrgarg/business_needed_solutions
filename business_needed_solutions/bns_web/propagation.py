# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""Push Blog Category / Blogger edits into the posts that embed them.

get_changes pages over a single cursor: Blog Post.modified. Category and
blogger details are embedded in each post's payload, so an edit to either
would otherwise never reach consumers — the post itself never changed.

Stamping the affected posts' `modified` at write time keeps that one cursor
authoritative. The alternative (looking up related changes at read time) has
no cursor of its own, so a rename touching more posts than a single page can
hold would be silently truncated.

Only fields that actually appear in the API payload trigger a stamp, so
unrelated edits don't churn every post in a category.
"""

import frappe

# fields embedded in blog_api payloads
CATEGORY_PAYLOAD_FIELDS = ("title", "route")
BLOGGER_PAYLOAD_FIELDS = ("full_name", "avatar", "bio")

# above this, stamping happens in a background job instead of inline
ENQUEUE_THRESHOLD = 50
BATCH_SIZE = 10


def propagate_category_change(doc, method=None):
	if _payload_fields_changed(doc, CATEGORY_PAYLOAD_FIELDS):
		_touch_posts({"blog_category": doc.name})


def propagate_blogger_change(doc, method=None):
	if _payload_fields_changed(doc, BLOGGER_PAYLOAD_FIELDS):
		_touch_posts({"blogger": doc.name})


def _payload_fields_changed(doc, fields):
	before = doc.get_doc_before_save()
	if not before:
		# new record — nothing embeds it yet
		return False
	return any(before.get(f) != doc.get(f) for f in fields)


def _touch_posts(filters):
	names = frappe.get_all(
		"Blog Post",
		filters={**filters, "published": 1},
		pluck="name",
		limit_page_length=0,
	)
	if not names:
		return

	if len(names) > ENQUEUE_THRESHOLD:
		frappe.enqueue(
			"business_needed_solutions.bns_web.propagation.stamp_posts",
			queue="long",
			names=names,
			enqueue_after_commit=True,
		)
	else:
		stamp_posts(names)


def stamp_posts(names):
	"""Advance `modified` so the posts surface on the next get_changes page.

	update_modified=False stops Frappe overwriting the value we are setting.
	"""
	now = frappe.utils.now()
	for i in range(0, len(names), BATCH_SIZE):
		for name in names[i : i + BATCH_SIZE]:
			frappe.db.set_value("Blog Post", name, "modified", now, update_modified=False)
		frappe.db.commit()

	from business_needed_solutions.bns_web.blog_api import clear_blog_api_cache

	clear_blog_api_cache()
