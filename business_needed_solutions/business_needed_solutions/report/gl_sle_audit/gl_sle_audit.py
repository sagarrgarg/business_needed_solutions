# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""GL SLE Audit — list submitted docs after cutoff with missing or
imbalanced GL Entry / Stock Ledger Entry.

Delegates the heavy lifting to `business_needed_solutions.gl_sle_audit`
so the audit logic stays testable independent of the report shell.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from frappe import _

from business_needed_solutions.business_needed_solutions import gl_sle_audit as audit_mod


def execute(filters: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    filters = filters or {}

    cutoff = filters.get("cutoff_date")
    doctypes = filters.get("doctypes")
    statuses = filters.get("statuses")
    company = filters.get("company")
    limit = filters.get("limit") or 50000

    rows = audit_mod.audit_gl_sle(
        cutoff_date=cutoff,
        doctypes=doctypes,
        company=company,
        statuses=statuses,
        limit=limit,
    )

    columns = _columns()
    return columns, rows


def _columns() -> List[Dict[str, Any]]:
    return [
        {"label": _("Doctype"),       "fieldname": "doctype",      "fieldtype": "Link",         "options": "DocType", "width": 150},
        {"label": _("Name"),          "fieldname": "name",         "fieldtype": "Dynamic Link", "options": "doctype", "width": 180},
        {"label": _("Posting Date"),  "fieldname": "posting_date", "fieldtype": "Date",         "width": 110},
        {"label": _("Company"),       "fieldname": "company",      "fieldtype": "Link",         "options": "Company", "width": 160},
        {"label": _("Status"),        "fieldname": "status",       "fieldtype": "Data",         "width": 190},
        {"label": _("Expected GL"),   "fieldname": "expected_gl",  "fieldtype": "Check",        "width": 80},
        {"label": _("GL Count"),      "fieldname": "gl_count",     "fieldtype": "Int",          "width": 80},
        {"label": _("GL Debit"),      "fieldname": "gl_dr",        "fieldtype": "Currency",     "width": 120},
        {"label": _("GL Credit"),     "fieldname": "gl_cr",        "fieldtype": "Currency",     "width": 120},
        {"label": _("GL Imbalance"),  "fieldname": "gl_imbalance", "fieldtype": "Currency",     "width": 120},
        {"label": _("Expected SLE"),  "fieldname": "expected_sle", "fieldtype": "Check",        "width": 80},
        {"label": _("SLE Count"),     "fieldname": "sle_count",    "fieldtype": "Int",          "width": 80},
        {"label": _("Update Stock"),  "fieldname": "update_stock", "fieldtype": "Check",        "width": 80},
        {"label": _("Perpetual"),     "fieldname": "perpetual",    "fieldtype": "Check",        "width": 80},
        {"label": _("Stock Items"),   "fieldname": "stock_item_count", "fieldtype": "Int",      "width": 80},
        {"label": _("Asset Items"),   "fieldname": "asset_item_count", "fieldtype": "Int",      "width": 80},
        {"label": _("Total Items"),   "fieldname": "total_item_count", "fieldtype": "Int",      "width": 80},
    ]
