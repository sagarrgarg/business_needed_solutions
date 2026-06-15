"""
GST ITC Health Check Report

Catches Purchase Invoice GST issues:
1. POS Mismatch — same-state supplier+company but POS points elsewhere
2. Tax Type Mismatch — IGST used for intra-state or CGST+SGST for inter-state
3. ITC Expensed (PoS) — ITC restricted due to Place of Supply rules
4. ITC Expensed (17(5)) — ITC ineligible under Section 17(5)
"""

import frappe
from frappe import _
from frappe.utils import flt


ISSUE_POS_MISMATCH = "POS Mismatch"
ISSUE_TAX_TYPE_MISMATCH = "Tax Type Mismatch"
ISSUE_ITC_EXPENSED_POS = "ITC Expensed PoS"
ISSUE_ITC_EXPENSED_175 = "ITC Expensed 17(5)"
# Ground-truth: GST actually posted to the company's GST Expense account
# (India Compliance ineligible-ITC capitalization). Catches Purchase
# Receipts and Purchase Invoices regardless of whether ineligibility_reason
# was persisted — the only reliable signal that ITC was made ineligible.
ISSUE_ITC_EXPENSED_BOOKED = "ITC Expensed (Booked)"

ALL_ISSUE_TYPES = [
    ISSUE_POS_MISMATCH,
    ISSUE_TAX_TYPE_MISMATCH,
    ISSUE_ITC_EXPENSED_POS,
    ISSUE_ITC_EXPENSED_175,
    ISSUE_ITC_EXPENSED_BOOKED,
]


def execute(filters=None):
    filters = filters or {}
    validate_filters(filters)
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def validate_filters(filters):
    if not filters.get("company"):
        frappe.throw(_("Company is mandatory"))
    if not filters.get("from_date") or not filters.get("to_date"):
        frappe.throw(_("From Date and To Date are mandatory"))
    if filters.get("from_date") > filters.get("to_date"):
        frappe.throw(_("From Date cannot be after To Date"))


def get_columns():
    return [
        {
            "label": _("Document Type"),
            "fieldname": "document_type",
            "fieldtype": "Data",
            "width": 120,
        },
        {
            "label": _("Document"),
            "fieldname": "name",
            "fieldtype": "Dynamic Link",
            "options": "document_type",
            "width": 160,
        },
        {
            "label": _("Posting Date"),
            "fieldname": "posting_date",
            "fieldtype": "Date",
            "width": 100,
        },
        {
            "label": _("Supplier"),
            "fieldname": "supplier",
            "fieldtype": "Link",
            "options": "Supplier",
            "width": 140,
        },
        {
            "label": _("Supplier GSTIN"),
            "fieldname": "supplier_gstin",
            "fieldtype": "Data",
            "width": 150,
        },
        {
            "label": _("Company GSTIN"),
            "fieldname": "company_gstin",
            "fieldtype": "Data",
            "width": 150,
        },
        {
            "label": _("Place of Supply"),
            "fieldname": "place_of_supply",
            "fieldtype": "Data",
            "width": 130,
        },
        {
            "label": _("Tax Template"),
            "fieldname": "taxes_and_charges",
            "fieldtype": "Data",
            "width": 160,
        },
        {
            "label": _("Issue Type"),
            "fieldname": "issue_type",
            "fieldtype": "Data",
            "width": 160,
        },
        {
            "label": _("Tax Amount"),
            "fieldname": "tax_amount",
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "label": _("Ineligibility Reason"),
            "fieldname": "ineligibility_reason",
            "fieldtype": "Data",
            "width": 220,
        },
    ]


def get_data(filters):
    issue_filter = filters.get("issue_type") or ALL_ISSUE_TYPES
    if isinstance(issue_filter, str):
        issue_filter = [i.strip() for i in issue_filter.split(",") if i.strip()]

    invoices = fetch_invoices(filters)
    if not invoices:
        return []

    invoice_names = [inv["name"] for inv in invoices]
    tax_rows = fetch_tax_rows(invoice_names)

    taxes_by_invoice = {}
    for row in tax_rows:
        taxes_by_invoice.setdefault(row["parent"], []).append(row)

    results = []
    for inv in invoices:
        results.extend(
            classify_invoice(inv, taxes_by_invoice.get(inv["name"], []), issue_filter)
        )

    # Ground-truth pass: any PR/PI that actually booked GST to the company's
    # GST Expense account. This is the only check that surfaces Purchase
    # Receipts (where perpetual-inventory ineligible-ITC capitalization
    # happens) and catches PoS-rule cases where ineligibility_reason was
    # never persisted on the document.
    if ISSUE_ITC_EXPENSED_BOOKED in issue_filter:
        results.extend(fetch_gst_expensed_docs(filters))

    results.sort(key=lambda r: (r["posting_date"] or "", r["name"]), reverse=True)
    return results


def fetch_gst_expensed_docs(filters):
    company = filters["company"]
    gst_expense_account = frappe.get_cached_value(
        "Company", company, "default_gst_expense_account"
    )
    if not gst_expense_account:
        return []

    conditions = [
        "gle.account = %(acc)s",
        "gle.company = %(company)s",
        "gle.is_cancelled = 0",
        "gle.voucher_type IN ('Purchase Receipt', 'Purchase Invoice')",
        "gle.posting_date BETWEEN %(from_date)s AND %(to_date)s",
    ]
    params = {
        "acc": gst_expense_account,
        "company": company,
        "from_date": filters["from_date"],
        "to_date": filters["to_date"],
    }

    # net credit = GST expensed/capitalized (ITC made ineligible) and not yet
    # reversed on that document. A doc whose debit (reversal) and credit
    # (capitalization) net to zero is already cleared and is skipped.
    rows = frappe.db.sql(
        """
        SELECT gle.voucher_type, gle.voucher_no,
               SUM(gle.credit) - SUM(gle.debit) AS net_expensed
        FROM `tabGL Entry` gle
        WHERE {conditions}
        GROUP BY gle.voucher_type, gle.voucher_no
        HAVING ABS(SUM(gle.credit) - SUM(gle.debit)) > 0.01
        """.format(conditions=" AND ".join(conditions)),
        params,
        as_dict=True,
    )
    if not rows:
        return []

    out = []
    # GST fields (supplier_gstin / company_gstin / place_of_supply /
    # ineligibility_reason) are India-Compliance custom fields and may be
    # absent on Purchase Receipt in some installs — select only what exists.
    field_cache = {}

    def _fields_for(dt):
        if dt not in field_cache:
            # use actual DB columns (not meta.has_field) — IC custom fields can
            # be defined in meta but missing as columns on some installs.
            cols = set(frappe.db.get_table_columns(dt))
            field_cache[dt] = [
                f for f in (
                    "posting_date", "supplier", "supplier_gstin", "company_gstin",
                    "place_of_supply", "taxes_and_charges", "ineligibility_reason",
                ) if f in cols
            ]
        return field_cache[dt]

    for r in rows:
        dt, dn = r["voucher_type"], r["voucher_no"]
        meta = frappe.db.get_value(dt, dn, _fields_for(dt), as_dict=True) or {}
        out.append({
            "document_type": dt,
            "name": dn,
            "posting_date": meta.get("posting_date"),
            "supplier": meta.get("supplier") or "",
            "supplier_gstin": meta.get("supplier_gstin") or "",
            "company_gstin": meta.get("company_gstin") or "",
            "place_of_supply": meta.get("place_of_supply") or "",
            "taxes_and_charges": meta.get("taxes_and_charges") or "",
            "issue_type": ISSUE_ITC_EXPENSED_BOOKED,
            "tax_amount": flt(r.get("net_expensed")),
            "ineligibility_reason": meta.get("ineligibility_reason")
                or _("GST booked to {0} (ITC treated ineligible)").format(gst_expense_account),
        })
    return out


def fetch_invoices(filters):
    conditions = [
        "pi.docstatus = 1",
        "pi.company = %(company)s",
        "pi.posting_date BETWEEN %(from_date)s AND %(to_date)s",
    ]
    params = {
        "company": filters["company"],
        "from_date": filters["from_date"],
        "to_date": filters["to_date"],
    }

    if filters.get("supplier"):
        conditions.append("pi.supplier = %(supplier)s")
        params["supplier"] = filters["supplier"]

    return frappe.db.sql(
        """
        SELECT
            pi.name, pi.posting_date, pi.supplier, pi.supplier_gstin,
            pi.company_gstin, pi.place_of_supply, pi.taxes_and_charges,
            pi.ineligibility_reason
        FROM `tabPurchase Invoice` pi
        WHERE {conditions}
        ORDER BY pi.posting_date DESC, pi.name DESC
        """.format(conditions=" AND ".join(conditions)),
        params,
        as_dict=True,
    )


def fetch_tax_rows(invoice_names):
    if not invoice_names:
        return []

    return frappe.db.sql(
        """
        SELECT ptc.parent, ptc.gst_tax_type, ptc.tax_amount
        FROM `tabPurchase Taxes and Charges` ptc
        WHERE ptc.parent IN %(names)s
            AND ptc.parenttype = 'Purchase Invoice'
            AND ptc.gst_tax_type IN ('igst', 'cgst', 'sgst')
            AND ptc.tax_amount != 0
        """,
        {"names": invoice_names},
        as_dict=True,
    )


def classify_invoice(inv, tax_rows, issue_filter):
    rows = []

    company_state = (inv.get("company_gstin") or "")[:2]
    supplier_state = (inv.get("supplier_gstin") or "")[:2]
    pos_state = (inv.get("place_of_supply") or "")[:2]

    igst_amount = sum(t["tax_amount"] for t in tax_rows if t["gst_tax_type"] == "igst")
    cgst_sgst_amount = sum(
        t["tax_amount"] for t in tax_rows if t["gst_tax_type"] in ("cgst", "sgst")
    )
    total_gst = igst_amount + cgst_sgst_amount

    # 1. POS Mismatch — same state parties, wrong POS
    if ISSUE_POS_MISMATCH in issue_filter:
        if (
            company_state and supplier_state and pos_state
            and supplier_state == company_state
            and pos_state != company_state
        ):
            rows.append(_row(inv, ISSUE_POS_MISMATCH, total_gst))

    # 2. Tax Type vs POS Mismatch
    # For purchases, inter/intra-state is determined by supplier state vs company state.
    # IGST is correct when supplier and company are in different states.
    # CGST+SGST is correct when supplier and company are in the same state.
    if ISSUE_TAX_TYPE_MISMATCH in issue_filter and tax_rows and supplier_state and company_state:
        is_intra_state = supplier_state == company_state
        if is_intra_state and igst_amount:
            # Same-state parties but IGST used — should be CGST+SGST
            rows.append(_row(inv, ISSUE_TAX_TYPE_MISMATCH, igst_amount))
        elif not is_intra_state and cgst_sgst_amount and not igst_amount:
            # Inter-state parties but only CGST+SGST used — should be IGST
            rows.append(_row(inv, ISSUE_TAX_TYPE_MISMATCH, cgst_sgst_amount))

    # 3. ITC Expensed — PoS rules
    if ISSUE_ITC_EXPENSED_POS in issue_filter:
        if inv.get("ineligibility_reason") == "ITC restricted due to PoS rules":
            rows.append(_row(inv, ISSUE_ITC_EXPENSED_POS, total_gst))

    # 4. ITC Expensed — Section 17(5)
    if ISSUE_ITC_EXPENSED_175 in issue_filter:
        if inv.get("ineligibility_reason") == "Ineligible As Per Section 17(5)":
            rows.append(_row(inv, ISSUE_ITC_EXPENSED_175, total_gst))

    return rows


def _row(inv, issue_type, tax_amount):
    return {
        "document_type": "Purchase Invoice",
        "name": inv["name"],
        "posting_date": inv["posting_date"],
        "supplier": inv["supplier"],
        "supplier_gstin": inv.get("supplier_gstin") or "",
        "company_gstin": inv.get("company_gstin") or "",
        "place_of_supply": inv.get("place_of_supply") or "",
        "taxes_and_charges": inv.get("taxes_and_charges") or "",
        "issue_type": issue_type,
        "tax_amount": tax_amount or 0,
        "ineligibility_reason": inv.get("ineligibility_reason") or "",
    }
