# Copyright (c) 2025, Business Needed Solutions and Contributors
# License: Commercial

"""
Internal Transfer Receive Mismatch Report

Lists what the internal-transfer submit checks refuse, so the report and the
validators always agree:

1. Document parity (one row per difference): every internal SI made from a DN,
   PR made from a DN / SI and PI made from an SI / PR is compared row by row
   through its link fields by bns_branch_accounting.internal_parity -- the same
   function the validators call. An item on several rows is matched to its own
   source row, never summed by item code. Rows, quantities, rates, amounts, HSN,
   item-level GST, GST per head, totals and batches / serials are compared with
   no tolerance.
2. Receiver missing: a submitted internal DN / SI after the internal-transfer
   cutoff whose receiving PR / PI was never submitted, with its age in days
   (see internal_transfer_scan.missing_receivers for which receiver is required).
3. Linkage: internal PR / PI / SI linkage the validators refuse, half-written
   DN <-> PR back-references, duplicate claimants, references on non-internal
   parties and external parties treated as internal.

Internal parties are judged on the party master (utils.is_bns_internal_supplier /
is_bns_internal_customer), like the validators and the GL rewrite -- never on the
document tick alone.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate, today

from business_needed_solutions.bns_branch_accounting import internal_parity as ip
from business_needed_solutions.bns_branch_accounting import internal_transfer_scan as scan
from business_needed_solutions.bns_branch_accounting import utils

_ALLOWED_ADDRESS_SEARCHFIELDS = {"name", "address_title"}


@frappe.whitelist()
def company_address_query(doctype, txt, searchfield, start, page_len, filters):
	"""
	Query to fetch only company addresses for the report filter.

	Why the searchfield whitelist: Frappe passes this arg through from the
	client and the old code interpolated it straight into an f-string SQL
	clause, which would let a caller send `searchfield="1=1; DROP TABLE..."`
	and execute arbitrary SQL. Lock it to known-safe columns.
	"""
	# Require caller to be authenticated AND have read on Address.
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if not frappe.has_permission("Address", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if searchfield not in _ALLOWED_ADDRESS_SEARCHFIELDS:
		searchfield = "name"

	conditions = ["is_company_address = 1"]
	values = {}

	if txt:
		# Parameterised LIKE with a named placeholder.
		conditions.append(f"{searchfield} like %(txt)s")
		values["txt"] = f"%{txt}%"

	if filters and filters.get("company"):
		conditions.append("address_title = %(company)s")
		values["company"] = filters.get("company")

	values["page_len"] = int(page_len or 20)
	values["start"] = int(start or 0)

	where_clause = " AND ".join(conditions)
	query = f"""
		SELECT
			name,
			IFNULL(address_title, name) AS address_title
		FROM `tabAddress`
		WHERE {where_clause}
		ORDER BY modified DESC
		LIMIT %(page_len)s
		OFFSET %(start)s
	"""
	return frappe.db.sql(query, values)


def execute(filters=None):
	"""Return (columns, data)."""
	filters = _apply_cutoff_filters(filters or {})
	return get_columns(), get_data(filters) or []


def get_columns():
	"""Define report columns."""
	return [
		{"fieldname": "posting_date", "label": _("Posting Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "document_type", "label": _("Document Type"), "fieldtype": "Data", "width": 120},
		{
			"fieldname": "document_name",
			"label": _("Document"),
			"fieldtype": "Dynamic Link",
			"options": "document_type",
			"width": 150,
		},
		{"fieldname": "company_address_name", "label": _("Company Address (Name)"), "fieldtype": "Data", "width": 180},
		{"fieldname": "customer_address_name", "label": _("Customer Address (Name)"), "fieldtype": "Data", "width": 180},
		{"fieldname": "grand_total", "label": _("Grand Total"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "missing_document", "label": _("Missing Document"), "fieldtype": "Data", "width": 150},
		{"fieldname": "mismatch_reason", "label": _("Mismatch Reason"), "fieldtype": "Data", "width": 300},
		{"fieldname": "age_days", "label": _("Age (Days)"), "fieldtype": "Int", "width": 90},
		{
			"fieldname": "purchase_receipt",
			"label": _("Purchase Receipt"),
			"fieldtype": "Link",
			"options": "Purchase Receipt",
			"width": 150,
		},
		{
			"fieldname": "purchase_invoice",
			"label": _("Purchase Invoice"),
			"fieldtype": "Link",
			"options": "Purchase Invoice",
			"width": 150,
		},
		{"fieldname": "transfer_chain", "label": _("Transfer Chain"), "fieldtype": "Data", "width": 140},
		{"fieldname": "source_document_type", "label": _("Source Type"), "fieldtype": "Data", "width": 110},
		{
			"fieldname": "source_document",
			"label": _("Source Document"),
			"fieldtype": "Dynamic Link",
			"options": "source_document_type",
			"width": 150,
		},
		{"fieldname": "row_no", "label": _("Row"), "fieldtype": "Int", "width": 60},
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 120},
		{"fieldname": "parity_field", "label": _("Field"), "fieldtype": "Data", "width": 130},
		{"fieldname": "expected_value", "label": _("Source Value"), "fieldtype": "Data", "width": 120},
		{"fieldname": "found_value", "label": _("This Document"), "fieldtype": "Data", "width": 120},
		{"fieldname": "source_location", "label": _("Source Location"), "fieldtype": "Data", "width": 160},
		{"fieldname": "purchase_location", "label": _("Purchase Location"), "fieldtype": "Data", "width": 160},
		{"fieldname": "location_mismatch", "label": _("Location Mismatch"), "fieldtype": "Data", "width": 200},
		{"fieldname": "item_mismatch_details", "label": _("Item Mismatch"), "fieldtype": "Data", "width": 250},
	]


def get_data(filters=None):
	"""All rows, newest first."""
	filters = frappe._dict(filters or {})
	data = []
	data.extend(get_document_parity_mismatches(filters))
	data.extend(get_missing_receiver_rows(filters))
	data.extend(get_internal_purchase_doc_linkage_mismatches(filters))
	data.extend(get_asymmetric_reference_mismatches(filters))
	data.extend(get_duplicate_and_foreign_reference_mismatches(filters))
	data.extend(get_external_party_internal_mismatches(filters))
	# Stable sort: the rows of one document stay together and in row order.
	data.sort(key=lambda x: getdate(x.get("posting_date") or today()), reverse=True)
	return data


def _apply_cutoff_filters(filters):
	"""Apply cutoff as default from_date when user has not provided one."""
	filters = frappe._dict(filters or {})
	if filters.get("from_date"):
		return filters
	cutoff = utils._get_internal_transfer_cutoff_date()
	if cutoff:
		filters["from_date"] = cutoff
	return filters


def _s(value):
	return cstr(value).strip()


def _empty_mismatch_row(**overrides):
	row = {
		"posting_date": None,
		"document_type": "",
		"document_name": "",
		"grand_total": 0.0,
		"company_address_name": "",
		"customer_address_name": "",
		"missing_document": "",
		"mismatch_reason": "",
		"age_days": None,
		"purchase_receipt": None,
		"purchase_invoice": None,
		"transfer_chain": "",
		"source_document_type": "",
		"source_document": "",
		"row_no": None,
		"item_code": "",
		"parity_field": "",
		"expected_value": "",
		"found_value": "",
		"source_location": "",
		"purchase_location": "",
		"location_mismatch": "",
		"item_mismatch_details": "",
	}
	row.update(overrides)
	return row


def _filter_by_party(filters, alias, conds, vals):
	"""Customer / company-address filters for queries on a DN or SI."""
	if filters.get("customer"):
		conds.append(f"{alias}.customer = %s")
		vals.append(filters.get("customer"))
	if filters.get("company_address"):
		conds.append(f"{alias}.company_address = %s")
		vals.append(filters.get("company_address"))


def _date_company(filters, alias, conds, vals):
	if filters.get("company"):
		conds.append(f"{alias}.company = %s")
		vals.append(filters.get("company"))
	if filters.get("from_date"):
		conds.append(f"{alias}.posting_date >= %s")
		vals.append(filters.get("from_date"))
	if filters.get("to_date"):
		conds.append(f"{alias}.posting_date <= %s")
		vals.append(filters.get("to_date"))


# ---------------------------------------------------------------------------
# 1. Document parity (internal_parity -- the validators' own comparison)
# ---------------------------------------------------------------------------


def get_document_parity_mismatches(filters=None):
	"""One row per difference internal_parity finds on a document the validators check."""
	filters = frappe._dict(filters or {})
	data = []
	sender_info = {}

	def _sender(doctype, name):
		key = (doctype, name)
		if key not in sender_info:
			fields = ["company_address", "customer_address"]
			if doctype and frappe.get_meta(doctype).has_field("billing_location"):
				fields.append("billing_location")
			sender_info[key] = (
				frappe.db.get_value(doctype, name, fields, as_dict=True) if doctype and name else None
			) or frappe._dict()
		return sender_info[key]

	for f in scan.parity_findings(filters):
		sender = _sender(f.sender_type, f.sender)
		source_location = _s(sender.get("billing_location"))
		purchase_location = f.location if f.doctype in (scan.PR, scan.PI) else ""
		location_mismatch = ""
		if source_location and purchase_location and source_location != purchase_location:
			location_mismatch = f"{source_location} vs {purchase_location}"
		source_type = {"DN": scan.DN, "SI": scan.SI, "PR": scan.PR}.get(f.link.split("->")[0], "")
		for m in f.mismatches:
			first_source = _s(m.source.split(",")[0])
			data.append(_empty_mismatch_row(
				posting_date=f.posting_date,
				document_type=f.doctype,
				document_name=f.name,
				grand_total=flt(f.grand_total),
				company_address_name=sender.get("company_address") or "",
				customer_address_name=sender.get("customer_address") or "",
				missing_document=_("{0} (Mismatch)").format(f.doctype),
				mismatch_reason=m.message(),
				purchase_receipt=f.name if f.doctype == scan.PR else (first_source if source_type == scan.PR else None),
				purchase_invoice=f.name if f.doctype == scan.PI else None,
				transfer_chain=f.link,
				source_document_type=source_type,
				source_document=first_source,
				row_no=m.row,
				item_code=m.item_code,
				parity_field=m.field,
				expected_value=ip._fmt(m.expected),
				found_value=ip._fmt(m.found),
				source_location=source_location,
				purchase_location=purchase_location,
				location_mismatch=location_mismatch,
				item_mismatch_details=(
					f"{m.source}={ip._fmt(m.expected)}, {f.name}={ip._fmt(m.found)}" if m.field == _("Item") else ""
				),
			))
	return data


# ---------------------------------------------------------------------------
# 2. Receiver missing
# ---------------------------------------------------------------------------


def get_missing_receiver_rows(filters=None):
	"""Submitted internal DN / SI after the cutoff without its submitted receiver."""
	data = []
	for r in scan.missing_receivers(filters):
		data.append(_empty_mismatch_row(
			posting_date=r.posting_date,
			document_type=r.doctype,
			document_name=r.name,
			grand_total=flt(r.grand_total),
			company_address_name=r.company_address or "",
			customer_address_name=r.customer_address or "",
			missing_document=r.missing,
			mismatch_reason=r.reason,
			age_days=r.age_days,
			purchase_receipt=r.purchase_receipt,
			purchase_invoice=r.purchase_invoice,
			transfer_chain=r.chain,
			source_location=r.location or "",
		))
	return data


# ---------------------------------------------------------------------------
# 3. Linkage
# ---------------------------------------------------------------------------


def _pr_scope_message(scope):
	# The messages of validate_internal_purchase_receipt_linkage for a receipt with no
	# usable source link.
	if scope == "same":
		return _("For same GSTIN internal flow, Purchase Receipt must be linked to a Delivery Note.")
	if scope == "different":
		return _("For different GSTIN internal flow, Purchase Receipt must be linked to a Sales Invoice.")
	return _("Purchase Receipt must be linked to Delivery Note (same GSTIN) or Sales Invoice (different GSTIN).")


def get_internal_purchase_doc_linkage_mismatches(filters=None):
	"""Internal PR / PI / SI linkage problems.

	Refused at submit (same rules as the validators, internal judged on the supplier /
	customer master):
	- PR of an internal supplier after the cutoff with no source reference, or whose
	  reference is neither a Delivery Note nor a Sales Invoice;
	- internal SI after the cutoff without both GSTINs or with the same GSTIN.
	Not refused at submit, listed so they get fixed:
	- PR whose source DN / SI is cancelled or not submitted;
	- PR made from a different-GSTIN Delivery Note that is not on the DN -> PR path;
	- internal PI (different GSTIN) not made from an internal SI or a Purchase Receipt.
	"""
	filters = frappe._dict(filters or {})
	data = []
	cutoff = utils._get_internal_transfer_cutoff_date()

	conds = [
		"d.docstatus = 1", "IFNULL(d.is_return, 0) = 0",
		"(d.is_bns_internal_supplier = 1 OR s.is_bns_internal_supplier = 1)",
	]
	vals = []
	_date_company(filters, "d", conds, vals)
	opt_in = (
		"dn.bns_allow_diff_gstin_dn_pr"
		if frappe.get_meta("Delivery Note").has_field("bns_allow_diff_gstin_dn_pr")
		else "0"
	)
	prs = frappe.db.sql(
		f"""
		SELECT d.name, d.posting_date, d.grand_total, d.company_gstin, d.supplier_delivery_note,
			d.bns_inter_company_reference,
			dn.docstatus AS dn_docstatus, dn.company_gstin AS dn_company_gstin,
			dn.billing_address_gstin AS dn_billing_address_gstin, dn.status AS dn_status,
			{opt_in} AS dn_opt_in, si.docstatus AS si_docstatus
		FROM `tabPurchase Receipt` d
		LEFT JOIN `tabSupplier` s ON s.name = d.supplier
		LEFT JOIN `tabDelivery Note` dn ON dn.name = d.bns_inter_company_reference
		LEFT JOIN `tabSales Invoice` si ON si.name = d.bns_inter_company_reference
		WHERE {" AND ".join(conds)}
		""",
		tuple(vals),
		as_dict=True,
	) or []
	global_allow = bool(
		frappe.db.get_single_value("BNS Branch Accounting Settings", "allow_different_gstin_dn_to_pr")
	)

	for pr in prs:
		ref = _s(pr.bns_inter_company_reference)
		has_dn, has_si = pr.dn_docstatus is not None, pr.si_docstatus is not None
		reason, missing = None, "Source Link (DN/SI)"
		if not ref:
			doc_like = frappe._dict(pr, doctype="Purchase Receipt")
			if not utils.is_after_internal_transfer_cutoff(utils._resolve_source_posting_date(doc_like)):
				continue
			reason = _pr_scope_message(utils._resolve_pr_gstin_scope(doc_like, False, False))
		elif has_dn and has_si:
			reason = _("Reference {0} is both a Delivery Note and a Sales Invoice; only one source link is allowed.").format(ref)
		elif not has_dn and not has_si:
			reason = _("Reference {0} is neither a Delivery Note nor a Sales Invoice. {1}").format(
				ref, _pr_scope_message(None))
		elif cint(pr.dn_docstatus if has_dn else pr.si_docstatus) != 1:
			missing = "Submitted source"
			reason = _("Source {0} {1} is {2} (not refused at submit).").format(
				_("Delivery Note") if has_dn else _("Sales Invoice"), ref,
				_("cancelled") if cint(pr.dn_docstatus if has_dn else pr.si_docstatus) == 2 else _("a draft"),
			)
		elif has_dn and not global_allow and not scan.dn_routes_to_pr(frappe._dict(
			company_gstin=pr.dn_company_gstin, billing_address_gstin=pr.dn_billing_address_gstin,
			bns_allow_diff_gstin_dn_pr=pr.dn_opt_in, status=pr.dn_status,
		)):
			missing = "Sales Invoice (DN->SI)"
			reason = _("Delivery Note {0} is a different-GSTIN transfer that is not on the DN -> PR path "
					   "(no opt-in, not 'BNS Internally Transferred'); it must be billed DN -> SI -> PI "
					   "(not refused at submit).").format(ref)
		if reason:
			data.append(_empty_mismatch_row(
				posting_date=pr.posting_date,
				document_type="Purchase Receipt",
				document_name=pr.name,
				grand_total=flt(pr.grand_total),
				missing_document=missing,
				mismatch_reason=reason,
				purchase_receipt=pr.name,
				source_document_type="Delivery Note" if has_dn else ("Sales Invoice" if has_si else ""),
				source_document=ref if (has_dn or has_si) else "",
			))

	if cutoff:
		conds = [
			"d.docstatus = 1", "IFNULL(d.is_return, 0) = 0", "d.posting_date >= %s",
			"(d.is_bns_internal_supplier = 1 OR s.is_bns_internal_supplier = 1)",
			"IFNULL(d.company_gstin, '') != ''", "IFNULL(d.supplier_gstin, '') != ''",
			# Same GSTIN: no PI belongs there at all. Different GSTIN: no SI behind it.
			"(d.company_gstin = d.supplier_gstin OR (si_ref.name IS NULL AND si_bill.name IS NULL))",
			"""NOT EXISTS (SELECT 1 FROM `tabPurchase Invoice Item` i WHERE i.parent = d.name
				AND IFNULL(i.purchase_receipt, '') != '')""",
		]
		vals = [cutoff]
		_date_company(filters, "d", conds, vals)
		# An internal SI as _is_internal_transfer_sales_invoice defines it.
		internal_si = "{0}.is_bns_internal_customer = 1 AND IFNULL({0}.is_return, 0) = 0"
		pis = frappe.db.sql(
			f"""
			SELECT d.name, d.posting_date, d.grand_total, d.company_gstin = d.supplier_gstin AS same_gstin
			FROM `tabPurchase Invoice` d
			LEFT JOIN `tabSupplier` s ON s.name = d.supplier
			LEFT JOIN `tabSales Invoice` si_ref ON si_ref.name = d.bns_inter_company_reference
				AND {internal_si.format("si_ref")}
			LEFT JOIN `tabSales Invoice` si_bill ON si_bill.name = d.bill_no
				AND {internal_si.format("si_bill")}
			WHERE {" AND ".join(conds)}
			""",
			tuple(vals),
			as_dict=True,
		) or []
		for pi in pis:
			data.append(_empty_mismatch_row(
				posting_date=pi.posting_date,
				document_type="Purchase Invoice",
				document_name=pi.name,
				grand_total=flt(pi.grand_total),
				missing_document="Delivery Note -> Purchase Receipt" if pi.same_gstin else "Sales Invoice / SI-linked PR",
				mismatch_reason=_(
					"Same-GSTIN internal PI: branches with one GSTIN move stock by DN -> PR and have no "
					"Purchase Invoice. Submitted before this was refused; cancel it."
				) if pi.same_gstin else _(
					"Internal PI not made from an internal Sales Invoice or an SI-made Purchase Receipt, so "
					"nothing is compared or paired. Submitted before this was refused; cancel and make it "
					"from the Sales Invoice."
				),
				purchase_invoice=pi.name,
			))

		for si in scan.gstin_problems(filters):
			data.append(_empty_mismatch_row(
				posting_date=si.posting_date,
				document_type="Sales Invoice",
				document_name=si.name,
				grand_total=flt(si.grand_total),
				company_address_name=si.company_address or "",
				customer_address_name=si.customer_address or "",
				missing_document="Different GSTINs",
				mismatch_reason=si.reason,
				transfer_chain="SI",
			))

	return data


def get_asymmetric_reference_mismatches(filters=None):
	"""Find DNs where a submitted PR references the DN but DN has no back-reference.

	This catches cases where PR.bns_inter_company_reference = DN.name but
	DN.bns_inter_company_reference is NULL/empty — meaning the bidirectional
	link was never completed. The PR is internal by its supplier master
	(utils.is_bns_internal_supplier), not only by its own tick.
	"""
	filters = frappe._dict(filters or {})
	conditions = [
		"pr.docstatus = 1",
		"(pr.is_bns_internal_supplier = 1 OR s.is_bns_internal_supplier = 1)",
		"IFNULL(pr.bns_inter_company_reference, '') != ''",
	]
	values = []
	_date_company(filters, "dn", conditions, values)
	_filter_by_party(filters, "dn", conditions, values)

	rows = frappe.db.sql(
		f"""
		SELECT
			dn.name          AS dn_name,
			dn.posting_date,
			dn.grand_total,
			dn.company_address  AS company_address_name,
			dn.customer_address AS customer_address_name,
			pr.name          AS pr_name
		FROM `tabPurchase Receipt` pr
		LEFT JOIN `tabSupplier` s ON s.name = pr.supplier
		JOIN `tabDelivery Note` dn
			ON dn.name = pr.bns_inter_company_reference
			AND dn.docstatus = 1
		WHERE {" AND ".join(conditions)}
			AND IFNULL(dn.bns_inter_company_reference, '') = ''
		""",
		tuple(values),
		as_dict=True,
	) or []

	data = []
	for row in rows:
		data.append(_empty_mismatch_row(
			posting_date=row.get("posting_date"),
			document_type="Delivery Note",
			document_name=row.get("dn_name"),
			grand_total=flt(row.get("grand_total") or 0),
			company_address_name=row.get("company_address_name") or "",
			customer_address_name=row.get("customer_address_name") or "",
			missing_document="DN ↔ PR Back-Reference",
			mismatch_reason=(
				f"PR {row.get('pr_name')} references this DN, "
				f"but DN has no bns_inter_company_reference back to the PR"
			),
			purchase_receipt=row.get("pr_name"),
			transfer_chain="DN->PR",
		))

	return data


def get_duplicate_and_foreign_reference_mismatches(filters=None):
	"""Detect legacy linkage glitches in internal transfer references.

	The bns_inter_company_reference link is strictly one-to-one, but older
	documents predate both the field's no_copy flag (Duplicate / Amend used
	to silently copy the ref) and the creation-flow duplicate guards. States:

	1. Duplicate claimants — two or more submitted PRs (or PIs) referencing
	   the same source DN/SI; two or more submitted internal SIs made from the
	   same Delivery Note (_validate_single_internal_si_per_dn).
	2. Foreign-party reference — a PR/PI carrying an internal reference while
	   its supplier MASTER is not BNS internal (DN/SI counterpart: customer
	   master not internal but back-reference set). The document tick alone does
	   not count: validation and GL go by the master (utils.is_bns_internal_supplier).
	3. Conflicting claim — a PR references a DN whose own back-reference
	   points at a different PR.
	"""
	filters = frappe._dict(filters or {})
	data = []

	def _conds(alias):
		conds, vals = [], []
		_date_company(filters, alias, conds, vals)
		return conds, vals

	def _resolve_source_doctype(name):
		if frappe.db.exists("Delivery Note", name):
			return "Delivery Note"
		if frappe.db.exists("Sales Invoice", name):
			return "Sales Invoice"
		return None

	# ── 1 + 2: claimant side (PR / PI) ─────────────────────────────────
	for claim_dt in ("Purchase Receipt", "Purchase Invoice"):
		conds, vals = _conds("d")
		where = " AND ".join(
			["d.docstatus = 1", "IFNULL(d.is_return, 0) = 0", "COALESCE(d.bns_inter_company_reference, '') != ''"]
			+ conds
		)

		dup_groups = frappe.db.sql(
			f"""
			SELECT
				d.bns_inter_company_reference AS source_ref,
				COUNT(*) AS cnt,
				GROUP_CONCAT(d.name ORDER BY d.name SEPARATOR ', ') AS claimants,
				MAX(d.posting_date) AS posting_date,
				SUM(d.grand_total) AS grand_total
			FROM `tab{claim_dt}` d
			WHERE {where}
			GROUP BY d.bns_inter_company_reference
			HAVING COUNT(*) > 1
			""",
			tuple(vals),
			as_dict=True,
		) or []

		for g in dup_groups:
			source_dt = _resolve_source_doctype(g.get("source_ref"))
			first_claimant = (g.get("claimants") or "").split(", ")[0]
			# purchase_receipt / purchase_invoice are Link columns — a
			# comma-joined claimant list would render as a broken link, so
			# point them at the first claimant; the full list is in the
			# reason. When the source doc no longer exists, anchor the row
			# on the first claimant too (document_name is a Dynamic Link
			# and needs a real doctype).
			data.append(_empty_mismatch_row(
				posting_date=g.get("posting_date"),
				document_type=source_dt or claim_dt,
				document_name=g.get("source_ref") if source_dt else first_claimant,
				grand_total=flt(g.get("grand_total") or 0),
				missing_document="Unique claimant (strict 1:1)",
				mismatch_reason=(
					f"{g.get('cnt')} submitted {claim_dt}s reference "
					f"{'this source' if source_dt else 'missing source ' + (g.get('source_ref') or '?')} "
					f"(link is strictly one-to-one): {g.get('claimants')}"
				),
				purchase_receipt=first_claimant if claim_dt == "Purchase Receipt" else None,
				purchase_invoice=first_claimant if claim_dt == "Purchase Invoice" else None,
				transfer_chain="Duplicate claimants",
			))

		foreign_rows = frappe.db.sql(
			f"""
			SELECT d.name, d.posting_date, d.grand_total, d.supplier,
				d.bns_inter_company_reference AS source_ref
			FROM `tab{claim_dt}` d
			LEFT JOIN `tabSupplier` s ON s.name = d.supplier
			WHERE {where}
				AND COALESCE(d.is_bns_internal_supplier, 0) = 0
				AND COALESCE(s.is_bns_internal_supplier, 0) = 0
			""",
			tuple(vals),
			as_dict=True,
		) or []

		for r in foreign_rows:
			data.append(_empty_mismatch_row(
				posting_date=r.get("posting_date"),
				document_type=claim_dt,
				document_name=r.get("name"),
				grand_total=flt(r.get("grand_total") or 0),
				missing_document="BNS Internal Supplier flag",
				mismatch_reason=(
					f"Carries internal reference {r.get('source_ref')} but supplier {r.get('supplier')} "
					f"is not BNS internal (likely a pre-no_copy Duplicate/Amend or import)"
				),
				purchase_receipt=r.get("name") if claim_dt == "Purchase Receipt" else None,
				purchase_invoice=r.get("name") if claim_dt == "Purchase Invoice" else None,
				transfer_chain="Foreign-party reference",
			))

	# ── 1b: two internal SIs made from one Delivery Note ───────────────
	conds, vals = _conds("si")
	where = " AND ".join(
		[
			"si.docstatus = 1", "IFNULL(si.is_return, 0) = 0",
			"(si.is_bns_internal_customer = 1 OR c.is_bns_internal_customer = 1)",
			"IFNULL(i.delivery_note, '') != ''",
		]
		+ conds
	)
	for g in frappe.db.sql(
		f"""
		SELECT i.delivery_note, COUNT(DISTINCT si.name) AS cnt,
			GROUP_CONCAT(DISTINCT si.name ORDER BY si.name SEPARATOR ', ') AS invoices,
			MAX(si.posting_date) AS posting_date
		FROM `tabSales Invoice Item` i
		JOIN `tabSales Invoice` si ON si.name = i.parent
		LEFT JOIN `tabCustomer` c ON c.name = si.customer
		WHERE {where}
		GROUP BY i.delivery_note
		HAVING COUNT(DISTINCT si.name) > 1
		""",
		tuple(vals),
		as_dict=True,
	) or []:
		data.append(_empty_mismatch_row(
			posting_date=g.get("posting_date"),
			document_type="Delivery Note",
			document_name=g.get("delivery_note"),
			missing_document="Unique internal SI per DN",
			mismatch_reason=(
				f"{g.get('cnt')} submitted internal Sales Invoices are made from this Delivery Note "
				f"(only one is allowed): {g.get('invoices')}"
			),
			transfer_chain="Duplicate claimants",
		))

	# ── 2b: source side (DN / SI) — back-ref set but customer not internal ─
	for source_dt in ("Delivery Note", "Sales Invoice"):
		conds, vals = _conds("d")
		where = " AND ".join(
			[
				"d.docstatus = 1",
				"COALESCE(d.bns_inter_company_reference, '') != ''",
				"COALESCE(d.is_bns_internal_customer, 0) = 0",
				"COALESCE(c.is_bns_internal_customer, 0) = 0",
			]
			+ conds
		)
		rows = frappe.db.sql(
			f"""
			SELECT d.name, d.posting_date, d.grand_total, d.customer,
				d.bns_inter_company_reference AS backref
			FROM `tab{source_dt}` d
			LEFT JOIN `tabCustomer` c ON c.name = d.customer
			WHERE {where}
			""",
			tuple(vals),
			as_dict=True,
		) or []
		for r in rows:
			data.append(_empty_mismatch_row(
				posting_date=r.get("posting_date"),
				document_type=source_dt,
				document_name=r.get("name"),
				grand_total=flt(r.get("grand_total") or 0),
				missing_document="BNS Internal Customer flag",
				mismatch_reason=(
					f"Has internal back-reference {r.get('backref')} but customer {r.get('customer')} "
					f"is not BNS internal"
				),
				transfer_chain="Foreign-party reference",
			))

	# ── 3: conflicting claim — PR refs DN, DN back-refs a different PR ──
	conds, vals = _conds("pr")
	where = " AND ".join(
		["pr.docstatus = 1", "COALESCE(pr.bns_inter_company_reference, '') != ''"] + conds
	)
	conflict_rows = frappe.db.sql(
		f"""
		SELECT
			pr.name AS pr_name, pr.posting_date, pr.grand_total,
			dn.name AS dn_name,
			dn.bns_inter_company_reference AS dn_backref
		FROM `tabPurchase Receipt` pr
		JOIN `tabDelivery Note` dn
			ON dn.name = pr.bns_inter_company_reference
			AND dn.docstatus = 1
		WHERE {where}
			AND COALESCE(dn.bns_inter_company_reference, '') != ''
			AND dn.bns_inter_company_reference != pr.name
		""",
		tuple(vals),
		as_dict=True,
	) or []

	for r in conflict_rows:
		data.append(_empty_mismatch_row(
			posting_date=r.get("posting_date"),
			document_type="Purchase Receipt",
			document_name=r.get("pr_name"),
			grand_total=flt(r.get("grand_total") or 0),
			missing_document="Consistent DN back-reference",
			mismatch_reason=(
				f"PR claims DN {r.get('dn_name')}, but the DN back-references a "
				f"different PR ({r.get('dn_backref')})"
			),
			purchase_receipt=r.get("pr_name"),
			transfer_chain="Conflicting claim",
		))

	return data


def get_external_party_internal_mismatches(filters=None):
	"""Flag documents treated as INTERNAL while their party master is EXTERNAL.

	A SI / DN / PI / PR is "treated internal" when its own internal flag is set
	OR its status is 'BNS Internally Transferred' (set whenever BNS applies the
	internal-transfer GL rewrite). If the linked Customer / Supplier master is
	not flagged internal, the document was mis-classified and is posting
	internal-transfer GL (Internal Debtor/Creditor/Sales/Purchase) it should
	not — e.g. an external supplier whose bill_no collided with our Sales
	Invoice naming series, or a flag copied via Duplicate/Amend.
	"""
	filters = frappe._dict(filters or {})
	data = []

	# (doctype, party_field, party_doctype, doc_flag_field, master_flag_field)
	specs = [
		("Sales Invoice", "customer", "Customer", "is_bns_internal_customer", "is_bns_internal_customer"),
		("Delivery Note", "customer", "Customer", "is_bns_internal_customer", "is_bns_internal_customer"),
		("Purchase Invoice", "supplier", "Supplier", "is_bns_internal_supplier", "is_bns_internal_supplier"),
		("Purchase Receipt", "supplier", "Supplier", "is_bns_internal_supplier", "is_bns_internal_supplier"),
	]

	for dt, party_field, party_dt, doc_flag, master_flag in specs:
		conds = [
			"d.docstatus = 1",
			f"(COALESCE(d.{doc_flag}, 0) = 1 OR d.status = 'BNS Internally Transferred')",
			f"COALESCE(p.{master_flag}, 0) = 0",
		]
		vals = []
		_date_company(filters, "d", conds, vals)

		rows = frappe.db.sql(
			f"""
			SELECT d.name, d.posting_date, d.grand_total, d.status,
			       d.{party_field} AS party, COALESCE(d.{doc_flag}, 0) AS doc_flag
			FROM `tab{dt}` d
			JOIN `tab{party_dt}` p ON p.name = d.{party_field}
			WHERE {" AND ".join(conds)}
			""",
			tuple(vals),
			as_dict=True,
		) or []

		for r in rows:
			data.append(_empty_mismatch_row(
				posting_date=r.get("posting_date"),
				document_type=dt,
				document_name=r.get("name"),
				grand_total=flt(r.get("grand_total") or 0),
				missing_document=f"Internal flag on external {party_dt}",
				mismatch_reason=(
					f"{party_dt} {r.get('party')} is NOT flagged internal, but this {dt} "
					f"is treated internal (doc flag={int(r.get('doc_flag') or 0)}, "
					f"status='{r.get('status')}') — verify it is not an external party "
					f"mis-classified as an internal transfer"
				),
				transfer_chain="External party treated as internal",
			))

	return data


# ---------------------------------------------------------------------------
# Bulk repair: external party mis-classified as internal
# ---------------------------------------------------------------------------

# (doctype, party_field, party_doctype, doc_flag_field)
_EXTERNAL_PARTY_FIX_SPEC = {
	"Sales Invoice": ("customer", "Customer", "is_bns_internal_customer"),
	"Delivery Note": ("customer", "Customer", "is_bns_internal_customer"),
	"Purchase Invoice": ("supplier", "Supplier", "is_bns_internal_supplier"),
	"Purchase Receipt": ("supplier", "Supplier", "is_bns_internal_supplier"),
}


@frappe.whitelist()
def fix_external_party_internal_documents(documents):
	"""Clear the internal markers on documents whose party master is EXTERNAL,
	then repost so GL reverts from internal-transfer accounts to the standard
	external pattern.

	Targets the report's "External party treated as internal" rows. For each doc
	it re-verifies the party master is genuinely external (safety), then clears
	the internal flag, bns_internal_status and bns_inter_company_reference, resets
	a 'BNS Internally Transferred' status to the standard computed status, and
	reposts the GL via Repost Accounting Ledger (the BNS GL rewrite then skips,
	emitting normal external GL).

	Gated by BNS Branch Accounting Settings write; the actual mutations run with
	ignore_permissions because that admin gate is already cleared.

	Args:
		documents: JSON string of [{voucher_type|document_type, voucher_no|document_name}, ...].
	"""
	if not frappe.has_permission("BNS Branch Accounting Settings", "write"):
		frappe.throw(
			_("BNS Branch Accounting Settings write permission required."),
			frappe.PermissionError,
		)

	if isinstance(documents, str):
		documents = json.loads(documents)

	if not documents:
		frappe.throw(_("No documents provided for external-party fix."))

	frappe.enqueue(
		"business_needed_solutions.bns_branch_accounting.report"
		".internal_transfer_receive_mismatch.internal_transfer_receive_mismatch"
		"._process_external_party_fix_batch",
		queue="long",
		timeout=1800,
		documents=documents,
	)

	return {
		"success": True,
		"message": _(
			"External-party fix + repost enqueued for {0} document(s). "
			"Check Background Jobs for progress."
		).format(len(documents)),
	}


def _process_external_party_fix_batch(documents):
	"""Worker: reconcile each flagged document's internal markers to its PARTY
	MASTER (the source of truth), then repost GL.

	- Master EXTERNAL: clear the doc internal flag / status / reference -> the BNS
	  rewrite skips and the doc emits the standard external GL.
	- Master INTERNAL: the document is a legitimate internal transfer that lost its
	  doc-level flag (e.g. a pre-no_copy Duplicate/Amend/import). HEAL it -- set the
	  flag, keep the reference -- and repost so the internal GL pattern is asserted.
	"""
	from business_needed_solutions.bns_branch_accounting.utils import (
		_apply_bns_internal_gl_rewrite_patch,
	)

	success = 0
	healed = 0
	errors = 0
	skipped = 0
	failures = []

	for entry in documents:
		voucher_type = entry.get("voucher_type") or entry.get("document_type") or ""
		voucher_no = entry.get("voucher_no") or entry.get("document_name") or ""

		spec = _EXTERNAL_PARTY_FIX_SPEC.get(voucher_type)
		if not spec or not voucher_no:
			errors += 1
			failures.append(f"{voucher_type or '?'} {voucher_no or '?'}: unsupported doctype")
			continue

		party_field, party_dt, doc_flag = spec
		try:
			doc = frappe.get_doc(voucher_type, voucher_no)
			if doc.docstatus != 1:
				errors += 1
				failures.append(f"{voucher_type} {voucher_no}: not submitted")
				continue

			# Reconcile the doc to its party master (the source of truth).
			party = doc.get(party_field)
			master_internal = bool(party and frappe.db.get_value(party_dt, party, doc_flag))
			meta = frappe.get_meta(voucher_type)

			if master_internal:
				# HEAL: legitimate internal transfer that lost its doc-level flag.
				if cint(doc.get(doc_flag)):
					skipped += 1
					failures.append(f"{voucher_type} {voucher_no}: already flagged internal — nothing to do")
					continue
				frappe.db.set_value(voucher_type, voucher_no, doc_flag, 1, update_modified=False)
				healed += 1
			else:
				# CLEAR: external party wrongly carrying internal markers.
				frappe.db.set_value(voucher_type, voucher_no, doc_flag, 0, update_modified=False)
				if meta.has_field("bns_internal_status"):
					frappe.db.set_value(voucher_type, voucher_no, "bns_internal_status", None, update_modified=False)
				if meta.has_field("bns_inter_company_reference"):
					frappe.db.set_value(voucher_type, voucher_no, "bns_inter_company_reference", None, update_modified=False)
				if (doc.get("status") or "") == "BNS Internally Transferred":
					fresh = frappe.get_doc(voucher_type, voucher_no)
					fresh.set_status(update=True)
				success += 1

			# Repost GL so the pattern matches the now-consistent flag.
			_apply_bns_internal_gl_rewrite_patch()
			ral = frappe.new_doc("Repost Accounting Ledger")
			ral.company = doc.company
			ral.delete_cancelled_entries = 0
			ral.append("vouchers", {"voucher_type": voucher_type, "voucher_no": voucher_no})
			ral.flags.ignore_permissions = True
			ral.save()
			ral.submit()

			frappe.db.commit()
		except Exception as e:
			errors += 1
			frappe.db.rollback()
			failures.append(f"{voucher_type} {voucher_no}: {str(e)[:200]}")
			frappe.log_error(title=f"External-party fix error: {voucher_type} {voucher_no}")

	message = _(
		"Internal-flag reconcile complete: {0} cleared (external), {1} healed "
		"(flag set, master internal), {2} skipped, {3} failed."
	).format(success, healed, skipped, errors)
	if failures:
		message += "<br><br>" + _("Details:") + "<br>" + "<br>".join(
			frappe.utils.escape_html(f) for f in failures[:25]
		)
		if len(failures) > 25:
			message += "<br>" + _("(showing first 25 of {0})").format(len(failures))

	frappe.publish_realtime(
		"msgprint",
		{
			"message": message,
			"title": _("Internal-Flag Reconcile"),
			"indicator": "green" if errors == 0 else "orange",
		},
	)


