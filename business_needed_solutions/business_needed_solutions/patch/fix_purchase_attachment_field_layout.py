# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
Put the supplier-invoice / e-Waybill attachment fields back on screen.

Frappe v16 applies ``insert_after`` only to custom fields. BNS moved two standard
Purchase Invoice fields (``bill_date``, ``column_break_15``) with ``insert_after``
property setters and hid ``column_break_15``. On v16 those setters are ignored,
so Supplier Invoice Date, e-Waybill Date and the e-Waybill attachment sat in the
hidden column. Purchase Receipt has no ``bill_no``/``bill_date`` at all, so its
attachment fields fell to the end of the form (Connections tab).

The layout now uses custom fields only, so it is the same on v15 and v16:

    Purchase Invoice > Supplier Invoice section
        bill_no, e-Waybill No, Transport Mode | bill_date, e-Waybill Date,
        e-Waybill | Supplier Invoice, Builty / LR Copy
    Purchase Receipt > Purchase Document Attachments section (Details tab)
        e-Waybill No, Transport Mode | e-Waybill Date, e-Waybill |
        Supplier Invoice, Builty / LR Copy
"""

import frappe

LAYOUT = {
	"Purchase Invoice": {
		"remove": [
			"bns_ewaybill_col_break_1",
			"bns_ewaybill_col_break_2",
			"bns_ewaybill_col_break",
			"bns_purchase_attachments_section",
		],
		"insert_after": {
			"bns_ewaybill_no": "bill_no",
			"bns_mode_of_transport": "bns_ewaybill_no",
			"bns_ewaybill_date": "bill_date",
			"bns_ewaybill_attachment": "bns_ewaybill_date",
			"bns_ewaybill_col_break_3": "bns_ewaybill_attachment",
			"bns_supplier_invoice_attachment": "bns_ewaybill_col_break_3",
			"bns_builty_attachment": "bns_supplier_invoice_attachment",
		},
	},
	"Purchase Receipt": {
		"remove": ["bns_ewaybill_col_break_2", "bns_ewaybill_col_break"],
		"insert_after": {
			"bns_purchase_attachments_section": "return_against",
			"bns_ewaybill_no": "bns_purchase_attachments_section",
			"bns_mode_of_transport": "bns_ewaybill_no",
			"bns_ewaybill_col_break_1": "bns_mode_of_transport",
			"bns_ewaybill_date": "bns_ewaybill_col_break_1",
			"bns_ewaybill_attachment": "bns_ewaybill_date",
			"bns_ewaybill_col_break_3": "bns_ewaybill_attachment",
			"bns_supplier_invoice_attachment": "bns_ewaybill_col_break_3",
			"bns_builty_attachment": "bns_supplier_invoice_attachment",
		},
	},
}

OLD_PROPERTY_SETTERS = (
	"Purchase Invoice-column_break_15-hidden",
	"Purchase Invoice-column_break_15-insert_after",
	"Purchase Invoice-bill_date-insert_after",
	"Purchase Receipt-bill_date-insert_after",
	"Purchase Receipt-supplier_invoice_section-insert_after",
)


def execute():
	for name in OLD_PROPERTY_SETTERS:
		if frappe.db.exists("Property Setter", name):
			frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)

	for doctype, layout in LAYOUT.items():
		for fieldname in layout["remove"]:
			name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname})
			if name:
				frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)

		for fieldname, after in layout["insert_after"].items():
			name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname})
			if name:
				frappe.db.set_value("Custom Field", name, "insert_after", after, update_modified=False)

		if doctype == "Purchase Receipt":
			name = frappe.db.get_value(
				"Custom Field", {"dt": doctype, "fieldname": "bns_purchase_attachments_section"}
			)
			if name:
				frappe.db.set_value("Custom Field", name, "collapsible", 0, update_modified=False)

		frappe.clear_cache(doctype=doctype)
