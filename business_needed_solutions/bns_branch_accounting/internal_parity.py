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
one source row and every source row is used exactly once (one exception: a Sales Invoice
made from a Delivery Note may add a non-stock row of zero value, such as packing, since it
moves no stock and no money); item, UOM, conversion factor, quantities, rates, amounts,
HSN and the item-level GST rates and amounts are equal; the taxes are equal per GST head
and in total; the header totals are equal; and where both documents move stock, the
batches and serials are the same. These strict rules are what the submit / save checks
enforce (assert_internal_pair, si_pi_link_mismatches).

The reports (report=True) compare tax-exclusive values only. One side may carry tax
inside its rate (included_in_print_rate) and the other add it on top: their rate /
amount / total differ by the tax while the ledger is the same, so the reports skip those
fields; taxable rates stay exact, and taxable amounts, item-level GST amounts, GST per
head, taxable totals, total taxes and grand total agree within Rs 1 (inclusive and
exclusive tax round the paise apart).

Rows are matched through their link (dn_detail / delivery_note_item / sales_invoice_item
/ pr_detail), never by item code, so an item on several rows of one invoice is compared
with its own source row.

`compare_internal_pair` returns the differences (the reports list them, report=True);
`assert_internal_pair` throws them (the submit / save checks, strict). A document the
check lets through never shows up in the reports.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

DN, SI, PR, PI = "Delivery Note", "Sales Invoice", "Purchase Receipt", "Purchase Invoice"

# Rupees two amounts may differ by: inclusive and exclusive tax round the paise apart.
AMOUNT_TOLERANCE = 1.0

# Submit / save checks: (field, label, decimals, tolerance), all exact. Rates and
# quantities at 6 places, amounts at the paisa.
ROW_NUMBERS = (
	("qty", "Quantity", 6, 0),
	("stock_qty", "Stock Quantity", 6, 0),
	("conversion_factor", "Conversion Factor", 6, 0),
	("rate", "Rate", 6, 0),
	("base_rate", "Base Rate", 6, 0),
	("amount", "Amount", 2, 0),
	("base_amount", "Base Amount", 2, 0),
	("net_rate", "Taxable Rate", 6, 0),
	("base_net_rate", "Base Taxable Rate", 6, 0),
	("net_amount", "Taxable Amount", 2, 0),
	("base_net_amount", "Base Taxable Amount", 2, 0),
)
# Reports: tax-exclusive values only. Quantities and rates exact, amounts within
# AMOUNT_TOLERANCE; rate, amount and total (tax-inclusive on one side) are skipped.
REPORT_ROW_NUMBERS = (
	("qty", "Quantity", 6, 0),
	("stock_qty", "Stock Quantity", 6, 0),
	("conversion_factor", "Conversion Factor", 6, 0),
	("net_rate", "Taxable Rate", 6, 0),
	("base_net_rate", "Base Taxable Rate", 6, 0),
	("net_amount", "Taxable Amount", 2, AMOUNT_TOLERANCE),
	("base_net_amount", "Base Taxable Amount", 2, AMOUNT_TOLERANCE),
)
ROW_TEXT = (
	("item_code", "Item"),
	("uom", "UOM"),
	("stock_uom", "Stock UOM"),
	("gst_hsn_code", "HSN/SAC"),
)
# India Compliance item-level GST (present on v15 and v16 when it is installed).
ROW_GST = (
	("igst_rate", "IGST Rate", 3, 0),
	("igst_amount", "IGST Amount", 2, 0),
	("cgst_rate", "CGST Rate", 3, 0),
	("cgst_amount", "CGST Amount", 2, 0),
	("sgst_rate", "SGST Rate", 3, 0),
	("sgst_amount", "SGST Amount", 2, 0),
	("cess_rate", "Cess Rate", 3, 0),
	("cess_amount", "Cess Amount", 2, 0),
	("cess_non_advol_rate", "Cess (Non-Advol) Rate", 3, 0),
	("cess_non_advol_amount", "Cess (Non-Advol) Amount", 2, 0),
)
REPORT_ROW_GST = (
	("igst_rate", "IGST Rate", 3, 0),
	("igst_amount", "IGST Amount", 2, AMOUNT_TOLERANCE),
	("cgst_rate", "CGST Rate", 3, 0),
	("cgst_amount", "CGST Amount", 2, AMOUNT_TOLERANCE),
	("sgst_rate", "SGST Rate", 3, 0),
	("sgst_amount", "SGST Amount", 2, AMOUNT_TOLERANCE),
	("cess_rate", "Cess Rate", 3, 0),
	("cess_amount", "Cess Amount", 2, AMOUNT_TOLERANCE),
	("cess_non_advol_rate", "Cess (Non-Advol) Rate", 3, 0),
	("cess_non_advol_amount", "Cess (Non-Advol) Amount", 2, AMOUNT_TOLERANCE),
)
HEADER_NUMBERS = (
	("total_qty", "Total Quantity", 6, 0),
	("total", "Total", 2, 0),
	("base_total", "Base Total", 2, 0),
	("net_total", "Taxable Total", 2, 0),
	("base_net_total", "Base Taxable Total", 2, 0),
	("total_taxes_and_charges", "Total Taxes", 2, 0),
	("base_total_taxes_and_charges", "Base Total Taxes", 2, 0),
	("grand_total", "Grand Total", 2, 0),
	("base_grand_total", "Base Grand Total", 2, 0),
)
REPORT_HEADER_NUMBERS = (
	("total_qty", "Total Quantity", 6, 0),
	("net_total", "Taxable Total", 2, AMOUNT_TOLERANCE),
	("base_net_total", "Base Taxable Total", 2, AMOUNT_TOLERANCE),
	("total_taxes_and_charges", "Total Taxes", 2, AMOUNT_TOLERANCE),
	("base_total_taxes_and_charges", "Base Total Taxes", 2, AMOUNT_TOLERANCE),
	("grand_total", "Grand Total", 2, AMOUNT_TOLERANCE),
	("base_grand_total", "Base Grand Total", 2, AMOUNT_TOLERANCE),
)


def _differs(a, b, places, tolerance=0) -> bool:
	a, b = round(flt(a), places), round(flt(b), places)
	if tolerance:
		return round(abs(a - b), places) > tolerance
	return a != b


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
		from business_needed_solutions.bns_branch_accounting.utils import _structural_si_for_internal_pi

		if _structural_si_for_internal_pi(doc):
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
		from business_needed_solutions.bns_branch_accounting.utils import _structural_si_for_internal_pi

		# The supplier's bill number is free text, not a link (same rule as submit).
		name = _structural_si_for_internal_pi(doc)
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


def _is_zero_value_extra_row(row) -> bool:
	"""A non-stock row worth nothing (no amount, no GST): it moves no stock and no money."""
	item = frappe.get_cached_value("Item", row.get("item_code"), ["is_stock_item", "is_fixed_asset"], as_dict=True) \
		if row.get("item_code") else None
	if not item or cint(item.is_stock_item) or cint(item.is_fixed_asset):
		return False
	fields = ("amount", "base_amount", "net_amount", "base_net_amount") + tuple(f[0] for f in ROW_GST if f[0].endswith("_amount"))
	return not any(flt(row.get(f)) for f in fields)


def _target_rows(doc, link):
	"""Rows that must each match one source row, and the extra rows allowed beside them."""
	rows = doc.get("items") or []
	if link == "DN->SI":
		# A zero-value non-stock row (packing, a free note) may be added to an invoice made
		# from a Delivery Note; every other row must come from the DN.
		extra = [r for r in rows if not cstr(r.get("dn_detail")).strip() and _is_zero_value_extra_row(r)]
		return [r for r in rows if r not in extra], extra
	return rows, []


def _moves_stock(doc) -> bool:
	if doc.doctype in (DN, PR):
		return True
	return bool(cint(doc.get("update_stock")))


# --------------------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------------------


def compare_internal_pair(doc, link: str, sources=None, row_sources=None, report=False) -> list[Mismatch]:
	"""Every difference between `doc` and its source(s) on `link`. Empty when identical.

	sources / row_sources (target row name -> source row name) are given when the
	documents are not linked yet (link / convert buttons); otherwise the links are read.
	report=True uses the reports' tax-exclusive rules; the default is the strict rules
	the submit / save checks enforce."""
	row_numbers = REPORT_ROW_NUMBERS if report else ROW_NUMBERS
	row_gst = REPORT_ROW_GST if report else ROW_GST
	header_numbers = REPORT_HEADER_NUMBERS if report else HEADER_NUMBERS
	tax_tolerance = AMOUNT_TOLERANCE if report else 0
	sources = sources if sources is not None else _source_docs(doc, link)
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
	rows, extra_rows = _target_rows(doc, link)
	for row in rows:
		name = (row_sources or {}).get(row.name) if row_sources is not None else _source_row_name(doc, row, link)
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

	gst_fields = [f for f in row_gst if frappe.get_meta(doc.doctype + " Item").has_field(f[0])]
	# Lots are compared once the document is being submitted (or is submitted): a draft
	# receiver gets its bundle copied from the sender only at validate / submit.
	stock = cint(doc.docstatus) == 1 and _moves_stock(doc) and all(_moves_stock(s) for s in sources)
	for row, src in matched:
		for field, label in ROW_TEXT:
			if cstr(row.get(field)).strip() != cstr(src.get(field)).strip():
				add(row.idx, row.item_code, _(label), src.get(field), row.get(field))
		for field, label, places, tolerance in row_numbers + tuple(gst_fields):
			if _differs(row.get(field), src.get(field), places, tolerance):
				add(row.idx, row.item_code, _(label), flt(src.get(field)), flt(row.get(field)))
		if stock:
			for field, expected, found in _lot_differences(row, src):
				add(row.idx, row.item_code, field, expected, found)

	for field, label, places, tolerance in header_numbers:
		expected = sum(flt(s.get(field)) for s in sources)
		if field == "total_qty":
			expected += sum(flt(r.get("qty")) for r in extra_rows)
		if _differs(doc.get(field), expected, places, tolerance):
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
		if _differs(t["amount"], s["amount"], 2, tax_tolerance):
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


def pair_rows_by_item(source, target) -> dict:
	"""Target row name -> source row name for two documents not linked yet: an existing
	row link to this source wins, then the same item, quantity and rate, then the same
	item, in row order. Each source row is used once; a row left unpaired is reported."""
	pool = list(source.get("items") or [])
	names = {r.name for r in pool}
	pairs = {}
	for row in target.get("items") or []:
		linked = cstr(row.get("sales_invoice_item")).strip()
		if linked in names and linked not in pairs.values():
			pairs[row.name] = linked
	pool = [r for r in pool if r.name not in pairs.values()]
	for exact in (True, False):
		for row in target.get("items") or []:
			if row.name in pairs:
				continue
			for src in pool:
				if src.item_code != row.item_code:
					continue
				if exact and (round(flt(src.qty), 6) != round(flt(row.qty), 6)
							  or round(flt(src.rate), 6) != round(flt(row.rate), 6)):
					continue
				pairs[row.name] = src.name
				pool.remove(src)
				break
	return pairs


def si_pi_link_mismatches(si, pi) -> list[Mismatch]:
	"""Differences between a Sales Invoice and a Purchase Invoice about to be linked as an
	internal transfer: the same rules as submit (SI->PI), rows paired by item / qty / rate."""
	return compare_internal_pair(pi, "SI->PI", sources=[si], row_sources=pair_rows_by_item(si, pi))


def mismatch_text(mismatches, limit=10) -> str:
	"""Plain-text list of differences for a message ("" when none)."""
	lines = [m.message() for m in mismatches[:limit]]
	if len(mismatches) > limit:
		lines.append(_("… and {0} more.").format(len(mismatches) - limit))
	return "; ".join(lines)


def as_dicts(mismatches):
	return [asdict(m) | {"message": m.message()} for m in mismatches]


# Public name for the reports.
fmt = _fmt
