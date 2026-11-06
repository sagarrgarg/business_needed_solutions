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
        # Purchase Invoice name -> stored fields (as_dict lookups / is_paid)
        self.pis = {}

    def get_cached_doc(self, doctype, name):
        if doctype == "Supplier":
            return self.suppliers[name]
        raise KeyError(doctype, name)

    def get_value(self, doctype, filters, fieldname=None, **_kwargs):
        if doctype == "Mode of Payment Account" and fieldname == "default_account":
            key = (filters.get("parent"), filters.get("company"))
            return self.mop_accounts.get(key)
        if doctype == "Purchase Invoice" and filters in self.pis:
            row = self.pis[filters]
            if isinstance(fieldname, (list, tuple)):
                return frappe._dict({f: row.get(f) for f in fieldname})
            return row.get(fieldname)
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

    def test_advance_and_write_off_reduce_cash_paid(self):
        # An advance already settles part of the invoice; paying the full total
        # in cash as well would pay the supplier twice.
        pi = _make_pi(total_advance=300.0, write_off_amount=50.0)
        aps.auto_mark_paid(pi)
        self.assertEqual(pi.paid_amount, 650.0)
        self.assertEqual(pi.base_paid_amount, 650.0)

    def test_return_against_unpaid_invoice_is_not_a_cash_refund(self):
        self.stubs.pis["PI-UNPAID"] = {"is_paid": 0}
        pi = _make_pi(is_return=1, return_against="PI-UNPAID", grand_total=-100.0,
                      base_grand_total=-100.0, rounded_total=-100.0, base_rounded_total=-100.0)
        aps.auto_mark_paid(pi)
        self.assertEqual(pi.is_paid, 0)

    def test_return_against_paid_invoice_is_refunded(self):
        self.stubs.pis["PI-PAID"] = {"is_paid": 1}
        pi = _make_pi(is_return=1, return_against="PI-PAID", grand_total=-100.0,
                      base_grand_total=-100.0, rounded_total=-100.0, base_rounded_total=-100.0)
        aps.auto_mark_paid(pi)
        self.assertEqual(pi.is_paid, 1)
        self.assertEqual(pi.paid_amount, -100.0)

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

    def _pi(self, name, supplier="Cash Vendor", **state):
        stored = {
            "is_paid": 0, "mode_of_payment": None, "cash_bank_account": None,
            "paid_amount": 0.0, "rounded_total": 1000.0, "grand_total": 1000.0,
            "base_rounded_total": 1000.0, "base_grand_total": 1000.0,
        }
        stored.update(state)
        self.stubs.pis[name] = stored
        return _MockPI(name=name, supplier=supplier, company="Acme",
                       posting_date="2026-05-01", outstanding_amount=1000.0,
                       grand_total=1000.0, is_return=0)

    def _run(self, pi, linked=(), other=()):
        with patch.object(aps, "_linked_payment_entries", return_value=list(linked)), \
             patch.object(aps, "_other_allocations", return_value=list(other)):
            return aps._process_pi_for_backfill(pi, dry_run=1)

    @staticmethod
    def _pe(name, account, pis):
        return {
            "name": name, "allocated_amount": 1000.0, "payment_type": "Pay",
            "paid_from": account, "paid_to": "Creditors - A", "cash_bank_account": account,
            "mode_of_payment": "Bank", "posting_date": "2026-05-01", "referenced_pis": pis,
        }

    def test_process_pi_dry_run_unpaid_would_update(self):
        row = self._run(self._pi("PI-1"))
        self.assertEqual(row["status"], "would-update")
        self.assertEqual(row["paid_amount"], 1000.0)
        self.assertEqual(row["to_account"], "Cash - A")
        self.assertEqual(row["cancelled"], [])

    def test_process_pi_dry_run_already_paid_is_ok(self):
        pi = self._pi("PI-2", is_paid=1, mode_of_payment="Cash",
                      cash_bank_account="Cash - A", paid_amount=1000.0)
        self.assertEqual(self._run(pi)["status"], "ok")

    def test_process_pi_dry_run_single_pi_pe_plans_cancel(self):
        row = self._run(self._pi("PI-3"), linked=[self._pe("PE-WRONG", "HDFC - A", ["PI-3"])])
        self.assertEqual(row["status"], "would-update")
        self.assertEqual(len(row["cancelled"]), 1)
        self.assertEqual(row["cancelled"][0]["old_pe"], "PE-WRONG")
        self.assertEqual(row["cancelled"][0]["action"], "would cancel")

    def test_process_pi_dry_run_multi_pi_pe_needs_manual(self):
        row = self._run(self._pi("PI-4"), linked=[self._pe("PE-MULTI", "HDFC - A", ["PI-4", "PI-OTHER"])])
        self.assertEqual(row["status"], "needs-manual")
        self.assertEqual(row["pes"], ["PE-MULTI"])

    def test_process_pi_dry_run_other_allocations_need_manual(self):
        # A journal entry or debit note allocated to the PI would stay allocated
        # after it is marked paid, paying it twice.
        row = self._run(self._pi("PI-6"), other=["Journal Entry JV-1"])
        self.assertEqual(row["status"], "needs-manual")
        self.assertEqual(row["vouchers"], ["Journal Entry JV-1"])

    def test_process_pi_dry_run_supplier_misconfigured_skipped(self):
        pi = self._pi("PI-5", supplier="Misconfigured Vendor")
        self.assertEqual(self._run(pi)["status"], "skipped")

    def test_failed_pi_is_rolled_back_alone(self):
        # One PI failing must undo only that PI (its own savepoint), never the
        # PIs processed before it.
        pi = self._pi("PI-7")
        with patch.object(aps, "_process_pi_for_backfill", side_effect=RuntimeError("boom")), \
             patch("frappe.db.savepoint") as savepoint, \
             patch("frappe.db.rollback") as rollback, \
             patch("frappe.log_error"):
            row = aps._process_one_pi(pi, dry_run=0)
        self.assertEqual(row["status"], "error")
        savepoint.assert_called_once()
        self.assertIn("save_point", rollback.call_args.kwargs)

    def test_summarize_counts_by_status(self):
        rows = [
            {"status": "ok"}, {"status": "ok"}, {"status": "paid"},
            {"status": "needs-manual"}, {"status": "ok"},
        ]
        self.assertEqual(aps._summarize(rows),
                         {"ok": 3, "paid": 1, "needs-manual": 1})

    def test_backfill_enqueues_live_run_above_threshold(self):
        # 11 PIs in scope, live run -> must enqueue, must NOT process inline.
        fake_pis = [_MockPI(name=f"PI-{i}", supplier="Cash Vendor",
                            company="Acme", posting_date="2026-05-01",
                            outstanding_amount=100.0, grand_total=100.0,
                            is_return=0) for i in range(11)]
        with patch("frappe.has_permission", return_value=True), \
             patch.object(aps, "_scope_pis_for_backfill", return_value=fake_pis), \
             patch.object(aps, "_run_backfill_inline") as inline_mock, \
             patch("frappe.enqueue") as enqueue_mock:
            result = aps.backfill_auto_paid_supplier(dry_run=0)
        inline_mock.assert_not_called()
        enqueue_mock.assert_called_once()
        self.assertTrue(result["enqueued"])
        self.assertEqual(result["total"], 11)

    def test_backfill_runs_inline_when_live_at_or_below_threshold(self):
        # 10 PIs (== threshold) live: inline path, no enqueue.
        fake_pis = [_MockPI(name=f"PI-{i}", supplier="Cash Vendor",
                            company="Acme", posting_date="2026-05-01",
                            outstanding_amount=0.0, grand_total=100.0,
                            is_return=0) for i in range(10)]
        with patch("frappe.has_permission", return_value=True), \
             patch.object(aps, "_scope_pis_for_backfill", return_value=fake_pis), \
             patch.object(aps, "_run_backfill_inline", return_value=[]) as inline_mock, \
             patch("frappe.enqueue") as enqueue_mock:
            result = aps.backfill_auto_paid_supplier(dry_run=0)
        inline_mock.assert_called_once()
        enqueue_mock.assert_not_called()
        self.assertFalse(result["enqueued"])

    def test_backfill_dry_run_never_enqueues(self):
        # Dry run with 500 PIs: still inline (read-only, safe to be sync).
        fake_pis = [_MockPI(name=f"PI-{i}", supplier="Cash Vendor",
                            company="Acme", posting_date="2026-05-01",
                            outstanding_amount=0.0, grand_total=100.0,
                            is_return=0) for i in range(500)]
        with patch("frappe.has_permission", return_value=True), \
             patch.object(aps, "_scope_pis_for_backfill", return_value=fake_pis), \
             patch.object(aps, "_run_backfill_inline", return_value=[]) as inline_mock, \
             patch("frappe.enqueue") as enqueue_mock:
            result = aps.backfill_auto_paid_supplier(dry_run=1)
        inline_mock.assert_called_once()
        enqueue_mock.assert_not_called()
        self.assertTrue(result["dry_run"])

    def test_backfill_throws_above_hard_max(self):
        # 2001 PIs: above hard cap, throw even in dry run.
        fake_pis = [_MockPI(name=f"PI-{i}", supplier="Cash Vendor",
                            company="Acme", posting_date="2026-05-01",
                            outstanding_amount=0.0, grand_total=100.0,
                            is_return=0) for i in range(2001)]
        with patch("frappe.has_permission", return_value=True), \
             patch.object(aps, "_scope_pis_for_backfill", return_value=fake_pis):
            with self.assertRaises(frappe.ValidationError):
                aps.backfill_auto_paid_supplier(dry_run=1)


if __name__ == "__main__":
    unittest.main()
