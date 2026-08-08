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
		# Only process if item requires a batch and doesn't have one yet
		if not item.get("batch_no") and item.get("item_code"):
			# Check if item has batch tracking enabled
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
