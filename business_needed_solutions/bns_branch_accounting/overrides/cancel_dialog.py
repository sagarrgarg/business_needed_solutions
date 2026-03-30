"""
BNS Branch Accounting - cancel dialog overrides.

This module customizes Frappe's "Cancel All Documents" lookup for BNS internal
flows so child-side cancellation (PR/PI) does not prompt to cancel parent
documents (DN/SI).
"""

import json
from typing import Iterable, List, Optional

import frappe
from frappe.desk.form.linked_with import get_submitted_linked_docs as frappe_get_submitted_linked_docs


def _as_list(value) -> List[str]:
    """Normalize ignore_doctypes_on_cancel_all payload to list."""
    if not value:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    if isinstance(value, Iterable):
        return [v for v in value if isinstance(v, str)]
    return []


@frappe.whitelist()
def get_submitted_linked_docs(doctype: str, name: str, ignore_doctypes_on_cancel_all=None):
    """
    Filter cancel-all popup for BNS one-way cancellation policy.

    Policy:
    - Cancelling Purchase Receipt should not ask to cancel Delivery Note/Sales Invoice.
    - Cancelling Purchase Invoice should not ask to cancel Sales Invoice.
    """
    ignore_list = _as_list(ignore_doctypes_on_cancel_all)

    if doctype == "Purchase Receipt":
        for dt in ("Delivery Note", "Sales Invoice"):
            if dt not in ignore_list:
                ignore_list.append(dt)
    elif doctype == "Purchase Invoice":
        if "Sales Invoice" not in ignore_list:
            ignore_list.append("Sales Invoice")

    return frappe_get_submitted_linked_docs(
        doctype=doctype,
        name=name,
        ignore_doctypes_on_cancel_all=ignore_list,
    )
