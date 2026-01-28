# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import copy
from collections import OrderedDict

import frappe
from frappe import _, _dict
from frappe.query_builder import Criterion
from frappe.utils import cstr, getdate

from erpnext import get_company_currency, get_default_company
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
	get_dimension_with_children,
)
from erpnext.accounts.report.financial_statements import get_cost_centers_with_children
from erpnext.accounts.report.utils import convert_to_presentation_currency, get_currency
from erpnext.accounts.utils import get_account_currency


def execute(filters=None):
	if not filters:
		return [], []

	account_details = {}
	if filters and filters.get("print_in_account_currency") and not filters.get("account"):
		frappe.throw(_("Select an account to print in account currency"))

	for acc in frappe.db.sql("""select name, is_group from tabAccount""", as_dict=1):
		account_details.setdefault(acc.name, acc)

	if filters.get("party"):
		filters.party = frappe.parse_json(filters.get("party"))

		filters.party = get_complete_party_list(filters.get("party"))

	if filters.get("voucher_no") and not filters.get("group_by"):
		filters.group_by = "Group by Voucher (Consolidated)"

	validate_filters(filters, account_details)

	validate_party(filters)

	filters = set_account_currency(filters)

	columns = get_columns(filters)

	res = get_result(filters, account_details)

	return columns, res


def validate_filters(filters, account_details):
	if not filters.get("company"):
		frappe.throw(_("{0} is mandatory").format(_("Company")))

	if not filters.get("from_date") and not filters.get("to_date"):
		frappe.throw(
			_("{0} and {1} are mandatory").format(frappe.bold(_("From Date")), frappe.bold(_("To Date")))
		)

	if filters.get("account"):
		filters.account = frappe.parse_json(filters.get("account"))
		for account in filters.account:
			if not account_details.get(account):
				frappe.throw(_("Account {0} does not exists").format(account))

	if filters.get("account") and filters.get("group_by") == "Group by Account":
		filters.account = frappe.parse_json(filters.get("account"))
		for account in filters.account:
			if account_details[account].is_group == 0:
				frappe.throw(_("Can not filter based on Child Account, if grouped by Account"))

	if filters.get("voucher_no") and filters.get("group_by") in ["Group by Voucher"]:
		frappe.throw(_("Can not filter based on Voucher No, if grouped by Voucher"))

	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date must be before To Date"))

	if filters.get("project"):
		filters.project = frappe.parse_json(filters.get("project"))

	if filters.get("cost_center"):
		filters.cost_center = frappe.parse_json(filters.get("cost_center"))


def validate_party(filters):
	party_type, party = filters.get("party_type"), filters.get("party")

	if party and party_type:
		for d in party:
			if not frappe.db.exists(party_type, d):
				frappe.throw(_("Invalid {0}: {1}").format(party_type, d))


def set_account_currency(filters):
	if filters.get("account") or (filters.get("party") and len(filters.party) == 1):
		filters["company_currency"] = frappe.get_cached_value("Company", filters.company, "default_currency")
		account_currency = None

		if filters.get("account"):
			if len(filters.get("account")) == 1:
				account_currency = get_account_currency(filters.account[0])
			else:
				currency = get_account_currency(filters.account[0])
				is_same_account_currency = True
				for account in filters.get("account"):
					if get_account_currency(account) != currency:
						is_same_account_currency = False
						break

				if is_same_account_currency:
					account_currency = currency

		elif filters.get("party") and filters.get("party_type"):
			gle_currency = frappe.db.get_value(
				"GL Entry",
				{"party_type": filters.party_type, "party": filters.party[0], "company": filters.company},
				"account_currency",
			)

			if gle_currency:
				account_currency = gle_currency
			else:
				account_currency = (
					None
					if filters.party_type in ["Employee", "Shareholder", "Member"]
					else frappe.get_cached_value(filters.party_type, filters.party[0], "default_currency")
				)

		filters["account_currency"] = account_currency or filters.company_currency
		if filters.account_currency != filters.company_currency and not filters.presentation_currency:
			filters.presentation_currency = filters.account_currency

	return filters


def get_result(filters, account_details):
	accounting_dimensions = []
	if filters.get("include_dimensions"):
		accounting_dimensions = get_accounting_dimensions()

	gl_entries = get_gl_entries(filters, accounting_dimensions)

	data = get_data_with_opening_closing(filters, account_details, accounting_dimensions, gl_entries)

	result = get_result_as_list(data, filters)

	return result


def get_gl_entries(filters, accounting_dimensions):
	currency_map = get_currency(filters)
	select_fields = """, debit, credit, debit_in_account_currency,
		credit_in_account_currency,remarks """

	if filters.get("show_remarks"):
		if remarks_length := frappe.db.get_single_value("Accounts Settings", "general_ledger_remarks_length"):
			select_fields += f",substr(remarks, 1, {remarks_length}) as 'remarks'"
		else:
			select_fields += """,remarks"""

	order_by_statement = "order by posting_date, account, creation"

	if filters.get("include_dimensions"):
		order_by_statement = "order by posting_date, creation"

	if filters.get("group_by") == "Group by Voucher":
		order_by_statement = "order by posting_date, voucher_type, voucher_no"
	if filters.get("group_by") == "Group by Account":
		order_by_statement = "order by account, posting_date, creation"

	if filters.get("include_default_book_entries"):
		filters["company_fb"] = frappe.get_cached_value(
			"Company", filters.get("company"), "default_finance_book"
		)

	dimension_fields = ""
	if accounting_dimensions:
		dimension_fields = ", ".join(accounting_dimensions) + ","

	transaction_currency_fields = ""
	if filters.get("add_values_in_transaction_currency"):
		transaction_currency_fields = (
			"debit_in_transaction_currency, credit_in_transaction_currency, transaction_currency,"
		)

	gl_entries = frappe.db.sql(
		f"""
		select
			name as gl_entry, posting_date, account, party_type, party,
			voucher_type, voucher_subtype, voucher_no, {dimension_fields}
			cost_center, project, {transaction_currency_fields}
			against_voucher_type, against_voucher, account_currency,
			against, is_opening, creation {select_fields}
		from `tabGL Entry`
		where company=%(company)s {get_conditions(filters)}
		{order_by_statement}
	""",
		filters,
		as_dict=1,
	)

	if filters.get("presentation_currency"):
		return convert_to_presentation_currency(gl_entries, currency_map)
	else:
		return gl_entries


def get_conditions(filters):
	conditions = []

	if filters.get("account"):
		filters.account = get_accounts_with_children(filters.account)
		if filters.account:
			conditions.append("account in %(account)s")

	if filters.get("cost_center"):
		filters.cost_center = get_cost_centers_with_children(filters.cost_center)
		conditions.append("cost_center in %(cost_center)s")

	if filters.get("voucher_no"):
		conditions.append("voucher_no=%(voucher_no)s")

	if filters.get("against_voucher_no"):
		conditions.append("against_voucher=%(against_voucher_no)s")

	if filters.get("ignore_err"):
		err_journals = frappe.db.get_all(
			"Journal Entry",
			filters={
				"company": filters.get("company"),
				"docstatus": 1,
				"voucher_type": ("in", ["Exchange Rate Revaluation", "Exchange Gain Or Loss"]),
			},
			as_list=True,
		)
		if err_journals:
			filters.update({"voucher_no_not_in": [x[0] for x in err_journals]})

	if filters.get("ignore_cr_dr_notes"):
		system_generated_cr_dr_journals = frappe.db.get_all(
			"Journal Entry",
			filters={
				"company": filters.get("company"),
				"docstatus": 1,
				"voucher_type": ("in", ["Credit Note", "Debit Note"]),
				"is_system_generated": 1,
			},
			as_list=True,
		)
		if system_generated_cr_dr_journals:
			vouchers_to_ignore = (filters.get("voucher_no_not_in") or []) + [
				x[0] for x in system_generated_cr_dr_journals
			]
			filters.update({"voucher_no_not_in": vouchers_to_ignore})

	if filters.get("voucher_no_not_in"):
		conditions.append("voucher_no not in %(voucher_no_not_in)s")

	if filters.get("group_by") == "Group by Party" and not filters.get("party_type"):
		conditions.append("party_type in ('Customer', 'Supplier')")

	if filters.get("party_type"):
		conditions.append("party_type=%(party_type)s")

	if filters.get("party"):
		conditions.append("party in %(party)s")

	if not (
		filters.get("account")
		or filters.get("party")
		or filters.get("group_by") in ["Group by Account", "Group by Party"]
	):
		conditions.append("(posting_date >=%(from_date)s or is_opening = 'Yes')")

	conditions.append("(posting_date <=%(to_date)s or is_opening = 'Yes')")

	if filters.get("project"):
		conditions.append("project in %(project)s")

	if filters.get("include_default_book_entries"):
		if filters.get("finance_book"):
			if filters.get("company_fb") and cstr(filters.get("finance_book")) != cstr(
				filters.get("company_fb")
			):
				frappe.throw(
					_("To use a different finance book, please uncheck 'Include Default FB Entries'")
				)
			else:
				conditions.append("(finance_book in (%(finance_book)s, '') OR finance_book IS NULL)")
		else:
			conditions.append("(finance_book in (%(company_fb)s, '') OR finance_book IS NULL)")
	else:
		if filters.get("finance_book"):
			conditions.append("(finance_book in (%(finance_book)s, '') OR finance_book IS NULL)")
		else:
			conditions.append("(finance_book in ('') OR finance_book IS NULL)")

	if not filters.get("show_cancelled_entries"):
		conditions.append("is_cancelled = 0")
	
	# Exclude system-generated Journal Entries (used for inter-party settlements etc.)
	conditions.append("voucher_no NOT IN (SELECT name FROM `tabJournal Entry` WHERE is_system_generated = 1)")

	from frappe.desk.reportview import build_match_conditions

	match_conditions = build_match_conditions("GL Entry")

	if match_conditions:
		conditions.append(match_conditions)

	accounting_dimensions = get_accounting_dimensions(as_list=False)

	if accounting_dimensions:
		for dimension in accounting_dimensions:
			# Ignore 'Finance Book' set up as dimension in below logic, as it is already handled in above section
			if not dimension.disabled and dimension.document_type != "Finance Book":
				if filters.get(dimension.fieldname):
					if frappe.get_cached_value("DocType", dimension.document_type, "is_tree"):
						filters[dimension.fieldname] = get_dimension_with_children(
							dimension.document_type, filters.get(dimension.fieldname)
						)
						conditions.append(f"{dimension.fieldname} in %({dimension.fieldname})s")
					else:
						conditions.append(f"{dimension.fieldname} in %({dimension.fieldname})s")

	return "and {}".format(" and ".join(conditions)) if conditions else ""


def get_accounts_with_children(accounts):
	if not isinstance(accounts, list):
		accounts = [d.strip() for d in accounts.strip().split(",") if d]

	if not accounts:
		return

	doctype = frappe.qb.DocType("Account")
	accounts_data = (
		frappe.qb.from_(doctype)
		.select(doctype.lft, doctype.rgt)
		.where(doctype.name.isin(accounts))
		.run(as_dict=True)
	)

	conditions = []
	for account in accounts_data:
		conditions.append((doctype.lft >= account.lft) & (doctype.rgt <= account.rgt))

	return frappe.qb.from_(doctype).select(doctype.name).where(Criterion.any(conditions)).run(pluck=True)


def set_bill_no(gl_entries):
	inv_details = get_supplier_invoice_details()
	for gl in gl_entries:
		gl["bill_no"] = inv_details.get(gl.get("against_voucher"), "")


def get_data_with_opening_closing(filters, account_details, accounting_dimensions, gl_entries):
	data = []
	totals_dict = get_totals_dict()

	set_bill_no(gl_entries)

	gle_map = initialize_gle_map(gl_entries, filters, totals_dict)

	totals, entries = get_accountwise_gle(filters, accounting_dimensions, gl_entries, gle_map, totals_dict)

	# Opening for filtered account
	data.append(totals.opening)

	if filters.get("group_by") != "Group by Voucher (Consolidated)":
		for _acc, acc_dict in gle_map.items():
			# acc
			if acc_dict.entries:
				# opening
				data.append({"debit_in_transaction_currency": None, "credit_in_transaction_currency": None})
				if filters.get("group_by") != "Group by Voucher":
					data.append(acc_dict.totals.opening)

				data += acc_dict.entries

				# totals
				data.append(acc_dict.totals.total)

				# closing
				if filters.get("group_by") != "Group by Voucher":
					data.append(acc_dict.totals.closing)

		data.append({"debit_in_transaction_currency": None, "credit_in_transaction_currency": None})
	else:
		data += entries

	# totals
	# data.append(totals.total)

	# closing
	data.append(totals.closing)

	return data


def get_totals_dict():
	def _get_debit_credit_dict(label):
		return _dict(
			account=f"'{label}'",
			debit=0.0,
			credit=0.0,
			debit_in_account_currency=0.0,
			credit_in_account_currency=0.0,
			debit_in_transaction_currency=None,
			credit_in_transaction_currency=None,
		)

	return _dict(
		opening=_get_debit_credit_dict(_("Opening")),
		total=_get_debit_credit_dict(_("Total")),
		closing=_get_debit_credit_dict(_("Closing")),
	)


def group_by_field(group_by):
	if group_by == "Group by Party":
		return "party"
	elif group_by in ["Group by Voucher (Consolidated)", "Group by Account"]:
		return "account"
	else:
		return "voucher_no"


def initialize_gle_map(gl_entries, filters, totals_dict):
	gle_map = OrderedDict()
	group_by = group_by_field(filters.get("group_by"))

	for gle in gl_entries:
		gle_map.setdefault(gle.get(group_by), _dict(totals=copy.deepcopy(totals_dict), entries=[]))
	return gle_map


def get_accountwise_gle(filters, accounting_dimensions, gl_entries, gle_map, totals):
	entries = []
	consolidated_gle = OrderedDict()
	group_by = group_by_field(filters.get("group_by"))
	group_by_voucher_consolidated = filters.get("group_by") == "Group by Voucher (Consolidated)"

	if filters.get("show_net_values_in_party_account"):
		account_type_map = get_account_type_map(filters.get("company"))

	immutable_ledger = frappe.db.get_single_value("Accounts Settings", "enable_immutable_ledger")

	def update_value_in_dict(data, key, gle):
		data[key].debit += gle.debit
		data[key].credit += gle.credit

		data[key].debit_in_account_currency += gle.debit_in_account_currency
		data[key].credit_in_account_currency += gle.credit_in_account_currency

		if filters.get("add_values_in_transaction_currency") and key not in ["opening", "closing", "total"]:
			data[key].debit_in_transaction_currency += gle.debit_in_transaction_currency
			data[key].credit_in_transaction_currency += gle.credit_in_transaction_currency

		if filters.get("show_net_values_in_party_account") and account_type_map.get(data[key].account) in (
			"Receivable",
			"Payable",
		):
			net_value = data[key].debit - data[key].credit
			net_value_in_account_currency = (
				data[key].debit_in_account_currency - data[key].credit_in_account_currency
			)

			if net_value < 0:
				dr_or_cr = "credit"
				rev_dr_or_cr = "debit"
			else:
				dr_or_cr = "debit"
				rev_dr_or_cr = "credit"

			data[key][dr_or_cr] = abs(net_value)
			data[key][dr_or_cr + "_in_account_currency"] = abs(net_value_in_account_currency)
			data[key][rev_dr_or_cr] = 0
			data[key][rev_dr_or_cr + "_in_account_currency"] = 0

		if data[key].against_voucher and gle.against_voucher:
			data[key].against_voucher += ", " + gle.against_voucher

	from_date, to_date = getdate(filters.from_date), getdate(filters.to_date)
	show_opening_entries = filters.get("show_opening_entries")

	for gle in gl_entries:
		group_by_value = gle.get(group_by)
		gle.voucher_subtype = _(gle.voucher_subtype)
		gle.against_voucher_type = _(gle.against_voucher_type)
		gle.remarks = _(gle.remarks)
		gle.party_type = _(gle.party_type)

		if gle.posting_date < from_date or (cstr(gle.is_opening) == "Yes" and not show_opening_entries):
			if not group_by_voucher_consolidated:
				update_value_in_dict(gle_map[group_by_value].totals, "opening", gle)
				update_value_in_dict(gle_map[group_by_value].totals, "closing", gle)

			update_value_in_dict(totals, "opening", gle)
			update_value_in_dict(totals, "closing", gle)

		elif gle.posting_date <= to_date or (cstr(gle.is_opening) == "Yes" and show_opening_entries):
			if not group_by_voucher_consolidated:
				update_value_in_dict(gle_map[group_by_value].totals, "total", gle)
				update_value_in_dict(gle_map[group_by_value].totals, "closing", gle)
				update_value_in_dict(totals, "total", gle)
				update_value_in_dict(totals, "closing", gle)

				gle_map[group_by_value].entries.append(gle)

			elif group_by_voucher_consolidated:
				keylist = [
					gle.get("posting_date"),
					gle.get("voucher_type"),
					gle.get("voucher_no"),
					gle.get("account"),
					gle.get("party_type"),
					gle.get("party"),
				]

				if immutable_ledger:
					keylist.append(gle.get("creation"))

				if filters.get("include_dimensions"):
					for dim in accounting_dimensions:
						keylist.append(gle.get(dim))
					keylist.append(gle.get("cost_center"))

				key = tuple(keylist)
				if key not in consolidated_gle:
					consolidated_gle.setdefault(key, gle)
				else:
					update_value_in_dict(consolidated_gle, key, gle)

	for value in consolidated_gle.values():
		update_value_in_dict(totals, "total", value)
		update_value_in_dict(totals, "closing", value)
		entries.append(value)

	return totals, entries


def get_account_type_map(company):
	account_type_map = frappe._dict(
		frappe.get_all("Account", fields=["name", "account_type"], filters={"company": company}, as_list=1)
	)

	return account_type_map


def get_result_as_list(data, filters):
	balance, _balance_in_account_currency = 0, 0
	supplier_invoice_details = get_supplier_invoice_details()  # Fetch bill_no details
	
	# Collect all voucher_nos by type for batch queries
	voucher_nos_by_type = collect_voucher_nos_by_type(data)
	
	# Batch fetch references for Payment Entry and Journal Entry
	payment_references = get_payment_entry_references(voucher_nos_by_type.get("Payment Entry", []))
	journal_references = get_journal_entry_references(voucher_nos_by_type.get("Journal Entry", []))
	
	# Batch fetch return status for Sales Invoice and Purchase Invoice
	invoice_return_status = get_invoice_return_status(
		voucher_nos_by_type.get("Sales Invoice", []),
		voucher_nos_by_type.get("Purchase Invoice", [])
	)

	for d in data:
		if not d.get("posting_date"):
			balance, _balance_in_account_currency = 0, 0

		balance = get_balance(d, balance, "debit", "credit")

		if d.get("voucher_no") or d.get("remarks"):
			d["reference_with_remarks"] = f"{d.get('voucher_no', '')} {d.get('remarks', '')}".strip()

		d["balance"] = balance

		if balance >= 0:
			d["balance"] = f"{frappe.format_value(balance, {'fieldtype': 'Currency', 'options': filters.account_currency})} Dr"
		else:
			d["balance"] = f"{frappe.format_value(abs(balance), {'fieldtype': 'Currency', 'options': filters.account_currency})} Cr"

		# Get supplier bill details (bill_no and bill_date)
		bill_info = supplier_invoice_details.get(d.get("voucher_no"), {})
		if isinstance(bill_info, dict):
			d["bill_no"] = bill_info.get("bill_no", "")
			d["bill_date"] = bill_info.get("bill_date", "")
		else:
			d["bill_no"] = bill_info or ""
			d["bill_date"] = ""
		
		# Get voucher info for reference lookups
		voucher_no = d.get("voucher_no")
		voucher_type = d.get("voucher_type")
		
		# Add ref_no for Payment Entry and Journal Entry
		if voucher_type == "Payment Entry" and voucher_no in payment_references:
			d["ref_no"] = payment_references[voucher_no]
		elif voucher_type == "Journal Entry" and voucher_no in journal_references:
			d["ref_no"] = journal_references[voucher_no]
		else:
			d["ref_no"] = ""
		
		# Override voucher_subtype for Sales Invoice / Purchase Invoice returns
		if voucher_type == "Sales Invoice" and voucher_no in invoice_return_status:
			if invoice_return_status[voucher_no].get("is_return"):
				d["voucher_subtype"] = _("Credit Note")
		elif voucher_type == "Purchase Invoice" and voucher_no in invoice_return_status:
			if invoice_return_status[voucher_no].get("is_return"):
				d["voucher_subtype"] = _("Debit Note")

		d["account_currency"] = filters.account_currency

	return data


def collect_voucher_nos_by_type(data):
	"""
	Collect all voucher numbers grouped by voucher type for efficient batch queries.
	Returns dict: {voucher_type: [list of voucher_nos]}
	"""
	voucher_nos_by_type = {}
	for d in data:
		voucher_type = d.get("voucher_type")
		voucher_no = d.get("voucher_no")
		if voucher_type and voucher_no:
			if voucher_type not in voucher_nos_by_type:
				voucher_nos_by_type[voucher_type] = set()
			voucher_nos_by_type[voucher_type].add(voucher_no)
	
	# Convert sets to lists for SQL queries
	return {k: list(v) for k, v in voucher_nos_by_type.items()}


def get_supplier_invoice_details():
	"""Fetch bill_no and bill_date from Purchase Invoice."""
	inv_details = {}
	for d in frappe.db.sql(
		""" select name, bill_no, bill_date from `tabPurchase Invoice`
		where docstatus = 1 and bill_no is not null and bill_no != '' """,
		as_dict=1,
	):
		inv_details[d.name] = {
			"bill_no": d.bill_no,
			"bill_date": d.bill_date
		}

	return inv_details


def get_payment_entry_references(voucher_nos=None):
	"""
	Fetch reference_no (Cheque/Reference No) for Payment Entries.
	
	Args:
		voucher_nos: List of Payment Entry names to filter. If None, fetches all.
	
	Returns:
		dict: {payment_entry_name: reference_no}
	"""
	ref_details = {}
	
	if voucher_nos is not None and not voucher_nos:
		return ref_details  # No Payment Entries to look up
	
	conditions = "docstatus = 1 and reference_no is not null and reference_no != ''"
	if voucher_nos:
		conditions += " and name in %(voucher_nos)s"
	
	for d in frappe.db.sql(
		f""" select name, reference_no from `tabPayment Entry`
		where {conditions} """,
		{"voucher_nos": voucher_nos} if voucher_nos else {},
		as_dict=1,
	):
		ref_details[d.name] = d.reference_no

	return ref_details


def get_journal_entry_references(voucher_nos=None):
	"""
	Fetch cheque_no (Reference Number) for Journal Entries.
	
	Args:
		voucher_nos: List of Journal Entry names to filter. If None, fetches all.
	
	Returns:
		dict: {journal_entry_name: cheque_no}
	"""
	ref_details = {}
	
	if voucher_nos is not None and not voucher_nos:
		return ref_details  # No Journal Entries to look up
	
	conditions = "docstatus = 1 and cheque_no is not null and cheque_no != ''"
	if voucher_nos:
		conditions += " and name in %(voucher_nos)s"
	
	for d in frappe.db.sql(
		f""" select name, cheque_no from `tabJournal Entry`
		where {conditions} """,
		{"voucher_nos": voucher_nos} if voucher_nos else {},
		as_dict=1,
	):
		ref_details[d.name] = d.cheque_no

	return ref_details


def get_invoice_return_status(sales_invoice_nos=None, purchase_invoice_nos=None):
	"""
	Fetch is_return status for Sales Invoices and Purchase Invoices.
	
	Args:
		sales_invoice_nos: List of Sales Invoice names to check
		purchase_invoice_nos: List of Purchase Invoice names to check
	
	Returns:
		dict: {invoice_name: {"is_return": bool, "doctype": str}}
	"""
	return_status = {}
	
	# Fetch Sales Invoice return status
	if sales_invoice_nos:
		for d in frappe.db.sql(
			""" select name, is_return from `tabSales Invoice`
			where docstatus = 1 and name in %(voucher_nos)s """,
			{"voucher_nos": sales_invoice_nos},
			as_dict=1,
		):
			return_status[d.name] = {"is_return": d.is_return, "doctype": "Sales Invoice"}
	
	# Fetch Purchase Invoice return status
	if purchase_invoice_nos:
		for d in frappe.db.sql(
			""" select name, is_return from `tabPurchase Invoice`
			where docstatus = 1 and name in %(voucher_nos)s """,
			{"voucher_nos": purchase_invoice_nos},
			as_dict=1,
		):
			return_status[d.name] = {"is_return": d.is_return, "doctype": "Purchase Invoice"}
	
	return return_status


def get_balance(row, balance, debit_field, credit_field):
	balance += row.get(debit_field, 0) - row.get(credit_field, 0)

	return balance



def get_columns(filters):
    # Define currency based on presentation or company
    if filters.get("presentation_currency"):
        currency = filters["presentation_currency"]
    else:
        if filters.get("company"):
            currency = get_company_currency(filters["company"])
        else:
            company = get_default_company()
            currency = get_company_currency(company)

    # Define columns to show only the required fields
    columns = [
        {"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
        {
            "label": _("Voucher Type"),
            "fieldname": "voucher_subtype",
            "fieldtype": "Data",
            "width": 120,
        },
        {
            "label": _("Reference"),
            "fieldname": "voucher_no",
            "fieldtype": "Dynamic Link",
            "options": "voucher_type",
            "width": 180,
        },
        {"label": _("Ref No"), "fieldname": "ref_no", "fieldtype": "Data", "width": 120},  # Cheque/Reference No
        {"label": _("Bill No"), "fieldname": "bill_no", "fieldtype": "Data", "width": 100},  # Supplier Bill No
        {"label": _("Bill Date"), "fieldname": "bill_date", "fieldtype": "Date", "width": 90},  # Supplier Bill Date
        {"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 250},
        {
            "label": _("Debit ({0})").format(currency),
            "fieldname": "debit",
            "fieldtype": "Float",
            "width": 130,
        },
        {
            "label": _("Credit ({0})").format(currency),
            "fieldname": "credit",
            "fieldtype": "Float",
            "width": 130,
        },
        {
            "label": _("Balance (Dr - Cr)"),
            "fieldname": "balance",
            "fieldtype": "Data",
            "width": 150,
        },
    ]

    return columns













def get_complete_party_list(parties):
    """Retrieve the complete list of parties including primary and secondary parties."""
    complete_party_list = set(parties)
    for party in parties:
        linked_parties = frappe.db.sql(
            """
            SELECT secondary_party FROM `tabParty Link`
            WHERE primary_party = %s
            UNION
            SELECT primary_party FROM `tabParty Link`
            WHERE secondary_party = %s
            """,
            (party, party),
            as_list=True
        )
        for linked_party in linked_parties:
            complete_party_list.add(linked_party[0])
    return list(complete_party_list)


@frappe.whitelist()
def get_statement_meta(filters):
    """
    Get all metadata needed for the statement print format:
    - Company info (name, logo, address)
    - Party info (name, address)
    - Ageing data
    - Future payments
    - Closing balance
    """
    from frappe.utils import flt, nowdate, today
    
    if isinstance(filters, str):
        filters = frappe.parse_json(filters)
    
    filters = frappe._dict(filters)
    
    meta = frappe._dict({
        "company": frappe._dict(),
        "party": frappe._dict(),
        "ageing": frappe._dict({
            "range1": 0, "range2": 0, "range3": 0, "range4": 0, "range5": 0
        }),
        "future_payments": [],
        "bank_details": frappe._dict(),
    })
    
    company = filters.get("company")
    party_list = filters.get("party")
    if isinstance(party_list, str):
        party_list = frappe.parse_json(party_list)
    
    party = party_list[0] if party_list and len(party_list) > 0 else None
    to_date = filters.get("to_date") or today()
    currency = filters.get("presentation_currency") or frappe.get_cached_value("Company", company, "default_currency")
    
    # 1. Company Info
    if company:
        company_doc = frappe.get_cached_doc("Company", company)
        
        # Extract PAN from GSTIN (characters 3-12, 0-indexed: 2:12)
        gstin = company_doc.get("gstin") or ""
        pan = gstin[2:12] if len(gstin) >= 12 else ""
        
        meta.company = frappe._dict({
            "name": company_doc.company_name,
            "logo": company_doc.get("logo_for_printing") or company_doc.get("company_logo") or "",
            "pan": pan,
            "gstin": gstin,
            "date_of_incorporation": company_doc.get("date_of_incorporation") or "",
            "previously_known_as": company_doc.get("bns_previously_known_as") or "",
            "cin": company_doc.get("bns_company_cin") or "",
            "msme_no": company_doc.get("bns_msme_no") or "",
            "msme_type": company_doc.get("bns_msme_type") or ""
        })
    
    # 2. Party Info
    if party:
        from frappe.contacts.doctype.address.address import get_default_address
        
        # Determine party type
        is_customer = frappe.db.exists("Customer", party)
        party_type = "Customer" if is_customer else "Supplier"
        
        meta.party.party_type = party_type
        meta.party.name = party
        
        # Get party document
        party_doc = frappe.get_doc(party_type, party)
        meta.party.party_name = party_doc.get("customer_name") if is_customer else party_doc.get("supplier_name")
        meta.party.tax_id = party_doc.get("tax_id") or ""
        
        # Get PAN from GSTIN (characters 3-12)
        party_gstin = party_doc.get("gstin") or ""
        meta.party.pan = party_gstin[2:12] if len(party_gstin) >= 12 else (party_doc.get("pan") or "")
        meta.party.gstin = party_gstin
        
        # Get address - simplified to just City, State, Country, Pincode
        address_name = None
        
        # Try primary address link first
        address_field = "customer_primary_address" if is_customer else "supplier_primary_address"
        address_name = party_doc.get(address_field)
        
        # Fallback to default address
        if not address_name:
            address_name = get_default_address(party_type, party)
        
        # Fallback to Dynamic Link
        if not address_name:
            address_links = frappe.get_all(
                "Dynamic Link",
                filters={
                    "link_doctype": party_type,
                    "link_name": party,
                    "parenttype": "Address"
                },
                fields=["parent"],
                limit=1
            )
            if address_links:
                address_name = address_links[0].parent
        
        # Build simplified address: City, State, Country, Pincode
        if address_name:
            try:
                addr_doc = frappe.get_doc("Address", address_name)
                addr_parts = []
                if addr_doc.city:
                    addr_parts.append(addr_doc.city)
                if addr_doc.state:
                    addr_parts.append(addr_doc.state)
                if addr_doc.country:
                    addr_parts.append(addr_doc.country)
                if addr_doc.pincode:
                    addr_parts.append(str(addr_doc.pincode))
                meta.party.address = ", ".join(addr_parts)
            except Exception:
                meta.party.address = ""
        else:
            meta.party.address = ""
        
        # 3. Ageing Data - Calculate from Payment Ledger Entry
        meta.ageing = get_party_ageing(company, party, party_type, to_date, currency)
        
        # 4. Bank Details (prefer party-specific default bank account, else company default)
        meta.bank_details = get_company_bank_details(company, party_type, party)
    
    return meta


def get_party_ageing(company, party, party_type, report_date, currency):
    """
    Calculate ageing from Payment Ledger Entry.
    Buckets: 0-30, 30-60, 60-90, 90-120, 120+
    """
    from frappe.utils import date_diff, getdate, flt
    
    ageing = frappe._dict({
        "range1": 0,  # 0-30
        "range2": 0,  # 30-60
        "range3": 0,  # 60-90
        "range4": 0,  # 90-120
        "range5": 0,  # 120+
    })
    
    report_date = getdate(report_date)
    
    try:
        # Get outstanding entries from Payment Ledger Entry
        ple = frappe.qb.DocType("Payment Ledger Entry")
        
        query = (
            frappe.qb.from_(ple)
            .select(
                ple.posting_date,
                ple.amount,
                ple.amount_in_account_currency
            )
            .where(ple.company == company)
            .where(ple.party_type == party_type)
            .where(ple.party == party)
            .where(ple.posting_date <= report_date)
            .where(ple.delinked == 0)
        )
        
        entries = query.run(as_dict=True)
        
        # Calculate outstanding per voucher and assign to buckets
        voucher_outstanding = {}
        for entry in entries:
            key = (entry.get("voucher_type"), entry.get("voucher_no"), entry.posting_date)
            if key not in voucher_outstanding:
                voucher_outstanding[key] = {"posting_date": entry.posting_date, "amount": 0}
            voucher_outstanding[key]["amount"] += flt(entry.amount)
        
        # Assign to ageing buckets based on posting date
        for key, data in voucher_outstanding.items():
            outstanding = data["amount"]
            if outstanding == 0:
                continue
            
            # For receivables, positive means outstanding; for payables, negative means outstanding
            if party_type == "Supplier":
                outstanding = -outstanding  # Payables are negative in PLE
            
            if outstanding <= 0:
                continue
                
            days = date_diff(report_date, data["posting_date"])
            
            if days <= 30:
                ageing.range1 += outstanding
            elif days <= 60:
                ageing.range2 += outstanding
            elif days <= 90:
                ageing.range3 += outstanding
            elif days <= 120:
                ageing.range4 += outstanding
            else:
                ageing.range5 += outstanding
                
    except Exception as e:
        frappe.log_error(f"Ageing calculation error: {str(e)}")
        # Fallback: Calculate from GL entries
        ageing = calculate_ageing_from_gl(company, party, party_type, report_date)
    
    return ageing


def calculate_ageing_from_gl(company, party, party_type, report_date):
    """
    Fallback: Calculate ageing directly from GL entries.
    Groups outstanding amounts by posting date age.
    """
    from frappe.utils import date_diff, getdate, flt
    
    ageing = frappe._dict({
        "range1": 0,  # 0-30
        "range2": 0,  # 30-60
        "range3": 0,  # 60-90
        "range4": 0,  # 90-120
        "range5": 0,  # 120+
    })
    
    report_date = getdate(report_date)
    
    # Get all GL entries for this party
    gl_entries = frappe.db.sql("""
        SELECT posting_date, debit, credit, voucher_no, voucher_type
        FROM `tabGL Entry`
        WHERE company = %s
        AND party = %s
        AND party_type = %s
        AND posting_date <= %s
        AND is_cancelled = 0
        ORDER BY posting_date
    """, (company, party, party_type, report_date), as_dict=True)
    
    # Calculate net amount per voucher and assign to buckets
    voucher_balances = {}
    for gle in gl_entries:
        key = (gle.voucher_type, gle.voucher_no)
        if key not in voucher_balances:
            voucher_balances[key] = {"posting_date": gle.posting_date, "balance": 0}
        voucher_balances[key]["balance"] += flt(gle.debit) - flt(gle.credit)
    
    # Assign to ageing buckets
    for key, data in voucher_balances.items():
        balance = data["balance"]
        if balance == 0:
            continue
            
        days = date_diff(report_date, data["posting_date"])
        
        if days <= 30:
            ageing.range1 += balance
        elif days <= 60:
            ageing.range2 += balance
        elif days <= 90:
            ageing.range3 += balance
        elif days <= 120:
            ageing.range4 += balance
        else:
            ageing.range5 += balance
    
    return ageing


def get_future_payments(party, currency):
    """Get future-dated payment entries for the party."""
    from frappe.utils import today, flt
    
    payments = frappe.db.get_all(
        "Payment Entry",
        filters={
            "party": party,
            "reference_date": [">", today()],
            "docstatus": 1
        },
        fields=["posting_date", "mode_of_payment", "reference_date", "paid_amount"],
        limit=10,
        order_by="reference_date asc"
    )
    
    return payments


def get_company_bank_details(company, party_type=None, party=None):
    """
    Get bank account details with preference:
    1) Default Bank Account for this party (party_type + party) within the company
    2) Fallback to company default bank account
    """
    filters = {"company": company, "is_default": 1}

    bank = None
    if party_type and party:
        bank = frappe.db.get_value(
            "Bank Account",
            {**filters, "party_type": party_type, "party": party},
            ["account_name", "bank", "bank_account_no", "branch_code", "iban"],
            as_dict=True,
        )

    if not bank:
        bank = frappe.db.get_value(
            "Bank Account",
            filters,
            ["account_name", "bank", "bank_account_no", "branch_code", "iban"],
            as_dict=True,
        )

    return bank or frappe._dict()


