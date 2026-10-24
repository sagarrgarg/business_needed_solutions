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


def execute():
	in_use = _formats_in_use()
	removed, disabled = [], []

	for name in OLD_PRINT_FORMATS:
		if not frappe.db.exists("Print Format", name):
			continue
		if name in in_use:
			# Still chosen somewhere: keep it printable, but hide it from new picks.
			frappe.db.set_value("Print Format", name, "disabled", 1, update_modified=False)
			disabled.append(name)
			continue
		try:
			frappe.delete_doc("Print Format", name, ignore_permissions=True, ignore_missing=True)
			removed.append(name)
		except frappe.LinkExistsError:
			frappe.clear_last_message()
			frappe.db.set_value("Print Format", name, "disabled", 1, update_modified=False)
			disabled.append(name)

	frappe.db.commit()
	if removed:
		print(f"remove_old_print_format_versions: removed {', '.join(removed)}")
	if disabled:
		print(f"remove_old_print_format_versions: disabled (still referenced) {', '.join(disabled)}")


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
