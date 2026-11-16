import frappe

from business_needed_solutions.business_needed_solutions.patch.remove_old_print_format_versions import (
	OLD_PRINT_FORMATS,
	_formats_in_use,
	repoint,
)


def execute():
	"""remove_old_print_format_versions disabled old formats that were still chosen
	(BNS Settings print rows, doctype default). Frappe refuses to print a disabled
	format, so direct print of those doctypes failed. Point them at the current
	format; where the site has none, enable the old one again."""
	in_use = _formats_in_use()
	for name in OLD_PRINT_FORMATS:
		if not frappe.db.get_value("Print Format", name, "disabled"):
			continue
		if name in in_use and repoint(name):
			print(f"reenable_old_print_formats_still_in_use: {name} -> replacement")
			continue
		# Still linked from somewhere (or no replacement): make it printable again.
		frappe.db.set_value("Print Format", name, "disabled", 0, update_modified=False)
		print(f"reenable_old_print_formats_still_in_use: enabled {name}")
	frappe.db.commit()
