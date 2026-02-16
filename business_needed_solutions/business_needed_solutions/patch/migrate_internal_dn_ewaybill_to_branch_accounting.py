"""
Migrate enable_internal_dn_ewaybill from BNS Settings to BNS Branch Accounting Settings.

Runs before BNS Settings doctype is updated (pre_model_sync) so we can read the value
before the field is removed.
"""

import frappe


def execute():
    try:
        # BNS Settings stores single values in Singles table
        old_val = frappe.db.get_value(
            "Singles",
            {"doctype": "BNS Settings", "field": "enable_internal_dn_ewaybill"},
            "value",
        )
        if old_val is None:
            return

        val = 1 if str(old_val) in ("1", "true", "True") else 0

        # Copy to BNS Branch Accounting Settings (Single doctype)
        if frappe.db.exists("DocType", "BNS Branch Accounting Settings"):
            if not frappe.db.exists("BNS Branch Accounting Settings", "BNS Branch Accounting Settings"):
                doc = frappe.new_doc("BNS Branch Accounting Settings")
                doc.enable_internal_dn_ewaybill = val
                doc.insert(ignore_permissions=True)
            else:
                frappe.db.set_value(
                    "BNS Branch Accounting Settings",
                    "BNS Branch Accounting Settings",
                    "enable_internal_dn_ewaybill",
                    val,
                    update_modified=False,
                )
            frappe.db.commit()
    except Exception:
        frappe.db.rollback()
