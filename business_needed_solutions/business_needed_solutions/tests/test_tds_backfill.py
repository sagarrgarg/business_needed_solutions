"""TDS on submitted Purchase Invoices (overrides/tds_backfill.py).

Builds its own company, categories, suppliers and invoices, and rolls everything back at
the end (FrappeTestCase). ERPNext v15 only: on v16 the tools are switched off.
"""

import random
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, getdate

from business_needed_solutions.business_needed_solutions.overrides import tds_backfill as tds

COMPANY = "_Test BNS TDS Co"
ABBR = "_TBT"
CAT_194Q = "_Test BNS 194Q"
CAT_194C = "_Test BNS 194C"
CAT_NO_ROUND = "_Test BNS No Round"
ITEM = "_Test BNS TDS Item"

# Tropical Industries, FY26-27: (invoice, month, day, net). The debit note is negative.
TROPICAL = [
    ("0089", 4, 5, 670000), ("0101", 4, 15, 77000), ("PI070127-0050", 4, 20, 10650),
    ("0113", 5, 2, 154000), ("0115", 5, 10, 1005000), ("0136", 5, 25, 704900),
    ("0158", 6, 5, 385000), ("0175", 6, 20, 536000), ("0176", 6, 22, 10500),
    ("DBN-0014", 7, 5, -536000), ("0233", 7, 10, 380000), ("0276", 7, 25, 770000),
    ("0355", 8, 1, 1078000), ("0379", 8, 6, 1065000), ("0380", 8, 7, 462000),
    ("0425", 8, 20, 932200), ("0480", 9, 10, 4740000), ("0494", 9, 25, 1990800),
]
TROPICAL_TDS = {"0355": 245, "0379": 1065, "0380": 462, "0425": 932, "0480": 4740, "0494": 1991}


def _acc(name):
    return f"{name} - {ABBR}"


class TestTDSBackfill(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not tds._tax_withholding_on_invoice():
            raise cls.skipTest(cls, "ERPNext without invoice tax withholding (v16)")
        frappe.set_user("Administrator")
        cls._setup_company()
        cls._setup_categories()
        settings = frappe.get_single("BNS Settings")
        settings.enable_tds_category_fixables = 1
        settings.tds_filed_upto = None
        settings.flags.ignore_mandatory = True
        settings.save(ignore_permissions=True)
        frappe.flags.pop("_bns_tds_backfill_roles", None)
        cls.fy_start, cls.fy_end = tds._fiscal_year(COMPANY)

    def setUp(self):
        frappe.db.savepoint("bns_tds_test")

    def tearDown(self):
        frappe.db.rollback(save_point="bns_tds_test")
        frappe.clear_document_cache("Tax Withholding Category", CAT_194Q)

    # ------------------------------------------------------------------ fixtures

    @classmethod
    def _setup_company(cls):
        if not frappe.db.exists("Company", COMPANY):
            frappe.get_doc({
                "doctype": "Company", "company_name": COMPANY, "abbr": ABBR,
                "default_currency": "INR", "country": "India",
                "create_chart_of_accounts_based_on": "Standard Template",
                "chart_of_accounts": "Standard",
            }).insert()
        from erpnext.accounts.utils import get_fiscal_year

        try:
            get_fiscal_year(frappe.utils.today(), company=COMPANY)
        except Exception:
            fy_name = get_fiscal_year(frappe.utils.today())[0]
            fy = frappe.get_doc("Fiscal Year", fy_name)
            fy.append("companies", {"company": COMPANY})
            fy.save()
            frappe.cache.delete_value("fiscal_years")
        for name in ("TDS Payable", "TDS Payable Old"):
            if not frappe.db.exists("Account", _acc(name)):
                frappe.get_doc({
                    "doctype": "Account", "account_name": name, "company": COMPANY,
                    "parent_account": _acc("Duties and Taxes"), "account_type": "Tax",
                }).insert()
        if not frappe.db.exists("Item", ITEM):
            frappe.get_doc({
                "doctype": "Item", "item_code": ITEM, "item_group": "Services",
                "is_stock_item": 0, "stock_uom": "Nos", "gst_hsn_code": "999900",
            }).insert()

    @classmethod
    def _setup_categories(cls):
        fy_start, fy_end = tds._fiscal_year(COMPANY)
        for name, rate, single, cumulative, excess, round_off in (
            (CAT_194Q, 0.1, 0, 5000000, 1, 1),
            (CAT_194C, 1, 30000, 100000, 0, 1),
            (CAT_NO_ROUND, 1, 0, 1000, 0, 0),
        ):
            if frappe.db.exists("Tax Withholding Category", name):
                frappe.delete_doc("Tax Withholding Category", name, force=True)
            frappe.get_doc({
                "doctype": "Tax Withholding Category", "name": name, "category_name": name,
                "tax_on_excess_amount": excess, "round_off_tax_amount": round_off,
                "rates": [{"from_date": fy_start, "to_date": fy_end, "tax_withholding_rate": rate,
                           "single_threshold": single, "cumulative_threshold": cumulative}],
                "accounts": [{"company": COMPANY, "account": _acc("TDS Payable")}],
            }).insert()

    def _supplier(self, name, pan):
        if not frappe.db.exists("Supplier", name):
            frappe.get_doc({"doctype": "Supplier", "supplier_name": name, "supplier_group": "All Supplier Groups",
                            "pan": pan, "default_currency": "INR"}).insert()
        frappe.db.set_value("Supplier", name, "tax_withholding_category", None)
        return name

    def _date(self, month, day):
        year = self.fy_start.year if month >= 4 else self.fy_start.year + 1
        return getdate(f"{year}-{month:02d}-{day:02d}")

    def _pi(self, supplier, date, amount, return_against=None, category=None):
        pi = frappe.new_doc("Purchase Invoice")
        pi.update({
            "company": COMPANY, "supplier": supplier, "posting_date": date, "set_posting_time": 1,
            "due_date": date, "bill_date": date, "bill_no": frappe.generate_hash(length=8),
            "credit_to": _acc("Creditors"), "apply_tds": 1 if category else 0,
            "tax_withholding_category": category, "currency": "INR", "conversion_rate": 1, "update_stock": 0,
            "is_return": 1 if amount < 0 else 0, "return_against": return_against,
        })
        pi.append("items", {
            "item_code": ITEM, "qty": -1 if amount < 0 else 1, "rate": abs(amount),
            "expense_account": _acc("Cost of Goods Sold"), "cost_center": _acc("Main"),
        })
        pi.insert()
        pi.submit()
        return pi.name

    def _tropical(self):
        supplier = self._supplier("_Test BNS Tropical", "AAACT1234B")
        names = {}
        for key, month, day, net in TROPICAL:
            names[key] = self._pi(supplier, self._date(month, day), net,
                                  return_against=names.get("0175") if net < 0 else None)
        frappe.db.set_value("Supplier", supplier, "tax_withholding_category", CAT_194Q)
        return supplier, names

    # ------------------------------------------------------------------ helpers

    def _run(self, specs, allow_filed=False):
        plans = tds._plans_from_specs(specs, allow_filed)
        return tds._apply_specs(specs, tds._plan_token(plans), allow_filed)

    def _change(self, name, category):
        return self._run([tds._invoice_spec(name, category)])

    def _tds(self, name):
        return flt(frappe.db.sql(
            """SELECT IFNULL(SUM(base_tax_amount_after_discount_amount), 0) FROM `tabPurchase Taxes and Charges`
               WHERE parent = %s AND is_tax_withholding_account = 1""", name)[0][0], 2)

    def _gl(self, name):
        return frappe.db.sql(
            """SELECT account, IFNULL(party, '') AS party, debit, credit FROM `tabGL Entry`
               WHERE voucher_type = 'Purchase Invoice' AND voucher_no = %s AND is_cancelled = 0
               ORDER BY account, debit, credit""", name, as_dict=True)

    def _assert_ledger_clean(self, name):
        gl = self._gl(name)
        self.assertAlmostEqual(sum(flt(g.debit) for g in gl), sum(flt(g.credit) for g in gl), 2)
        tds_rows = [g for g in gl if g.account in (_acc("TDS Payable"), _acc("TDS Payable Old"))]
        self.assertFalse([g for g in tds_rows if flt(g.debit)], f"{name}: contra debit on TDS account")
        self.assertLessEqual(len(tds_rows), 1)
        # The ledger is exactly what a Repost Accounting Ledger of the invoice makes.
        before = tds._live_gl_net(name)
        tds._rebuild_gl(name)
        self.assertEqual({k: flt(v, 2) for k, v in before.items()},
                         {k: flt(v, 2) for k, v in tds._live_gl_net(name).items()})
        own = frappe.db.get_all("Payment Ledger Entry", filters={
            "voucher_no": name, "against_voucher_no": name}, fields=["delinked"])
        self.assertTrue(own and not any(r.delinked for r in own))
        ple_sum = flt(frappe.db.sql(
            """SELECT SUM(amount) FROM `tabPayment Ledger Entry`
               WHERE against_voucher_no = %s AND delinked = 0""", name)[0][0], 2)
        self.assertAlmostEqual(flt(frappe.db.get_value("Purchase Invoice", name, "outstanding_amount"), 2), ple_sum, 2)

    def _assert_tropical(self, names):
        for key, name in names.items():
            self.assertEqual(self._tds(name), flt(TROPICAL_TDS.get(key, 0)), key)
        self.assertEqual(sum(self._tds(n) for n in names.values()), 9435)

    # ------------------------------------------------------------------ tests

    def test_tropical_plan(self):
        supplier, names = self._tropical()
        plan = tds.plan_supplier_year(supplier, COMPANY, mode="supplier")
        targets = {d.name: d.target_tds for d in plan.docs}
        for key, name in names.items():
            if key != "DBN-0014":
                self.assertEqual(targets[name], TROPICAL_TDS.get(key, 0), key)
        self.assertEqual(sum(TROPICAL_TDS.values()), 9435)

    def test_tropical_any_order(self):
        supplier, names = self._tropical()
        order = [k for k in names if k != "DBN-0014"]
        # newest first, one invoice at a time, through the invoice button
        for key in reversed(order):
            self._change(names[key], CAT_194Q)
        self._assert_tropical(names)
        for name in names.values():
            self._assert_ledger_clean(name)
        # take it all off in a random order, then put it back in another
        rng = random.Random(7)
        shuffled = order[:]
        rng.shuffle(shuffled)
        for key in shuffled:
            self._change(names[key], None)
        for name in names.values():
            self.assertEqual(self._tds(name), 0)
        rng.shuffle(shuffled)
        for key in shuffled:
            self._change(names[key], CAT_194Q)
        self._assert_tropical(names)

    def test_tropical_redo_and_noop(self):
        supplier, names = self._tropical()
        self._run([{"supplier": supplier, "company": COMPANY, "mode": "supplier"}])
        self._assert_tropical(names)
        count = frappe.db.count("GL Entry")
        summary = self._run([{"supplier": supplier, "company": COMPANY, "mode": "supplier"}])
        self.assertEqual(summary["changed"], 0)
        self.assertEqual(frappe.db.count("GL Entry"), count)

    def test_zero_is_not_final(self):
        """0380 worked out alone, before the earlier bills, still ends up with 462."""
        supplier, names = self._tropical()
        self._change(names["0380"], CAT_194Q)
        self.assertEqual(self._tds(names["0380"]), 0)  # earlier bills not in the category yet
        self._run([{"supplier": supplier, "company": COMPANY, "mode": "supplier"}])
        self.assertEqual(self._tds(names["0380"]), 462)

    def test_partial_payment_stays_linked(self):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        supplier = self._supplier("_Test BNS Partly Paid", "AAACP1234C")
        pi = self._pi(supplier, self._date(5, 1), 50000)
        pe = get_payment_entry("Purchase Invoice", pi, party_amount=20000, bank_account=_acc("Cash"))
        pe.reference_no, pe.reference_date = "X1", pe.posting_date
        pe.insert()
        pe.submit()
        frappe.db.set_value("Supplier", supplier, "tax_withholding_category", CAT_194C)

        for category, tds_amount in ((CAT_194C, 500), (None, 0), (CAT_194C, 500)):
            self._change(pi, category)
            self.assertEqual(self._tds(pi), tds_amount)
            self.assertAlmostEqual(flt(frappe.db.get_value("Purchase Invoice", pi, "outstanding_amount")),
                                   50000 - tds_amount - 20000, 2)
            self.assertEqual(flt(frappe.db.get_value("Payment Entry Reference",
                             {"parent": pe.name, "reference_name": pi}, "allocated_amount")), 20000)
            self._assert_ledger_clean(pi)

    def test_overpaid_invoice_cuts_newest_payment(self):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        supplier = self._supplier("_Test BNS Fully Paid", "AAACF1234D")
        pi = self._pi(supplier, self._date(5, 2), 50000)
        pes = []
        for amount in (30000, 20000):
            pe = get_payment_entry("Purchase Invoice", pi, party_amount=amount, bank_account=_acc("Cash"))
            pe.reference_no, pe.reference_date = "X2", pe.posting_date
            pe.insert()
            pe.submit()
            pes.append(pe.name)
        frappe.db.set_value("Supplier", supplier, "tax_withholding_category", CAT_194C)
        preview = tds.preview_tds_category_change(pi, CAT_194C)
        caps = preview["plans"][0]["rows"][0]["caps"]
        self.assertEqual(len(caps), 1)
        summary = self._change(pi, CAT_194C)
        self.assertEqual(summary["error_count"], 0, summary["errors"])
        allocated = {
            pe: flt(frappe.db.get_value("Payment Entry Reference", {"parent": pe, "reference_name": pi},
                                        "allocated_amount"))
            for pe in pes
        }
        self.assertEqual(sum(allocated.values()), 49500)
        self.assertEqual(sorted(allocated.values()), [19500, 30000])
        self.assertEqual(flt(frappe.db.get_value("Purchase Invoice", pi, "outstanding_amount")), 0)
        self._assert_ledger_clean(pi)

    def test_remap_moves_invoices_and_reports_challans(self):
        supplier, names = self._tropical()
        self._run([{"supplier": supplier, "company": COMPANY, "mode": "supplier"}])
        old, new = _acc("TDS Payable"), _acc("TDS Payable Old")
        frappe.db.set_value("Tax Withholding Account", {"parent": CAT_194Q, "company": COMPANY}, "account", new)
        frappe.clear_document_cache("Tax Withholding Category", CAT_194Q)
        je = frappe.get_doc({
            "doctype": "Journal Entry", "company": COMPANY, "posting_date": self._date(9, 7),
            "accounts": [
                {"account": old, "debit_in_account_currency": 245, "cost_center": _acc("Main")},
                {"account": _acc("Cash"), "credit_in_account_currency": 245, "cost_center": _acc("Main")},
            ],
        }).insert()
        je.submit()

        preview = tds.preview_tds_remap(COMPANY)
        self.assertEqual(preview["summary"]["changes"], len(TROPICAL_TDS))
        self.assertEqual([c.voucher_no for c in preview["challans"]], [je.name])
        specs = tds._remap_specs(COMPANY)
        for s in specs:
            s["old_accounts"] = tds._old_accounts(COMPANY)
        summary = tds._apply_specs(specs, preview["token"])
        self.assertEqual(summary["changed"], len(TROPICAL_TDS))
        self.assertFalse(summary["remaining"]["done"])
        self.assertEqual(flt(summary["remaining"]["challan_amount"]), 245)
        on_old = flt(frappe.db.sql(
            """SELECT IFNULL(SUM(credit - debit), 0) FROM `tabGL Entry`
               WHERE account = %s AND voucher_type = 'Purchase Invoice' AND is_cancelled = 0""", old)[0][0])
        self.assertEqual(on_old, 0)
        self._assert_tropical(names)
        for name in names.values():
            self._assert_ledger_clean(name)

    def test_filed_quarter_is_blocked(self):
        supplier = self._supplier("_Test BNS Filed", "AAACQ1234E")
        q1 = self._pi(supplier, self._date(5, 3), 50000)
        q2 = self._pi(supplier, self._date(7, 3), 50000)
        frappe.db.set_value("Supplier", supplier, "tax_withholding_category", CAT_194C)
        frappe.db.set_single_value("BNS Settings", "tds_filed_upto", self._date(6, 30))
        try:
            spec = {"supplier": supplier, "company": COMPANY, "mode": "supplier"}
            plan = tds.plan_supplier_year(supplier, COMPANY, mode="supplier")
            rows = {d.name: d for d in plan.docs}
            self.assertTrue(rows[q1].blocked)
            self.assertFalse(rows[q2].blocked)
            self.assertEqual(rows[q2].quarter, "Q2")
            self._run([spec])
            self.assertEqual(self._tds(q1), 0)
            self.assertEqual(self._tds(q2), 500)
            self._run([spec], allow_filed=True)  # System Manager override
            self.assertEqual(self._tds(q1), 500)
        finally:
            frappe.db.set_single_value("BNS Settings", "tds_filed_upto", None)

    def test_rounding(self):
        supplier = self._supplier("_Test BNS Paise", "AAACR1234F")
        pi = self._pi(supplier, self._date(5, 4), 1286.4)
        frappe.db.set_value("Supplier", supplier, "tax_withholding_category", CAT_NO_ROUND)
        preview = tds.preview_supplier_tds(supplier, COMPANY)
        self.assertTrue(any("round" in w.lower() for w in preview["plans"][0]["warnings"]))
        self._run([{"supplier": supplier, "company": COMPANY, "mode": "supplier"}])
        self.assertEqual(self._tds(pi), 12.86)

    def test_refuses_when_other_lines_would_move(self):
        from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice

        supplier = self._supplier("_Test BNS Stock", "AAACS1234G")
        pi = self._pi(supplier, self._date(5, 5), 50000)
        frappe.db.set_value("Supplier", supplier, "tax_withholding_category", CAT_194C)
        original = PurchaseInvoice.get_gl_entries

        def with_stock_line(self, *args, **kwargs):
            gl = original(self, *args, **kwargs)
            gl.append(self.get_gl_dict({"account": _acc("Stock In Hand"), "debit": 1, "debit_in_account_currency": 1}))
            return gl

        with patch.object(PurchaseInvoice, "get_gl_entries", with_stock_line):
            plan = tds.plan_supplier_year(supplier, COMPANY, mode="supplier")
        row = next(d for d in plan.docs if d.name == pi)
        self.assertIn("Stock In Hand", row.blocked)
        self.assertEqual(self._tds(pi), 0)

    def test_preview_token_required(self):
        supplier = self._supplier("_Test BNS Token", "AAACU1234H")
        pi = self._pi(supplier, self._date(5, 6), 50000)
        frappe.db.set_value("Supplier", supplier, "tax_withholding_category", CAT_194C)
        with self.assertRaises(frappe.ValidationError):
            tds._apply_specs([tds._invoice_spec(pi, CAT_194C)], "stale")
        self.assertEqual(self._tds(pi), 0)

    def test_native_invoices_need_no_change(self):
        """Invoices ERPNext withheld on at submit, in date order, already match the plan."""
        supplier = self._supplier("_Test BNS Native", "AAACV1234J")
        frappe.db.set_value("Supplier", supplier, "tax_withholding_category", CAT_194Q)
        names = [self._pi(supplier, self._date(m, 1), amount, category=CAT_194Q)
                 for m, amount in ((4, 3000000), (5, 2500000), (6, 1000000))]
        self.assertEqual([self._tds(n) for n in names], [0, 500, 1000])
        plan = tds.plan_supplier_year(supplier, COMPANY, mode="supplier")
        self.assertEqual([d.name for d in plan.docs if d.action != "none"], [])


    def test_endpoints_used_by_the_ui(self):
        from business_needed_solutions.business_needed_solutions.page.bns_dashboard import bns_dashboard

        supplier = self._supplier("_Test BNS UI", "AAACW1234K")
        a = self._pi(supplier, self._date(5, 7), 20000)
        b = self._pi(supplier, self._date(5, 8), 40000)
        frappe.db.set_value("Supplier", supplier, "tax_withholding_category", CAT_194C)

        self.assertTrue(tds.get_tds_category_button(b)["show"])
        preview = tds.preview_tds_category_change(b, CAT_194C)
        frappe.as_json(preview)
        self.assertEqual(preview["summary"]["changes"], 1)
        result = tds.apply_tds_category_change(b, CAT_194C, token=preview["token"])
        self.assertEqual(result["status"], "done")
        self.assertEqual(self._tds(b), 400)  # 40,000 crosses the single 30,000 limit on its own

        items = frappe.as_json([{"purchase_invoice": a}])
        preview = bns_dashboard.preview_selected_pis_tds(items)
        frappe.as_json(preview)
        # a joins the category: b now carries the catch-up on both (60,000 x 1%)
        rows = {r["name"]: r for r in preview["plans"][0]["rows"]}
        self.assertEqual(rows[a]["action"], "flags")
        self.assertEqual(rows[b]["target_tds"], 600)
        bns_dashboard.fix_selected_pis_tds(items, token=preview["token"])
        self.assertEqual((self._tds(a), self._tds(b)), (0, 600))

        preview = tds.preview_supplier_tds(supplier, COMPANY)
        self.assertEqual(preview["summary"]["changes"], 0)
        with self.assertRaises(frappe.ValidationError):
            tds.redo_supplier_tds(supplier, COMPANY, token="stale")

        # a prior-year invoice never gets the button
        frappe.db.set_value("Purchase Invoice", a, "posting_date", frappe.utils.add_days(self.fy_start, -1))
        self.assertFalse(tds.get_tds_category_button(a)["show"])
        with self.assertRaises(frappe.ValidationError):
            tds.preview_tds_category_change(a, CAT_194C)

    def test_hand_added_tds_row_is_left_alone(self):
        """A TDS row on an invoice with apply_tds off is not removed by a change elsewhere."""
        supplier = self._supplier("_Test BNS Hand Row", "AAACX1234L")
        a = self._pi(supplier, self._date(5, 9), 50000)
        b = self._pi(supplier, self._date(5, 10), 50000)
        frappe.db.set_value("Supplier", supplier, "tax_withholding_category", CAT_194C)
        self._change(a, CAT_194C)
        frappe.db.set_value("Purchase Invoice", a, {"apply_tds": 0, "tax_withholding_category": None})
        plan = tds.plan_supplier_year(supplier, COMPANY, overrides={b: CAT_194C})
        rows = {d.name: d for d in plan.docs}
        self.assertEqual(rows[a].action, "none")
        self.assertEqual(rows[b].target_tds, 500)

