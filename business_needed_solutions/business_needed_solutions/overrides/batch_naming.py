import frappe
from frappe.utils import now_datetime

def set_custom_batch_nos(doc, method):
	if not frappe.db.exists("DocType", "BNS Settings"):
		return
		
	try:
		bns_settings = frappe.get_doc("BNS Settings")
		if not bns_settings.get("batch_naming_formats"):
			return
	except Exception:
		return

	# Determine current doctype and purpose
	doctype = doc.doctype
	purpose = doc.get("purpose") or doc.get("stock_entry_type") or ""

	now = now_datetime()
	day_of_year = now.strftime("%j")
	year_1digit = str(now.year)[-1]
	year_2digit = now.strftime("%y")
	year_4digit = now.strftime("%Y")

	for item in doc.get("items") or []:
		if not item.get("item_code"):
			continue

		# Skip issue rows (we only create/validate batches when receiving inventory)
		if doctype == "Stock Entry" and not item.get("t_warehouse"):
			continue
		if doctype in ["Purchase Receipt", "Purchase Invoice"] and doc.get("is_return"):
			continue

		has_batch = frappe.get_cached_value("Item", item.item_code, "has_batch_no")
		if not has_batch:
			continue

		# Find matching rule
		matched_rule = None
		for row in bns_settings.batch_naming_formats:
			if not row.is_active:
				continue
				
			targets = [t.strip() for t in (row.target_doctype or "").split(",") if t.strip()]
			if doctype not in targets:
				continue
				
			purposes = [p.strip() for p in (row.stock_entry_purposes or "").split(",") if p.strip()]
			if doctype == "Stock Entry" and purposes and purpose not in purposes:
				continue
				
			matched_rule = row
			break

		if not matched_rule or not matched_rule.format_string:
			continue

		# Generate base name
		base_name = matched_rule.format_string.format(
			item_code=item.item_code,
			day_of_year=day_of_year,
			year_1digit=year_1digit,
			year_2digit=year_2digit,
			year_4digit=year_4digit
		)

		has_provided_batch = item.get("batch_no") or item.get("serial_and_batch_bundle")

		if not has_provided_batch:
			final_batch_no = base_name
			if matched_rule.append_suffix:
				# Append suffix sequentially -01, -02...
				suffix_idx = 1
				while frappe.db.exists("Batch", {"batch_id": f"{base_name}-{suffix_idx:02d}"}):
					suffix_idx += 1
				final_batch_no = f"{base_name}-{suffix_idx:02d}"

			# Ensure the Batch exists in the database
			if not frappe.db.exists("Batch", {"batch_id": final_batch_no}):
				batch_doc = frappe.new_doc("Batch")
				batch_doc.item = item.item_code
				batch_doc.batch_id = final_batch_no
				batch_doc.insert(ignore_permissions=True)
			
			item.batch_no = final_batch_no
		else:
			# Validate manually provided batches
			batches_to_check = []
			if item.get("batch_no"):
				batches_to_check.append(item.batch_no)
			
			if item.get("serial_and_batch_bundle"):
				bundle_entries = frappe.db.get_all(
					"Serial and Batch Entry",
					filters={"parent": item.serial_and_batch_bundle},
					fields=["batch_no"]
				)
				batches_to_check.extend([e.batch_no for e in bundle_entries if e.batch_no])
				
			for b_id in batches_to_check:
				if not b_id:
					continue
				if not b_id.startswith(base_name):
					# Check if it's a BRAND NEW batch (no Stock Ledger Entries exist yet)
					has_sles = frappe.db.exists("Stock Ledger Entry", {"batch_no": b_id})
					if not has_sles:
						frappe.throw(f"Row #{item.idx}: Manually created Batch '{b_id}' does not match the required format '{base_name}' for this transaction.")

@frappe.whitelist()
def get_expected_batch_no(item_code, doctype="Stock Entry", purpose="Manufacture"):
	if not frappe.db.exists("DocType", "BNS Settings"):
		return None
		
	try:
		bns_settings = frappe.get_doc("BNS Settings")
		if not bns_settings.get("batch_naming_formats"):
			return None
	except Exception:
		return None

	has_batch = frappe.get_cached_value("Item", item_code, "has_batch_no")
	if not has_batch:
		return None

	now = now_datetime()
	day_of_year = now.strftime("%j")
	year_1digit = str(now.year)[-1]
	year_2digit = now.strftime("%y")
	year_4digit = now.strftime("%Y")

	matched_rule = None
	for row in bns_settings.batch_naming_formats:
		if not row.is_active:
			continue
			
		targets = [t.strip() for t in (row.target_doctype or "").split(",") if t.strip()]
		if doctype not in targets:
			continue
			
		purposes = [p.strip() for p in (row.stock_entry_purposes or "").split(",") if p.strip()]
		if doctype == "Stock Entry" and purposes and purpose not in purposes:
			continue
			
		matched_rule = row
		break

	if not matched_rule or not matched_rule.format_string:
		return None

	base_name = matched_rule.format_string.format(
		item_code=item_code,
		day_of_year=day_of_year,
		year_1digit=year_1digit,
		year_2digit=year_2digit,
		year_4digit=year_4digit
	)

	final_batch_no = base_name

	if matched_rule.append_suffix:
		suffix_idx = 1
		while frappe.db.exists("Batch", {"batch_id": f"{base_name}-{suffix_idx:02d}"}):
			suffix_idx += 1
		final_batch_no = f"{base_name}-{suffix_idx:02d}"

	return final_batch_no
