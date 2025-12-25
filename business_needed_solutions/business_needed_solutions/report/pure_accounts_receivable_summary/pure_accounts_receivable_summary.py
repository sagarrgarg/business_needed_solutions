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


def get_supplier_invoice_and_received_amounts(parties, company, report_date, show_future_payments=0, from_date=None):
	"""
	Get supplier invoice amounts (including debit notes) for parties that are linked to suppliers.
	Uses Purchase Invoice directly like Purchase Register does.
	Returns dict: {party: {"received_invoice_amount": x}}
	"""
	from frappe.query_builder.functions import Sum, Abs
	
	result = {}
	if not parties:
		return result
	
	# Get payable account types
	payable_accounts = frappe.get_all(
		"Account",
		filters={"account_type": "Payable", "company": company},
		pluck="name"
	)
	
	if not payable_accounts:
		return result
	
	# Query Purchase Invoices directly (like Purchase Register does)
	pi = frappe.qb.DocType("Purchase Invoice")
	
	# Build query for supplier invoices (Purchase Invoices) including debit notes
	# Sum absolute values of base_grand_total to get total invoice amount including debit notes
	supplier_invoices_query = (
		frappe.qb.from_(pi)
		.select(pi.supplier, Sum(Abs(pi.base_grand_total)).as_("amount"))
		.where(
			(pi.supplier.isin(parties))
			& (pi.docstatus == 1)
			& (pi.credit_to.isin(payable_accounts))
			& (pi.posting_date <= report_date)
		)
	)
	
	# Add from_date filter if provided
	if from_date:
		supplier_invoices_query = supplier_invoices_query.where(pi.posting_date >= from_date)
	
	supplier_invoices_query = supplier_invoices_query.groupby(pi.supplier)
	
	invoice_data = supplier_invoices_query.run(as_dict=True)
	
	# Combine invoice amounts
	for row in invoice_data:
		party = row["supplier"]
		if party not in result:
			result[party] = {"received_invoice_amount": 0.0}
		result[party]["received_invoice_amount"] = flt(row["amount"])
	
	return result


def get_customer_invoice_and_paid_amounts(parties, company, report_date, show_future_payments=0, from_date=None):
	"""
	Get customer invoice amounts (Sales Invoices including Credit Notes) for customer parties.
	Uses Sales Invoice directly like Sales Register does.
	Returns dict: {party: {"invoiced_amount": x}}
	"""
	from frappe.query_builder.functions import Sum, Abs
	
	result = {}
	if not parties:
		return result
	
	# Get receivable account types
	receivable_accounts = frappe.get_all(
		"Account",
		filters={"account_type": "Receivable", "company": company},
		pluck="name"
	)
	
	if not receivable_accounts:
		return result
	
	# Query Sales Invoices directly (like Sales Register does)
	si = frappe.qb.DocType("Sales Invoice")
	
	# Build query for customer invoices (Sales Invoices) including credit notes
	# Sum absolute values of base_grand_total to get total invoice amount including credit notes
	customer_invoices_query = (
		frappe.qb.from_(si)
		.select(si.customer, Sum(Abs(si.base_grand_total)).as_("amount"))
		.where(
			(si.customer.isin(parties))
			& (si.docstatus == 1)
			& (si.debit_to.isin(receivable_accounts))
			& (si.posting_date <= report_date)
		)
	)
	
	# Add from_date filter if provided
	if from_date:
		customer_invoices_query = customer_invoices_query.where(si.posting_date >= from_date)
	
	customer_invoices_query = customer_invoices_query.groupby(si.customer)
	
	invoice_data = customer_invoices_query.run(as_dict=True)
	
	# Combine invoice amounts
	for row in invoice_data:
		party = row["customer"]
		if party not in result:
			result[party] = {"invoiced_amount": 0.0}
		result[party]["invoiced_amount"] = flt(row["amount"])
	
	return result





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

	# Add city column if add_customer_cities is checked
	if filters.get("add_customer_cities"):
		main_columns.append({
			"label": _("City"),
			"fieldname": "city",
			"fieldtype": "Data",
			"width": 120
		})
		
		# Get customer cities
		customer_cities = {}
		customer_list = [d.get("party") for d in main_data if d.get("party_type") == "Customer"]
		if customer_list:
			customer_addresses = frappe.get_all(
				"Customer",
				fields=["name", "customer_primary_address"],
				filters={"name": ["in", customer_list]}
			)
			
			address_list = [d.customer_primary_address for d in customer_addresses if d.customer_primary_address]
			if address_list:
				addresses = frappe.get_all(
					"Address",
					fields=["name", "city"],
					filters={"name": ["in", address_list]}
				)
				address_city_map = {d.name: d.city for d in addresses}
				
				for customer in customer_addresses:
					if customer.customer_primary_address:
						customer_cities[customer.name] = address_city_map.get(customer.customer_primary_address, "")
			
			# Add city to main_data
			for row in main_data:
				if row.get("party_type") == "Customer":
					row["city"] = customer_cities.get(row.get("party"), "")

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

	# 5a. Build mapping of customer parties to their linked supplier parties
	# and get supplier invoice/received amounts for those suppliers
	customer_to_supplier_map = {}
	supplier_parties_to_query = set()
	
	for pl in party_links:
		# If secondary_role is Supplier, then primary_party (Customer) is linked to a supplier
		if pl.secondary_role == "Supplier":
			customer_to_supplier_map[pl.primary_party] = pl.secondary_party
			supplier_parties_to_query.add(pl.secondary_party)
		# If primary_role is Supplier, then secondary_party (Customer) is linked to a supplier
		if pl.primary_role == "Supplier":
			customer_to_supplier_map[pl.secondary_party] = pl.primary_party
			supplier_parties_to_query.add(pl.primary_party)
	
	# Also include common parties - they are both customer and supplier
	for party in common_parties:
		customer_to_supplier_map[party] = party
		supplier_parties_to_query.add(party)
	
	# Get supplier amounts keyed by supplier party
	supplier_amounts_by_supplier = {}
	if supplier_parties_to_query:
		supplier_amounts_by_supplier = get_supplier_invoice_and_received_amounts(
			list(supplier_parties_to_query),
			company,
			report_date,
			filters.get("show_future_payments", 0),
			filters.get("from_date")
		)
	
	# Map supplier amounts back to customer parties
	supplier_amounts = {}
	for customer_party, supplier_party in customer_to_supplier_map.items():
		if supplier_party in supplier_amounts_by_supplier:
			supplier_amounts[customer_party] = supplier_amounts_by_supplier[supplier_party]
	
	# 5b. Get customer invoice and paid amounts for all customer parties
	customer_parties_to_query = list(main_dict.keys())
	customer_amounts = {}
	if customer_parties_to_query:
		customer_amounts = get_customer_invoice_and_paid_amounts(
			customer_parties_to_query,
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
			# Calculate net balance: AR outstanding - AP outstanding
			ar_outstanding = flt(row.get("outstanding", 0.0))
			ap_outstanding = flt(secondary_dict[party].get("outstanding", 0.0))
			net_balance = ar_outstanding - ap_outstanding
			
			# Only show in Receivable if net balance is positive (debit)
			if net_balance <= 0:
				processed_common_parties.add(party)
				continue  # Skip this party, it will appear in Payable report
			
			# Net balance is positive, show in Receivable
			# Make a copy so we don't overwrite main_dict
			updated_row = row.copy()
			
			# Subtract AP amounts from AR amounts for all currency fields
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
						# For Receivable: secondary is Customer, primary is Supplier
						# Check if primary Supplier has AP outstanding in secondary_dict
						if primary_party_for_secondary in secondary_dict:
							primary_row = secondary_dict[primary_party_for_secondary]
							updated_row["secondary_party_type"] = primary_row["party_type"]
							updated_row["secondary_party"] = primary_party_for_secondary
							# Net AR - AP for all currency fields
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
		
		# Only add if outstanding is positive after adjustments
		if flt(updated_row.get("outstanding", 0.0)) > 0:
			party_name = updated_row.get("party_name") or party
			
			# Get Receivable accounts to filter Party GL by account_type
			receivable_accounts = frappe.get_all(
				"Account",
				filters={"account_type": "Receivable", "company": company},
				pluck="name"
			)
			account_filter = quote(",".join(receivable_accounts)) if receivable_accounts else "undefined"
			
			gl_url = f"/app/query-report/Party%20GL?company={quote(company)}&from_date={quote(str(from_date))}&to_date={quote(str(to_date))}&account={account_filter}&party=%5B%22{quote(party)}%22%5D&party_name={quote(party_name)}&group_by=Group+by+Voucher+%28Consolidated%29&project=undefined&include_dimensions=1&include_default_book_entries=1"
			button_html = f'<a href="{gl_url}" target="_blank" class="btn btn-xs btn-default">GL: {party_name}</a>'

			updated_row["party_gl_link"] = button_html
			
			# Add the 2 new columns:
			# 1. Received Invoice Amount (if party linked to supplier, then supplier's received invoice including debit note)
			updated_row["received_invoice_amount"] = flt(supplier_amounts.get(party, {}).get("received_invoice_amount", 0.0))
			
			# 2. Invoiced Amount (Invoices we sent to customer incl credit note)
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

		if self.filters.show_gl_balance:
			gl_balance_map = get_gl_balance(self.filters.report_date, self.filters.company, self.account_type)

		# Calculate opening balances
		# For Receivable (Asset): debit - credit (positive = customer owes us)
		# For Payable (Liability): credit - debit (positive = we owe supplier)
		opening_balances = {}
		if self.filters.get("from_date"):
			for party_type in self.party_type:
				accounts = frappe.get_all(
					"Account",
					filters={"account_type": self.account_type, "company": self.filters.company},
					pluck="name"
				)
				if not accounts:
					continue

				# Use different formula based on account type
				if self.account_type == "Payable":
					# For Payable: credit - debit (positive means we owe)
					balance_formula = "SUM(credit) - SUM(debit)"
				else:
					# For Receivable: debit - credit (positive means customer owes)
					balance_formula = "SUM(debit) - SUM(credit)"

				opening_entries = frappe.db.sql(f"""
					SELECT party, {balance_formula} as balance
					FROM `tabGL Entry`
					WHERE posting_date < %s
					AND party_type = %s
					AND account in %s
					AND company = %s
					AND is_cancelled = 0
					GROUP BY party
				""", (self.filters.from_date, party_type, tuple(accounts), self.filters.company), as_dict=1)

				for entry in opening_entries:
					if entry.party:
						opening_balances[entry.party] = entry.balance

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

			# Add opening balance
			row.opening = opening_balances.get(party, 0.0)

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
			self.add_column(_("Opening Balance"), fieldname="opening")
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


def get_gl_balance(report_date, company, account_type):
	"""
	Get GL balance for parties filtered by account_type.
	For Receivable (Asset): debit - credit (positive = customer owes us)
	For Payable (Liability): credit - debit (positive = we owe supplier)
	"""
	# Get accounts of the specified account_type
	accounts = frappe.get_all(
		"Account",
		filters={"account_type": account_type, "company": company},
		pluck="name"
	)
	
	if not accounts:
		return frappe._dict()
	
	# Use different formula based on account type
	if account_type == "Payable":
		# For Payable: credit - debit (positive means we owe)
		balance_formula = "SUM(credit) - SUM(debit)"
	else:
		# For Receivable: debit - credit (positive means customer owes)
		balance_formula = "SUM(debit) - SUM(credit)"
	
	balance_data = frappe.db.sql(f"""
		SELECT party, {balance_formula} as balance
		FROM `tabGL Entry`
		WHERE posting_date <= %s
		AND account IN %s
		AND company = %s
		AND is_cancelled = 0
		GROUP BY party
	""", (report_date, tuple(accounts), company), as_dict=1)
	
	return frappe._dict([(d.party, d.balance) for d in balance_data if d.party])