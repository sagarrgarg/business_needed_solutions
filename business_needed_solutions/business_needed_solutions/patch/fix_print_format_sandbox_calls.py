import re

import frappe

# Newer Frappe hardens the print-format jinja sandbox:
# - frappe.get_doc is swapped for get_doc_as_dict(doctype, name), so the
#   single-arg Singles form frappe.get_doc("BNS Settings") crashes with
#   "get_doc_as_dict() missing 1 required positional argument: 'name'".
# - frappe.get_attr is blocked outright.
# File-based formats are fixed in the repo, but UI-edited copies and DB-only
# formats live in tabPrint Format and never re-sync from files — this patch
# rewrites those rows in place.

SINGLE_ARG_GET_DOC = re.compile(r"""frappe\.get_doc\(\s*(['"])([^'"]+)\1\s*\)""")

GET_ATTR_EWAYBILL = re.compile(
    r"""frappe\.get_attr\(\s*['"]business_needed_solutions\.bns_branch_accounting"""
    r"""\.gst_integration\.get_ewaybill_data_for_print['"]\s*\)"""
)


def execute():
	names = frappe.get_all("Print Format", pluck="name")
	fixed = []
	for name in names:
		html = frappe.db.get_value("Print Format", name, "html")
		if not html:
			continue

		new = SINGLE_ARG_GET_DOC.sub(lambda m: f"frappe.get_doc({m.group(1)}{m.group(2)}{m.group(1)}, {m.group(1)}{m.group(2)}{m.group(1)})", html)
		new = GET_ATTR_EWAYBILL.sub("get_ewaybill_data_for_print", new)

		if new != html:
			frappe.db.set_value("Print Format", name, "html", new, update_modified=False)
			fixed.append(name)

	if fixed:
		frappe.db.commit()
		print(f"fix_print_format_sandbox_calls: rewrote {len(fixed)} print format(s): {', '.join(fixed)}")
