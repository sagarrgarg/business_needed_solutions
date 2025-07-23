"""
Business Needed Solutions - Vehicle Update System

This module provides functionality to update vehicle and transporter details
for documents that support e-Waybill functionality.
"""

import frappe
from frappe import _
from frappe.utils import get_link_to_form
from typing import Optional, Dict, Any
import logging

# Configure logging
logger = logging.getLogger(__name__)


class VehicleUpdateError(Exception):
    """Custom exception for vehicle update errors."""
    pass


@frappe.whitelist()
def update_vehicle_or_transporter(
    doctype: str, 
    docname: str, 
    vehicle_no: Optional[str] = None, 
    transporter: Optional[str] = None, 
    gst_transporter_id: Optional[str] = None
) -> None:
    """
    Update vehicle number and transporter details for a document.
    
    This function allows updating vehicle and transporter information for documents
    that support e-Waybill functionality, but only when the e-Waybill status is
    'Pending' or 'Not Applicable'.
    
    Args:
        doctype (str): The document type to update
        docname (str): The name of the document to update
        vehicle_no (Optional[str]): The vehicle number to set
        transporter (Optional[str]): The transporter to set
        gst_transporter_id (Optional[str]): The GST transporter ID to set
        
    Raises:
        VehicleUpdateError: If update fails or is not allowed
    """
    try:
        # Load the document
        doc = _load_document(doctype, docname)
        
        # Validate e-Waybill status
        _validate_ewaybill_status(doc)
        
        # Prepare update data
        update_data = _prepare_update_data(vehicle_no, transporter, gst_transporter_id)
        
        if not update_data:
            raise VehicleUpdateError(_("No data provided to update."))
        
        # Update the document
        _update_document(doc, update_data)
        
        # Show success message
        _show_success_message(doctype, docname)
        
        logger.info(f"Successfully updated vehicle/transporter details for {doctype} {docname}")
        
    except Exception as e:
        logger.error(f"Error updating vehicle/transporter details: {str(e)}")
        raise


def _load_document(doctype: str, docname: str):
    """
    Load the document to be updated.
    
    Args:
        doctype (str): The document type
        docname (str): The document name
        
    Returns:
        The loaded document
        
    Raises:
        VehicleUpdateError: If document cannot be loaded
    """
    try:
        return frappe.get_doc(doctype, docname)
    except Exception as e:
        raise VehicleUpdateError(_("Could not load document {0} {1}: {2}").format(doctype, docname, str(e)))


def _validate_ewaybill_status(doc) -> None:
    """
    Validate that the e-Waybill status allows updates.
    
    Args:
        doc: The document to validate
        
    Raises:
        VehicleUpdateError: If e-Waybill status does not allow updates
    """
    if doc.e_waybill_status not in ["Pending", "Not Applicable"]:
        raise VehicleUpdateError(_(
            "e-Waybill can only be updated if the status is 'Pending' or 'Not Applicable'."
        ))


def _prepare_update_data(
    vehicle_no: Optional[str], 
    transporter: Optional[str], 
    gst_transporter_id: Optional[str]
) -> Dict[str, Any]:
    """
    Prepare the data to be updated.
    
    Args:
        vehicle_no (Optional[str]): The vehicle number
        transporter (Optional[str]): The transporter
        gst_transporter_id (Optional[str]): The GST transporter ID
        
    Returns:
        Dict[str, Any]: The data to be updated
    """
    update_data = {}
    
    # Allow changing vehicle number even if it's None initially
    if vehicle_no is not None:
        update_data["vehicle_no"] = vehicle_no
        
    if transporter:
        update_data["transporter"] = transporter
        update_data["gst_transporter_id"] = gst_transporter_id
        
    return update_data


def _update_document(doc, update_data: Dict[str, Any]) -> None:
    """
    Update the document with the provided data.
    
    Args:
        doc: The document to update
        update_data (Dict[str, Any]): The data to update
        
    Raises:
        VehicleUpdateError: If update fails
    """
    try:
        # Ignore validation restrictions for update after submit
        doc.flags.ignore_validate_update_after_submit = True
        
        # Update the document
        doc.update(update_data)
        doc.save(ignore_permissions=True)
        
    except Exception as e:
        raise VehicleUpdateError(_("Failed to update document: {0}").format(str(e)))


def _show_success_message(doctype: str, docname: str) -> None:
    """
    Show a success message after successful update.
    
    Args:
        doctype (str): The document type
        docname (str): The document name
    """
    message = _("Vehicle/Transporter details updated successfully for {0}.").format(
        get_link_to_form(doctype, docname)
    )
    
    frappe.msgprint(
        message,
        alert=True,
        indicator="green",
    )