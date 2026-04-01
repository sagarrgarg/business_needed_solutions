"""
Business Needed Solutions - Negative Stock Override

Allows designated roles to submit stock documents with negative stock even when
ERPNext's Stock Settings has 'Allow Negative Stock' turned OFF. A cutoff date
controls the window: transactions posted on or before the cutoff are eligible
for the override; transactions after the cutoff follow normal Stock Settings.

This is the inverse of the warehouse_negative_stock module (which restricts
specific warehouses when negative stock is globally allowed). The two features
are orthogonal and compose correctly.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate


def should_override_negative_stock(posting_date=None):
	"""
	Determine whether negative stock should be allowed for the current user
	and the given posting_date, based on BNS Settings.

	Args:
		posting_date (str|datetime.date|None): Document posting date.

	Returns:
		bool: True if BNS override should allow negative stock.
	"""
	if frappe.flags.get("through_repost_item_valuation"):
		return False

	if not cint(
		frappe.db.get_single_value("BNS Settings", "allow_negative_stock_override", cache=True)
	):
		return False

	if _is_negative_stock_already_allowed():
		return False

	cutoff = frappe.db.get_single_value("BNS Settings", "negative_stock_cutoff_date", cache=True)
	if cutoff and posting_date:
		if getdate(posting_date) > getdate(cutoff):
			return False

	override_roles = _get_override_roles()
	if not override_roles:
		return False

	user_roles = set(frappe.get_roles(frappe.session.user))
	return bool(override_roles & user_roles)


def _is_negative_stock_already_allowed():
	"""Return True if ERPNext already allows negative stock globally."""
	return cint(
		frappe.db.get_single_value("Stock Settings", "allow_negative_stock", cache=True)
	)


def _get_override_roles():
	"""
	Fetch the set of roles configured in BNS Settings for negative stock override.
	Result is cached per-request via frappe.flags.

	Returns:
		set: Role names.
	"""
	cache_key = "_bns_negative_stock_override_roles"
	if cache_key not in frappe.flags:
		roles = frappe.get_all(
			"Has Role",
			filters={
				"parenttype": "BNS Settings",
				"parentfield": "negative_stock_override_roles",
			},
			pluck="role",
		)
		frappe.flags[cache_key] = set(roles)
	return frappe.flags[cache_key]


def apply_patches():
	"""
	Monkey-patch ERPNext stock ledger functions to support BNS negative stock
	override. Called via after_app_init hook.

	Patches:
		1. make_sl_entries – sets allow_negative_stock=True before SLEs are
		   created, propagating the override through the entire chain.
		2. update_entries_after.__init__ – catches the reposting /
		   direct-invocation path where make_sl_entries is not used.
	"""
	import erpnext.stock.stock_ledger as sl

	if getattr(sl, "_bns_neg_stock_override_patched", False):
		return
	sl._bns_neg_stock_override_patched = True

	_patch_make_sl_entries(sl)
	_patch_update_entries_after_init(sl)


def _patch_make_sl_entries(sl):
	"""Wrap make_sl_entries to inject allow_negative_stock when BNS override applies."""
	original = sl.make_sl_entries

	def patched_make_sl_entries(sl_entries, allow_negative_stock=False, via_landed_cost_voucher=False):
		if not allow_negative_stock and sl_entries:
			posting_date = sl_entries[0].get("posting_date") if sl_entries else None
			if should_override_negative_stock(posting_date):
				allow_negative_stock = True
		return original(sl_entries, allow_negative_stock, via_landed_cost_voucher)

	sl.make_sl_entries = patched_make_sl_entries


def _patch_update_entries_after_init(sl):
	"""Wrap update_entries_after.__init__ to override self.allow_negative_stock."""
	original_init = sl.update_entries_after.__init__

	def patched_init(self, args, allow_zero_rate=False, allow_negative_stock=None,
					 via_landed_cost_voucher=False, verbose=1):
		original_init(self, args, allow_zero_rate, allow_negative_stock,
					  via_landed_cost_voucher, verbose)
		if not self.allow_negative_stock:
			posting_date = self.args.get("posting_date")
			if should_override_negative_stock(posting_date):
				self.allow_negative_stock = True

	sl.update_entries_after.__init__ = patched_init
