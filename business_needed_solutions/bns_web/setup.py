# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""Idempotent setup for the "Website API" role (BNS Web).

The role is for the brand websites' lead-capture flow (contact forms posting
into CRM). It is deliberately NOT needed by the blog API: blog_api.py uses
permission-ignoring server-side queries with its own site scoping, so the
per-site API users work with zero roles. Never grant this role read on
Blog Post / Blogger / Blog Category / BNS Website — that would open the
generic /api/resource endpoints and bypass the per-site filtering.

Runs on after_migrate. CRM doctypes (CRM Lead, FCRM Note, CRM Lead Source)
only exist when the Frappe CRM app is installed; missing doctypes are skipped
so migrate never breaks on a site without CRM.
"""

import frappe

WEBSITE_API_ROLE = "Website API"

# Mirrors the operator-approved permission matrix. Flags not listed are 0.
WEBSITE_API_PERMS = [
	{"doctype": "CRM Lead Source", "read": 1},
	{"doctype": "Contact", "read": 1, "if_owner": 1},
	{"doctype": "Company", "read": 1},
	{"doctype": "Campaign", "read": 1},
	{"doctype": "CRM Lead", "read": 1, "create": 1},
	{"doctype": "FCRM Note", "create": 1},
	{"doctype": "Comment", "create": 1},
]

PTYPE_FLAGS = (
	"select",
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"report",
	"import",
	"export",
	"print",
	"email",
	"share",
)


def ensure_website_api_role():
	_ensure_role()
	for spec in WEBSITE_API_PERMS:
		doctype = spec["doctype"]
		if not frappe.db.exists("DocType", doctype):
			# e.g. CRM app not installed on this site
			continue
		_ensure_perm(doctype, spec)
	frappe.clear_cache()


def ensure_blog_not_in_sitemap():
	"""Keep ERP-hosted blog URLs out of sitemap.xml / search indexing.

	www/sitemap.py skips doctypes whose meta.allow_guest_to_view is falsy, and
	that path *does* read meta — so a Property Setter works here (unlike
	has_web_view, which is read straight from tabDocType). Without this the
	sitemap would advertise blog URLs that BlogWebViewGuard then 404s.
	"""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	for doctype in ("Blog Post", "Blog Category"):
		if not frappe.db.exists("DocType", doctype):
			continue
		make_property_setter(
			doctype,
			None,
			"allow_guest_to_view",
			0,
			"Check",
			for_doctype=True,
			validate_fields_for_doctype=False,
		)


def ensure_crm_country_field():
	"""Select field with all country names on CRM Lead (module BNS Web).

	Options are generated from frappe's geo data at migrate time instead of
	being hardcoded, and the field is only created where the CRM app exists.
	"""
	if not frappe.db.exists("DocType", "CRM Lead"):
		return

	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
	from frappe.geo.country_info import get_all as get_all_countries

	options = "\n".join(["", *sorted(get_all_countries().keys())])

	create_custom_fields(
		{
			"CRM Lead": [
				{
					"fieldname": "country",
					"label": "Country",
					"fieldtype": "Select",
					"options": options,
					"insert_after": "territory",
					"module": "BNS Web",
				}
			]
		},
		update=True,
	)


def _ensure_role():
	if frappe.db.exists("Role", WEBSITE_API_ROLE):
		return
	frappe.get_doc(
		{
			"doctype": "Role",
			"role_name": WEBSITE_API_ROLE,
			"desk_access": 0,
		}
	).insert(ignore_permissions=True)


def _ensure_perm(doctype, spec):
	from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype
	from frappe.permissions import setup_custom_perms

	# Without this, the first Custom DocPerm on a doctype would REPLACE all
	# its standard permissions instead of adding to them.
	setup_custom_perms(doctype)

	if_owner = spec.get("if_owner", 0)
	filters = {
		"parent": doctype,
		"role": WEBSITE_API_ROLE,
		"permlevel": 0,
		"if_owner": if_owner,
	}
	name = frappe.db.get_value("Custom DocPerm", filters)

	if name:
		perm = frappe.get_doc("Custom DocPerm", name)
	else:
		perm = frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": doctype,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": WEBSITE_API_ROLE,
				"permlevel": 0,
				"if_owner": if_owner,
			}
		)

	changed = perm.is_new()
	for flag in PTYPE_FLAGS:
		want = int(spec.get(flag, 0))
		if int(perm.get(flag) or 0) != want:
			perm.set(flag, want)
			changed = True

	if changed:
		perm.save(ignore_permissions=True)
		validate_permissions_for_doctype(doctype)
