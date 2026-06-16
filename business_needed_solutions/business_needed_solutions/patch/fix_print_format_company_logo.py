import frappe


def execute():
	"""Replace the deprecated Company.logo_for_printing field with company_logo
	in all stored print formats.

	India Compliance's v15 patch migrate_logo_for_printing copies
	logo_for_printing -> company_logo and then DELETES the logo_for_printing
	field. Any print format still reading logo_for_printing then crashes with
	"Unknown column 'logo_for_printing'". File-based BNS formats are fixed in
	the repo; this rewrites UI-edited / DB-only copies in place.
	"""
	names = frappe.get_all("Print Format", pluck="name")
	fixed = []
	for name in names:
		html = frappe.db.get_value("Print Format", name, "html")
		if not html or "logo_for_printing" not in html:
			continue
		frappe.db.set_value(
			"Print Format", name, "html", html.replace("logo_for_printing", "company_logo"),
			update_modified=False,
		)
		fixed.append(name)

	if fixed:
		frappe.db.commit()
		print(f"fix_print_format_company_logo: rewrote {len(fixed)} print format(s): {', '.join(fixed)}")
