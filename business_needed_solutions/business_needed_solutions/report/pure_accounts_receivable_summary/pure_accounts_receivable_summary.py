# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors and contributors
# For license information, please see license.txt


import frappe
from frappe import _, scrub
from frappe.utils import cint, flt
from urllib.parse import quote
from erpnext.accounts.party import get_partywise_advanced_payment_amount
from erpnext.accounts.report.accounts_receivable.accounts_receivable import ReceivablePayableReport
from erpnext.accounts.utils import get_currency_precision, get_party_types_from_account_type
from erpnext.accounts.doctype.process_statement_of_accounts.process_statement_of_accounts import get_customers_based_on_sales_person

def get_fiscal_year_dates(report_date, company):
	report_date = frappe.utils.getdate(report_date)

	# First, try to get Fiscal Year where the company is linked in the child table
	fiscal_years = frappe.get_all(
		"Fiscal Year",
		fields=["name", "year_start_date", "year_end_date"],
		filters={
			"disabled": 0,
			"year_start_date": ("<=", report_date),
			"year_end_date": (">=", report_date),
		},
		order_by="year_start_date desc"
	)

	for fy in fiscal_years:
		linked_companies = frappe.get_all(
			"Fiscal Year Company",
			filters={"parent": fy.name, "company": company},
			pluck="company"
		)
		if linked_companies:
			return fy.year_start_date, fy.year_end_date

	# Fallback to any Fiscal Year (system default)
	if fiscal_years:
		fy = fiscal_years[0]
		return fy.year_start_date, fy.year_end_date

	# Absolute fallback
	return "2023-04-01", "2024-03-31"





def execute(filters=None):
	args = {
		"account_type": "Receivable",
		"naming_by": ["Selling Settings", "cust_master_name"],
	}

	secondary_args = {
		"account_type": "Payable",
		"naming_by": ["Buying Settings", "supp_master_name"],
	}

	report_date = filters.get("report_date") or frappe.utils.today()
	company = filters.get("company") or frappe.defaults.get_global_default("company")
	from_date, to_date = get_fiscal_year_dates(report_date, company)

	# Get customers based on sales person if filter is applied
	customers = []
	if filters.get("sales_person"):
		customers = [d.name for d in get_customers_based_on_sales_person(filters.get("sales_person"))]
		if not customers:
			return [], []

	# 1. Get columns & data for Receivable (main) and Payable (secondary).
	main_columns, main_data = AccountsReceivablePayableSummary(filters).run(args)
	secondary_columns, secondary_data = AccountsReceivablePayableSummary(filters).run(secondary_args)

	# Filter main_data based on customers if sales person filter is applied
	if customers:
		main_data = [d for d in main_data if d.get("party") in customers]

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
		party_name = updated_row.get("party_name") or party
		gl_url = f"/app/query-report/Party%20GL?company={quote(company)}&from_date={quote(str(from_date))}&to_date={quote(str(to_date))}&account=undefined&party=%5B%22{quote(party)}%22%5D&party_name={quote(party_name)}&group_by=Group+by+Voucher+%28Consolidated%29&project=undefined&include_dimensions=1&include_default_book_entries=1"
		button_html = f'<a href="{gl_url}" target="_blank" class="btn btn-xs btn-default">GL: {party_name}</a>'

		updated_row["party_gl_link"] = button_html
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
	# 6. You can return the same columns from the main dataset
	#    (they now reflect the differences).
	#    No extra "r_minus_p" column is needed since you replaced
	#    the existing numeric fields with (R - P).
	return main_columns, final_data


class AccountsReceivablePayableSummary(ReceivablePayableReport):
	def run(self, args):
		self.account_type = args.get("account_type")
		self.party_type = get_party_types_from_account_type(self.account_type)
		self.party_naming_by = frappe.db.get_value(args.get("naming_by")[0], None, args.get("naming_by")[1])
		self.get_columns()
		self.get_data(args)
		return self.columns, self.data

	def get_data(self, args):
		self.data = []
		self.accounting_entries = ReceivablePayableReport(self.filters).run(args)[1]
		self.currency_precision = get_currency_precision() or 2

		self.get_party_total(args)

		party = None
		for party_type in self.party_type:
			if self.filters.get(scrub(party_type)):
				party = self.filters.get(scrub(party_type))

		party_advance_amount = (
			get_partywise_advanced_payment_amount(
				self.party_type,
				self.filters.report_date,
				self.filters.show_future_payments,
				self.filters.company,
				party=party,
			)
			or {}
		)

		if self.filters.show_gl_balance:
			gl_balance_map = get_gl_balance(self.filters.report_date, self.filters.company)

		exclude_groups = self.filters.get(
			"exclude_customer_group" if self.account_type == "Receivable" else "exclude_supplier_group"
		) or []
		
		for party, party_dict in self.party_total.items():
			if flt(party_dict.outstanding, self.currency_precision) == 0:
				continue

			# Dynamically exclude based on account type
			group_field = "customer_group" if self.account_type == "Receivable" else "supplier_group"
			if party_dict.get(group_field) in exclude_groups:
				continue

			row = frappe._dict()

			row.party = party
			if self.party_naming_by == "Naming Series":
				if self.account_type == "Payable":
					doctype = "Supplier"
					fieldname = "supplier_name"
				else:
					doctype = "Customer"
					fieldname = "customer_name"
				row.party_name = frappe.get_cached_value(doctype, party, fieldname)

			row.update(party_dict)

			# Advance against party
			row.advance = party_advance_amount.get(party, 0)
			row.purepaid = row.paid
			# In AR/AP, advance shown in paid columns,
			# but in summary report advance shown in separate column
			row.paid -= row.advance

			if self.filters.show_gl_balance:
				row.gl_balance = gl_balance_map.get(party)
				row.diff = flt(row.outstanding) - flt(row.gl_balance)

			if self.filters.show_future_payments:
				row.remaining_balance = flt(row.outstanding) - flt(row.future_amount)

			self.data.append(row)

	def get_party_total(self, args):
		self.party_total = frappe._dict()

		for d in self.accounting_entries:
			self.init_party_total(d)

			# Add all amount columns
			for k in list(self.party_total[d.party]):
				if isinstance(self.party_total[d.party][k], float):
					self.party_total[d.party][k] += d.get(k) or 0.0

			# set territory, customer_group, sales person etc
			self.set_party_details(d)

	def init_party_total(self, row):
		default_dict = {
			"invoiced": 0.0,
			"paid": 0.0,
			"credit_note": 0.0,
			"outstanding": 0.0,
			"total_due": 0.0,
			"future_amount": 0.0,
			"sales_person": [],
			"party_type": row.party_type,
		}
		for i in self.range_numbers:
			range_key = f"range{i}"
			default_dict[range_key] = 0.0

		self.party_total.setdefault(
			row.party,
			frappe._dict(default_dict),
		)

	def set_party_details(self, row):
		self.party_total[row.party].currency = row.currency

		for key in ("territory", "customer_group", "supplier_group"):
			if row.get(key):
				self.party_total[row.party][key] = row.get(key, "")
		if row.sales_person:
			self.party_total[row.party].sales_person.append(row.get("sales_person", ""))

		if self.filters.sales_partner:
			self.party_total[row.party]["default_sales_partner"] = row.get("default_sales_partner", "")

	def get_columns(self):
		self.columns = []
		self.add_column(
			label=_("Party Type"),
			fieldname="party_type",
			fieldtype="Data",
			width=100,
		)
		self.add_column(
			label=_("Party"),
			fieldname="party",
			fieldtype="Dynamic Link",
			options="party_type",
			width=180,
		)

		if self.party_naming_by == "Naming Series":
			self.add_column(
				label=_("Supplier Name") if self.account_type == "Payable" else _("Customer Name"),
				fieldname="party_name",
				fieldtype="Data",
			)
		self.add_column(_("Invoiced Amount"), fieldname="invoiced")
		self.add_column(_("Paid Amount"), fieldname="purepaid")
		self.add_column(_("Outstanding Amount"), fieldname="outstanding")

		if self.filters.show_gl_balance:
			self.add_column(_("GL Balance"), fieldname="gl_balance")
			self.add_column(_("Difference"), fieldname="diff")

		self.setup_ageing_columns()
		self.add_column(label="Total Amount Due", fieldname="total_due")

		if self.filters.show_future_payments:
			self.add_column(label=_("Future Payment Amount"), fieldname="future_amount")
			self.add_column(label=_("Remaining Balance"), fieldname="remaining_balance")

		if self.account_type == "Receivable":
			
			self.add_column(
				label=_("Customer Group"),
				fieldname="customer_group",
				fieldtype="Link",
				options="Customer Group",
			)
			if self.filters.show_sales_person:
				self.add_column(label=_("Sales Person"), fieldname="sales_person", fieldtype="Data")

			if self.filters.sales_partner:
				self.add_column(label=_("Sales Partner"), fieldname="default_sales_partner", fieldtype="Data")

		else:
			self.add_column(
				label=_("Supplier Group"),
				fieldname="supplier_group",
				fieldtype="Link",
				options="Supplier Group",
			)


def get_gl_balance(report_date, company):
	return frappe._dict(
		frappe.db.get_all(
			"GL Entry",
			fields=["party", "sum(debit -  credit)"],
			filters={"posting_date": ("<=", report_date), "is_cancelled": 0, "company": company},
			group_by="party",
			as_list=1,
		)
	)