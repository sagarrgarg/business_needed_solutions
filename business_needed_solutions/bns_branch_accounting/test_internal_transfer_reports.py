# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
The internal-transfer reports list what the submit checks refuse (internal_parity +
the receiver rules), and nothing else.

Documents are written straight to the database (db_insert, no hooks) as submitted
vouchers and rolled back after every test, so each case shows one rule without a full
two-branch setup.

    bench --site test.localhost run-tests --app business_needed_solutions --module \
        business_needed_solutions.bns_branch_accounting.test_internal_transfer_reports
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, date_diff, getdate, today

from business_needed_solutions.bns_branch_accounting import internal_transfer_scan as scan
from business_needed_solutions.bns_branch_accounting.report.internal_transfer_accounting_audit import (
	internal_transfer_accounting_audit as audit,
)
from business_needed_solutions.bns_branch_accounting.report.internal_transfer_receive_mismatch import (
	internal_transfer_receive_mismatch as report,
)

COMPANY = "_Test Company"
CUSTOMER = "_BNSRPT Internal Customer"
SUPPLIER = "_BNSRPT Internal Supplier"
GSTIN_A, GSTIN_B = "24AAACB0000A1Z5", "27AAACB0000A1Z1"
FILTERS = {"company": COMPANY, "from_date": "2026-01-01", "to_date": "2026-12-31"}

# P799 on two rows at different rates, WL-06 once: the case an item_code match got wrong.
ROWS = (("P799", 2, 100), ("P799", 4, 120), ("WL-06", 4, 50))


def _insert(doctype, name, header, rows, row_prefix, link=None):
	"""Insert a submitted document (and its rows) without running any hook."""
	doc = frappe.get_doc({"doctype": doctype, "company": COMPANY, "docstatus": 1, **header})
	doc.name = name
	total = 0
	for i, (item_code, qty, rate, *extra) in enumerate(rows, start=1):
		amount = qty * rate
		total += amount
		row = {
			"name": f"{row_prefix}-{i}", "idx": i, "docstatus": 1, "item_code": item_code,
			"item_name": item_code, "uom": "Nos", "stock_uom": "Nos", "conversion_factor": 1,
			"qty": qty, "stock_qty": qty, "rate": rate, "base_rate": rate, "net_rate": rate,
			"base_net_rate": rate, "amount": amount, "base_amount": amount, "net_amount": amount,
			"base_net_amount": amount, "description": item_code,
		}
		if link:
			row.update(link(i, *extra))
		doc.append("items", row)
	doc.update({
		"total_qty": sum(r[1] for r in rows), "total": total, "base_total": total, "net_total": total,
		"base_net_total": total, "grand_total": total, "base_grand_total": total,
		"rounded_total": total, "base_rounded_total": total,
	})
	doc.db_insert()
	for child in doc.get_all_children():
		child.parent, child.parenttype, child.parentfield = doc.name, doctype, "items"
		child.db_insert()
	return doc


class TestInternalTransferReports(FrappeTestCase):
	def setUp(self):
		frappe.db.set_single_value("BNS Branch Accounting Settings", "internal_transfer_cutoff_fy",
								   "_Test Fiscal Year 2026")
		for doctype, name, flag in (("Customer", CUSTOMER, "is_bns_internal_customer"),
									("Supplier", SUPPLIER, "is_bns_internal_supplier")):
			if not frappe.db.exists(doctype, name):
				party = frappe.get_doc({"doctype": doctype, "name": name,
										doctype.lower() + "_name": name, flag: 1})
				party.db_insert()

	def tearDown(self):
		frappe.db.rollback()

	# -- builders --------------------------------------------------------------------

	def _dn(self, name, posting_date="2026-06-01", rows=ROWS, **header):
		return _insert("Delivery Note", name, {
			"customer": CUSTOMER, "posting_date": posting_date, "company_gstin": GSTIN_A,
			"billing_address_gstin": GSTIN_A, "is_bns_internal_customer": 1, **header,
		}, rows, name)

	def _pr_from(self, dn, name, rows=None, **header):
		rows = rows or [(r.item_code, r.qty, r.rate, r.name) for r in dn.items]
		# Both halves of the link, as the creation flow writes them.
		frappe.db.set_value("Delivery Note", dn.name, "bns_inter_company_reference", name, update_modified=False)
		return _insert("Purchase Receipt", name, {
			"supplier": SUPPLIER, "posting_date": dn.posting_date, "company_gstin": GSTIN_A,
			"supplier_gstin": GSTIN_A, "bns_inter_company_reference": dn.name,
			"is_bns_internal_supplier": 1, **header,
		}, rows, name, link=lambda i, src: {"delivery_note_item": src, "delivery_note": dn.name})

	def _si(self, name, posting_date="2026-06-01", **header):
		return _insert("Sales Invoice", name, {
			"customer": CUSTOMER, "posting_date": posting_date, "company_gstin": GSTIN_A,
			"billing_address_gstin": GSTIN_B, "is_bns_internal_customer": 1, "update_stock": 1, **header,
		}, ROWS, name)

	def _rows(self, name):
		return [r for r in report.get_data(dict(FILTERS)) if name in (r["document_name"], r.get("purchase_receipt"))]

	# -- document parity -------------------------------------------------------------

	def test_item_on_two_rows_exact_copy_shows_nothing(self):
		dn = self._dn("_BNSRPT-DN-A")
		# The receipt's tick is off, the supplier master is internal: still an internal
		# receipt (validation and GL go by the master), so no foreign-party row either.
		self._pr_from(dn, "_BNSRPT-PR-A", is_bns_internal_supplier=0)
		self.assertEqual(self._rows("_BNSRPT-PR-A"), [])
		self.assertEqual(self._rows("_BNSRPT-DN-A"), [])

	def test_item_on_two_rows_is_matched_row_by_row(self):
		dn = self._dn("_BNSRPT-DN-B")
		# The two P799 rows swap quantities: item totals still agree (6 = 6), the rows do not.
		swapped = [("P799", 4, 100, dn.items[0].name), ("P799", 2, 120, dn.items[1].name),
				   ("WL-06", 4, 50, dn.items[2].name)]
		self._pr_from(dn, "_BNSRPT-PR-B", rows=swapped)
		rows = [r for r in self._rows("_BNSRPT-PR-B") if r["transfer_chain"] == "DN->PR"]
		by_field = {(r["row_no"], r["parity_field"]) for r in rows}
		self.assertIn((1, "Quantity"), by_field)
		self.assertIn((2, "Quantity"), by_field)
		self.assertIn((1, "Amount"), by_field)
		# No made-up "missing" / "extra" rows and nothing on the untouched WL-06 row.
		self.assertFalse([r for r in rows if r["parity_field"] in ("Row", "Source row")], rows)
		self.assertFalse([r for r in rows if r["row_no"] == 3], rows)
		qty_row = next(r for r in rows if r["row_no"] == 1 and r["parity_field"] == "Quantity")
		self.assertEqual((qty_row["expected_value"], qty_row["found_value"]), ("2", "4"))
		self.assertEqual(qty_row["source_document"], "_BNSRPT-DN-B")
		self.assertIn("Row 1 (P799)", qty_row["mismatch_reason"])

		# The audit reports the same document from the same comparison.
		parity = [r for r in audit._audit_document_parity(frappe._dict(FILTERS))
				  if r["document_name"] == "_BNSRPT-PR-B"]
		self.assertEqual(len(parity), 1)
		self.assertEqual(parity[0]["deviation_type"], "Document Parity")
		self.assertEqual(parity[0]["document_type"], "Purchase Receipt")
		self.assertIn("Row 1 (P799)", parity[0]["details"])

	def test_report_agrees_with_the_receipt_check(self):
		dn = self._dn("_BNSRPT-DN-V")
		pr = self._pr_from(dn, "_BNSRPT-PR-V", rows=[("P799", 2, 100, dn.items[0].name),
													  ("P799", 4, 121, dn.items[1].name),
													  ("WL-06", 4, 50, dn.items[2].name)])
		doc = frappe.get_doc("Purchase Receipt", pr.name)
		from business_needed_solutions.bns_branch_accounting.utils import (
			_validate_internal_pr_one_to_one_parity,
		)

		with self.assertRaises(frappe.ValidationError):
			_validate_internal_pr_one_to_one_parity(doc)
		fields = {r["parity_field"] for r in self._rows(pr.name) if r["transfer_chain"] == "DN->PR"}
		self.assertTrue({"Rate", "Amount", "Total"} <= fields, fields)

	# -- receiver missing ------------------------------------------------------------

	def test_dn_without_receipt_is_listed_with_its_age(self):
		posting = add_days(today(), -40)
		if getdate(posting) < getdate("2026-01-01"):
			posting = "2026-01-02"
		self._dn("_BNSRPT-DN-C", posting_date=posting)
		filters = dict(FILTERS, to_date=today())
		rows = [r for r in report.get_data(filters) if r["document_name"] == "_BNSRPT-DN-C"]
		self.assertEqual(len(rows), 1, rows)
		self.assertEqual(rows[0]["missing_document"], "Purchase Receipt")
		self.assertEqual(rows[0]["transfer_chain"], "DN->PR")
		self.assertEqual(rows[0]["age_days"], date_diff(today(), posting))

		older = dict(filters, older_than_days=rows[0]["age_days"] + 1)
		self.assertFalse([r for r in report.get_data(older) if r["document_name"] == "_BNSRPT-DN-C"])

		# The audit's "No Counter-Document" uses the same rule.
		counter = [r for r in audit._audit_cross_document_consistency(frappe._dict(filters), {"stock_in_transit": "X"})
				   if r["document_name"] == "_BNSRPT-DN-C"]
		self.assertEqual([r["deviation_type"] for r in counter], ["No Counter-Document"])

	def test_dn_before_the_cutoff_is_not_listed(self):
		self._dn("_BNSRPT-DN-OLD", posting_date="2025-12-31")
		rows = report.get_data(dict(FILTERS, from_date="2025-01-01"))
		self.assertFalse([r for r in rows if r["document_name"] == "_BNSRPT-DN-OLD"])

	def test_sales_invoice_receivers(self):
		self._si("_BNSRPT-SI-D")
		si_e = self._si("_BNSRPT-SI-E")
		_insert("Purchase Receipt", "_BNSRPT-PR-E", {
			"supplier": SUPPLIER, "posting_date": "2026-06-01", "company_gstin": GSTIN_B,
			"supplier_gstin": GSTIN_A, "bns_inter_company_reference": si_e.name, "is_bns_internal_supplier": 1,
		}, [(r.item_code, r.qty, r.rate, r.name) for r in si_e.items], "_BNSRPT-PR-E",
			link=lambda i, src: {"sales_invoice_item": src})
		rows = {r["document_name"]: r for r in report.get_missing_receiver_rows(FILTERS)}
		self.assertEqual(rows["_BNSRPT-SI-D"]["missing_document"], "Purchase Invoice")
		self.assertEqual(rows["_BNSRPT-SI-D"]["transfer_chain"], "SI->PI")
		self.assertEqual(rows["_BNSRPT-SI-E"]["transfer_chain"], "SI->PR->PI")
		self.assertEqual(rows["_BNSRPT-SI-E"]["purchase_receipt"], "_BNSRPT-PR-E")

		# Once the invoice exists the SI is no longer missing its receiver.
		_insert("Purchase Invoice", "_BNSRPT-PI-D", {
			"supplier": SUPPLIER, "posting_date": "2026-06-02", "company_gstin": GSTIN_B,
			"supplier_gstin": GSTIN_A, "bns_inter_company_reference": "_BNSRPT-SI-D",
			"bill_no": "_BNSRPT-SI-D", "is_bns_internal_supplier": 1, "update_stock": 1,
		}, ROWS, "_BNSRPT-PI-D")
		names = {r["document_name"] for r in report.get_missing_receiver_rows(FILTERS)}
		self.assertNotIn("_BNSRPT-SI-D", names)
		self.assertIn("_BNSRPT-SI-E", names)

	# -- party judged on the master ----------------------------------------------------

	def test_reference_on_a_regular_supplier_is_listed(self):
		dn = self._dn("_BNSRPT-DN-F")
		frappe.db.set_value("Supplier", SUPPLIER, "is_bns_internal_supplier", 0)
		self._pr_from(dn, "_BNSRPT-PR-F", is_bns_internal_supplier=0)
		chains = {r["transfer_chain"] for r in self._rows("_BNSRPT-PR-F")}
		self.assertIn("Foreign-party reference", chains)
		self.assertNotIn("DN->PR", chains)  # refused before parity: no parity rows


class TestParityGates(FrappeTestCase):
	"""parity_links() runs the validators' gates (stubbed parties / cutoff)."""

	def _doc(self, doctype, **values):
		doc = frappe.new_doc(doctype)
		doc.update(values)
		return doc

	def test_receipt_on_regular_supplier_is_not_compared(self):
		pr = self._doc("Purchase Receipt", bns_inter_company_reference="DN-X")
		with patch.object(scan.utils, "is_bns_internal_supplier", return_value=False):
			self.assertEqual(scan.parity_links(pr), [])
		with patch.object(scan.utils, "is_bns_internal_supplier", return_value=True), \
				patch.object(scan.ip, "detect_links", return_value=["DN->PR"]):
			self.assertEqual(scan.parity_links(pr), ["DN->PR"])

	def test_returns_are_never_compared(self):
		for doctype in ("Sales Invoice", "Purchase Receipt", "Purchase Invoice"):
			self.assertEqual(scan.parity_links(self._doc(doctype, is_return=1, bns_inter_company_reference="X")), [])

	def test_sales_invoice_gates(self):
		si = self._doc("Sales Invoice", company_gstin=GSTIN_A, billing_address_gstin=GSTIN_B, posting_date="2026-06-01")
		si.append("items", {"item_code": "A", "delivery_note": "DN-X"})
		with patch.object(scan.utils, "is_bns_internal_customer", return_value=True), \
				patch.object(scan.utils, "is_after_internal_transfer_cutoff", return_value=True):
			self.assertEqual(scan.parity_links(si), ["DN->SI"])
			si.billing_address_gstin = GSTIN_A  # refused for its GSTIN first (gstin_problems)
			self.assertEqual(scan.parity_links(si), [])
		si.billing_address_gstin = GSTIN_B
		with patch.object(scan.utils, "is_bns_internal_customer", return_value=True), \
				patch.object(scan.utils, "is_after_internal_transfer_cutoff", return_value=False):
			self.assertEqual(scan.parity_links(si), [])

	def test_dn_receiver_route(self):
		same = frappe._dict(company_gstin=GSTIN_A, billing_address_gstin=GSTIN_A)
		diff = frappe._dict(company_gstin=GSTIN_A, billing_address_gstin=GSTIN_B)
		self.assertTrue(scan.dn_routes_to_pr(same))
		self.assertFalse(scan.dn_routes_to_pr(diff))
		self.assertTrue(scan.dn_routes_to_pr(frappe._dict(diff, bns_allow_diff_gstin_dn_pr=1)))
		self.assertTrue(scan.dn_routes_to_pr(frappe._dict(diff, status="BNS Internally Transferred")))
