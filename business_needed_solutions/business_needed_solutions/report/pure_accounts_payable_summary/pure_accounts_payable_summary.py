# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _, scrub
from urllib.parse import quote
from frappe.utils import cint, flt
from business_needed_solutions.business_needed_solutions.report.pure_accounts_receivable_summary.pure_accounts_receivable_summary import (
	AccountsReceivablePayableSummary, get_fiscal_year_dates, 
	get_supplier_invoice_and_received_amounts, get_customer_invoice_and_paid_amounts
)


# def execute(filters=None):
# 	args = {
# 		"account_type": "Payable",
# 		"naming_by": ["Buying Settings", "supp_master_name"],
# 	}
# 	secondary_args = {
# 		"account_type": "Receivable",
# 		"naming_by": ["Selling Settings", "cust_master_name"],
# 	}
# 	return AccountsReceivablePayableSummary(filters).run(args,secondary_args)


def execute(filters=None):
	args = {
		"account_type": "Payable",
		"naming_by": ["Buying Settings", "supp_master_name"],
	}
	secondary_args = {
		"account_type": "Receivable",
		"naming_by": ["Selling Settings", "cust_master_name"],
	}

	report_date = filters.get("report_date") or frappe.utils.today()
	company = filters.get("company") or frappe.defaults.get_global_default("company")
	from_date, to_date = get_fiscal_year_dates(report_date, company)

	# 1. Get columns & data for Receivable (main) and Payable (secondary).
	main_columns, main_data = AccountsReceivablePayableSummary(filters).run(args)
	secondary_columns, secondary_data = AccountsReceivablePayableSummary(filters).run(secondary_args)

	# Add city column if add_supplier_cities is checked
	supplier_cities = {}
	if filters.get("add_supplier_cities"):
		main_columns.append({
			"label": _("City"),
			"fieldname": "city",
			"fieldtype": "Data",
			"width": 120
		})
		
		# Get supplier cities - include all parties that might appear (including common parties)
		# First, get all parties from main_data
		all_parties = [d.get("party") for d in main_data if d.get("party")]
		
		# Check which of these exist as Supplier (for common parties)
		if all_parties:
			supplier_addresses = frappe.get_all(
				"Supplier",
				fields=["name", "supplier_primary_address"],
				filters={"name": ["in", all_parties]}
			)
			
			address_list = [d.supplier_primary_address for d in supplier_addresses if d.supplier_primary_address]
			if address_list:
				addresses = frappe.get_all(
					"Address",
					fields=["name", "city"],
					filters={"name": ["in", address_list]}
				)
				address_city_map = {d.name: d.city for d in addresses}
				
				for supplier in supplier_addresses:
					if supplier.supplier_primary_address:
						supplier_cities[supplier.name] = address_city_map.get(supplier.supplier_primary_address, "")
			
			# Add city to main_data for suppliers
			for row in main_data:
				if row.get("party_type") == "Supplier" or row.get("party") in supplier_cities:
					row["city"] = supplier_cities.get(row.get("party"), "")

	# 2. Convert main_data and secondary_data to dictionaries keyed by 'party'.
	main_dict = {}
	for row in main_data:
		party = row.get("party")
		if party:
			main_dict[party] = row

	secondary_dict = {}
	for row in secondary_data:
		party = row.get("party")
		if party:
			secondary_dict[party] = row

	# 3. Identify common parties (appear in both AR and AP)
	common_parties = set(main_dict.keys()) & set(secondary_dict.keys())

	# 4. Gather Party Link information:
	#    - primary_map: maps primary_party -> [secondary_party1, ...]
	#    - skip_set: all secondary_party, to be skipped entirely.
	party_links = frappe.get_all(
		"Party Link",
		fields=["primary_party", "primary_role", "secondary_party", "secondary_role"],
	)

	primary_map = {}
	skip_set = set()

	for pl in party_links:
		primary = pl.primary_party
		secondary = pl.secondary_party

		if primary not in primary_map:
			primary_map[primary] = []
		primary_map[primary].append(secondary)

		skip_set.add(secondary)

	# 5. Get currency fields for adjustments
	currency_fields = []
	for col in main_columns:
		if col.get("fieldtype") == "Currency":
			currency_fields.append(col["fieldname"])

	# 5a. Build mapping of supplier parties to their linked customer parties
	# and get customer invoice/paid amounts for those customers
	supplier_to_customer_map = {}
	customer_parties_to_query = set()
	
	for pl in party_links:
		# If secondary_role is Customer, then primary_party (Supplier) is linked to a customer
		if pl.secondary_role == "Customer":
			supplier_to_customer_map[pl.primary_party] = pl.secondary_party
			customer_parties_to_query.add(pl.secondary_party)
		# If primary_role is Customer, then secondary_party (Supplier) is linked to a customer
		if pl.primary_role == "Customer":
			supplier_to_customer_map[pl.secondary_party] = pl.primary_party
			customer_parties_to_query.add(pl.primary_party)
	
	# Also include common parties - they are both supplier and customer
	for party in common_parties:
		supplier_to_customer_map[party] = party
		customer_parties_to_query.add(party)
	
	# Get customer amounts keyed by customer party
	customer_amounts_by_customer = {}
	if customer_parties_to_query:
		customer_amounts_by_customer = get_customer_invoice_and_paid_amounts(
			list(customer_parties_to_query),
			company,
			report_date,
			filters.get("show_future_payments", 0),
			filters.get("from_date")
		)
	
	# Map customer amounts back to supplier parties
	customer_amounts = {}
	for supplier_party, customer_party in supplier_to_customer_map.items():
		if customer_party in customer_amounts_by_customer:
			customer_amounts[supplier_party] = customer_amounts_by_customer[customer_party]
	
	# 5b. Get supplier invoice and received amounts for all supplier parties
	supplier_parties_to_query = list(main_dict.keys())
	supplier_amounts = {}
	if supplier_parties_to_query:
		supplier_amounts = get_supplier_invoice_and_received_amounts(
			supplier_parties_to_query,
			company,
			report_date,
			filters.get("show_future_payments", 0),
			filters.get("from_date")
		)

	# 6. Build the final data with new logic:
	#    - For common parties: categorize by net balance (debit -> Receivable, credit -> Payable)
	#    - For Party Links: still apply netting but respect net balance categorization
	final_data = []
	processed_common_parties = set()
	
	for party, row in main_dict.items():
		# Check if this party is a common party (both Customer and Supplier)
		is_common_party = party in common_parties
		
		if is_common_party:
			# Calculate net balance: AP outstanding - AR outstanding
			ap_outstanding = flt(row.get("outstanding", 0.0))
			ar_outstanding = flt(secondary_dict[party].get("outstanding", 0.0))
			net_balance = ap_outstanding - ar_outstanding
			
			# Only show in Payable if net balance is positive (credit/negative AR)
			if net_balance <= 0:
				processed_common_parties.add(party)
				continue  # Skip this party, it appears in Receivable report
			
			# Net balance is positive, show in Payable
			# Make a copy so we don't overwrite main_dict
			updated_row = row.copy()
			
			# Subtract AR amounts from AP amounts for all currency fields
			sec_row = secondary_dict[party]
			updated_row["secondary_party_type"] = sec_row["party_type"]
			updated_row["secondary_party"] = sec_row["party"]
			updated_row["is_common_party"] = True
			
			for fieldname in currency_fields:
				updated_row[fieldname] = (
					flt(updated_row.get(fieldname, 0.0)) 
					- flt(sec_row.get(fieldname, 0.0))
				)
			
			processed_common_parties.add(party)
		else:
			# Not a common party, apply existing Party Link logic
			# Make a copy so we don't overwrite main_dict
			updated_row = row.copy()
			
			# Check if party is a secondary party in Party Link
			if party in skip_set:
				# Secondary party: find its primary party and net against it
				# Find the primary party for this secondary
				primary_party_for_secondary = None
				for primary_party, secondary_list in primary_map.items():
					if party in secondary_list:
						primary_party_for_secondary = primary_party
						break
				
				if primary_party_for_secondary:
					# Check if primary party exists in main_dict (same report type)
					has_primary_in_report = primary_party_for_secondary in main_dict
					
					if has_primary_in_report:
						# Primary party is in this report, skip secondary (it will be netted into primary)
						continue
					else:
						# Primary party is not in this report, but check if it has opposite side outstanding
						# For Payable: secondary is Supplier, primary is Customer
						# Check if primary Customer has AR outstanding in secondary_dict
						if primary_party_for_secondary in secondary_dict:
							primary_row = secondary_dict[primary_party_for_secondary]
							updated_row["secondary_party_type"] = primary_row["party_type"]
							updated_row["secondary_party"] = primary_party_for_secondary
							# Net AP - AR for all currency fields
							for fieldname in currency_fields:
								updated_row[fieldname] = (
									flt(updated_row.get(fieldname, 0.0)) 
									- flt(primary_row.get(fieldname, 0.0))
								)

			# For primary parties: net against their secondary parties
			if party in primary_map:
				for secondary_party in primary_map[party]:
					# Skip if secondary party is already processed as common party
					if secondary_party in processed_common_parties:
						continue
					
					# If the secondary party has Receivable amounts in secondary_dict
					if secondary_party in secondary_dict:
						sec_row = secondary_dict[secondary_party]
						updated_row["secondary_party_type"] = sec_row["party_type"]
						updated_row["secondary_party"] = sec_row["party"]
						for fieldname in currency_fields:
							updated_row[fieldname] = (
								flt(updated_row.get(fieldname, 0.0)) 
								- flt(sec_row.get(fieldname, 0.0))
							)
		
		# Only add if outstanding is positive after adjustments
		if flt(updated_row.get("outstanding", 0.0)) > 0:
			# For common parties in Payable report, ensure supplier city is set
			if filters.get("add_supplier_cities") and is_common_party:
				updated_row["city"] = supplier_cities.get(party, updated_row.get("city", ""))
			
			party_name = updated_row.get("party_name") or party
			
			# Get Payable accounts to filter Party GL by account_type
			payable_accounts = frappe.get_all(
				"Account",
				filters={"account_type": "Payable", "company": company},
				pluck="name"
			)
			account_filter = quote(",".join(payable_accounts)) if payable_accounts else "undefined"
			
			gl_url = f"/app/query-report/Party%20GL?company={quote(company)}&from_date={quote(str(from_date))}&to_date={quote(str(to_date))}&account={account_filter}&party=%5B%22{quote(party)}%22%5D&party_name={quote(party_name)}&group_by=Group+by+Voucher+%28Consolidated%29&project=undefined&include_dimensions=1&include_default_book_entries=1"
			button_html = f'<a href="{gl_url}" target="_blank" class="btn btn-xs btn-default">GL: {party_name}</a>'

			updated_row["party_gl_link"] = button_html
			
			# Add the 2 new columns:
			# 1. Received Invoice Amount (Supplier's received invoice including debit note)
			updated_row["received_invoice_amount"] = flt(supplier_amounts.get(party, {}).get("received_invoice_amount", 0.0))
			
			# 2. Invoiced Amount (if party linked to customer, then customer's invoiced amount incl credit note)
			updated_row["invoiced_amount"] = flt(customer_amounts.get(party, {}).get("invoiced_amount", 0.0))
			
			final_data.append(updated_row)

	main_columns.append(
		{
			"label": "Party GL",
			"fieldname": "party_gl_link",
			"fieldtype": "HTML",
			"width": 200,
		}
	)
	main_columns.append(
		{
			"label": "Secondary Party",
			"fieldname": "secondary_party",
			"fieldtype": "Data",  # or "Dynamic Link" if you want it linked
			"width": 140,
		}
	)

	main_columns.append(
		{
			"label": "Secondary Party Type",
			"fieldname": "secondary_party_type",
			"fieldtype": "Data",
			"width": 120,
		}
	)
	
	# Find the index of "Opening Balance" column and insert the 2 new columns after it
	opening_balance_index = None
	for i, col in enumerate(main_columns):
		if col.get("fieldname") == "opening":
			opening_balance_index = i
			break
	
	# Add the 2 new columns right after Opening Balance
	if opening_balance_index is not None:
		insert_index = opening_balance_index + 1
		main_columns.insert(insert_index, {
			"label": _("Received Invoice Amount"),
			"fieldname": "received_invoice_amount",
			"fieldtype": "Currency",
			"width": 150,
		})
		main_columns.insert(insert_index + 1, {
			"label": _("Invoiced Amount"),
			"fieldname": "invoiced_amount",
			"fieldtype": "Currency",
			"width": 150,
		})
	else:
		# Fallback: add at the end if opening balance not found
		main_columns.append({
			"label": _("Received Invoice Amount"),
			"fieldname": "received_invoice_amount",
			"fieldtype": "Currency",
			"width": 150,
		})
		main_columns.append({
			"label": _("Invoiced Amount"),
			"fieldname": "invoiced_amount",
			"fieldtype": "Currency",
			"width": 150,
		})

	# 6. You can return the same columns from the main dataset
	#    (they now reflect the differences).
	#    No extra "r_minus_p" column is needed since you replaced
	#    the existing numeric fields with (R - P).
	return main_columns, final_data