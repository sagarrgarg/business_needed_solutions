# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""
Blog doctypes for Frappe v16 and later.

Frappe v15 shipped Blog Post, Blog Category, Blogger and Blog Settings in its Website module.
v16 removed them from the framework (they moved to the separate frappe/blog app). BNS Web is
built on Blog Post, and BNS's custom-field fixture includes a Blog Post field, so without these
doctypes Frappe skips BNS's whole custom-field fixture and every guest page 403s (the blog web
guard reads Blog Post). On a v16 site without the blog app, BNS therefore provides the same four
doctypes itself, with v15's exact schema and v15's save behaviour.

Who provides them is decided per site on every install and migrate (ensure_blog_doctypes):

* "app" — Frappe v15, or the frappe/blog app: the DocTypes exist with their source files.
  BNS does nothing and the hooks below stay inert.
* "orphan" — a site upgraded from v15 to v16: the DocType records are still in the database
  but their files are gone, so Frappe's migrate would delete the definitions as orphans (the
  tables and posts stay, unusable). BNS adopts them first by marking them custom, which orphan
  cleanup skips, so every definition, post, custom field and permission survives unchanged.
* "missing" — a fresh v16 site, or one whose definitions were already deleted as orphans:
  BNS creates them as custom DocTypes from definitions/*.json, which are copied verbatim from
  frappe version-15 (frappe/website/doctype/*/*.json, MIT licence). An existing table is
  reused as is, so posts left behind by an earlier orphan cleanup come back.

The DocTypes stay in the Website module, as in v15, rather than a BNS module, so uninstalling
BNS never drops blog data. BNS keeps them without a web view: BNS Web serves posts to the brand
websites through its API and never on the ERP domain (see web_view_guard.py).

If the frappe/blog app is installed later it takes the DocTypes over from BNS (same names and
fields) and the hooks below go inert again.
"""

from __future__ import annotations

import json
import os
from math import ceil

import frappe
from frappe import _
from frappe.utils import cint, cstr, markdown, strip_html_tags, today

BLOG_DOCTYPES = ("Blogger", "Blog Category", "Blog Post", "Blog Settings")  # links resolve in this order
DEFINITIONS = os.path.join(os.path.dirname(__file__), "definitions")

# v15's web views need v15's WebsiteGenerator controllers and templates, which a custom DocType
# does not have; BNS never serves blog pages on the ERP domain anyway.
WEB_PROPERTIES_OFF = {"has_web_view": 0, "allow_guest_to_view": 0, "index_web_pages_for_search": 0}

# Definition keys that belong to the source file, not to a DocType created here.
_SOURCE_ONLY_KEYS = (
	"creation",
	"modified",
	"modified_by",
	"owner",
	"idx",
	"doctype",
	"links",
	"actions",
	"states",
)


# --------------------------------------------------------------------------------------
# Install / migrate
# --------------------------------------------------------------------------------------


def ensure_blog_doctypes() -> dict:
	"""Make the four blog DocTypes available on this site. Idempotent.

	Wired to before_install and before_migrate (so the doctypes exist before Frappe syncs BNS's
	custom-field fixture and before it removes orphans) and to after_migrate (a last check).
	Returns {doctype: action} for logging and tests.
	"""
	actions = {}
	changed = False
	known_files = _doctypes_with_source_files()
	for doctype in BLOG_DOCTYPES:
		provider = provider_of(doctype, known_files)
		if provider == "orphan":
			_adopt(doctype)
			actions[doctype], changed = "adopted", True
		elif provider == "missing":
			_create(doctype)
			actions[doctype], changed = "created", True
		else:
			actions[doctype] = provider  # "app" or "bns": nothing to do
	if changed:
		frappe.clear_cache()
	return actions


def provider_of(doctype: str, known_files: set | None = None) -> str:
	""" "app", "bns", "orphan" or "missing" — see the module docstring."""
	row = frappe.db.get_value("DocType", doctype, ["custom"], as_dict=True)
	if not row:
		return "missing"
	if cint(row.custom):
		return "bns"
	if known_files is None:
		known_files = _doctypes_with_source_files(also=(doctype,))
	return "app" if doctype in known_files else "orphan"


def _doctypes_with_source_files(also: tuple = ()) -> set:
	"""DocType names that have a schema file in an installed app — Frappe's own orphan test."""
	try:
		from frappe.model.sync import create_entity_file_map

		return set(create_entity_file_map(["DocType"])["DocType"])
	except (ImportError, AttributeError, KeyError):
		# Older Frappe (v15 still ships these doctypes): look for each blog doctype's file,
		# and for any other doctype the caller asks about.
		return {doctype for doctype in (*BLOG_DOCTYPES, *also) if _has_source_file(doctype)}


def _has_source_file(doctype: str) -> bool:
	module = frappe.db.get_value("DocType", doctype, "module")
	if not module:
		return False
	app = frappe.local.module_app.get(frappe.scrub(module)) or frappe.db.get_value(
		"Module Def", module, "app_name"
	)
	if not app:
		return True  # cannot tell: leave it alone rather than take over an app's doctype
	name = frappe.scrub(doctype)
	path = frappe.get_app_path(app, frappe.scrub(module), "doctype", name, f"{name}.json")
	return os.path.exists(path)


def _adopt(doctype: str) -> None:
	"""Keep an orphaned v15 definition alive by making it custom (orphan cleanup skips custom)."""
	frappe.db.set_value("DocType", doctype, {"custom": 1, **WEB_PROPERTIES_OFF}, update_modified=False)
	frappe.clear_cache(doctype=doctype)
	frappe.logger("bns_web").info(f"BNS adopted orphaned DocType {doctype} (Frappe v16 without the blog app)")


def _create(doctype: str) -> None:
	definition = load_definition(doctype)
	for role in {p.get("role") for p in definition.get("permissions", []) if p.get("role")}:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)
	doc = frappe.get_doc(as_custom_definition(definition))
	doc.insert(ignore_permissions=True)
	frappe.logger("bns_web").info(f"BNS created DocType {doctype} (Frappe v16 without the blog app)")


def load_definition(doctype: str) -> dict:
	with open(os.path.join(DEFINITIONS, f"{frappe.scrub(doctype)}.json")) as f:
		return json.load(f)


def as_custom_definition(definition: dict) -> dict:
	"""The v15 definition as a custom DocType in the Website module, without a web view."""
	doc = {k: v for k, v in definition.items() if k not in _SOURCE_ONLY_KEYS}
	doc.update({"doctype": "DocType", "custom": 1, "module": "Website", **WEB_PROPERTIES_OFF})
	doc["fields"] = [{k: v for k, v in f.items() if k not in _SOURCE_ONLY_KEYS} for f in definition["fields"]]
	doc["permissions"] = [
		{k: v for k, v in p.items() if k not in _SOURCE_ONLY_KEYS} for p in definition.get("permissions", [])
	]
	return doc


# --------------------------------------------------------------------------------------
# v15 save behaviour (doc_events). Inert unless BNS provides the doctype.
# --------------------------------------------------------------------------------------


def bns_provides(doctype: str) -> bool:
	"""True when the doctype is BNS's custom copy (not v15 core, not the blog app)."""
	try:
		return bool(cint(frappe.get_meta(doctype).custom))
	except frappe.DoesNotExistError:
		return False


def _scrub(text) -> str:
	"""WebsiteGenerator.scrub in v15: the page name used for names and routes."""
	from frappe.website.utils import cleanup_page_name

	return cleanup_page_name(cstr(text)).replace("_", "-")


def blog_category_autoname(doc, method=None):
	if bns_provides(doc.doctype) and not doc.name:
		doc.name = _scrub(doc.title)


def blog_category_validate(doc, method=None):
	if bns_provides(doc.doctype):
		doc.route = "blog/" + doc.name  # BlogCategory.set_route


def blog_post_autoname(doc, method=None):
	if bns_provides(doc.doctype) and not doc.name:
		doc.name = _scrub(doc.title)  # WebsiteGenerator.autoname


def blog_post_validate(doc, method=None):
	"""BlogPost.validate in v15 (with WebsiteGenerator.set_route first)."""
	if not bns_provides(doc.doctype):
		return

	if cint(doc.published) and not doc.route:
		category_route = frappe.db.get_value("Blog Category", doc.blog_category, "route")
		doc.route = f"{cstr(category_route)}/{_scrub(doc.title)}"
	if doc.route:
		doc.route = doc.route.strip("/.")[:139]

	if not doc.blog_intro:
		from frappe.website.utils import get_html_content_based_on_type

		content = get_html_content_based_on_type(doc, "content", doc.content_type)
		doc.blog_intro = strip_html_tags(cstr(content)[:200])
	if doc.blog_intro:
		doc.blog_intro = doc.blog_intro[:200]

	doc.meta_title = (doc.meta_title or doc.title or "")[:60]
	doc.meta_description = (doc.meta_description or doc.blog_intro or "")[:140]

	if cint(doc.published) and not doc.published_on:
		doc.published_on = today()

	if cint(doc.featured):
		if not doc.meta_image:
			frappe.throw(_("A featured post must have a cover image"))
		for name in frappe.get_all("Blog Post", {"featured": 1, "name": ("!=", doc.name)}, pluck="name"):
			frappe.db.set_value("Blog Post", name, "featured", 0)

	content = doc.content or doc.content_html or ""
	if doc.content_type == "Markdown":
		content = markdown(doc.content_md or "")
	doc.read_time = ceil(len(strip_html_tags(cstr(content)).split()) / 250)


def blog_post_on_update(doc, method=None):
	if bns_provides(doc.doctype):
		_clear_website_cache("writers")


def blogger_validate(doc, method=None):
	"""Blogger.validate in v15: a blogger's user is created when it does not exist yet."""
	if bns_provides(doc.doctype) and doc.user and not frappe.db.exists("User", doc.user):
		frappe.get_doc(
			{"doctype": "User", "email": doc.user, "first_name": doc.user.split("@", 1)[0]}
		).insert()


def blogger_on_update(doc, method=None):
	"""Blogger.on_update in v15: the user's unattributed posts get this blogger, and the user is
	restricted to this Blogger record."""
	if not bns_provides(doc.doctype):
		return
	_clear_website_cache("blog")
	if doc.user:
		for name in frappe.get_all(
			"Blog Post", {"owner": doc.user, "blogger": ("is", "not set")}, pluck="name"
		):
			post = frappe.get_doc("Blog Post", name)
			post.blogger = doc.name
			post.save()
		frappe.permissions.add_user_permission("Blogger", doc.name, doc.user)


def blog_settings_on_update(doc, method=None):
	if bns_provides(doc.doctype):
		_clear_website_cache("blog")
		_clear_website_cache("writers")


def _clear_website_cache(path):
	from frappe.website.utils import clear_cache

	clear_cache(path)
