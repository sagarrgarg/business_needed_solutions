# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
Strict one-to-one parity between internal-transfer documents (internal_parity.py).

In-memory documents (nothing saved): the source documents are handed to the matcher
directly, so each case shows one rule.

    bench --site <site> run-tests --module \
        business_needed_solutions.bns_branch_accounting.test_internal_parity
"""

import unittest
from unittest.mock import patch

import frappe

from business_needed_solutions.bns_branch_accounting import internal_parity as ip


def _doc(doctype, name, rows, taxes=(), **header):
	doc = frappe.new_doc(doctype)
	doc.name = name
	doc.update(header)
	for i, r in enumerate(rows, start=1):
		row = doc.append("items", {"idx": i, "uom": "Nos", "stock_uom": "Nos", "conversion_factor": 1,
								   "gst_hsn_code": "61149090", **r})
		row.stock_qty = row.get("stock_qty") or row.qty
		row.amount = row.get("amount") or row.qty * row.rate
		row.net_rate = row.get("net_rate") or row.rate
		row.net_amount = row.get("net_amount") or row.amount
		for f in ("base_rate", "base_amount", "base_net_rate", "base_net_amount"):
			row.set(f, row.get(f) or row.get(f[5:]))
	for t in taxes:
		doc.append("taxes", t)
	doc.total_qty = sum(r.qty for r in doc.items)
	doc.total = doc.base_total = doc.net_total = doc.base_net_total = sum(r.amount for r in doc.items)
	tax = sum(t.get("base_tax_amount_after_discount_amount", 0) for t in taxes)
	doc.total_taxes_and_charges = doc.base_total_taxes_and_charges = tax
	doc.grand_total = doc.base_grand_total = doc.total + tax
	return doc


def _igst(amount, rate=18):
	return {"charge_type": "On Net Total", "account_head": "IGST", "rate": rate, "gst_tax_type": "igst",
			"base_tax_amount_after_discount_amount": amount, "tax_amount": amount}


class TestInternalParity(unittest.TestCase):
	def _sale(self, *rows, taxes=None):
		rows = rows or ({"item_code": "P799", "qty": 2, "rate": 100}, {"item_code": "P799", "qty": 3, "rate": 120})
		si = _doc("Sales Invoice", "SI-1", rows, taxes if taxes is not None else [_igst(sum(r["qty"] * r["rate"] for r in rows) * 0.18)])
		for i, r in enumerate(si.items, start=1):
			r.name = f"SIR-{i}"
			r.igst_rate, r.igst_amount = 18, r.amount * 0.18
		return si

	def _pi_from(self, si, change=None, drop=None, taxes=None):
		rows = []
		for r in si.items:
			if drop and r.name == drop:
				continue
			rows.append({"item_code": r.item_code, "qty": r.qty, "rate": r.rate, "sales_invoice_item": r.name,
						 "igst_rate": r.igst_rate, "igst_amount": r.igst_amount})
		if change:
			change(rows)
		amount = sum(r["qty"] * r["rate"] for r in rows)
		return _doc("Purchase Invoice", "PI-1", rows, taxes if taxes is not None else [
			{**_igst(amount * 0.18), "add_deduct_tax": "Add"}])

	def _compare(self, pi, si, link="SI->PI"):
		with patch.object(ip, "_source_docs", return_value=[si]):
			return ip.compare_internal_pair(pi, link)

	def test_exact_copy_has_no_difference(self):
		si = self._sale()
		self.assertEqual(self._compare(self._pi_from(si), si), [])

	def test_same_item_on_two_rows_is_matched_row_by_row(self):
		si = self._sale()
		# Quantities swapped between the two P799 rows: item totals still agree.
		def swap(rows):
			rows[0]["qty"], rows[1]["qty"] = rows[1]["qty"], rows[0]["qty"]
		found = self._compare(self._pi_from(si, change=swap), si)
		self.assertTrue(any(m.field == "Quantity" and m.row == 1 for m in found), found)

	def test_extra_row_is_refused(self):
		si = self._sale()
		def extra(rows):
			rows.append({"item_code": "WL-06", "qty": 1, "rate": 50})
		found = self._compare(self._pi_from(si, change=extra), si)
		self.assertTrue(any(m.field == "Source row" and m.item_code == "WL-06" for m in found), found)

	def test_missing_row_is_refused(self):
		si = self._sale()
		found = self._compare(self._pi_from(si, drop="SIR-2"), si)
		self.assertTrue(any(m.field == "Row" and m.found == "missing" for m in found), found)

	def test_row_used_twice_is_refused(self):
		si = self._sale()
		def twice(rows):
			rows[1]["sales_invoice_item"] = "SIR-1"
		found = self._compare(self._pi_from(si, change=twice), si)
		self.assertTrue(any(m.field == "Source row" and m.found == "used again" for m in found), found)

	def test_rate_and_hsn_must_be_equal(self):
		si = self._sale()
		def change(rows):
			rows[0]["rate"] = 101
			rows[1]["gst_hsn_code"] = "95030010"
		fields = {m.field for m in self._compare(self._pi_from(si, change=change), si)}
		self.assertIn("Rate", fields)
		self.assertIn("HSN/SAC", fields)

	def test_tax_head_must_match_not_only_the_total(self):
		si = self._sale()
		amount = si.total * 0.18
		half = {"charge_type": "On Net Total", "rate": 9, "add_deduct_tax": "Add",
				"base_tax_amount_after_discount_amount": amount / 2, "tax_amount": amount / 2}
		pi = self._pi_from(si, taxes=[{**half, "account_head": "CGST", "gst_tax_type": "cgst"},
									  {**half, "account_head": "SGST", "gst_tax_type": "sgst"}])
		fields = {m.field for m in self._compare(pi, si)}
		self.assertIn("IGST amount", fields)
		self.assertIn("CGST amount", fields)
		self.assertNotIn("Total Taxes", fields)  # totals agree; only the heads differ

	def test_item_level_gst_must_match(self):
		si = self._sale()
		def change(rows):
			rows[0]["igst_amount"] = rows[0]["igst_amount"] + 9.52
		fields = {m.field for m in self._compare(self._pi_from(si, change=change), si)}
		self.assertIn("IGST Amount", fields)

	def test_paisa_difference_in_totals_is_refused(self):
		si = self._sale()
		pi = self._pi_from(si)
		pi.grand_total += 0.01
		self.assertTrue(any(m.field == "Grand Total" for m in self._compare(pi, si)))

	def test_assert_throws_with_the_differences(self):
		si = self._sale()
		def change(rows):
			rows[0]["qty"] = 5
		pi = self._pi_from(si, change=change)
		with patch.object(ip, "_source_docs", return_value=[si]):
			with self.assertRaises(frappe.ValidationError) as ctx:
				ip.assert_internal_pair(pi, links=["SI->PI"], force=True)
		self.assertIn("Quantity", str(ctx.exception))

	def test_dn_to_si_rows_without_a_dn_link_are_refused(self):
		dn = _doc("Delivery Note", "DN-1", [{"item_code": "A", "qty": 1, "rate": 10}])
		dn.items[0].name = "DNR-1"
		si = _doc("Sales Invoice", "SI-2", [
			{"item_code": "A", "qty": 1, "rate": 10, "delivery_note": "DN-1", "dn_detail": "DNR-1"},
			{"item_code": "B", "qty": 1, "rate": 0},
		])
		found = self._compare(si, dn, link="DN->SI")
		self.assertTrue(any(m.item_code == "B" and m.field == "Source row" for m in found), found)

	def test_lots_compared_only_when_submitting(self):
		si = self._sale()
		pi = self._pi_from(si)
		pi.update_stock = si.update_stock = 1
		with patch.object(ip, "_lot_differences", return_value=[("Batches", "A × 2", "B × 2")]) as lots:
			self.assertEqual(self._compare(pi, si), [])
			lots.assert_not_called()
			pi.docstatus = 1
			found = self._compare(pi, si)
		self.assertTrue(any(m.field == "Batches" for m in found))
