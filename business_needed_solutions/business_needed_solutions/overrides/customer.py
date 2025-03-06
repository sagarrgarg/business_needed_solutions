import frappe
from frappe import _

# def validate_pan_uniqueness(doc, method):
#     if doc.pan:
#         existing_customer = frappe.db.exists(
#             "Customer",
#             {
#                 "pan": doc.pan,
#                 "name": ["!=", doc.name]
#             }
#         )
#         if existing_customer:
#             frappe.throw(_("PAN number must be unique. Another customer with the same PAN already exists."))