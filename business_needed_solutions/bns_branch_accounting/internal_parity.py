# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""Strict one-to-one parity between an internal-transfer document and its source.

Links covered (forward documents only; returns follow the return rules):

    DN -> SI   Sales Invoice rows made from Delivery Note rows      (row.dn_detail)
    DN -> PR   Purchase Receipt from a Delivery Note (same GSTIN)  (row.delivery_note_item)
    SI -> PR   Purchase Receipt from a Sales Invoice (diff. GSTIN) (row.sales_invoice_item)
    SI -> PI   Purchase Invoice from a Sales Invoice                (row.sales_invoice_item,
                                                                    or through its PR row)
    PR -> PI   Purchase Invoice from a Purchase Receipt             (row.pr_detail)

Nothing may change from one document to the next: every target row is linked to exactly
one source row and every source row is used exactly once; item, UOM, conversion factor,
quantities, rates, amounts, HSN and the item-level GST rates and amounts are equal; the
taxes are equal per GST head (CGST / SGST / IGST / cess, rate and amount) and in total;
the header totals are equal; and where both documents move stock, the batches and
serials are the same.

`compare_internal_pair` returns the differences (the reports list them);
`assert_internal_pair` throws them (the submit / save checks). Both use the same rules,
so a document the check lets through never shows up in the reports, and the reverse.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

DN, SI, PR, PI = "Delivery Note", "Sales Invoice", "Purchase Receipt", "Purchase Invoice"

# (field, label, decimals). Rates and quantities at 6 places, amounts at the paisa.
ROW_NUMBERS = (
	("qty", "Quantity", 6),
	("stock_qty", "Stock Quantity", 6),
	("conversion_factor", "Conversion Factor", 6),
	("rate", "Rate", 6),
	("base_rate", "Base Rate", 6),
	("amount", "Amount", 2),
	("base_amount", "Base Amount", 2),
	("net_rate", "Taxable Rate", 6),
	("base_net_rate", "Base Taxable Rate", 6),
	("net_amount", "Taxable Amount", 2),
	("base_net_amount", "Base Taxable Amount", 2),
)
ROW_TEXT = (
	("item_code", "Item"),
	("uom", "UOM"),
	("stock_uom", "Stock UOM"),
	("gst_hsn_code", "HSN/SAC"),
)
# India Compliance item-level GST (present on v15 and v16 when it is installed).
ROW_GST = (
	("igst_rate", "IGST Rate", 3),
	("igst_amount", "IGST Amount", 2),
	("cgst_rate", "CGST Rate", 3),
	("cgst_amount", "CGST Amount", 2),
	("sgst_rate", "SGST Rate", 3),
	("sgst_amount", "SGST Amount", 2),
	("cess_rate", "Cess Rate", 3),
	("cess_amount", "Cess Amount", 2),
	("cess_non_advol_rate", "Cess (Non-Advol) Rate", 3),
	("cess_non_advol_amount", "Cess (Non-Advol) Amount", 2),
)
HEADER_NUMBERS = (
	("total_qty", "Total Quantity", 6),
	("total", "Total", 2),
	("base_total", "Base Total", 2),
	("net_total", "Taxable Total", 2),
	("base_net_total", "Base Taxable Total", 2),
	("total_taxes_and_charges", "Total Taxes", 2),
	("base_total_taxes_and_charges", "Base Total Taxes", 2),
	("grand_total", "Grand Total", 2),
	("base_grand_total", "Base Grand Total", 2),
)


@dataclass
class Mismatch:
	link: str
	target: str
	source: str
	row: int | None  # target row idx (None: header / taxes / a missing row)
	item_code: str
	field: str
	expected: object  # source value
	found: object  # target value

	def message(self) -> str:
		where = _("Row {0} ({1})").format(self.row, self.item_code) if self.row else (self.item_code or _("Totals"))
		return _("{0}: {1} is {2} on {3} but {4} here").format(
			where, self.field, _fmt(self.expected), self.source, _fmt(self.found)
		)


def _fmt(value):
	if isinstance(value, float):
		return f"{value:,.6f}".rstrip("0").rstrip(".")
	if value in (None, ""):
		return "—"
	return cstr(value)


# --------------------------------------------------------------------------------------
# Which link a document is on, and its source rows
# --------------------------------------------------------------------------------------


def detect_links(doc) -> list[str]:
	"""The parity links that apply to this (forward, internal) document."""
	items = doc.get("items") or []
	if doc.doctype == SI:
		return ["DN->SI"] if any(cstr(r.get("delivery_note")).strip() for r in items) else []
	if doc.doctype == PR:
		ref = cstr(doc.get("bns_inter_company_reference")).strip()
		if not ref:
			return []
		if frappe.db.exists(DN, ref):
			return ["DN->PR"]
		if frappe.db.exists(SI, ref):
			return ["SI->PR"]
		return []
	if doc.doctype == PI:
		links = []
		if any(cstr(r.get("pr_detail")).strip() or cstr(r.get("purchase_receipt")).strip() for r in items):
			links.append("PR->PI")
		from business_needed_solutions.bns_branch_accounting.utils import _resolve_si_name_for_internal_pi

		if _resolve_si_name_for_internal_pi(doc):
			links.append("SI->PI")
		return links
	return []


def _source_docs(doc, link):
	items = doc.get("items") or []
	if link == "DN->SI":
		names = sorted({cstr(r.get("delivery_note")).strip() for r in items} - {""})
		return [frappe.get_doc(DN, n) for n in names if frappe.db.exists(DN, n)]
	if link in ("DN->PR", "SI->PR"):
		ref = cstr(doc.get("bns_inter_company_reference")).strip()
		return [frappe.get_doc(DN if link == "DN->PR" else SI, ref)]
	if link == "PR->PI":
		names = sorted({cstr(r.get("purchase_receipt")).strip() for r in items} - {""})
		return [frappe.get_doc(PR, n) for n in names if frappe.db.exists(PR, n)]
	if link == "SI->PI":
		from business_needed_solutions.bns_branch_accounting.utils import _resolve_si_name_for_internal_pi

		name = _resolve_si_name_for_internal_pi(doc)
		return [frappe.get_doc(SI, name)] if name else []
	return []


def _source_row_name(doc, row, link) -> str:
	if link == "DN->SI":
		return cstr(row.get("dn_detail")).strip()
	if link == "DN->PR":
		return cstr(row.get("delivery_note_item")).strip()
	if link == "SI->PR":
		return cstr(row.get("sales_invoice_item")).strip()
	if link == "PR->PI":
		return cstr(row.get("pr_detail")).strip()
	if link == "SI->PI":
		name = cstr(row.get("sales_invoice_item")).strip()
		if not name and cstr(row.get("pr_detail")).strip():
			name = cstr(frappe.db.get_value("Purchase Receipt Item", row.pr_detail, "sales_invoice_item")).strip()
		return name
	return ""


def _target_rows(doc, link):
	rows = doc.get("items") or []
	if link == "DN->SI":
		# Rows not made from a DN cannot be part of a DN-linked internal invoice.
		return rows
	return rows


def _moves_stock(doc) -> bool:
	if doc.doctype in (DN, PR):
		return True
	return bool(cint(doc.get("update_stock")))


# --------------------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------------------


def compare_internal_pair(doc, link: str) -> list[Mismatch]:
	"""Every difference between `doc` and its source(s) on `link`. Empty when identical."""
	sources = _source_docs(doc, link)
	if not sources:
		return []
	source_label = ", ".join(s.name for s in sources)
	out: list[Mismatch] = []

	def add(row, item_code, field, expected, found):
		out.append(Mismatch(link, doc.name or _("this document"), source_label, row, item_code or "", field,
							expected, found))

	source_rows = {}
	for s in sources:
		for r in s.get("items") or []:
			source_rows[r.name] = r

	used = set()
	matched = []
	for row in _target_rows(doc, link):
		name = _source_row_name(doc, row, link)
		src = source_rows.get(name)
		if not src:
			add(row.idx, row.item_code, _("Source row"), _("a row of {0}").format(source_label),
				_("not linked to any"))
			continue
		if name in used:
			add(row.idx, row.item_code, _("Source row"), _("used once"), _("used again"))
			continue
		used.add(name)
		matched.append((row, src))

	for name, src in source_rows.items():
		if name not in used:
			add(None, src.item_code, _("Row"), _("row {0}, qty {1}").format(src.idx, _fmt(flt(src.qty))),
				_("missing"))

	gst_fields = [f for f in ROW_GST if frappe.get_meta(doc.doctype + " Item").has_field(f[0])]
	# Lots are compared once the document is being submitted (or is submitted): a draft
	# receiver gets its bundle copied from the sender only at validate / submit.
	stock = cint(doc.docstatus) == 1 and _moves_stock(doc) and all(_moves_stock(s) for s in sources)
	for row, src in matched:
		for field, label in ROW_TEXT:
			if cstr(row.get(field)).strip() != cstr(src.get(field)).strip():
				add(row.idx, row.item_code, _(label), src.get(field), row.get(field))
		for field, label, places in ROW_NUMBERS + tuple(gst_fields):
			if round(flt(row.get(field)), places) != round(flt(src.get(field)), places):
				add(row.idx, row.item_code, _(label), flt(src.get(field)), flt(row.get(field)))
		if stock:
			for field, expected, found in _lot_differences(row, src):
				add(row.idx, row.item_code, field, expected, found)

	for field, label, places in HEADER_NUMBERS:
		expected = sum(flt(s.get(field)) for s in sources)
		if round(flt(doc.get(field)), places) != round(expected, places):
			add(None, "", _(label), expected, flt(doc.get(field)))

	target_tax, source_tax = _gst_heads(doc), defaultdict(lambda: {"rate": set(), "amount": 0.0})
	for s in sources:
		for head, v in _gst_heads(s).items():
			source_tax[head]["rate"] |= v["rate"]
			source_tax[head]["amount"] += v["amount"]
	for head in sorted(set(target_tax) | set(source_tax)):
		t = target_tax.get(head) or {"rate": set(), "amount": 0.0}
		s = source_tax.get(head) or {"rate": set(), "amount": 0.0}
		label = head.upper()
		# The rate is compared per row (cgst_rate, igst_rate, ...); a tax row may carry it
		# as "Actual" with rate 0 on one side, so only the amount per head is compared here.
		if round(t["amount"], 2) != round(s["amount"], 2):
			add(None, "", _("{0} amount").format(label), s["amount"], t["amount"])
	return out


def _rates(rates):
	return ", ".join(_fmt(r) for r in sorted(rates)) or "—"


def _gst_heads(doc) -> dict:
	"""GST per head ({"cgst": {"rate": {9.0}, "amount": 900.0}, ...}) from the tax rows.
	Accounts differ between sender (output) and receiver (input), so heads are compared
	by GST type, never by account."""
	heads: dict = {}
	for t in doc.get("taxes") or []:
		head = cstr(t.get("gst_tax_type")).strip().lower()
		if not head or cint(t.get("is_tax_withholding_account")):
			continue
		amount = flt(t.get("base_tax_amount_after_discount_amount") or t.get("base_tax_amount"))
		if t.get("add_deduct_tax") == "Deduct":
			amount = -amount
		h = heads.setdefault(head, {"rate": set(), "amount": 0.0})
		if flt(t.get("rate")):
			h["rate"].add(round(flt(t.get("rate")), 3))
		h["amount"] += amount
	return heads


def _lot_differences(row, src):
	"""Batches / serials a stock-moving row carries, against its source row."""
	from business_needed_solutions.bns_branch_accounting.serial_batch_parity_check import _extract, _tracking

	has_serial, has_batch = _tracking(row.item_code)
	if not (has_serial or has_batch):
		return []
	a, b = _extract(src, has_serial, has_batch), _extract(row, has_serial, has_batch)
	diffs = []
	if has_serial and set(a.serials) != set(b.serials):
		missing, extra = sorted(set(a.serials) - set(b.serials)), sorted(set(b.serials) - set(a.serials))
		diffs.append((_("Serial Nos"), ", ".join(missing) or "—", ", ".join(extra) or "—"))
	if has_batch:
		sa = {k: round(abs(flt(v)), 6) for k, v in (a.batches or {}).items()}
		sb = {k: round(abs(flt(v)), 6) for k, v in (b.batches or {}).items()}
		if sa != sb:
			diffs.append((_("Batches"), _batch_text(sa), _batch_text(sb)))
	if has_serial and has_batch and (a.serial_batch or {}) != (b.serial_batch or {}):
		diffs.append((_("Serial → Batch"), _("as sent"), _("changed")))
	return diffs


def _batch_text(batches):
	return ", ".join(f"{k} × {_fmt(v)}" for k, v in sorted(batches.items())) or "—"


# --------------------------------------------------------------------------------------
# Enforcement
# --------------------------------------------------------------------------------------


def applies(doc) -> bool:
	"""Forward internal-transfer document on or after the internal-transfer cutoff."""
	from business_needed_solutions.bns_branch_accounting import utils

	if cint(doc.get("is_return")):
		return False
	if doc.doctype == SI:
		internal = utils.is_bns_internal_customer(doc)
	elif doc.doctype in (PR, PI):
		internal = utils.is_bns_internal_supplier(doc) or bool(cstr(doc.get("bns_inter_company_reference")).strip())
	else:
		return False
	if not internal:
		return False
	return bool(utils.is_after_internal_transfer_cutoff(utils._resolve_source_posting_date(doc)
														  if doc.doctype != SI else doc.get("posting_date")))


def internal_pair_mismatches(doc) -> list[Mismatch]:
	out = []
	for link in detect_links(doc):
		out += compare_internal_pair(doc, link)
	return out


def assert_internal_pair(doc, method=None, links=None, force=False) -> None:
	"""Throw when the document differs in anything from its source document(s).
	force=True: the caller already decided the document is in scope (its own cutoff rules)."""
	if not force and not applies(doc):
		return
	mismatches = []
	for link in links or detect_links(doc):
		mismatches += compare_internal_pair(doc, link)
	if not mismatches:
		return
	shown = mismatches[:15]
	lines = "<br>".join(frappe.utils.escape_html(m.message()) for m in shown)
	more = _("<br>… and {0} more.").format(len(mismatches) - len(shown)) if len(mismatches) > len(shown) else ""
	frappe.throw(
		_("{0} must be an exact copy of {1} ({2}). Differences:<br>{3}{4}").format(
			doc.doctype, mismatches[0].source, mismatches[0].link, lines, more
		),
		title=_("Internal Transfer Mismatch"),
	)


def as_dicts(mismatches):
	return [asdict(m) | {"message": m.message()} for m in mismatches]


# Public name for the reports.
fmt = _fmt
