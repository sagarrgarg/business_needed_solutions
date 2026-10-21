"""
Unit tests for the BNS same party / company address submit guard.

Stubs BNS Settings and the Address GSTIN lookup, so the suite runs without real
documents or addresses.
"""

import unittest
from unittest.mock import patch

import frappe

from business_needed_solutions.business_needed_solutions.overrides import (
	same_address_validation as sav,
)

GURUKUL = (
	"Shed No- B-7, Gurukul Industrial Estate,<br>P O Amarnagar, Faridabad<br>\nFaridabad<br>\n"
	"Haryana, State Code: 06<br>\nPIN Code: 121003<br>\nIndia<br>\nGSTIN: 06AAJCK9474A1ZF<br>"
)
# The same premises typed differently, as v16's Text Editor stores it
GURUKUL_V16 = (
	"<p>SHED NO.B-7, GURUKUL INDUSTRIAL ESTATE, P.O AMARNAGAR, Faridabad,</p><p>Faridabad</p>"
	"<p>Haryana, State Code: 06</p><p>PIN Code: 121003</p><p>India</p><p>GSTIN: 06AAJCK9474A1ZF</p>"
)
URBAN_ESTATE = (
	"45/27C, Urban Estate<br>Faridabad<br>Haryana, State Code: 06<br>PIN Code: 121002<br>India<br>"
	"GSTIN: 06AAJCK9474A1ZF<br>"
)
KGOPL_GSTIN = "06AAJCK9474A1ZF"
SISTER_GSTIN = "06AANCR5086K1ZR"


class _Meta:
	def get_label(self, fieldname):
		return fieldname.replace("_", " ").title()


class _MockDoc:
	def __init__(self, **fields):
		self.__dict__.update(fields)
		self.meta = _Meta()

	def get(self, key, default=None):
		return self.__dict__.get(key, default)


def _selling(doctype="Delivery Note", **overrides):
	base = {
		"doctype": doctype,
		"is_return": 0,
		"customer_address": "KGOPL Urban Estate, Faridabad",
		"address_display": URBAN_ESTATE,
		"company_address": "KGOPL Gurukul, Faridabad",
		"company_address_display": GURUKUL,
		"billing_address_gstin": KGOPL_GSTIN,
		"company_gstin": KGOPL_GSTIN,
	}
	base.update(overrides)
	return _MockDoc(**base)


def _buying(doctype="Purchase Receipt", **overrides):
	base = {
		"doctype": doctype,
		"is_return": 0,
		"supplier_address": "KGOPL Gurukul, Faridabad",
		"address_display": GURUKUL,
		"billing_address": "KGOPL Urban Estate, Faridabad",
		"billing_address_display": URBAN_ESTATE,
		"supplier_gstin": KGOPL_GSTIN,
		"company_gstin": KGOPL_GSTIN,
	}
	base.update(overrides)
	return _MockDoc(**base)


class TestAddressComparison(unittest.TestCase):
	def test_same_text_matches(self):
		self.assertTrue(sav.is_same_address(GURUKUL, GURUKUL, 90)[0])

	def test_v16_html_and_punctuation_still_match(self):
		same, score = sav.is_same_address(GURUKUL, GURUKUL_V16, 90)
		self.assertTrue(same, score)

	def test_different_shed_number_is_a_different_address(self):
		# ~99% as text: only the number check keeps two sheds apart
		same, score = sav.is_same_address(GURUKUL, GURUKUL.replace("B-7", "B-8"), 90)
		self.assertGreater(score, 90)
		self.assertFalse(same)

	def test_different_branch_does_not_match(self):
		self.assertFalse(sav.is_same_address(GURUKUL, URBAN_ESTATE, 90)[0])

	def test_shorter_address_inside_longer_one_does_not_match(self):
		short = "Gurukul Industrial Estate, Faridabad<br>Haryana<br>PIN Code: 121003<br>India"
		self.assertFalse(sav.is_same_address(GURUKUL, short, 90)[0])

	def test_blank_text_never_matches(self):
		self.assertFalse(sav.is_same_address("", GURUKUL, 90)[0])
		self.assertFalse(sav.is_same_address(None, None, 90)[0])

	def test_normalize_drops_html_and_template_labels(self):
		self.assertEqual(
			sav.normalize_address(
				"<p>Plot 5, Sector 9</p><p>PIN Code: 121001</p><p>India</p><p>GSTIN: X</p>"
			),
			"plot 5 sector 9 121001",
		)

	def test_difflib_fallback_agrees(self):
		with patch.object(sav, "_fuzz", None):
			self.assertTrue(sav.is_same_address(GURUKUL, GURUKUL_V16, 90)[0])
			self.assertFalse(sav.is_same_address(GURUKUL, URBAN_ESTATE, 90)[0])


class TestSubmitGuard(unittest.TestCase):
	def setUp(self):
		self.settings = {"block_same_party_company_address": 1, "same_address_match_threshold": 90}
		self.address_gstin = {}
		patches = [
			patch.object(
				frappe.db,
				"get_single_value",
				side_effect=lambda dt, field, cache=False: self.settings.get(field),
			),
			patch.object(
				frappe.db, "get_value", side_effect=lambda dt, name, field: self.address_gstin.get(name)
			),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def assertBlocked(self, doc):
		with self.assertRaises(frappe.ValidationError):
			sav.validate_party_company_address_differ(doc)

	def assertAllowed(self, doc):
		sav.validate_party_company_address_differ(doc)

	def test_same_gstin_challan_between_branches_is_allowed(self):
		self.assertAllowed(_selling())

	def test_challan_from_gurukul_to_gurukul_is_blocked(self):
		self.assertBlocked(_selling(customer_address="KGOPL Gurukul, Faridabad", address_display=GURUKUL))

	def test_different_address_record_with_same_text_is_blocked(self):
		self.assertBlocked(_selling(customer_address="KGOPL Gurukul Copy", address_display=GURUKUL_V16))

	def test_all_six_doctypes_are_checked(self):
		for doctype in ("Sales Order", "Sales Invoice", "Delivery Note"):
			self.assertBlocked(
				_selling(doctype, customer_address="KGOPL Gurukul, Faridabad", address_display=GURUKUL)
			)
		for doctype in ("Purchase Order", "Purchase Invoice", "Purchase Receipt"):
			self.assertBlocked(
				_buying(
					doctype,
					billing_address="KGOPL Gurukul, Faridabad",
					billing_address_display=GURUKUL,
				)
			)

	def test_sister_concern_with_other_gstin_at_same_premises_is_allowed(self):
		self.assertAllowed(
			_selling(
				customer_address="GARG GLOBAL-Billing",
				address_display=GURUKUL_V16,
				billing_address_gstin=SISTER_GSTIN,
			)
		)

	def test_missing_party_gstin_falls_back_to_address_then_blocks(self):
		doc = _selling(customer_address="Walk-in Copy", address_display=GURUKUL, billing_address_gstin=None)
		self.assertBlocked(doc)
		self.address_gstin["Walk-in Copy"] = SISTER_GSTIN
		self.assertAllowed(doc)

	def test_returns_are_skipped(self):
		self.assertAllowed(
			_selling(
				"Sales Invoice",
				is_return=1,
				customer_address="KGOPL Gurukul, Faridabad",
				address_display=GURUKUL,
			)
		)

	def test_setting_off_allows_everything(self):
		self.settings["block_same_party_company_address"] = 0
		self.assertAllowed(_selling(customer_address="KGOPL Gurukul, Faridabad", address_display=GURUKUL))

	def test_blank_addresses_are_left_to_other_checks(self):
		self.assertAllowed(_selling(customer_address=None, address_display=None))

	def test_unset_threshold_uses_default(self):
		self.settings["same_address_match_threshold"] = 0
		self.assertBlocked(_selling(customer_address="KGOPL Gurukul Copy", address_display=GURUKUL_V16))

	def test_other_doctypes_are_ignored(self):
		self.assertAllowed(_MockDoc(doctype="Stock Entry", customer_address="X", company_address="X"))
