"""
Unit tests for BNS Purchase Document Attachment Validation.

Covers the matrix added by the mode-of-transport + e-Waybill-date + supplier
skip-flag rules. Uses unittest.mock to stub frappe.db calls so the suite runs
without external fixtures or a populated site.
"""

import unittest
from unittest.mock import patch

import frappe

from business_needed_solutions.business_needed_solutions.overrides import attachment_validation as av


class _MockDoc:
    """
    Test stand-in for a Frappe Document. frappe._dict can't be used here
    because the production validator reads doc.items, which collides with
    dict.items() on _dict.
    """

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


def _make_doc(doctype="Purchase Invoice", **overrides):
    base = {
        "doctype": doctype,
        "name": "TEST-" + doctype.replace(" ", "-"),
        "supplier": "Vendor A",
        "posting_date": "2026-05-21",
        "base_grand_total": 100_000.0,
        "is_return": 0,
        "is_bns_internal_supplier": 0,
        "gst_category": "Registered Regular",
        "items": [frappe._dict({"item_code": "ITEM-A"})],
        "bns_supplier_invoice_attachment": "/files/inv.pdf",
        "bns_ewaybill_attachment": None,
        "bns_ewaybill_date": None,
        "bns_mode_of_transport": "",
        "bill_no": "SUP-INV-001",
        "bill_date": "2026-05-20",
    }
    base.update(overrides)
    return _MockDoc(**base)


class _Stubs:
    """
    Reusable stubs for the per-call DB lookups the validator does.
    Adjust the dicts on a per-test basis before each call.
    """

    def __init__(self):
        self.singles = {
            "BNS Settings": {
                "enforce_purchase_document_attachments": 1,
                "purchase_attachment_cutoff_date": None,
            },
            "GST Settings": {
                "enable_e_waybill": 1,
                "e_waybill_threshold": 50_000,
            },
        }
        self.supplier = {
            "Vendor A": {
                "is_bns_internal_supplier": 0,
                "bns_skip_supplier_invoice_details": 0,
            }
        }
        self.item_stock = {"ITEM-A": 1}

    def get_single_value(self, doctype, fieldname, cache=False):
        return self.singles.get(doctype, {}).get(fieldname)

    def get_value(self, doctype, name, fieldname=None, cache=False):
        if doctype == "Supplier":
            row = self.supplier.get(name, {})
            return row.get(fieldname)
        return None

    def get_cached_value(self, doctype, name, fieldname):
        if doctype == "Item" and fieldname == "is_stock_item":
            return self.item_stock.get(name, 0)
        return None


class AttachmentValidationTests(unittest.TestCase):

    def setUp(self):
        self.stubs = _Stubs()
        self._patches = [
            patch("frappe.db.get_single_value", side_effect=self.stubs.get_single_value),
            patch("frappe.db.get_value", side_effect=self.stubs.get_value),
            patch("frappe.get_cached_value", side_effect=self.stubs.get_cached_value),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    # -- bypass paths -------------------------------------------------------

    def test_enforcement_disabled_is_noop(self):
        self.stubs.singles["BNS Settings"]["enforce_purchase_document_attachments"] = 0
        doc = _make_doc(bns_supplier_invoice_attachment=None, bill_no=None)
        av.validate_purchase_attachments(doc)  # no throw

    def test_pre_cutoff_is_noop(self):
        self.stubs.singles["BNS Settings"]["purchase_attachment_cutoff_date"] = "2026-12-31"
        doc = _make_doc(bns_supplier_invoice_attachment=None, bill_no=None)
        av.validate_purchase_attachments(doc)

    def test_return_is_noop(self):
        doc = _make_doc(is_return=1, bill_no=None, bns_supplier_invoice_attachment=None)
        av.validate_purchase_attachments(doc)

    def test_internal_supplier_doc_flag_is_noop(self):
        doc = _make_doc(is_bns_internal_supplier=1, bill_no=None, bns_supplier_invoice_attachment=None)
        av.validate_purchase_attachments(doc)

    def test_internal_supplier_master_flag_is_noop(self):
        self.stubs.supplier["Vendor A"]["is_bns_internal_supplier"] = 1
        doc = _make_doc(bill_no=None, bns_supplier_invoice_attachment=None)
        av.validate_purchase_attachments(doc)

    def test_pi_linked_to_pr_skips_entirely(self):
        doc = _make_doc(
            bill_no=None,
            bns_supplier_invoice_attachment=None,
            items=[frappe._dict({"item_code": "ITEM-A", "purchase_receipt": "PR-1"})],
        )
        av.validate_purchase_attachments(doc)

    # -- supplier invoice no/date ------------------------------------------

    def test_bill_no_required_by_default(self):
        doc = _make_doc(bill_no=None)
        with self.assertRaises(frappe.ValidationError):
            av.validate_purchase_attachments(doc)

    def test_bill_date_required_by_default(self):
        doc = _make_doc(bill_date=None)
        with self.assertRaises(frappe.ValidationError):
            av.validate_purchase_attachments(doc)

    def test_supplier_skip_flag_waives_bill_fields(self):
        self.stubs.supplier["Vendor A"]["bns_skip_supplier_invoice_details"] = 1
        doc = _make_doc(
            bill_no=None,
            bill_date=None,
            bns_mode_of_transport="By Hand",  # disable e-waybill rule
        )
        av.validate_purchase_attachments(doc)

    # -- mode of transport --------------------------------------------------

    def test_by_hand_skips_ewaybill_even_over_threshold(self):
        doc = _make_doc(
            bns_mode_of_transport="By Hand",
            base_grand_total=10_000_000,
        )
        av.validate_purchase_attachments(doc)

    def test_by_lorry_skips_ewaybill_even_over_threshold(self):
        doc = _make_doc(
            bns_mode_of_transport="By Lorry",
            base_grand_total=10_000_000,
        )
        av.validate_purchase_attachments(doc)

    def test_by_ewaybill_with_attach_and_date_passes(self):
        doc = _make_doc(
            bns_mode_of_transport="By e-Waybill",
            bns_ewaybill_attachment="/files/ewb.pdf",
            bns_ewaybill_date="2026-05-21",
        )
        av.validate_purchase_attachments(doc)

    def test_by_ewaybill_missing_attach_throws(self):
        doc = _make_doc(
            bns_mode_of_transport="By e-Waybill",
            bns_ewaybill_attachment=None,
            bns_ewaybill_date="2026-05-21",
        )
        with self.assertRaises(frappe.ValidationError):
            av.validate_purchase_attachments(doc)

    def test_by_ewaybill_missing_date_throws(self):
        doc = _make_doc(
            bns_mode_of_transport="By e-Waybill",
            bns_ewaybill_attachment="/files/ewb.pdf",
            bns_ewaybill_date=None,
        )
        with self.assertRaises(frappe.ValidationError):
            av.validate_purchase_attachments(doc)

    def test_blank_mode_falls_back_to_threshold_rule(self):
        # Over threshold with stock items and registered supplier ⇒ required.
        doc = _make_doc(
            bns_mode_of_transport="",
            bns_ewaybill_attachment=None,
        )
        with self.assertRaises(frappe.ValidationError):
            av.validate_purchase_attachments(doc)

    def test_blank_mode_below_threshold_passes(self):
        doc = _make_doc(
            bns_mode_of_transport="",
            base_grand_total=10_000,  # below 50k threshold
            bns_ewaybill_attachment=None,
        )
        av.validate_purchase_attachments(doc)

    def test_unregistered_supplier_skips_ewaybill(self):
        doc = _make_doc(
            gst_category="Unregistered",
            bns_ewaybill_attachment=None,
        )
        av.validate_purchase_attachments(doc)


if __name__ == "__main__":
    unittest.main()
