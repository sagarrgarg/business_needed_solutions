"""
BNS internal party guard.

When BNS internal flags are enabled, standard ERPNext internal flags are forced
off so both mechanisms do not conflict.
"""

from typing import Optional


def enforce_bns_over_standard_internal_customer(doc, method: Optional[str] = None) -> None:
    """If BNS internal customer is on, keep standard internal customer off."""
    if not getattr(doc, "is_bns_internal_customer", None):
        return
    if doc.is_bns_internal_customer:
        doc.is_internal_customer = 0


def enforce_bns_over_standard_internal_supplier(doc, method: Optional[str] = None) -> None:
    """If BNS internal supplier is on, keep standard internal supplier off."""
    if not getattr(doc, "is_bns_internal_supplier", None):
        return
    if doc.is_bns_internal_supplier:
        doc.is_internal_supplier = 0
