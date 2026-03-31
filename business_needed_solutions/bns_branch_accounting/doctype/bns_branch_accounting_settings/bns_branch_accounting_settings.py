# Copyright (c) 2026, BNS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class BNSBranchAccountingSettings(Document):
	"""BNS Branch Accounting Settings - Account mapping for internal transfers."""

	def validate(self):
		self._migrate_legacy_cutoff()
		self._validate_cutoff_dependency()

	def _migrate_legacy_cutoff(self):
		"""One-time migration: copy old Date field into new FY Link fields."""
		if self.internal_transfer_cutoff_fy or self.accounting_rewrite_cutoff_fy:
			return
		old_date = self.internal_validation_cutoff_date
		if not old_date:
			return
		try:
			from erpnext.accounts.utils import get_fiscal_year
			fy_info = get_fiscal_year(getdate(old_date))
			fy_name = fy_info[0] if fy_info else None
		except Exception:
			frappe.logger().warning(
				"Could not resolve Fiscal Year for legacy cutoff date %s: migration skipped.",
				old_date,
			)
			fy_name = None
		if fy_name and frappe.db.exists("Fiscal Year", fy_name):
			self.internal_transfer_cutoff_fy = fy_name
			self.accounting_rewrite_cutoff_fy = fy_name

	def _validate_cutoff_dependency(self):
		"""Accounting Rewrite requires Internal Transfer to be set first,
		and its FY start must not precede the Internal Transfer FY start."""
		if self.accounting_rewrite_cutoff_fy and not self.internal_transfer_cutoff_fy:
			frappe.throw(
				_("Accounting Rewrite Cutoff cannot be set without Internal Transfer Cutoff."),
				title=_("Invalid Cutoff Configuration"),
			)
		if self.internal_transfer_cutoff_fy and self.accounting_rewrite_cutoff_fy:
			transfer_start = frappe.db.get_value(
				"Fiscal Year", self.internal_transfer_cutoff_fy, "year_start_date"
			)
			accounting_start = frappe.db.get_value(
				"Fiscal Year", self.accounting_rewrite_cutoff_fy, "year_start_date"
			)
			if transfer_start and accounting_start and getdate(accounting_start) < getdate(transfer_start):
				frappe.throw(
					_("Accounting Rewrite Cutoff ({0}) cannot be earlier than Internal Transfer Cutoff ({1}).").format(
						self.accounting_rewrite_cutoff_fy, self.internal_transfer_cutoff_fy
					),
					title=_("Invalid Cutoff Configuration"),
				)

