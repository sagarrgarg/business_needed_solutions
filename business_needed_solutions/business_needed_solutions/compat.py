# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""
Read core settings and fields whose home changed between ERPNext v15 and v16.

Each helper detects what the installed version provides and, on v15, returns exactly
what the code read before, so v15 behaviour is unchanged.
"""

import frappe


def get_frozen_accounts_settings(company=None):
	"""(frozen_till_date, role_allowed_to_post_in_frozen_period) for ``company``.

	ERPNext v15 keeps one site-wide setting on Accounts Settings (``acc_frozen_upto``,
	``frozen_accounts_modifier``). v16 moved it to each Company
	(``accounts_frozen_till_date``, ``role_allowed_for_frozen_entries``; patch
	v16_0/migrate_account_freezing_settings_to_company copies the old values over).
	"""
	if frappe.get_meta("Accounts Settings").has_field("acc_frozen_upto"):
		return (
			frappe.db.get_single_value("Accounts Settings", "acc_frozen_upto"),
			frappe.db.get_single_value("Accounts Settings", "frozen_accounts_modifier"),
		)
	if not company or not frappe.get_meta("Company").has_field("accounts_frozen_till_date"):
		return None, None
	values = frappe.get_cached_value(
		"Company", company, ["accounts_frozen_till_date", "role_allowed_for_frozen_entries"]
	)
	return tuple(values) if values else (None, None)


def is_secondary_output_row(row):
	"""True for a Stock Entry row that is a by-output rather than a consumed component.

	ERPNext v15 marks scrap rows with ``is_scrap_item``. v16 replaced it with
	``secondary_item_type`` (Co-Product, By-Product, Scrap, Additional Finished Good;
	erpnext#53975); rows migrated from v15 scrap carry only ``valuation_type``, and v16's own
	stock entry code tests ``secondary_item_type or valuation_type``. ``row.get`` returns None
	for fields the installed version lacks, so v15 reads ``is_scrap_item`` alone.
	"""
	return bool(
		row.get("is_scrap_item") or row.get("secondary_item_type") or row.get("valuation_type")
	)


def asset_purchase_amount_field():
	"""Asset's purchase value field.

	``gross_purchase_amount`` on ERPNext v15; v16 renamed it ``net_purchase_amount`` (patch
	v15_0/rename_gross_purchase_amount_to_net_purchase_amount, a pure rename).
	"""
	if frappe.get_meta("Asset").has_field("gross_purchase_amount"):
		return "gross_purchase_amount"
	return "net_purchase_amount"
