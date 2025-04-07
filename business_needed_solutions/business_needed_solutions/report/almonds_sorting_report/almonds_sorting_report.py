import frappe
from frappe.utils import cint, flt
from frappe.model.docstatus import DocStatus

def execute(filters=None):
	columns, data = [], []
	columns = get_columns()
	data = get_filtered_stock_entries(filters)
	return columns, data

def get_columns():
    columns=[
            {
				"label": "Batch No",
				"fieldname": "batch_id",
				"fieldtype": "Link",
				"options": "batch",
				"width": 250,
			},
			{
				"label": "Item Name",
				"fieldname": "item_name",
				"width": 250,
			},
			{
				"label": "QTY",
				"fieldname": "transfer_qty",
				"width": 250,
			},
			{
				"label": "UOM",
				"fieldname": "stock_uom",
				"width": 100,
			},
			{
				"label": "Percent",
				"fieldname": "avg_percent",
				"width": 100,
			},
    ]
    return columns
    
def get_filtered_stock_entries(filters):
	if not filters.get("batch_no") or not filters.get("item_code"):
		frappe.throw("Batch No and Item Code are required filters")
		
	precision = cint(frappe.db.get_single_value("System Settings", "float_precision"))
	stock_entries = frappe.db.get_list("Stock Ledger Entry", 
		filters={"docstatus": 1, "batch_no": filters.batch_no},
		fields={"voucher_no"}, 
		pluck="voucher_no")
	
	if not stock_entries:
		return []
		
	# Track inputs (source items) and outputs (target items) separately
	source_items = {}
	target_items = {}
	
	for stock_entry in stock_entries:
		stock_entry_doc = frappe.get_doc("Stock Entry", stock_entry)
		
		if stock_entry_doc.purpose == "Repack" and stock_entry_doc.stock_entry_type == "Almonds Sorting" and stock_entry_doc.docstatus == 1:
			# Process source items (items going out)
			for item in stock_entry_doc.items:
				if item.s_warehouse:  # Source warehouse means item is going out
					item_key = item.item_code
					if item_key not in source_items:
						source_items[item_key] = {
							"item_code": item.item_code,
							"item_name": item.item_name,
							"transfer_qty": 0,
							"stock_uom": item.stock_uom,
							"batch_id": item.batch_no or "NA"
						}
					source_items[item_key]["transfer_qty"] += flt(item.transfer_qty, precision)
					
				# Process target items (items coming in)
				elif item.t_warehouse:  # Target warehouse means item is coming in
					item_key = item.item_code
					if item_key not in target_items:
						target_items[item_key] = {
							"item_code": item.item_code,
							"item_name": item.item_name,
							"transfer_qty": 0,
							"stock_uom": item.stock_uom,
							"batch_id": item.batch_no or "NA"
						}
					target_items[item_key]["transfer_qty"] += flt(item.transfer_qty, precision)
	
	# Calculate the main quantity (what went out)
	main_qty = 0
	if filters.item_code in source_items:
		main_qty = source_items[filters.item_code]["transfer_qty"]
	
	if main_qty == 0:
		frappe.msgprint("No outgoing quantity found for the specified item code and batch")
		return []
	
	# Calculate the total of all outputs
	total_output = 0
	for item_code, item_data in target_items.items():
		total_output += item_data["transfer_qty"]
	
	# Prepare results
	results = []
	
	# Add the main item (source)
	if filters.item_code in source_items:
		main_item = source_items[filters.item_code]
		main_item["avg_percent"] = "100%"
		results.append(main_item)
	
	# Add all target items
	for item_code, item_data in target_items.items():
		# Skip if this is the same as the main item (shouldn't happen in correct workflow)
		if item_code == filters.item_code and item_data["batch_id"] == filters.batch_no:
			continue
			
		item_data["avg_percent"] = str(flt((item_data["transfer_qty"]/main_qty)*100, precision)) + "%"
		results.append(item_data)
	
	# Calculate and add the difference
	difference = main_qty - total_output
	results.append({
		'transfer_qty': difference,
		'item_name': 'Difference (Loss/Gain)',
		'stock_uom': source_items[filters.item_code]["stock_uom"] if filters.item_code in source_items else "Kg",
		'item_code': 'NA',
		'batch_id': 'NA',
		'avg_percent': str(flt((difference/main_qty)*100, precision)) + "%"
	})
	
	# Sort results
	results = sorted(results, key=lambda d: d['batch_id'])
	
	return results