# Copyright (c) 2025, Sagar Ratan Garg and Contributors
# See license.txt

"""
BNS Settings doctype tests.

Note: Tests for warehouse_validation, auto_transit_validation, and warehouse_filtering
were removed because those modules no longer exist. The corresponding BNS Settings
fields (restrict_same_warehouse, auto_transit_material_transfer) were never implemented
or have been removed.
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestBNSSettings(FrappeTestCase):
	def test_bns_settings_loads(self):
		"""Verify BNS Settings can be loaded without error."""
		doc = frappe.get_single("BNS Settings")
		self.assertIsNotNone(doc)
		self.assertTrue(hasattr(doc, "discount_type"))
