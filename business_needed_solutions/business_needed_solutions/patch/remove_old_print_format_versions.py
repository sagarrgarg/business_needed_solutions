import frappe

# BNS keeps one print format per document: SI V2, PI V2, and V1 for the rest.
# These older or experimental versions are removed. The ones the app shipped are
# gone from the repo and the fixture; the site-made copies (DN V3, PI Temp) were
# stop-gaps for the header cut-off that SI/PI V2 now handle.
OLD_PRINT_FORMATS = (
	"BNS SI Dynamic V1",
	"BNS SI Dynamic V3",
	"BNS SI - V1",
	"BNS SI -V2 (d1d2d3)",
	"BNS PI Dynamic V1",
	"BNS PI Dynamic Temp",
	"BNS DN Dynamic V2",
	"BNS DN Dynamic V3",
)

# The format that replaces them, per document type.
REPLACEMENTS = {
	"Sales Invoice": "BNS SI Dynamic V2",
	"Purchase Invoice": "BNS PI Dynamic V2",
	"Delivery Note": "BNS DN Dynamic V1",
}


def execute():
	in_use = _formats_in_use()
	removed, disabled = [], []

	for name in OLD_PRINT_FORMATS:
		if not frappe.db.exists("Print Format", name):
			continue
		if name in in_use and not repoint(name):
			# Still chosen and no replacement on this site: keep it as it is, printable.
			continue
		try:
			frappe.delete_doc("Print Format", name, ignore_permissions=True, ignore_missing=True)
			removed.append(name)
		except frappe.LinkExistsError:
			# Other documents link to it: keep it (a disabled Print Format cannot print).
			frappe.clear_last_message()
			disabled.append(name)

	frappe.db.commit()
	if removed:
		print(f"remove_old_print_format_versions: removed {', '.join(removed)}")
	if disabled:
		print(f"remove_old_print_format_versions: kept (still referenced) {', '.join(disabled)}")


def _formats_in_use() -> set[str]:
	"""Formats set as a doctype default or in the BNS Settings print table."""
	used = set(
		frappe.get_all(
			"Property Setter",
			filters={"property": "default_print_format", "value": ["in", OLD_PRINT_FORMATS]},
			pluck="value",
		)
	)
	if frappe.db.table_exists("BNS Settings Print Format"):
		used.update(
			frappe.get_all(
				"BNS Settings Print Format",
				filters={"print_format": ["in", OLD_PRINT_FORMATS]},
				pluck="print_format",
			)
		)
	return used


def repoint(name: str) -> bool:
	"""Point the BNS Settings print rows and doctype defaults that use `name` at its
	replacement. False when this site has no replacement for its document type."""
	doc_type = frappe.db.get_value("Print Format", name, "doc_type")
	new = REPLACEMENTS.get(doc_type)
	if not new or not frappe.db.exists("Print Format", new) or frappe.db.get_value("Print Format", new, "disabled"):
		return False

	if frappe.db.table_exists("BNS Settings Print Format"):
		for row in frappe.get_all(
			"BNS Settings Print Format", filters={"print_format": name}, fields=["name", "parent", "doctype_map"]
		):
			duplicate = frappe.db.exists(
				"BNS Settings Print Format",
				{"parent": row.parent, "doctype_map": row.doctype_map, "print_format": new},
			)
			if duplicate:
				frappe.db.delete("BNS Settings Print Format", row.name)
			else:
				frappe.db.set_value("BNS Settings Print Format", row.name, "print_format", new, update_modified=False)

	for ps in frappe.get_all(
		"Property Setter", filters={"property": "default_print_format", "value": name}, pluck="name"
	):
		frappe.db.set_value("Property Setter", ps, "value", new, update_modified=False)

	frappe.clear_cache()
	return True
