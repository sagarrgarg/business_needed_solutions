"""
BNS Internal Customer/Supplier vs standard internal.

When BNS internal is turned on, standard ERPNext internal customer/supplier
is forced off so the two mechanisms do not conflict.
"""

import frappe
from typing import Optional


def enforce_bns_over_standard_internal_customer(doc, method: Optional[str] = None) -> None:
    """
    When is_bns_internal_customer is 1, set is_internal_customer to 0 and ensure
    it stays off. BNS internal and standard internal are mutually exclusive.
    """
    if not getattr(doc, "is_bns_internal_customer", None):
        return
    if doc.is_bns_internal_customer:
        doc.is_internal_customer = 0


def enforce_bns_over_standard_internal_supplier(doc, method: Optional[str] = None) -> None:
    """
    When is_bns_internal_supplier is 1, set is_internal_supplier to 0 and ensure
    it stays off. BNS internal and standard internal are mutually exclusive.
    """
    if not getattr(doc, "is_bns_internal_supplier", None):
        return
    if doc.is_bns_internal_supplier:
        doc.is_internal_supplier = 0
