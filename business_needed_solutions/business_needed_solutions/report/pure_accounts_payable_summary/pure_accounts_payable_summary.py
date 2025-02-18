# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _, scrub
from frappe.utils import cint, flt
from business_needed_solutions.business_needed_solutions.report.pure_accounts_receivable_summary.pure_accounts_receivable_summary import (
	AccountsReceivablePayableSummary,
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

	# 1. Get columns & data for Receivable (main) and Payable (secondary).
	main_columns, main_data = AccountsReceivablePayableSummary(filters).run(args)
	secondary_columns, secondary_data = AccountsReceivablePayableSummary(filters).run(secondary_args)

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

	# 3. Gather Party Link information:
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

	# 4. Decide which fields/columns we want to adjust by (R - P).
	#    This includes 'outstanding', ageing columns, and total_due.
	#    Add more fields if needed (e.g., future_amount).
	# columns_to_adjust = ["outstanding", "total_due"]
	# # Example: if you know your age ranges are range0..range4, include those:
	# for i in range(5):
	# 	columns_to_adjust.append(f"range{i}")

	currency_fields = []

	for col in main_columns:
		# if the column is meant to hold currency values
		if col.get("fieldtype") == "Currency":
			# store the fieldname for easy reference
			currency_fields.append(col["fieldname"])

	# 5. Build the final data. For each party in main_dict:
	#    - Skip if it appears as a secondary_party.
	#    - If it appears in primary_map, subtract the corresponding secondary amounts.
	final_data = []
	for party, row in main_dict.items():
		if party in skip_set:
			# This means the party is listed as a secondary_party somewhere => skip it
			continue

		# Make a copy so we don't overwrite main_dict
		updated_row = row.copy()

		# For each linked secondary party, subtract the relevant columns
		if party in primary_map:
			for secondary_party in primary_map[party]:
				# If the secondary party has Payable amounts in secondary_dict
				if secondary_party in secondary_dict:
					sec_row = secondary_dict[secondary_party]
					updated_row["secondary_party_type"] = sec_row["party_type"]
					updated_row["secondary_party"] = sec_row["party"]
					for fieldname in currency_fields:
						updated_row[fieldname] = (
							flt(updated_row.get(fieldname, 0.0)) 
							- flt(sec_row.get(fieldname, 0.0))
						)

		final_data.append(updated_row)
	main_columns.append(
		{
			"label": "Secondary Party",
			"fieldname": "secondary_party",
			"fieldtype": "Link",  # or "Dynamic Link" if you want it linked
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
	# 6. You can return the same columns from the main dataset
	#    (they now reflect the differences).
	#    No extra "r_minus_p" column is needed since you replaced
	#    the existing numeric fields with (R - P).
	return main_columns, final_data