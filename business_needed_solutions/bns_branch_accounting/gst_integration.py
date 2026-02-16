"""
BNS Branch Accounting - GST integration for internal transfers.

Handles:
- Mandate Vehicle No / GST Transporter ID for internal customer Delivery Notes (intra-state, above threshold).
- Auto-generate e-Waybill for same-GSTIN internal Delivery Notes when enabled in BNS Branch Accounting Settings.
"""

import logging
from typing import Optional

import frappe
from frappe import _
from india_compliance.gst_india.utils import is_api_enabled

from business_needed_solutions.bns_branch_accounting.utils import is_bns_internal_customer

logger = logging.getLogger(__name__)

# Default sub-supply type for internal stock transfers (NIC code 5 = "For Own Use")
INTERNAL_TRANSFER_SUB_SUPPLY_TYPE = 5


def validate_internal_dn_vehicle_no(doc, method: Optional[str] = None) -> None:
    """
    Mandate Vehicle No or GST Transporter ID before submission for internal
    customer Delivery Notes only when:
    1. The transfer is intra-state (same GSTIN) — because inter-state
       (different GSTIN) transfers go through Sales Invoice flow anyway.
    2. The invoice value meets or exceeds the GST Settings e-Waybill threshold.

    Per GST e-Way Bill rules, either vehicle_no OR gst_transporter_id is
    sufficient to satisfy the transport detail requirement.

    Intra-state is determined by comparing the **full** company_gstin and
    billing_address_gstin (not just the first 2 state-code digits).

    Args:
        doc: The Delivery Note document being validated
        method (Optional[str]): The method being called

    Raises:
        frappe.ValidationError: If neither Vehicle No nor GST Transporter ID
            is provided for an intra-state transfer above threshold
    """
    # Only enforce on submit
    if doc.docstatus != 1:
        return

    # Skip returns — they don't need transport details
    if doc.get("is_return"):
        return

    is_internal = doc.get("is_internal_customer") or is_bns_internal_customer(doc)
    if not is_internal:
        return

    # Skip if vehicle number OR transporter ID is already provided
    has_vehicle = bool((doc.get("vehicle_no") or "").strip())
    has_transporter = bool((doc.get("gst_transporter_id") or "").strip())
    if has_vehicle or has_transporter:
        return

    # Only enforce for intra-state (same full GSTIN) transfers.
    # Inter-state (different GSTIN) transfers use the Sales Invoice flow,
    # so vehicle details are not required on the DN.
    if _is_inter_state_transfer(doc):
        logger.debug(
            f"DN {doc.name}: Inter-state internal transfer — vehicle/transporter "
            f"not mandatory on DN (handled via Sales Invoice)"
        )
        return

    # Check against the e-Waybill threshold from GST Settings
    e_waybill_threshold = _get_ewaybill_threshold()
    if abs(doc.base_grand_total) < e_waybill_threshold:
        logger.debug(
            f"DN {doc.name}: Value {doc.base_grand_total} below e-Waybill threshold "
            f"{e_waybill_threshold} — vehicle/transporter not mandatory"
        )
        return

    frappe.throw(
        _(
            "Either Vehicle No or GST Transporter ID is mandatory for intra-state "
            "internal Delivery Notes with value of {0} or above. (Current value: {1})"
        ).format(
            frappe.format_value(e_waybill_threshold, {"fieldtype": "Currency"}),
            frappe.format_value(abs(doc.base_grand_total), {"fieldtype": "Currency"}),
        ),
        title=_("Missing Transport Details"),
    )


def maybe_generate_internal_dn_ewaybill(doc, method: Optional[str] = None) -> None:
    """
    Auto-generate e-Waybill for internal customer Delivery Notes when:
    1. BNS Settings toggle is enabled
    2. Customer is BNS internal customer
    3. Billing GSTIN equals Company GSTIN (same GSTIN internal transfer)
    4. Invoice value exceeds GST Settings e-Waybill threshold
    5. Goods are supplied (not services)
    6. Required addresses and transport details are present
    7. India Compliance API is enabled

    Generation runs synchronously so the user gets immediate feedback.
    The doc is stamped with _sub_supply_type = 5 ("For Own Use") before
    calling IC's internal generator, which is the correct NIC sub-supply
    code for same-GSTIN stock transfers.

    Args:
        doc: The Delivery Note document being submitted
        method (Optional[str]): The method being called
    """
    try:
        # Guard: Check if feature is enabled in BNS Branch Accounting Settings
        if not _is_internal_dn_ewaybill_enabled():
            logger.debug("Internal DN e-Waybill feature is disabled in BNS Branch Accounting Settings")
            return

        # Guard: Only process on submit (docstatus == 1)
        if doc.docstatus != 1:
            return

        # Guard: Skip returns
        if doc.get("is_return"):
            return

        # Guard: Check if already has e-Waybill
        if doc.get("ewaybill"):
            logger.debug(f"Delivery Note {doc.name} already has e-Waybill: {doc.ewaybill}")
            return

        # Guard: Check if customer is BNS internal
        if not is_bns_internal_customer(doc):
            logger.debug(f"Customer {doc.customer} is not a BNS internal customer")
            return

        # Guard: Check if GSTIN is same (internal transfer under same GSTIN)
        company_gstin = (doc.get("company_gstin") or "").strip().upper()
        billing_gstin = (doc.get("billing_address_gstin") or "").strip().upper()

        if not company_gstin or not billing_gstin:
            logger.debug(f"Missing GSTIN - company: {company_gstin}, billing: {billing_gstin}")
            return

        if company_gstin != billing_gstin:
            logger.debug("GSTINs differ — not a same-GSTIN internal transfer")
            return

        # Guard: Check GST Settings requirements
        gst_settings = frappe.get_cached_doc("GST Settings")

        if not gst_settings.enable_e_waybill:
            logger.debug("e-Waybill is disabled in GST Settings")
            return

        if not gst_settings.enable_e_waybill_from_dn:
            logger.debug("e-Waybill from Delivery Note is disabled in GST Settings")
            return

        # Guard: API must be enabled (otherwise IC throws inside BaseAPI.__init__)
        if not is_api_enabled(gst_settings):
            logger.debug("India Compliance API is not enabled — skipping e-Waybill")
            return

        # Guard: Check threshold
        e_waybill_threshold = gst_settings.e_waybill_threshold or 0
        if abs(doc.base_grand_total) < e_waybill_threshold:
            logger.debug(
                f"Invoice value {doc.base_grand_total} below threshold {e_waybill_threshold}"
            )
            return

        # Guard: Check if goods are supplied (not just services)
        if not _are_goods_supplied(doc):
            logger.debug("No goods supplied — only services")
            return

        # Guard: Required address fields (IC will throw MandatoryError otherwise)
        if not doc.get("company_address"):
            frappe.msgprint(
                _("e-Waybill not auto-generated: Company Address is missing."),
                title=_("e-Waybill Requirements Not Met"),
                indicator="orange",
            )
            return

        if not doc.get("customer_address"):
            frappe.msgprint(
                _("e-Waybill not auto-generated: Customer Address is missing."),
                title=_("e-Waybill Requirements Not Met"),
                indicator="orange",
            )
            return

        # Guard: Validate transporter / vehicle requirements
        transport_error = _validate_transport_details(doc)
        if transport_error:
            logger.info(f"Transport validation failed for {doc.name}: {transport_error}")
            frappe.msgprint(
                _("e-Waybill not auto-generated: {0}").format(transport_error),
                title=_("e-Waybill Requirements Not Met"),
                indicator="orange",
            )
            return

        # Default mode_of_transport to "Road" when vehicle_no is filled
        # but mode was left blank (common data-entry oversight).
        if doc.get("vehicle_no") and not doc.get("mode_of_transport"):
            doc.db_set("mode_of_transport", "Road", update_modified=False)
            doc.mode_of_transport = "Road"

        # Stamp the sub-supply type India Compliance expects for Delivery
        # Notes (normally set via the e-Waybill dialog). Without this the
        # API payload sends an empty sub_supply_type and NIC rejects it.
        doc._sub_supply_type = INTERNAL_TRANSFER_SUB_SUPPLY_TYPE

        # Call IC's internal generator synchronously so errors surface to
        # the user immediately instead of failing silently in a background job.
        from india_compliance.gst_india.utils.e_waybill import _generate_e_waybill

        logger.info(f"Generating e-Waybill for internal DN {doc.name}")
        _generate_e_waybill(doc, throw=False)

        if doc.get("ewaybill"):
            frappe.msgprint(
                _("e-Waybill {0} generated for this internal transfer.").format(
                    frappe.bold(doc.ewaybill)
                ),
                title=_("e-Waybill Generated"),
                indicator="green",
            )

    except Exception as e:
        logger.error(f"Error in internal DN e-Waybill generation: {str(e)}")
        frappe.log_error(
            title=_("e-Waybill Auto-Generation Error"),
            message=f"Failed to auto-generate e-Waybill for Delivery Note {doc.name}: {str(e)}",
        )
        # Show the user a warning; don't block submission.
        frappe.msgprint(
            _("e-Waybill auto-generation failed: {0}. You can generate it manually.").format(
                str(e)
            ),
            title=_("e-Waybill Auto-Generation Failed"),
            indicator="orange",
        )


def _is_internal_dn_ewaybill_enabled() -> bool:
    """
    Check if internal DN e-Waybill feature is enabled in BNS Branch Accounting Settings.

    Returns:
        bool: True if feature is enabled, False otherwise
    """
    try:
        return bool(
            frappe.db.get_single_value("BNS Branch Accounting Settings", "enable_internal_dn_ewaybill")
        )
    except Exception as e:
        logger.error(f"Error checking internal DN e-Waybill setting: {str(e)}")
        return False


def _are_goods_supplied(doc) -> bool:
    """
    Check if goods (not just services) are supplied in the document.

    Goods are identified by HSN codes NOT starting with "99" (which are services).

    Args:
        doc: The document to check

    Returns:
        bool: True if goods are supplied, False otherwise
    """
    for item in doc.items:
        hsn_code = item.get("gst_hsn_code") or ""
        # Services have HSN codes starting with 99
        if hsn_code and not hsn_code.startswith("99") and item.qty != 0:
            return True
    return False


def _validate_transport_details(doc) -> Optional[str]:
    """
    Validate transporter/vehicle details required for e-Waybill generation.

    Matches India Compliance logic:
    - When gst_transporter_id is provided: Part A only can be generated (vehicle_no not required).
    - When only mode_of_transport is provided: full details (vehicle_no, lr_no as applicable)
      must be filled.

    Args:
        doc: The document to validate

    Returns:
        Optional[str]: Error message if validation fails, None if valid
    """
    mode_of_transport = doc.get("mode_of_transport")
    gst_transporter_id = (doc.get("gst_transporter_id") or "").strip()

    # Either mode_of_transport or gst_transporter_id is required
    if not mode_of_transport and not gst_transporter_id:
        return _("Either GST Transporter ID or Mode of Transport is required to generate e-Waybill")

    # When gst_transporter_id is provided, India Compliance allows Part A only generation
    # (no vehicle_no required). Same as IC's validate_applicability + set_transporter_details.
    if gst_transporter_id:
        return None

    # Validate based on mode of transport (only when transporter_id is not provided)
    if mode_of_transport == "Road" and not doc.get("vehicle_no"):
        return _("Vehicle Number is required to generate e-Waybill for supply via Road")

    if mode_of_transport == "Ship" and not (doc.get("vehicle_no") and doc.get("lr_no")):
        return _("Vehicle Number and L/R No is required to generate e-Waybill for supply via Ship")

    if mode_of_transport in ("Rail", "Air") and not doc.get("lr_no"):
        return _("L/R No. is required to generate e-Waybill for supply via Rail or Air")

    return None


def _is_inter_state_transfer(doc) -> bool:
    """
    Determine whether the Delivery Note is an inter-state (different GSTIN)
    transfer by comparing the full company_gstin and billing_address_gstin.

    For BNS internal transfers "intra-state" means **same GSTIN** — the
    exact same GST registration on both sides.  When GSTINs differ the
    transfer is inter-state and must go through the Sales Invoice flow,
    so vehicle details are not required on the DN.

    Args:
        doc: The Delivery Note document

    Returns:
        bool: True if different GSTIN (inter-state), False if same GSTIN
              (intra-state) or if either GSTIN is missing
    """
    company_gstin = (doc.get("company_gstin") or "").strip().upper()
    billing_gstin = (doc.get("billing_address_gstin") or "").strip().upper()

    if not company_gstin or not billing_gstin:
        # Cannot determine — treat as intra-state (safer default: enforce
        # vehicle requirement so the user is prompted to fill in details).
        logger.debug(
            f"DN {doc.name}: Cannot determine GSTIN — company_gstin={company_gstin!r}, "
            f"billing_gstin={billing_gstin!r}. Treating as same GSTIN (intra-state)."
        )
        return False

    return company_gstin != billing_gstin


def _get_ewaybill_threshold() -> float:
    """
    Fetch the e-Waybill threshold amount from GST Settings.

    Returns:
        float: The threshold amount; 0 if not configured or on error
    """
    try:
        return float(
            frappe.db.get_single_value("GST Settings", "e_waybill_threshold") or 0
        )
    except Exception as e:
        logger.error(f"Error fetching e-Waybill threshold: {e}")
        return 0
