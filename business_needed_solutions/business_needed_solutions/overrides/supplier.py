import frappe
from frappe import _

def validate_pan_uniqueness(doc, method):
    if doc.pan:
        existing_customer = frappe.db.exists(
            "Supplier",
            {
                "pan": doc.pan,
                "name": ["!=", doc.name]
            }
        )
        if existing_customer:
            frappe.throw(_("PAN number must be unique. Another supplier with the same PAN already exists."))