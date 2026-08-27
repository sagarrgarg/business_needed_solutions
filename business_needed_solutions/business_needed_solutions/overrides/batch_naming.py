import frappe
from frappe.utils import now_datetime

def get_bns_batch_format_rule(item_code, doctype="Stock Entry", purpose=""):
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

	matched_rule = None
	for row in bns_settings.batch_naming_formats:
		if not row.is_active:
			continue
			
		targets = [t.strip().lower() for t in (row.target_doctype or "").split(",") if t.strip()]
		if doctype and targets and (doctype.lower() not in targets):
			continue
			
		purposes = [p.strip().lower() for p in (row.stock_entry_purposes or "").split(",") if p.strip()]
		if doctype == "Stock Entry" and purposes:
			p_check = (purpose or "").strip().lower()
			if p_check not in purposes:
				continue
				
		matched_rule = row
		break

	return matched_rule

def generate_bns_batch_no(item_code, matched_rule):
	now = now_datetime()
	day_of_year = now.strftime("%j")
	year_1digit = str(now.year)[-1]
	year_2digit = now.strftime("%y")
	year_4digit = now.strftime("%Y")

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

	return base_name, final_batch_no

def ensure_bns_batch_doc(item_code, batch_no):
	if not frappe.db.exists("Batch", {"batch_id": batch_no}) and not frappe.db.exists("Batch", batch_no):
		batch_doc = frappe.new_doc("Batch")
		batch_doc.item = item_code
		batch_doc.batch_id = batch_no
		batch_doc.insert(ignore_permissions=True)

def bns_batch_autoname(doc, method=None):
	"""
	Hooked on Batch DocType autoname.
	Ensures that any Batch created automatically or manually gets named by BNS format rules
	instead of ERPNext standard 7-character random hash (e.g. 227CA50).
	"""
	if not doc.get("item"):
		return

	# If batch_id already explicitly set with custom name (not random 7-char hash), respect it
	if doc.get("batch_id") and len(doc.batch_id) != 7:
		doc.name = doc.batch_id
		return

	ref_doctype = doc.get("reference_doctype") or ""
	ref_name = doc.get("reference_name") or ""
	purpose = ""

	if ref_doctype and ref_name and frappe.db.exists(ref_doctype, ref_name):
		ref_doc = frappe.get_doc(ref_doctype, ref_name)
		purpose = ref_doc.get("purpose") or ref_doc.get("stock_entry_type") or ""

	matched_rule = get_bns_batch_format_rule(doc.item, doctype=ref_doctype or "Stock Entry", purpose=purpose)
	if not matched_rule or not matched_rule.format_string:
		# Try fallback to any active rule for this item
		matched_rule = get_bns_batch_format_rule(doc.item, doctype="")

	if matched_rule and matched_rule.format_string:
		base_name, final_batch_no = generate_bns_batch_no(doc.item, matched_rule)
		doc.batch_id = final_batch_no
		doc.name = final_batch_no

def set_custom_batch_nos(doc, method=None):
	if not frappe.db.exists("DocType", "BNS Settings"):
		return
		
	doctype = doc.doctype
	purpose = doc.get("purpose") or doc.get("stock_entry_type") or ""

	# For Purchase Invoice, only process if stock is updated
	if doctype == "Purchase Invoice" and not doc.get("update_stock"):
		return

	# For return transactions, do not generate new inward batches
	if doc.get("is_return"):
		return

	for item in doc.get("items") or []:
		if not item.get("item_code"):
			continue

		# Skip issue rows (we only create/validate batches when receiving inventory)
		if doctype == "Stock Entry" and not item.get("t_warehouse"):
			continue

		has_batch = frappe.get_cached_value("Item", item.item_code, "has_batch_no")
		if not has_batch:
			continue

		matched_rule = get_bns_batch_format_rule(item.item_code, doctype=doctype, purpose=purpose)
		if not matched_rule or not matched_rule.format_string:
			continue

		base_name, final_batch_no = generate_bns_batch_no(item.item_code, matched_rule)

		# Check if item has a serial_and_batch_bundle attached
		bundle_name = item.get("serial_and_batch_bundle")
		if bundle_name and frappe.db.exists("Serial and Batch Bundle", bundle_name):
			entries = frappe.db.get_all(
				"Serial and Batch Entry",
				filters={"parent": bundle_name},
				fields=["name", "batch_no", "qty"]
			)
			for entry in entries:
				current_batch = entry.batch_no or ""
				# If batch is empty or is a random 7-char hash from ERPNext, update it to BNS batch
				if not current_batch or (not current_batch.startswith(base_name) and len(current_batch) == 7):
					ensure_bns_batch_doc(item.item_code, final_batch_no)
					frappe.db.set_value("Serial and Batch Entry", entry.name, "batch_no", final_batch_no)
					if item.get("batch_no"):
						item.batch_no = final_batch_no
		elif not item.get("batch_no"):
			ensure_bns_batch_doc(item.item_code, final_batch_no)
			item.batch_no = final_batch_no
		else:
			# Validate manually provided batch
			current_batch = item.get("batch_no") or ""
			if current_batch and not current_batch.startswith(base_name):
				# If it was an auto-generated random 7-char hash, fix it
				if len(current_batch) == 7 and not frappe.db.exists("Stock Ledger Entry", {"batch_no": current_batch}):
					ensure_bns_batch_doc(item.item_code, final_batch_no)
					item.batch_no = final_batch_no
				else:
					has_sles = frappe.db.exists("Stock Ledger Entry", {"batch_no": current_batch})
					if not has_sles:
						frappe.throw(f"Row #{item.idx}: Manually created Batch '{current_batch}' does not match the required format '{base_name}' for this transaction.")

@frappe.whitelist()
def get_expected_batch_no(item_code, doctype="Stock Entry", purpose="Manufacture"):
	matched_rule = get_bns_batch_format_rule(item_code, doctype=doctype, purpose=purpose)
	if not matched_rule or not matched_rule.format_string:
		return None

	base_name, final_batch_no = generate_bns_batch_no(item_code, matched_rule)
	return final_batch_no