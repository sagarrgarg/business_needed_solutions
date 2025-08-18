import frappe
from frappe import _
from datetime import timedelta
import json


def execute(filters=None):
	"""
	Stock Ledger Negative Episodes Report
	
	Detects negative stock episodes and provides recommendations for fixing them.
	An episode is defined as a period where stock balance goes negative and 
	continues until it recovers to zero or positive.
	"""
	
	# Get stock ledger data
	stock_ledger_data = get_stock_ledger_data(filters)
	
	if not stock_ledger_data:
		return [], []
	
	# Process data to find negative episodes
	episodes = find_negative_episodes(stock_ledger_data)
	
	# Prepare columns
	columns = get_columns()
	
	# Prepare data for report
	data = prepare_report_data(episodes)
	
	return columns, data


def get_stock_ledger_data(filters):
	"""
	Fetch stock ledger entries based on filters
	"""
	conditions = get_conditions(filters)
	
	query = """
		SELECT 
			sle.item_code,
			sle.warehouse,
			sle.posting_date,
			sle.posting_time,
			sle.voucher_type,
			sle.voucher_no,
			sle.actual_qty as in_qty,
			CASE WHEN sle.actual_qty < 0 THEN ABS(sle.actual_qty) ELSE 0 END as out_qty,
			CASE WHEN sle.actual_qty > 0 THEN sle.actual_qty ELSE 0 END as in_qty_positive,
			sle.qty_after_transaction as balance_qty,
			sle.valuation_rate,
			sle.stock_uom,
			sle.batch_no,
			sle.serial_no,
			sle.project,
			sle.company
		FROM `tabStock Ledger Entry` sle
		WHERE {conditions}
		ORDER BY sle.item_code, sle.warehouse, sle.posting_date, sle.posting_time, sle.voucher_no
	""".format(conditions=conditions)
	
	return frappe.db.sql(query, filters, as_dict=1)


def get_conditions(filters):
	"""
	Build WHERE conditions for the query
	"""
	conditions = [
		"sle.docstatus = 1",
		# Exclude cancelled entries
		"sle.is_cancelled = 0",
		# Exclude stock reconciliation entries that are cancelled
		"(sle.voucher_type != 'Stock Reconciliation' OR sle.voucher_type = 'Stock Reconciliation' AND sle.is_cancelled = 0)",
		# Exclude entries from cancelled vouchers
		"sle.voucher_no NOT IN (SELECT name FROM `tabStock Reconciliation` WHERE docstatus = 2)",
		"sle.voucher_no NOT IN (SELECT name FROM `tabDelivery Note` WHERE docstatus = 2)",
		"sle.voucher_no NOT IN (SELECT name FROM `tabSales Invoice` WHERE docstatus = 2)",
		"sle.voucher_no NOT IN (SELECT name FROM `tabPurchase Receipt` WHERE docstatus = 2)",
		"sle.voucher_no NOT IN (SELECT name FROM `tabPurchase Invoice` WHERE docstatus = 2)",
		"sle.voucher_no NOT IN (SELECT name FROM `tabStock Entry` WHERE docstatus = 2)",
		"sle.voucher_no NOT IN (SELECT name FROM `tabMaterial Request` WHERE docstatus = 2)",
		"sle.voucher_no NOT IN (SELECT name FROM `tabWork Order` WHERE docstatus = 2)",
		"sle.voucher_no NOT IN (SELECT name FROM `tabJob Card` WHERE docstatus = 2)"
	]
	
	if filters.get("company"):
		conditions.append("sle.company = %(company)s")
	
	if filters.get("from_date"):
		conditions.append("sle.posting_date >= %(from_date)s")
	
	if filters.get("to_date"):
		conditions.append("sle.posting_date <= %(to_date)s")
	
	if filters.get("warehouse"):
		conditions.append("sle.warehouse = %(warehouse)s")
	
	if filters.get("item_code"):
		conditions.append("sle.item_code = %(item_code)s")
	
	if filters.get("item_group"):
		conditions.append("sle.item_code IN (SELECT name FROM `tabItem` WHERE item_group = %(item_group)s)")
	
	if filters.get("batch_no"):
		conditions.append("sle.batch_no = %(batch_no)s")
	
	if filters.get("brand"):
		conditions.append("sle.item_code IN (SELECT name FROM `tabItem` WHERE brand = %(brand)s)")
	
	if filters.get("voucher_no"):
		conditions.append("sle.voucher_no LIKE %(voucher_no)s")
	
	if filters.get("project"):
		conditions.append("sle.project = %(project)s")
	
	return " AND ".join(conditions)


def find_negative_episodes(stock_ledger_data):
	"""
	Find negative stock episodes from stock ledger data
	"""
	episodes = []
	
	# Group by item and warehouse
	grouped_data = {}
	for entry in stock_ledger_data:
		key = (entry.item_code, entry.warehouse)
		if key not in grouped_data:
			grouped_data[key] = []
		grouped_data[key].append(entry)
	
	# Process each group
	for (item_code, warehouse), group in grouped_data.items():
		episodes.extend(find_episodes_for_group(group, item_code, warehouse))
	
	return episodes


def find_episodes_for_group(group, item_code, warehouse):
	"""
	Find negative episodes for a specific item-warehouse group
	"""
	episodes = []
	
	# Sort group by date and time
	group.sort(key=lambda x: (x.posting_date, x.posting_time, x.voucher_no))
	
	# Calculate average valuation rate for the group
	valuation_rates = [entry.valuation_rate for entry in group if entry.valuation_rate]
	avg_val_rate = sum(valuation_rates) / len(valuation_rates) if valuation_rates else 0
	
	# Find transitions to negative
	neg_starts = []
	for i, entry in enumerate(group):
		if i == 0:
			prev_balance = 0
		else:
			prev_balance = group[i-1].balance_qty
		
		if entry.balance_qty < 0 and prev_balance >= 0:
			neg_starts.append(i)
	
	# Process each negative start
	i = 0
	while i < len(neg_starts):
		start_idx = neg_starts[i]
		
		# Find episode end (first recovery to >= 0)
		episode_end_idx = start_idx
		for j in range(start_idx + 1, len(group)):
			if group[j].balance_qty >= 0:
				episode_end_idx = j - 1
				break
			episode_end_idx = j
		
		# Find insert point (last IN before start)
		insert_idx = 0
		for j in range(start_idx, -1, -1):
			if group[j].in_qty_positive > 0:
				insert_idx = j
				break
		
		# Calculate required quantity
		min_balance = min(entry.balance_qty for entry in group[start_idx:episode_end_idx + 1])
		required_qty = max(0.0, -min_balance)
		
		# Create episode record
		episode = {
			"item_code": item_code,
			"warehouse": warehouse,
			"episode_start": group[start_idx].posting_date,
			"episode_end": group[episode_end_idx].posting_date,
			"insert_at": group[insert_idx].posting_date if insert_idx > 0 else group[0].posting_date,
			"required_qty": round(required_qty, 6),
			"avg_valuation_rate": avg_val_rate,
			"stock_uom": group[0].stock_uom,
			"episode_rows": episode_end_idx - insert_idx + 1,
			"next_in_voucher": group[episode_end_idx + 1].voucher_no if episode_end_idx + 1 < len(group) else None,
			"insert_voucher_ref": group[insert_idx].voucher_no if group[insert_idx].in_qty_positive > 0 else "VIRTUAL_OPENING",
			"start_voucher": group[start_idx].voucher_no,
			"end_voucher": group[episode_end_idx].voucher_no,
			"min_balance": min_balance,
			"company": group[0].company
		}
		
		episodes.append(episode)
		
		# Move to next negative start after this episode
		i += 1
		while i < len(neg_starts) and neg_starts[i] <= episode_end_idx:
			i += 1
	
	return episodes


def get_columns():
	"""
	Define report columns
	"""
	return [
		{
			"fieldname": "item_code",
			"label": _("Item"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 120
		},
		{
			"fieldname": "warehouse",
			"label": _("Warehouse"),
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 120
		},
		{
			"fieldname": "episode_start",
			"label": _("Episode Start"),
			"fieldtype": "Date",
			"width": 100
		},
		{
			"fieldname": "episode_end",
			"label": _("Episode End"),
			"fieldtype": "Date",
			"width": 100
		},
		{
			"fieldname": "required_qty",
			"label": _("Required Qty"),
			"fieldtype": "Float",
			"width": 100
		},
		{
			"fieldname": "stock_uom",
			"label": _("UOM"),
			"fieldtype": "Link",
			"options": "UOM",
			"width": 60
		},
		{
			"fieldname": "avg_valuation_rate",
			"label": _("Avg Valuation Rate"),
			"fieldtype": "Currency",
			"width": 120
		},
		{
			"fieldname": "min_balance",
			"label": _("Min Balance"),
			"fieldtype": "Float",
			"width": 100
		},
		{
			"fieldname": "start_voucher",
			"label": _("Start Voucher"),
			"fieldtype": "Data",
			"width": 120
		},
		{
			"fieldname": "end_voucher",
			"label": _("End Voucher"),
			"fieldtype": "Data",
			"width": 120
		},
		{
			"fieldname": "insert_voucher_ref",
			"label": _("Insert Voucher Ref"),
			"fieldtype": "Data",
			"width": 120
		},
		{
			"fieldname": "next_in_voucher",
			"label": _("Next IN Voucher"),
			"fieldtype": "Data",
			"width": 120
		},
		{
			"fieldname": "episode_rows",
			"label": _("Episode Rows"),
			"fieldtype": "Int",
			"width": 80
		},
		{
			"fieldname": "company",
			"label": _("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"width": 100
		}
	]


def prepare_report_data(episodes):
	"""
	Prepare episodes data for the report
	"""
	data = []
	
	for episode in episodes:
		row = {
			"item_code": episode["item_code"],
			"warehouse": episode["warehouse"],
			"episode_start": episode["episode_start"],
			"episode_end": episode["episode_end"],
			"required_qty": episode["required_qty"],
			"stock_uom": episode["stock_uom"],
			"avg_valuation_rate": episode["avg_valuation_rate"],
			"min_balance": episode["min_balance"],
			"start_voucher": episode["start_voucher"],
			"end_voucher": episode["end_voucher"],
			"insert_voucher_ref": episode["insert_voucher_ref"],
			"next_in_voucher": episode["next_in_voucher"],
			"episode_rows": episode["episode_rows"],
			"company": episode["company"]
		}
		data.append(row)
	
	# Sort by item, warehouse, and insert date
	data.sort(key=lambda x: (x["item_code"], x["warehouse"], x["episode_start"]))
	
	return data


@frappe.whitelist()
def export_fix_plan(filters):
	"""
	Export fix plan as CSV for bulk processing
	"""
	import csv
	from io import StringIO
	
	# Get episodes data
	stock_ledger_data = get_stock_ledger_data(filters)
	if not stock_ledger_data:
		return ""
	
	episodes = find_negative_episodes(stock_ledger_data)
	
	# Create CSV content
	output = StringIO()
	writer = csv.writer(output)
	
	# Write header
	writer.writerow([
		"Item Code", "Warehouse", "Episode Start", "Episode End", 
		"Required Qty", "Stock UOM", "Avg Valuation Rate", "Min Balance",
		"Start Voucher", "End Voucher", "Insert Voucher Ref", 
		"Next IN Voucher", "Company"
	])
	
	# Write data
	for episode in episodes:
		writer.writerow([
			episode["item_code"],
			episode["warehouse"],
			episode["episode_start"],
			episode["episode_end"],
			episode["required_qty"],
			episode["stock_uom"],
			episode["avg_valuation_rate"],
			episode["min_balance"],
			episode["start_voucher"],
			episode["end_voucher"],
			episode["insert_voucher_ref"],
			episode["next_in_voucher"] or "",
			episode["company"]
		])
	
	return output.getvalue()
