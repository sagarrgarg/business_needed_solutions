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


ISSUE_POS_MISMATCH = "POS Mismatch"
ISSUE_TAX_TYPE_MISMATCH = "Tax Type Mismatch"
ISSUE_ITC_EXPENSED_POS = "ITC Expensed PoS"
ISSUE_ITC_EXPENSED_175 = "ITC Expensed 17(5)"

ALL_ISSUE_TYPES = [
    ISSUE_POS_MISMATCH,
    ISSUE_TAX_TYPE_MISMATCH,
    ISSUE_ITC_EXPENSED_POS,
    ISSUE_ITC_EXPENSED_175,
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
            "label": _("Invoice"),
            "fieldname": "name",
            "fieldtype": "Link",
            "options": "Purchase Invoice",
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

    results.sort(key=lambda r: (r["posting_date"], r["name"]), reverse=True)
    return results


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
