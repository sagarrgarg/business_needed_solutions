# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
Branch-accounting fixes of 2026-11-16, one rule per case (in-memory documents, lookups patched):

- an internal PI for a Sales Invoice from before the cutoff (named in the bill number, or
  through an older receipt) keeps the old rules; after the cutoff the bill number is no link;
- one Sales Invoice is received on one PI only;
- SI -> PI mapping does not copy ERPNext's inter_company_invoice_reference;
- a receipt made from a DN-made Sales Invoice takes the DN's cost;
- an SI made from a DN may add a non-stock row of zero value, nothing else;
- linking / converting an SI and a PI uses the submit rules and names every difference;
- receipts: GSTIN scope from supplier_gstin; no linkage or parity rules before the cutoff;
- older v15 builds price each batch at its own rate.

    bench --site <site> run-tests --module \
        business_needed_solutions.bns_branch_accounting.test_branch_accounting_fixes
"""

import unittest
from unittest.mock import patch

import frappe

from business_needed_solutions.bns_branch_accounting import internal_parity as ip
from business_needed_solutions.bns_branch_accounting import utils
from business_needed_solutions.bns_branch_accounting.test_internal_parity import _doc, _igst

AFTER, BEFORE, CUTOFF = "2026-10-01", "2020-01-01", "2026-04-01"


def _pi(**header):
	doc = frappe.new_doc("Purchase Invoice")
	doc.update({"supplier": "Branch B", "company_gstin": "27AAAAA0000A1Z5", "supplier_gstin": "24AAAAA0000A1Z5",
				"posting_date": AFTER, "docstatus": 1, **header})
	doc.append("items", {"item_code": "P799", "qty": 1, "rate": 10})
	return doc


class _Cutoff(unittest.TestCase):
	def setUp(self):
		self.patches = [
			patch.object(utils, "is_bns_internal_supplier", return_value=True),
			patch.object(utils, "is_after_internal_transfer_cutoff", side_effect=lambda d: bool(d) and str(d) >= CUTOFF),
		]
		for p in self.patches:
			p.start()

	def tearDown(self):
		for p in self.patches:
			p.stop()


class TestPreCutoffSource(_Cutoff):
	def test_bill_number_naming_a_pre_cutoff_sales_invoice_keeps_the_old_rules(self):
		with patch.object(utils, "_structural_si_for_internal_pi", return_value=None), \
				patch.object(utils, "_pre_cutoff_source_of_internal_pi", return_value=("SINV-OLD", BEFORE)):
			source = utils.internal_purchase_invoice_source(_pi(bill_no="SINV-OLD"))
		self.assertFalse(source.applies)
		self.assertTrue(source.legacy)
		self.assertIsNone(source.problem)
		self.assertEqual(source.si, "SINV-OLD")

	def test_bill_number_naming_a_post_cutoff_sales_invoice_is_no_link(self):
		with patch.object(utils, "_structural_si_for_internal_pi", return_value=None), \
				patch.object(utils, "_pre_cutoff_source_of_internal_pi", return_value=("SINV-NEW", AFTER)):
			source = utils.internal_purchase_invoice_source(_pi(bill_no="SINV-NEW"))
		self.assertTrue(source.applies)
		self.assertIn("entered directly cannot be submitted", source.problem)
		self.assertIn("recharges", source.problem)

	def test_source_reports_without_throwing_and_submit_throws(self):
		with patch.object(utils, "_structural_si_for_internal_pi", return_value=None), \
				patch.object(utils, "_pre_cutoff_source_of_internal_pi", return_value=(None, None)):
			self.assertTrue(utils.internal_purchase_invoice_source(_pi()).problem)
			with self.assertRaises(frappe.ValidationError):
				utils.assert_internal_purchase_invoice_has_source(_pi())

	def test_older_receipt_dates_the_pi(self):
		pi = _pi()
		pi.items[0].purchase_receipt = "PR-OLD"
		pr = frappe._dict(bns_inter_company_reference="", supplier_delivery_note="", posting_date=BEFORE)
		with patch.object(utils.frappe.db, "get_value", return_value=pr):
			self.assertEqual(utils._pre_cutoff_source_of_internal_pi(pi), (None, BEFORE))

	def test_bill_number_lookup(self):
		old, typed = _pi(bill_no="SINV-OLD"), _pi(bill_no="ACME/77")
		with patch.object(utils, "_is_internal_transfer_sales_invoice", side_effect=lambda n: n == "SINV-OLD"), \
				patch.object(utils.frappe.db, "get_value", return_value=BEFORE):
			self.assertEqual(utils._pre_cutoff_source_of_internal_pi(old), ("SINV-OLD", BEFORE))
			self.assertEqual(utils._pre_cutoff_source_of_internal_pi(typed), (None, None))


class TestReceivedOnce(unittest.TestCase):
	def test_second_pi_on_one_sales_invoice_is_refused(self):
		pi = _pi(name="PINV-0002")
		with patch.object(utils.frappe.db, "get_value", return_value="PINV-0001"):
			with self.assertRaises(frappe.ValidationError) as ctx:
				utils._assert_si_not_received_twice(pi, "SINV-0001")
		self.assertIn("already received", str(ctx.exception))

	def test_first_pi_passes(self):
		pi = _pi()
		with patch.object(utils.frappe.db, "get_value", return_value=None):
			utils._assert_si_not_received_twice(pi, "SINV-0001")


class TestSiToPiMapping(unittest.TestCase):
	def test_standard_inter_company_link_is_not_copied(self):
		self.assertIn("inter_company_invoice_reference", utils._get_sales_invoice_mapping()["Sales Invoice"]["field_no_map"])


class TestReceiptCostFromDeliveryNote(unittest.TestCase):
	def _values(self, doctype, name, fields=None, as_dict=False, **kw):
		rows = {
			("Sales Invoice Item", "SIR-1"): frappe._dict(incoming_rate=0, dn_detail="DNR-1"),
			("Delivery Note Item", "DNR-1"): frappe._dict(parent="DN-1", item_code="P799", incoming_rate=self.dn_rate),
		}
		return rows.get((doctype, name))

	def test_sales_invoice_made_from_a_dn_takes_the_dn_row_cost(self):
		self.dn_rate = 400
		with patch.object(utils.frappe.db, "get_value", side_effect=self._values):
			self.assertEqual(utils._get_si_item_transfer_rate(frappe._dict(name="SIR-1", incoming_rate=0)), 400)

	def test_dn_row_without_a_rate_reads_its_stock_ledger(self):
		self.dn_rate = 0
		with patch.object(utils.frappe.db, "get_value", side_effect=self._values), \
				patch.object(utils, "_get_rate_from_dn_stock_ledger", return_value=410) as sle:
			self.assertEqual(utils._get_si_item_transfer_rate(frappe._dict(name="SIR-1", incoming_rate=0)), 410)
		sle.assert_called_once_with("DN-1", "P799", None, "DNR-1")

	def test_sales_invoice_that_moved_stock_keeps_its_rate(self):
		self.assertEqual(utils._get_si_item_transfer_rate(frappe._dict(name="SIR-1", incoming_rate=375)), 375)

	def test_receipt_from_a_sales_invoice_resolves_its_source(self):
		self.dn_rate = 400
		with patch.object(utils.frappe.db, "exists", return_value=True), \
				patch.object(utils.frappe.db, "get_value", side_effect=self._values):
			self.assertEqual(utils._source_incoming_rate_for_pr_item(frappe._dict(sales_invoice_item="SIR-1"), False), 400)
		self.assertIsNone(utils._source_incoming_rate_for_pr_item(frappe._dict(), False))


class TestZeroValueExtraRow(unittest.TestCase):
	def setUp(self):
		self.items = {"P799": {"is_stock_item": 1}, "PACK": {"is_stock_item": 0}, "BOX": {"is_stock_item": 1}}
		real = frappe.get_cached_value
		self._p = patch.object(ip.frappe, "get_cached_value", side_effect=lambda dt, name, field, *a, **k:
			frappe._dict(is_fixed_asset=0, **self.items[name]) if dt == "Item" and name in self.items
			else real(dt, name, field, *a, **k))
		self._p.start()

	def tearDown(self):
		self._p.stop()

	def _pair(self, extra):
		dn = _doc("Delivery Note", "DN-1", [{"item_code": "P799", "qty": 2, "rate": 100}], [_igst(36)])
		dn.items[0].name = "DNR-1"
		dn.items[0].igst_rate, dn.items[0].igst_amount = 18, 36
		si = _doc("Sales Invoice", "SI-1", [{"item_code": "P799", "qty": 2, "rate": 100, "dn_detail": "DNR-1"}, extra],
				  [_igst(36 + extra.get("igst_amount", 0))])
		si.items[0].igst_rate, si.items[0].igst_amount = 18, 36
		for i, r in enumerate(si.items, start=1):
			r.name = f"SIR-{i}"
		with patch.object(ip, "_source_docs", return_value=[dn]):
			return ip.compare_internal_pair(si, "DN->SI")

	def test_non_stock_row_of_zero_value_is_allowed(self):
		self.assertEqual(self._pair({"item_code": "PACK", "qty": 1, "rate": 0}), [])

	def test_priced_extra_row_is_refused(self):
		self.assertTrue(self._pair({"item_code": "PACK", "qty": 1, "rate": 5}))

	def test_stock_item_extra_row_is_refused_even_at_zero(self):
		self.assertTrue(self._pair({"item_code": "BOX", "qty": 1, "rate": 0}))


class TestSiPiLinkCheck(unittest.TestCase):
	def _si(self):
		si = _doc("Sales Invoice", "SI-1", [{"item_code": "P799", "qty": 2, "rate": 100}], [_igst(36)])
		si.items[0].name = "SIR-1"
		return si

	def _pi(self, *rows):
		pi = _doc("Purchase Invoice", "PI-1", rows, [{**_igst(sum(r["qty"] * r["rate"] for r in rows) * 0.18), "add_deduct_tax": "Add"}])
		for i, r in enumerate(pi.items, start=1):
			r.name = f"PIR-{i}"
		return pi

	def test_unlinked_exact_copy_pairs_and_matches(self):
		self.assertEqual(ip.si_pi_link_mismatches(self._si(), self._pi({"item_code": "P799", "qty": 2, "rate": 100})), [])

	def test_extra_pi_item_is_named(self):
		mismatches = ip.si_pi_link_mismatches(
			self._si(), self._pi({"item_code": "P799", "qty": 2, "rate": 100}, {"item_code": "P800", "qty": 1, "rate": 10})
		)
		text = ip.mismatch_text(mismatches)
		self.assertIn("P800", text)
		self.assertIn("not linked to any", text)

	def test_rate_change_is_named(self):
		text = ip.mismatch_text(ip.si_pi_link_mismatches(self._si(), self._pi({"item_code": "P799", "qty": 2, "rate": 99})))
		self.assertIn("Rate", text)


class TestReceiptRules(_Cutoff):
	def test_gstin_scope_reads_the_supplier_gstin(self):
		pr = frappe._dict(doctype="Purchase Receipt", company_gstin="27AAAAA0000A1Z5", supplier_gstin="24AAAAA0000A1Z5")
		self.assertEqual(utils._resolve_pr_gstin_scope(pr, True, False), "different")
		pr.supplier_gstin = "27AAAAA0000A1Z5"
		self.assertEqual(utils._resolve_pr_gstin_scope(pr, False, True), "same")

	def test_receipt_from_a_dn_across_gstins_is_refused(self):
		pr = frappe.new_doc("Purchase Receipt")
		pr.update({"supplier": "Branch B", "bns_inter_company_reference": "DN-1", "posting_date": AFTER,
				   "company_gstin": "27AAAAA0000A1Z5", "supplier_gstin": "24AAAAA0000A1Z5"})
		with patch.object(utils, "_validate_internal_ref_requires_internal_party"), \
				patch.object(utils, "_validate_unique_internal_source_claim"), \
				patch.object(utils, "_resolve_source_posting_date", return_value=AFTER), \
				patch.object(utils, "_get_pr_source_link_flags", return_value={"has_dn_link": True, "has_si_link": False,
																			   "dn_names": ["DN-1"], "si_names": []}), \
				patch.object(utils, "_dn_has_diff_gstin_opt_in", return_value=False):
			with self.assertRaises(frappe.ValidationError) as ctx:
				utils.validate_internal_purchase_receipt_linkage(pr)
		self.assertIn("cannot be linked to a Delivery Note", str(ctx.exception))

	def test_older_receipt_keeps_its_rules(self):
		pr = frappe.new_doc("Purchase Receipt")
		pr.update({"supplier": "Branch B", "bns_inter_company_reference": "DN-1", "posting_date": BEFORE})
		with patch.object(utils, "_validate_internal_ref_requires_internal_party"), \
				patch.object(utils, "_validate_unique_internal_source_claim"), \
				patch.object(utils, "_resolve_source_posting_date", return_value=BEFORE), \
				patch.object(utils, "_validate_internal_pr_one_to_one_parity") as parity:
			utils.validate_internal_purchase_receipt_linkage(pr)
		parity.assert_not_called()


class TestPerBatchRatesOnOlderV15(unittest.TestCase):
	def test_each_entry_gets_its_own_rate_and_the_totals_follow(self):
		bundle = frappe.new_doc("Serial and Batch Bundle")
		bundle.append("entries", {"batch_no": "B1", "qty": 3, "incoming_rate": 120})
		bundle.append("entries", {"batch_no": "B2", "qty": 2, "incoming_rate": 120})
		utils._apply_per_entry_rates(bundle, {(None, "B1"): 100, (None, "B2"): 150})
		self.assertEqual([(e.incoming_rate, e.stock_value_difference) for e in bundle.entries], [(100, 300), (150, 300)])
		self.assertEqual(bundle.total_amount, 600)
		self.assertEqual(bundle.total_qty, 5)
