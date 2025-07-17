# Copyright (c) 2025, Sagar Ratan Garg and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe import _
from business_needed_solutions.business_needed_solutions.overrides.warehouse_validation import validate_warehouse_restriction
from business_needed_solutions.business_needed_solutions.overrides.auto_transit_validation import auto_set_transit_for_material_transfer
from business_needed_solutions.business_needed_solutions.overrides.warehouse_filtering import validate_warehouse_filtering


class TestBNSSettings(FrappeTestCase):
	def setUp(self):
		"""Set up test data"""
		# Create test warehouses
		self.source_warehouse = frappe.get_doc({
			"doctype": "Warehouse",
			"warehouse_name": "Test Source Warehouse",
			"company": "Test Company"
		}).insert()
		
		self.target_warehouse = frappe.get_doc({
			"doctype": "Warehouse", 
			"warehouse_name": "Test Target Warehouse",
			"company": "Test Company"
		}).insert()
		
		# Create test item
		self.test_item = frappe.get_doc({
			"doctype": "Item",
			"item_code": "TEST-ITEM-001",
			"item_name": "Test Item",
			"item_group": "Products",
			"stock_uom": "Nos"
		}).insert()
		
		# Create BNS Settings if not exists
		if not frappe.db.exists("BNS Settings"):
			frappe.get_doc({
				"doctype": "BNS Settings",
				"discount_type": "Single"
			}).insert()
	
	def tearDown(self):
		"""Clean up test data"""
		# Delete test documents
		frappe.delete_doc("Warehouse", self.source_warehouse.name, force=True)
		frappe.delete_doc("Warehouse", self.target_warehouse.name, force=True)
		frappe.delete_doc("Item", self.test_item.name, force=True)
	
	def test_warehouse_restriction_disabled(self):
		"""Test that warehouse restriction is not enforced when setting is disabled"""
		# Disable the restriction
		bns_settings = frappe.get_doc("BNS Settings")
		bns_settings.restrict_same_warehouse = 0
		bns_settings.save()
		
		# Create stock entry with same warehouse
		stock_entry = frappe.get_doc({
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": "Test Company",
			"from_warehouse": self.source_warehouse.name,
			"to_warehouse": self.source_warehouse.name,  # Same warehouse
			"items": [{
				"item_code": self.test_item.name,
				"qty": 1,
				"s_warehouse": self.source_warehouse.name,
				"t_warehouse": self.source_warehouse.name,  # Same warehouse
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"transfer_qty": 1
			}]
		})
		
		# Should not raise an exception
		try:
			validate_warehouse_restriction(stock_entry, "validate")
			# If we reach here, no exception was raised
			self.assertTrue(True)
		except Exception as e:
			self.fail(f"Exception raised when restriction is disabled: {e}")
	
	def test_warehouse_restriction_enabled(self):
		"""Test that warehouse restriction is enforced when setting is enabled"""
		# Enable the restriction
		bns_settings = frappe.get_doc("BNS Settings")
		bns_settings.restrict_same_warehouse = 1
		bns_settings.save()
		
		# Create stock entry with same warehouse
		stock_entry = frappe.get_doc({
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": "Test Company",
			"from_warehouse": self.source_warehouse.name,
			"to_warehouse": self.source_warehouse.name,  # Same warehouse
			"items": [{
				"item_code": self.test_item.name,
				"qty": 1,
				"s_warehouse": self.source_warehouse.name,
				"t_warehouse": self.source_warehouse.name,  # Same warehouse
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"transfer_qty": 1
			}]
		})
		
		# Should raise an exception
		with self.assertRaises(frappe.ValidationError) as context:
			validate_warehouse_restriction(stock_entry, "validate")
		
		# Check that the error message contains the expected text
		self.assertIn("Source and target warehouse cannot be same", str(context.exception))
	
	def test_warehouse_restriction_different_warehouses(self):
		"""Test that validation passes when source and target warehouses are different"""
		# Enable the restriction
		bns_settings = frappe.get_doc("BNS Settings")
		bns_settings.restrict_same_warehouse = 1
		bns_settings.save()
		
		# Create stock entry with different warehouses
		stock_entry = frappe.get_doc({
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": "Test Company",
			"from_warehouse": self.source_warehouse.name,
			"to_warehouse": self.target_warehouse.name,  # Different warehouse
			"items": [{
				"item_code": self.test_item.name,
				"qty": 1,
				"s_warehouse": self.source_warehouse.name,
				"t_warehouse": self.target_warehouse.name,  # Different warehouse
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"transfer_qty": 1
			}]
		})
		
		# Should not raise an exception
		try:
			validate_warehouse_restriction(stock_entry, "validate")
			# If we reach here, no exception was raised
			self.assertTrue(True)
		except Exception as e:
			self.fail(f"Exception raised when warehouses are different: {e}")
	
	def test_auto_transit_disabled(self):
		"""Test that auto-transit is not set when setting is disabled"""
		# Disable the auto-transit setting
		bns_settings = frappe.get_doc("BNS Settings")
		bns_settings.auto_transit_material_transfer = 0
		bns_settings.save()
		
		# Create stock entry with Material Transfer
		stock_entry = frappe.get_doc({
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": "Test Company",
			"from_warehouse": self.source_warehouse.name,
			"to_warehouse": self.target_warehouse.name,
			"add_to_transit": 0,  # Explicitly set to 0
			"items": [{
				"item_code": self.test_item.name,
				"qty": 1,
				"s_warehouse": self.source_warehouse.name,
				"t_warehouse": self.target_warehouse.name,
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"transfer_qty": 1
			}]
		})
		
		# Call the auto-transit function
		auto_set_transit_for_material_transfer(stock_entry, "validate")
		
		# Should remain 0 (not changed)
		self.assertEqual(stock_entry.add_to_transit, 0)
	
	def test_auto_transit_enabled(self):
		"""Test that auto-transit is set when setting is enabled"""
		# Enable the auto-transit setting
		bns_settings = frappe.get_doc("BNS Settings")
		bns_settings.auto_transit_material_transfer = 1
		bns_settings.save()
		
		# Create stock entry with Material Transfer
		stock_entry = frappe.get_doc({
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": "Test Company",
			"from_warehouse": self.source_warehouse.name,
			"to_warehouse": self.target_warehouse.name,
			"add_to_transit": 0,  # Explicitly set to 0
			"items": [{
				"item_code": self.test_item.name,
				"qty": 1,
				"s_warehouse": self.source_warehouse.name,
				"t_warehouse": self.target_warehouse.name,
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"transfer_qty": 1
			}]
		})
		
		# Call the auto-transit function
		auto_set_transit_for_material_transfer(stock_entry, "validate")
		
		# Should be set to 1
		self.assertEqual(stock_entry.add_to_transit, 1)
	
	def test_auto_transit_not_applicable(self):
		"""Test that auto-transit is not set for non-Material Transfer entries"""
		# Enable the auto-transit setting
		bns_settings = frappe.get_doc("BNS Settings")
		bns_settings.auto_transit_material_transfer = 1
		bns_settings.save()
		
		# Create stock entry with Material Issue (not Material Transfer)
		stock_entry = frappe.get_doc({
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Issue",
			"purpose": "Material Issue",
			"company": "Test Company",
			"from_warehouse": self.source_warehouse.name,
			"add_to_transit": 0,  # Explicitly set to 0
			"items": [{
				"item_code": self.test_item.name,
				"qty": 1,
				"s_warehouse": self.source_warehouse.name,
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"transfer_qty": 1
			}]
		})
		
		# Call the auto-transit function
		auto_set_transit_for_material_transfer(stock_entry, "validate")
		
		# Should remain 0 (not changed)
		self.assertEqual(stock_entry.add_to_transit, 0)
	
	def test_auto_transit_outgoing_stock_entry(self):
		"""Test that auto-transit is not set for outgoing stock entries"""
		# Enable the auto-transit setting
		bns_settings = frappe.get_doc("BNS Settings")
		bns_settings.auto_transit_material_transfer = 1
		bns_settings.save()
		
		# Create stock entry with outgoing_stock_entry set
		stock_entry = frappe.get_doc({
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": "Test Company",
			"from_warehouse": self.source_warehouse.name,
			"to_warehouse": self.target_warehouse.name,
			"outgoing_stock_entry": "STE-TEST-001",  # Set outgoing stock entry
			"add_to_transit": 0,  # Explicitly set to 0
			"items": [{
				"item_code": self.test_item.name,
				"qty": 1,
				"s_warehouse": self.source_warehouse.name,
				"t_warehouse": self.target_warehouse.name,
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"transfer_qty": 1
			}]
		})
		
		# Call the auto-transit function
		auto_set_transit_for_material_transfer(stock_entry, "validate")
		
		# Should remain 0 (not changed)
		self.assertEqual(stock_entry.add_to_transit, 0)
	
	def test_warehouse_filtering_disabled(self):
		"""Test that warehouse filtering is not applied when setting is disabled"""
		# Disable the auto-transit setting
		bns_settings = frappe.get_doc("BNS Settings")
		bns_settings.auto_transit_material_transfer = 0
		bns_settings.save()
		
		# Create stock entry with non-transit target warehouse (should be allowed when disabled)
		stock_entry = frappe.get_doc({
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": "Test Company",
			"from_warehouse": self.source_warehouse.name,
			"to_warehouse": self.target_warehouse.name,  # Non-transit warehouse
			"items": [{
				"item_code": self.test_item.name,
				"qty": 1,
				"s_warehouse": self.source_warehouse.name,
				"t_warehouse": self.target_warehouse.name,  # Non-transit warehouse
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"transfer_qty": 1
			}]
		})
		
		# Should not raise an exception
		try:
			validate_warehouse_filtering(stock_entry, "validate")
			# If we reach here, no exception was raised
			self.assertTrue(True)
		except Exception as e:
			self.fail(f"Exception raised when warehouse filtering is disabled: {e}")
	
	def test_warehouse_filtering_new_transfer_transit_target(self):
		"""Test that new Material Transfer entries require transit target warehouse"""
		# Enable the auto-transit setting
		bns_settings = frappe.get_doc("BNS Settings")
		bns_settings.auto_transit_material_transfer = 1
		bns_settings.save()
		
		# Create stock entry with non-transit target warehouse (should fail)
		stock_entry = frappe.get_doc({
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": "Test Company",
			"from_warehouse": self.source_warehouse.name,
			"to_warehouse": self.target_warehouse.name,  # Non-transit warehouse
			"items": [{
				"item_code": self.test_item.name,
				"qty": 1,
				"s_warehouse": self.source_warehouse.name,
				"t_warehouse": self.target_warehouse.name,  # Non-transit warehouse
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"transfer_qty": 1
			}]
		})
		
		# Should raise an exception
		with self.assertRaises(frappe.ValidationError) as context:
			validate_warehouse_filtering(stock_entry, "validate")
		
		# Check that the error message contains the expected text
		self.assertIn("must be a transit warehouse", str(context.exception))
	
	def test_warehouse_filtering_new_transfer_transit_source(self):
		"""Test that new Material Transfer entries cannot have transit source warehouse"""
		# Enable the auto-transit setting
		bns_settings = frappe.get_doc("BNS Settings")
		bns_settings.auto_transit_material_transfer = 1
		bns_settings.save()
		
		# Create stock entry with transit source warehouse (should fail)
		stock_entry = frappe.get_doc({
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": "Test Company",
			"from_warehouse": self.transit_warehouse.name,  # Transit warehouse
			"to_warehouse": self.transit_warehouse.name,
			"items": [{
				"item_code": self.test_item.name,
				"qty": 1,
				"s_warehouse": self.transit_warehouse.name,  # Transit warehouse
				"t_warehouse": self.transit_warehouse.name,
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"transfer_qty": 1
			}]
		})
		
		# Should raise an exception
		with self.assertRaises(frappe.ValidationError) as context:
			validate_warehouse_filtering(stock_entry, "validate")
		
		# Check that the error message contains the expected text
		self.assertIn("cannot be a transit warehouse", str(context.exception))
	
	def test_warehouse_filtering_receipt_from_transit(self):
		"""Test that receipt from transit entries require transit source and specific target"""
		# Enable the auto-transit setting
		bns_settings = frappe.get_doc("BNS Settings")
		bns_settings.auto_transit_material_transfer = 1
		bns_settings.save()
		
		# Create outgoing stock entry with custom_for_which_warehouse_to_transfer
		outgoing_entry = frappe.get_doc({
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": "Test Company",
			"from_warehouse": self.source_warehouse.name,
			"to_warehouse": self.transit_warehouse.name,
			"custom_for_which_warehouse_to_transfer": self.target_warehouse.name,
			"items": [{
				"item_code": self.test_item.name,
				"qty": 1,
				"s_warehouse": self.source_warehouse.name,
				"t_warehouse": self.transit_warehouse.name,
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"transfer_qty": 1
			}]
		}).insert()
		
		# Create receipt stock entry
		receipt_entry = frappe.get_doc({
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": "Test Company",
			"from_warehouse": self.transit_warehouse.name,  # Transit warehouse
			"to_warehouse": self.target_warehouse.name,  # Should match outgoing entry's custom field
			"outgoing_stock_entry": outgoing_entry.name,
			"items": [{
				"item_code": self.test_item.name,
				"qty": 1,
				"s_warehouse": self.transit_warehouse.name,  # Transit warehouse
				"t_warehouse": self.target_warehouse.name,  # Should match outgoing entry's custom field
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"transfer_qty": 1
			}]
		})
		
		# Should not raise an exception
		try:
			validate_warehouse_filtering(receipt_entry, "validate")
			# If we reach here, no exception was raised
			self.assertTrue(True)
		except Exception as e:
			self.fail(f"Exception raised for valid receipt from transit: {e}")
		
		# Clean up
		frappe.delete_doc("Stock Entry", outgoing_entry.name, force=True)
