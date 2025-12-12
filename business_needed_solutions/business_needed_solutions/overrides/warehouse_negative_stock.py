"""
Business Needed Solutions - Warehouse-Level Negative Stock Restriction

This module provides warehouse-wise negative stock restriction that integrates
with ERPNext's existing "Allow Negative Stock" setting. The restriction applies
at Stock Ledger Entry level to cover all stock transactions (standard and custom)
while bypassing during reposting operations.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt
from erpnext.stock.stock_ledger import (
	NegativeStockError,
	get_previous_sle,
	get_future_sle_with_negative_qty,
	get_future_sle_with_negative_batch_qty,
	is_negative_with_precision,
)


def is_warehouse_negative_stock_disallowed(warehouse):
	"""
	Check if a warehouse disallows negative stock.
	
	Args:
		warehouse (str): Warehouse name
		
	Returns:
		bool: True if warehouse disallows negative stock, False otherwise
	"""
	if not warehouse:
		return False
	
	# Check if BNS feature is enabled
	if not _is_per_warehouse_negative_stock_enabled():
		return False
		
	# Check if ERPNext allows negative stock globally
	# If not, warehouse-level restriction doesn't apply (ERPNext handles it)
	allow_negative_stock = cint(
		frappe.db.get_single_value("Stock Settings", "allow_negative_stock", cache=True)
	)
	if not allow_negative_stock:
		return False
	
	# Check warehouse-level setting
	disallow = cint(
		frappe.db.get_value("Warehouse", warehouse, "bns_disallow_negative_stock", cache=True)
	)
	return bool(disallow)


def _is_per_warehouse_negative_stock_enabled():
	"""
	Check if per-warehouse negative stock disallow feature is enabled in BNS Settings.
	
	Returns:
		bool: True if feature is enabled, False otherwise
	"""
	return cint(
		frappe.db.get_single_value("BNS Settings", "enable_per_warehouse_negative_stock_disallow", cache=True)
	)


def should_apply_warehouse_restriction():
	"""
	Check if warehouse restriction should be applied.
	Skips restriction during reposting operations.
	
	Returns:
		bool: True if restriction should apply, False otherwise
	"""
	# Check if BNS feature is enabled
	if not _is_per_warehouse_negative_stock_enabled():
		return False
	
	# Skip during reposting
	if frappe.flags.get("through_repost_item_valuation"):
		return False
	
	# Only apply if ERPNext allows negative stock globally
	# (If ERPNext doesn't allow, it handles validation itself)
	allow_negative_stock = cint(
		frappe.db.get_single_value("Stock Settings", "allow_negative_stock", cache=True)
	)
	return bool(allow_negative_stock)


def validate_warehouse_negative_stock(args):
	"""
	Validate negative stock for a warehouse that disallows it.
	
	Args:
		args (dict): Stock Ledger Entry arguments containing:
			- item_code
			- warehouse
			- actual_qty
			- posting_date
			- posting_time
			- posting_datetime
			- voucher_type
			- voucher_no
			- batch_no (optional)
			- reserved_stock (optional)
			
	Raises:
		NegativeStockError: If negative stock would occur and warehouse disallows it
	"""
	if not should_apply_warehouse_restriction():
		return
	
	if not is_warehouse_negative_stock_disallowed(args.get("warehouse")):
		return
	
	# Skip if actual_qty is positive (incoming stock) - unless it's Stock Reconciliation
	if args.get("actual_qty", 0) >= 0 and args.get("voucher_type") != "Stock Reconciliation":
		return
	
	# Handle Stock Reconciliation special case
	if (
		args.get("voucher_type") == "Stock Reconciliation"
		and args.get("actual_qty", 0) < 0
		and args.get("serial_and_batch_bundle")
		and frappe.db.get_value("Stock Reconciliation Item", args.get("voucher_detail_no"), "qty") > 0
	):
		return
	
	# Ensure posting_datetime is set
	if not args.get("posting_datetime"):
		from erpnext.stock.utils import get_combine_datetime
		args["posting_datetime"] = get_combine_datetime(
			args.get("posting_date"), args.get("posting_time")
		)
	
	# Get previous SLE to check current quantity
	previous_sle = get_previous_sle(args)
	current_qty = flt(previous_sle.get("qty_after_transaction") or 0)
	actual_qty = flt(args.get("actual_qty", 0))
	
	# Get reserved stock if not provided in args
	reserved_stock = flt(args.get("reserved_stock", 0))
	if not reserved_stock and args.get("item_code") and args.get("warehouse"):
		# Try to get reserved stock from Bin
		from erpnext.stock.utils import get_or_make_bin
		bin_name = get_or_make_bin(args.get("item_code"), args.get("warehouse"))
		reserved_stock = flt(frappe.db.get_value("Bin", bin_name, "reserved_stock") or 0)
	
	# Calculate quantity after current transaction
	flt_precision = cint(frappe.db.get_default("float_precision")) or 2
	qty_after_current = flt(current_qty + actual_qty - reserved_stock, flt_precision)
	
	# Check if current transaction would cause negative stock
	if qty_after_current < 0 and abs(qty_after_current) > 0.0001:
		# Current transaction causes negative stock - throw error immediately
		warehouse_name = frappe.get_desk_link("Warehouse", args.get("warehouse"))
		message = _("{0} units of {1} needed in {2} on {3} {4} for {5} to complete this transaction.").format(
			abs(qty_after_current),
			frappe.get_desk_link("Item", args.get("item_code"), show_title_with_name=True),
			warehouse_name,
			args.get("posting_date"),
			args.get("posting_time"),
			frappe.get_desk_link(args.get("voucher_type"), args.get("voucher_no")),
		)
		# Add warehouse restriction context
		message += "<br><br>" + _("Note: While 'Allow Negative Stock' is enabled in Stock Settings, warehouse {0} has 'Disallow Negative Stock' enabled.").format(
			warehouse_name
		)
		frappe.throw(message, NegativeStockError, title=_("Insufficient Stock"))
	
	# Also check future SLEs to find the first negative occurrence (same as ERPNext logic)
	neg_sle = get_future_sle_with_negative_qty(args)
	
	if is_negative_with_precision(neg_sle):
		warehouse_name = frappe.get_desk_link("Warehouse", args.get("warehouse"))
		message = _("{0} units of {1} needed in {2} on {3} {4} for {5} to complete this transaction.").format(
			abs(neg_sle[0]["qty_after_transaction"]),
			frappe.get_desk_link("Item", args.get("item_code"), show_title_with_name=True),
			warehouse_name,
			neg_sle[0]["posting_date"],
			neg_sle[0]["posting_time"],
			frappe.get_desk_link(neg_sle[0]["voucher_type"], neg_sle[0]["voucher_no"]),
		)
		# Add warehouse restriction context
		message += "<br><br>" + _("Note: While 'Allow Negative Stock' is enabled in Stock Settings, warehouse {0} has 'Disallow Negative Stock' enabled.").format(
			warehouse_name
		)
		frappe.throw(message, NegativeStockError, title=_("Insufficient Stock"))
	
	# Check batch-level negative stock if batch_no is present
	if args.get("batch_no"):
		neg_batch_sle = get_future_sle_with_negative_batch_qty(args)
		if is_negative_with_precision(neg_batch_sle, is_batch=True):
			warehouse_name = frappe.get_desk_link("Warehouse", args.get("warehouse"))
			message = _(
				"{0} units of {1} needed in {2} on {3} {4} for {5} to complete this transaction."
			).format(
				abs(neg_batch_sle[0]["cumulative_total"]),
				frappe.get_desk_link("Batch", args.get("batch_no")),
				warehouse_name,
				neg_batch_sle[0]["posting_date"],
				neg_batch_sle[0]["posting_time"],
				frappe.get_desk_link(neg_batch_sle[0]["voucher_type"], neg_batch_sle[0]["voucher_no"]),
			)
			# Add warehouse restriction context
			message += "<br><br>" + _("Note: While 'Allow Negative Stock' is enabled in Stock Settings, warehouse {0} has 'Disallow Negative Stock' enabled.").format(
				warehouse_name
			)
			frappe.throw(message, NegativeStockError, title=_("Insufficient Stock for Batch"))


def apply_patches():
	"""
	Apply monkey patches to ERPNext stock ledger functions to add warehouse-level negative stock validation.
	
	This function should be called during app initialization (via hooks).
	"""
	import erpnext.stock.stock_ledger as stock_ledger_module
	
	# Ensure patches are only applied once
	if hasattr(stock_ledger_module, '_bns_warehouse_negative_stock_patched'):
		return
	
	stock_ledger_module._bns_warehouse_negative_stock_patched = True
	
	# Store original function if not already stored
	if not hasattr(stock_ledger_module, '_original_validate_negative_qty_in_future_sle'):
		stock_ledger_module._original_validate_negative_qty_in_future_sle = (
			stock_ledger_module.validate_negative_qty_in_future_sle
		)
	
	# Patch validate_negative_qty_in_future_sle
	def patched_validate(args, allow_negative_stock=False):
		"""Patched wrapper for validate_negative_qty_in_future_sle"""
		# First run original validation (this will return early if ERPNext doesn't allow negative stock)
		# But we still need to check warehouse restriction even if ERPNext allows globally
		try:
			stock_ledger_module._original_validate_negative_qty_in_future_sle(args, allow_negative_stock)
		except Exception:
			# If original validation throws, re-raise it
			raise
		
		# If we get here, ERPNext allows negative stock globally (or validation passed)
		# Now check warehouse-level restriction regardless of allow_negative_stock parameter
		# This ensures warehouse restriction is always checked when ERPNext allows negative stock
		validate_warehouse_negative_stock(args)
	
	stock_ledger_module.validate_negative_qty_in_future_sle = patched_validate
	
	# Verify patch was applied
	if stock_ledger_module.validate_negative_qty_in_future_sle != patched_validate:
		frappe.log_error("Failed to patch validate_negative_qty_in_future_sle", "BNS Warehouse Negative Stock")
	
	# Patch make_entry to validate BEFORE submitting SLE
	if not hasattr(stock_ledger_module, '_original_make_entry'):
		stock_ledger_module._original_make_entry = stock_ledger_module.make_entry
	
	def patched_make_entry(args, allow_negative_stock=False, via_landed_cost_voucher=False):
		"""Patched wrapper for make_entry that validates warehouse restriction before creating SLE"""
		# Validate warehouse restriction BEFORE creating the SLE
		# This catches negative stock at the source, not just in future SLEs
		if should_apply_warehouse_restriction():
			warehouse = args.get("warehouse")
			if warehouse and is_warehouse_negative_stock_disallowed(warehouse):
				# Prepare args for validation
				validation_args = {
					"item_code": args.get("item_code"),
					"warehouse": warehouse,
					"actual_qty": args.get("actual_qty", 0),
					"posting_date": args.get("posting_date"),
					"posting_time": args.get("posting_time"),
					"voucher_type": args.get("voucher_type"),
					"voucher_no": args.get("voucher_no"),
					"batch_no": args.get("batch_no"),
					"reserved_stock": args.get("reserved_stock"),
					"voucher_detail_no": args.get("voucher_detail_no"),
					"serial_and_batch_bundle": args.get("serial_and_batch_bundle"),
				}
				# Validate - this will throw if negative stock would occur
				validate_warehouse_negative_stock(validation_args)
		
		# Call original make_entry
		return stock_ledger_module._original_make_entry(args, allow_negative_stock, via_landed_cost_voucher)
	
	stock_ledger_module.make_entry = patched_make_entry
	
	# Patch update_entries_after.validate_negative_stock method
	if not hasattr(stock_ledger_module.update_entries_after, '_original_validate_negative_stock'):
		stock_ledger_module.update_entries_after._original_validate_negative_stock = (
			stock_ledger_module.update_entries_after.validate_negative_stock
		)
	
	def patched_method(self, sle):
		"""Patched wrapper for update_entries_after.validate_negative_stock"""
		# Original validation logic
		diff = self.wh_data.qty_after_transaction + flt(sle.actual_qty) - flt(self.reserved_stock)
		diff = flt(diff, self.flt_precision)
		
		# Check if negative stock would occur
		if diff < 0 and abs(diff) > 0.0001:
			# Check if ERPNext allows negative stock
			if not self.allow_negative_stock:
				# ERPNext doesn't allow - use original behavior (add exception)
				exc = sle.copy().update({"diff": diff})
				self.exceptions.setdefault(sle.warehouse, []).append(exc)
				return False
			
			# ERPNext allows negative stock - check warehouse restriction
			if should_apply_warehouse_restriction():
				if is_warehouse_negative_stock_disallowed(sle.warehouse):
					# Warehouse disallows negative stock - add exception
					exc = sle.copy().update({"diff": diff})
					self.exceptions.setdefault(sle.warehouse, []).append(exc)
					return False
		
		# No negative stock or allowed - return True
		return True
	
	stock_ledger_module.update_entries_after.validate_negative_stock = patched_method


def validate_sle_warehouse_negative_stock(doc, method=None):
	"""
	Validate warehouse negative stock restriction when Stock Ledger Entry is validated.
	
	This is called as a doc_event hook on Stock Ledger Entry validate.
	
	Args:
		doc: Stock Ledger Entry document
		method: Method name (validate)
	"""
	if doc.is_cancelled:
		return
	
	if not should_apply_warehouse_restriction():
		return
	
	if not is_warehouse_negative_stock_disallowed(doc.warehouse):
		return
	
	# Skip if actual_qty is positive (incoming stock) - unless it's Stock Reconciliation
	if doc.actual_qty >= 0 and doc.voucher_type != "Stock Reconciliation":
		return
	
	# Handle Stock Reconciliation special case
	if (
		doc.voucher_type == "Stock Reconciliation"
		and doc.actual_qty < 0
		and doc.serial_and_batch_bundle
		and frappe.db.get_value("Stock Reconciliation Item", doc.voucher_detail_no, "qty") > 0
	):
		return
	
	# Prepare args for validation
	args = {
		"item_code": doc.item_code,
		"warehouse": doc.warehouse,
		"actual_qty": doc.actual_qty,
		"posting_date": doc.posting_date,
		"posting_time": doc.posting_time,
		"posting_datetime": doc.posting_datetime,
		"voucher_type": doc.voucher_type,
		"voucher_no": doc.voucher_no,
		"batch_no": doc.batch_no,
		"voucher_detail_no": doc.voucher_detail_no,
		"serial_and_batch_bundle": doc.serial_and_batch_bundle,
	}
	
	# Get reserved stock from Bin
	from erpnext.stock.utils import get_or_make_bin
	bin_name = get_or_make_bin(doc.item_code, doc.warehouse)
	args["reserved_stock"] = flt(frappe.db.get_value("Bin", bin_name, "reserved_stock") or 0)
	
	# Validate - this will throw if negative stock would occur
	validate_warehouse_negative_stock(args)
