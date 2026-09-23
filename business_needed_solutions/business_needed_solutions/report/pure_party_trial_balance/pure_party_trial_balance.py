# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""
Pure Party Trial Balance — receivables and payables of one party, on one line.

ERPNext's own "Trial Balance for Party" answers a narrower question than people read into it:

  1. It runs for ONE party type. A customer who is also a supplier is two separate runs, and
     nothing tells you the two rows belong to the same entity.
  2. It sums EVERY GL row carrying that party, whatever account it landed on — advances parked
     in a payable account, the BNS internal branch debtor/creditor, a misposted expense with a
     party on it. The total is "everything tagged with this party", not "what this party owes".
  3. It nets debit against credit per party (toggle_debit_credit), so the two sides are already
     merged before you can see them.

This report keeps the trial-balance shape — opening, movement, closing, each as Dr/Cr — and fixes
those three:

  * Both party types in one run, receivable and payable side by side.
  * "Pure": only accounts of type Receivable and Payable, and the BNS internal branch accounts
     dropped, because an internal branch balance is the company owing itself. Untick
     `only_pure_accounts` to fall back to ERPNext's every-account behaviour.
  * Linked customer/supplier pairs knocked off into a single net row, so a party you both buy
     from and sell to shows what is actually settleable.

The `erpnext_closing` column carries what "Trial Balance for Party" would print for the same
party over the same dates, and `purity_difference` the gap. A non-zero gap is not an error — it
is party-tagged value sitting outside the receivable/payable accounts, and it is exactly what
this report exists to surface.

Ageing, when switched on, is netted the way "Pure Accounts Receivable Summary" already nets it:
each bucket of the supplier side subtracted from the same bucket of the customer side, then
`redistribute_negative_ageing_buckets` applies any resulting negative FIFO against the oldest
positive bucket. Both functions are imported from that report rather than reimplemented, so the
app keeps one definition of netted ageing — if the convention changes there, it changes here.

The ageing is struck AS AT the To Date, not over the period: a bucket is "how long has this been
outstanding on the closing date", which has no meaning for a date range. The bucket total and the
closing balance answer different questions and will not always agree — ageing counts open
invoices, the trial balance counts the account. `total_due_vs_closing` reports that gap.
"""

import frappe
from erpnext.accounts.utils import get_currency_precision
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt, getdate

from business_needed_solutions.business_needed_solutions.report.pure_accounts_receivable_summary.pure_accounts_receivable_summary import (
	AccountsReceivablePayableSummary,
	redistribute_negative_ageing_buckets,
)

PARTY_TYPES = ("Customer", "Supplier")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	_validate_filters(filters)

	precision = get_currency_precision()
	currency = frappe.get_cached_value("Company", filters.company, "default_currency")

	pure_accounts = get_pure_accounts(filters)
	if filters.get("only_pure_accounts", 1) and not pure_accounts:
		frappe.throw(_("No Receivable or Payable accounts found for {0}.").format(filters.company))

	balances = get_party_balances(filters, pure_accounts if filters.get("only_pure_accounts", 1) else None)
	erpnext_balances = get_party_balances(filters, None) if filters.get("show_purity_check") else {}

	ageing, ranges = get_party_ageing(filters) if filters.get("show_ageing") else ({}, [])

	groups = build_link_groups(filters, set(balances) | set(erpnext_balances) | set(ageing))
	data = build_rows(filters, balances, erpnext_balances, ageing, ranges, groups, precision, currency)

	return get_columns(filters, ranges), data


def _validate_filters(filters):
	if not filters.get("company"):
		frappe.throw(_("Company is mandatory"))
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("From Date and To Date are mandatory"))
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date"))


# ─── accounts ────────────────────────────────────────────────────────────────


def get_pure_accounts(filters) -> list:
	"""Receivable and Payable accounts of the company, less the BNS internal branch pair.

	An internal branch debtor/creditor balance is one arm of the company owing the other, which
	is why it is dropped here even though its account_type is Receivable/Payable.
	"""
	accounts = frappe.get_all(
		"Account",
		filters={
			"company": filters.company,
			"account_type": ("in", ("Receivable", "Payable")),
			"is_group": 0,
		},
		pluck="name",
	)

	if filters.get("account"):
		chosen = filters.get("account")
		chosen = chosen if isinstance(chosen, (list, tuple)) else [chosen]
		accounts = [a for a in accounts if a in set(chosen)]

	if not filters.get("include_internal_accounts"):
		for account in get_internal_branch_accounts():
			if account in accounts:
				accounts.remove(account)

	return accounts


def get_internal_branch_accounts() -> list:
	"""The BNS internal branch debtor/creditor accounts, if the settings Single carries them.

	Read defensively: a site that has not migrated the doctype yet must degrade to "no internal
	accounts", never raise inside a report.
	"""
	try:
		settings = frappe.get_cached_doc("BNS Branch Accounting Settings")
	except Exception:
		return []

	return [
		account
		for account in (
			settings.get("internal_branch_debtor_account"),
			settings.get("internal_branch_creditor_account"),
		)
		if account
	]


# ─── balances ────────────────────────────────────────────────────────────────


def get_party_balances(filters, accounts=None) -> dict:
	"""{(party_type, party): {opening_debit, opening_credit, debit, credit}} over the period.

	Opening follows ERPNext: anything before From Date, plus opening entries dated inside the
	window, so a period that starts mid-year still shows the brought-forward balance.
	"""
	gle = frappe.qb.DocType("GL Entry")

	def _base():
		query = (
			frappe.qb.from_(gle)
			.select(gle.party_type, gle.party, Sum(gle.debit).as_("debit"), Sum(gle.credit).as_("credit"))
			.where(
				(gle.company == filters.company)
				& (gle.is_cancelled == 0)
				& (gle.party_type.isin(PARTY_TYPES))
				& (gle.party.notnull())
				& (gle.party != "")
			)
			.groupby(gle.party_type, gle.party)
		)
		if accounts is not None:
			query = query.where(gle.account.isin(accounts))
		if filters.get("party_type"):
			query = query.where(gle.party_type == filters.party_type)
		if filters.get("party"):
			query = query.where(gle.party == filters.party)
		return query

	opening_rows = (
		_base()
		.where(
			(gle.posting_date < filters.from_date)
			| ((gle.is_opening == "Yes") & (gle.posting_date <= filters.to_date))
		)
		.run(as_dict=True)
	)
	period_rows = (
		_base()
		.where(
			(gle.posting_date >= filters.from_date)
			& (gle.posting_date <= filters.to_date)
			& (gle.is_opening == "No")
		)
		.run(as_dict=True)
	)

	balances = {}
	for row in opening_rows:
		entry = balances.setdefault(
			(row.party_type, row.party),
			{"opening_debit": 0.0, "opening_credit": 0.0, "debit": 0.0, "credit": 0.0},
		)
		entry["opening_debit"] += flt(row.debit)
		entry["opening_credit"] += flt(row.credit)

	for row in period_rows:
		entry = balances.setdefault(
			(row.party_type, row.party),
			{"opening_debit": 0.0, "opening_credit": 0.0, "debit": 0.0, "credit": 0.0},
		)
		entry["debit"] += flt(row.debit)
		entry["credit"] += flt(row.credit)

	return balances


def toggle_debit_credit(debit, credit):
	"""Collapse a two-sided balance onto the side it actually sits on — ERPNext's own rule."""
	if flt(debit) > flt(credit):
		return flt(debit) - flt(credit), 0.0
	return 0.0, flt(credit) - flt(debit)


# ─── ageing ──────────────────────────────────────────────────────────────────


def get_party_ageing(filters):
	"""{(party_type, party): {range1..rangeN, total_due, outstanding}} as at the To Date.

	Struck through the same class "Pure Accounts Receivable Summary" uses, run once per side, so
	a bucket here means exactly what a bucket means there — including `adjust_running_accounts`,
	which applies a party's own unallocated advances FIFO to its oldest invoices before the two
	sides are netted against each other.
	"""
	ranges = [r.strip() for r in (filters.get("ranges") or "30, 60, 90, 120").split(",") if r.strip()]
	range_count = len(ranges) + 1
	bucket_fields = [f"range{i}" for i in range(1, range_count + 1)]

	ageing = {}
	for account_type, party_type, naming_by in (
		("Receivable", "Customer", ["Selling Settings", "cust_master_name"]),
		("Payable", "Supplier", ["Buying Settings", "supp_master_name"]),
	):
		if filters.get("party_type") and filters.get("party_type") != party_type:
			continue

		# The AR/AP engine takes ONE party_account, and defaults to every account of the type when
		# given none. Left at its default it would age the internal branch account the balances
		# deliberately exclude, and the buckets would stop tying to the closing figures beside
		# them — so run it once per pure account and merge.
		accounts = _side_accounts(filters, account_type)

		for account in accounts or [None]:
			side_filters = frappe._dict(
				{
					"company": filters.company,
					"report_date": filters.to_date,
					"ageing_based_on": filters.get("ageing_based_on") or "Due Date",
					"range": ", ".join(ranges),
					"adjust_running_accounts": filters.get("adjust_running_accounts", 1),
					"party_type": party_type,
					"party": [filters.party] if filters.get("party") else [],
					"party_account": account,
					"show_gl_balance": 0,
					"show_future_payments": 0,
				}
			)

			try:
				_columns, rows = AccountsReceivablePayableSummary(side_filters).run(
					{"account_type": account_type, "naming_by": naming_by}
				)
			except Exception:
				# Ageing is an add-on to a trial balance: if the AR/AP engine cannot run for a
				# side, the balances must still report. Log and carry on without those buckets.
				frappe.log_error(
					title=f"Pure Party Trial Balance: ageing failed for {account_type}",
					message=frappe.get_traceback(),
				)
				continue

			for row in rows:
				party = row.get("party")
				if not party:
					continue
				entry = ageing.setdefault(
					(party_type, party),
					dict.fromkeys([*bucket_fields, "total_due", "outstanding"], 0.0),
				)
				for field in bucket_fields:
					entry[field] += flt(row.get(field))
				entry["total_due"] += flt(row.get("total_due"))
				entry["outstanding"] += flt(row.get("outstanding"))

	return ageing, ranges


def _side_accounts(filters, account_type):
	"""The pure accounts of one side, or None to let ERPNext age every account of that type."""
	if not filters.get("only_pure_accounts", 1):
		return None

	pure = set(get_pure_accounts(filters))
	if not pure:
		return None

	return [
		account
		for account in frappe.get_all(
			"Account",
			filters={"company": filters.company, "account_type": account_type, "is_group": 0},
			pluck="name",
		)
		if account in pure
	]


def _net_ageing(members, ageing, ranges, filters, precision) -> dict:
	"""Net a group's buckets the way Pure Accounts Receivable Summary nets them.

	Bucket minus same bucket — but oriented to the side the group actually lands on. The two pure
	reports each show their own side positive, because a payable is not a negative receivable; if
	this report simply subtracted supplier from customer, every payable row would come out
	negative and the redistribution below would wipe it to nothing. So the dominant side leads and
	`ageing_side` says which one it is.

	A supplier payable aged 10 days knocking off a customer receivable aged 90 still leaves a
	negative near bucket, which is what the redistribution is for: it pushes that negative onto
	the oldest positive bucket and preserves the total, rather than reporting a negative age band.
	"""
	bucket_fields = [f"range{i}" for i in range(1, len(ranges) + 2)]
	customer = dict.fromkeys([*bucket_fields, "total_due"], 0.0)
	supplier = dict.fromkeys([*bucket_fields, "total_due"], 0.0)

	found = False
	for party_type, party in members:
		entry = ageing.get((party_type, party))
		if not entry:
			continue
		found = True
		side = customer if party_type == "Customer" else supplier
		for field in [*bucket_fields, "total_due"]:
			side[field] += flt(entry.get(field))

	if not found:
		return {}

	receivable_leads = customer["total_due"] >= supplier["total_due"]
	lead, trail = (customer, supplier) if receivable_leads else (supplier, customer)

	row = {field: lead[field] - trail[field] for field in [*bucket_fields, "total_due"]}
	row["ageing_side"] = _("Receivable") if receivable_leads else _("Payable")

	# Default ON, matching the filter: without it a knocked-off pair keeps negative age bands.
	if filters.get("adjust_running_accounts", 1):
		redistribute_negative_ageing_buckets(row, bucket_fields)

	for field in [*bucket_fields, "total_due"]:
		row[field] = flt(row[field], precision)
	return row


# ─── customer ↔ supplier knock-off ───────────────────────────────────────────


def build_link_groups(filters, party_keys) -> dict:
	"""Map each (party_type, party) onto the key of the entity it belongs to.

	A Party Link is the authority. When `match_unlinked_by_pan` is on, parties sharing a PAN are
	grouped too — the same pairing the "Unlinked Customer Supplier by PAN" report offers to
	create, so the trial balance can net them before anyone clicks Create.
	"""
	groups = {key: key for key in party_keys}
	if not filters.get("knock_off_linked_parties", 1):
		return groups

	def _union(a, b):
		if a not in groups or b not in groups:
			return
		root_a, root_b = _root(groups, a), _root(groups, b)
		if root_a == root_b:
			return
		# Customer side leads, so a netted row reads as a receivable position by default.
		primary, secondary = (root_a, root_b) if root_a[0] == "Customer" else (root_b, root_a)
		groups[secondary] = primary

	for link in frappe.get_all(
		"Party Link",
		fields=["primary_role", "primary_party", "secondary_role", "secondary_party"],
	):
		if link.primary_role in PARTY_TYPES and link.secondary_role in PARTY_TYPES:
			_union((link.primary_role, link.primary_party), (link.secondary_role, link.secondary_party))

	if filters.get("match_unlinked_by_pan"):
		by_pan = {}
		for party_type in PARTY_TYPES:
			for row in frappe.get_all(party_type, fields=["name", "pan"], filters={"pan": ("is", "set")}):
				if row.pan:
					by_pan.setdefault(row.pan.strip().upper(), []).append((party_type, row.name))
		for members in by_pan.values():
			for other in members[1:]:
				_union(members[0], other)

	return {key: _root(groups, key) for key in groups}


def _root(groups, key):
	seen = set()
	while groups.get(key, key) != key and key not in seen:
		seen.add(key)
		key = groups[key]
	return key


# ─── rows ────────────────────────────────────────────────────────────────────


def build_rows(filters, balances, erpnext_balances, ageing, ranges, groups, precision, currency) -> list:
	grouped = {}
	for key, values in balances.items():
		grouped.setdefault(groups.get(key, key), {})[key] = values

	names = get_party_names(set(balances) | set(erpnext_balances))
	show_members = filters.get("show_members")
	hide_zero = not filters.get("show_zero_balance")

	data, totals = [], _blank_totals(currency, ranges if filters.get("show_ageing") else None)
	for group_key in sorted(grouped, key=lambda k: (k[0], k[1])):
		members = grouped[group_key]
		row = _aggregate(members, precision)

		if hide_zero and not any(
			row[field]
			for field in (
				"opening_debit",
				"opening_credit",
				"debit",
				"credit",
				"closing_debit",
				"closing_credit",
			)
		):
			continue

		row.update(
			{
				"party_type": group_key[0],
				"party": group_key[1],
				"party_name": names.get(group_key, {}).get("party_name"),
				"pan": names.get(group_key, {}).get("pan"),
				"is_knocked_off": 1 if len(members) > 1 else 0,
				"members": ", ".join(f"{k[1]} ({k[0]})" for k in sorted(members)) if len(members) > 1 else "",
				"currency": currency,
				"indent": 0,
			}
		)

		if filters.get("show_purity_check"):
			erpnext_dr, erpnext_cr = _erpnext_closing(members, erpnext_balances, precision)
			row["erpnext_closing"] = flt(erpnext_dr - erpnext_cr, precision)
			row["purity_difference"] = flt(
				row["erpnext_closing"] - (row["closing_debit"] - row["closing_credit"]), precision
			)

		if filters.get("show_ageing"):
			row.update(_net_ageing(members, ageing, ranges, filters, precision))
			# Open invoices against the account balance, compared in one signed frame: ageing is a
			# magnitude on its own side, the trial balance is Dr less Cr. They measure different
			# things, so a gap is information rather than an error — unposted advances, a
			# journal-only balance, or a payment on account never allocated to an invoice all
			# land here.
			signed_due = flt(row.get("total_due"))
			if row.get("ageing_side") == _("Payable"):
				signed_due = -signed_due
			row["total_due_vs_closing"] = flt(
				signed_due - (row["closing_debit"] - row["closing_credit"]), precision
			)

		data.append(row)
		for field in totals:
			if field in row and isinstance(row[field], (int, float)):
				totals[field] += row[field]

		if show_members and len(members) > 1:
			for member_key in sorted(members):
				member = _single(members[member_key], precision)
				member.update(
					{
						"party_type": member_key[0],
						"party": member_key[1],
						"party_name": names.get(member_key, {}).get("party_name"),
						"pan": names.get(member_key, {}).get("pan"),
						"currency": currency,
						"indent": 1,
					}
				)
				data.append(member)

	totals["party_name"] = _("Totals")
	totals["indent"] = 0
	data.append(totals)
	return data


def _blank_totals(currency, ranges=None):
	fields = [
		"opening_debit",
		"opening_credit",
		"debit",
		"credit",
		"closing_debit",
		"closing_credit",
		"receivable",
		"customer_advance",
		"payable",
		"supplier_advance",
		"erpnext_closing",
		"purity_difference",
		"total_due",
		"total_due_vs_closing",
	]
	fields += [f"range{i}" for i in range(1, len(ranges or []) + 2)]
	totals = dict.fromkeys(fields, 0.0)
	totals["currency"] = currency
	return totals


def _single(values, precision) -> dict:
	"""One party's own figures, each side collapsed the way a trial balance shows it."""
	opening_debit, opening_credit = toggle_debit_credit(values["opening_debit"], values["opening_credit"])
	closing_debit, closing_credit = toggle_debit_credit(
		opening_debit + values["debit"], opening_credit + values["credit"]
	)
	return {
		"opening_debit": flt(opening_debit, precision),
		"opening_credit": flt(opening_credit, precision),
		"debit": flt(values["debit"], precision),
		"credit": flt(values["credit"], precision),
		"closing_debit": flt(closing_debit, precision),
		"closing_credit": flt(closing_credit, precision),
	}


def _aggregate(members, precision) -> dict:
	"""Net a linked group onto one line, keeping each side visible before the knock-off.

	Each side is reported on the side it actually sits on, never as a signed receivable: a customer
	carrying a credit is an advance received, not a negative debtor, and a supplier carrying a
	debit is an advance paid. Collapsing those into one signed figure is what makes a knocked-off
	total unreadable — you can no longer tell a settled party from one owing and owed in equal
	measure. The netted closing follows afterwards, from the summed movement.
	"""
	opening_debit = opening_credit = debit = credit = 0.0
	receivable = customer_advance = payable = supplier_advance = 0.0

	for (party_type, _party), values in members.items():
		opening_debit += values["opening_debit"]
		opening_credit += values["opening_credit"]
		debit += values["debit"]
		credit += values["credit"]

		member_dr, member_cr = toggle_debit_credit(
			values["opening_debit"] + values["debit"], values["opening_credit"] + values["credit"]
		)
		if party_type == "Customer":
			receivable += member_dr
			customer_advance += member_cr
		else:
			payable += member_cr
			supplier_advance += member_dr

	opening_debit, opening_credit = toggle_debit_credit(opening_debit, opening_credit)
	closing_debit, closing_credit = toggle_debit_credit(opening_debit + debit, opening_credit + credit)

	return {
		"opening_debit": flt(opening_debit, precision),
		"opening_credit": flt(opening_credit, precision),
		"debit": flt(debit, precision),
		"credit": flt(credit, precision),
		"closing_debit": flt(closing_debit, precision),
		"closing_credit": flt(closing_credit, precision),
		"receivable": flt(receivable, precision),
		"customer_advance": flt(customer_advance, precision),
		"payable": flt(payable, precision),
		"supplier_advance": flt(supplier_advance, precision),
	}


def _erpnext_closing(members, erpnext_balances, precision):
	"""What "Trial Balance for Party" would close at for the same parties, all accounts included."""
	debit = credit = 0.0
	for key in members:
		values = erpnext_balances.get(key)
		if not values:
			continue
		debit += values["opening_debit"] + values["debit"]
		credit += values["opening_credit"] + values["credit"]
	return toggle_debit_credit(flt(debit, precision), flt(credit, precision))


def get_party_names(party_keys) -> dict:
	names = {}
	for party_type in PARTY_TYPES:
		wanted = [key[1] for key in party_keys if key[0] == party_type]
		if not wanted:
			continue
		field = "customer_name" if party_type == "Customer" else "supplier_name"
		for row in frappe.get_all(
			party_type, fields=["name", field, "pan"], filters={"name": ("in", wanted)}
		):
			names[(party_type, row.name)] = {"party_name": row.get(field), "pan": row.get("pan")}
	return names


# ─── columns ─────────────────────────────────────────────────────────────────


def get_columns(filters, ranges=None) -> list:
	columns = [
		{
			# Data, not a Link to DocType. Frappe treats a Link column as a linked doctype and
			# demands read permission on it before returning any row, so "options": "DocType"
			# made the whole report throw "No permission to read DocType" for anyone without
			# DocType read — which is every ordinary Accounts User. The value is still a doctype
			# name, so the Dynamic Link on `party` below keeps working.
			"fieldname": "party_type",
			"label": _("Party Type"),
			"fieldtype": "Data",
			"width": 110,
		},
		{
			"fieldname": "party",
			"label": _("Party"),
			"fieldtype": "Dynamic Link",
			"options": "party_type",
			"width": 180,
		},
		{"fieldname": "party_name", "label": _("Name"), "fieldtype": "Data", "width": 200},
		{"fieldname": "pan", "label": _("PAN"), "fieldtype": "Data", "width": 110},
		{
			"fieldname": "is_knocked_off",
			"label": _("Knocked Off"),
			"fieldtype": "Check",
			"width": 100,
		},
		{"fieldname": "members", "label": _("Netted Parties"), "fieldtype": "Data", "width": 240},
		{
			"fieldname": "opening_debit",
			"label": _("Opening (Dr)"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"fieldname": "opening_credit",
			"label": _("Opening (Cr)"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"fieldname": "debit",
			"label": _("Debit"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"fieldname": "credit",
			"label": _("Credit"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"fieldname": "receivable",
			"label": _("Receivable"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		},
		{
			"fieldname": "customer_advance",
			"label": _("Customer Advance"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		},
		{
			"fieldname": "payable",
			"label": _("Payable"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		},
		{
			"fieldname": "supplier_advance",
			"label": _("Supplier Advance"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		},
		{
			"fieldname": "closing_debit",
			"label": _("Closing (Dr)"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"fieldname": "closing_credit",
			"label": _("Closing (Cr)"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
	]

	if filters.get("show_purity_check"):
		columns += [
			{
				"fieldname": "erpnext_closing",
				"label": _("ERPNext Closing (all accounts)"),
				"fieldtype": "Currency",
				"options": "currency",
				"width": 190,
			},
			{
				"fieldname": "purity_difference",
				"label": _("Outside Receivable/Payable"),
				"fieldtype": "Currency",
				"options": "currency",
				"width": 190,
			},
		]

	if filters.get("show_ageing"):
		columns += _ageing_columns(ranges or [])

	columns.append(
		{
			"fieldname": "currency",
			"label": _("Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"width": 90,
		}
	)
	return columns


def _ageing_columns(ranges) -> list:
	"""Bucket labels built the way ERPNext builds them: 0-30, 31-60, ... , 120-Above."""
	columns = [
		{
			"fieldname": "ageing_side",
			"label": _("Ageing Side"),
			"fieldtype": "Data",
			"width": 110,
		}
	]
	previous = 0
	for index, boundary in enumerate(ranges):
		columns.append(
			{
				"fieldname": f"range{index + 1}",
				"label": _("{0}-{1}").format(previous, boundary),
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			}
		)
		previous = cint(boundary) + 1

	columns.append(
		{
			"fieldname": f"range{len(ranges) + 1}",
			"label": _("{0}-Above").format(previous),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		}
	)
	columns.append(
		{
			"fieldname": "total_due",
			"label": _("Total Due (netted)"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		}
	)
	columns.append(
		{
			"fieldname": "total_due_vs_closing",
			"label": _("Due less Closing"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		}
	)
	return columns
