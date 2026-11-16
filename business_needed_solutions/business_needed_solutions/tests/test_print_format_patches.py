# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
Old BNS print formats still chosen in BNS Settings or as a doctype default must stay
printable: they are pointed at the current format (a disabled format cannot print).

    bench --site <site> run-tests --skip-before-tests --module \
        business_needed_solutions.business_needed_solutions.tests.test_print_format_patches
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from business_needed_solutions.business_needed_solutions.patch import (
	reenable_old_print_formats_still_in_use as reenable,
)
from business_needed_solutions.business_needed_solutions.patch import (
	remove_old_print_format_versions as remove,
)

OLD, NEW = "BNS SI Dynamic V1", "BNS SI Dynamic V2"


class TestOldPrintFormats(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._commit = patch.object(frappe.db, "commit")
		self._commit.start()
		if not frappe.db.exists("Print Format", NEW):
			self.skipTest(f"{NEW} not installed on this site")
		frappe.db.set_value("Print Format", NEW, "disabled", 0)
		if not frappe.db.exists("Print Format", OLD):
			frappe.get_doc({
				"doctype": "Print Format", "name": OLD, "doc_type": "Sales Invoice", "module": "Accounts",
				"custom_format": 1, "print_format_type": "Jinja", "html": "<p>old</p>", "standard": "No",
			}).insert(ignore_permissions=True)
		settings = frappe.get_single("BNS Settings")
		settings.set("print_format", [{"doctype_map": "Sales Invoice", "print_format": OLD}])
		settings.save(ignore_permissions=True)
		frappe.make_property_setter({
			"doctype": "Sales Invoice", "doctype_or_field": "DocType", "property": "default_print_format",
			"value": OLD, "property_type": "Data",
		})

	def tearDown(self):
		self._commit.stop()
		frappe.db.rollback()

	def _default(self):
		return frappe.db.get_value(
			"Property Setter", {"doc_type": "Sales Invoice", "property": "default_print_format"}, "value"
		)

	def _rows(self):
		return frappe.get_all("BNS Settings Print Format", filters={"doctype_map": "Sales Invoice"}, pluck="print_format")

	def test_disabled_format_in_use_is_pointed_at_the_current_one(self):
		frappe.db.set_value("Print Format", OLD, "disabled", 1)  # what the old patch left
		reenable.execute()
		self.assertEqual(self._rows(), [NEW])
		self.assertEqual(self._default(), NEW)

	def test_without_a_replacement_the_old_format_is_enabled_again(self):
		frappe.db.set_value("Print Format", OLD, "disabled", 1)
		frappe.db.set_value("Print Format", NEW, "disabled", 1)
		reenable.execute()
		self.assertEqual(frappe.db.get_value("Print Format", OLD, "disabled"), 0)
		self.assertEqual(self._rows(), [OLD])

	def test_removal_repoints_before_deleting(self):
		remove.execute()
		self.assertFalse(frappe.db.exists("Print Format", OLD))
		self.assertEqual(self._rows(), [NEW])
		self.assertEqual(self._default(), NEW)

	def test_duplicate_row_is_dropped_not_doubled(self):
		settings = frappe.get_single("BNS Settings")
		settings.append("print_format", {"doctype_map": "Sales Invoice", "print_format": NEW})
		settings.save(ignore_permissions=True)
		frappe.db.set_value("Print Format", OLD, "disabled", 1)
		reenable.execute()
		self.assertEqual(self._rows(), [NEW])
