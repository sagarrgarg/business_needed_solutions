import frappe
from frappe import _
from frappe.utils import get_link_to_form

@frappe.whitelist()
def update_vehicle_or_transporter(doctype, docname, vehicle_no=None, transporter=None, gst_transporter_id=None):
    # Load the document
    doc = frappe.get_doc(doctype, docname)

    # Check if e-Waybill status is either 'Pending' or 'Not Applicable'
    if doc.e_waybill_status not in ["Pending", "Not Applicable"]:
        frappe.throw(_("e-Waybill can only be updated if the status is 'Pending' or 'Not Applicable'."))

    # Ignore validation restrictions for update after submit
    doc.flags.ignore_validate_update_after_submit = True

    # Update vehicle number and transporter details if provided
    update_data = {}
    if vehicle_no is not None:  # Allow changing vehicle number even if it's None initially
        update_data["vehicle_no"] = vehicle_no
    if transporter:
        update_data["transporter"] = transporter
        update_data["gst_transporter_id"] = gst_transporter_id

    if update_data:
        doc.update(update_data)
        doc.save(ignore_permissions=True)
        frappe.msgprint(
            _(f"Vehicle/Transporter details updated successfully for {get_link_to_form(doctype, docname)}."),
            alert=True,
            indicator="green",
        )
    else:
        frappe.throw(_("No data provided to update."))