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
   - Checks if Purchase Invoice exists via bns_inter_company_reference
   - Checks if quantities match between SI and PI items

"""

import frappe
from frappe import _
from frappe.utils import today, flt, getdate

# No tolerance: compare rounded values so matching SI-PI (e.g. after link_si_pi) are not falsely reported as mismatch.
# Amounts: round to 2 decimals; qty: round to 6 decimals. This avoids float representation noise without allowing any business tolerance.


def _amounts_equal(a, b):
	"""Compare amounts with no tolerance; round to 2 decimals."""
	return round(flt(a or 0), 2) == round(flt(b or 0), 2)


def _qtys_equal(a, b):
	"""Compare quantities with no tolerance; round to 6 decimals."""
	return round(flt(a or 0), 6) == round(flt(b or 0), 6)


@frappe.whitelist()
def company_address_query(doctype, txt, searchfield, start, page_len, filters):
	"""
	Query to fetch only company addresses for the report filter.
	"""
	conditions = ["is_company_address = 1"]
	values = []

	if txt:
		conditions.append(f"{searchfield} like %s")
		values.append(f"%{txt}%")

	# If company filter is provided, try to match via address title
	company = None
	if filters:
		company = filters.get("company")
		if company:
			conditions.append("address_title = %s")
			values.append(company)

	where_clause = " AND ".join(conditions)
	query = f"""
		SELECT
			name,
			IFNULL(address_title, name) AS address_title
		FROM `tabAddress`
		WHERE {where_clause}
		ORDER BY modified DESC
		LIMIT %s
		OFFSET %s
	"""
	values.extend([page_len, start])
	return frappe.db.sql(query, tuple(values))


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

	filters = _apply_cutoff_filters(filters)
	
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
			"fieldname": "company_address_name",
			"label": _("Company Address (Name)"),
			"fieldtype": "Data",
			"width": 180
		},
		{
			"fieldname": "customer_address_name",
			"label": _("Customer Address (Name)"),
			"fieldtype": "Data",
			"width": 180
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
		},
		{
			"fieldname": "transfer_chain",
			"label": _("Transfer Chain"),
			"fieldtype": "Data",
			"width": 140
		},
		{
			"fieldname": "source_destination_warehouse",
			"label": _("Source Dest. Warehouse"),
			"fieldtype": "Data",
			"width": 180
		},
		{
			"fieldname": "purchase_warehouse",
			"label": _("Purchase Warehouse"),
			"fieldtype": "Data",
			"width": 180
		},
		{
			"fieldname": "warehouse_mismatch",
			"label": _("Location Mismatch"),
			"fieldtype": "Data",
			"width": 250
		},
		{
			"fieldname": "item_mismatch_details",
			"label": _("Item Mismatch"),
			"fieldtype": "Data",
			"width": 250
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

	# Include orphan/invalid internal PR/PI rows based on linkage rules.
	internal_purchase_mismatch_data = get_internal_purchase_doc_linkage_mismatches(filters)
	data.extend(internal_purchase_mismatch_data)
	
	# Sort by posting date descending (handle None values)
	if data:
		data.sort(key=lambda x: x.get("posting_date") or today(), reverse=True)
	
	return data or []


def _get_internal_validation_cutoff_date():
	"""Read global posting-date cutoff from BNS Branch Accounting Settings."""
	cutoff = frappe.db.get_single_value(
		"BNS Branch Accounting Settings",
		"internal_validation_cutoff_date",
	)
	if not cutoff:
		return None
	try:
		return getdate(cutoff)
	except Exception:
		return None


def _apply_cutoff_filters(filters):
	"""Apply cutoff as default from_date when user has not provided one."""
	filters = frappe._dict(filters or {})
	if filters.get("from_date"):
		return filters
	cutoff = _get_internal_validation_cutoff_date()
	if cutoff:
		filters["from_date"] = cutoff
	return filters


def _link_flags_from_refs(*refs):
	"""Return link flags for DN/SI from given reference values."""
	seen = set()
	values = []
	for ref in refs:
		ref = (ref or "").strip()
		if ref and ref not in seen:
			seen.add(ref)
			values.append(ref)

	has_dn = any(frappe.db.exists("Delivery Note", ref) for ref in values)
	has_si = any(frappe.db.exists("Sales Invoice", ref) for ref in values)
	return has_dn, has_si


def _resolve_scope(company_gstin, billing_gstin, has_dn, has_si):
	company_gstin = (company_gstin or "").strip()
	billing_gstin = (billing_gstin or "").strip()
	if company_gstin and billing_gstin:
		return "same" if company_gstin == billing_gstin else "different"
	if has_dn and not has_si:
		return "same"
	if has_si and not has_dn:
		return "different"
	return None


def get_internal_purchase_doc_linkage_mismatches(filters=None):
	"""Find submitted internal PR/PI rows violating PR/PI linkage rules."""
	filters = frappe._dict(filters or {})
	data = []

	common_conditions = ["docstatus = 1", "is_bns_internal_supplier = 1"]
	common_values = []
	if filters.get("company"):
		common_conditions.append("company = %s")
		common_values.append(filters.get("company"))
	if filters.get("from_date"):
		common_conditions.append("posting_date >= %s")
		common_values.append(filters.get("from_date"))
	if filters.get("to_date"):
		common_conditions.append("posting_date <= %s")
		common_values.append(filters.get("to_date"))

	pr_rows = frappe.db.sql(
		f"""
		SELECT
			name, posting_date, grand_total, company, company_gstin, supplier_gstin,
			bns_inter_company_reference
		FROM `tabPurchase Receipt`
		WHERE {" AND ".join(common_conditions)}
		""",
		tuple(common_values),
		as_dict=True,
	) or []

	for pr in pr_rows:
		has_dn, has_si = _link_flags_from_refs(
			pr.get("bns_inter_company_reference"),
		)
		scope = _resolve_scope(
			pr.get("company_gstin"),
			pr.get("supplier_gstin"),
			has_dn,
			has_si,
		)

		reason = None
		if has_dn and has_si:
			reason = "PR linked to both DN and SI; only one source link is allowed."
		elif scope == "same" and (not has_dn or has_si):
			reason = "Same GSTIN internal PR must be linked to DN only."
		elif scope == "different" and (has_dn or not has_si):
			reason = "Different GSTIN internal PR must be linked to SI only (DN link not allowed)."
		elif scope is None and not has_dn and not has_si:
			reason = "PR has no source link; expected DN (same GSTIN) or SI (different GSTIN)."

		if reason:
			data.append(
				{
					"posting_date": pr.get("posting_date") or None,
					"document_type": "Purchase Receipt",
					"document_name": pr.get("name"),
					"grand_total": pr.get("grand_total") or 0.0,
					"company_address_name": "",
					"customer_address_name": "",
					"missing_document": "Source Link (DN/SI)",
					"mismatch_reason": reason,
					"purchase_receipt": pr.get("name"),
					"purchase_invoice": None,
					"transfer_chain": "",
					"source_destination_warehouse": "",
					"purchase_warehouse": "",
					"warehouse_mismatch": "",
					"item_mismatch_details": "",
				}
			)

	pi_rows = frappe.db.sql(
		f"""
		SELECT
			name, posting_date, grand_total, company, company_gstin, supplier_gstin,
			bns_inter_company_reference
		FROM `tabPurchase Invoice`
		WHERE {" AND ".join(common_conditions)}
		""",
		tuple(common_values),
		as_dict=True,
	) or []

	for pi in pi_rows:
		company_gstin = (pi.get("company_gstin") or "").strip()
		billing_gstin = (pi.get("supplier_gstin") or "").strip()
		if not (company_gstin and billing_gstin and company_gstin != billing_gstin):
			continue

		_, has_si_direct = _link_flags_from_refs(pi.get("bns_inter_company_reference"))

		pr_names = frappe.get_all(
			"Purchase Invoice Item",
			filters={"parent": pi.get("name")},
			pluck="purchase_receipt",
		) or []
		pr_names = sorted({(name or "").strip() for name in pr_names if name})

		has_valid_pr_link = False
		for pr_name in pr_names:
			pr_link = frappe.db.get_value(
				"Purchase Receipt",
				pr_name,
				["bns_inter_company_reference"],
				as_dict=True,
			)
			if not pr_link:
				continue
			pr_has_dn, pr_has_si = _link_flags_from_refs(
				pr_link.get("bns_inter_company_reference"),
			)
			if pr_has_si and not pr_has_dn:
				has_valid_pr_link = True
				break

		if has_si_direct or has_valid_pr_link:
			continue

		data.append(
			{
				"posting_date": pi.get("posting_date") or None,
				"document_type": "Purchase Invoice",
				"document_name": pi.get("name"),
				"grand_total": pi.get("grand_total") or 0.0,
				"company_address_name": "",
				"customer_address_name": "",
				"missing_document": "Sales Invoice / SI-linked PR",
				"mismatch_reason": "Different GSTIN internal PI is standalone/unlinked; must link to SI directly or via SI-linked PR.",
				"purchase_receipt": None,
				"purchase_invoice": pi.get("name"),
				"transfer_chain": "",
				"source_destination_warehouse": "",
				"purchase_warehouse": "",
				"warehouse_mismatch": "",
				"item_mismatch_details": "",
			}
		)

	return data


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
		
		if filters.get("company_address"):
			conditions.append("dn.company_address = %s")
			values.append(filters.company_address)
		
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
			dn.grand_total,
			dn.company_address as company_address_name,
			dn.customer_address as customer_address_name
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
		
		# Get all Delivery Note items with taxable values
		dn_items_query = """
		SELECT 
			name,
			item_code,
			qty,
			stock_qty,
			net_amount,
			base_net_amount,
			target_warehouse,
			warehouse
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
		
		# Get DN document for totals and taxes
		dn_doc = frappe.get_doc("Delivery Note", dn_name)
		dn_grand_total = flt(dn_doc.grand_total or 0)
		dn_total_taxes = flt(dn_doc.total_taxes_and_charges or 0)
		dn_net_total = flt(dn_doc.net_total or 0)
		
		# Check each DN item against PR items
		missing_items = []
		qty_mismatches = []
		taxable_value_mismatches = []
		warehouse_mismatches = []
		item_code_mismatches = []
		dn_dest_warehouses = set()
		pr_recv_warehouses = set()
		matched_prs = set()
		pr_grand_total = 0
		pr_total_taxes = 0
		pr_net_total = 0
		
		for dn_item in dn_items:
			dn_item_name = dn_item.get("name")
			dn_qty = flt(dn_item.get("qty") or 0)
			dn_stock_qty = flt(dn_item.get("stock_qty") or 0)
			dn_net_amount = flt(dn_item.get("net_amount") or 0)
			dn_base_net_amount = flt(dn_item.get("base_net_amount") or 0)
			
			# Find Purchase Receipt items linked to this DN item
			pr_item_query = """
			SELECT 
				pri.parent as pr_name,
				pri.item_code as pr_item_code,
				pri.qty as pr_qty,
				pri.stock_qty as pr_stock_qty,
				pri.net_amount as pr_net_amount,
				pri.base_net_amount as pr_base_net_amount,
				pri.warehouse as pr_warehouse,
				pr.docstatus,
				pr.grand_total,
				pr.total_taxes_and_charges,
				pr.net_total
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
					"dn_qty": dn_qty,
					"dn_taxable_value": dn_base_net_amount if dn_base_net_amount > 0 else dn_net_amount
				})
			else:
				# Aggregate quantities and taxable values from all PRs for this DN item
				total_pr_qty = 0
				total_pr_stock_qty = 0
				total_pr_net_amount = 0
				total_pr_base_net_amount = 0
				pr_names_for_item = []
				
				for pr_item in pr_items:
					pr_name = pr_item.get("pr_name")
					pr_qty = flt(pr_item.get("pr_qty") or 0)
					pr_stock_qty = flt(pr_item.get("pr_stock_qty") or 0)
					pr_net_amount = flt(pr_item.get("pr_net_amount") or 0)
					pr_base_net_amount = flt(pr_item.get("pr_base_net_amount") or 0)
					
					# Store PR totals (use first PR's totals)
					if not matched_prs:
						pr_grand_total = flt(pr_item.get("grand_total") or 0)
						pr_total_taxes = flt(pr_item.get("total_taxes_and_charges") or 0)
						pr_net_total = flt(pr_item.get("net_total") or 0)
					
					matched_prs.add(pr_name)
					pr_names_for_item.append(pr_name)
					total_pr_qty += pr_qty
					total_pr_stock_qty += pr_stock_qty
					total_pr_net_amount += pr_net_amount
					total_pr_base_net_amount += pr_base_net_amount
				
				# Check if aggregated quantities match DN quantity
				# Use stock_qty if available, else qty
				if dn_stock_qty > 0:
					if abs(dn_stock_qty - total_pr_stock_qty) > 0.01:  # Allow difference of 0.01
						qty_mismatches.append({
							"item": dn_item.get("item_code") or "",
							"pr": ", ".join(pr_names_for_item[:3]),  # Show up to 3 PR names
							"dn_qty": dn_stock_qty,
							"pr_qty": total_pr_stock_qty
						})
				else:
					if abs(dn_qty - total_pr_qty) > 0.01:  # Allow difference of 0.01
						qty_mismatches.append({
							"item": dn_item.get("item_code") or "",
							"pr": ", ".join(pr_names_for_item[:3]),  # Show up to 3 PR names
							"dn_qty": dn_qty,
							"pr_qty": total_pr_qty
						})
				
				# Check taxable value mismatch
				dn_taxable_value = dn_base_net_amount if dn_base_net_amount > 0 else dn_net_amount
				pr_taxable_value = total_pr_base_net_amount if total_pr_base_net_amount > 0 else total_pr_net_amount
				if abs(dn_taxable_value - pr_taxable_value) > 5.0:  # Allow difference of ₹5
					taxable_value_mismatches.append({
						"item": dn_item.get("item_code") or "",
						"dn_taxable_value": dn_taxable_value,
						"pr_taxable_value": pr_taxable_value
					})

				# Track warehouse and item code mismatches
				dn_dest_wh = (dn_item.get("target_warehouse") or dn_item.get("warehouse") or "").strip()
				if dn_dest_wh:
					dn_dest_warehouses.add(dn_dest_wh)
				for pr_item in pr_items:
					pr_wh = (pr_item.get("pr_warehouse") or "").strip()
					if pr_wh:
						pr_recv_warehouses.add(pr_wh)
					if dn_dest_wh and pr_wh and dn_dest_wh != pr_wh:
						warehouse_mismatches.append({
							"item": dn_item.get("item_code") or "",
							"dn_warehouse": dn_dest_wh,
							"pr_warehouse": pr_wh,
						})
					pr_ic = (pr_item.get("pr_item_code") or "").strip()
					dn_ic = (dn_item.get("item_code") or "").strip()
					if pr_ic and dn_ic and pr_ic != dn_ic:
						item_code_mismatches.append({
							"dn_item_code": dn_ic,
							"pr_item_code": pr_ic,
						})
		
		# Check grand total and tax mismatches
		grand_total_mismatch = None
		tax_mismatch = None
		
		if matched_prs:
			# Get consolidated PR totals (sum all PRs)
			pr_totals_query = """
			SELECT 
				SUM(grand_total) as total_grand_total,
				SUM(total_taxes_and_charges) as total_taxes,
				SUM(base_total_taxes_and_charges) as base_total_taxes,
				SUM(net_total) as total_net_total
			FROM `tabPurchase Receipt`
			WHERE name IN ({})
			AND docstatus = 1
			""".format(",".join(["%s"] * len(matched_prs)))
			
			try:
				pr_totals = frappe.db.sql(pr_totals_query, tuple(matched_prs), as_dict=True)
				if pr_totals and pr_totals[0]:
					pr_grand_total = flt(pr_totals[0].get("total_grand_total") or 0)
					pr_total_taxes = flt(pr_totals[0].get("total_taxes") or 0)
					pr_base_taxes = flt(pr_totals[0].get("base_total_taxes") or 0)
					pr_net_total = flt(pr_totals[0].get("total_net_total") or 0)
					
					# Compare grand totals
					if abs(dn_grand_total - pr_grand_total) > 5.0:  # Allow difference of ₹5
						grand_total_mismatch = {
							"dn_total": dn_grand_total,
							"pr_total": pr_grand_total,
							"diff": dn_grand_total - pr_grand_total
						}
					
					# Compare taxes (in company currency - base_total_taxes_and_charges)
					dn_base_taxes = flt(dn_doc.base_total_taxes_and_charges or 0)
					if dn_base_taxes == 0:
						# Fallback to total_taxes_and_charges if base not available
						dn_base_taxes = dn_total_taxes
					if pr_base_taxes == 0:
						# Fallback to total_taxes_and_charges if base not available
						pr_base_taxes = pr_total_taxes
					
					if abs(dn_base_taxes - pr_base_taxes) > 0.01:
						tax_mismatch = {
							"dn_tax": dn_base_taxes,
							"pr_tax": pr_base_taxes,
							"diff": dn_base_taxes - pr_base_taxes
						}
			except Exception as e:
				frappe.log_error(f"Error checking PR totals for DN {dn_name}: {str(e)}")
		
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
			
			# Combine all mismatches
			all_mismatches = []
			
			# Add missing items
			for item in missing_items:
				all_mismatches.append({
					"item": item['item'],
					"dn_qty": item['dn_qty'],
					"pr_qty": 0,
					"type": "missing",
					"taxable_value_info": f"Taxable Value: ₹{item.get('dn_taxable_value', 0):.2f}"
				})
			
			# Add quantity mismatches
			for mismatch in qty_mismatches:
				all_mismatches.append({
					"item": mismatch['item'],
					"dn_qty": mismatch['dn_qty'],
					"pr_qty": mismatch['pr_qty'],
					"type": "qty_mismatch"
				})
			
			# Add taxable value mismatches
			for mismatch in taxable_value_mismatches:
				all_mismatches.append({
					"item": mismatch['item'],
					"dn_taxable_value": mismatch['dn_taxable_value'],
					"pr_taxable_value": mismatch['pr_taxable_value'],
					"type": "taxable_value_mismatch"
				})
			
			# Build mismatch reason string
			mismatch_parts = []
			
			if all_mismatches:
				# Show item-wise differences
				for m in all_mismatches[:5]:  # Show up to 5 items
					if m['type'] == "missing":
						taxable_value_info = f" ({m.get('taxable_value_info', '')})" if m.get('taxable_value_info') else ""
						mismatch_parts.append(f"{m['item']} (DN Qty: {m['dn_qty']}, PR: Missing{taxable_value_info})")
					elif m['type'] == "qty_mismatch":
						mismatch_parts.append(f"{m['item']} (DN Qty: {m['dn_qty']}, PR Qty: {m['pr_qty']})")
					elif m['type'] == "taxable_value_mismatch":
						mismatch_parts.append(f"{m['item']} (DN Taxable Value: ₹{m['dn_taxable_value']:.2f}, PR Taxable Value: ₹{m['pr_taxable_value']:.2f})")
				
				if len(all_mismatches) > 5:
					mismatch_parts.append(f"and {len(all_mismatches) - 5} more items")
			
			# Add grand total mismatch
			if grand_total_mismatch:
				mismatch_parts.append(f"Grand Total: DN ₹{grand_total_mismatch['dn_total']:.2f} vs PR ₹{grand_total_mismatch['pr_total']:.2f} (Diff: ₹{abs(grand_total_mismatch['diff']):.2f})")
			
			# Add tax mismatch (Total Taxes and Charges in company currency)
			if tax_mismatch:
				mismatch_parts.append(f"Total Taxes and Charges: DN ₹{tax_mismatch['dn_tax']:.2f} vs PR ₹{tax_mismatch['pr_tax']:.2f} (Diff: ₹{abs(tax_mismatch['diff']):.2f})")
			
			if mismatch_parts:
				mismatch_reason = " | ".join(mismatch_parts)
				missing_doc = "Purchase Receipt (Mismatch)"
			else:
				# No mismatch found, skip this DN
				continue
		
		# Build warehouse and item mismatch summary strings
		wh_mismatch_str = ""
		if warehouse_mismatches:
			wh_parts = []
			for wm in warehouse_mismatches[:3]:
				wh_parts.append(f"{wm['item']}: DN={wm['dn_warehouse']}, PR={wm['pr_warehouse']}")
			if len(warehouse_mismatches) > 3:
				wh_parts.append(f"... +{len(warehouse_mismatches) - 3} more")
			wh_mismatch_str = " | ".join(wh_parts)

		item_mismatch_str = ""
		if item_code_mismatches:
			im_parts = []
			for im in item_code_mismatches[:3]:
				im_parts.append(f"DN={im['dn_item_code']}, PR={im['pr_item_code']}")
			if len(item_code_mismatches) > 3:
				im_parts.append(f"... +{len(item_code_mismatches) - 3} more")
			item_mismatch_str = " | ".join(im_parts)

		mismatches.append({
			"posting_date": dn.get("posting_date") or None,
			"document_type": "Delivery Note",
			"document_name": dn_name,
			"grand_total": dn.get("grand_total") or 0.0,
			"company_address_name": dn.get("company_address_name") or "",
			"customer_address_name": dn.get("customer_address_name") or "",
			"missing_document": missing_doc,
			"mismatch_reason": mismatch_reason,
			"purchase_receipt": purchase_receipt,
			"purchase_invoice": None,
			"transfer_chain": "DN->PR",
			"source_destination_warehouse": ", ".join(sorted(dn_dest_warehouses)) if dn_dest_warehouses else "",
			"purchase_warehouse": ", ".join(sorted(pr_recv_warehouses)) if pr_recv_warehouses else "",
			"warehouse_mismatch": wh_mismatch_str,
			"item_mismatch_details": item_mismatch_str,
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
		
		if filters.get("company_address"):
			conditions.append("si.company_address = %s")
			values.append(filters.company_address)
		
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
			si.grand_total,
			si.company_address as company_address_name,
			si.customer_address as customer_address_name
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
		
		# Get all Sales Invoice items with taxable values
		si_items_query = """
		SELECT 
			name,
			item_code,
			qty,
			stock_qty,
			net_amount,
			base_net_amount,
			warehouse,
			delivery_note
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
		
		# Get Sales Invoice document for totals and taxes
		si_doc = frappe.get_doc("Sales Invoice", si_name)
		
		# Determine chain type: SI->PI or SI->PR->PI
		has_dn_ref = any((item.get("delivery_note") or "").strip() for item in si_items)
		si_pr_ref = ""
		if si_doc.meta.has_field("bns_purchase_receipt_reference"):
			si_pr_ref = (si_doc.get("bns_purchase_receipt_reference") or "").strip()
		si_pi_ref = (si_doc.get("bns_inter_company_reference") or "").strip()

		if si_pr_ref and frappe.db.exists("Purchase Receipt", si_pr_ref):
			chain_type = "DN->SI->PR->PI" if has_dn_ref else "SI->PR->PI"
		elif si_pi_ref and frappe.db.exists("Purchase Invoice", si_pi_ref):
			chain_type = "DN->SI->PI" if has_dn_ref else "SI->PI"
		else:
			chain_type = "DN->SI->PI" if has_dn_ref else "SI->PI"

		# Check for Purchase Invoice mismatch
		pi_mismatch = check_si_pi_mismatch(si_name, si_items, si_doc)
		
		# Also check SI->PR->PI chain for PR mismatch
		pr_mismatch_info = _check_si_pr_chain_mismatch(si_name, si_items, si_pr_ref)

		si_warehouses = set()
		for item in si_items:
			wh = (item.get("warehouse") or "").strip()
			if wh:
				si_warehouses.add(wh)

		if pi_mismatch:
			mismatches.append({
				"posting_date": si.get("posting_date") or None,
				"document_type": "Sales Invoice",
				"document_name": si_name,
				"grand_total": si.get("grand_total") or 0.0,
				"company_address_name": si.get("company_address_name") or "",
				"customer_address_name": si.get("customer_address_name") or "",
				"missing_document": pi_mismatch.get("missing_doc", "Purchase Invoice"),
				"mismatch_reason": pi_mismatch.get("reason", "No PI for SI"),
				"purchase_receipt": pi_mismatch.get("purchase_receipt") or (si_pr_ref if si_pr_ref else None),
				"purchase_invoice": pi_mismatch.get("purchase_invoice"),
				"transfer_chain": chain_type,
				"source_destination_warehouse": ", ".join(sorted(si_warehouses)) if si_warehouses else "",
				"purchase_warehouse": pi_mismatch.get("purchase_warehouse", ""),
				"warehouse_mismatch": pi_mismatch.get("warehouse_mismatch", ""),
				"item_mismatch_details": pi_mismatch.get("item_mismatch_details", ""),
			})
		elif pr_mismatch_info:
			mismatches.append({
				"posting_date": si.get("posting_date") or None,
				"document_type": "Sales Invoice",
				"document_name": si_name,
				"grand_total": si.get("grand_total") or 0.0,
				"company_address_name": si.get("company_address_name") or "",
				"customer_address_name": si.get("customer_address_name") or "",
				"missing_document": pr_mismatch_info.get("missing_doc", "Purchase Receipt"),
				"mismatch_reason": pr_mismatch_info.get("reason", ""),
				"purchase_receipt": si_pr_ref or None,
				"purchase_invoice": None,
				"transfer_chain": chain_type,
				"source_destination_warehouse": ", ".join(sorted(si_warehouses)) if si_warehouses else "",
				"purchase_warehouse": pr_mismatch_info.get("purchase_warehouse", ""),
				"warehouse_mismatch": pr_mismatch_info.get("warehouse_mismatch", ""),
				"item_mismatch_details": pr_mismatch_info.get("item_mismatch_details", ""),
			})
	
	return mismatches or []


def _check_si_pr_chain_mismatch(si_name, si_items, si_pr_ref):
	"""
	Check SI->PR chain for warehouse and item mismatches.

	Args:
		si_name: Sales Invoice name
		si_items: SI item rows
		si_pr_ref: bns_purchase_receipt_reference value

	Returns:
		dict with mismatch info or None
	"""
	if not si_pr_ref or not frappe.db.exists("Purchase Receipt", si_pr_ref):
		return None

	pr_items = frappe.db.sql(
		"""
		SELECT item_code, qty, stock_qty, warehouse
		FROM `tabPurchase Receipt Item`
		WHERE parent = %s
		""",
		(si_pr_ref,),
		as_dict=True,
	) or []

	if not pr_items:
		return None

	si_agg = {}
	for sii in si_items:
		ic = (sii.get("item_code") or "").strip()
		if ic:
			si_agg.setdefault(ic, 0)
			si_agg[ic] += flt(sii.get("stock_qty") or sii.get("qty") or 0)

	pr_agg = {}
	pr_warehouses = set()
	for pri in pr_items:
		ic = (pri.get("item_code") or "").strip()
		wh = (pri.get("warehouse") or "").strip()
		if ic:
			pr_agg.setdefault(ic, 0)
			pr_agg[ic] += flt(pri.get("stock_qty") or pri.get("qty") or 0)
		if wh:
			pr_warehouses.add(wh)

	si_warehouses = set()
	for sii in si_items:
		wh = (sii.get("warehouse") or "").strip()
		if wh:
			si_warehouses.add(wh)

	wh_mismatches = []
	item_mismatches = []
	qty_mismatches = []

	for ic, si_qty in si_agg.items():
		pr_qty = pr_agg.get(ic, 0)
		if not _qtys_equal(si_qty, pr_qty):
			if pr_qty == 0:
				item_mismatches.append(f"SI has {ic}, PR missing")
			else:
				qty_mismatches.append(f"{ic}: SI={si_qty}, PR={pr_qty}")

	for ic in pr_agg:
		if ic not in si_agg:
			item_mismatches.append(f"PR has extra {ic}")

	if si_warehouses and pr_warehouses and si_warehouses != pr_warehouses:
		si_wh_str = ", ".join(sorted(si_warehouses))
		pr_wh_str = ", ".join(sorted(pr_warehouses))
		wh_mismatches.append(f"SI={si_wh_str}, PR={pr_wh_str}")

	if not qty_mismatches and not item_mismatches and not wh_mismatches:
		return None

	parts = qty_mismatches + item_mismatches
	return {
		"missing_doc": "Purchase Receipt (Mismatch)",
		"reason": " | ".join(parts[:5]) if parts else "Warehouse mismatch only",
		"purchase_warehouse": ", ".join(sorted(pr_warehouses)) if pr_warehouses else "",
		"warehouse_mismatch": " | ".join(wh_mismatches) if wh_mismatches else "",
		"item_mismatch_details": " | ".join(item_mismatches[:3]) if item_mismatches else "",
	}


def check_si_pi_mismatch(si_name, si_items, si_doc):
	"""
	Check if Sales Invoice has matching Purchase Invoice.
	Compares quantities, taxable values, grand totals, and total taxes.
	
	Returns:
		dict: Mismatch information or None if no mismatch
	"""
	# Check if PI exists via bns_inter_company_reference (BNS internal transfers use this field)
	pi_name = frappe.db.get_value("Purchase Invoice", {"bns_inter_company_reference": si_name, "docstatus": 1}, "name")
	
	if not pi_name:
		return {
			"missing_doc": "Purchase Invoice",
			"reason": "No PI for SI",
			"purchase_invoice": None
		}
	
	# Get PI document for totals and taxes
	pi_doc = frappe.get_doc("Purchase Invoice", pi_name)
	pi_grand_total = flt(pi_doc.grand_total or 0)
	pi_total_taxes = flt(pi_doc.total_taxes_and_charges or 0)
	pi_base_taxes = flt(pi_doc.base_total_taxes_and_charges or 0)
	pi_net_total = flt(pi_doc.net_total or 0)
	
	# Check quantity, taxable value, and item mismatches
	missing_items = []
	qty_mismatches = []
	taxable_value_mismatches = []
	extra_items = []
	warehouse_mismatches_pi = []
	item_code_mismatches_pi = []
	si_warehouses_set = set()
	pi_warehouses_set = set()
	
	# Track which PI items are matched
	matched_pi_items = set()
	
	for si_item in si_items:
		si_item_name = si_item.get("name")
		si_qty = flt(si_item.get("qty") or 0)
		si_stock_qty = flt(si_item.get("stock_qty") or 0)
		si_net_amount = flt(si_item.get("net_amount") or 0)
		si_base_net_amount = flt(si_item.get("base_net_amount") or 0)
		
		# Find Purchase Invoice items linked to this SI item
		pi_item_query = """
		SELECT 
			pii.name,
			pii.item_code as pi_item_code,
			pii.qty as pi_qty,
			pii.stock_qty as pi_stock_qty,
			pii.net_amount as pi_net_amount,
			pii.base_net_amount as pi_base_net_amount,
			pii.warehouse as pi_warehouse
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
				"si_qty": si_qty,
				"si_taxable_value": si_base_net_amount if si_base_net_amount > 0 else si_net_amount
			})
		else:
			# Aggregate quantities and taxable values
			total_pi_qty = 0
			total_pi_stock_qty = 0
			total_pi_net_amount = 0
			total_pi_base_net_amount = 0
			
			for pi_item in pi_items:
				matched_pi_items.add(pi_item.get("name"))
				total_pi_qty += flt(pi_item.get("pi_qty") or 0)
				total_pi_stock_qty += flt(pi_item.get("pi_stock_qty") or 0)
				total_pi_net_amount += flt(pi_item.get("pi_net_amount") or 0)
				total_pi_base_net_amount += flt(pi_item.get("pi_base_net_amount") or 0)
			
			# Check quantity match (no tolerance; rounded comparison)
			if si_stock_qty > 0:
				if not _qtys_equal(si_stock_qty, total_pi_stock_qty):
					qty_mismatches.append({
						"item": si_item.get("item_code") or "",
						"si_qty": si_stock_qty,
						"pi_qty": total_pi_stock_qty
					})
			else:
				if not _qtys_equal(si_qty, total_pi_qty):
					qty_mismatches.append({
						"item": si_item.get("item_code") or "",
						"si_qty": si_qty,
						"pi_qty": total_pi_qty
					})
			
			# Check taxable value mismatch (no tolerance; rounded comparison)
			si_taxable_value = si_base_net_amount if si_base_net_amount > 0 else si_net_amount
			pi_taxable_value = total_pi_base_net_amount if total_pi_base_net_amount > 0 else total_pi_net_amount
			if not _amounts_equal(si_taxable_value, pi_taxable_value):
				taxable_value_mismatches.append({
					"item": si_item.get("item_code") or "",
					"si_taxable_value": si_taxable_value,
					"pi_taxable_value": pi_taxable_value
				})

			# Track warehouse and item code mismatches
			si_wh = (si_item.get("warehouse") or "").strip()
			if si_wh:
				si_warehouses_set.add(si_wh)
			for pi_item in pi_items:
				pi_wh = (pi_item.get("pi_warehouse") or "").strip()
				if pi_wh:
					pi_warehouses_set.add(pi_wh)
				if si_wh and pi_wh and si_wh != pi_wh:
					warehouse_mismatches_pi.append({
						"item": si_item.get("item_code") or "",
						"si_warehouse": si_wh,
						"pi_warehouse": pi_wh,
					})
				pi_ic = (pi_item.get("pi_item_code") or "").strip()
				si_ic = (si_item.get("item_code") or "").strip()
				if pi_ic and si_ic and pi_ic != si_ic:
					item_code_mismatches_pi.append({
						"si_item_code": si_ic,
						"pi_item_code": pi_ic,
					})
	
	# Check for extra items in PI (not linked to any SI item)
	all_pi_items_query = """
	SELECT 
		pii.name,
		pii.item_code,
		pii.qty,
		pii.net_amount,
		pii.base_net_amount
	FROM `tabPurchase Invoice Item` pii
	WHERE pii.parent = %s
	"""
	try:
		all_pi_items = frappe.db.sql(all_pi_items_query, (pi_name,), as_dict=True) or []
		for pi_item in all_pi_items:
			if pi_item.get("name") not in matched_pi_items:
				pi_taxable_value = flt(pi_item.get("base_net_amount") or 0) if flt(pi_item.get("base_net_amount") or 0) > 0 else flt(pi_item.get("net_amount") or 0)
				extra_items.append({
					"item": pi_item.get("item_code") or "",
					"pi_qty": flt(pi_item.get("qty") or 0),
					"pi_taxable_value": pi_taxable_value
				})
	except Exception as e:
		frappe.log_error(f"Error checking extra PI items: {str(e)}")
	
	# Check grand total mismatch (no tolerance; rounded comparison)
	grand_total_mismatch = None
	if not _amounts_equal(si_doc.grand_total, pi_grand_total):
		grand_total_mismatch = {
			"si_total": flt(si_doc.grand_total or 0),
			"pi_total": pi_grand_total,
			"diff": flt(si_doc.grand_total or 0) - pi_grand_total
		}
	
	# Check tax mismatch (compare in company currency - base_total_taxes_and_charges; no tolerance)
	tax_mismatch = None
	si_base_taxes = flt(si_doc.base_total_taxes_and_charges or 0)
	if si_base_taxes == 0:
		si_base_taxes = flt(si_doc.total_taxes_and_charges or 0)
	if pi_base_taxes == 0:
		pi_base_taxes = pi_total_taxes
	
	if not _amounts_equal(si_base_taxes, pi_base_taxes):
		tax_mismatch = {
			"si_tax": si_base_taxes,
			"pi_tax": pi_base_taxes,
			"diff": si_base_taxes - pi_base_taxes
		}

	# Fallback: when item-level linking is incomplete (missing/extra items) but no qty/taxable mismatch,
	# compare by aggregated item_code totals. Ensures explicitly linked SI-PI (e.g. via link_si_pi) with
	# matching items/qty/taxable value are not falsely reported as mismatch.
	if (missing_items or extra_items) and not qty_mismatches and not taxable_value_mismatches:
		all_pi_items_for_agg = frappe.db.sql(all_pi_items_query, (pi_name,), as_dict=True) or []
		if all_pi_items_for_agg:
			si_agg = {}
			for si_item in si_items:
				ic = si_item.get("item_code") or ""
				q = flt(si_item.get("qty") or 0)
				sq = flt(si_item.get("stock_qty") or q)
				na = flt(si_item.get("net_amount") or 0)
				bna = flt(si_item.get("base_net_amount") or 0)
				if ic not in si_agg:
					si_agg[ic] = {"qty": 0, "stock_qty": 0, "net_amount": 0, "base_net_amount": 0}
				si_agg[ic]["qty"] += q
				si_agg[ic]["stock_qty"] += sq
				si_agg[ic]["net_amount"] += na
				si_agg[ic]["base_net_amount"] += bna
			pi_agg = {}
			for pi_item in all_pi_items_for_agg:
				ic = pi_item.get("item_code") or ""
				q = flt(pi_item.get("qty") or 0)
				na = flt(pi_item.get("net_amount") or 0)
				bna = flt(pi_item.get("base_net_amount") or 0)
				if ic not in pi_agg:
					pi_agg[ic] = {"qty": 0, "net_amount": 0, "base_net_amount": 0}
				pi_agg[ic]["qty"] += q
				pi_agg[ic]["net_amount"] += na
				pi_agg[ic]["base_net_amount"] += bna
			agg_match = True
			for ic, s in si_agg.items():
				if ic not in pi_agg:
					agg_match = False
					break
				p = pi_agg[ic]
				if not _qtys_equal(s["qty"], p["qty"]):
					agg_match = False
					break
				sv = s["base_net_amount"] if s["base_net_amount"] > 0 else s["net_amount"]
				pv = p["base_net_amount"] if p["base_net_amount"] > 0 else p["net_amount"]
				if not _amounts_equal(sv, pv):
					agg_match = False
					break
			for ic in pi_agg:
				if ic not in si_agg:
					agg_match = False
					break
			if agg_match and not grand_total_mismatch and not tax_mismatch:
				return None

	# Build mismatch reason
	if missing_items or qty_mismatches or taxable_value_mismatches or extra_items or grand_total_mismatch or tax_mismatch:
		all_mismatches = []
		
		# Add missing items
		for item in missing_items:
			all_mismatches.append(f"{item['item']} (SI Qty: {item['si_qty']}, Taxable Value: ₹{item['si_taxable_value']:.2f}, PI: Missing)")
		
		# Add quantity mismatches
		for mismatch in qty_mismatches:
			all_mismatches.append(f"{mismatch['item']} (SI Qty: {mismatch['si_qty']}, PI Qty: {mismatch['pi_qty']})")
		
		# Add taxable value mismatches
		for mismatch in taxable_value_mismatches:
			all_mismatches.append(f"{mismatch['item']} (SI Taxable Value: ₹{mismatch['si_taxable_value']:.2f}, PI Taxable Value: ₹{mismatch['pi_taxable_value']:.2f})")
		
		# Add extra items
		for item in extra_items:
			all_mismatches.append(f"{item['item']} (Extra in PI: Qty {item['pi_qty']}, Taxable Value ₹{item['pi_taxable_value']:.2f})")
		
		# Add grand total mismatch
		if grand_total_mismatch:
			all_mismatches.append(f"Grand Total: SI ₹{grand_total_mismatch['si_total']:.2f} vs PI ₹{grand_total_mismatch['pi_total']:.2f} (Diff: ₹{abs(grand_total_mismatch['diff']):.2f})")
		
		# Add tax mismatch (Total Taxes and Charges in company currency)
		if tax_mismatch:
			all_mismatches.append(f"Total Taxes and Charges: SI ₹{tax_mismatch['si_tax']:.2f} vs PI ₹{tax_mismatch['pi_tax']:.2f} (Diff: ₹{abs(tax_mismatch['diff']):.2f})")
		
		# Build warehouse mismatch string
		wh_mismatch_str = ""
		if warehouse_mismatches_pi:
			wh_parts = []
			for wm in warehouse_mismatches_pi[:3]:
				wh_parts.append(f"{wm['item']}: SI={wm['si_warehouse']}, PI={wm['pi_warehouse']}")
			if len(warehouse_mismatches_pi) > 3:
				wh_parts.append(f"... +{len(warehouse_mismatches_pi) - 3} more")
			wh_mismatch_str = " | ".join(wh_parts)

		item_mismatch_str = ""
		if item_code_mismatches_pi:
			im_parts = []
			for im in item_code_mismatches_pi[:3]:
				im_parts.append(f"SI={im['si_item_code']}, PI={im['pi_item_code']}")
			if len(item_code_mismatches_pi) > 3:
				im_parts.append(f"... +{len(item_code_mismatches_pi) - 3} more")
			item_mismatch_str = " | ".join(im_parts)

		return {
			"missing_doc": "Purchase Invoice (Mismatch)",
			"reason": " | ".join(all_mismatches[:8]) + (f" | ... and {len(all_mismatches) - 8} more" if len(all_mismatches) > 8 else ""),
			"purchase_invoice": pi_name,
			"purchase_warehouse": ", ".join(sorted(pi_warehouses_set)) if pi_warehouses_set else "",
			"warehouse_mismatch": wh_mismatch_str,
			"item_mismatch_details": item_mismatch_str,
		}
	
	# No quantity/value mismatches, but check for warehouse or item code mismatches only
	if warehouse_mismatches_pi or item_code_mismatches_pi:
		wh_mismatch_str = ""
		if warehouse_mismatches_pi:
			wh_parts = []
			for wm in warehouse_mismatches_pi[:3]:
				wh_parts.append(f"{wm['item']}: SI={wm['si_warehouse']}, PI={wm['pi_warehouse']}")
			wh_mismatch_str = " | ".join(wh_parts)

		item_mismatch_str = ""
		if item_code_mismatches_pi:
			im_parts = []
			for im in item_code_mismatches_pi[:3]:
				im_parts.append(f"SI={im['si_item_code']}, PI={im['pi_item_code']}")
			item_mismatch_str = " | ".join(im_parts)

		reason_parts = []
		if wh_mismatch_str:
			reason_parts.append(f"Location: {wh_mismatch_str}")
		if item_mismatch_str:
			reason_parts.append(f"Item: {item_mismatch_str}")

		return {
			"missing_doc": "Purchase Invoice (Location/Item Mismatch)",
			"reason": " | ".join(reason_parts),
			"purchase_invoice": pi_name,
			"purchase_warehouse": ", ".join(sorted(pi_warehouses_set)) if pi_warehouses_set else "",
			"warehouse_mismatch": wh_mismatch_str,
			"item_mismatch_details": item_mismatch_str,
		}

	return None


