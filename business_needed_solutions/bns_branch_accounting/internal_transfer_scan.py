# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""Find the submitted internal-transfer documents the submit-time checks refuse.

Shared by the "Internal Transfer Receive Mismatch" and "Internal Transfer Accounting
Audit" reports, so both list exactly what the validators would block:

- Document parity (`parity_findings`): the same gates as the validators, then
  `internal_parity.compare_internal_pair` for each link
    SI  validate_internal_sales_invoice_linkage            DN->SI
    PR  validate_internal_purchase_receipt_linkage          DN->PR / SI->PR
    PI  validate_internal_purchase_invoice_si_parity        SI->PI / PR->PI
- Receiver missing (`missing_receivers`): a submitted forward internal DN / SI after the
  internal-transfer cutoff whose receiving document was never submitted.
    DN routed DN->PR (same GSTIN, the per-DN diff-GSTIN opt-in, or status
      "BNS Internally Transferred"): needs a Purchase Receipt referencing it.
    DN on the different-GSTIN path: needs a Sales Invoice made from it (DN->SI); the
      invoice then needs its own receiver (next rule).
    SI (different GSTIN): needs a Purchase Invoice resolving to it - directly
      (reference / bill no.) or through a Purchase Receipt made from it (SI->PR->PI).
      When the receiving PI neither updates stock nor comes from a receipt, the goods
      were never received (validate_internal_stock_movement_captured).

Internal parties are judged like the validators and the GL rewrite: the document tick
OR the party master (utils.is_bns_internal_customer / is_bns_internal_supplier).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, cstr, date_diff, getdate, today

from business_needed_solutions.bns_branch_accounting import internal_parity as ip
from business_needed_solutions.bns_branch_accounting import utils

DN, SI, PR, PI = ip.DN, ip.SI, ip.PR, ip.PI
_CHUNK = 500


def _chunks(values, size=_CHUNK):
	values = list(values)
	for i in range(0, len(values), size):
		yield values[i : i + size]


def _s(value) -> str:
	return cstr(value).strip()


def cutoff_date():
	return utils._get_internal_transfer_cutoff_date()


# --------------------------------------------------------------------------------------
# Which links the validators check
# --------------------------------------------------------------------------------------


def parity_links(doc) -> list[str]:
	"""The parity links the save / submit checks run for this document (same gates)."""
	if cint(doc.get("is_return")):
		return []
	if doc.doctype == SI:
		# utils.validate_internal_sales_invoice_linkage
		if not utils.is_bns_internal_customer(doc):
			return []
		if not utils.is_after_internal_transfer_cutoff(doc.get("posting_date")):
			return []
		co, bill = _s(doc.get("company_gstin")), _s(doc.get("billing_address_gstin"))
		if not co or not bill or co == bill:
			return []  # refused for its GSTINs before parity: see gstin_problems()
		if not any(_s(r.get("delivery_note")) for r in doc.get("items") or []):
			return []
		return ["DN->SI"]
	if doc.doctype == PR:
		# utils.validate_internal_purchase_receipt_linkage -> _validate_internal_pr_one_to_one_parity:
		# any PR with a source reference (the cutoff does not apply once a reference is set).
		if not _s(doc.get("bns_inter_company_reference")):
			return []
		if not utils.is_bns_internal_supplier(doc):
			return []  # refused earlier: an internal reference on a regular supplier
		return ip.detect_links(doc)
	if doc.doctype == PI:
		# utils.validate_internal_purchase_invoice_si_parity
		if not utils.is_bns_internal_supplier(doc):
			return []
		if not utils.is_after_internal_transfer_cutoff(utils._resolve_source_posting_date(doc)):
			return []
		links = ip.detect_links(doc)
		co, bill = _s(doc.get("company_gstin")), _s(doc.get("billing_address_gstin"))
		if co and bill and co == bill:
			return []
		return links
	return []


# --------------------------------------------------------------------------------------
# Document parity
# --------------------------------------------------------------------------------------


def _base_conditions(filters, alias, conds, vals):
	if filters.get("company"):
		conds.append(f"{alias}.company = %s")
		vals.append(filters.get("company"))
	if filters.get("from_date"):
		conds.append(f"{alias}.posting_date >= %s")
		vals.append(filters.get("from_date"))
	if filters.get("to_date"):
		conds.append(f"{alias}.posting_date <= %s")
		vals.append(filters.get("to_date"))


def _parity_candidates(doctype, filters):
	"""Submitted forward documents that can be on a parity link (SQL pre-filter only;
	parity_links() decides)."""
	conds, vals = ["d.docstatus = 1", "IFNULL(d.is_return, 0) = 0"], []
	_base_conditions(filters, "d", conds, vals)
	if doctype == SI:
		cutoff = cutoff_date()
		if not cutoff:
			return []
		conds += [
			"d.posting_date >= %s",
			"(d.is_bns_internal_customer = 1 OR p.is_bns_internal_customer = 1)",
			"""EXISTS (SELECT 1 FROM `tabSales Invoice Item` i
				WHERE i.parent = d.name AND IFNULL(i.delivery_note, '') != '')""",
		]
		vals.append(cutoff)
		join = "LEFT JOIN `tabCustomer` p ON p.name = d.customer"
	elif doctype == PR:
		conds += [
			"IFNULL(d.bns_inter_company_reference, '') != ''",
			"(d.is_bns_internal_supplier = 1 OR p.is_bns_internal_supplier = 1)",
		]
		join = "LEFT JOIN `tabSupplier` p ON p.name = d.supplier"
	elif doctype == PI:
		if not cutoff_date():
			return []
		conds += [
			"(d.is_bns_internal_supplier = 1 OR p.is_bns_internal_supplier = 1)",
			"""(IFNULL(d.bns_inter_company_reference, '') != '' OR IFNULL(d.bill_no, '') != ''
				OR EXISTS (SELECT 1 FROM `tabPurchase Invoice Item` i WHERE i.parent = d.name
					AND (IFNULL(i.purchase_receipt, '') != '' OR IFNULL(i.pr_detail, '') != '')))""",
		]
		join = "LEFT JOIN `tabSupplier` p ON p.name = d.supplier"
	else:
		return []
	return frappe.db.sql(
		f"SELECT d.name FROM `tab{doctype}` d {join} WHERE {' AND '.join(conds)} ORDER BY d.posting_date, d.name",
		tuple(vals),
		pluck=True,
	) or []


def sender_of(doc):
	"""(doctype, name) of the sending document of a transfer document: the SI itself for
	DN->SI, the DN / SI a receipt references, the SI an invoice resolves to."""
	if doc.doctype in (DN, SI):
		return doc.doctype, doc.name
	if doc.doctype == PR:
		ref = _s(doc.get("bns_inter_company_reference"))
		for dt in (DN, SI):
			if ref and frappe.db.exists(dt, ref):
				return dt, ref
		return None, None
	if doc.doctype == PI:
		si = utils._resolve_si_name_for_internal_pi(doc)
		if si:
			return SI, si
		for r in doc.get("items") or []:
			if _s(r.get("purchase_receipt")):
				ref = _s(frappe.db.get_value(PR, r.purchase_receipt, "bns_inter_company_reference"))
				for dt in (DN, SI):
					if ref and frappe.db.exists(dt, ref):
						return dt, ref
	return None, None


def sender_passes(filters, doctype, name) -> bool:
	"""Customer / company-address filters apply to the sending document."""
	if not (filters.get("customer") or filters.get("company_address")):
		return True
	if not doctype or not name:
		return False
	values = frappe.db.get_value(doctype, name, ["customer", "company_address"], as_dict=True) or {}
	if filters.get("customer") and values.get("customer") != filters.get("customer"):
		return False
	if filters.get("company_address") and values.get("company_address") != filters.get("company_address"):
		return False
	return True


def parity_findings(filters, doctypes=(SI, PR, PI)):
	"""[{doctype, name, posting_date, company, grand_total, location, link, sender_type,
	sender, mismatches: [Mismatch]}] - one entry per (document, link) that differs."""
	filters = frappe._dict(filters or {})
	out = []
	for doctype in doctypes:
		for name in _parity_candidates(doctype, filters):
			doc = frappe.get_doc(doctype, name)
			links = parity_links(doc)
			if not links:
				continue
			sender_type, sender = sender_of(doc)
			if not sender_passes(filters, sender_type, sender):
				continue
			for link in links:
				mismatches = ip.compare_internal_pair(doc, link)
				if mismatches:
					out.append(frappe._dict(
						doctype=doctype, name=name, posting_date=doc.posting_date, company=doc.company,
						grand_total=doc.get("grand_total"), location=_s(doc.get("location")),
						link=link, sender_type=sender_type, sender=sender, mismatches=mismatches,
					))
	return out


def gstin_problems(filters):
	"""Internal SIs after the cutoff that validate_internal_sales_invoice_linkage refuses
	for their GSTINs (missing, or the same on both sides)."""
	filters = frappe._dict(filters or {})
	cutoff = cutoff_date()
	if not cutoff:
		return []
	conds = [
		"d.docstatus = 1", "IFNULL(d.is_return, 0) = 0", "d.posting_date >= %s",
		"(d.is_bns_internal_customer = 1 OR p.is_bns_internal_customer = 1)",
		"""(IFNULL(d.company_gstin, '') = '' OR IFNULL(d.billing_address_gstin, '') = ''
			OR d.company_gstin = d.billing_address_gstin)""",
	]
	vals = [cutoff]
	_base_conditions(filters, "d", conds, vals)
	_party_conditions(filters, "d", conds, vals)
	rows = frappe.db.sql(
		f"""SELECT d.name, d.posting_date, d.grand_total, d.company_address, d.customer_address,
			d.company_gstin, d.billing_address_gstin
		FROM `tabSales Invoice` d LEFT JOIN `tabCustomer` p ON p.name = d.customer
		WHERE {' AND '.join(conds)}""",
		tuple(vals),
		as_dict=True,
	)
	for r in rows:
		if not _s(r.company_gstin) or not _s(r.billing_address_gstin):
			r.reason = _("Internal Sales Invoice without Company GSTIN / Billing GSTIN (both are required).")
		else:
			r.reason = _("Internal Sales Invoice with the same Company and Billing GSTIN ({0}); "
						 "a same-GSTIN transfer goes Delivery Note -> Purchase Receipt.").format(r.company_gstin)
	return rows


def _party_conditions(filters, alias, conds, vals):
	if filters.get("customer"):
		conds.append(f"{alias}.customer = %s")
		vals.append(filters.get("customer"))
	if filters.get("company_address"):
		conds.append(f"{alias}.company_address = %s")
		vals.append(filters.get("company_address"))


# --------------------------------------------------------------------------------------
# Receiver missing
# --------------------------------------------------------------------------------------


def dn_routes_to_pr(dn) -> bool:
	"""The DN's receiver is a Purchase Receipt (same-GSTIN path): same GSTIN, the per-DN
	diff-GSTIN opt-in, or the status update_delivery_note_status_for_bns_internal sets
	only on that path."""
	co, bill = _s(dn.get("company_gstin")), _s(dn.get("billing_address_gstin"))
	if co and bill and co == bill:
		return True
	if cint(dn.get("bns_allow_diff_gstin_dn_pr")):
		return True
	return dn.get("status") == "BNS Internally Transferred"


def _sources(doctype, filters, extra_conds=(), fields=""):
	cutoff = cutoff_date()
	if not cutoff:
		return []
	conds = [
		"d.docstatus = 1", "IFNULL(d.is_return, 0) = 0", "d.posting_date >= %s",
		"(d.is_bns_internal_customer = 1 OR p.is_bns_internal_customer = 1)",
		*extra_conds,
	]
	vals = [cutoff]
	_base_conditions(filters, "d", conds, vals)
	_party_conditions(filters, "d", conds, vals)
	return frappe.db.sql(
		f"""SELECT d.name, d.posting_date, d.grand_total, d.company, d.company_address,
			d.customer_address, d.company_gstin, d.billing_address_gstin, d.status,
			d.bns_inter_company_reference {fields}
		FROM `tab{doctype}` d LEFT JOIN `tabCustomer` p ON p.name = d.customer
		WHERE {' AND '.join(conds)}""",
		tuple(vals),
		as_dict=True,
	) or []


def _opt_field(doctype, field):
	"""SQL select fragment for a field that may not exist on every site."""
	return f", d.{field}" if frappe.get_meta(doctype).has_field(field) else f", NULL AS {field}"


def _by_ref(doctype, refs, docstatus=1, extra=""):
	"""{reference: [names]} of forward documents whose bns_inter_company_reference is in refs."""
	out = {}
	for chunk in _chunks(refs):
		for r in frappe.db.sql(
			f"""SELECT name, bns_inter_company_reference AS ref {extra} FROM `tab{doctype}`
			WHERE docstatus = %s AND IFNULL(is_return, 0) = 0
			AND bns_inter_company_reference IN %s ORDER BY name""",
			(docstatus, tuple(chunk)),
			as_dict=True,
		):
			out.setdefault(r.ref, []).append(r.name)
	return out


def _age(posting_date) -> int:
	return date_diff(today(), getdate(posting_date)) if posting_date else 0


def missing_receivers(filters, include_stock=True):
	"""Submitted internal DNs / SIs (after the cutoff) without their submitted receiver.

	Returns [{doctype, name, posting_date, age_days, grand_total, company_address,
	customer_address, location, missing, chain, reason, purchase_receipt,
	purchase_invoice, sales_invoice, kind}] where kind is "receiver" or "stock"."""
	filters = frappe._dict(filters or {})
	rows = []
	dns = _sources(
		DN, filters,
		fields=_opt_field(DN, "billing_location") + _opt_field(DN, "bns_allow_diff_gstin_dn_pr"),
	)
	if dns:
		names = [d.name for d in dns]
		prs = _by_ref(PR, names)
		draft_prs = _by_ref(PR, names, docstatus=0)
		sis = {}
		for chunk in _chunks(names):
			for r in frappe.db.sql(
				"""SELECT DISTINCT i.delivery_note AS dn, si.name FROM `tabSales Invoice Item` i
				JOIN `tabSales Invoice` si ON si.name = i.parent
				WHERE si.docstatus = 1 AND IFNULL(si.is_return, 0) = 0 AND i.delivery_note IN %s""",
				(tuple(chunk),),
				as_dict=True,
			):
				sis.setdefault(r.dn, []).append(r.name)
		for dn in dns:
			if dn_routes_to_pr(dn):
				if prs.get(dn.name):
					continue
				draft = draft_prs.get(dn.name)
				rows.append(_missing_row(
					DN, dn, PR, "DN->PR",
					_("No submitted Purchase Receipt references this Delivery Note.")
					+ (" " + _("Draft: {0}.").format(", ".join(draft)) if draft else ""),
					purchase_receipt=(draft or [None])[0],
				))
			elif not sis.get(dn.name):
				rows.append(_missing_row(
					DN, dn, SI, "DN->SI->PI",
					_("Different-GSTIN internal Delivery Note: no submitted Sales Invoice is made "
					  "from it, so nothing can be received."),
				))
	sis = _sources(
		SI, filters,
		extra_conds=(
			"IFNULL(d.company_gstin, '') != ''", "IFNULL(d.billing_address_gstin, '') != ''",
			"d.company_gstin != d.billing_address_gstin",
		),
		fields=_opt_field(SI, "billing_location") + """, d.update_stock,
			EXISTS (SELECT 1 FROM `tabSales Invoice Item` i WHERE i.parent = d.name
				AND IFNULL(i.delivery_note, '') != '') AS from_dn""",
	)
	if sis:
		rows += _si_receivers(sis, include_stock)
	if cint(filters.get("older_than_days")):
		rows = [r for r in rows if r.age_days > cint(filters.older_than_days)]
	return rows


def _missing_row(doctype, src, missing, chain, reason, kind="receiver", **links):
	return frappe._dict(
		doctype=doctype, name=src.name, posting_date=src.posting_date, age_days=_age(src.posting_date),
		grand_total=src.grand_total, company_address=src.company_address,
		customer_address=src.customer_address, location=_s(src.get("billing_location")),
		missing=missing, chain=chain, reason=reason, kind=kind,
		purchase_receipt=links.get("purchase_receipt"), purchase_invoice=links.get("purchase_invoice"),
		sales_invoice=links.get("sales_invoice"),
	)


def _si_receivers(sis, include_stock):
	names = [s.name for s in sis]
	si_set = set(names)
	# Purchase Invoices resolving to the SI the way _resolve_si_name_for_internal_pi does:
	# its reference, else its bill no. (when the reference is not an internal SI).
	pis = {}
	pi_info = {}
	for chunk in _chunks(names):
		for r in frappe.db.sql(
			"""SELECT name, bns_inter_company_reference AS ref, bill_no, update_stock, posting_date
			FROM `tabPurchase Invoice` WHERE docstatus = 1 AND IFNULL(is_return, 0) = 0
			AND (bns_inter_company_reference IN %(c)s OR bill_no IN %(c)s)""",
			{"c": tuple(chunk)},
			as_dict=True,
		):
			ref, bill = _s(r.ref), _s(r.bill_no)
			if ref in si_set:
				target = ref
			elif bill in si_set and not (ref and utils._is_internal_transfer_sales_invoice(ref)):
				target = bill
			else:
				continue
			pis.setdefault(target, []).append(r.name)
			pi_info[r.name] = r
	prs = _by_ref(PR, names)
	pr_to_si = {pr: si for si, lst in prs.items() for pr in lst}
	for chunk in _chunks(list(pr_to_si)):
		for r in frappe.db.sql(
			"""SELECT DISTINCT pi.name, i.purchase_receipt, pi.update_stock, pi.posting_date
			FROM `tabPurchase Invoice Item` i JOIN `tabPurchase Invoice` pi ON pi.name = i.parent
			WHERE pi.docstatus = 1 AND IFNULL(pi.is_return, 0) = 0 AND i.purchase_receipt IN %s""",
			(tuple(chunk),),
			as_dict=True,
		):
			si = pr_to_si[r.purchase_receipt]
			if r.name not in (pis.get(si) or []):
				pis.setdefault(si, []).append(r.name)
			pi_info.setdefault(r.name, r)
	draft_pis = _by_ref(PI, names, docstatus=0)

	rows = []
	enforced = include_stock and utils._is_internal_stock_movement_enforced()
	for si in sis:
		chain_head = "DN->SI" if cint(si.from_dn) else "SI"
		found = pis.get(si.name) or []
		pr_names = prs.get(si.name) or []
		if not found:
			draft = draft_pis.get(si.name)
			if pr_names:
				reason = _("Goods received on {0}, but no submitted Purchase Invoice is made from it.").format(
					", ".join(pr_names))
				chain = chain_head + "->PR->PI"
			else:
				reason = _("No submitted Purchase Invoice (or Purchase Receipt) is made from this Sales Invoice.")
				chain = chain_head + "->PI"
			if draft:
				reason += " " + _("Draft: {0}.").format(", ".join(draft))
			rows.append(_missing_row(
				SI, si, PI, chain, reason,
				purchase_receipt=(pr_names or [None])[0], purchase_invoice=(draft or [None])[0],
				sales_invoice=si.name,
			))
			continue
		if pr_names or not enforced:
			continue
		# Invoice received but no stock: the receiving PI neither updates stock nor comes
		# from a receipt (validate_internal_stock_movement_captured, same switch + cutoff).
		for pi_name in found:
			info = pi_info.get(pi_name) or {}
			if cint(info.get("update_stock")):
				continue
			if not utils.is_after_internal_transfer_cutoff(info.get("posting_date")):
				continue
			pi_doc = frappe.get_doc(PI, pi_name)
			if utils._internal_stock_movement_uncaptured(pi_doc):
				rows.append(_missing_row(
					SI, si, _("Stock receipt"), chain_head + "->PI",
					_("{0} has stock items but neither updates stock nor comes from a Purchase Receipt: "
					  "the goods were never received.").format(pi_name),
					kind="stock", purchase_invoice=pi_name, sales_invoice=si.name,
				))
	return rows
