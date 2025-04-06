import frappe
from frappe import _

def validate_pan_uniqueness(doc, method):
    """Validate PAN uniqueness for both Customer and Supplier"""
    if not doc.pan:
        return

    # Check if PAN uniqueness is enabled in settings
    # enforce_pan_uniqueness = frappe.db.get_value("BNS Settings", None, "enforce_pan_uniqueness", ignore_permissions=True)
    enforce_pan_uniqueness = frappe.get_single_value("BNS Settings", "enforce_pan_uniqueness")
    if not enforce_pan_uniqueness:
        return

    # Determine the doctype for the error message
    doctype_label = "Customer" if doc.doctype == "Customer" else "Supplier"
    
    # Check for existing PAN
    existing_doc = frappe.db.exists(
        doc.doctype,
        {
            "pan": doc.pan,
            "name": ["!=", doc.name]
        }
    )
    
    if existing_doc:
        frappe.throw(_(
            "PAN number must be unique. Another {doctype} with the same PAN already exists."
        ).format(doctype=doctype_label)) 