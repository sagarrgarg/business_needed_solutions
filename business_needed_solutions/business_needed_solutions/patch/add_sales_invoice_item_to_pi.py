# Copyright (c) 2026, Sagar Garg and Contributors
# License: GNU General Public License v3. See license.txt

"""Add `sales_invoice_item` to Purchase Invoice Item and backfill existing rows.

The SI->PI internal-transfer leg needs a per-row link to the source Sales Invoice
Item so batch/serial auto-fill (ensure_internal_batch_bundle_mapping) and the 1-to-1
parity check can resolve the source. The field previously existed only on Purchase
Receipt Item. Fixtures sync runs later in `migrate`, so this patch creates the field
first, then backfills historical internal PI rows by matching each row to its source
SI row on (item_code, qty, rate).
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import flt


def execute():
	# 1) Ensure the row-link field exists before we backfill (fixtures sync later in migrate).
	if not frappe.db.exists("Custom Field", "Purchase Invoice Item-sales_invoice_item"):
		create_custom_fields(
			{
				"Purchase Invoice Item": [
					{
						"fieldname": "sales_invoice_item",
						"label": "Sales Invoice Item",
						"fieldtype": "Data",
						"insert_after": "pr_detail",
						"read_only": 1,
						"no_copy": 1,
						"hidden": 1,
						"print_hide": 1,
						"module": "BNS Branch Accounting",
					}
				]
			},
			ignore_validate=True,
		)

	# 2) Backfill existing internal Purchase Invoices whose source is a Sales Invoice.
	pis = frappe.get_all(
		"Purchase Invoice",
		filters={"bns_inter_company_reference": ["is", "set"], "docstatus": 1},
		fields=["name", "bns_inter_company_reference"],
	)

	filled = 0
	for pi in pis:
		si_name = (pi.bns_inter_company_reference or "").strip()
		# The reference may point at a PR (PR->PI leg); only SI-sourced PIs apply here.
		if not si_name or not frappe.db.exists("Sales Invoice", si_name):
			continue

		si_rows = frappe.get_all(
			"Sales Invoice Item",
			filters={"parent": si_name},
			fields=["name", "item_code", "qty", "rate"],
			order_by="idx",
		)
		pool = {}
		for r in si_rows:
			pool.setdefault(_key(r), []).append(r.name)

		pi_rows = frappe.get_all(
			"Purchase Invoice Item",
			filters={"parent": pi.name, "sales_invoice_item": ["in", ["", None]]},
			fields=["name", "item_code", "qty", "rate"],
			order_by="idx",
		)
		for r in pi_rows:
			candidates = pool.get(_key(r))
			if candidates:
				frappe.db.set_value(
					"Purchase Invoice Item", r.name, "sales_invoice_item", candidates.pop(0), update_modified=False
				)
				filled += 1

	frappe.db.commit()
	frappe.logger().info(f"add_sales_invoice_item_to_pi: linked {filled} PI rows across {len(pis)} internal PIs")


def _key(row):
	return (row.item_code, round(flt(row.qty), 3), round(flt(row.rate), 3))
