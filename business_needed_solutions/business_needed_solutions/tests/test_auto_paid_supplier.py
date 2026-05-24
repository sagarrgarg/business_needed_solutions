"""
Unit tests for BNS Auto-Paid Supplier hook.

Stubs frappe.get_cached_doc and frappe.db.get_value so the suite runs
without a real Supplier or Mode of Payment record.
"""

import unittest
from unittest.mock import patch

import frappe

from business_needed_solutions.business_needed_solutions.overrides import (
    auto_paid_supplier as aps,
)


class _MockDoc:
    """Stand-in Document for the validate hook.

    Mirrors the same pattern used in test_attachment_validation.py so the
    PI .get(field) accessor and attribute assignment both work.
    """

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


def _make_pi(**overrides):
    base = {
        "doctype": "Purchase Invoice",
        "name": "TEST-PI",
        "supplier": "Cash Vendor",
        "company": "Acme",
        "is_paid": 0,
        "is_return": 0,
        "is_bns_internal_supplier": 0,
        "mode_of_payment": None,
        "cash_bank_account": None,
        "paid_amount": 0.0,
        "base_paid_amount": 0.0,
        "grand_total": 1000.0,
        "base_grand_total": 1000.0,
        "rounded_total": 1000.0,
        "base_rounded_total": 1000.0,
    }
    base.update(overrides)
    return _MockDoc(**base)


class _Stubs:
    """Reusable stubs for the DB calls the hook makes."""

    def __init__(self):
        self.suppliers = {
            "Cash Vendor": _MockDoc(
                name="Cash Vendor",
                bns_auto_paid_supplier=1,
                bns_auto_paid_mode_of_payment="Cash",
            ),
            "Bank Vendor": _MockDoc(
                name="Bank Vendor",
                bns_auto_paid_supplier=0,
                bns_auto_paid_mode_of_payment=None,
            ),
            "Misconfigured Vendor": _MockDoc(
                name="Misconfigured Vendor",
                bns_auto_paid_supplier=1,
                bns_auto_paid_mode_of_payment=None,
            ),
            "Wrong Company Vendor": _MockDoc(
                name="Wrong Company Vendor",
                bns_auto_paid_supplier=1,
                bns_auto_paid_mode_of_payment="MOP Without Acme",
            ),
        }
        # (parent, company) -> default_account
        self.mop_accounts = {
            ("Cash", "Acme"): "Cash - A",
        }

    def get_cached_doc(self, doctype, name):
        if doctype == "Supplier":
            return self.suppliers[name]
        raise KeyError(doctype, name)

    def get_value(self, doctype, filters, fieldname=None, **_kwargs):
        if doctype == "Mode of Payment Account" and fieldname == "default_account":
            key = (filters.get("parent"), filters.get("company"))
            return self.mop_accounts.get(key)
        return None


class AutoPaidSupplierTests(unittest.TestCase):

    def setUp(self):
        self.stubs = _Stubs()
        self._patches = [
            patch("frappe.get_cached_doc", side_effect=self.stubs.get_cached_doc),
            patch("frappe.db.get_value", side_effect=self.stubs.get_value),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    # -- happy path ---------------------------------------------------------

    def test_flag_on_sets_is_paid_block(self):
        pi = _make_pi()
        aps.auto_mark_paid(pi)
        self.assertEqual(pi.is_paid, 1)
        self.assertEqual(pi.mode_of_payment, "Cash")
        self.assertEqual(pi.cash_bank_account, "Cash - A")
        self.assertEqual(pi.paid_amount, 1000.0)
        self.assertEqual(pi.base_paid_amount, 1000.0)

    def test_flag_on_overrides_manual_is_paid_and_wrong_mop(self):
        # User pre-ticked Is Paid with a different MOP/account; supplier
        # master must override.
        pi = _make_pi(
            is_paid=1,
            mode_of_payment="Bank Transfer",
            cash_bank_account="HDFC - A",
            paid_amount=500.0,
            base_paid_amount=500.0,
        )
        aps.auto_mark_paid(pi)
        self.assertEqual(pi.is_paid, 1)
        self.assertEqual(pi.mode_of_payment, "Cash")
        self.assertEqual(pi.cash_bank_account, "Cash - A")
        self.assertEqual(pi.paid_amount, 1000.0)
        self.assertEqual(pi.base_paid_amount, 1000.0)

    def test_flag_on_return_pi_negative_paid_amount(self):
        # Return PIs carry negative totals; the same hook must propagate
        # the negative paid_amount (refund leg).
        pi = _make_pi(
            is_return=1,
            grand_total=-1000.0,
            base_grand_total=-1000.0,
            rounded_total=-1000.0,
            base_rounded_total=-1000.0,
        )
        aps.auto_mark_paid(pi)
        self.assertEqual(pi.is_paid, 1)
        self.assertEqual(pi.paid_amount, -1000.0)
        self.assertEqual(pi.base_paid_amount, -1000.0)

    def test_grand_total_fallback_when_rounded_total_zero(self):
        # Some companies disable rounding -> rounded_total = 0; fall back
        # to grand_total.
        pi = _make_pi(rounded_total=0.0, base_rounded_total=0.0)
        aps.auto_mark_paid(pi)
        self.assertEqual(pi.paid_amount, 1000.0)
        self.assertEqual(pi.base_paid_amount, 1000.0)

    # -- bypass paths -------------------------------------------------------

    def test_flag_off_is_noop(self):
        pi = _make_pi(supplier="Bank Vendor")
        aps.auto_mark_paid(pi)
        self.assertEqual(pi.is_paid, 0)
        self.assertIsNone(pi.mode_of_payment)
        self.assertIsNone(pi.cash_bank_account)

    def test_internal_branch_supplier_is_noop(self):
        # Even if flagged at supplier master, internal branch flow wins.
        pi = _make_pi(is_bns_internal_supplier=1)
        aps.auto_mark_paid(pi)
        self.assertEqual(pi.is_paid, 0)

    def test_no_supplier_is_noop(self):
        pi = _make_pi(supplier=None)
        aps.auto_mark_paid(pi)
        self.assertEqual(pi.is_paid, 0)

    # -- hard validation ----------------------------------------------------

    def test_flag_on_without_mop_throws(self):
        pi = _make_pi(supplier="Misconfigured Vendor")
        with self.assertRaises(frappe.ValidationError):
            aps.auto_mark_paid(pi)

    def test_flag_on_without_company_account_throws(self):
        pi = _make_pi(supplier="Wrong Company Vendor")
        with self.assertRaises(frappe.ValidationError):
            aps.auto_mark_paid(pi)


# ===========================================================================
# Backfill helpers
# ===========================================================================


class _MockPI:
    """Lightweight stand-in for the dict-like rows returned by get_all."""

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def __getitem__(self, key):
        return self.__dict__[key]

    def get(self, key, default=None):
        return self.__dict__.get(key, default)

    @property
    def name(self):
        return self.__dict__["name"]


class BackfillHelpersTests(unittest.TestCase):
    """Covers what's mockable: account resolution, dry-run flow for a PI.

    The live cancel + recreate path needs real PE / Account / Account-Currency
    records, which is integration-level — exercised manually via the BNS
    Settings button.
    """

    def setUp(self):
        self.stubs = _Stubs()
        self._patches = [
            patch("frappe.get_cached_doc", side_effect=self.stubs.get_cached_doc),
            patch("frappe.db.get_value", side_effect=self.stubs.get_value),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_resolve_mop_account_hit(self):
        self.assertEqual(aps._resolve_mop_account("Cash", "Acme"), "Cash - A")

    def test_resolve_mop_account_miss(self):
        self.assertIsNone(aps._resolve_mop_account("Cash", "Unknown Co"))
        self.assertIsNone(aps._resolve_mop_account(None, "Acme"))
        self.assertIsNone(aps._resolve_mop_account("Cash", None))

    def test_process_pi_dry_run_no_linked_pes_needs_pay(self):
        pi = _MockPI(name="PI-1", supplier="Cash Vendor", company="Acme",
                     posting_date="2026-05-01", outstanding_amount=1000.0,
                     grand_total=1000.0, is_return=0)
        with patch.object(aps, "_linked_payment_entries", return_value=[]):
            row = aps._process_pi_for_backfill(pi, dry_run=1)
        self.assertEqual(row["status"], "would-pay-residual")
        self.assertEqual(row["amount"], 1000.0)
        self.assertEqual(row["to_account"], "Cash - A")
        self.assertEqual(row["reclassified"], [])

    def test_process_pi_dry_run_correct_account_pe_already_paid(self):
        pi = _MockPI(name="PI-2", supplier="Cash Vendor", company="Acme",
                     posting_date="2026-05-01", outstanding_amount=0.0,
                     grand_total=1000.0, is_return=0)
        linked = [{
            "name": "PE-OK", "allocated_amount": 1000.0,
            "payment_type": "Pay", "paid_from": "Cash - A",
            "paid_to": "Creditors - A", "cash_bank_account": "Cash - A",
            "mode_of_payment": "Cash", "posting_date": "2026-05-01",
            "referenced_pis": ["PI-2"],
        }]
        with patch.object(aps, "_linked_payment_entries", return_value=linked):
            row = aps._process_pi_for_backfill(pi, dry_run=1)
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["reclassified"], [])
        self.assertEqual(row["residual"], 0)

    def test_process_pi_dry_run_wrong_account_pe(self):
        pi = _MockPI(name="PI-3", supplier="Cash Vendor", company="Acme",
                     posting_date="2026-05-01", outstanding_amount=0.0,
                     grand_total=1000.0, is_return=0)
        linked = [{
            "name": "PE-WRONG", "allocated_amount": 1000.0,
            "payment_type": "Pay", "paid_from": "HDFC - A",
            "paid_to": "Creditors - A", "cash_bank_account": "HDFC - A",
            "mode_of_payment": "Bank", "posting_date": "2026-05-01",
            "referenced_pis": ["PI-3"],
        }]
        with patch.object(aps, "_linked_payment_entries", return_value=linked):
            row = aps._process_pi_for_backfill(pi, dry_run=1)
        # Outstanding is 0 (PE-WRONG paid it), so phase 3 says ok; phase 2
        # reports the reclassification plan.
        self.assertEqual(row["status"], "ok")
        self.assertEqual(len(row["reclassified"]), 1)
        plan = row["reclassified"][0]
        self.assertEqual(plan["old_pe"], "PE-WRONG")
        self.assertEqual(plan["from_account"], "HDFC - A")
        self.assertEqual(plan["to_account"], "Cash - A")
        self.assertEqual(plan["action"], "would cancel + recreate")

    def test_process_pi_dry_run_multi_pi_pe_needs_manual(self):
        pi = _MockPI(name="PI-4", supplier="Cash Vendor", company="Acme",
                     posting_date="2026-05-01", outstanding_amount=0.0,
                     grand_total=1000.0, is_return=0)
        linked = [{
            "name": "PE-MULTI", "allocated_amount": 1000.0,
            "payment_type": "Pay", "paid_from": "HDFC - A",
            "paid_to": "Creditors - A", "cash_bank_account": "HDFC - A",
            "mode_of_payment": "Bank", "posting_date": "2026-05-01",
            "referenced_pis": ["PI-4", "PI-OTHER"],
        }]
        with patch.object(aps, "_linked_payment_entries", return_value=linked):
            row = aps._process_pi_for_backfill(pi, dry_run=1)
        self.assertEqual(row["status"], "needs-manual")
        self.assertEqual(row["pes"], ["PE-MULTI"])

    def test_process_pi_dry_run_supplier_misconfigured_skipped(self):
        pi = _MockPI(name="PI-5", supplier="Misconfigured Vendor", company="Acme",
                     posting_date="2026-05-01", outstanding_amount=500.0,
                     grand_total=500.0, is_return=0)
        with patch.object(aps, "_linked_payment_entries", return_value=[]):
            row = aps._process_pi_for_backfill(pi, dry_run=1)
        self.assertEqual(row["status"], "skipped")

    def test_summarize_counts_by_status(self):
        rows = [
            {"status": "ok"}, {"status": "ok"}, {"status": "paid"},
            {"status": "needs-manual"}, {"status": "ok"},
        ]
        self.assertEqual(aps._summarize(rows),
                         {"ok": 3, "paid": 1, "needs-manual": 1})


if __name__ == "__main__":
    unittest.main()
