# Copyright (c) 2025, Business Needed Solutions and Contributors
# License: Commercial

"""
Internal Transfer Receive Mismatch Report

This report identifies Delivery Notes and Sales Invoices with internal customers that are missing
their corresponding Purchase Receipts/Purchase Invoices or have quantity mismatches.

Matching Logic:
1. DN to PR (Same GSTIN):
   - Only shows Delivery Notes where Company GSTIN matches Customer GSTIN
   - Matches Delivery Note items with Purchase Receipt items via delivery_note_item field
   - Checks if quantities match between DN and PR items

2. SI to PI (Different GSTIN):
   - Shows Sales Invoices where Company GSTIN differs from Customer GSTIN
   - Checks if Purchase Invoice exists via inter_company_invoice_reference
   - Checks if quantities match between SI and PI items

3. SI to PR (Different GSTIN, Stock Items):
   - Shows Sales Invoices where Company GSTIN differs from Customer GSTIN
   - Checks if Purchase Receipt exists via supplier_delivery_note or bns_inter_company_reference
   - Checks if quantities match between SI and PR items
"""

import frappe
from frappe import _
from frappe.utils import today


def execute(filters=None):
	"""
	Execute the report and return columns and data.
	
	Args:
		filters: Dictionary of filters (optional)
		
	Returns:
		tuple: (columns, data) where columns is a list of column definitions
		       and data is a list of dictionaries containing report data
	"""
	if not filters:
		filters = {}
	
	columns = get_columns()
	data = get_data(filters)
	
	# Ensure we always return valid data
	if not data:
		data = []
	
	return columns, data


def get_columns():
	"""Define report columns."""
	return [
		{
			"fieldname": "posting_date",
			"label": _("Posting Date"),
			"fieldtype": "Date",
			"width": 100
		},
		{
			"fieldname": "document_type",
			"label": _("Document Type"),
			"fieldtype": "Data",
			"width": 120
		},
		{
			"fieldname": "document_name",
			"label": _("Document"),
			"fieldtype": "Dynamic Link",
			"options": "document_type",
			"width": 150
		},
		{
			"fieldname": "grand_total",
			"label": _("Grand Total"),
			"fieldtype": "Currency",
			"width": 120
		},
		{
			"fieldname": "missing_document",
			"label": _("Missing Document"),
			"fieldtype": "Data",
			"width": 150
		},
		{
			"fieldname": "mismatch_reason",
			"label": _("Mismatch Reason"),
			"fieldtype": "Data",
			"width": 200
		},
		{
			"fieldname": "purchase_receipt",
			"label": _("Purchase Receipt"),
			"fieldtype": "Link",
			"options": "Purchase Receipt",
			"width": 150
		},
		{
			"fieldname": "purchase_invoice",
			"label": _("Purchase Invoice"),
			"fieldtype": "Link",
			"options": "Purchase Invoice",
			"width": 150
		}
	]


def get_data(filters=None):
	"""
	Get report data by checking for missing or mismatched Purchase Receipts/Purchase Invoices.
	
	Args:
		filters: Dictionary of filters (optional)
		
	Returns:
		list: List of dictionaries containing report data
	"""
	data = []
	
	# Get Delivery Notes with internal customers that are missing Purchase Receipts
	dn_data = get_delivery_note_mismatches(filters)
	data.extend(dn_data)
	
	# Get Sales Invoices with internal customers that are missing Purchase Invoices or Purchase Receipts
	si_data = get_sales_invoice_mismatches(filters)
	data.extend(si_data)
	
	# Sort by posting date descending (handle None values)
	if data:
		data.sort(key=lambda x: x.get("posting_date") or today(), reverse=True)
	
	return data or []


def get_delivery_note_mismatches(filters=None):
	"""
	Get Delivery Notes that are missing Purchase Receipts or have quantity mismatches.
	Matches by delivery_note_item field in Purchase Receipt Item and checks quantities.
	
	Returns:
		list: List of dictionaries with DN mismatch data
	"""
	conditions = []
	values = []
	
	# Base conditions
	conditions.append("c.is_bns_internal_customer = 1")
	conditions.append("dn.docstatus = 1")
	# Only show DNs where GSTINs match (exclude GSTIN mismatches)
	conditions.append("(dn.company_gstin IS NOT NULL AND dn.billing_address_gstin IS NOT NULL AND dn.company_gstin = dn.billing_address_gstin)")
	
	# Add filter conditions
	if filters:
		if filters.get("company"):
			conditions.append("dn.company = %s")
			values.append(filters.company)
		
		if filters.get("customer"):
			conditions.append("dn.customer = %s")
			values.append(filters.customer)
		
		if filters.get("from_date"):
			conditions.append("dn.posting_date >= %s")
			values.append(filters.from_date)
		
		if filters.get("to_date"):
			conditions.append("dn.posting_date <= %s")
			values.append(filters.to_date)
	
	where_clause = " AND ".join(conditions)
	
	# Get all Delivery Notes with internal customers
	dn_query = """
		SELECT 
			dn.posting_date,
			dn.name,
			dn.grand_total
		FROM 
			`tabDelivery Note` dn
		JOIN 
			`tabCustomer` c ON dn.customer = c.name
		WHERE 
			""" + where_clause
	
	try:
		dn_results = frappe.db.sql(dn_query, tuple(values), as_dict=True) or []
	except Exception as e:
		frappe.log_error(f"Error in get_delivery_note_mismatches: {str(e)}")
		dn_results = []
	
	mismatches = []
	for dn in dn_results:
		dn_name = dn.get("name") or ""
		
		# Get all Delivery Note items
		dn_items_query = """
			SELECT 
				name,
				item_code,
				qty,
				stock_qty
			FROM `tabDelivery Note Item`
			WHERE parent = %s
		"""
		
		try:
			dn_items = frappe.db.sql(dn_items_query, (dn_name,), as_dict=True) or []
		except Exception as e:
			frappe.log_error(f"Error fetching DN items for {dn_name}: {str(e)}")
			dn_items = []
		
		if not dn_items:
			# Skip if no items
			continue
		
		# Check each DN item against PR items
		missing_items = []
		qty_mismatches = []
		matched_prs = set()
		
		for dn_item in dn_items:
			dn_item_name = dn_item.get("name")
			dn_qty = dn_item.get("qty") or 0
			dn_stock_qty = dn_item.get("stock_qty") or 0
			
			# Find Purchase Receipt items linked to this DN item
			pr_item_query = """
				SELECT 
					pri.parent as pr_name,
					pri.qty as pr_qty,
					pri.stock_qty as pr_stock_qty,
					pr.docstatus
				FROM `tabPurchase Receipt Item` pri
				JOIN `tabPurchase Receipt` pr ON pri.parent = pr.name
				WHERE pri.delivery_note_item = %s
				AND pr.docstatus = 1
			"""
			
			try:
				pr_items = frappe.db.sql(pr_item_query, (dn_item_name,), as_dict=True) or []
			except Exception as e:
				frappe.log_error(f"Error checking PR items for DN item {dn_item_name}: {str(e)}")
				pr_items = []
			
			if not pr_items:
				# Item not found in any PR
				missing_items.append({
					"item": dn_item.get("item_code") or "",
					"dn_qty": dn_qty
				})
			else:
				# Aggregate quantities from all PRs for this DN item
				total_pr_qty = 0
				total_pr_stock_qty = 0
				pr_names_for_item = []
				
				for pr_item in pr_items:
					pr_name = pr_item.get("pr_name")
					pr_qty = pr_item.get("pr_qty") or 0
					pr_stock_qty = pr_item.get("pr_stock_qty") or 0
					
					matched_prs.add(pr_name)
					pr_names_for_item.append(pr_name)
					total_pr_qty += pr_qty
					total_pr_stock_qty += pr_stock_qty
				
				# Check if aggregated quantities match DN quantity
				# Use stock_qty if available, else qty
				if dn_stock_qty > 0:
					if abs(dn_stock_qty - total_pr_stock_qty) > 0.001:  # Allow small floating point differences
						qty_mismatches.append({
							"item": dn_item.get("item_code") or "",
							"pr": ", ".join(pr_names_for_item[:3]),  # Show up to 3 PR names
							"dn_qty": dn_stock_qty,
							"pr_qty": total_pr_stock_qty
						})
				else:
					if abs(dn_qty - total_pr_qty) > 0.001:
						qty_mismatches.append({
							"item": dn_item.get("item_code") or "",
							"pr": ", ".join(pr_names_for_item[:3]),  # Show up to 3 PR names
							"dn_qty": dn_qty,
							"pr_qty": total_pr_qty
						})
		
		# Determine mismatch reason
		mismatch_reason = ""
		missing_doc = "Purchase Receipt"
		purchase_receipt = None
		
		# Check if PR is completely missing (no PR found for any item)
		if not matched_prs:
			# No PR found at all
			mismatch_reason = "No PR for DN"
			missing_doc = "Purchase Receipt"
		else:
			# PR exists, show item-wise differences
			purchase_receipt = list(matched_prs)[0]
			
			# Combine missing items and quantity mismatches for item-wise display
			all_mismatches = []
			
			# Add missing items
			for item in missing_items:
				all_mismatches.append({
					"item": item['item'],
					"dn_qty": item['dn_qty'],
					"pr_qty": 0,
					"type": "missing"
				})
			
			# Add quantity mismatches
			for mismatch in qty_mismatches:
				all_mismatches.append({
					"item": mismatch['item'],
					"dn_qty": mismatch['dn_qty'],
					"pr_qty": mismatch['pr_qty'],
					"type": "qty_mismatch"
				})
			
			if all_mismatches:
				# Show item-wise differences
				mismatch_list = []
				for m in all_mismatches[:5]:  # Show up to 5 items
					if m['type'] == "missing":
						mismatch_list.append(f"{m['item']} (DN: {m['dn_qty']}, PR: Missing)")
					else:
						mismatch_list.append(f"{m['item']} (DN: {m['dn_qty']}, PR: {m['pr_qty']})")
				
				if len(all_mismatches) > 5:
					mismatch_list.append(f"and {len(all_mismatches) - 5} more items")
				
				mismatch_reason = ", ".join(mismatch_list)
				missing_doc = "Purchase Receipt (Partial)"
			else:
				# No mismatch found, skip this DN
				continue
		
		mismatches.append({
			"posting_date": dn.get("posting_date") or None,
			"document_type": "Delivery Note",
			"document_name": dn_name,
			"grand_total": dn.get("grand_total") or 0.0,
			"missing_document": missing_doc,
			"mismatch_reason": mismatch_reason,
			"purchase_receipt": purchase_receipt,
			"purchase_invoice": None
		})
	
	return mismatches or []


def get_sales_invoice_mismatches(filters=None):
	"""
	Get Sales Invoices that are missing Purchase Invoices or Purchase Receipts or have quantity mismatches.
	Only checks Sales Invoices where GSTINs differ (different GSTIN flow).
	
	Returns:
		list: List of dictionaries with SI mismatch data
	"""
	conditions = []
	values = []
	
	# Base conditions - SI with internal customer and different GSTIN
	conditions.append("c.is_bns_internal_customer = 1")
	conditions.append("si.docstatus = 1")
	conditions.append("si.status = 'BNS Internally Transferred'")
	# Only show SIs where GSTINs differ (different GSTIN flow)
	conditions.append("(si.company_gstin IS NOT NULL AND si.billing_address_gstin IS NOT NULL AND si.company_gstin != si.billing_address_gstin)")
	
	# Add filter conditions
	if filters:
		if filters.get("company"):
			conditions.append("si.company = %s")
			values.append(filters.company)
		
		if filters.get("customer"):
			conditions.append("si.customer = %s")
			values.append(filters.customer)
		
		if filters.get("from_date"):
			conditions.append("si.posting_date >= %s")
			values.append(filters.from_date)
		
		if filters.get("to_date"):
			conditions.append("si.posting_date <= %s")
			values.append(filters.to_date)
	
	where_clause = " AND ".join(conditions)
	
	# Get all Sales Invoices with internal customers and different GSTIN
	si_query = """
		SELECT 
			si.posting_date,
			si.name,
			si.grand_total
		FROM 
			`tabSales Invoice` si
		JOIN 
			`tabCustomer` c ON si.customer = c.name
		WHERE 
			""" + where_clause
	
	try:
		si_results = frappe.db.sql(si_query, tuple(values), as_dict=True) or []
	except Exception as e:
		frappe.log_error(f"Error in get_sales_invoice_mismatches: {str(e)}")
		si_results = []
	
	mismatches = []
	for si in si_results:
		si_name = si.get("name") or ""
		
		# Get all Sales Invoice items
		si_items_query = """
			SELECT 
				name,
				item_code,
				qty,
				stock_qty
			FROM `tabSales Invoice Item`
			WHERE parent = %s
		"""
		
		try:
			si_items = frappe.db.sql(si_items_query, (si_name,), as_dict=True) or []
		except Exception as e:
			frappe.log_error(f"Error fetching SI items for {si_name}: {str(e)}")
			si_items = []
		
		if not si_items:
			# Skip if no items
			continue
		
		# Check for Purchase Invoice mismatch
		pi_mismatch = check_si_pi_mismatch(si_name, si_items)
		
		# Check for Purchase Receipt mismatch (for stock items)
		pr_mismatch = check_si_pr_mismatch(si_name, si_items)
		
		# Combine PI and PR mismatches into one row
		if pi_mismatch or pr_mismatch:
			# Combine missing documents
			missing_docs = []
			if pi_mismatch:
				missing_docs.append(pi_mismatch.get("missing_doc", "Purchase Invoice"))
			if pr_mismatch:
				missing_docs.append(pr_mismatch.get("missing_doc", "Purchase Receipt"))
			
			# Combine mismatch reasons
			reasons = []
			if pi_mismatch and pi_mismatch.get("reason"):
				reasons.append(f"PI: {pi_mismatch.get('reason')}")
			if pr_mismatch and pr_mismatch.get("reason"):
				reasons.append(f"PR: {pr_mismatch.get('reason')}")
			
			mismatches.append({
				"posting_date": si.get("posting_date") or None,
				"document_type": "Sales Invoice",
				"document_name": si_name,
				"grand_total": si.get("grand_total") or 0.0,
				"missing_document": " / ".join(missing_docs) if missing_docs else "Purchase Invoice / Purchase Receipt",
				"mismatch_reason": " | ".join(reasons) if reasons else "Mismatch detected",
				"purchase_receipt": pr_mismatch.get("purchase_receipt") if pr_mismatch else None,
				"purchase_invoice": pi_mismatch.get("purchase_invoice") if pi_mismatch else None
			})
	
	return mismatches or []


def check_si_pi_mismatch(si_name, si_items):
	"""
	Check if Sales Invoice has matching Purchase Invoice.
	
	Returns:
		dict: Mismatch information or None if no mismatch
	"""
	# Check if PI exists via bns_inter_company_reference (BNS internal transfers use this field)
	pi_name = frappe.db.get_value("Purchase Invoice", {"bns_inter_company_reference": si_name, "docstatus": 1}, "name")
	
	# Also check inter_company_invoice_reference for backward compatibility
	if not pi_name:
		pi_name = frappe.db.get_value("Purchase Invoice", {"inter_company_invoice_reference": si_name, "docstatus": 1}, "name")
	
	if not pi_name:
		return {
			"missing_doc": "Purchase Invoice",
			"reason": "No PI for SI",
			"purchase_invoice": None
		}
	
	# Check quantity mismatches
	missing_items = []
	qty_mismatches = []
	
	for si_item in si_items:
		si_item_name = si_item.get("name")
		si_qty = si_item.get("qty") or 0
		si_stock_qty = si_item.get("stock_qty") or 0
		
		# Find Purchase Invoice items linked to this SI item
		pi_item_query = """
			SELECT 
				pii.qty as pi_qty,
				pii.stock_qty as pi_stock_qty
			FROM `tabPurchase Invoice Item` pii
			WHERE pii.parent = %s
			AND pii.sales_invoice_item = %s
		"""
		
		try:
			pi_items = frappe.db.sql(pi_item_query, (pi_name, si_item_name), as_dict=True) or []
		except Exception as e:
			frappe.log_error(f"Error checking PI items for SI item {si_item_name}: {str(e)}")
			pi_items = []
		
		if not pi_items:
			missing_items.append({
				"item": si_item.get("item_code") or "",
				"si_qty": si_qty
			})
		else:
			# Aggregate quantities
			total_pi_qty = sum(item.get("pi_qty") or 0 for item in pi_items)
			total_pi_stock_qty = sum(item.get("pi_stock_qty") or 0 for item in pi_items)
			
			# Check quantity match
			if si_stock_qty > 0:
				if abs(si_stock_qty - total_pi_stock_qty) > 0.001:
					qty_mismatches.append({
						"item": si_item.get("item_code") or "",
						"si_qty": si_stock_qty,
						"pi_qty": total_pi_stock_qty
					})
			else:
				if abs(si_qty - total_pi_qty) > 0.001:
					qty_mismatches.append({
						"item": si_item.get("item_code") or "",
						"si_qty": si_qty,
						"pi_qty": total_pi_qty
					})
	
	if missing_items or qty_mismatches:
		all_mismatches = []
		for item in missing_items:
			all_mismatches.append(f"{item['item']} (SI: {item['si_qty']}, PI: Missing)")
		for mismatch in qty_mismatches:
			all_mismatches.append(f"{mismatch['item']} (SI: {mismatch['si_qty']}, PI: {mismatch['pi_qty']})")
		
		return {
			"missing_doc": "Purchase Invoice (Partial)" if missing_items else "Purchase Invoice (Qty Mismatch)",
			"reason": ", ".join(all_mismatches[:5]) + (f" and {len(all_mismatches) - 5} more items" if len(all_mismatches) > 5 else ""),
			"purchase_invoice": pi_name
		}
	
	return None


def check_si_pr_mismatch(si_name, si_items):
	"""
	Check if Sales Invoice has matching Purchase Receipt.
	Only checks if SI has stock items or was created from DN.
	
	Returns:
		dict: Mismatch information or None if no mismatch
	"""
	# Check if PR exists via supplier_delivery_note or bns_inter_company_reference
	pr_name = frappe.db.get_value("Purchase Receipt", 
		{"supplier_delivery_note": si_name, "docstatus": 1}, "name")
	
	if not pr_name:
		pr_name = frappe.db.get_value("Purchase Receipt", 
			{"bns_inter_company_reference": si_name, "docstatus": 1}, "name")
	
	if not pr_name:
		# Check if SI has stock items - if yes, PR should exist
		has_stock_items = False
		for si_item in si_items:
			item_code = si_item.get("item_code")
			if item_code:
				is_stock = frappe.db.get_value("Item", item_code, "is_stock_item")
				if is_stock:
					has_stock_items = True
					break
		
		# Also check if SI was created from DN
		has_dn_reference = any(item.get("delivery_note") for item in si_items if item.get("delivery_note"))
		
		if has_stock_items or has_dn_reference:
			return {
				"missing_doc": "Purchase Receipt",
				"reason": "No PR for SI",
				"purchase_receipt": None
			}
		else:
			# No stock items and not from DN, PR not required
			return None
	
	# Check quantity mismatches
	missing_items = []
	qty_mismatches = []
	
	for si_item in si_items:
		si_item_name = si_item.get("name")
		si_qty = si_item.get("qty") or 0
		si_stock_qty = si_item.get("stock_qty") or 0
		
		# Find Purchase Receipt items linked to this SI item
		# PR items reference SI via sales_invoice_item field (when created from SI)
		pr_item_query = """
			SELECT 
				pri.qty as pr_qty,
				pri.stock_qty as pr_stock_qty
			FROM `tabPurchase Receipt Item` pri
			WHERE pri.parent = %s
			AND (pri.sales_invoice_item = %s OR pri.delivery_note_item IN (
				SELECT name FROM `tabDelivery Note Item` WHERE si_detail = %s
			))
		"""
		
		try:
			pr_items = frappe.db.sql(pr_item_query, (pr_name, si_item_name, si_item_name), as_dict=True) or []
		except Exception as e:
			frappe.log_error(f"Error checking PR items for SI item {si_item_name}: {str(e)}")
			pr_items = []
		
		if not pr_items:
			missing_items.append({
				"item": si_item.get("item_code") or "",
				"si_qty": si_qty
			})
		else:
			# Aggregate quantities
			total_pr_qty = sum(item.get("pr_qty") or 0 for item in pr_items)
			total_pr_stock_qty = sum(item.get("pr_stock_qty") or 0 for item in pr_items)
			
			# Check quantity match
			if si_stock_qty > 0:
				if abs(si_stock_qty - total_pr_stock_qty) > 0.001:
					qty_mismatches.append({
						"item": si_item.get("item_code") or "",
						"si_qty": si_stock_qty,
						"pr_qty": total_pr_stock_qty
					})
			else:
				if abs(si_qty - total_pr_qty) > 0.001:
					qty_mismatches.append({
						"item": si_item.get("item_code") or "",
						"si_qty": si_qty,
						"pr_qty": total_pr_qty
					})
	
	if missing_items or qty_mismatches:
		all_mismatches = []
		for item in missing_items:
			all_mismatches.append(f"{item['item']} (SI: {item['si_qty']}, PR: Missing)")
		for mismatch in qty_mismatches:
			all_mismatches.append(f"{mismatch['item']} (SI: {mismatch['si_qty']}, PR: {mismatch['pr_qty']})")
		
		return {
			"missing_doc": "Purchase Receipt (Partial)" if missing_items else "Purchase Receipt (Qty Mismatch)",
			"reason": ", ".join(all_mismatches[:5]) + (f" and {len(all_mismatches) - 5} more items" if len(all_mismatches) > 5 else ""),
			"purchase_receipt": pr_name
		}
	
	return None
