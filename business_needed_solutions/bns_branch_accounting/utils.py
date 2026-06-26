"""
BNS Branch Accounting - Internal Transfer Utilities

This module contains all BNS internal transfer logic:
- DN→PR, SI→PI, SI→PR creation and linking
- Status updates for BNS internally transferred documents
- Convert, link, unlink operations
- Bulk conversion and validation
"""

import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.contacts.doctype.address.address import get_company_address
from erpnext.accounts.doctype.sales_invoice.sales_invoice import update_address, update_taxes
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
    get_accounting_dimensions,
)
from erpnext.accounts.utils import get_fiscal_year
from frappe.utils import flt, cint, get_link_to_form, getdate, add_to_date, now_datetime
from frappe import bold
from typing import Optional, Dict, Any, List, Tuple, Set
from collections import defaultdict
import logging
import json
import time

# Configure logging
logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Permission gates for whitelisted endpoints in this module.
#
# Why: every @frappe.whitelist() in utils.py is reachable by any
# authenticated user. Several of them create / modify / submit
# documents (make_bns_internal_*, convert_*_to_bns_internal,
# link_*/unlink_*, bulk_convert_*, bns_force_*_gl_*).
#
# These helpers do NOT hardcode role names. They consult the Frappe
# Role Permission Manager via frappe.has_permission(), so admins grant
# access through the Desk UI (Setup → Role Permission Manager) without
# editing code.
#
# Gate doctype: `BNS Branch Accounting Settings` — the Single doctype
# that owns the internal-transfer behaviour. Admins configure who can
# read/write branch-accounting operations by editing its role
# permissions in the Role Permission Manager.
# -------------------------------------------------------------------


_BNS_BA_SETTINGS = "BNS Branch Accounting Settings"


def _bns_require_accounts_read():
    """Read / lookup endpoint gate — checks BNS Branch Accounting Settings
    read permission via the Role Permission Manager."""
    if not frappe.has_permission(_BNS_BA_SETTINGS, "read"):
        frappe.throw(
            _("You need read permission on {0} for this BNS endpoint. "
              "Ask an administrator to grant your role access via the "
              "Role Permission Manager.").format(_BNS_BA_SETTINGS),
            frappe.PermissionError,
        )


def _bns_require_accounts_write():
    """Write / mutate endpoint gate — checks BNS Branch Accounting Settings
    write permission via the Role Permission Manager."""
    if not frappe.has_permission(_BNS_BA_SETTINGS, "write"):
        frappe.throw(
            _("You need write permission on {0} for this BNS endpoint. "
              "Ask an administrator to grant your role access via the "
              "Role Permission Manager.").format(_BNS_BA_SETTINGS),
            frappe.PermissionError,
        )


def _bns_require_doctype_read(doctype: str):
    """Per-doctype read gate — used by BNS endpoints that operate on a
    specific transaction doctype (Sales Invoice, Purchase Invoice,
    Delivery Note, Purchase Receipt) rather than on branch-accounting
    configuration. Lets admins grant routine accounts users access to
    BNS convert/link operations without granting write on BNS Branch
    Accounting Settings."""
    if not frappe.has_permission(doctype, "read"):
        frappe.throw(
            _("You need read permission on {0} for this BNS endpoint.").format(doctype),
            frappe.PermissionError,
        )


def _bns_require_doctype_write(doctype: str):
    """Per-doctype write gate. See `_bns_require_doctype_read` for rationale."""
    if not frappe.has_permission(doctype, "write"):
        frappe.throw(
            _("You need write permission on {0} for this BNS endpoint.").format(doctype),
            frappe.PermissionError,
        )


def _bns_debug_log(hypothesis_id: str, location: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
    """Append one NDJSON debug line for runtime investigation."""
    try:
        site_name = getattr(frappe.local, "site", "") or "unknown-site"
        payload = {
            "runId": f"{site_name}:{int(time.time() * 1000)}",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        debug_log_path = frappe.get_site_path("logs", "bns_branch_accounting_debug.ndjson")
        with open(debug_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass

_BNS_INTERNAL_GL_PATCHED = False
_BNS_REPOST_GL_FAILSAFE_PATCHED = False
_BNS_TRANSFER_RATE_STOCK_LEDGER_PATCHED = False
_BNS_REPOST_ACCOUNTING_LEDGER_PATCHED = False
_BNS_REPOST_TRACKING_DTYPE = "BNS Repost Tracking"
_BNS_REPOST_STATUS_IN_PROGRESS = "In Progress"
_BNS_REPOST_STATUS_PROCESSED = "Processed"
_BNS_REPOST_STATUS_FAILED = "Failed"
_BNS_REPOST_CACHE_TTL_SEC = 6 * 60 * 60


def _duplicate_serial_and_batch_bundle(
    source_item, target_item, target_warehouse: Optional[str], transaction_type: str = "Inward"
) -> None:
    """
    Clone a Serial and Batch Bundle from source item row to target item row.

    Handles four scenarios:
    1. Source has serial_and_batch_bundle -> duplicate via SerialBatchCreation
    2. Source has legacy serial_no/batch_no without bundle -> copy with use_serial_batch_fields=1
    3. Source has neither, but Item now requires batch/serial (cross-FY) -> log warning, skip
    4. Source has neither and Item doesn't require batch/serial -> no-op

    Args:
        source_item: Source document item row (DN Item, SI Item)
        target_item: Target document item row (PR Item, PI Item)
        target_warehouse: Warehouse for the new bundle (must not be None when SBB is present)
        transaction_type: "Inward" or "Outward"
    """
    source_bundle = source_item.get("serial_and_batch_bundle")

    if source_bundle:
        if not target_warehouse:
            logger.warning(
                "SBB duplication skipped for item %s: target_warehouse is None "
                "(source bundle %s). Batch/serial info will not carry to target.",
                source_item.item_code, source_bundle,
            )
            return

        from erpnext.stock.serial_batch_bundle import SerialBatchCreation

        try:
            cls_obj = SerialBatchCreation(
                {
                    "type_of_transaction": transaction_type,
                    "serial_and_batch_bundle": source_bundle,
                    "item_code": source_item.item_code,
                    "warehouse": target_warehouse,
                }
            )
            cls_obj.duplicate_package()
            target_item.serial_and_batch_bundle = cls_obj.serial_and_batch_bundle
            target_item.use_serial_batch_fields = 0
        except Exception:
            logger.error(
                "Failed to duplicate Serial and Batch Bundle %s for item %s",
                source_bundle, source_item.item_code, exc_info=True,
            )
            raise

    elif source_item.get("serial_no") or source_item.get("batch_no"):
        target_item.use_serial_batch_fields = 1
        if source_item.get("serial_no"):
            target_item.serial_no = source_item.serial_no
        if source_item.get("batch_no"):
            target_item.batch_no = source_item.batch_no

    else:
        item_meta = frappe.get_cached_value(
            "Item", source_item.item_code,
            ["has_batch_no", "has_serial_no"], as_dict=True,
        )
        if item_meta and (item_meta.has_batch_no or item_meta.has_serial_no):
            logger.warning(
                "Item %s now requires batch/serial, but source document item "
                "has no batch_no, serial_no, or serial_and_batch_bundle. "
                "This is expected for cross-fiscal-year transfers where tracking "
                "was enabled after the source was submitted. The target document's "
                "batch/serial must be set manually before submission.",
                source_item.item_code,
            )


def _source_incoming_rate_for_pr_item(pr_item, is_dn_linked):
    """Authoritative source rate for a PR item: the linked Delivery Note Item
    incoming_rate (including a genuine 0). Returns None when no source item link
    resolves, so the caller can tell "genuine zero" from "unresolved".
    """
    if not is_dn_linked:
        return None
    dn_item = (pr_item.get("delivery_note_item") or "").strip()
    if dn_item and frappe.db.exists("Delivery Note Item", dn_item):
        return flt(frappe.db.get_value("Delivery Note Item", dn_item, "incoming_rate") or 0)
    return None


def _get_bns_transfer_rate_for_pr_sle(sle):
    """
    Resolve the forced incoming_rate for a Purchase Receipt SLE row.

    Returns a float (INCLUDING 0.0) to force that incoming_rate, or None to
    leave ERPNext's own valuation untouched.

    Scope: submitted, BNS internal supplier, DN/SI-linked, after the accounting
    rewrite cutoff. A stored bns_transfer_rate of 0 is ambiguous (a genuine
    zero-cost transfer vs an unresolved rate), so on 0 we consult the SOURCE
    Delivery Note Item incoming_rate: if that source item resolves, its value
    (0 or positive) is authoritative; only when no source resolves is the row
    left alone.
    """
    if not sle or getattr(sle, "voucher_type", None) != "Purchase Receipt":
        return None
    if not getattr(sle, "voucher_detail_no", None):
        return None
    if flt(getattr(sle, "actual_qty", 0)) <= 0:
        return None

    pri_meta = frappe.get_meta("Purchase Receipt Item")
    if not pri_meta.has_field("bns_transfer_rate"):
        return None

    pr_item = frappe.db.get_value(
        "Purchase Receipt Item",
        sle.voucher_detail_no,
        ["parent", "bns_transfer_rate", "delivery_note_item"],
        as_dict=True,
    )
    if not pr_item:
        return None

    pr = frappe.db.get_value(
        "Purchase Receipt",
        pr_item.get("parent"),
        ["docstatus", "is_bns_internal_supplier", "bns_inter_company_reference", "posting_date"],
        as_dict=True,
    )
    if not pr or pr.docstatus != 1:
        return None
    source_ref = (pr.get("bns_inter_company_reference") or "").strip()
    if not source_ref:
        return None

    source_posting_date = None
    for dt in ("Delivery Note", "Sales Invoice"):
        sd = frappe.db.get_value(dt, source_ref, "posting_date")
        if sd:
            source_posting_date = sd
            break
    if not is_after_accounting_rewrite_cutoff(source_posting_date or pr.get("posting_date")):
        return None

    is_dn_linked = bool(pr.get("is_bns_internal_supplier") and frappe.db.exists("Delivery Note", source_ref))
    is_si_linked = frappe.db.exists("Sales Invoice", source_ref)
    if not (is_dn_linked or is_si_linked):
        return None

    transfer_rate = flt(pr_item.get("bns_transfer_rate") or 0)
    if transfer_rate > 0:
        return transfer_rate

    # Stored rate is 0 -> consult the source DN item to disambiguate genuine
    # zero-cost from unresolved.
    source_rate = _source_incoming_rate_for_pr_item(pr_item, is_dn_linked)
    if source_rate is not None:
        return source_rate
    return None


def _source_incoming_rate_for_pi_item(pi_item):
    """Authoritative source rate for a PI item: the linked Sales Invoice Item
    incoming_rate, chasing the Delivery Note behind it when the SI rate is 0.
    Returns None when no source SI item link resolves (so the caller can tell a
    genuine zero from an unresolved rate).
    """
    si_item = (pi_item.get("sales_invoice_item") or "").strip()
    if not si_item:
        return None
    row = frappe.db.get_value(
        "Sales Invoice Item", si_item,
        ["incoming_rate", "dn_detail"], as_dict=True,
    )
    if not row:
        return None
    rate = flt(row.get("incoming_rate") or 0)
    if rate > 0:
        return rate
    # SI rate is itself 0 -> chase the DN behind it for the authoritative cost.
    dn_detail = (row.get("dn_detail") or "").strip()
    if dn_detail and frappe.db.exists("Delivery Note Item", dn_detail):
        return flt(frappe.db.get_value("Delivery Note Item", dn_detail, "incoming_rate") or 0)
    return rate  # SI item resolves but values to 0 everywhere -> genuine 0


def _get_bns_transfer_rate_for_pi_sle(sle):
    """
    Resolve the forced incoming_rate for a Purchase Invoice SLE row.

    Returns a float (INCLUDING 0.0) to force that incoming_rate, or None to
    leave ERPNext's own valuation untouched. On a stored rate of 0 we consult
    the SOURCE Sales Invoice Item incoming_rate (chasing its DN) so a genuine
    zero-cost transfer books at 0 while a truly unresolved row is left alone.
    """
    if not sle or getattr(sle, "voucher_type", None) != "Purchase Invoice":
        return None
    if not getattr(sle, "voucher_detail_no", None):
        return None
    if flt(getattr(sle, "actual_qty", 0)) <= 0:
        return None

    pii_meta = frappe.get_meta("Purchase Invoice Item")
    if not pii_meta.has_field("bns_transfer_rate"):
        return None

    pi_item = frappe.db.get_value(
        "Purchase Invoice Item",
        sle.voucher_detail_no,
        ["parent", "bns_transfer_rate", "sales_invoice_item"],
        as_dict=True,
    )
    if not pi_item:
        return None

    pi = frappe.db.get_value(
        "Purchase Invoice",
        pi_item.get("parent"),
        [
            "docstatus",
            "is_bns_internal_supplier",
            "bns_inter_company_reference",
            "posting_date",
            "update_stock",
        ],
        as_dict=True,
    )
    if not pi or pi.docstatus != 1:
        return None
    if not cint(pi.get("update_stock")):
        return None
    if not pi.get("is_bns_internal_supplier"):
        return None
    source_ref = (pi.get("bns_inter_company_reference") or "").strip()
    if not source_ref or not frappe.db.exists("Sales Invoice", source_ref):
        return None
    source_posting_date = frappe.db.get_value("Sales Invoice", source_ref, "posting_date")
    if not is_after_accounting_rewrite_cutoff(source_posting_date or pi.get("posting_date")):
        return None

    transfer_rate = flt(pi_item.get("bns_transfer_rate") or 0)
    if transfer_rate > 0:
        return transfer_rate

    source_rate = _source_incoming_rate_for_pi_item(pi_item)
    if source_rate is not None:
        return source_rate
    return None


def _get_bns_transfer_rate_for_sle(sle):
    """Resolve the forced incoming_rate override for PR/PI SLE rows.

    Returns a float (incl 0.0) to force, or None to leave ERPNext's valuation.
    """
    rate = _get_bns_transfer_rate_for_pr_sle(sle)
    if rate is not None:
        return rate
    return _get_bns_transfer_rate_for_pi_sle(sle)


def _apply_bns_transfer_rate_stock_ledger_patch() -> None:
    """Ensure PR repost valuation path can use Purchase Receipt Item.bns_transfer_rate."""
    global _BNS_TRANSFER_RATE_STOCK_LEDGER_PATCHED
    if _BNS_TRANSFER_RATE_STOCK_LEDGER_PATCHED:
        return

    try:
        from erpnext.stock.stock_ledger import update_entries_after

        original_method = update_entries_after.get_incoming_outgoing_rate_from_transaction
        original_process_sle = update_entries_after.process_sle
        if getattr(original_method, "_bns_transfer_rate_patched", False):
            _BNS_TRANSFER_RATE_STOCK_LEDGER_PATCHED = True
            return

        def patched_get_incoming_outgoing_rate_from_transaction(self, sle):
            rate = original_method(self, sle)
            transfer_rate = _get_bns_transfer_rate_for_sle(sle)
            if transfer_rate is not None:
                sle.incoming_rate = transfer_rate
                return transfer_rate
            return rate

        def patched_process_sle(self, sle):
            transfer_rate = _get_bns_transfer_rate_for_sle(sle)
            if transfer_rate is not None:
                sle.incoming_rate = transfer_rate
                sle.recalculate_rate = 1
            return original_process_sle(self, sle)

        patched_get_incoming_outgoing_rate_from_transaction._bns_transfer_rate_patched = True
        patched_process_sle._bns_transfer_rate_patched = True
        update_entries_after.get_incoming_outgoing_rate_from_transaction = patched_get_incoming_outgoing_rate_from_transaction
        update_entries_after.process_sle = patched_process_sle
        _BNS_TRANSFER_RATE_STOCK_LEDGER_PATCHED = True
        logger.info("Applied BNS stock-ledger patch: PR/PI repost valuation uses bns_transfer_rate")
    except Exception as e:
        logger.error(f"Failed to apply BNS transfer-rate stock-ledger patch: {str(e)}")


def _get_bns_branch_accounting_accounts() -> Dict[str, Any]:
    """Get BNS Branch Accounting account settings required for GL rewrite."""
    legacy_internal_transfer_account = (
        frappe.db.get_single_value("BNS Branch Accounting Settings", "internal_transfer_account") or ""
    ).strip()
    sales_transfer_account = (
        frappe.db.get_single_value(
            "BNS Branch Accounting Settings", "internal_sales_transfer_account"
        )
        or legacy_internal_transfer_account
    )
    purchase_transfer_account = (
        frappe.db.get_single_value(
            "BNS Branch Accounting Settings", "internal_purchase_transfer_account"
        )
        or legacy_internal_transfer_account
    )
    settings = {
        "stock_in_transit_account": frappe.db.get_single_value(
            "BNS Branch Accounting Settings", "stock_in_transit_account"
        ),
        "internal_sales_transfer_account": sales_transfer_account,
        "internal_purchase_transfer_account": purchase_transfer_account,
        # Non-GST (DN/PR same-GSTIN) accounts fall back to the GST/Inter-State
        # account so installs that haven't split the ledger keep working.
        "internal_sales_non_gst_account": (
            frappe.db.get_single_value(
                "BNS Branch Accounting Settings", "internal_sales_non_gst_account"
            )
            or sales_transfer_account
        ),
        "internal_purchase_non_gst_account": (
            frappe.db.get_single_value(
                "BNS Branch Accounting Settings", "internal_purchase_non_gst_account"
            )
            or purchase_transfer_account
        ),
        # Keep legacy field readable during transition only.
        "internal_transfer_account": legacy_internal_transfer_account,
        "internal_branch_debtor_account": frappe.db.get_single_value(
            "BNS Branch Accounting Settings", "internal_branch_debtor_account"
        ),
        "internal_branch_creditor_account": frappe.db.get_single_value(
            "BNS Branch Accounting Settings", "internal_branch_creditor_account"
        ),
        "force_bns_internal_gl_rewrite": cint(
            frappe.db.get_single_value("BNS Branch Accounting Settings", "force_bns_internal_gl_rewrite") or 0
        ),
    }

    required = (
        "stock_in_transit_account",
        "internal_branch_debtor_account",
        "internal_branch_creditor_account",
    )
    missing = [f for f in required if not settings.get(f)]
    if missing:
        logger.warning("Skipping BNS internal GL rewrite. Missing settings fields: %s", ", ".join(missing))
        return {}

    return settings


def _is_bns_internal_dn_pr_scope(doc) -> bool:
    """Return True when document is in BNS internal DN/PR scope."""
    if not doc:
        return False
    if doc.doctype == "Delivery Note":
        if doc.get("is_bns_internal_customer"):
            return True
        customer = doc.get("customer")
        return bool(customer and frappe.db.get_value("Customer", customer, "is_bns_internal_customer"))
    if doc.doctype == "Purchase Receipt":
        if doc.get("is_bns_internal_supplier"):
            return True
        supplier = doc.get("supplier")
        return bool(supplier and frappe.db.get_value("Supplier", supplier, "is_bns_internal_supplier"))
    return False


def validate_bns_internal_accounting_settings_for_dn_pr(
    doc, method: Optional[str] = None
) -> None:
    """
    Hard gate before DN/PR submit for BNS internal scope.

    Blocks submit when required BNS accounts are missing or invalid.
    """
    if not doc or doc.doctype not in ("Delivery Note", "Purchase Receipt"):
        return
    if not _is_bns_internal_dn_pr_scope(doc):
        return

    legacy_internal_transfer_account = (
        frappe.db.get_single_value("BNS Branch Accounting Settings", "internal_transfer_account") or ""
    ).strip()

    required_fields = {
        "stock_in_transit_account": _("Stock in Transit Account"),
        "internal_branch_debtor_account": _("Internal Branch Debtor Account"),
        "internal_branch_creditor_account": _("Internal Branch Creditor Account"),
    }
    # DN routes through same-GSTIN GL rewrite when GSTINs match OR when the
    # DN carries the per-document diff-GSTIN opt-in flag. Both paths need the
    # sales transfer account configured.
    dn_routes_same_gstin = doc.doctype == "Delivery Note" and (
        (doc.get("billing_address_gstin") or "") == (doc.get("company_gstin") or "")
        or _diff_gstin_dn_pr_active_for_dn(doc)
    )
    if dn_routes_same_gstin:
        required_fields["internal_sales_non_gst_account"] = _("Internal Sales Transfer Account (Non-GST)")
    elif doc.doctype == "Purchase Receipt":
        required_fields["internal_purchase_non_gst_account"] = _("Internal Purchase Transfer Account (Non-GST)")

    configured = {
        fieldname: (frappe.db.get_single_value("BNS Branch Accounting Settings", fieldname) or "").strip()
        for fieldname in required_fields
    }
    # Transition fallback chain for DN/PR same-GSTIN accounts:
    # non_gst field -> GST/Inter-State field -> legacy combined field.
    if "internal_sales_non_gst_account" in configured and not configured["internal_sales_non_gst_account"]:
        configured["internal_sales_non_gst_account"] = (
            (frappe.db.get_single_value("BNS Branch Accounting Settings", "internal_sales_transfer_account") or "").strip()
            or legacy_internal_transfer_account
        )
    if "internal_purchase_non_gst_account" in configured and not configured["internal_purchase_non_gst_account"]:
        configured["internal_purchase_non_gst_account"] = (
            (frappe.db.get_single_value("BNS Branch Accounting Settings", "internal_purchase_transfer_account") or "").strip()
            or legacy_internal_transfer_account
        )
    missing = [required_fields[f] for f, value in configured.items() if not value]

    invalid_messages = []
    for fieldname, account_name in configured.items():
        if not account_name:
            continue
        account_row = frappe.db.get_value(
            "Account",
            account_name,
            ["name", "is_group", "disabled", "company"],
            as_dict=True,
        )
        label = required_fields[fieldname]
        if not account_row:
            invalid_messages.append(_("{0}: '{1}' does not exist.").format(label, account_name))
            continue
        if cint(account_row.get("is_group")):
            invalid_messages.append(
                _("{0}: '{1}' is a Group account. Please select a Ledger account.").format(
                    label, account_name
                )
            )
        if cint(account_row.get("disabled")):
            invalid_messages.append(
                _("{0}: '{1}' is disabled. Please select an active account.").format(
                    label, account_name
                )
            )
        if doc.get("company") and account_row.get("company") and account_row.get("company") != doc.get("company"):
            invalid_messages.append(
                _("{0}: '{1}' belongs to company '{2}', but this document is for '{3}'.").format(
                    label,
                    account_name,
                    account_row.get("company"),
                    doc.get("company"),
                )
            )

    if not missing and not invalid_messages:
        return

    parts = []
    if missing:
        parts.append(
            _("Missing in BNS Branch Accounting Settings: {0}.").format(", ".join(missing))
        )
    if invalid_messages:
        parts.append("\n".join(invalid_messages))

    frappe.throw(
        _(
            "Cannot submit this internal {0} because BNS accounting setup is incomplete.\n\n{1}\n\nPlease update BNS Branch Accounting Settings and try again."
        ).format(doc.doctype, "\n".join(parts)),
        title=_("BNS Internal Accounting Setup Required"),
    )


def _diff_gstin_dn_pr_global_enabled() -> bool:
    """Return True when the org-level setting permits direct DN -> PR for
    different-GSTIN flows.

    Acts as a master switch only. To actually flip a DN through the
    same-GSTIN code path, each Delivery Note must additionally carry
    ``bns_allow_diff_gstin_dn_pr = 1`` — stamped via the
    ``submit_diff_gstin_dn_for_internal_transfer`` whitelisted API.

    Compliance: inter-state goods movement on a delivery challan (DN)
    without a Sales Invoice is permitted under GST for own-use stock
    transfer, job work, and similar non-sale movements. The toggle and
    per-DN opt-in together provide a two-step audit trail for those
    narrow cases.
    """
    try:
        return bool(
            frappe.db.get_single_value(
                "BNS Branch Accounting Settings", "allow_different_gstin_dn_to_pr"
            )
        )
    except Exception:
        return False


# Backwards-compatible alias — older callers may import this name. New code
# should call _diff_gstin_dn_pr_global_enabled() or
# _diff_gstin_dn_pr_active_for_dn() depending on whether per-DN check applies.
_diff_gstin_dn_pr_override_enabled = _diff_gstin_dn_pr_global_enabled


def _dn_has_diff_gstin_opt_in(dn) -> bool:
    """Return True when a Delivery Note has been opted in to the diff-GSTIN
    DN -> PR flow via the per-document flag.

    Accepts either a DN docname (str) or a doc-like object with
    ``.get("bns_allow_diff_gstin_dn_pr")``. Decoupled from the global
    setting so callers can keep the per-DN flag honored even after an admin
    flips the org-level toggle off (existing flagged DNs stay valid by
    design — design decision recorded with the feature ship).
    """
    if dn is None:
        return False
    if isinstance(dn, str):
        if not dn:
            return False
        try:
            return bool(
                frappe.db.get_value("Delivery Note", dn, "bns_allow_diff_gstin_dn_pr")
            )
        except Exception:
            return False
    # Doc-like: prefer attribute, fall back to dict-style get.
    try:
        return bool(dn.get("bns_allow_diff_gstin_dn_pr"))
    except Exception:
        return False


def _diff_gstin_dn_pr_active_for_dn(dn) -> bool:
    """Return True when the diff-GSTIN DN -> PR override should apply for a
    given Delivery Note at runtime.

    Once a DN has been stamped with ``bns_allow_diff_gstin_dn_pr = 1`` via the
    submit-time button, downstream behaviour (status update, GL rewrite,
    e-Waybill, conversion/link/bulk eligibility) stays active for that
    document regardless of the org-level setting state. This preserves
    historical GL pairing for already-flagged DNs/PRs after an admin flips
    the global setting off (design decision locked with the per-DN button).

    The global setting is consulted separately by the entrypoints that
    create new flagged DNs (button visibility, submit API) — not here.
    """
    return _dn_has_diff_gstin_opt_in(dn)


def _get_internal_transfer_cutoff_date():
    """Resolve Internal Transfer cutoff FY to year_start_date, or None if disabled."""
    fy = frappe.db.get_single_value(
        "BNS Branch Accounting Settings", "internal_transfer_cutoff_fy"
    )
    if not fy:
        return None
    start = frappe.db.get_value("Fiscal Year", fy, "year_start_date")
    return getdate(start) if start else None


def _get_accounting_rewrite_cutoff_date():
    """Resolve Accounting Rewrite cutoff FY to year_start_date, or None if disabled."""
    fy = frappe.db.get_single_value(
        "BNS Branch Accounting Settings", "accounting_rewrite_cutoff_fy"
    )
    if not fy:
        return None
    start = frappe.db.get_value("Fiscal Year", fy, "year_start_date")
    return getdate(start) if start else None


def is_after_internal_transfer_cutoff(posting_date) -> bool:
    """True when posting_date >= Internal Transfer cutoff FY start.
    Returns False when the cutoff FY is empty (phase disabled)."""
    cutoff = _get_internal_transfer_cutoff_date()
    if not cutoff or not posting_date:
        return False
    try:
        return getdate(posting_date) >= cutoff
    except Exception:
        return False


def is_after_accounting_rewrite_cutoff(posting_date) -> bool:
    """True when posting_date >= Accounting Rewrite cutoff FY start
    AND Phase 1 (Internal Transfer) is also active for that date."""
    if not is_after_internal_transfer_cutoff(posting_date):
        return False
    cutoff = _get_accounting_rewrite_cutoff_date()
    if not cutoff:
        return False
    try:
        return getdate(posting_date) >= cutoff
    except Exception:
        return False


def _resolve_source_posting_date(doc):
    """For PR/PI, resolve the source DN/SI posting_date that governs the chain.
    For DN/SI (source documents themselves), returns their own posting_date."""
    if doc.doctype in ("Delivery Note", "Sales Invoice"):
        return doc.get("posting_date")

    ref = (doc.get("bns_inter_company_reference") or "").strip()
    if not ref:
        if doc.doctype == "Purchase Receipt":
            ref = (doc.get("supplier_delivery_note") or "").strip()
        elif doc.doctype == "Purchase Invoice":
            ref = (doc.get("bill_no") or "").strip()

    if ref:
        for dt in ("Delivery Note", "Sales Invoice"):
            pd = frappe.db.get_value(dt, ref, "posting_date")
            if pd:
                return pd

    return doc.get("posting_date")


# Deprecated aliases -- kept for backward compatibility with external callers
def _get_internal_validation_cutoff_date():
    """Deprecated: use _get_internal_transfer_cutoff_date instead."""
    return _get_internal_transfer_cutoff_date()


def is_after_internal_validation_cutoff(posting_date) -> bool:
    """Deprecated: use is_after_internal_transfer_cutoff instead."""
    return is_after_internal_transfer_cutoff(posting_date)


def _get_pr_source_link_flags(doc) -> Dict[str, Any]:
    """Detect whether PR is linked to DN and/or SI via source reference fields."""
    candidates = []
    value = (doc.get("bns_inter_company_reference") or "").strip()
    if value:
        candidates.append(value)

    has_dn_link = False
    has_si_link = False
    dn_names = []
    si_names = []

    for ref_name in candidates:
        if frappe.db.exists("Delivery Note", ref_name):
            has_dn_link = True
            dn_names.append(ref_name)
        if frappe.db.exists("Sales Invoice", ref_name):
            has_si_link = True
            si_names.append(ref_name)

    return {
        "has_dn_link": has_dn_link,
        "has_si_link": has_si_link,
        "dn_names": dn_names,
        "si_names": si_names,
    }


def _resolve_pr_gstin_scope(doc, has_dn_link: bool, has_si_link: bool) -> Optional[str]:
    """Resolve PR GST scope as 'same' or 'different'.

    When the PR is linked to a Delivery Note flagged with the per-document
    diff-GSTIN DN -> PR opt-in (``bns_allow_diff_gstin_dn_pr``), treat scope
    as 'same' so the rest of the BNS pipeline routes the PR through the DN-PR
    code path even when GSTINs differ.
    """
    if has_dn_link and not has_si_link:
        link_flags = _get_pr_source_link_flags(doc)
        for dn_name in link_flags.get("dn_names") or []:
            if _dn_has_diff_gstin_opt_in(dn_name):
                return "same"
    company_gstin = (doc.get("company_gstin") or "").strip()
    billing_gstin = (doc.get("billing_address_gstin") or "").strip()
    if company_gstin and billing_gstin:
        return "same" if company_gstin == billing_gstin else "different"
    if has_dn_link and not has_si_link:
        return "same"
    if has_si_link and not has_dn_link:
        return "different"
    return None


def _is_bns_internal_same_gstin_delivery_note(doc) -> bool:
    """Check DN is in scoped BNS internal same-GSTIN flow.
    Cutoff check is the caller's responsibility.

    When the DN carries the per-document diff-GSTIN opt-in flag, the
    same-GSTIN code path applies regardless of GSTIN match.
    """
    if not (
        doc
        and doc.doctype == "Delivery Note"
        and doc.docstatus == 1
        and is_bns_internal_customer(doc)
    ):
        return False
    if _diff_gstin_dn_pr_active_for_dn(doc):
        return True
    return (doc.get("billing_address_gstin") or "") == (doc.get("company_gstin") or "")


def _is_bns_internal_delivery_note(doc) -> bool:
    """Check DN is in scoped BNS internal flow (same/different GSTIN).
    Cutoff check is the caller's responsibility."""
    return bool(
        doc
        and doc.doctype == "Delivery Note"
        and doc.docstatus == 1
        and is_bns_internal_customer(doc)
    )


def _is_same_gstin_internal_delivery_note(doc) -> bool:
    """Return True when internal DN should route through the same-GSTIN GL
    rewrite path.

    Same-GSTIN path runs when billing GSTIN == company GSTIN, OR when the
    DN carries the per-document diff-GSTIN opt-in flag (and both GSTINs
    are populated so the document is not a non-GST corner case).

    Returns False when either GSTIN is empty/None to avoid triggering the
    same-GSTIN GL rewrite path for non-GST companies or documents where
    GSTIN hasn't been populated yet.
    """
    billing = (doc.get("billing_address_gstin") or "").strip()
    company = (doc.get("company_gstin") or "").strip()
    if not billing or not company:
        return False
    if billing == company:
        return True
    return _diff_gstin_dn_pr_active_for_dn(doc)


def _is_bns_internal_different_gstin_sales_invoice(doc) -> bool:
    """Check SI is in scoped BNS internal different-GSTIN flow."""
    if not doc or getattr(doc, "doctype", "") != "Sales Invoice":
        return False
    if not is_bns_internal_customer(doc):
        return False
    company_gstin = (doc.get("company_gstin") or "").strip()
    billing_gstin = (doc.get("billing_address_gstin") or "").strip()
    return bool(company_gstin and billing_gstin and company_gstin != billing_gstin)


def _is_stale_inter_company_ref(doctype: str, docname: str, ref_name: str) -> str:
    """
    Check if a bns_inter_company_reference is stale and safe to clear.

    Returns a non-empty reason string if the link is stale, empty string if
    the link is active and should not be cleared.

    A ref is stale when:
      - The referenced document does not exist or is cancelled.
      - The referenced document does not link back (its own
        bns_inter_company_reference points elsewhere or is empty).
    """
    if not ref_name:
        return "empty"

    counter_doctype = {
        "Delivery Note": "Purchase Receipt",
        "Purchase Receipt": "Delivery Note",
        "Sales Invoice": "Purchase Invoice",
        "Purchase Invoice": "Sales Invoice",
    }.get(doctype, "")
    if not counter_doctype:
        return ""

    if not frappe.db.exists(counter_doctype, ref_name):
        return "ref_not_exists"

    ref_status = frappe.db.get_value(counter_doctype, ref_name, "docstatus")
    if ref_status == 2:
        return "ref_cancelled"

    back_ref = (
        frappe.db.get_value(counter_doctype, ref_name, "bns_inter_company_reference") or ""
    ).strip()
    if not back_ref:
        return "ref_has_no_backref"
    if back_ref != docname:
        return f"ref_points_to_{back_ref}"

    return ""


def _clear_counter_backref(doctype: str, docname: str, old_ref: str) -> None:
    """
    When clearing a bns_inter_company_reference on one side, also clear the
    back-reference on the other document so the pair isn't left half-linked.
    """
    counter_doctype = {
        "Delivery Note": "Purchase Receipt",
        "Purchase Receipt": "Delivery Note",
        "Sales Invoice": "Purchase Invoice",
        "Purchase Invoice": "Sales Invoice",
    }.get(doctype, "")
    if not counter_doctype or not old_ref:
        return
    if not frappe.db.exists(counter_doctype, old_ref):
        return
    back = (
        frappe.db.get_value(counter_doctype, old_ref, "bns_inter_company_reference") or ""
    ).strip()
    if back == docname:
        frappe.db.set_value(
            counter_doctype, old_ref,
            "bns_inter_company_reference", "",
            update_modified=False,
        )
        logger.info(
            "Cleared counter-backref on %s %s (was %s)",
            counter_doctype, old_ref, docname,
        )


def _get_linked_delivery_note_for_pr(doc) -> Optional[str]:
    """Resolve linked Delivery Note for Purchase Receipt in same-GSTIN flow."""
    candidate = doc.get("bns_inter_company_reference")
    if candidate and frappe.db.exists("Delivery Note", candidate):
        return candidate
    return None


def _is_bns_internal_same_gstin_purchase_receipt(doc) -> bool:
    """Check PR is in scoped BNS internal same-GSTIN DN->PR flow.
    Cutoff check is the caller's responsibility.

    When the linked Delivery Note carries the per-document diff-GSTIN opt-in
    flag, the same-GSTIN path applies regardless of the source DN's GSTIN
    match.
    """
    if not (
        doc
        and doc.doctype == "Purchase Receipt"
        and doc.docstatus == 1
        and is_bns_internal_supplier(doc)
    ):
        return False

    dn_name = _get_linked_delivery_note_for_pr(doc)
    if not dn_name:
        return False

    if _diff_gstin_dn_pr_active_for_dn(dn_name):
        return True

    dn_gstin = frappe.db.get_value("Delivery Note", dn_name, "billing_address_gstin")
    dn_company_gstin = frappe.db.get_value("Delivery Note", dn_name, "company_gstin")
    return bool((dn_gstin or "") == (dn_company_gstin or ""))


def _is_bns_internal_si_linked_purchase_receipt(doc) -> bool:
    """Check PR is in scoped SI->PR transfer flow (different GSTIN style).
    Cutoff check is the caller's responsibility."""
    if not (
        doc
        and doc.doctype == "Purchase Receipt"
        and doc.docstatus == 1
    ):
        return False

    source_ref = (doc.get("bns_inter_company_reference") or doc.get("supplier_delivery_note") or "").strip()
    return bool(source_ref and frappe.db.exists("Sales Invoice", source_ref))


def _is_bns_internal_different_gstin_purchase_invoice(doc) -> bool:
    """Check PI is in scoped BNS internal different-GSTIN SI->PI flow.
    Cutoff check is the caller's responsibility."""
    if not (
        doc
        and doc.doctype == "Purchase Invoice"
        and doc.docstatus == 1
        and is_bns_internal_supplier(doc)
        and cint(doc.get("update_stock"))
    ):
        return False
    source_ref = (doc.get("bns_inter_company_reference") or "").strip()
    if not source_ref or not frappe.db.exists("Sales Invoice", source_ref):
        return False
    company_gstin = (doc.get("company_gstin") or "").strip()
    billing_gstin = (doc.get("billing_address_gstin") or "").strip()
    if not (company_gstin and billing_gstin):
        si_gstin = frappe.db.get_value(
            "Sales Invoice",
            source_ref,
            ["company_gstin", "billing_address_gstin"],
            as_dict=True,
        ) or {}
        company_gstin = company_gstin or (si_gstin.get("company_gstin") or "").strip()
        billing_gstin = billing_gstin or (si_gstin.get("billing_address_gstin") or "").strip()
    return bool(company_gstin and billing_gstin and company_gstin != billing_gstin)


def _validate_internal_ref_requires_internal_party(doc) -> None:
    """A bns_inter_company_reference on a non-internal-party document is
    always invalid state — historically produced by Duplicate/Amend before
    the field was no_copy, or by data import. Throw a clear error instead
    of letting GST-scope resolution emit a confusing linkage message.

    When only the DOCUMENT flag is missing but the supplier master is
    flagged internal, heal the doc flag instead of throwing — mapped-doc
    creation flows (e.g. SI -> PR) set the ref on the draft before the flag
    is stamped, and older docs predate flag stamping entirely."""
    source_ref = (doc.get("bns_inter_company_reference") or "").strip()
    if not source_ref:
        return
    if doc.doctype not in ("Purchase Receipt", "Purchase Invoice"):
        return
    if cint(doc.get("is_bns_internal_supplier") or 0):
        return
    if doc.get("supplier") and cint(
        frappe.db.get_value("Supplier", doc.supplier, "is_bns_internal_supplier") or 0
    ):
        doc.is_bns_internal_supplier = 1
        return
    frappe.throw(
        _(
            "{0} carries internal transfer reference {1} but the supplier is not flagged "
            "BNS Internal. Either mark the supplier as BNS internal or clear the reference — "
            "a non-internal document must not claim an internal source."
        ).format(_(doc.doctype), bold(source_ref)),
        title=_("Internal Reference on Non-Internal Document"),
    )


def _validate_unique_internal_source_claim(doc) -> None:
    """The internal transfer link is strictly one-to-one. Block save/submit
    when another submitted document of the same doctype already claims the
    same source (DN/SI). Creation flows already guard this; this closes the
    remaining routes (copy, amend, data import, direct API)."""
    source_ref = (doc.get("bns_inter_company_reference") or "").strip()
    if not source_ref:
        return
    other = frappe.db.get_value(
        doc.doctype,
        {
            "bns_inter_company_reference": source_ref,
            "docstatus": 1,
            "name": ("!=", doc.name or ""),
        },
        "name",
    )
    if other:
        frappe.throw(
            _(
                "{0} {1} already references internal source {2}. The internal transfer link is "
                "strictly one-to-one; cancel or unlink the other document before claiming this source."
            ).format(_(doc.doctype), bold(other), bold(source_ref)),
            title=_("Duplicate Internal Reference"),
        )


def validate_internal_purchase_receipt_linkage(doc, method: Optional[str] = None) -> None:
    """
    Enforce PR linkage rules after configured cutoff.

    Rules:
    - Same GSTIN: PR must be DN-linked only.
    - Different GSTIN: PR (if used) must be SI-linked only.
    """
    if doc.doctype != "Purchase Receipt":
        return
    source_ref = (doc.get("bns_inter_company_reference") or "").strip()
    if source_ref:
        _validate_internal_ref_requires_internal_party(doc)
        _validate_unique_internal_source_claim(doc)
    if not is_bns_internal_supplier(doc) and not source_ref:
        return
    if not is_after_internal_transfer_cutoff(_resolve_source_posting_date(doc)) and not source_ref:
        return

    link_flags = _get_pr_source_link_flags(doc)
    has_dn_link = bool(link_flags.get("has_dn_link"))
    has_si_link = bool(link_flags.get("has_si_link"))
    gst_scope = _resolve_pr_gstin_scope(doc, has_dn_link=has_dn_link, has_si_link=has_si_link)

    if has_dn_link and has_si_link:
        frappe.throw(
            _(
                "Purchase Receipt cannot be linked to both Delivery Note and Sales Invoice. Keep only one linkage based on GST scope."
            ),
            title=_("Invalid Internal PR Linkage"),
        )

    if gst_scope == "same":
        if not has_dn_link:
            frappe.throw(
                _("For same GSTIN internal flow, Purchase Receipt must be linked to a Delivery Note."),
                title=_("Invalid Internal PR Linkage"),
            )
        if has_si_link:
            frappe.throw(
                _("For same GSTIN internal flow, Purchase Receipt cannot be linked to a Sales Invoice."),
                title=_("Invalid Internal PR Linkage"),
            )
        _validate_internal_pr_one_to_one_parity(doc)
        return

    if gst_scope == "different":
        if has_dn_link:
            frappe.throw(
                _("For different GSTIN internal flow, Purchase Receipt cannot be linked to a Delivery Note."),
                title=_("Invalid Internal PR Linkage"),
            )
        if not has_si_link:
            frappe.throw(
                _("For different GSTIN internal flow, Purchase Receipt must be linked to a Sales Invoice."),
                title=_("Invalid Internal PR Linkage"),
            )
        _validate_internal_pr_one_to_one_parity(doc)
        return

    if not has_dn_link and not has_si_link:
        frappe.throw(
            _("Purchase Receipt must be linked to Delivery Note (same GSTIN) or Sales Invoice (different GSTIN)."),
            title=_("Missing Internal PR Linkage"),
        )

    _validate_internal_pr_one_to_one_parity(doc)


def _validate_internal_pr_one_to_one_parity(doc) -> None:
    """Validate strict one-to-one parity for internal PR against its source."""
    source_name = (doc.get("bns_inter_company_reference") or "").strip()
    if not source_name:
        return

    source_doctype = None
    source_link_field = None
    source_doc = None
    if frappe.db.exists("Delivery Note", source_name):
        source_doctype = "Delivery Note"
        source_link_field = "delivery_note_item"
        source_doc = frappe.get_doc("Delivery Note", source_name)
        source_items = [d for d in source_doc.get("items") or [] if flt(d.get("qty") or 0) + flt(d.get("returned_qty") or 0) > 0]
    elif frappe.db.exists("Sales Invoice", source_name):
        source_doctype = "Sales Invoice"
        source_link_field = "sales_invoice_item"
        source_doc = frappe.get_doc("Sales Invoice", source_name)
        source_items = [d for d in source_doc.get("items") or [] if flt(d.get("qty") or 0) > 0]
    else:
        return

    pr_items = doc.get("items") or []
    if len(pr_items) != len(source_items):
        frappe.throw(
            _(
                "Strict 1:1 validation failed: Purchase Receipt item count ({0}) must match {1} item count ({2})."
            ).format(len(pr_items), source_doctype, len(source_items)),
            title=_("One-to-One Validation Failed"),
        )

    source_by_name = {d.get("name"): d for d in source_items if d.get("name")}
    seen_source_rows = set()

    def _same_num(a, b, precision=6):
        return round(flt(a or 0), precision) == round(flt(b or 0), precision)

    for pr_item in pr_items:
        src_row_name = pr_item.get(source_link_field)
        source_item = source_by_name.get(src_row_name)
        if not source_item:
            frappe.throw(
                _(
                    "Strict 1:1 validation failed: PR item {0} is not linked to a valid {1} item."
                ).format(pr_item.get("item_code") or pr_item.get("name"), source_doctype),
                title=_("One-to-One Validation Failed"),
            )
        if src_row_name in seen_source_rows:
            frappe.throw(
                _("Strict 1:1 validation failed: duplicate mapping for source item {0}.").format(src_row_name),
                title=_("One-to-One Validation Failed"),
            )
        seen_source_rows.add(src_row_name)

        if (pr_item.get("item_code") or "") != (source_item.get("item_code") or ""):
            frappe.throw(
                _("Strict 1:1 validation failed: item code mismatch for source row {0}.").format(src_row_name),
                title=_("One-to-One Validation Failed"),
            )

        for fieldname, precision in (
            ("conversion_factor", 6),
            ("qty", 6),
            ("stock_qty", 6),
            ("rate", 6),
            ("base_rate", 6),
            ("amount", 2),
            ("base_amount", 2),
            ("net_rate", 6),
            ("base_net_rate", 6),
            ("net_amount", 2),
            ("base_net_amount", 2),
        ):
            source_val = flt(source_item.get(fieldname) or 0)
            entered_val = flt(pr_item.get(fieldname) or 0)
            if not _same_num(entered_val, source_val, precision=precision):
                source_row_no = cint(source_item.get("idx") or 0)
                label_map = {
                    "qty": _("Quantity"),
                    "stock_qty": _("Stock Quantity"),
                    "conversion_factor": _("UOM Conversion Factor"),
                    "rate": _("Rate"),
                    "base_rate": _("Base Rate"),
                    "amount": _("Amount"),
                    "base_amount": _("Base Amount"),
                    "net_rate": _("Taxable Rate"),
                    "base_net_rate": _("Base Taxable Rate"),
                    "net_amount": _("Taxable Amount"),
                    "base_net_amount": _("Base Taxable Amount"),
                }
                value_precision = 6 if fieldname in ("qty", "stock_qty", "conversion_factor", "rate", "base_rate", "net_rate", "base_net_rate") else 2
                frappe.throw(
                    _(
                        "Row {0} ({1}) does not match the source document.\n\nField: {2}\nExpected (source): {3}\nEntered in Purchase Receipt: {4}\n\nPlease make this row exactly same as source document."
                    ).format(
                        source_row_no or "-",
                        pr_item.get("item_code") or pr_item.get("name"),
                        label_map.get(fieldname, fieldname),
                        round(source_val, value_precision),
                        round(entered_val, value_precision),
                    ),
                    title=_("One-to-One Validation Failed"),
                )

        for fieldname in ("uom", "stock_uom"):
            src_val = (source_item.get(fieldname) or "")
            pr_val = (pr_item.get(fieldname) or "")
            if src_val and pr_val and src_val != pr_val:
                source_row_no = cint(source_item.get("idx") or 0)
                label_map = {"uom": _("UOM"), "stock_uom": _("Stock UOM")}
                frappe.throw(
                    _(
                        "Row {0} ({1}) does not match the source document.\n\nField: {2}\nExpected (source): {3}\nEntered in Purchase Receipt: {4}\n\nPlease make this row exactly same as source document."
                    ).format(
                        source_row_no or "-",
                        pr_item.get("item_code") or pr_item.get("name"),
                        label_map.get(fieldname, fieldname),
                        src_val,
                        pr_val,
                    ),
                    title=_("One-to-One Validation Failed"),
                )

    if len(seen_source_rows) != len(source_items):
        frappe.throw(
            _("Strict 1:1 validation failed: not all source items are mapped."),
            title=_("One-to-One Validation Failed"),
        )

    for fieldname in (
        "total",
        "base_total",
        "net_total",
        "base_net_total",
        "total_taxes_and_charges",
        "base_total_taxes_and_charges",
        "grand_total",
        "base_grand_total",
    ):
        if not _same_num(doc.get(fieldname), source_doc.get(fieldname), precision=2):
            frappe.throw(
                _(
                    "Strict 1:1 validation failed: header field {0} mismatch between Purchase Receipt and {1}."
                ).format(fieldname, source_doctype),
                title=_("One-to-One Validation Failed"),
            )


def validate_internal_purchase_invoice_linkage(doc, method: Optional[str] = None) -> None:
    """Enforce interstate internal PI linkage after configured cutoff."""
    if doc.doctype != "Purchase Invoice":
        return
    # These two guards must run before the is_bns_internal_supplier early
    # return: a ref on a NON-internal PI is exactly the broken state the
    # first guard exists to catch.
    if (doc.get("bns_inter_company_reference") or "").strip():
        _validate_internal_ref_requires_internal_party(doc)
        _validate_unique_internal_source_claim(doc)
    if not is_bns_internal_supplier(doc):
        return
    if not is_after_internal_transfer_cutoff(_resolve_source_posting_date(doc)):
        return

    company_gstin = (doc.get("company_gstin") or "").strip()
    billing_gstin = (doc.get("billing_address_gstin") or "").strip()
    if not (company_gstin and billing_gstin and company_gstin != billing_gstin):
        return

    ref_name = (doc.get("bns_inter_company_reference") or "").strip()
    has_si_link = bool(ref_name and frappe.db.exists("Sales Invoice", ref_name))

    valid_pr_link = False
    pr_names = sorted(
        {
            (item.get("purchase_receipt") or "").strip()
            for item in (doc.get("items") or [])
            if item.get("purchase_receipt")
        }
    )
    for pr_name in pr_names:
        pr_link = frappe.db.get_value(
            "Purchase Receipt",
            pr_name,
            ["bns_inter_company_reference"],
            as_dict=True,
        )
        if not pr_link:
            continue
        ref_candidates = [(pr_link.get("bns_inter_company_reference") or "").strip()]
        pr_has_si = any(ref and frappe.db.exists("Sales Invoice", ref) for ref in ref_candidates)
        pr_has_dn = any(ref and frappe.db.exists("Delivery Note", ref) for ref in ref_candidates)
        if pr_has_si and not pr_has_dn:
            valid_pr_link = True
            break

    if has_si_link or valid_pr_link:
        return

    frappe.throw(
        _(
            "For different GSTIN internal flow, Purchase Invoice must be linked to Sales Invoice directly or through a PR that is SI-linked."
        ),
        title=_("Invalid Internal PI Linkage"),
    )


def _is_internal_transfer_sales_invoice(si_name: str) -> bool:
    """True only when the Sales Invoice exists AND is itself a BNS internal
    transfer (is_bns_internal_customer = 1).

    Guards the PI->SI resolution below: matching bill_no / ref against ANY
    Sales Invoice misclassifies common-party PIs (the same outside party is
    both customer and supplier, and bill_no is used to cross-link the sale
    and purchase) and coincidental bill numbers as internal branch transfers.
    """
    if not si_name:
        return False
    return bool(frappe.db.get_value("Sales Invoice", si_name, "is_bns_internal_customer"))


def _resolve_si_name_for_internal_pi(doc) -> Optional[str]:
    """Resolve the linked INTERNAL-TRANSFER Sales Invoice for a PI from its
    header ref, bill_no, or PR chain. Only an internal-transfer SI qualifies —
    see [[_is_internal_transfer_sales_invoice]]."""
    ref = (doc.get("bns_inter_company_reference") or "").strip()
    if ref and _is_internal_transfer_sales_invoice(ref):
        return ref
    bill = (doc.get("bill_no") or "").strip()
    if bill and _is_internal_transfer_sales_invoice(bill):
        return bill
    pr_names = sorted(
        {(row.get("purchase_receipt") or "").strip()
         for row in (doc.get("items") or [])
         if (row.get("purchase_receipt") or "").strip()}
    )
    for pr_name in pr_names:
        pr_ref = (frappe.db.get_value("Purchase Receipt", pr_name, "bns_inter_company_reference") or "").strip()
        if pr_ref and _is_internal_transfer_sales_invoice(pr_ref):
            return pr_ref
    return None


def _get_rate_from_dn_stock_ledger(
    dn_name: str, item_code: str, warehouse: Optional[str] = None
) -> float:
    """Read valuation from Delivery Note Stock Ledger Entry for this item."""
    if not dn_name or not item_code:
        return 0.0
    filters: Dict[str, Any] = {
        "voucher_type": "Delivery Note",
        "voucher_no": dn_name,
        "item_code": item_code,
        "is_cancelled": 0,
    }
    if warehouse:
        filters["warehouse"] = warehouse
    rows = frappe.get_all(
        "Stock Ledger Entry",
        filters=filters,
        fields=["incoming_rate", "stock_value", "actual_qty"],
        order_by="posting_date desc, posting_time desc, creation desc",
        limit=20,
    )
    for row in rows:
        ir = flt(row.incoming_rate or 0)
        if ir > 0:
            return ir
        aq = flt(row.actual_qty or 0)
        sv = flt(row.stock_value or 0)
        if aq != 0 and sv != 0:
            return abs(sv) / abs(aq)
    if warehouse:
        return _get_rate_from_dn_stock_ledger(dn_name, item_code, None)
    return 0.0


def _build_si_rate_maps_for_pi(si_name: str) -> Tuple[Dict[str, float], List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    """Load SI item rates, per-name map, and item_code buckets for PI line matching.

    When SI item incoming_rate is 0 and the item links to a DN (via delivery_note
    + dn_detail), backfills from DN Item.incoming_rate then DN SLE.
    """
    si_items = frappe.get_all(
        "Sales Invoice Item",
        filters={"parent": si_name},
        fields=["name", "item_code", "qty", "stock_qty", "incoming_rate",
                "delivery_note", "dn_detail"],
    )
    si_rate_by_item: Dict[str, float] = {}
    for d in si_items:
        rate = flt(d.incoming_rate or 0) or flt(
            frappe.db.get_value("Sales Invoice Item", d.name, "incoming_rate") or 0
        )
        if rate <= 0:
            rate = _resolve_rate_from_dn_chain(d)
        si_rate_by_item[d.name] = rate

    si_item_buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for d in si_items:
        rate = si_rate_by_item.get(d.name, 0)
        si_item_buckets[d.item_code].append(
            {
                "name": d.name,
                "qty": flt(d.qty or 0),
                "stock_qty": flt(d.stock_qty or d.qty or 0),
                "remaining_qty": flt(d.qty or 0),
                "remaining_stock_qty": flt(d.stock_qty or d.qty or 0),
                "rate": rate,
            }
        )
    return si_rate_by_item, si_items, si_item_buckets


def _resolve_rate_from_dn_chain(si_item: Dict[str, Any]) -> float:
    """Resolve incoming_rate for an SI item from its linked Delivery Note.

    Fallback order:
    1. DN Item.incoming_rate (via dn_detail)
    2. DN Stock Ledger Entry (via delivery_note + item_code)
    """
    dn_name = (si_item.get("delivery_note") or "").strip()
    dn_detail = (si_item.get("dn_detail") or "").strip()
    item_code = si_item.get("item_code")

    if not dn_name:
        return 0.0

    if dn_detail:
        dn_ir = flt(
            frappe.db.get_value("Delivery Note Item", dn_detail, "incoming_rate") or 0
        )
        if dn_ir > 0:
            return dn_ir

    if item_code:
        return _get_rate_from_dn_stock_ledger(dn_name, item_code)

    return 0.0


def _consume_si_bucket_for_pi_line(
    bucket_list: List[Dict[str, Any]], pi_qty: float, pi_stock_qty: float
) -> Tuple[Optional[str], float]:
    """Match one PI line to an SI bucket row (same logic as _match_and_set_item_references)."""
    if not bucket_list:
        return None, 0.0
    for si_item_data in bucket_list:
        if si_item_data["remaining_qty"] <= 0:
            continue
        if pi_stock_qty > 0 and si_item_data["remaining_stock_qty"] > 0:
            if round(pi_stock_qty, 6) == round(si_item_data["remaining_stock_qty"], 6):
                name = si_item_data["name"]
                rate = flt(si_item_data["rate"] or 0)
                si_item_data["remaining_qty"] = 0
                si_item_data["remaining_stock_qty"] = 0
                return name, rate
        elif round(pi_qty, 6) == round(si_item_data["remaining_qty"], 6):
            name = si_item_data["name"]
            rate = flt(si_item_data["rate"] or 0)
            si_item_data["remaining_qty"] = 0
            si_item_data["remaining_stock_qty"] = 0
            return name, rate
    for si_item_data in bucket_list:
        if si_item_data["remaining_qty"] > 0:
            name = si_item_data["name"]
            rate = flt(si_item_data["rate"] or 0)
            if pi_stock_qty > 0 and si_item_data["remaining_stock_qty"] > 0:
                si_item_data["remaining_stock_qty"] -= pi_stock_qty
            else:
                si_item_data["remaining_qty"] -= pi_qty
            return name, rate
    return None, 0.0


def _get_outgoing_rate_from_si_stock_ledger(
    si_name: str, item_code: str, warehouse: Optional[str] = None
) -> float:
    """Read valuation from latest non-cancelled Sales Invoice Stock Ledger row for this item."""
    if not si_name or not item_code:
        return 0.0
    filters: Dict[str, Any] = {
        "voucher_type": "Sales Invoice",
        "voucher_no": si_name,
        "item_code": item_code,
        "is_cancelled": 0,
    }
    if warehouse:
        filters["warehouse"] = warehouse
    rows = frappe.get_all(
        "Stock Ledger Entry",
        filters=filters,
        fields=["incoming_rate", "stock_value", "actual_qty"],
        order_by="posting_date desc, posting_time desc, creation desc",
        limit=20,
    )
    for row in rows:
        ir = flt(row.incoming_rate or 0)
        if ir > 0:
            return ir
        aq = flt(row.actual_qty or 0)
        sv = flt(row.stock_value or 0)
        if aq != 0 and sv != 0:
            return abs(sv) / abs(aq)
    if warehouse:
        return _get_outgoing_rate_from_si_stock_ledger(si_name, item_code, None)
    return 0.0


def _resolve_pi_item_transfer_rate_extras(
    item: Dict[str, Any],
    si_name: str,
    si_rate_by_item: Dict[str, float],
    pr_item_rates: Dict[str, float],
    si_item_buckets: Dict[str, List[Dict[str, Any]]],
    si_dn_map: Optional[Dict[str, str]] = None,
) -> Tuple[float, Optional[str]]:
    """Resolve PI item transfer-rate through the full fallback chain.

    Fallback order:
    1. SI item link (sales_invoice_item) → SI incoming_rate (already DN-backfilled)
    2. PR item link (pr_detail) → PR bns_transfer_rate
    3. Item-code/qty bucket match → SI incoming_rate
    4. SI Stock Ledger Entry
    5. DN Stock Ledger Entry (via SI item → delivery_note link)

    Args:
        si_dn_map: {si_item_name: delivery_note_name} for DN SLE fallback.

    Returns (rate, si_item_name_to_link).
    """
    source_rate: Optional[float] = None
    si_item_for_link: Optional[str] = None

    sii = (item.get("sales_invoice_item") or "").strip()
    if sii:
        r = si_rate_by_item.get(sii)
        if r is not None and flt(r) > 0:
            return flt(r), sii

    pr_detail = (item.get("pr_detail") or "").strip()
    if pr_detail:
        pr_r = pr_item_rates.get(pr_detail, 0)
        if flt(pr_r) > 0:
            return flt(pr_r), si_item_for_link

    item_code = item.get("item_code")
    pi_qty = flt(item.get("qty") or 0)
    pi_stock_qty = flt(item.get("stock_qty") or pi_qty)
    if item_code and item_code in si_item_buckets:
        matched_name, matched_rate = _consume_si_bucket_for_pi_line(
            si_item_buckets[item_code], pi_qty, pi_stock_qty
        )
        if matched_name:
            si_item_for_link = matched_name
            source_rate = flt(matched_rate or 0)
            if source_rate <= 0:
                source_rate = flt(si_rate_by_item.get(matched_name) or 0) or flt(
                    frappe.db.get_value("Sales Invoice Item", matched_name, "incoming_rate") or 0
                )
            if source_rate > 0:
                return source_rate, si_item_for_link

    if item_code:
        sle_rate = _get_outgoing_rate_from_si_stock_ledger(
            si_name, item_code, item.get("warehouse")
        )
        if sle_rate > 0:
            return sle_rate, si_item_for_link

    if item_code and si_dn_map:
        ref_si_item = si_item_for_link or sii
        dn_name = si_dn_map.get(ref_si_item or "") if ref_si_item else None
        if not dn_name:
            for _si_item_name, _dn in si_dn_map.items():
                if _dn:
                    dn_name = _dn
                    break
        if dn_name:
            dn_sle_rate = _get_rate_from_dn_stock_ledger(
                dn_name, item_code, item.get("warehouse")
            )
            if dn_sle_rate > 0:
                return dn_sle_rate, si_item_for_link

    return 0.0, si_item_for_link


def apply_internal_pi_transfer_rates_from_si(doc, si_name: Optional[str] = None) -> int:
    """
    Populate Purchase Invoice Item.bns_transfer_rate before validate/submit.

    Uses SI item link, PR item rate, item_code/qty bucket match, then Stock Ledger
    (Sales Invoice voucher) as fallback when incoming_rate / links are missing.
    """
    if doc.doctype != "Purchase Invoice":
        return 0
    if not cint(doc.get("update_stock")):
        return 0
    if not is_bns_internal_supplier(doc):
        return 0
    if not is_after_internal_transfer_cutoff(_resolve_source_posting_date(doc)):
        return 0

    resolved_si = si_name or _resolve_si_name_for_internal_pi(doc)
    if not resolved_si:
        return 0

    pii_meta = frappe.get_meta("Purchase Invoice Item")
    if not pii_meta.has_field("bns_transfer_rate"):
        return 0

    si_rate_by_item, si_rows, si_item_buckets = _build_si_rate_maps_for_pi(resolved_si)

    si_dn_map: Dict[str, str] = {}
    for d in si_rows:
        dn = (d.get("delivery_note") or "").strip()
        if dn:
            si_dn_map[d.name] = dn

    pi_items_list = list(doc.get("items") or [])
    pr_detail_names = sorted(
        {(it.get("pr_detail") or "").strip() for it in pi_items_list if (it.get("pr_detail") or "").strip()}
    )
    pr_item_rates: Dict[str, float] = {}
    if pr_detail_names:
        pr_rows = frappe.get_all(
            "Purchase Receipt Item",
            filters={"name": ("in", pr_detail_names)},
            fields=["name", "bns_transfer_rate"],
        )
        pr_item_rates = {r.name: flt(r.bns_transfer_rate or 0) for r in pr_rows}

    updated = 0
    for item in pi_items_list:
        if flt(item.get("qty") or 0) <= 0:
            continue
        if item.get("item_code") and not cint(
            frappe.db.get_value("Item", item.get("item_code"), "is_stock_item")
        ):
            continue

        rate, link_si = _resolve_pi_item_transfer_rate_extras(
            item, resolved_si, si_rate_by_item, pr_item_rates, si_item_buckets,
            si_dn_map=si_dn_map,
        )
        # Only write when the source is CONFIRMED: a resolved source link (which
        # may legitimately carry a genuine 0) or a positive rate. An unresolved
        # row (no link, non-positive rate) must NOT clobber an existing rate.
        # Deliberately do NOT skip rows that already have a positive
        # bns_transfer_rate -- a STALE positive must be overwritten from source.
        if not link_si and flt(rate) <= 0:
            continue
        new_rate = flt(rate)
        link_needed = bool(
            link_si
            and pii_meta.has_field("sales_invoice_item")
            and not (item.get("sales_invoice_item") or "").strip()
        )
        if flt(item.get("bns_transfer_rate") or 0) == new_rate and not link_needed:
            continue

        item.bns_transfer_rate = new_rate
        updated += 1
        if link_needed:
            item.sales_invoice_item = link_si

        row_name = item.get("name")
        if row_name and frappe.db.exists("Purchase Invoice Item", row_name):
            db_vals: Dict[str, Any] = {"bns_transfer_rate": new_rate}
            if link_needed:
                db_vals["sales_invoice_item"] = link_si
            frappe.db.set_value("Purchase Invoice Item", row_name, db_vals, update_modified=False)

    if updated:
        frappe.clear_cache(doctype="Purchase Invoice")
    return updated


def validate_internal_purchase_invoice_transfer_rate(doc, method: Optional[str] = None) -> None:
    """Require PI item transfer-rate for internal SI-linked update-stock PI rows."""
    if doc.doctype != "Purchase Invoice":
        return
    if not cint(doc.get("update_stock")):
        return
    if not is_bns_internal_supplier(doc):
        return
    if not is_after_internal_transfer_cutoff(_resolve_source_posting_date(doc)):
        return

    si_name = _resolve_si_name_for_internal_pi(doc)
    if not si_name:
        return

    pii_meta = frappe.get_meta("Purchase Invoice Item")
    if not pii_meta.has_field("bns_transfer_rate"):
        return

    apply_internal_pi_transfer_rates_from_si(doc, si_name=si_name)

    si_rate_by_item, _si_rows, si_item_buckets = _build_si_rate_maps_for_pi(si_name)

    missing_rows = []
    for item in (doc.get("items") or []):
        if flt(item.get("qty") or 0) <= 0:
            continue
        if flt(item.get("bns_transfer_rate") or 0) > 0:
            continue
        if item.get("item_code") and not cint(
            frappe.db.get_value("Item", item.get("item_code"), "is_stock_item")
        ):
            continue

        si_item_link = (item.get("sales_invoice_item") or "").strip()
        expected_rate = 0.0
        if si_item_link and si_item_link in si_rate_by_item:
            expected_rate = flt(si_rate_by_item[si_item_link])
        elif item.get("item_code") and item.get("item_code") in si_item_buckets:
            bucket = si_item_buckets[item.get("item_code")]
            if bucket:
                expected_rate = max(flt(b.get("rate") or 0) for b in bucket)

        if expected_rate <= 0:
            continue

        missing_rows.append(
            f"#{cint(item.get('idx') or 0) or '?'} "
            f"{item.get('item_code') or item.get('item_name') or item.get('name')}"
        )

    if missing_rows:
        frappe.throw(
            _(
                "Internal SI->PI transfer-rate is missing for these rows: {0}. "
                "The linked Sales Invoice has a positive incoming_rate for these items. "
                "Please fetch SI incoming_rate into bns_transfer_rate before submit."
            ).format(", ".join(missing_rows)),
            title=_("Missing Internal Transfer Rate"),
        )


def validate_internal_purchase_invoice_si_parity(doc, method: Optional[str] = None) -> None:
    """Block PI submit when items/amounts/taxes diverge from the linked Sales Invoice.

    Runs on before_submit for BNS internal different-GSTIN PI flows.
    Drafts can be edited freely; only submission is gated.
    """
    if doc.doctype != "Purchase Invoice":
        return
    if not is_bns_internal_supplier(doc):
        return
    if not is_after_internal_transfer_cutoff(_resolve_source_posting_date(doc)):
        return

    si_name = _resolve_si_name_for_internal_pi(doc)
    if not si_name:
        return

    company_gstin = (doc.get("company_gstin") or "").strip()
    billing_gstin = (doc.get("billing_address_gstin") or "").strip()
    if company_gstin and billing_gstin and company_gstin == billing_gstin:
        return

    tolerance = flt(
        frappe.db.get_single_value("BNS Branch Accounting Settings", "si_pi_amount_tolerance") or 0
    )
    result = validate_si_pi_items_match(si_name, doc.name, check_all=True, amount_tolerance=tolerance)
    if result.get("match"):
        return

    errors: List[str] = []
    for item in (result.get("missing_items") or [])[:5]:
        errors.append(_("Item {0}: SI qty {1}, PI missing").format(item["item_code"], item["si_qty"]))
    for item in (result.get("qty_mismatches") or [])[:5]:
        errors.append(_("Item {0}: SI qty {1}, PI qty {2}").format(item["item_code"], item["si_qty"], item["pi_qty"]))
    for item in (result.get("taxable_value_mismatches") or [])[:5]:
        errors.append(
            _("Item {0}: SI taxable {1:.2f}, PI taxable {2:.2f}").format(
                item["item_code"], item["si_taxable_value"], item["pi_taxable_value"]
            )
        )
    gt = result.get("grand_total_mismatch")
    if gt:
        errors.append(
            _("Grand Total: SI {0:.2f} vs PI {1:.2f} (diff {2:.2f})").format(
                gt["si_total"], gt["pi_total"], abs(gt["diff"])
            )
        )
    tx = result.get("tax_mismatch")
    if tx:
        errors.append(
            _("Total Taxes: SI {0:.2f} vs PI {1:.2f} (diff {2:.2f})").format(
                tx["si_tax"], tx["pi_tax"], abs(tx["diff"])
            )
        )

    frappe.throw(
        _(
            "Purchase Invoice does not match source Sales Invoice {0}:\n{1}"
        ).format(si_name, "\n".join(errors)),
        title=_("Internal SI-PI Parity Mismatch"),
    )


def _throw_si_dn_mismatch(
    source_item,
    entered_item,
    field_label: str,
    expected_value,
    entered_value,
    precision: int = 2,
) -> None:
    row_no = cint(source_item.get("idx") or 0) or "-"
    item_code = entered_item.get("item_code") or source_item.get("item_code") or entered_item.get("name")
    expected_out = round(flt(expected_value or 0), precision) if isinstance(expected_value, (int, float)) else expected_value
    entered_out = round(flt(entered_value or 0), precision) if isinstance(entered_value, (int, float)) else entered_value
    frappe.throw(
        _(
            "Row {0} ({1}) does not match Delivery Note.\n\nField: {2}\nExpected (Delivery Note): {3}\nEntered in Sales Invoice: {4}\n\nPlease make this row exactly same as Delivery Note."
        ).format(row_no, item_code, field_label, expected_out, entered_out),
        title=_("One-to-One Validation Failed"),
    )


def _validate_single_internal_si_per_dn(doc, dn_names: List[str]) -> None:
    """Block creating another internal SI (draft/submitted) for same DN context."""
    if not dn_names:
        return

    si_item_rows = frappe.get_all(
        "Sales Invoice Item",
        filters={
            "delivery_note": ("in", dn_names),
            "parent": ("!=", doc.name or ""),
            "docstatus": ("in", [0, 1]),
        },
        fields=["parent", "delivery_note"],
    )
    if not si_item_rows:
        return

    checked_parents = set()
    for row in si_item_rows:
        parent = row.get("parent")
        if not parent or parent in checked_parents:
            continue
        checked_parents.add(parent)
        parent_meta = frappe.db.get_value(
            "Sales Invoice",
            parent,
            ["name", "docstatus", "is_return", "is_bns_internal_customer", "customer"],
            as_dict=True,
        )
        if not parent_meta or cint(parent_meta.get("is_return")):
            continue
        parent_is_internal = bool(parent_meta.get("is_bns_internal_customer"))
        if not parent_is_internal and parent_meta.get("customer"):
            parent_is_internal = bool(
                frappe.db.get_value("Customer", parent_meta.get("customer"), "is_bns_internal_customer")
            )
        if not parent_is_internal:
            continue

        frappe.throw(
            _(
                "Delivery Note {0} is already linked to Sales Invoice {1} ({2}). You cannot create another internal Sales Invoice for the same Delivery Note."
            ).format(
                row.get("delivery_note"),
                parent_meta.get("name"),
                _docstatus_label(parent_meta.get("docstatus")),
            ),
            title=_("Duplicate Internal Sales Invoice Not Allowed"),
        )


def _validate_internal_si_dn_one_to_one_parity(doc, dn_names: List[str]) -> None:
    """Validate strict one-to-one parity for internal SI rows mapped from DN."""
    if not dn_names:
        return

    source_dns = [frappe.get_doc("Delivery Note", dn_name) for dn_name in dn_names if frappe.db.exists("Delivery Note", dn_name)]
    if not source_dns:
        return

    source_rows = []
    source_row_map = {}
    source_totals = defaultdict(float)
    for dn in source_dns:
        dn_rows = [d for d in (dn.get("items") or []) if flt(d.get("qty") or 0) > 0]
        for row in dn_rows:
            key = (dn.name, row.get("name"))
            source_rows.append((dn.name, row))
            source_row_map[key] = row
        for fieldname in (
            "total",
            "base_total",
            "net_total",
            "base_net_total",
            "grand_total",
            "base_grand_total",
        ):
            source_totals[fieldname] += flt(dn.get(fieldname) or 0)

    si_items = [d for d in (doc.get("items") or []) if d.get("delivery_note")]
    if len(si_items) != len(source_rows):
        frappe.throw(
            _(
                "Strict 1:1 validation failed: Sales Invoice has {0} Delivery Note-linked rows, but source Delivery Note rows are {1}. Please keep rows exactly one-to-one."
            ).format(len(si_items), len(source_rows)),
            title=_("One-to-One Validation Failed"),
        )

    seen_source_rows = set()

    def _same_num(a, b, precision=6):
        return round(flt(a or 0), precision) == round(flt(b or 0), precision)

    for si_item in si_items:
        dn_name = (si_item.get("delivery_note") or "").strip()
        dn_detail = (si_item.get("dn_detail") or "").strip()
        if not dn_detail:
            frappe.throw(
                _(
                    "Row {0} ({1}) is missing Delivery Note Row reference (dn_detail). Please fetch items from Delivery Note again."
                ).format(cint(si_item.get("idx") or 0) or "-", si_item.get("item_code") or si_item.get("name")),
                title=_("One-to-One Validation Failed"),
            )
        source_item = source_row_map.get((dn_name, dn_detail))
        if not source_item:
            frappe.throw(
                _(
                    "Row {0} ({1}) is not linked to a valid Delivery Note row. Please reselect the correct Delivery Note item."
                ).format(cint(si_item.get("idx") or 0) or "-", si_item.get("item_code") or si_item.get("name")),
                title=_("One-to-One Validation Failed"),
            )
        source_key = (dn_name, dn_detail)
        if source_key in seen_source_rows:
            frappe.throw(
                _(
                    "Delivery Note row {0} is mapped more than once. Each Delivery Note row can be used only once in Sales Invoice."
                ).format(cint(source_item.get("idx") or 0) or "-"),
                title=_("One-to-One Validation Failed"),
            )
        seen_source_rows.add(source_key)

        if (si_item.get("item_code") or "") != (source_item.get("item_code") or ""):
            _throw_si_dn_mismatch(
                source_item,
                si_item,
                _("Item Code"),
                source_item.get("item_code"),
                si_item.get("item_code"),
                precision=0,
            )

        for fieldname, precision, label in (
            ("conversion_factor", 6, _("UOM Conversion Factor")),
            ("qty", 6, _("Quantity")),
            ("stock_qty", 6, _("Stock Quantity")),
            ("rate", 6, _("Rate")),
            ("base_rate", 6, _("Base Rate")),
            ("amount", 2, _("Amount")),
            ("base_amount", 2, _("Base Amount")),
            ("net_rate", 6, _("Taxable Rate")),
            ("base_net_rate", 6, _("Base Taxable Rate")),
            ("net_amount", 2, _("Taxable Amount")),
            ("base_net_amount", 2, _("Base Taxable Amount")),
        ):
            if not _same_num(si_item.get(fieldname), source_item.get(fieldname), precision=precision):
                _throw_si_dn_mismatch(
                    source_item,
                    si_item,
                    label,
                    source_item.get(fieldname),
                    si_item.get(fieldname),
                    precision=precision,
                )

        for fieldname, label in (("uom", _("UOM")), ("stock_uom", _("Stock UOM"))):
            src_val = (source_item.get(fieldname) or "")
            si_val = (si_item.get(fieldname) or "")
            if src_val and si_val and src_val != si_val:
                _throw_si_dn_mismatch(source_item, si_item, label, src_val, si_val, precision=0)

    if len(seen_source_rows) != len(source_rows):
        frappe.throw(
            _(
                "Strict 1:1 validation failed: all Delivery Note rows are not mapped in Sales Invoice. Please include every row exactly once."
            ),
            title=_("One-to-One Validation Failed"),
        )

    for fieldname, label in (
        ("net_total", _("Taxable Total")),
        ("base_net_total", _("Base Taxable Total")),
        ("grand_total", _("Grand Total")),
        ("base_grand_total", _("Base Grand Total")),
    ):
        source_val = round(flt(source_totals.get(fieldname) or 0), 2)
        entered_val = round(flt(doc.get(fieldname) or 0), 2)
        if source_val != entered_val:
            frappe.throw(
                _(
                    "{0} does not match Delivery Note total.\n\nExpected (Delivery Notes): {1}\nEntered in Sales Invoice: {2}\n\nPlease keep taxable and grand totals exactly same as Delivery Note."
                ).format(label, source_val, entered_val),
                title=_("One-to-One Validation Failed"),
            )


def validate_internal_sales_invoice_linkage(doc, method: Optional[str] = None) -> None:
    """Enforce internal SI different-GSTIN and DN strict parity after cutoff."""
    if doc.doctype != "Sales Invoice":
        return
    if cint(doc.get("is_return")):
        return
    if not is_bns_internal_customer(doc):
        return
    if not is_after_internal_transfer_cutoff(doc.get("posting_date")):
        return

    company_gstin = (doc.get("company_gstin") or "").strip()
    billing_gstin = (doc.get("billing_address_gstin") or "").strip()
    if not company_gstin or not billing_gstin:
        frappe.throw(
            _("GSTIN is missing on Sales Invoice. Internal Sales Invoice requires both Company GSTIN and Billing GSTIN."),
            title=_("GSTIN Required"),
        )
    if company_gstin == billing_gstin:
        frappe.throw(
            _("Internal Sales Invoice is allowed only when Company GSTIN and Billing GSTIN are different."),
            title=_("Invalid Internal Sales Invoice"),
        )

    dn_names = sorted(
        {
            (item.get("delivery_note") or "").strip()
            for item in (doc.get("items") or [])
            if (item.get("delivery_note") or "").strip()
        }
    )
    if not dn_names:
        return

    _validate_single_internal_si_per_dn(doc, dn_names)
    _validate_internal_si_dn_one_to_one_parity(doc, dn_names)


@frappe.whitelist()
def check_existing_internal_si_for_dn(delivery_notes: List[str], current_si: Optional[str] = None) -> Dict[str, Any]:
    """UI helper to check duplicate internal SI existence for DN context."""
    _bns_require_accounts_read()
    dn_names = sorted({(d or "").strip() for d in (delivery_notes or []) if (d or "").strip()})
    if not dn_names:
        return {"exists": False}

    si_item_rows = frappe.get_all(
        "Sales Invoice Item",
        filters={
            "delivery_note": ("in", dn_names),
            "parent": ("!=", current_si or ""),
            "docstatus": ("in", [0, 1]),
        },
        fields=["parent", "delivery_note"],
        order_by="modified desc",
    )
    if not si_item_rows:
        return {"exists": False}

    seen = set()
    for row in si_item_rows:
        si_name = row.get("parent")
        if not si_name or si_name in seen:
            continue
        seen.add(si_name)
        si_meta = frappe.db.get_value(
            "Sales Invoice",
            si_name,
            ["name", "docstatus", "is_return", "is_bns_internal_customer", "customer"],
            as_dict=True,
        )
        if not si_meta or cint(si_meta.get("is_return")):
            continue
        si_internal = bool(si_meta.get("is_bns_internal_customer"))
        if not si_internal and si_meta.get("customer"):
            si_internal = bool(
                frappe.db.get_value("Customer", si_meta.get("customer"), "is_bns_internal_customer")
            )
        if not si_internal:
            continue
        return {
            "exists": True,
            "sales_invoice": si_meta.get("name"),
            "docstatus": cint(si_meta.get("docstatus")),
            "docstatus_label": _docstatus_label(si_meta.get("docstatus")),
            "delivery_note": row.get("delivery_note"),
        }

    return {"exists": False}


# Temporarily disabled unused helper (kept commented for rollback safety).
# def _get_dn_item_transfer_rate_for_gl(dn_item) -> float:
#     """Get transfer rate from Delivery Note Item incoming_rate with DB fallback."""
#     rate = flt(dn_item.get("incoming_rate") or 0)
#     if rate > 0:
#         return rate
#
#     if dn_item.get("name") and frappe.db.exists("Delivery Note Item", dn_item.get("name")):
#         return flt(frappe.db.get_value("Delivery Note Item", dn_item.get("name"), "incoming_rate") or 0)
#
#     return 0


def _resolve_dn_transfer_amount(doc, force_mode: bool = False) -> Tuple[float, str]:
    """Resolve DN transfer amount from billing rate side (not valuation).

    Zero-rate items (samples, free goods) are skipped without blocking the
    rewrite — only items with positive qty AND zero rate after all fallbacks
    are treated as "missing" in non-force mode.
    """
    total = 0.0
    missing = False
    for item in doc.get("items") or []:
        line_amount = flt(item.get("base_net_amount") or 0)
        if line_amount <= 0:
            line_amount = flt(item.get("base_amount") or 0)
        if line_amount <= 0:
            qty = abs(flt(item.get("qty") or 0))
            rate = flt(item.get("base_net_rate") or item.get("rate") or 0)
            line_amount = qty * rate

        if line_amount <= 0:
            item_rate = flt(item.get("rate") or 0)
            if item_rate <= 0:
                continue
            missing = True
            continue
        total += line_amount

    if total <= 0:
        return 0.0, "no_transfer_amount"
    if missing and not force_mode:
        return 0.0, "missing_item_transfer_rate"
    return total, ""


def _resolve_pr_transfer_amount(doc, force_mode: bool = False) -> Tuple[float, str]:
    """Resolve PR transfer amount from billing rate side (not valuation).

    Zero-rate items (samples, free goods) are skipped without blocking the
    rewrite — only items with positive qty AND zero rate after all fallbacks
    are treated as "missing" in non-force mode.
    """
    total = 0.0
    missing = False
    for item in doc.get("items") or []:
        line_amount = flt(item.get("base_net_amount") or 0)
        if line_amount <= 0:
            line_amount = flt(item.get("base_amount") or 0)
        if line_amount <= 0:
            qty = abs(flt(item.get("qty") or 0))
            rate = flt(item.get("base_net_rate") or item.get("rate") or 0)
            line_amount = qty * rate

        if line_amount <= 0:
            item_rate = flt(item.get("rate") or 0)
            if item_rate <= 0:
                continue
            missing = True
            continue
        total += line_amount

    if total <= 0:
        return 0.0, "no_transfer_amount"
    if missing and not force_mode:
        return 0.0, "missing_item_transfer_rate"
    return total, ""


def _voucher_sle_stock_value(voucher_type: str, voucher_no: str) -> float:
    """Absolute net stock value the voucher's own SLE actually moved.

    This is the authoritative transit/stock-leg amount. ERPNext's stock GL falls
    back to item.valuation_rate * qty when an SLE stock_value_difference is 0
    (e.g. a receiver pulling in goods the sender shipped at 0 from negative
    stock), which over/under-states the leg versus what really moved. Using the
    SLE value keeps the receiver's transit credit equal to the sender's transit
    debit so Stock-in-Transit / Internal COGS nets to zero.
    """
    row = frappe.db.sql(
        """SELECT COALESCE(SUM(stock_value_difference), 0)
           FROM `tabStock Ledger Entry`
           WHERE voucher_type=%s AND voucher_no=%s AND is_cancelled=0""",
        (voucher_type, voucher_no),
    )
    return abs(flt(row[0][0])) if row else 0.0


def _resolve_valuation_from_gl_entries(
    gl_entries: List[Dict[str, Any]], side: str, company: Optional[str] = None
) -> Tuple[float, Optional[str], str]:
    """Resolve valuation amount and stock account from generated GL entries."""
    if side not in ("debit", "credit"):
        return 0.0, None, "invalid_side"

    stock_accounts = set()
    if company:
        try:
            from erpnext.stock import get_warehouse_account_map

            warehouse_map = get_warehouse_account_map(company)
            for row in (warehouse_map or {}).values():
                account = row.get("account")
                if account:
                    stock_accounts.add(account)
        except Exception:
            pass

    # Fallback heuristic for setups where warehouse account map is unavailable.
    if not stock_accounts and gl_entries:
        for row in gl_entries:
            account = (row.get("account") or "").strip()
            if "stock in hand" in account.lower():
                stock_accounts.add(account)
    # Strong fallback: detect stock accounts from Account.account_type
    # so custom account naming does not break BNS rewrite.
    if not stock_accounts and gl_entries:
        for row in gl_entries:
            account = (row.get("account") or "").strip()
            if not account:
                continue
            try:
                if frappe.get_cached_value("Account", account, "account_type") == "Stock":
                    stock_accounts.add(account)
            except Exception:
                continue

    if not stock_accounts:
        return 0.0, None, "no_stock_accounts"

    stock_side_entries = [
        row
        for row in (gl_entries or [])
        if row.get("account") in stock_accounts and flt(row.get(side) or 0) > 0
    ]
    if not stock_side_entries:
        return 0.0, None, "no_stock_side_entries"

    accounts = {row.get("account") for row in stock_side_entries if row.get("account")}
    if len(accounts) != 1:
        return 0.0, None, "multiple_stock_accounts"

    valuation_amount = sum(flt(row.get(side) or 0) for row in stock_side_entries)
    if valuation_amount <= 0:
        return 0.0, None, "non_positive_valuation_amount"

    return valuation_amount, next(iter(accounts)), ""


def _make_bns_gl_entry(doc, account: str, debit: float = 0.0, credit: float = 0.0, against: str = "", template: Optional[Dict[str, Any]] = None):
    """Build GL entry while preserving dimensions from template."""
    template = template or {}
    party_type = None
    party = None
    cost_center = template.get("cost_center")

    # In BNS rewrite, party fields are allowed only on internal branch debtor/creditor accounts.
    # Non receivable/payable GL rows (e.g. internal transfer, tax, stock) must not carry party.
    debtor_account = frappe.db.get_single_value(
        "BNS Branch Accounting Settings", "internal_branch_debtor_account"
    )
    creditor_account = frappe.db.get_single_value(
        "BNS Branch Accounting Settings", "internal_branch_creditor_account"
    )
    if account == debtor_account or account == creditor_account:
        party_type = template.get("party_type")
        party = template.get("party")
        if not party_type or not party:
            if account == debtor_account:
                party_type = "Customer"
                party = getattr(doc, "customer", None)
            elif account == creditor_account:
                party_type = "Supplier"
                party = getattr(doc, "supplier", None)

    # Cost center is mandatory for many P&L account entries in ERPNext.
    # Keep template value when present; else fall back to document-level and company default.
    if not cost_center:
        cost_center = getattr(doc, "cost_center", None) or doc.get("cost_center")
    if not cost_center:
        cost_center = frappe.get_cached_value("Company", doc.company, "cost_center") if doc.get("company") else None

    # Preserve ERPNext accounting dimensions on rewritten GL rows.
    # Precedence: source GL template row value > document-level value.
    dimension_args: Dict[str, Any] = {}
    for dimension in get_accounting_dimensions():
        dim_val = template.get(dimension)
        if dim_val in (None, ""):
            dim_val = doc.get(dimension)
        if dim_val not in (None, ""):
            dimension_args[dimension] = dim_val

    args = {
        "account": account,
        "debit": flt(debit),
        "credit": flt(credit),
        "against": against,
        "party_type": party_type,
        "party": party,
        "cost_center": cost_center,
        "project": template.get("project"),
        "finance_book": template.get("finance_book"),
        "remarks": template.get("remarks") or _("BNS internal transfer accounting rewrite"),
    }
    args.update(dimension_args)
    return doc.get_gl_dict(args)


def _rewrite_bns_internal_dn_gl_entries(doc, gl_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rewrite DN GL entries into BNS internal branch-accounting pattern."""
    if not _is_bns_internal_delivery_note(doc):
        return gl_entries
    if not is_after_accounting_rewrite_cutoff(doc.get("posting_date")):
        return gl_entries

    settings = _get_bns_branch_accounting_accounts()
    if not settings:
        return gl_entries

    force_mode = bool(settings.get("force_bns_internal_gl_rewrite"))
    is_return = cint(doc.get("is_return"))
    # A forward DN relieves stock (original GL posts the stock account on the
    # CREDIT side); a sales-return DN brings stock back (stock on the DEBIT
    # side). Resolve valuation from the matching side; every leg reverses for
    # a return.
    val_side = "debit" if is_return else "credit"
    valuation_amount, stock_account, valuation_reason = _resolve_valuation_from_gl_entries(
        gl_entries, side=val_side, company=doc.company
    )
    has_valuation = valuation_amount > 0 and bool(stock_account)

    # Dimension template: prefer the stock GL row; fall back to any GL row,
    # else {} — a zero-valuation internal DN emits no stock GL, but the
    # revenue legs (debtor / non-GST internal sales) must still post.
    # _make_bns_gl_entry builds cost-center / party / dimensions from the
    # document when no template row is available.
    template = None
    if has_valuation:
        template = next((row for row in gl_entries if row.get("account") == stock_account and flt(row.get(val_side) or 0) > 0), None)
    if not template and gl_entries:
        template = gl_entries[0]
    template = template or {}

    if _is_same_gstin_internal_delivery_note(doc):
        if not settings.get("internal_sales_non_gst_account"):
            logger.warning("Skipping DN GL rewrite for %s due to missing internal_sales_non_gst_account", doc.name)
            return gl_entries

        transfer_amount, transfer_reason = _resolve_dn_transfer_amount(doc, force_mode=force_mode)

        # Revenue legs move on the transfer (billing) amount and are DECOUPLED
        # from stock valuation: a same-GSTIN internal sale recognises the branch
        # receivable + non-GST internal sales even when the goods left the source
        # warehouse at zero cost. Valuation legs post only when there is stock
        # value. A return reverses every leg (Debtor Cr / Sales Dr, stock Dr /
        # transit Cr).
        debtor_side = "credit" if is_return else "debit"
        sales_side = "debit" if is_return else "credit"
        transit_side = "credit" if is_return else "debit"
        stock_side = "debit" if is_return else "credit"

        rewritten = []
        if transfer_amount > 0:
            rewritten.append(_make_bns_gl_entry(doc, settings["internal_branch_debtor_account"], **{debtor_side: transfer_amount}, against=settings["internal_sales_non_gst_account"], template=template))
            rewritten.append(_make_bns_gl_entry(doc, settings["internal_sales_non_gst_account"], **{sales_side: transfer_amount}, against=settings["internal_branch_debtor_account"], template=template))
        if has_valuation:
            rewritten.append(_make_bns_gl_entry(doc, settings["stock_in_transit_account"], **{transit_side: valuation_amount}, against=stock_account, template=template))
            rewritten.append(_make_bns_gl_entry(doc, stock_account, **{stock_side: valuation_amount}, against=settings["stock_in_transit_account"], template=template))
        if not rewritten:
            logger.warning("Skipping DN GL rewrite for %s: no transfer amount (reason=%s) and no valuation (reason=%s)", doc.name, transfer_reason or "ok", valuation_reason or "ok")
            return gl_entries
    else:
        # Different-GSTIN internal DN: valuation-only — revenue and GST are
        # recognised on the linked Sales Invoice, so this DN must NOT post
        # sale/debtor legs (that would double-count). Zero valuation here
        # correctly yields no GL. A return reverses the valuation legs.
        if not has_valuation:
            return gl_entries
        if not settings.get("stock_in_transit_account"):
            logger.warning("Skipping DN GL rewrite for %s due to missing stock_in_transit_account", doc.name)
            return gl_entries
        transit_side = "credit" if is_return else "debit"
        stock_side = "debit" if is_return else "credit"
        rewritten = [
            _make_bns_gl_entry(doc, settings["stock_in_transit_account"], **{transit_side: valuation_amount}, against=stock_account, template=template),
            _make_bns_gl_entry(doc, stock_account, **{stock_side: valuation_amount}, against=settings["stock_in_transit_account"], template=template),
        ]

    debit_total = sum(flt(row.get("debit") or 0) for row in rewritten)
    credit_total = sum(flt(row.get("credit") or 0) for row in rewritten)
    if abs(debit_total - credit_total) > 0.5:
        logger.error("Skipping DN GL rewrite for %s due to balance mismatch %s vs %s", doc.name, debit_total, credit_total)
        return gl_entries

    return rewritten


def _rewrite_bns_internal_pr_gl_entries(doc, gl_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rewrite PR GL entries into BNS internal branch-accounting pattern."""
    is_dn_same_gstin_scope = _is_bns_internal_same_gstin_purchase_receipt(doc)
    is_si_linked_scope = _is_bns_internal_si_linked_purchase_receipt(doc)
    if not (is_dn_same_gstin_scope or is_si_linked_scope):
        return gl_entries
    if not is_after_accounting_rewrite_cutoff(_resolve_source_posting_date(doc)):
        return gl_entries

    settings = _get_bns_branch_accounting_accounts()
    if not settings:
        return gl_entries
    if not settings.get("stock_in_transit_account"):
        logger.warning("Skipping PR GL rewrite for %s due to missing stock_in_transit_account", doc.name)
        return gl_entries
    if is_dn_same_gstin_scope and not settings.get("internal_purchase_non_gst_account"):
        logger.warning("Skipping PR GL rewrite for %s due to missing internal_purchase_non_gst_account", doc.name)
        return gl_entries

    force_mode = bool(settings.get("force_bns_internal_gl_rewrite"))
    is_return = cint(doc.get("is_return"))
    transfer_amount, transfer_reason = _resolve_pr_transfer_amount(doc, force_mode=force_mode)
    # A forward PR receives stock (stock on the DEBIT side); a purchase-return
    # PR sends it back (stock on the CREDIT side). Resolve from the matching
    # side; every leg reverses for a return.
    val_side = "credit" if is_return else "debit"
    valuation_amount, stock_account, valuation_reason = _resolve_valuation_from_gl_entries(
        gl_entries, side=val_side, company=doc.company
    )
    # Use the ACTUAL stock value moved (SLE svd) for the transit leg, not
    # ERPNext's valuation_rate-based GL number (which diverges when an item's
    # svd is 0), so receiver-transit-Cr == sender-transit-Dr.
    if stock_account:
        valuation_amount = _voucher_sle_stock_value(doc.doctype, doc.name)
    has_valuation = valuation_amount > 0 and bool(stock_account)

    template = None
    if has_valuation:
        template = next((row for row in gl_entries if row.get("account") == stock_account and flt(row.get(val_side) or 0) > 0), None)
    if not template and gl_entries:
        template = gl_entries[0]
    template = template or {}

    if is_dn_same_gstin_scope:
        # Party legs (creditor / non-GST internal purchase) move on the transfer
        # amount, DECOUPLED from stock valuation: the receiving branch books its
        # payable + internal purchase even if the goods arrived at zero cost.
        # Valuation legs post only when there is stock value. A return reverses
        # every leg (Purchase Cr / Creditor Dr, stock Cr / transit Dr).
        purchase_side = "credit" if is_return else "debit"
        creditor_side = "debit" if is_return else "credit"
        stock_side = "credit" if is_return else "debit"
        transit_side = "debit" if is_return else "credit"
        rewritten = []
        if transfer_amount > 0:
            rewritten.append(_make_bns_gl_entry(doc, settings["internal_purchase_non_gst_account"], **{purchase_side: transfer_amount}, against=settings["internal_branch_creditor_account"], template=template))
            rewritten.append(_make_bns_gl_entry(doc, settings["internal_branch_creditor_account"], **{creditor_side: transfer_amount}, against=settings["internal_purchase_non_gst_account"], template=template))
        if has_valuation:
            rewritten.append(_make_bns_gl_entry(doc, stock_account, **{stock_side: valuation_amount}, against=settings["stock_in_transit_account"], template=template))
            rewritten.append(_make_bns_gl_entry(doc, settings["stock_in_transit_account"], **{transit_side: valuation_amount}, against=stock_account, template=template))
        if not rewritten:
            logger.warning("Skipping PR GL rewrite for %s: no transfer amount (reason=%s) and no valuation (reason=%s)", doc.name, transfer_reason or "ok", valuation_reason or "ok")
            return gl_entries
    else:
        # SI->PR: valuation-only — purchase and GST are recognised on the linked
        # Purchase Invoice, so the PR must NOT post purchase/creditor legs. A
        # return reverses the valuation legs.
        if not has_valuation:
            return gl_entries
        stock_side = "credit" if is_return else "debit"
        transit_side = "debit" if is_return else "credit"
        rewritten = [
            _make_bns_gl_entry(doc, stock_account, **{stock_side: valuation_amount}, against=settings["stock_in_transit_account"], template=template),
            _make_bns_gl_entry(doc, settings["stock_in_transit_account"], **{transit_side: valuation_amount}, against=stock_account, template=template),
        ]

    debit_total = sum(flt(row.get("debit") or 0) for row in rewritten)
    credit_total = sum(flt(row.get("credit") or 0) for row in rewritten)
    if abs(debit_total - credit_total) > 0.5:
        logger.error("Skipping PR GL rewrite for %s due to balance mismatch %s vs %s", doc.name, debit_total, credit_total)
        return gl_entries

    return rewritten


def _balance_bns_internal_pi_gl_entries(
    doc, gl_entries: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Balance PI GL entries for BNS internal PIs in the Phase 1 window.

    When repost changes Stock In Hand (valuation shift) but Creditors stays
    fixed to grand_total, the GL becomes imbalanced.  This function absorbs
    the difference via the expense / COGS account so debit == credit.

    Only called for PIs that are after internal_transfer_cutoff but before
    accounting_rewrite_cutoff (Phase 1 window).
    """
    if not gl_entries:
        return gl_entries

    debit_total = sum(flt(row.get("debit") or 0) for row in gl_entries)
    credit_total = sum(flt(row.get("credit") or 0) for row in gl_entries)
    diff = flt(debit_total - credit_total, 2)

    if abs(diff) < 0.01:
        return gl_entries

    expense_account = None
    for item in (doc.get("items") or []):
        acct = (item.get("expense_account") or "").strip()
        if acct:
            expense_account = acct
            break
    if not expense_account:
        expense_account = frappe.get_cached_value(
            "Company", doc.company, "stock_adjustment_account"
        )
    if not expense_account:
        expense_account = frappe.get_cached_value(
            "Company", doc.company, "default_expense_account"
        )
    if not expense_account:
        logger.error(
            "Cannot balance PI GL for %s: no expense account found (diff=%s)",
            doc.name, diff,
        )
        return gl_entries

    existing_expense_entry = None
    for row in gl_entries:
        if row.get("account") == expense_account:
            existing_expense_entry = row
            break

    if existing_expense_entry:
        cur_debit = flt(existing_expense_entry.get("debit") or 0)
        cur_credit = flt(existing_expense_entry.get("credit") or 0)
        if diff > 0:
            new_credit = cur_credit + diff
            existing_expense_entry["credit"] = flt(new_credit, 2)
            existing_expense_entry["credit_in_account_currency"] = flt(new_credit, 2)
        else:
            new_debit = cur_debit + abs(diff)
            existing_expense_entry["debit"] = flt(new_debit, 2)
            existing_expense_entry["debit_in_account_currency"] = flt(new_debit, 2)
    else:
        template = gl_entries[0] if gl_entries else {}
        adjustment_entry = dict(template)
        adjustment_entry["account"] = expense_account
        adjustment_entry["against"] = doc.get("credit_to") or ""
        if diff > 0:
            adjustment_entry["debit"] = 0
            adjustment_entry["debit_in_account_currency"] = 0
            adjustment_entry["credit"] = flt(abs(diff), 2)
            adjustment_entry["credit_in_account_currency"] = flt(abs(diff), 2)
        else:
            adjustment_entry["debit"] = flt(abs(diff), 2)
            adjustment_entry["debit_in_account_currency"] = flt(abs(diff), 2)
            adjustment_entry["credit"] = 0
            adjustment_entry["credit_in_account_currency"] = 0
        gl_entries.append(adjustment_entry)

    logger.info(
        "Balanced PI GL for %s: diff=%s adjusted via %s",
        doc.name, diff, expense_account,
    )
    return gl_entries


def _rewrite_bns_internal_pi_gl_entries(doc, gl_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rewrite PI GL entries into BNS internal SI->PI stock-transfer pattern."""
    if not (doc and doc.doctype == "Purchase Invoice" and doc.docstatus == 1):
        return gl_entries
    if not _is_bns_internal_purchase_invoice_from_si(doc):
        return gl_entries
    source_date = _resolve_source_posting_date(doc)
    if not is_after_accounting_rewrite_cutoff(source_date):
        if is_after_internal_transfer_cutoff(source_date):
            return _balance_bns_internal_pi_gl_entries(doc, gl_entries)
        return gl_entries

    settings = _get_bns_branch_accounting_accounts()
    if not settings:
        return gl_entries
    if not settings.get("internal_purchase_transfer_account"):
        logger.warning("Skipping PI GL rewrite for %s due to missing internal_purchase_transfer_account", doc.name)
        return gl_entries

    is_return = cint(doc.get("is_return"))
    grand_total = flt(doc.get("base_grand_total") or doc.get("base_rounded_total") or 0)
    taxable_total = flt(doc.get("base_net_total") or doc.get("base_total") or 0)
    tax_by_account = _resolve_pi_tax_account_amounts(doc)

    if is_return:
        grand_total = abs(grand_total)
        taxable_total = abs(taxable_total)

    if grand_total <= 0 or taxable_total < 0:
        logger.warning("Skipping PI GL rewrite for %s due to invalid totals", doc.name)
        return gl_entries

    creditor_side = "debit" if is_return else "credit"
    transfer_side = "credit" if is_return else "debit"

    creditor_template = next(
        (
            row
            for row in (gl_entries or [])
            if row.get("account") == settings["internal_branch_creditor_account"] and flt(row.get(creditor_side) or 0) > 0
        ),
        None,
    )
    if not creditor_template:
        creditor_template = next((row for row in (gl_entries or []) if flt(row.get(creditor_side) or 0) > 0), None)
    if not creditor_template and gl_entries:
        creditor_template = gl_entries[0]
    if not creditor_template:
        return gl_entries

    rewritten = [
        _make_bns_gl_entry(
            doc,
            settings["internal_branch_creditor_account"],
            **{creditor_side: grand_total},
            against=settings["internal_purchase_transfer_account"],
            template=creditor_template,
        ),
        _make_bns_gl_entry(
            doc,
            settings["internal_purchase_transfer_account"],
            **{transfer_side: taxable_total},
            against=settings["internal_branch_creditor_account"],
            template=creditor_template,
        ),
    ]

    for tax_account, tax_amount in sorted(tax_by_account.items()):
        tax_template = next(
            (
                row
                for row in (gl_entries or [])
                if row.get("account") == tax_account
                and (flt(row.get("debit") or 0) > 0 or flt(row.get("credit") or 0) > 0)
            ),
            creditor_template,
        )
        abs_tax = abs(tax_amount)
        if is_return:
            tax_positive_side = "credit" if tax_amount > 0 else "debit"
        else:
            tax_positive_side = "debit" if tax_amount > 0 else "credit"
        rewritten.append(
            _make_bns_gl_entry(
                doc,
                tax_account,
                **{tax_positive_side: abs_tax},
                against=settings["internal_branch_creditor_account"],
                template=tax_template,
            )
        )

    has_pr_linked_rows = any((row.get("purchase_receipt") or "").strip() for row in (doc.get("items") or []))

    if cint(doc.get("update_stock")) and not has_pr_linked_rows:
        stock_gl_side = "debit" if not is_return else "credit"
        valuation_amount, stock_account, valuation_reason = _resolve_valuation_from_gl_entries(
            gl_entries, side=stock_gl_side, company=doc.company
        )
        # Use the ACTUAL stock value moved (SLE svd) for the transit leg, not
        # ERPNext's valuation_rate-based GL number (which diverges when an item's
        # svd is 0), so the receiver's Internal COGS credit == the sender's debit.
        if stock_account:
            valuation_amount = _voucher_sle_stock_value(doc.doctype, doc.name)
        # Stock legs are optional: when the PI received stock at zero valuation,
        # skip them but KEEP the party legs (creditor / purchase-transfer / GST).
        if valuation_amount > 0 and stock_account:
            stock_template = next(
                (
                    row
                    for row in (gl_entries or [])
                    if row.get("account") == stock_account and flt(row.get(stock_gl_side) or 0) > 0
                ),
                creditor_template,
            )
            transit_side = "credit" if not is_return else "debit"
            rewritten.append(
                _make_bns_gl_entry(
                    doc,
                    stock_account,
                    **{stock_gl_side: valuation_amount},
                    against=settings["stock_in_transit_account"],
                    template=stock_template,
                )
            )
            rewritten.append(
                _make_bns_gl_entry(
                    doc,
                    settings["stock_in_transit_account"],
                    **{transit_side: valuation_amount},
                    against=stock_account,
                    template=stock_template,
                )
            )
        else:
            logger.warning(
                "PI %s has update_stock but zero stock valuation; posting party legs only (reason=%s)",
                doc.name,
                valuation_reason or "ok",
            )

    debit_total = sum(flt(row.get("debit") or 0) for row in rewritten)
    credit_total = sum(flt(row.get("credit") or 0) for row in rewritten)
    if abs(debit_total - credit_total) > 0.5:
        logger.error("Skipping PI GL rewrite for %s due to balance mismatch %s vs %s", doc.name, debit_total, credit_total)
        return gl_entries

    return rewritten


def _resolve_pi_tax_account_amounts(doc) -> Dict[str, float]:
    """Aggregate PI tax/charge amounts account-wise in base currency."""
    account_amounts: Dict[str, float] = defaultdict(float)
    for tax in (doc.get("taxes") or []):
        account = (tax.get("account_head") or "").strip()
        if not account:
            continue
        base_amount = flt(
            tax.get("base_tax_amount_after_discount_amount")
            or tax.get("base_tax_amount")
            or 0
        )
        if abs(base_amount) <= 0.000001:
            continue
        account_amounts[account] += base_amount
    return dict(account_amounts)


def _resolve_si_tax_account_amounts(doc) -> Dict[str, float]:
    """Aggregate SI tax/charge amounts account-wise in base currency."""
    account_amounts: Dict[str, float] = defaultdict(float)
    for tax in (doc.get("taxes") or []):
        account = (tax.get("account_head") or "").strip()
        if not account:
            continue
        base_amount = flt(
            tax.get("base_tax_amount_after_discount_amount")
            or tax.get("base_tax_amount")
            or 0
        )
        if abs(base_amount) <= 0.000001:
            continue
        account_amounts[account] += base_amount
    return dict(account_amounts)


def _rewrite_bns_internal_si_gl_entries(doc, gl_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rewrite SI GL entries into BNS internal different-GSTIN pattern."""
    if not _is_bns_internal_different_gstin_sales_invoice(doc):
        return gl_entries
    if not is_after_accounting_rewrite_cutoff(doc.get("posting_date")):
        return gl_entries

    settings = _get_bns_branch_accounting_accounts()
    if not settings:
        return gl_entries
    if not settings.get("internal_sales_transfer_account"):
        logger.warning("Skipping SI GL rewrite for %s due to missing internal_sales_transfer_account", doc.name)
        return gl_entries

    debtor_account = settings["internal_branch_debtor_account"]
    transfer_account = settings["internal_sales_transfer_account"]
    is_return = cint(doc.get("is_return"))
    grand_total = flt(doc.get("base_grand_total") or doc.get("base_rounded_total") or 0)
    taxable_total = flt(doc.get("base_net_total") or doc.get("base_total") or 0)
    tax_by_account = _resolve_si_tax_account_amounts(doc)

    if is_return:
        grand_total = abs(grand_total)
        taxable_total = abs(taxable_total)

    if grand_total <= 0 or taxable_total < 0:
        logger.warning("Skipping SI GL rewrite for %s due to invalid totals", doc.name)
        return gl_entries

    debtor_side = "credit" if is_return else "debit"
    transfer_side = "debit" if is_return else "credit"

    debtor_template = next(
        (
            row
            for row in (gl_entries or [])
            if row.get("account") == debtor_account and flt(row.get(debtor_side) or 0) > 0
        ),
        None,
    )
    if not debtor_template:
        debtor_template = next((row for row in (gl_entries or []) if flt(row.get(debtor_side) or 0) > 0), None)
    if not debtor_template and gl_entries:
        debtor_template = gl_entries[0]
    if not debtor_template:
        return gl_entries

    rewritten = [
        _make_bns_gl_entry(
            doc,
            debtor_account,
            **{debtor_side: grand_total},
            against=transfer_account,
            template=debtor_template,
        )
    ]

    for tax_account, tax_amount in sorted(tax_by_account.items()):
        tax_template = next(
            (
                row
                for row in (gl_entries or [])
                if row.get("account") == tax_account
                and (flt(row.get("debit") or 0) > 0 or flt(row.get("credit") or 0) > 0)
            ),
            debtor_template,
        )
        abs_tax = abs(tax_amount)
        if is_return:
            tax_positive_side = "debit" if tax_amount > 0 else "credit"
        else:
            tax_positive_side = "credit" if tax_amount > 0 else "debit"
        rewritten.append(
            _make_bns_gl_entry(
                doc,
                tax_account,
                **{tax_positive_side: abs_tax},
                against=debtor_account,
                template=tax_template,
            )
        )

    rewritten.append(
        _make_bns_gl_entry(
            doc,
            transfer_account,
            **{transfer_side: taxable_total},
            against=debtor_account,
            template=debtor_template,
        )
    )

    if cint(doc.get("update_stock")):
        stock_gl_side = "credit" if not is_return else "debit"
        valuation_amount, stock_account, valuation_reason = _resolve_valuation_from_gl_entries(
            gl_entries, side=stock_gl_side, company=doc.company
        )
        # Stock legs are optional: when the SI moved stock at zero valuation,
        # skip them but KEEP the revenue legs (debtor / sales-transfer / GST),
        # which are recognised on the transaction amount regardless of cost.
        if valuation_amount > 0 and stock_account:
            stock_template = next(
                (
                    row
                    for row in (gl_entries or [])
                    if row.get("account") == stock_account and flt(row.get(stock_gl_side) or 0) > 0
                ),
                debtor_template,
            )
            transit_side = "debit" if not is_return else "credit"
            rewritten.append(
                _make_bns_gl_entry(
                    doc,
                    settings["stock_in_transit_account"],
                    **{transit_side: valuation_amount},
                    against=stock_account,
                    template=stock_template,
                )
            )
            rewritten.append(
                _make_bns_gl_entry(
                    doc,
                    stock_account,
                    **{stock_gl_side: valuation_amount},
                    against=settings["stock_in_transit_account"],
                    template=stock_template,
                )
            )
        else:
            logger.warning(
                "SI %s has update_stock but zero stock valuation; posting revenue legs only (reason=%s)",
                doc.name,
                valuation_reason or "ok",
            )

    debit_total = sum(flt(row.get("debit") or 0) for row in rewritten)
    credit_total = sum(flt(row.get("credit") or 0) for row in rewritten)
    if abs(debit_total - credit_total) > 0.5:
        logger.error(
            "Skipping SI GL rewrite for %s due to balance mismatch %s vs %s",
            doc.name,
            debit_total,
            credit_total,
        )
        return gl_entries

    logger.info(
        "Applied BNS SI GL rewrite for %s (update_stock=%s, grand=%s, taxable=%s)",
        doc.name,
        cint(doc.get("update_stock")),
        grand_total,
        taxable_total,
    )
    return rewritten


def _apply_bns_internal_gl_rewrite_patch() -> None:
    """Patch ERPNext GL generation for DN/PR/PI/SI in BNS internal scopes."""
    global _BNS_INTERNAL_GL_PATCHED
    if _BNS_INTERNAL_GL_PATCHED:
        return

    try:
        from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
        from erpnext.controllers.stock_controller import StockController
        from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt

        original_stock_get_gl_entries = StockController.get_gl_entries
        original_pr_get_gl_entries = PurchaseReceipt.get_gl_entries
        original_pi_get_gl_entries = PurchaseInvoice.get_gl_entries
        original_si_get_gl_entries = SalesInvoice.get_gl_entries

        if getattr(original_stock_get_gl_entries, "_bns_internal_gl_rewrite_patched", False):
            _BNS_INTERNAL_GL_PATCHED = True
            return

        def patched_stock_get_gl_entries(self, warehouse_account=None, default_expense_account=None, default_cost_center=None):
            gl_entries = original_stock_get_gl_entries(self, warehouse_account, default_expense_account, default_cost_center)
            if getattr(self, "doctype", None) == "Delivery Note":
                gl_entries = _rewrite_bns_internal_dn_gl_entries(self, gl_entries)
                return append_asset_transfer_gl_entries(self, gl_entries)
            return gl_entries

        def patched_pr_get_gl_entries(self, warehouse_account=None, via_landed_cost_voucher=False):
            gl_entries = original_pr_get_gl_entries(self, warehouse_account, via_landed_cost_voucher)
            gl_entries = _rewrite_bns_internal_pr_gl_entries(self, gl_entries)
            return append_asset_transfer_gl_entries(self, gl_entries)

        def patched_pi_get_gl_entries(self, warehouse_account=None):
            gl_entries = original_pi_get_gl_entries(self, warehouse_account)
            gl_entries = _rewrite_bns_internal_pi_gl_entries(self, gl_entries)
            return append_asset_transfer_gl_entries(self, gl_entries)

        def patched_si_get_gl_entries(self, warehouse_account=None):
            gl_entries = original_si_get_gl_entries(self, warehouse_account)
            gl_entries = _rewrite_bns_internal_si_gl_entries(self, gl_entries)
            return append_asset_transfer_gl_entries(self, gl_entries)

        patched_stock_get_gl_entries._bns_internal_gl_rewrite_patched = True
        patched_pr_get_gl_entries._bns_internal_gl_rewrite_patched = True
        patched_pi_get_gl_entries._bns_internal_gl_rewrite_patched = True
        patched_si_get_gl_entries._bns_internal_gl_rewrite_patched = True
        StockController.get_gl_entries = patched_stock_get_gl_entries
        PurchaseReceipt.get_gl_entries = patched_pr_get_gl_entries
        PurchaseInvoice.get_gl_entries = patched_pi_get_gl_entries
        SalesInvoice.get_gl_entries = patched_si_get_gl_entries
        _BNS_INTERNAL_GL_PATCHED = True
        logger.info("Applied BNS internal GL rewrite patch for Delivery Note, Purchase Receipt, Purchase Invoice, and Sales Invoice")

    except Exception as e:
        logger.error("Failed to apply BNS internal GL rewrite patch: %s", str(e))


def _run_bns_gl_repost_correction(doc, force_override: bool = False) -> None:
    """Re-run repost GLE only for scoped DN/PR vouchers as failsafe."""
    cache_key = f"bns_gl_repost_correction::{doc.name}"
    if not force_override and frappe.cache().get_value(cache_key):
        # region agent log
        _bns_debug_log(
            "H3",
            "utils.py:_run_bns_gl_repost_correction",
            "Skipped by repost_item_valuation cache key",
            {"doc": doc.name, "cache_key": cache_key},
        )
        # endregion
        return

    scoped_vouchers: Set[Tuple[str, str]] = set()

    if doc.get("based_on") == "Transaction" and doc.get("voucher_type") in ("Delivery Note", "Purchase Receipt"):
        scoped_vouchers.add((doc.get("voucher_type"), doc.get("voucher_no")))

    try:
        from erpnext.stock.stock_ledger import get_affected_transactions
        affected = get_affected_transactions(doc)
    except Exception:
        affected = set()

    for voucher_type, voucher_no in affected:
        if voucher_type not in ("Delivery Note", "Purchase Receipt") or not voucher_no:
            continue
        scoped_vouchers.add((voucher_type, voucher_no))

    filtered_vouchers: List[Tuple[str, str]] = []
    for voucher_type, voucher_no in sorted(scoped_vouchers):
        if not frappe.db.exists(voucher_type, voucher_no):
            continue
        if not force_override and _is_bns_repost_voucher_processed(
            "repost_item_valuation", doc.name, voucher_type, voucher_no
        ):
            continue
        voucher_doc = frappe.get_doc(voucher_type, voucher_no)
        if voucher_type == "Delivery Note":
            is_scope = _is_bns_internal_delivery_note(voucher_doc) and is_after_accounting_rewrite_cutoff(
                voucher_doc.get("posting_date")
            )
            # region agent log
            _bns_debug_log(
                "H2",
                "utils.py:_run_bns_gl_repost_correction",
                "Evaluated DN scope for repost_item_valuation",
                {"doc": doc.name, "voucher_no": voucher_no, "is_scope": is_scope},
            )
            # endregion
            if is_scope:
                filtered_vouchers.append((voucher_type, voucher_no))
        elif voucher_type == "Purchase Receipt" and (
            _is_bns_internal_same_gstin_purchase_receipt(voucher_doc)
            or _is_bns_internal_si_linked_purchase_receipt(voucher_doc)
        ) and is_after_accounting_rewrite_cutoff(_resolve_source_posting_date(voucher_doc)):
            filtered_vouchers.append((voucher_type, voucher_no))
    # region agent log
    _bns_debug_log(
        "H4",
        "utils.py:_run_bns_gl_repost_correction",
        "Repost item valuation correction prepared voucher lists",
        {
            "doc": doc.name,
            "scoped_count": len(scoped_vouchers),
            "filtered_count": len(filtered_vouchers),
            "force_override": bool(force_override),
        },
    )
    # endregion

    if filtered_vouchers:
        scope = "repost_item_valuation"
        repost_doc_name = doc.name
        claimed = []
        for voucher_type, voucher_no in filtered_vouchers:
            if _claim_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no):
                claimed.append((voucher_type, voucher_no))
        if claimed:
            _apply_bns_internal_gl_rewrite_patch()
            settings = _get_bns_branch_accounting_accounts()
            force_mode = bool(settings and settings.get("force_bns_internal_gl_rewrite")) or bool(force_override)
            try:
                if force_mode:
                    rebuilt = 0
                    for voucher_type, voucher_no in claimed:
                        if _force_rebuild_bns_gl_for_voucher(
                            voucher_type, voucher_no, context="repost_item_valuation"
                        ):
                            rebuilt += 1
                            if not force_override:
                                _mark_bns_repost_voucher_processed(scope, repost_doc_name, voucher_type, voucher_no)
                    logger.info("BNS repost GL force-rebuild applied for repost %s on %s/%s vouchers", doc.name, rebuilt, len(claimed))
                else:
                    from erpnext.accounts.utils import repost_gle_for_stock_vouchers
                    before_counts = {(vt, vn): _get_ledger_row_counts_for_voucher(vt, vn) for vt, vn in claimed}
                    repost_gle_for_stock_vouchers(claimed, doc.posting_date, doc.company, repost_doc=doc)
                    for voucher_type, voucher_no in claimed:
                        after_counts = _get_ledger_row_counts_for_voucher(voucher_type, voucher_no)
                        logger.info("BNS repost audit %s", frappe.as_json({"scope": scope, "mode": "repost_gle_for_stock_vouchers", "repost_doc": repost_doc_name, "voucher_type": voucher_type, "voucher_no": voucher_no, "before_count": before_counts[(voucher_type, voucher_no)], "after_count": after_counts}))
                        if not force_override:
                            _mark_bns_repost_voucher_processed(scope, repost_doc_name, voucher_type, voucher_no)
                    logger.info("BNS repost GL failsafe applied for repost %s on %s vouchers", doc.name, len(claimed))
            except Exception as e:
                for voucher_type, voucher_no in claimed:
                    _mark_bns_repost_tracking_failed(scope, repost_doc_name, voucher_type, voucher_no, str(e))
                raise
            finally:
                for voucher_type, voucher_no in claimed:
                    _release_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no)

    if force_override:
        frappe.cache().delete_value(cache_key)
    else:
        frappe.cache().set_value(cache_key, 1, expires_in_sec=6 * 60 * 60)


def _get_ledger_row_counts_for_voucher(voucher_type: str, voucher_no: str) -> Dict[str, int]:
    """Return per-ledger row counts for one voucher."""
    filters = {"voucher_type": voucher_type, "voucher_no": voucher_no}
    counts = {
        "gl_entry": frappe.db.count("GL Entry", filters),
        "payment_ledger_entry": 0,
        "advance_payment_ledger_entry": 0,
    }
    if frappe.db.table_exists("Payment Ledger Entry"):
        counts["payment_ledger_entry"] = frappe.db.count("Payment Ledger Entry", filters)
    if frappe.db.table_exists("Advance Payment Ledger Entry"):
        counts["advance_payment_ledger_entry"] = frappe.db.count("Advance Payment Ledger Entry", filters)
    return counts


def _delete_ledger_rows_for_voucher(voucher_type: str, voucher_no: str) -> None:
    """Delete GL/PLE rows for one voucher before controlled rebuild."""
    filters = {"voucher_type": voucher_type, "voucher_no": voucher_no}
    if frappe.db.table_exists("Advance Payment Ledger Entry"):
        frappe.db.delete("Advance Payment Ledger Entry", filters)
    if frappe.db.table_exists("Payment Ledger Entry"):
        frappe.db.delete("Payment Ledger Entry", filters)
    frappe.db.delete("GL Entry", filters)


def _get_repost_doctype_for_scope(scope: str, voucher_type: Optional[str] = None) -> str:
    """Return the Repost doctype name for a given scope."""
    m = {
        "repost_item_valuation": "Repost Item Valuation",
        "repost_accounting_ledger": "Repost Accounting Ledger",
        # For generic BNS repost guards, bind tracking to the voucher doctype itself
        # so tracking keys are always backed by an existing document.
        "bns_internal_gl_repost": voucher_type or "Repost Item Valuation",
        "pr_transfer_rate_repost": "Repost Item Valuation",
        "pi_transfer_rate_repost": "Repost Item Valuation",
    }
    return m.get(scope, "Repost Item Valuation")


def _is_bns_repost_tracking_available() -> bool:
    """Check if BNS Repost Tracking doctype and table exist and are usable."""
    try:
        return bool(
            frappe.db.exists("DocType", _BNS_REPOST_TRACKING_DTYPE)
            and frappe.db.table_exists(_BNS_REPOST_TRACKING_DTYPE)
        )
    except Exception:
        return False


def _build_bns_repost_tracking_key(scope: str, repost_doc: str, voucher_type: str, voucher_no: str) -> str:
    """Build the canonical tracking key for DB-backed repost tracking."""
    return "bns_repost_voucher::" + scope + "::" + repost_doc + "::" + voucher_type + "::" + voucher_no


def _claim_bns_repost_lock(scope, repost_doc, voucher_type, voucher_no, lock_ttl_min=10):
    """Claim or create a DB-backed lock for repost tracking. Returns True if lock acquired."""
    key = _build_bns_repost_tracking_key(scope, repost_doc, voucher_type, voucher_no)
    if not _is_bns_repost_tracking_available():
        if frappe.cache().get_value(key):
            return False
        frappe.cache().set_value(key, 1, expires_in_sec=max(cint(lock_ttl_min), 1) * 60)
        return True

    lock_expires = add_to_date(now_datetime(), minutes=max(cint(lock_ttl_min), 1), as_datetime=True)
    try:
        frappe.db.sql(
            f"""
            UPDATE `tab{_BNS_REPOST_TRACKING_DTYPE}`
            SET status=%s, lock_expires_at=%s, last_error=NULL
            WHERE tracking_key=%s
              AND status!=%s
              AND (status!=%s OR lock_expires_at IS NULL OR lock_expires_at < NOW())
            """,
            (
                _BNS_REPOST_STATUS_IN_PROGRESS,
                lock_expires,
                key,
                _BNS_REPOST_STATUS_PROCESSED,
                _BNS_REPOST_STATUS_IN_PROGRESS,
            ),
        )
        affected_rows = 0
        try:
            affected_rows_fn = getattr(frappe.db, "affected_rows", None)
            if callable(affected_rows_fn):
                affected_rows = cint(affected_rows_fn() or 0)
        except Exception:
            affected_rows = 0
        if affected_rows <= 0:
            try:
                row_count_result = frappe.db.sql("SELECT ROW_COUNT()", as_list=True) or [[0]]
                affected_rows = cint((row_count_result[0][0] if row_count_result and row_count_result[0] else 0) or 0)
            except Exception:
                affected_rows = 0
        if affected_rows > 0:
            return True

        if frappe.db.exists(_BNS_REPOST_TRACKING_DTYPE, {"tracking_key": key}):
            return False

        frappe.get_doc(
            {
                "doctype": _BNS_REPOST_TRACKING_DTYPE,
                "tracking_key": key,
                "scope": scope,
                "repost_doctype": _get_repost_doctype_for_scope(scope, voucher_type),
                "repost_docname": repost_doc,
                "voucher_type": voucher_type,
                "voucher_no": voucher_no,
                "status": _BNS_REPOST_STATUS_IN_PROGRESS,
                "lock_expires_at": lock_expires,
            }
        ).insert(ignore_permissions=True)
        return True
    except Exception as e:
        logger.warning("BNS repost lock claim failed for %s: %s", key, str(e))
        return False


def _refresh_bns_repost_lock(scope, repost_doc, voucher_type, voucher_no, lock_ttl_min=10):
    """Refresh the lock expiry for an active repost tracking record."""
    key = _build_bns_repost_tracking_key(scope, repost_doc, voucher_type, voucher_no)
    if not _is_bns_repost_tracking_available():
        frappe.cache().set_value(key, 1, expires_in_sec=max(cint(lock_ttl_min), 1) * 60)
        return
    frappe.db.set_value(
        _BNS_REPOST_TRACKING_DTYPE,
        {"tracking_key": key, "status": _BNS_REPOST_STATUS_IN_PROGRESS},
        {"lock_expires_at": add_to_date(now_datetime(), minutes=max(cint(lock_ttl_min), 1), as_datetime=True)},
        update_modified=True,
    )


def _mark_bns_repost_tracking_processed(scope, repost_doc, voucher_type, voucher_no):
    """Mark repost tracking as Processed in DB, with cache fallback."""
    key = _build_bns_repost_tracking_key(scope, repost_doc, voucher_type, voucher_no)
    if _is_bns_repost_tracking_available():
        try:
            if frappe.db.exists(_BNS_REPOST_TRACKING_DTYPE, key):
                frappe.db.set_value(
                    _BNS_REPOST_TRACKING_DTYPE,
                    key,
                    {
                        "status": _BNS_REPOST_STATUS_PROCESSED,
                        "processed_at": now_datetime(),
                        "lock_expires_at": None,
                        "last_error": None,
                    },
                    update_modified=True,
                )
            else:
                rd = _get_repost_doctype_for_scope(scope, voucher_type)
                frappe.get_doc(
                    {
                        "doctype": _BNS_REPOST_TRACKING_DTYPE,
                        "tracking_key": key,
                        "scope": scope,
                        "repost_doctype": rd,
                        "repost_docname": repost_doc,
                        "voucher_type": voucher_type,
                        "voucher_no": voucher_no,
                        "status": _BNS_REPOST_STATUS_PROCESSED,
                        "processed_at": now_datetime(),
                    }
                ).insert(ignore_permissions=True)
        except Exception as e:
            logger.warning("BNS repost mark processed failed: %s", str(e))
    _mark_bns_repost_voucher_processed_cache(scope, repost_doc, voucher_type, voucher_no)


def _mark_bns_repost_tracking_failed(scope, repost_doc, voucher_type, voucher_no, error):
    """Mark repost tracking as Failed in DB, with cache fallback."""
    if _is_bns_repost_tracking_available():
        key = _build_bns_repost_tracking_key(scope, repost_doc, voucher_type, voucher_no)
        try:
            err = str(error)[:1000]
            if frappe.db.exists(_BNS_REPOST_TRACKING_DTYPE, key):
                frappe.db.set_value(
                    _BNS_REPOST_TRACKING_DTYPE,
                    key,
                    {
                        "status": _BNS_REPOST_STATUS_FAILED,
                        "last_error": err,
                        "lock_expires_at": None,
                    },
                    update_modified=True,
                )
            else:
                rd = _get_repost_doctype_for_scope(scope, voucher_type)
                frappe.get_doc(
                    {
                        "doctype": _BNS_REPOST_TRACKING_DTYPE,
                        "tracking_key": key,
                        "scope": scope,
                        "repost_doctype": rd,
                        "repost_docname": repost_doc,
                        "voucher_type": voucher_type,
                        "voucher_no": voucher_no,
                        "status": _BNS_REPOST_STATUS_FAILED,
                        "last_error": err,
                    }
                ).insert(ignore_permissions=True)
        except Exception as e:
            logger.warning("BNS repost mark failed: %s", str(e))


def _release_bns_repost_lock(scope, repost_doc, voucher_type, voucher_no):
    """Release the DB-backed lock. Defensive cleanup."""
    key = _build_bns_repost_tracking_key(scope, repost_doc, voucher_type, voucher_no)
    if not _is_bns_repost_tracking_available():
        frappe.cache().delete_value(key)
        return
    try:
        if frappe.db.exists(_BNS_REPOST_TRACKING_DTYPE, key):
            frappe.db.set_value(
                _BNS_REPOST_TRACKING_DTYPE,
                key,
                {"lock_expires_at": None},
                update_modified=True,
            )
    except Exception as e:
        logger.warning("BNS repost lock release failed: %s", str(e))


def _bns_repost_voucher_marker_key(
    scope: str, repost_doc: str, voucher_type: str, voucher_no: str
) -> str:
    return f"bns_repost_voucher::{scope}::{repost_doc}::{voucher_type}::{voucher_no}"


def _is_bns_repost_voucher_processed(
    scope: str, repost_doc: str, voucher_type: str, voucher_no: str
) -> bool:
    """Check DB-backed tracking first (status Processed), fallback to cache."""
    if _is_bns_repost_tracking_available():
        key = _build_bns_repost_tracking_key(scope, repost_doc, voucher_type, voucher_no)
        try:
            status = frappe.db.get_value(_BNS_REPOST_TRACKING_DTYPE, key, "status")
            if status == _BNS_REPOST_STATUS_PROCESSED:
                return True
        except Exception:
            pass
    return bool(frappe.cache().get_value(_bns_repost_voucher_marker_key(scope, repost_doc, voucher_type, voucher_no)))


def _mark_bns_repost_voucher_processed(
    scope: str, repost_doc: str, voucher_type: str, voucher_no: str
) -> None:
    """Mark voucher as processed via DB-backed tracking (Processed), fallback to cache."""
    _mark_bns_repost_tracking_processed(scope, repost_doc, voucher_type, voucher_no)


def _mark_bns_repost_voucher_processed_cache(
    scope: str, repost_doc: str, voucher_type: str, voucher_no: str
) -> None:
    """Set cache-only marker as fallback when DB tracking unavailable."""
    frappe.cache().set_value(
        _bns_repost_voucher_marker_key(scope, repost_doc, voucher_type, voucher_no),
        1,
        expires_in_sec=6 * 60 * 60,
    )


def _force_rebuild_bns_gl_for_voucher(
    voucher_type: str, voucher_no: str, context: str = "manual"
) -> bool:
    """Force rebuild GL entries for one internal-transfer voucher using patched get_gl_entries."""
    if voucher_type not in ("Delivery Note", "Purchase Receipt", "Purchase Invoice", "Sales Invoice") or not voucher_no:
        return False
    if not frappe.db.exists(voucher_type, voucher_no):
        return False

    doc = frappe.get_doc(voucher_type, voucher_no)
    if doc.docstatus != 1:
        return False

    if voucher_type == "Delivery Note" and not _is_bns_internal_delivery_note(doc):
        return False
    if voucher_type == "Purchase Receipt" and not (
        _is_bns_internal_same_gstin_purchase_receipt(doc)
        or _is_bns_internal_si_linked_purchase_receipt(doc)
    ):
        return False
    if voucher_type == "Purchase Invoice":
        if not _is_bns_internal_purchase_invoice_from_si(doc):
            return False
    if voucher_type == "Sales Invoice" and not _is_bns_internal_different_gstin_sales_invoice(doc):
        return False

    _apply_bns_internal_gl_rewrite_patch()
    save_point = "bns_force_rebuild_voucher"
    before_counts = _get_ledger_row_counts_for_voucher(voucher_type, voucher_no)
    # region agent log
    _bns_debug_log(
        "H5",
        "utils.py:_force_rebuild_bns_gl_for_voucher",
        "Force rebuild entered",
        {
            "context": context,
            "voucher_type": voucher_type,
            "voucher_no": voucher_no,
            "before_count": before_counts,
        },
    )
    # endregion

    try:
        frappe.db.savepoint(save_point)
        # Symmetric replacement: remove ledger rows for voucher and rebuild.
        _delete_ledger_rows_for_voucher(voucher_type, voucher_no)
        doc.make_gl_entries(from_repost=True)
        after_counts = _get_ledger_row_counts_for_voucher(voucher_type, voucher_no)
        # Safety: never accept a rebuild that emptied GL for a previously posted voucher.
        if before_counts.get("gl_entry", 0) > 0 and after_counts.get("gl_entry", 0) == 0:
            raise frappe.ValidationError(
                f"BNS force rebuild produced zero GL rows for {voucher_type} {voucher_no}; rolling back."
            )
        logger.info(
            "BNS repost audit %s",
            frappe.as_json(
                {
                    "scope": context,
                    "mode": "force_rebuild",
                    "voucher_type": voucher_type,
                    "voucher_no": voucher_no,
                    "before_count": before_counts,
                    "after_count": after_counts,
                }
            ),
        )
        logger.info("Force rebuilt BNS GL for %s %s", voucher_type, voucher_no)
        # region agent log
        _bns_debug_log(
            "H5",
            "utils.py:_force_rebuild_bns_gl_for_voucher",
            "Force rebuild succeeded",
            {
                "context": context,
                "voucher_type": voucher_type,
                "voucher_no": voucher_no,
                "after_count": after_counts,
            },
        )
        # endregion
        return True
    except Exception as e:
        frappe.db.rollback(save_point=save_point)
        logger.error("Force rebuild failed for %s %s: %s", voucher_type, voucher_no, str(e))
        # region agent log
        _bns_debug_log(
            "H5",
            "utils.py:_force_rebuild_bns_gl_for_voucher",
            "Force rebuild failed",
            {
                "context": context,
                "voucher_type": voucher_type,
                "voucher_no": voucher_no,
                "error": str(e),
            },
        )
        # endregion
        return False


def _run_bns_gl_repost_accounting_correction(repost_doc_name: str, force_override: bool = False) -> None:
    """Apply BNS GL correction for vouchers included in Repost Accounting Ledger."""
    if not repost_doc_name or not frappe.db.exists("Repost Accounting Ledger", repost_doc_name):
        return

    cache_key = f"bns_gl_accounting_repost_correction::{repost_doc_name}"
    if not force_override and frappe.cache().get_value(cache_key):
        # region agent log
        _bns_debug_log(
            "H3",
            "utils.py:_run_bns_gl_repost_accounting_correction",
            "Skipped by repost_accounting cache key",
            {"repost_doc_name": repost_doc_name, "cache_key": cache_key},
        )
        # endregion
        return

    repost_doc = frappe.get_doc("Repost Accounting Ledger", repost_doc_name)
    vouchers = []
    for row in repost_doc.get("vouchers") or []:
        if row.voucher_type in ("Delivery Note", "Purchase Receipt") and row.voucher_no:
            vouchers.append((row.voucher_type, row.voucher_no))

    if not vouchers:
        if force_override:
            frappe.cache().delete_value(cache_key)
        else:
            frappe.cache().set_value(cache_key, 1, expires_in_sec=6 * 60 * 60)
        return

    filtered = []
    for voucher_type, voucher_no in sorted(set(vouchers)):
        if not frappe.db.exists(voucher_type, voucher_no):
            continue
        if not force_override and _is_bns_repost_voucher_processed(
            "repost_accounting_ledger", repost_doc_name, voucher_type, voucher_no
        ):
            # region agent log
            _bns_debug_log(
                "H3",
                "utils.py:_run_bns_gl_repost_accounting_correction",
                "Voucher skipped by per-voucher accounting marker",
                {
                    "repost_doc_name": repost_doc_name,
                    "voucher_type": voucher_type,
                    "voucher_no": voucher_no,
                },
            )
            # endregion
            continue
        doc = frappe.get_doc(voucher_type, voucher_no)
        if voucher_type == "Delivery Note":
            is_scope = _is_bns_internal_delivery_note(doc) and is_after_accounting_rewrite_cutoff(
                doc.get("posting_date")
            )
            # region agent log
            _bns_debug_log(
                "H2",
                "utils.py:_run_bns_gl_repost_accounting_correction",
                "Evaluated DN scope for repost_accounting",
                {
                    "repost_doc_name": repost_doc_name,
                    "voucher_no": voucher_no,
                    "is_scope": is_scope,
                },
            )
            # endregion
            if is_scope:
                filtered.append((voucher_type, voucher_no))
        elif voucher_type == "Purchase Receipt" and (
            _is_bns_internal_same_gstin_purchase_receipt(doc)
            or _is_bns_internal_si_linked_purchase_receipt(doc)
        ) and is_after_accounting_rewrite_cutoff(
            _resolve_source_posting_date(doc)
        ):
            filtered.append((voucher_type, voucher_no))

    # region agent log
    _bns_debug_log(
        "H4",
        "utils.py:_run_bns_gl_repost_accounting_correction",
        "Repost accounting correction prepared voucher lists",
        {
            "repost_doc_name": repost_doc_name,
            "input_count": len(vouchers),
            "filtered_count": len(filtered),
            "force_override": bool(force_override),
        },
    )
    # endregion

    if not filtered:
        if force_override:
            frappe.cache().delete_value(cache_key)
        else:
            frappe.cache().set_value(cache_key, 1, expires_in_sec=6 * 60 * 60)
        return

    scope = "repost_accounting_ledger"
    claimed = []
    for voucher_type, voucher_no in filtered:
        if _claim_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no):
            claimed.append((voucher_type, voucher_no))
    if not claimed:
        if force_override:
            frappe.cache().delete_value(cache_key)
        else:
            frappe.cache().set_value(cache_key, 1, expires_in_sec=6 * 60 * 60)
        return

    _apply_bns_internal_gl_rewrite_patch()
    settings = _get_bns_branch_accounting_accounts()
    force_mode = bool(settings and settings.get("force_bns_internal_gl_rewrite")) or bool(force_override)
    # Different-GSTIN internal DN must not drift to default COGS/SIH on repost;
    # force controlled rebuild for this subset.
    if not force_mode:
        for voucher_type, voucher_no in claimed:
            if voucher_type != "Delivery Note":
                continue
            try:
                voucher_doc = frappe.get_doc(voucher_type, voucher_no)
            except Exception:
                continue
            if (
                _is_bns_internal_delivery_note(voucher_doc)
                and is_after_accounting_rewrite_cutoff(voucher_doc.get("posting_date"))
                and not _is_same_gstin_internal_delivery_note(voucher_doc)
            ):
                force_mode = True
                break
    try:
        if force_mode:
            rebuilt = 0
            for voucher_type, voucher_no in claimed:
                if _force_rebuild_bns_gl_for_voucher(
                    voucher_type, voucher_no, context="repost_accounting_ledger"
                ):
                    rebuilt += 1
                    if not force_override:
                        _mark_bns_repost_voucher_processed(scope, repost_doc_name, voucher_type, voucher_no)
            logger.info("BNS Repost Accounting Ledger force-rebuild applied for %s on %s/%s vouchers", repost_doc_name, rebuilt, len(claimed))
        else:
            from erpnext.accounts.utils import repost_gle_for_stock_vouchers
            before_counts = {(vt, vn): _get_ledger_row_counts_for_voucher(vt, vn) for vt, vn in claimed}
            repost_gle_for_stock_vouchers(claimed, repost_doc.posting_date, repost_doc.company, repost_doc=repost_doc)
            for voucher_type, voucher_no in claimed:
                after_counts = _get_ledger_row_counts_for_voucher(voucher_type, voucher_no)
                logger.info("BNS repost audit %s", frappe.as_json({"scope": scope, "mode": "repost_gle_for_stock_vouchers", "repost_doc": repost_doc_name, "voucher_type": voucher_type, "voucher_no": voucher_no, "before_count": before_counts[(voucher_type, voucher_no)], "after_count": after_counts}))
                if not force_override:
                    _mark_bns_repost_voucher_processed(scope, repost_doc_name, voucher_type, voucher_no)
            logger.info("BNS Repost Accounting Ledger correction applied for %s on %s vouchers", repost_doc_name, len(claimed))
    except Exception as e:
        for voucher_type, voucher_no in claimed:
            _mark_bns_repost_tracking_failed(scope, repost_doc_name, voucher_type, voucher_no, str(e))
        raise
    finally:
        for voucher_type, voucher_no in claimed:
            _release_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no)

    if force_override:
        frappe.cache().delete_value(cache_key)
    else:
        frappe.cache().set_value(cache_key, 1, expires_in_sec=6 * 60 * 60)


@frappe.whitelist()
def bns_force_rewrite_gl_for_repost_accounting_ledger(repost_doc_name: str) -> Dict[str, Any]:
    """
    Force-correct GL for DN/PR vouchers included in a Repost Accounting Ledger doc.
    This bypasses setting-based force flag and executes hard rebuild path.
    """
    _bns_require_accounts_write()
    if not repost_doc_name:
        return {"ok": False, "message": "Missing repost_doc_name"}
    if not frappe.db.exists("Repost Accounting Ledger", repost_doc_name):
        return {"ok": False, "message": f"Repost Accounting Ledger {repost_doc_name} not found"}

    repost_doc = frappe.get_doc("Repost Accounting Ledger", repost_doc_name)
    processed = []
    for row in repost_doc.get("vouchers") or []:
        if row.voucher_type in ("Delivery Note", "Purchase Receipt") and row.voucher_no:
            if _force_rebuild_bns_gl_for_voucher(
                row.voucher_type, row.voucher_no, context="manual_repost_accounting_ledger"
            ):
                processed.append(f"{row.voucher_type}:{row.voucher_no}")

    return {
        "ok": True,
        "message": f"BNS force GL rewrite completed for {repost_doc_name}",
        "processed": processed,
    }


@frappe.whitelist()
def bns_force_rewrite_gl_for_repost_item_valuation(repost_doc_name: str) -> Dict[str, Any]:
    """
    Force-correct GL for DN/PR vouchers affected by a Repost Item Valuation doc.
    This bypasses setting-based force flag and executes hard rebuild path.
    """
    _bns_require_accounts_write()
    if not repost_doc_name:
        return {"ok": False, "message": "Missing repost_doc_name"}
    if not frappe.db.exists("Repost Item Valuation", repost_doc_name):
        return {"ok": False, "message": f"Repost Item Valuation {repost_doc_name} not found"}

    doc = frappe.get_doc("Repost Item Valuation", repost_doc_name)
    _run_bns_gl_repost_correction(doc, force_override=True)
    return {"ok": True, "message": f"BNS force GL rewrite completed for {repost_doc_name}"}


@frappe.whitelist()
def bns_debug_internal_gl_scope(voucher_type: str, voucher_no: str) -> Dict[str, Any]:
    """Debug helper to inspect BNS GL rewrite scope and amount resolution."""
    _bns_require_accounts_read()
    if voucher_type not in ("Delivery Note", "Purchase Receipt") or not voucher_no:
        return {"ok": False, "message": "Invalid voucher_type/voucher_no"}
    if not frappe.db.exists(voucher_type, voucher_no):
        return {"ok": False, "message": f"{voucher_type} {voucher_no} not found"}

    doc = frappe.get_doc(voucher_type, voucher_no)
    gl_entries = frappe.get_all(
        "GL Entry",
        filters={"voucher_type": voucher_type, "voucher_no": voucher_no, "is_cancelled": 0},
        fields=["account", "debit", "credit"],
        order_by="creation asc",
    )
    settings = _get_bns_branch_accounting_accounts()
    force_mode = bool(settings and settings.get("force_bns_internal_gl_rewrite"))
    out = {
        "ok": True,
        "voucher_type": voucher_type,
        "voucher_no": voucher_no,
        "settings_loaded": bool(settings),
        "force_mode_setting": force_mode,
        "is_dn_scope": _is_bns_internal_delivery_note(doc) if voucher_type == "Delivery Note" else None,
        "is_dn_same_gstin_scope": _is_bns_internal_same_gstin_delivery_note(doc) if voucher_type == "Delivery Note" else None,
        "is_pr_scope": _is_bns_internal_same_gstin_purchase_receipt(doc) if voucher_type == "Purchase Receipt" else None,
        "gl_entries": gl_entries,
        "doc_get_gl_entries_qualname": getattr(getattr(doc, "get_gl_entries", None), "__qualname__", None),
        "doc_get_gl_entries_module": getattr(getattr(doc, "get_gl_entries", None), "__module__", None),
    }

    try:
        from erpnext.controllers.stock_controller import StockController
        out["stock_controller_patched"] = bool(
            getattr(StockController.get_gl_entries, "_bns_internal_gl_rewrite_patched", False)
        )
        out["stock_controller_get_gl_entries_qualname"] = getattr(
            StockController.get_gl_entries, "__qualname__", None
        )
    except Exception:
        pass

    if voucher_type == "Purchase Receipt":
        try:
            from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt
            out["purchase_receipt_patched"] = bool(
                getattr(PurchaseReceipt.get_gl_entries, "_bns_internal_gl_rewrite_patched", False)
            )
            out["purchase_receipt_get_gl_entries_qualname"] = getattr(
                PurchaseReceipt.get_gl_entries, "__qualname__", None
            )
        except Exception:
            pass

    if voucher_type == "Delivery Note":
        try:
            from erpnext.stock import get_warehouse_account_map
            out["computed_gl_entries"] = doc.get_gl_entries(get_warehouse_account_map(doc.company))
        except Exception as e:
            out["computed_gl_entries_error"] = str(e)

        transfer_amount, transfer_reason = _resolve_dn_transfer_amount(doc, force_mode=True)
        valuation_amount, stock_account, valuation_reason = _resolve_valuation_from_gl_entries(
            gl_entries, side="credit", company=doc.company
        )
        out.update(
            {
                "transfer_amount": transfer_amount,
                "transfer_reason": transfer_reason,
                "valuation_amount": valuation_amount,
                "valuation_reason": valuation_reason,
                "stock_account": stock_account,
            }
        )
    else:
        try:
            from erpnext.stock import get_warehouse_account_map
            out["computed_gl_entries"] = doc.get_gl_entries(get_warehouse_account_map(doc.company))
        except Exception as e:
            out["computed_gl_entries_error"] = str(e)

        transfer_amount, transfer_reason = _resolve_pr_transfer_amount(doc, force_mode=True)
        valuation_amount, stock_account, valuation_reason = _resolve_valuation_from_gl_entries(
            gl_entries, side="debit", company=doc.company
        )
        out.update(
            {
                "transfer_amount": transfer_amount,
                "transfer_reason": transfer_reason,
                "valuation_amount": valuation_amount,
                "valuation_reason": valuation_reason,
                "stock_account": stock_account,
            }
        )

    return out


@frappe.whitelist()
def bns_force_rebuild_gl_for_voucher(voucher_type: str, voucher_no: str) -> Dict[str, Any]:
    """Force rebuild GL for one DN/PR voucher and return result."""
    _bns_require_accounts_write()
    try:
        result = _force_rebuild_bns_gl_for_voucher(voucher_type, voucher_no)
        return {"ok": bool(result), "voucher_type": voucher_type, "voucher_no": voucher_no}
    except Exception as e:
        return {"ok": False, "voucher_type": voucher_type, "voucher_no": voucher_no, "error": str(e)}


def _apply_bns_repost_gl_failsafe_patch() -> None:
    """Patch Repost Item Valuation GL phase to run BNS-scoped failsafe correction."""
    global _BNS_REPOST_GL_FAILSAFE_PATCHED
    if _BNS_REPOST_GL_FAILSAFE_PATCHED:
        return

    try:
        from erpnext.stock.doctype.repost_item_valuation import repost_item_valuation as riv
        original_repost_gl_entries = riv.repost_gl_entries

        if getattr(original_repost_gl_entries, "_bns_repost_gl_failsafe_patched", False):
            _BNS_REPOST_GL_FAILSAFE_PATCHED = True
            return

        def patched_repost_gl_entries(doc):
            doc_lock_scope = "repost_item_valuation"
            doc_lock_repost = doc.name if doc else ""
            doc_lock_voucher_type = "Repost Item Valuation"
            doc_lock_voucher_no = doc.name if doc else ""
            original_repost_gl_entries(doc)
            try:
                _run_bns_gl_repost_correction(doc)
            except Exception as e:
                logger.error("BNS repost GL failsafe error for %s: %s", doc.name, str(e))
            finally:
                if doc_lock_repost:
                    _release_bns_repost_lock(
                        doc_lock_scope,
                        doc_lock_repost,
                        doc_lock_voucher_type,
                        doc_lock_voucher_no,
                    )

        patched_repost_gl_entries._bns_repost_gl_failsafe_patched = True
        riv.repost_gl_entries = patched_repost_gl_entries
        _BNS_REPOST_GL_FAILSAFE_PATCHED = True
        logger.info("Applied BNS repost GL failsafe patch")

    except Exception as e:
        logger.error("Failed to apply BNS repost GL failsafe patch: %s", str(e))


def _apply_bns_repost_accounting_ledger_patch() -> None:
    """Patch Repost Accounting Ledger start_repost to run BNS correction after ERPNext repost."""
    global _BNS_REPOST_ACCOUNTING_LEDGER_PATCHED
    if _BNS_REPOST_ACCOUNTING_LEDGER_PATCHED:
        return

    try:
        from erpnext.accounts.doctype.repost_accounting_ledger import repost_accounting_ledger as ral
        original_start_repost = ral.start_repost

        if getattr(original_start_repost, "_bns_repost_accounting_patched", False):
            _BNS_REPOST_ACCOUNTING_LEDGER_PATCHED = True
            return

        def patched_start_repost(account_repost_doc=str):
            result = original_start_repost(account_repost_doc)
            doc_lock_scope = "repost_accounting_ledger"
            doc_lock_repost = str(account_repost_doc or "")
            doc_lock_voucher_type = "Repost Accounting Ledger"
            doc_lock_voucher_no = str(account_repost_doc or "")
            try:
                _run_bns_gl_repost_accounting_correction(account_repost_doc)
            except Exception as e:
                logger.error("BNS repost accounting correction failed for %s: %s", account_repost_doc, str(e))
            finally:
                if doc_lock_repost:
                    _release_bns_repost_lock(
                        doc_lock_scope,
                        doc_lock_repost,
                        doc_lock_voucher_type,
                        doc_lock_voucher_no,
                    )
            return result

        patched_start_repost._bns_repost_accounting_patched = True
        ral.start_repost = patched_start_repost
        _BNS_REPOST_ACCOUNTING_LEDGER_PATCHED = True
        logger.info("Applied BNS Repost Accounting Ledger patch")
    except Exception as e:
        logger.error("Failed to apply BNS Repost Accounting Ledger patch: %s", str(e))


def _trigger_bns_internal_gl_repost(doc, source: str) -> bool:
    """Run a guarded repost so custom BNS GL rewrite is applied reliably."""
    if not doc or doc.docstatus != 1:
        return False

    scope = "bns_internal_gl_repost"
    # Keep tracking anchored to a real document to avoid lock/doc lookup failures.
    repost_doc = doc.name
    voucher_type = doc.doctype
    voucher_no = doc.name
    if not _claim_bns_repost_lock(scope, repost_doc, voucher_type, voucher_no):
        return False

    try:
        _apply_bns_internal_gl_rewrite_patch()
        doc.repost_future_sle_and_gle(force=True)
        _mark_bns_repost_tracking_processed(scope, repost_doc, voucher_type, voucher_no)
        logger.info("Triggered guarded BNS GL repost for %s %s (%s)", doc.doctype, doc.name, source)
        return True
    except Exception as e:
        _mark_bns_repost_tracking_failed(scope, repost_doc, voucher_type, voucher_no, str(e))
        logger.error("Failed guarded BNS GL repost for %s %s (%s): %s", doc.doctype, doc.name, source, str(e))
        return False


_BNS_REPOST_EMAIL_SUPPRESSED = False


def _suppress_repost_error_emails() -> None:
    """Replace ERPNext's repost error emailer with a no-op.

    Repost Item Valuation failures already create an Error Log and set the
    document status to Failed. The emails to Stock Managers are noisy and
    not actionable for most teams; errors are visible on the document and
    in the BNS dashboard repost tracker.
    """
    global _BNS_REPOST_EMAIL_SUPPRESSED
    if _BNS_REPOST_EMAIL_SUPPRESSED:
        return

    try:
        from erpnext.stock.doctype.repost_item_valuation import (
            repost_item_valuation as riv_module,
        )

        if getattr(riv_module.notify_error_to_stock_managers, "_bns_suppressed", False):
            _BNS_REPOST_EMAIL_SUPPRESSED = True
            return

        def _noop(doc, traceback):
            pass

        _noop._bns_suppressed = True
        riv_module.notify_error_to_stock_managers = _noop
        _BNS_REPOST_EMAIL_SUPPRESSED = True
        logger.info("Suppressed Repost Item Valuation error emails")
    except Exception as e:
        logger.error("Failed to suppress repost error emails: %s", str(e))


_BNS_ASSET_INTERNAL_PATCHED = False


def _apply_bns_asset_internal_patches() -> None:
    """Skip ERPNext's asset auto-creation and disposal for BNS internal transfers.

    - BuyingController.process_fixed_asset: suppress auto_make_assets so a
      receiving internal PR/PI does NOT mint a duplicate Asset.
    - SalesInvoice.process_asset_depreciation: suppress the "Sold" status +
      disposal_date + sale-depreciation so an internal SI keeps the same asset.

    Gated by is_bns_internal_transfer (NOT ERPNext's is_internal_transfer), so
    only BNS internal branch transfers are affected. The transfer GL is posted
    by the get_gl_entries rewrite + append_asset_transfer_gl_entries; the SI GL
    rewrite already replaces ERPNext's disposal GL with the branch pattern.
    """
    global _BNS_ASSET_INTERNAL_PATCHED
    if _BNS_ASSET_INTERNAL_PATCHED:
        return
    try:
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
        from erpnext.controllers.buying_controller import BuyingController

        original_process_fixed_asset = BuyingController.process_fixed_asset
        original_process_asset_depreciation = SalesInvoice.process_asset_depreciation

        if getattr(original_process_fixed_asset, "_bns_asset_internal_patched", False):
            _BNS_ASSET_INTERNAL_PATCHED = True
            return

        def patched_process_fixed_asset(self):
            try:
                if is_bns_internal_transfer(self):
                    return
            except Exception:
                logger.exception("BNS asset: process_fixed_asset guard failed for %s", getattr(self, "name", "?"))
            return original_process_fixed_asset(self)

        def patched_process_asset_depreciation(self):
            try:
                if is_bns_internal_transfer(self):
                    return
            except Exception:
                logger.exception("BNS asset: process_asset_depreciation guard failed for %s", getattr(self, "name", "?"))
            return original_process_asset_depreciation(self)

        patched_process_fixed_asset._bns_asset_internal_patched = True
        patched_process_asset_depreciation._bns_asset_internal_patched = True
        BuyingController.process_fixed_asset = patched_process_fixed_asset
        SalesInvoice.process_asset_depreciation = patched_process_asset_depreciation
        _BNS_ASSET_INTERNAL_PATCHED = True
        logger.info("Applied BNS asset internal-transfer patches (no auto-asset, no disposal)")
    except Exception as e:
        logger.error("Failed to apply BNS asset internal-transfer patches: %s", str(e))


_BNS_STICKY_STATUS_PATCHED = False


def _bns_should_hold_internal_status(doc) -> bool:
    """True when a submitted SI/PI is a BNS internal transfer (after the
    internal-transfer cutoff) and so must keep the 'BNS Internally Transferred'
    status instead of the recomputed Unpaid/Overdue/Paid.

    A cheap pre-filter on the internal flag (or an already-set status) avoids the
    expensive detection on every set_status of every normal invoice.
    """
    try:
        if getattr(doc, "docstatus", 0) != 1:
            return False
        dt = getattr(doc, "doctype", None)
        if dt == "Sales Invoice":
            if not (doc.get("is_bns_internal_customer") or doc.get("status") == "BNS Internally Transferred"):
                return False
            if not _should_update_sales_invoice_status(doc):
                return False
        elif dt == "Purchase Invoice":
            if not (doc.get("is_bns_internal_supplier") or doc.get("status") == "BNS Internally Transferred"):
                return False
            if not _is_bns_internal_purchase_invoice_from_si(doc):
                return False
        else:
            return False
        return is_after_internal_transfer_cutoff(_resolve_source_posting_date(doc))
    except Exception:
        logger.exception("BNS sticky status: detection failed for %s", getattr(doc, "name", "?"))
        return False


def _wrap_bns_sticky_set_status(original_set_status):
    """Wrap an invoice set_status so a BNS internal transfer keeps its custom
    status. ERPNext's overdue scheduler only escalates 'Unpaid%'/'Partly Paid%'
    rows, so preventing the drift to Unpaid here keeps the status sticky."""

    def patched_set_status(self, update=False, status=None, update_modified=True):
        result = original_set_status(self, update=update, status=status, update_modified=update_modified)
        try:
            # Only re-assert on a recompute (status not explicitly forced) so an
            # explicit set (e.g. Cancelled) is respected.
            if status is None and _bns_should_hold_internal_status(self):
                if self.status != "BNS Internally Transferred":
                    self.status = "BNS Internally Transferred"
                    if update:
                        self.db_set("status", "BNS Internally Transferred", update_modified=update_modified)
        except Exception:
            logger.exception("BNS sticky status: re-assert failed for %s", getattr(self, "name", "?"))
        return result

    patched_set_status._bns_sticky_status_patched = True
    return patched_set_status


def _apply_bns_sticky_status_patch() -> None:
    """Keep 'BNS Internally Transferred' sticky on internal SI/PI against
    ERPNext's status recomputation (set_status -> Unpaid/Overdue/Paid)."""
    global _BNS_STICKY_STATUS_PATCHED
    if _BNS_STICKY_STATUS_PATCHED:
        return
    try:
        from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

        if getattr(SalesInvoice.set_status, "_bns_sticky_status_patched", False):
            _BNS_STICKY_STATUS_PATCHED = True
            return
        SalesInvoice.set_status = _wrap_bns_sticky_set_status(SalesInvoice.set_status)
        PurchaseInvoice.set_status = _wrap_bns_sticky_set_status(PurchaseInvoice.set_status)
        _BNS_STICKY_STATUS_PATCHED = True
        logger.info("Applied BNS sticky-status patch (internal SI/PI keep 'BNS Internally Transferred')")
    except Exception as e:
        logger.error("Failed to apply BNS sticky-status patch: %s", str(e))


def reassert_bns_internal_invoice_status():
    """Daily safety net: re-assert 'BNS Internally Transferred' on internal SI/PI
    whose status drifted away (the overdue scheduler's bulk SQL, or any path that
    wrote status outside set_status, or pre-patch data).

    The set_status patch prevents drift in the live path; this heals whatever
    slipped through. Uses frappe ORM (db_set) -- never a raw status SQL UPDATE.
    """
    cutoff = _get_internal_transfer_cutoff_date()
    if not cutoff:
        return

    skip_statuses = [
        "BNS Internally Transferred", "Cancelled", "Draft",
        "Return", "Credit Note Issued", "Debit Note Issued",
    ]
    healed = 0
    for dt, flag in (
        ("Sales Invoice", "is_bns_internal_customer"),
        ("Purchase Invoice", "is_bns_internal_supplier"),
    ):
        names = frappe.get_all(
            dt,
            filters={
                "docstatus": 1,
                flag: 1,
                "status": ("not in", skip_statuses),
                "posting_date": (">=", cutoff),
            },
            pluck="name",
        )
        for name in names:
            try:
                doc = frappe.get_doc(dt, name)
                if _bns_should_hold_internal_status(doc):
                    frappe.db.set_value(dt, name, "status", "BNS Internally Transferred", update_modified=False)
                    healed += 1
            except Exception:
                logger.exception("BNS status re-assert failed for %s %s", dt, name)
        frappe.db.commit()

    if healed:
        logger.info("BNS status re-assert: healed %s internal invoice(s)", healed)


def bns_prioritize_repost_item_valuation():
    """Cron (every 5 min): when the BNS setting is ON, keep the Repost Item
    Valuation queue draining continuously instead of waiting for the hourly run.

    Implementation note: we do NOT write our own repost loop. We re-trigger
    ERPNext's own scheduled job ('repost_item_valuation.repost_entries') via
    Scheduled Job Type.enqueue(force=True). Frappe deduplicates that job by its
    rq_job_id, so it never runs concurrently with itself or with the hourly
    scheduler -- zero double-processing risk -- and repost_entries() still
    honours Stock Reposting Settings' configured timeslot. So this just makes
    the *same* single-worker drainer start promptly (every 5 min) rather than
    once an hour.
    """
    if not frappe.db.get_single_value(
        "BNS Branch Accounting Settings", "prioritize_repost_item_valuation"
    ):
        return

    # Nothing queued -> don't bother enqueuing.
    pending = frappe.db.count(
        "Repost Item Valuation",
        {"status": ("in", ("Queued", "In Progress")), "docstatus": 1},
    )
    if not pending:
        return

    try:
        job_type = frappe.get_doc(
            "Scheduled Job Type", "repost_item_valuation.repost_entries"
        )
    except frappe.DoesNotExistError:
        logger.warning(
            "BNS prioritize repost: Scheduled Job Type 'repost_item_valuation.repost_entries' not found"
        )
        return

    # enqueue() is a no-op if the job is already queued/running (frappe dedup),
    # so calling it every 5 minutes simply keeps one drainer alive.
    job_type.enqueue(force=True)


# Best-effort eager patching on module import.
_apply_bns_transfer_rate_stock_ledger_patch()
_apply_bns_internal_gl_rewrite_patch()
_apply_bns_repost_gl_failsafe_patch()
_apply_bns_repost_accounting_ledger_patch()
_apply_bns_asset_internal_patches()
_apply_bns_sticky_status_patch()
_suppress_repost_error_emails()


def apply_bns_runtime_patches() -> None:
    """
    Ensure BNS runtime monkey patches are applied in every process (web/worker).
    Hooked from after_app_init so repost workers don't miss patch load.
    """
    _apply_bns_transfer_rate_stock_ledger_patch()
    _apply_bns_internal_gl_rewrite_patch()
    _apply_bns_repost_gl_failsafe_patch()
    _apply_bns_repost_accounting_ledger_patch()
    _apply_bns_asset_internal_patches()
    _apply_bns_sticky_status_patch()
    _suppress_repost_error_emails()


def is_bns_internal_customer(doc) -> bool:
    """
    Check if the document's customer is a BNS internal customer.

    Args:
        doc: Document with customer field (e.g. Sales Invoice, Delivery Note).

    Returns:
        bool: True if customer is BNS internal, False otherwise.
    """
    if doc.get("is_bns_internal_customer"):
        return True
    if getattr(doc, "customer", None):
        return bool(frappe.db.get_value("Customer", doc.customer, "is_bns_internal_customer"))
    return False


def is_bns_internal_supplier(doc) -> bool:
    """
    Check if the document's supplier is a BNS internal supplier.

    Args:
        doc: Document with supplier field (e.g. Purchase Invoice, Purchase Receipt).

    Returns:
        bool: True if supplier is BNS internal, False otherwise.
    """
    if doc.get("is_bns_internal_supplier"):
        return True
    if getattr(doc, "supplier", None):
        return bool(frappe.db.get_value("Supplier", doc.supplier, "is_bns_internal_supplier"))
    return False


def is_bns_internal_transfer(doc) -> bool:
    """BNS analogue of accounts_controller.is_internal_transfer().

    True when the document is a BNS internal branch transfer (by BNS flags). Used
    ONLY to gate BNS asset-transfer handling -- ERPNext's native
    is_internal_transfer() (which drives 40+ inter-company code paths) is left
    untouched, so existing stock flows are unaffected.
    """
    dt = getattr(doc, "doctype", None)
    if dt in ("Sales Invoice", "Delivery Note", "Sales Order"):
        return is_bns_internal_customer(doc)
    if dt in ("Purchase Invoice", "Purchase Receipt", "Purchase Order"):
        return is_bns_internal_supplier(doc)
    return False


def _asset_net_book_value_on_date(asset_name, as_of_date, finance_book=None) -> float:
    """Net book value (gross - accumulated depreciation) of an asset as of a date.

    Delegates to ERPNext's date-aware helper
    (get_value_after_depreciation_on_disposal_date), which returns
    value_after_depreciation when no depreciation is scheduled and the
    schedule-derived NBV otherwise. Falls back to gross - opening accumulated
    depreciation on any failure (e.g. transfer date before available_for_use).
    Returns 0.0 when the asset is missing.
    """
    if not asset_name:
        return 0.0
    asset = frappe.db.get_value(
        "Asset",
        asset_name,
        ["gross_purchase_amount", "opening_accumulated_depreciation"],
        as_dict=True,
    )
    if not asset:
        return 0.0
    try:
        from erpnext.assets.doctype.asset.depreciation import (
            get_value_after_depreciation_on_disposal_date,
        )

        return flt(get_value_after_depreciation_on_disposal_date(asset_name, as_of_date, finance_book))
    except Exception:
        logger.exception("BNS: NBV-on-date fallback for asset %s as of %s", asset_name, as_of_date)
        return flt(asset.get("gross_purchase_amount") or 0) - flt(
            asset.get("opening_accumulated_depreciation") or 0
        )


# ---------------------------------------------------------------------------
# Internal asset transfer — GL legs (asset analogue of the stock-in-transit move)
# ---------------------------------------------------------------------------

def _bns_asset_transfer_row_field(doctype: str) -> Optional[str]:
    """Field on the item row that links the existing asset being transferred.

    Sales Invoice uses ERPNext's native mandatory `asset`; DN/PR/PI use the BNS
    custom `bns_transferred_asset` (so ERPNext's purchase asset linkage / cancel
    guard never engages).
    """
    if doctype == "Sales Invoice":
        return "asset"
    if doctype in ("Delivery Note", "Purchase Receipt", "Purchase Invoice"):
        return "bns_transferred_asset"
    return None


def _asset_category_account(asset_name: str, company: str, fieldname: str) -> Optional[str]:
    """Resolve a company-scoped Asset Category Account (fixed_asset_account /
    accumulated_depreciation_account) for the asset's category."""
    if not asset_name or not company:
        return None
    category = frappe.db.get_value("Asset", asset_name, "asset_category")
    if not category:
        return None
    return frappe.db.get_value(
        "Asset Category Account",
        {"parent": category, "company_name": company},
        fieldname,
    )


def _bns_asset_transfer_rows(doc) -> List[Dict[str, Any]]:
    """Return fixed-asset item rows of an internal transfer with their linked
    asset and value snapshot (gross / accumulated depreciation / NBV) as of the
    document posting date.
    """
    rows: List[Dict[str, Any]] = []
    field = _bns_asset_transfer_row_field(doc.doctype)
    if not field:
        return rows
    as_of = doc.get("posting_date")
    for item in (doc.get("items") or []):
        code = item.get("item_code")
        is_fa = cint(item.get("is_fixed_asset")) or (
            code and cint(frappe.db.get_value("Item", code, "is_fixed_asset"))
        )
        if not is_fa:
            continue
        asset_name = (item.get(field) or "").strip()
        if not asset_name or not frappe.db.exists("Asset", asset_name):
            continue
        gross = flt(frappe.db.get_value("Asset", asset_name, "gross_purchase_amount") or 0)
        nbv = _asset_net_book_value_on_date(asset_name, as_of)
        accum = flt(gross - nbv)
        if accum < 0:
            accum = 0.0
        rows.append({"item": item, "asset": asset_name, "gross": gross, "nbv": nbv, "accum": accum})
    return rows


def _build_asset_transfer_legs(doc, asset_rows, transit_account, template):
    """Build the 3-leg asset movement per asset row (self-balanced):

    Sender (DN/SI):  Cr Fixed Asset (gross) | Dr Accumulated Depreciation (accum) | Dr Asset-in-Transit (NBV)
    Receiver (PR/PI): Dr Fixed Asset (gross) | Cr Accumulated Depreciation (accum) | Cr Asset-in-Transit (NBV)

    is_return flips the direction. The Internal Debtor/Sales/Purchase/Creditor
    billing pair is already posted by the stock rewrite on the transfer amount,
    so it is NOT duplicated here.
    """
    legs = []
    is_sender_doc = doc.doctype in ("Delivery Note", "Sales Invoice")
    sender = is_sender_doc ^ bool(cint(doc.get("is_return")))
    for ar in asset_rows:
        gross, accum, nbv = flt(ar["gross"]), flt(ar["accum"]), flt(ar["nbv"])
        if gross <= 0:
            continue
        fa_account = _asset_category_account(ar["asset"], doc.company, "fixed_asset_account")
        accum_account = _asset_category_account(ar["asset"], doc.company, "accumulated_depreciation_account")
        if not fa_account:
            logger.warning("BNS asset transfer: no fixed_asset_account for asset %s (%s)", ar["asset"], doc.name)
            continue
        if accum > 0 and not accum_account:
            logger.warning("BNS asset transfer: no accumulated_depreciation_account for asset %s (%s)", ar["asset"], doc.name)
            continue
        if sender:
            legs.append(_make_bns_gl_entry(doc, fa_account, credit=gross, template=template))
            if accum > 0:
                legs.append(_make_bns_gl_entry(doc, accum_account, debit=accum, template=template))
            legs.append(_make_bns_gl_entry(doc, transit_account, debit=nbv, template=template))
        else:
            legs.append(_make_bns_gl_entry(doc, fa_account, debit=gross, template=template))
            if accum > 0:
                legs.append(_make_bns_gl_entry(doc, accum_account, credit=accum, template=template))
            legs.append(_make_bns_gl_entry(doc, transit_account, credit=nbv, template=template))
    return legs


def append_asset_transfer_gl_entries(doc, gl_entries):
    """Append BNS internal asset-transfer GL legs for fixed-asset rows.

    Posted through the get_gl_entries patch so they reverse with the rest on
    cancel. No-op unless the doc is a BNS internal transfer, after the accounting
    rewrite cutoff, and carries linked fixed-asset rows. Each asset row's legs
    are internally balanced, so the overall GL stays balanced.
    """
    try:
        if doc.doctype not in ("Delivery Note", "Sales Invoice", "Purchase Receipt", "Purchase Invoice"):
            return gl_entries
        if not is_bns_internal_transfer(doc):
            return gl_entries
        if not is_after_accounting_rewrite_cutoff(doc.get("posting_date")):
            return gl_entries
        asset_rows = _bns_asset_transfer_rows(doc)
        if not asset_rows:
            return gl_entries
        transit_account = (
            frappe.db.get_single_value("BNS Branch Accounting Settings", "asset_in_transit_account") or ""
        ).strip()
        if not transit_account:
            logger.warning("BNS asset transfer: asset_in_transit_account not set; skipping %s", doc.name)
            return gl_entries
        template = (gl_entries[0] if gl_entries else {}) or {}
        legs = _build_asset_transfer_legs(doc, asset_rows, transit_account, template)
        if legs:
            gl_entries = list(gl_entries or []) + legs
    except Exception:
        logger.exception("BNS: asset transfer GL append failed for %s", getattr(doc, "name", "?"))
    return gl_entries


def bns_apply_asset_transfer(doc, method: Optional[str] = None) -> None:
    """On submit of a BNS internal RECEIVER (PR/PI), move the linked asset's
    cost_center to the receiving branch so future depreciation posts there.
    The prior cost_center is stored on the asset for an exact revert on cancel.

    The same asset record is kept throughout (no new asset, no disposal) -- only
    the branch dimension changes. The asset is NOT moved by the sender (DN/SI);
    the value sits in Asset-in-Transit until the receiver posts.
    """
    if doc.doctype not in ("Purchase Receipt", "Purchase Invoice"):
        return
    if not is_bns_internal_transfer(doc):
        return
    if not is_after_accounting_rewrite_cutoff(doc.get("posting_date")):
        return
    if not frappe.get_meta("Asset").has_field("bns_pre_transfer_cost_center"):
        return
    for ar in _bns_asset_transfer_rows(doc):
        asset_name = ar["asset"]
        new_cc = doc.get("cost_center") or (ar["item"].get("cost_center") or "")
        if not new_cc:
            continue
        cur_cc = frappe.db.get_value("Asset", asset_name, "cost_center")
        if cur_cc == new_cc:
            continue
        frappe.db.set_value(
            "Asset",
            asset_name,
            {"bns_pre_transfer_cost_center": cur_cc, "cost_center": new_cc},
            update_modified=False,
        )
        logger.info(
            "BNS asset transfer: %s cost_center %s -> %s via %s",
            asset_name, cur_cc, new_cc, doc.name,
        )


def bns_revert_asset_transfer(doc, method: Optional[str] = None) -> None:
    """On cancel of a BNS internal receiver, restore the asset's prior cost_center."""
    if doc.doctype not in ("Purchase Receipt", "Purchase Invoice"):
        return
    if not frappe.get_meta("Asset").has_field("bns_pre_transfer_cost_center"):
        return
    for ar in _bns_asset_transfer_rows(doc):
        asset_name = ar["asset"]
        prev_cc = frappe.db.get_value("Asset", asset_name, "bns_pre_transfer_cost_center")
        if prev_cc:
            frappe.db.set_value(
                "Asset",
                asset_name,
                {"cost_center": prev_cc, "bns_pre_transfer_cost_center": None},
                update_modified=False,
            )
            logger.info(
                "BNS asset transfer: reverted %s cost_center -> %s on cancel of %s",
                asset_name, prev_cc, doc.name,
            )


def _bns_repost_voucher_gl(voucher_type: str, voucher_no: str) -> None:
    """Repost a voucher's GL via Repost Accounting Ledger so the BNS-patched
    get_gl_entries (incl. append_asset_transfer_gl_entries) re-runs with the
    current NBV."""
    doc = frappe.get_doc(voucher_type, voucher_no)
    if doc.docstatus != 1:
        return
    _apply_bns_internal_gl_rewrite_patch()
    ral = frappe.new_doc("Repost Accounting Ledger")
    ral.company = doc.company
    ral.delete_cancelled_entries = 0
    ral.append("vouchers", {"voucher_type": voucher_type, "voucher_no": voucher_no})
    ral.flags.ignore_permissions = True
    ral.save()
    ral.submit()


def _bns_internal_transfer_docs_for_asset(asset_name: str) -> List[Tuple[str, str]]:
    """Submitted BNS transfer documents that reference this asset (SI via native
    `asset`; DN/PR/PI via bns_transferred_asset)."""
    out: List[Tuple[str, str]] = []
    if not asset_name:
        return out
    for dt, field in (
        ("Sales Invoice", "asset"),
        ("Delivery Note", "bns_transferred_asset"),
        ("Purchase Receipt", "bns_transferred_asset"),
        ("Purchase Invoice", "bns_transferred_asset"),
    ):
        child = dt + " Item"
        try:
            if not frappe.get_meta(child).has_field(field):
                continue
        except Exception:
            continue
        parents = frappe.get_all(child, filters={field: asset_name}, pluck="parent")
        for parent in set(parents):
            if frappe.db.get_value(dt, parent, "docstatus") == 1:
                out.append((dt, parent))
    return out


def _bns_repost_transfers_for_asset(asset_name: str) -> None:
    """Repost all submitted BNS internal transfers of an asset (background job)."""
    for voucher_type, voucher_no in _bns_internal_transfer_docs_for_asset(asset_name):
        try:
            _bns_repost_voucher_gl(voucher_type, voucher_no)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            logger.exception("BNS asset NBV repost failed for %s %s", voucher_type, voucher_no)


def bns_repost_asset_transfers_on_depreciation(doc, method: Optional[str] = None) -> None:
    """When a depreciation Journal Entry (incl. back-dated) changes an asset's
    NBV, repost any BNS internal transfers of that asset so their NBV-based GL
    stays correct. ERPNext keeps value_after_depreciation as a date-blind running
    balance with no asset-repost analog, so BNS reposts the dependent GL itself.
    """
    if getattr(doc, "doctype", None) != "Journal Entry":
        return
    if (doc.get("voucher_type") or "") != "Depreciation Entry":
        return
    asset_names = {
        (acc.get("reference_name") or "").strip()
        for acc in (doc.get("accounts") or [])
        if (acc.get("reference_type") or "") == "Asset" and (acc.get("reference_name") or "").strip()
    }
    for asset_name in asset_names:
        if not _bns_internal_transfer_docs_for_asset(asset_name):
            continue
        frappe.enqueue(
            "business_needed_solutions.bns_branch_accounting.utils._bns_repost_transfers_for_asset",
            queue="long",
            timeout=1800,
            asset_name=asset_name,
        )


def _voucher_owns_sle(voucher_type, doc) -> bool:
    """True when the voucher writes its OWN Stock Ledger Entries.

    Delivery Note / Purchase Receipt always move stock. Sales Invoice /
    Purchase Invoice move stock only when Update Stock is on — otherwise the
    stock (and its SLE) lives on the linked DN/PR. This is exactly ERPNext's
    Repost Item Valuation precondition (validate_update_stock), so it decides
    whether an RIV can / should be created for the voucher. update_stock=0
    invoices must be reposted GL-only (RAL); RIV would both throw and have
    nothing to recompute.
    """
    if voucher_type in ("Delivery Note", "Purchase Receipt"):
        return True
    if voucher_type in ("Sales Invoice", "Purchase Invoice"):
        return bool(cint(doc.get("update_stock")))
    return False


def _internal_stock_movement_uncaptured(doc) -> bool:
    """True when an internal SI/PI carries stock items but records no stock
    movement anywhere: Update Stock is off AND no source stock document is
    linked on any row (Delivery Note for SI, Purchase Receipt for PI).

    Such a document posts GL but leaves inventory unmoved — an inventory
    hole. The correct shapes are DN -> SI (stock on the DN) or an SI with
    Update Stock on (stock on the SI); likewise PR -> PI or PI with Update
    Stock for purchases.
    """
    dt = doc.doctype
    if dt == "Sales Invoice":
        if not is_bns_internal_customer(doc):
            return False
        src_field = "delivery_note"
    elif dt == "Purchase Invoice":
        if not is_bns_internal_supplier(doc):
            return False
        src_field = "purchase_receipt"
    else:
        return False

    if cint(doc.get("update_stock")):
        return False

    has_stock_item = False
    for it in doc.get("items") or []:
        if (it.get(src_field) or "").strip():
            return False  # stock movement owned by the linked DN/PR
        if not has_stock_item and cint(
            frappe.get_cached_value("Item", it.get("item_code"), "is_stock_item")
        ):
            has_stock_item = True
    return has_stock_item


def validate_internal_stock_movement_captured(doc, method: Optional[str] = None) -> None:
    """before_submit guard: an internal SI/PI with stock items must capture
    stock movement — via the DN->SI / PR->PI flow or with Update Stock on.

    Gated on the Phase-1 internal-transfer cutoff so historical amendments
    are not retro-blocked; only current/forward internal documents are
    enforced. See [[_internal_stock_movement_uncaptured]].
    """
    if doc.doctype not in ("Sales Invoice", "Purchase Invoice"):
        return
    if not is_after_internal_transfer_cutoff(doc.get("posting_date")):
        return
    if not _internal_stock_movement_uncaptured(doc):
        return

    if doc.doctype == "Sales Invoice":
        frappe.throw(
            _(
                "This internal Sales Invoice has stock items but no stock movement is captured. "
                "Create it from a Delivery Note (DN → SI) or enable 'Update Stock' so the goods "
                "actually leave inventory."
            ),
            title=_("Stock Movement Not Captured"),
        )
    else:
        frappe.throw(
            _(
                "This internal Purchase Invoice has stock items but no stock movement is captured. "
                "Link a Purchase Receipt (PR → PI) or enable 'Update Stock' so the goods actually "
                "enter inventory."
            ),
            title=_("Stock Movement Not Captured"),
        )


class BNSInternalTransferError(Exception):
    """Custom exception for BNS internal transfer operations."""
    pass


class BNSValidationError(Exception):
    """Custom exception for BNS validation operations."""
    pass


def get_received_items(reference_name: str, doctype: str, reference_fieldname: str) -> Dict:
    """
    Get already received items for a reference document.
    
    Tracks partial receipts to prevent over-receipt.
    
    Args:
        reference_name (str): Name of the source document (DN/SI)
        doctype (str): Target doctype (Purchase Receipt/Purchase Invoice)
        reference_fieldname (str): Field name in child table that references source item
        
    Returns:
        Dict: Map of (source_item_name, item_code) -> received_qty
    """
    reference_field = "bns_inter_company_reference"
    
    filters = {
        reference_field: reference_name,
        "docstatus": 1,
    }
    
    target_doctypes = frappe.get_all(
        doctype,
        filters=filters,
        as_list=True,
    )
    
    if not target_doctypes:
        return {}
    
    target_doctypes = [d[0] for d in target_doctypes]
    
    # Get received items as list of tuples (as_list=1 returns tuples)
    received_items_list = frappe.get_all(
        doctype + " Item",
        filters={"parent": ("in", target_doctypes)},
        fields=[reference_fieldname, "item_code", "qty"],
        as_list=1,
    )
    
    # Convert to dict format: (source_item_name, item_code) -> qty
    result = defaultdict(float)
    for row in received_items_list:
        if len(row) >= 3:
            source_item_name = row[0]
            item_code = row[1] if len(row) > 1 else None
            qty = flt(row[2] if len(row) > 2 else row[1])
            if source_item_name and item_code:
                result[(source_item_name, item_code)] += qty
    
    return result


def validate_inter_company_party(doctype: str, party: str, company: str, inter_company_reference: Optional[str] = None) -> None:
    """
    Validate inter-company party relationships.
    
    Checks that bns_represents_company matches between parties.
    Note: Skips "Allowed To Transact With" check as per BNS requirements.
    
    Args:
        doctype (str): Document type (Sales Invoice, Purchase Invoice, etc.)
        party (str): Party name (Customer/Supplier)
        company (str): Company name
        inter_company_reference (Optional[str]): Reference document name
        
    Raises:
        BNSValidationError: If validation fails
    """
    if not party:
        return
    
    if doctype in ["Sales Invoice", "Sales Order"]:
        partytype, ref_partytype = "Customer", "Supplier"
        
        if doctype == "Sales Invoice":
            ref_doc = "Purchase Invoice"
        else:
            ref_doc = "Purchase Order"
    else:
        partytype, ref_partytype = "Supplier", "Customer"
        
        if doctype == "Purchase Invoice":
            ref_doc = "Sales Invoice"
        else:
            ref_doc = "Sales Order"
    
    if inter_company_reference:
        # Validate against existing reference document
        if not frappe.db.exists(ref_doc, inter_company_reference):
            return
        
        doc = frappe.get_doc(ref_doc, inter_company_reference)
        ref_party = doc.supplier if doctype in ["Sales Invoice", "Sales Order"] else doc.customer
        
        # Check that party represents the reference document's company
        party_represents = frappe.db.get_value(partytype, {"name": party}, "bns_represents_company")
        
        if not party_represents or party_represents != doc.company:
            raise BNSValidationError(_("Invalid {0} for Inter Company Transaction.").format(_(partytype)))
        
        # Check that reference party represents the target company
        ref_party_represents = frappe.get_cached_value(ref_partytype, ref_party, "bns_represents_company")
        
        if not ref_party_represents or ref_party_represents != company:
            raise BNSValidationError(_("Invalid Company for Inter Company Transaction."))


def update_linked_doc(doctype: str, name: str, inter_company_reference: Optional[str]) -> None:
    """
    Update bidirectional linked document references.
    
    Args:
        doctype (str): Document type (Sales Invoice, Purchase Invoice, etc.)
        name (str): Document name
        inter_company_reference (Optional[str]): Reference document name
    """
    if not inter_company_reference:
        return
    
    ref_field = "bns_inter_company_reference"
    
    # Update the reference document with this document's name
    if doctype == "Sales Invoice":
        ref_doctype = "Purchase Invoice"
    elif doctype == "Purchase Invoice":
        ref_doctype = "Sales Invoice"
    elif doctype == "Delivery Note":
        ref_doctype = "Purchase Receipt"
    elif doctype == "Purchase Receipt":
        ref_doctype = "Delivery Note"
    else:
        return
    
    if frappe.db.exists(ref_doctype, inter_company_reference):
        frappe.db.set_value(ref_doctype, inter_company_reference, ref_field, name, update_modified=False)


def validate_internal_transfer_qty(doc) -> None:
    """
    Validate that PR/PI quantities don't exceed source document quantities.
    
    Args:
        doc: Purchase Receipt or Purchase Invoice document
        
    Raises:
        BNSValidationError: If quantities exceed source document
    """
    if doc.doctype not in ["Purchase Invoice", "Purchase Receipt"]:
        return
    
    inter_company_reference = (doc.get("bns_inter_company_reference") or "").strip()
    if not inter_company_reference:
        return

    if doc.doctype == "Purchase Receipt":
        if frappe.db.exists("Sales Invoice", inter_company_reference):
            parent_doctype = "Sales Invoice"
            reference_fieldname = "sales_invoice_item"
        elif frappe.db.exists("Delivery Note", inter_company_reference):
            parent_doctype = "Delivery Note"
            reference_fieldname = "delivery_note_item"
        else:
            return
    else:
        parent_doctype = "Sales Invoice"
        reference_fieldname = "sales_invoice_item"
    
    # Get item-wise transfer quantities from source document
    child_doctype = parent_doctype + " Item"
    
    # Check which fields exist based on doctype
    # Sales Invoice Item doesn't have returned_qty or received_qty
    has_returned_received_fields = parent_doctype not in ["Sales Invoice"]
    
    if has_returned_received_fields:
        fields = ["name", "item_code", "qty", "returned_qty", "received_qty"]
    else:
        fields = ["name", "item_code", "qty"]
    
    source_items = frappe.get_all(
        child_doctype,
        filters={"parent": inter_company_reference},
        fields=fields,
    )
    
    if not source_items:
        return
    
    # Calculate available quantities: qty + returned_qty - received_qty
    item_wise_transfer_qty = {}
    for item in source_items:
        key = (item.name, item.item_code)
        if has_returned_received_fields:
            available_qty = flt(item.qty or 0) + flt(item.get("returned_qty", 0) or 0) - flt(item.get("received_qty", 0) or 0)
        else:
            # For Sales Invoice Item, use qty directly
            available_qty = flt(item.qty or 0)
        item_wise_transfer_qty[key] = available_qty
    
    # Get already received quantities using canonical BNS source linkage.
    received_items = get_received_items(inter_company_reference, doc.doctype, reference_fieldname)
    
    # Calculate total received quantities including current document
    precision = frappe.get_precision(doc.doctype + " Item", "qty")
    over_receipt_allowance = frappe.db.get_single_value("Stock Settings", "over_delivery_receipt_allowance", cache=True) or 0
    
    # Check each item in current document
    for item in doc.items:
        source_item_name = item.get(reference_fieldname)
        item_code = item.get("item_code")
        
        if not source_item_name or not item_code:
            continue
        
        key = (source_item_name, item_code)
        transferred_qty = item_wise_transfer_qty.get(key, 0)
        
        if transferred_qty <= 0:
            continue
        
        # Calculate total received qty (already received + current)
        already_received = received_items.get(key, 0)
        current_qty = flt(item.qty or 0)
        total_received = already_received + current_qty
        
        # Apply over-receipt allowance if configured
        max_allowed = transferred_qty
        if over_receipt_allowance:
            max_allowed = transferred_qty + flt(transferred_qty * over_receipt_allowance / 100, precision)
        
        if total_received > flt(max_allowed, precision):
            frappe.throw(
                _("For Item {0} cannot be received more than {1} qty against the {2} {3}").format(
                    bold(item_code),
                    bold(flt(max_allowed, precision)),
                    bold(parent_doctype),
                    get_link_to_form(parent_doctype, inter_company_reference),
                )
            )


def _has_any_positive_received_qty(received_items: Dict[Tuple[str, str], float]) -> bool:
    """Return True if any already-received quantity exists for source item keys."""
    return any(flt(qty or 0) > 0 for qty in (received_items or {}).values())


def _validate_batch_serial_parity(source_item, target_item, source_label: str, target_label: str) -> None:
    """
    Verify batch/serial information is consistent between paired source and target items.

    For SBB-based items, compares both batch and serial entries between bundles.
    For legacy field items, compares batch_no/serial_no strings.
    Non-batch/serial items are skipped.

    Cross-fiscal-year note: if one side has batch/serial info and the other
    doesn't (e.g. source submitted before batch tracking was enabled), this
    function logs a warning instead of throwing — the mismatch is expected
    during the transition period.

    Args:
        source_item: Source document item row
        target_item: Target document item row
        source_label: Human-readable source doc label (e.g. "Delivery Note")
        target_label: Human-readable target doc label (e.g. "Purchase Receipt")
    """
    source_bundle = source_item.get("serial_and_batch_bundle")
    target_bundle = target_item.get("serial_and_batch_bundle")

    if source_bundle and target_bundle:
        _validate_sbb_batch_parity(source_bundle, target_bundle, source_item, source_label, target_label)
        _validate_sbb_serial_parity(source_bundle, target_bundle, source_item, source_label, target_label)
        return

    if (source_bundle and not target_bundle) or (not source_bundle and target_bundle):
        logger.warning(
            "SBB parity skip for item %s in %s -> %s: one side has "
            "serial_and_batch_bundle and the other does not "
            "(source=%s, target=%s). Expected during cross-fiscal-year transitions.",
            source_item.item_code, source_label, target_label,
            source_bundle or "None", target_bundle or "None",
        )
        return

    source_batch = (source_item.get("batch_no") or "").strip()
    target_batch = (target_item.get("batch_no") or "").strip()

    if source_batch and target_batch and source_batch != target_batch:
        frappe.throw(
            _(
                "Batch mismatch in {0} -> {1} for item {2}: "
                "source batch {3}, target batch {4}."
            ).format(source_label, target_label, bold(source_item.item_code), bold(source_batch), bold(target_batch)),
            title=_("Batch Parity Failed"),
        )

    if source_batch and not target_batch:
        logger.warning(
            "Batch parity skip for item %s in %s -> %s: source has batch_no "
            "%s but target has none. Expected during cross-FY transitions.",
            source_item.item_code, source_label, target_label, source_batch,
        )


def _validate_sbb_batch_parity(source_bundle, target_bundle, source_item, source_label, target_label):
    """Compare batch entries between two Serial and Batch Bundles."""
    from erpnext.stock.serial_batch_bundle import get_batches_from_bundle

    source_batches = get_batches_from_bundle(source_bundle)
    target_batches = get_batches_from_bundle(target_bundle)

    if not source_batches or not target_batches:
        return

    source_set = set(source_batches.keys())
    target_set = set(target_batches.keys())
    missing = source_set - target_set
    if missing:
        frappe.throw(
            _(
                "Batch mismatch in {0} -> {1} for item {2}: "
                "batches {3} present in source but missing in target."
            ).format(source_label, target_label, bold(source_item.item_code), ", ".join(missing)),
            title=_("Batch Parity Failed"),
        )


def _validate_sbb_serial_parity(source_bundle, target_bundle, source_item, source_label, target_label):
    """Compare serial number entries between two Serial and Batch Bundles."""
    from erpnext.stock.serial_batch_bundle import get_serial_nos_from_bundle

    source_serials = get_serial_nos_from_bundle(source_bundle)
    target_serials = get_serial_nos_from_bundle(target_bundle)

    if not source_serials or not target_serials:
        return

    source_set = set(source_serials)
    target_set = set(target_serials)
    missing = source_set - target_set
    if missing:
        display = ", ".join(list(missing)[:5])
        if len(missing) > 5:
            display += f" (+{len(missing) - 5} more)"
        frappe.throw(
            _(
                "Serial number mismatch in {0} -> {1} for item {2}: "
                "serial nos {3} present in source but missing in target."
            ).format(source_label, target_label, bold(source_item.item_code), display),
            title=_("Serial Parity Failed"),
        )


def _enforce_one_to_one_item_and_amount_parity(
    source_doc,
    target_doc,
    source_link_field: str,
    source_item_filter,
    source_label: str,
    target_label: str,
) -> None:
    """Ensure mapped target document is a strict one-to-one mirror of source."""
    source_items = [d for d in (source_doc.get("items") or []) if source_item_filter(d)]
    target_items = target_doc.get("items") or []

    if len(target_items) != len(source_items):
        frappe.throw(
            _(
                "Strict 1:1 mapping failed for {0} -> {1}. Source items: {2}, target items: {3}."
            ).format(source_label, target_label, len(source_items), len(target_items)),
            title=_("One-to-One Validation Failed"),
        )

    source_by_name = {d.get("name"): d for d in source_items if d.get("name")}
    for target_item in target_items:
        source_item_name = target_item.get(source_link_field)
        source_item = source_by_name.get(source_item_name)
        if not source_item:
            frappe.throw(
                _(
                    "Strict 1:1 mapping failed: target item {0} is not linked to a valid source item."
                ).format(target_item.get("item_code") or target_item.get("name")),
                title=_("One-to-One Validation Failed"),
            )

        # Force parity for key item identity/quantity/UOM/conversion/amount fields.
        target_item.item_code = source_item.get("item_code")
        target_item.uom = source_item.get("uom")
        if hasattr(source_item, "stock_uom"):
            target_item.stock_uom = source_item.get("stock_uom")
        target_item.conversion_factor = flt(source_item.get("conversion_factor") or target_item.get("conversion_factor") or 1)

        _validate_batch_serial_parity(source_item, target_item, source_label, target_label)

        numeric_fields = (
            "qty",
            "stock_qty",
            "rate",
            "base_rate",
            "amount",
            "base_amount",
            "net_rate",
            "base_net_rate",
            "net_amount",
            "base_net_amount",
        )
        for fieldname in numeric_fields:
            if hasattr(source_item, fieldname):
                setattr(target_item, fieldname, flt(source_item.get(fieldname) or 0))

    # Recalculate totals after forcing item parity, then verify key totals.
    target_doc.set_missing_values()

    header_fields = (
        # Taxable totals
        "total",
        "base_total",
        "net_total",
        "base_net_total",
        # Tax totals
        "total_taxes_and_charges",
        "base_total_taxes_and_charges",
        # Grand totals
        "grand_total",
        "base_grand_total",
    )
    for fieldname in header_fields:
        source_val = round(flt(source_doc.get(fieldname) or 0), 2)
        target_val = round(flt(target_doc.get(fieldname) or 0), 2)
        if source_val != target_val:
            frappe.throw(
                _(
                    "Strict 1:1 totals mismatch on {0} ({1}: {2}, {3}: {4})."
                ).format(fieldname, source_label, source_val, target_label, target_val),
                title=_("One-to-One Validation Failed"),
            )


def _docstatus_label(docstatus: int) -> str:
    """Return human-friendly docstatus label."""
    return {0: _("Draft"), 1: _("Submitted"), 2: _("Cancelled")}.get(cint(docstatus), str(docstatus))


def _get_existing_pr_for_source(source_name: str) -> Optional[Dict[str, Any]]:
    """Find existing non-cancelled PR linked to the given source DN/SI."""
    if not source_name:
        return None

    pr_name = frappe.db.get_value(
        "Purchase Receipt",
        {"bns_inter_company_reference": source_name, "docstatus": ["in", [0, 1]]},
        "name",
    )
    if not pr_name:
        return None

    pr_meta = frappe.db.get_value(
        "Purchase Receipt",
        pr_name,
        ["name", "docstatus"],
        as_dict=True,
    )
    return pr_meta


def _get_existing_pi_for_source(source_name: str) -> Optional[Dict[str, Any]]:
    """Find existing non-cancelled PI linked to the given source SI."""
    if not source_name:
        return None

    pi_name = frappe.db.get_value(
        "Purchase Invoice",
        {"bns_inter_company_reference": source_name, "docstatus": ["in", [0, 1]]},
        "name",
    )
    if not pi_name:
        return None

    pi_meta = frappe.db.get_value(
        "Purchase Invoice",
        pi_name,
        ["name", "docstatus"],
        as_dict=True,
    )
    return pi_meta


@frappe.whitelist()
def make_bns_internal_purchase_receipt(source_name: str, target_doc: Optional[Dict] = None) -> Dict:
    """
    Create a Purchase Receipt from a Delivery Note for internal customers.
    
    Args:
        source_name (str): Name of the source Delivery Note
        target_doc (Optional[Dict]): Target document for mapping
        
    Returns:
        Dict: Mapped Purchase Receipt document
        
    Raises:
        BNSValidationError: If validation fails
        BNSInternalTransferError: If internal transfer setup fails
    """
    _bns_require_doctype_write("Purchase Receipt")
    try:
        dn = frappe.get_doc("Delivery Note", source_name, for_update=True)

        if not is_after_internal_transfer_cutoff(dn.get("posting_date")):
            frappe.throw(
                _("Cannot create internal Purchase Receipt: source Delivery Note {0} is before the Internal Transfer Cutoff.").format(source_name),
                title=_("Cutoff Date Restriction"),
            )

        _validate_internal_delivery_note(dn)

        existing_pr = _get_existing_pr_for_source(dn.name)
        if existing_pr:
            frappe.throw(
                _(
                    "A Purchase Receipt ({0}) already exists for this Delivery Note in {1} state. You cannot create another one."
                ).format(existing_pr.get("name"), _docstatus_label(existing_pr.get("docstatus"))),
                title=_("Cannot Create Purchase Receipt"),
            )
        
        # Get representing company
        represents_company = _get_representing_company(dn.customer)
        
        # Validate inter-company party
        validate_inter_company_party("Purchase Receipt", dn.customer, represents_company)
        
        # Create mapped document
        doclist = get_mapped_doc(
            "Delivery Note",
            source_name,
            _get_delivery_note_mapping(),
            target_doc,
            _set_missing_values,
        )

        _enforce_one_to_one_item_and_amount_parity(
            source_doc=dn,
            target_doc=doclist,
            source_link_field="delivery_note_item",
            source_item_filter=lambda d: flt(d.get("qty") or 0) + flt(d.get("returned_qty") or 0) > 0,
            source_label="Delivery Note",
            target_label="Purchase Receipt",
        )
        
        # Validate quantities
        validate_internal_transfer_qty(doclist)

        logger.info(f"Successfully created internal Purchase Receipt from Delivery Note {source_name}")
        return doclist
        
    except Exception as e:
        logger.error(f"Error creating internal Purchase Receipt: {str(e)}")
        raise


def _validate_internal_delivery_note(dn) -> None:
    """Validate that the delivery note is for an internal customer."""
    if not dn.get("is_bns_internal_customer"):
        raise BNSValidationError(_("Delivery Note is not for an internal customer"))


def _get_representing_company(customer: str) -> str:
    """Get the company that the customer represents."""
    represents_company = frappe.db.get_value("Customer", customer, "bns_represents_company")
    if not represents_company:
        raise BNSValidationError(_("No company is assigned to the internal customer"))
    return represents_company


def _get_delivery_note_mapping() -> Dict[str, Any]:
    """Get the mapping configuration for Delivery Note to Purchase Receipt."""
    return {
        "Delivery Note": {
            "doctype": "Purchase Receipt",
            "field_map": {
                "name": "delivery_note",
            },
            "field_no_map": ["set_warehouse", "rejected_warehouse", "cost_center", "project", "location"],
            "validation": {"docstatus": ["=", 1]},
            "postprocess": _update_details,
        },
        "Delivery Note Item": {
            "doctype": "Purchase Receipt Item",
            "field_map": {
                "name": "delivery_note_item",
                "target_warehouse": "from_warehouse",
            },
            # Deliberately exclude purchase_order / purchase_order_item:
            # The DN items may reference a PO whose supplier differs from
            # the BNS internal supplier on the new PR.  Carrying them over
            # triggers ERPNext's validate_with_previous_doc() which
            # compares PR.supplier against PO.supplier and throws
            # "Incorrect value: Supplier must be equal to …".
            # serial_no, batch_no, serial_and_batch_bundle are handled in
            # _update_item() via _duplicate_serial_and_batch_bundle() — each
            # target document needs its own SBB, so raw copying is forbidden.
            "field_no_map": ["warehouse", "rejected_warehouse", "expense_account", "cost_center", "project", "location",
                             "purchase_order", "purchase_order_item",
                             "serial_no", "batch_no", "serial_and_batch_bundle"],
            # Do not depend on DN item.received_qty here; it can drift from
            # actual submitted PR linkage in amendment/relink scenarios.
            # Remaining qty is finalized in _set_missing_values() via
            # get_received_items() against submitted PR documents.
            "condition": lambda item: flt(item.qty) + flt(item.returned_qty or 0) > 0,
            "postprocess": _update_item,
        },
    }


def _set_missing_values(source, target) -> None:
    """Set missing values for the target Purchase Receipt."""
    target.run_method("set_missing_values")
    
    # Get received items to track partial receipts
    received_items = get_received_items(source.name, "Purchase Receipt", "delivery_note_item")
    
    # Strict one-to-one mode: do not allow partial PR generation.
    if _has_any_positive_received_qty(received_items):
        frappe.throw(
            _("Strict one-to-one mode: Purchase Receipt already exists for this Delivery Note. Partial creation is not allowed."),
            title=_("Cannot Create Purchase Receipt"),
        )
    
    # Clear document level warehouses and accounting dimensions
    _clear_document_level_fields(target)


def _clear_document_level_fields(target) -> None:
    """Clear warehouse and accounting dimension fields at document level."""
    target.rejected_warehouse = None
    target.set_warehouse = None
    target.cost_center = None
    
    # Clear optional fields if they exist
    for field in ['location', 'project']:
        if hasattr(target, field):
            setattr(target, field, None)


def _update_details(source_doc, target_doc, source_parent) -> None:
    """
    Update details for the Purchase Receipt from Delivery Note.
    
    TRANSFER UNDER SAME GSTIN:
    - is_bns_internal_customer = 1
    - status = "BNS Internally Transferred" (set on submit)
    - supplier_delivery_note = DN name
    - per_billed = 100% (set on submit)
    """
    # Handle case where source_parent might be None (when called as postprocess)
    if source_parent is None:
        # This is being called as a postprocess function, so we need to get the data differently
        # The source_doc is the Delivery Note, and target_doc is the Purchase Receipt
        represents_company = _get_representing_company(source_doc.customer)
        target_doc.company = represents_company
        
        # Find supplier representing the delivery note's company
        supplier = _find_internal_supplier(represents_company)
        target_doc.supplier = supplier
        
        # Set internal transfer fields
        target_doc.buying_price_list = source_doc.selling_price_list
        target_doc.bns_inter_company_reference = source_doc.name
        
        # Set supplier_delivery_note = DN name (TRANSFER UNDER SAME GSTIN)
        target_doc.supplier_delivery_note = source_doc.name
        
        # Set is_bns_internal_supplier = 1 (TRANSFER UNDER SAME GSTIN)
        target_doc.is_bns_internal_supplier = 1
        
        # Do NOT set standard represents_company or inter_company_reference on PR; use BNS fields only.

        # Handle addresses
        _update_addresses(target_doc, source_doc)
        
        # Handle taxes
        _update_taxes(target_doc)
    else:
        # This is being called from the main function with proper parameters
        represents_company = _get_representing_company(source_doc.customer)
        target_doc.company = represents_company
        
        # Find supplier representing the delivery note's company
        supplier = _find_internal_supplier(represents_company)
        target_doc.supplier = supplier
        
        # Set internal transfer fields
        target_doc.buying_price_list = source_doc.selling_price_list
        target_doc.bns_inter_company_reference = source_doc.name
        
        # Set supplier_delivery_note = DN name (TRANSFER UNDER SAME GSTIN)
        target_doc.supplier_delivery_note = source_doc.name
        
        # Set is_bns_internal_supplier = 1 (TRANSFER UNDER SAME GSTIN)
        target_doc.is_bns_internal_supplier = 1
        
        # Do NOT set standard represents_company or inter_company_reference on PR; use BNS fields only.

        # Update delivery note with reference
        _update_delivery_note_reference(source_doc.name, target_doc.name)
        
        # Handle addresses
        _update_addresses(target_doc, source_doc)
        
        # Handle taxes
        _update_taxes(target_doc)


def _find_internal_supplier(company: str) -> str:
    """Find supplier that represents the given company."""
    supplier = frappe.get_all(
        "Supplier",
        filters={
            "is_bns_internal_supplier": 1,
            "bns_represents_company": company
        },
        limit=1
    )
    
    if not supplier:
        raise BNSInternalTransferError(_("No supplier found for Inter Company Transactions which represents company {0}").format(company))
        
    return supplier[0].name


def _update_delivery_note_reference(dn_name: str, pr_name: str) -> None:
    """Update delivery note with purchase receipt reference."""
    # Do NOT update status here - it's handled by on_submit hook
    frappe.db.set_value("Delivery Note", dn_name, {
        "bns_inter_company_reference": pr_name
    }, update_modified=False)
    # Update bidirectional reference
    update_linked_doc("Purchase Receipt", pr_name, dn_name)


def _update_addresses(target_doc, source_doc) -> None:
    """Update addresses for internal transfer.

    For BNS internal transfers the DN's company_address is the *logical*
    supplier address on the receiving PR, but ERPNext validates that the
    ``supplier_address`` has a Dynamic Link to the Supplier.  To avoid
    "Billing Address does not belong to the Supplier" errors we resolve
    the supplier_address to an address that is actually linked to the
    Supplier.  If the DN's company_address is already linked to the
    Supplier (common when the Supplier represents the same company), we
    use it directly.  Otherwise we fall back to the Supplier's default
    address.  If no linked address exists at all, we skip setting
    supplier_address so the user can fill it manually without being
    blocked.
    """
    # For Purchase Receipt, swap shipping/dispatch addresses (inverse)
    if target_doc.doctype == "Purchase Receipt":
        # Resolve supplier_address: prefer source company_address if it
        # belongs to the supplier, otherwise fall back to supplier default.
        supplier = target_doc.supplier
        supplier_address = _resolve_supplier_address(
            supplier, source_doc.company_address
        )
        if supplier_address:
            update_address(target_doc, "supplier_address", "address_display", supplier_address)
        else:
            # Clear supplier_address so validation won't choke on a
            # mismatched address; the user can set it manually.
            target_doc.supplier_address = None
            target_doc.address_display = None

        # Customer address becomes billing address (company-linked, no
        # party validation on billing_address for Purchase Receipt).
        if source_doc.customer_address:
            update_address(target_doc, "billing_address", "billing_address_display", source_doc.customer_address)

        # Shipping address = Dispatch address from source (inverse)
        if source_doc.dispatch_address_name:
            update_address(target_doc, "shipping_address", "shipping_address_display", source_doc.dispatch_address_name)
        else:
            # Clear shipping address if not in source document
            target_doc.shipping_address = None
            target_doc.shipping_address_name = None
            target_doc.shipping_address_display = None
        # Dispatch address = Shipping address from source (inverse)
        if source_doc.shipping_address_name:
            update_address(target_doc, "dispatch_address", "dispatch_address_display", source_doc.shipping_address_name)
        else:
            # Clear dispatch address if not in source document
            target_doc.dispatch_address = None
            target_doc.dispatch_address_name = None
            target_doc.dispatch_address_display = None
        # Clear templates for BNS internal transfers
        target_doc.dispatch_address_template = None
        target_doc.shipping_address_template = None
    else:
        # For other doctypes, use the original swapping logic
        update_address(target_doc, "supplier_address", "address_display", source_doc.company_address)
        update_address(target_doc, "shipping_address", "shipping_address_display", source_doc.customer_address)
        update_address(target_doc, "billing_address", "billing_address_display", source_doc.customer_address)
        # Explicitly clear dispatch address and templates for BNS internal transfers
        target_doc.dispatch_address = None
        target_doc.dispatch_address_name = None
        target_doc.dispatch_address_display = None
        target_doc.dispatch_address_template = None
        target_doc.shipping_address_template = None


def _resolve_supplier_address(supplier: str, preferred_address: Optional[str] = None) -> Optional[str]:
    """Return an address linked to *supplier* via Dynamic Link.

    1. If *preferred_address* is already linked to the supplier, return it.
    2. Otherwise return the supplier's default / first linked address.
    3. If no linked address exists, return ``None``.
    """
    if not supplier:
        return preferred_address

    # Addresses linked to this Supplier via Dynamic Link
    linked_addresses = frappe.get_all(
        "Dynamic Link",
        filters={
            "link_doctype": "Supplier",
            "link_name": supplier,
            "parenttype": "Address",
        },
        pluck="parent",
    )

    if not linked_addresses:
        logger.debug(f"No addresses linked to Supplier {supplier}")
        return None

    # Prefer the address we already have if it's linked
    if preferred_address and preferred_address in linked_addresses:
        return preferred_address

    # Fall back to the supplier's default address or first available
    default_address = frappe.db.get_value(
        "Dynamic Link",
        {
            "link_doctype": "Supplier",
            "link_name": supplier,
            "parenttype": "Address",
        },
        "parent",
    )
    return default_address or linked_addresses[0]


def _update_taxes(target_doc) -> None:
    """Update taxes for the purchase receipt."""
    # Recalculate taxes based on supplier and addresses
    update_taxes(
        target_doc,
        party=target_doc.supplier,
        party_type="Supplier",
        company=target_doc.company,
        doctype=target_doc.doctype,
        party_address=target_doc.supplier_address,
        company_address=target_doc.shipping_address,
    )


def _update_item(source, target, source_parent) -> None:
    """Update item details for the purchase receipt item."""
    source_qty = flt(source.qty or 0)
    returned_qty = flt(source.returned_qty or 0)
    received_qty = flt(source.received_qty or 0)
    target.qty = source_qty + returned_qty - received_qty

    conversion_factor = flt(source.conversion_factor or 1)
    source_stock_qty = flt(source.stock_qty or source_qty)
    returned_stock_qty = returned_qty * conversion_factor
    received_stock_qty = received_qty * conversion_factor
    target.stock_qty = source_stock_qty + returned_stock_qty - received_stock_qty
    
    # Map net_rate and base_net_rate from source (taxable rate)
    if source.get("net_rate"):
        target.net_rate = flt(source.net_rate)
    if source.get("base_net_rate"):
        target.base_net_rate = flt(source.base_net_rate)

    # BNS transfer rate is the source DN item's outgoing valuation mirror (incoming_rate on DN Item).
    # Keep this separate from billing/net rate.
    if getattr(target, "meta", None) and target.meta.has_field("bns_transfer_rate"):
        target.bns_transfer_rate = _get_dn_item_transfer_rate(source)
    
    target.received_qty = 0

    # Do NOT carry purchase_order / purchase_order_item from the DN.
    # The DN's PO belongs to a different supplier; copying it causes
    # ERPNext's validate_with_previous_doc() to throw
    # "Incorrect value: Supplier must be equal to …".
    target.purchase_order = None
    target.purchase_order_item = None
    
    target_wh = target.warehouse or target.rejected_warehouse

    # Clear accounting fields to let system auto-populate
    _clear_item_level_fields(target)

    _duplicate_serial_and_batch_bundle(
        source, target,
        target_warehouse=target_wh,
        transaction_type="Inward",
    )


def _get_dn_item_transfer_rate(dn_item) -> float:
    """Get outgoing valuation mirror for a Delivery Note Item."""
    rate = flt(dn_item.get("incoming_rate") or 0)
    if rate:
        return rate

    # Fallback to DB in case mapper source did not carry incoming_rate.
    if dn_item.get("name"):
        return flt(
            frappe.db.get_value("Delivery Note Item", dn_item.get("name"), "incoming_rate") or 0
        )
    return 0.0


def _get_si_item_transfer_rate(si_item) -> float:
    """Get outgoing valuation mirror for a Sales Invoice Item."""
    rate = flt(si_item.get("incoming_rate") or 0)
    if rate:
        return rate

    # Fallback to DB in case mapper source did not carry incoming_rate.
    if si_item.get("name"):
        return flt(
            frappe.db.get_value("Sales Invoice Item", si_item.get("name"), "incoming_rate") or 0
        )
    return 0.0


def _clear_item_level_fields(target) -> None:
    """Clear accounting and warehouse fields at item level."""
    # Clear accounting fields
    target.expense_account = None
    target.cost_center = None
    
    # Clear warehouse fields
    target.warehouse = None
    target.rejected_warehouse = None
    
    # Clear other accounting dimensions
    for field in ['location', 'project']:
        if hasattr(target, field):
            setattr(target, field, None)





def update_delivery_note_status_for_bns_internal(doc, method: Optional[str] = None) -> None:
    """
    Update the status of a Delivery Note based on GSTIN match.
    
    TRANSFER UNDER SAME GSTIN:
    - is_bns_internal_customer = 1
    - status = "BNS Internally Transferred"
    - per_billed = 100%
    
    TRANSFER UNDER DIFFERENT GSTIN:
    - is_bns_internal_customer = 0
    - status = "To Bill"
    
    Args:
        doc: The Delivery Note document
        method (Optional[str]): The method being called
    """
    if doc.docstatus != 1:
        return
    if not is_after_internal_transfer_cutoff(doc.get("posting_date")):
        return

    if doc.status == "BNS Internally Transferred":
        return

    if not is_bns_internal_customer(doc):
        return

    try:
        billing_address_gstin = getattr(doc, 'billing_address_gstin', None)
        company_gstin = getattr(doc, 'company_gstin', None)

        if billing_address_gstin is not None and company_gstin is not None:
            # Treat diff-GSTIN DN as same-GSTIN when the DN carries the
            # per-document opt-in flag — the DN-PR direct flow needs the
            # internal-customer flag and the "BNS Internally Transferred"
            # status so the rest of the BNS pipeline (status, per_billed, GL
            # rewrite, repost) applies.
            route_as_same_gstin = billing_address_gstin == company_gstin or _diff_gstin_dn_pr_active_for_dn(doc)
            if route_as_same_gstin:
                per_billed = 100
                doc.db_set("status", "BNS Internally Transferred", update_modified=False)
                doc.db_set("per_billed", per_billed, update_modified=False)
                doc.db_set("is_bns_internal_customer", 1, update_modified=False)
                if is_after_accounting_rewrite_cutoff(doc.get("posting_date")):
                    _trigger_bns_internal_gl_repost(doc, source="dn_on_submit_status_update")
                frappe.clear_cache(doctype="Delivery Note")
                logger.info(f"Updated Delivery Note {doc.name} status to BNS Internally Transferred (same GSTIN or diff-GSTIN override)")
            else:
                doc.db_set("status", "To Bill", update_modified=False)
                doc.db_set("is_bns_internal_customer", 0, update_modified=False)
                frappe.clear_cache(doctype="Delivery Note")
                logger.info(f"Updated Delivery Note {doc.name} status to To Bill (different GSTIN)")

    except Exception as e:
        logger.error(f"Error updating Delivery Note status: {str(e)}")
        raise


def update_purchase_receipt_status_for_bns_internal(doc, method: Optional[str] = None) -> None:
    """
    Update the status of a Purchase Receipt based on is_bns_internal_supplier.
    
    TRANSFER UNDER SAME GSTIN (from DN):
    - is_bns_internal_supplier = 1
    - status = "BNS Internally Transferred"
    - per_billed = 100%
    
    TRANSFER UNDER DIFFERENT GSTIN (from SI):
    - is_bns_internal_supplier = 0
    - status = "To Bill"
    
    Args:
        doc: The Purchase Receipt document
        method (Optional[str]): The method being called
    """
    if doc.docstatus != 1:
        return

    if doc.status == "BNS Internally Transferred":
        return

    try:
        is_bns_internal = is_bns_internal_supplier(doc)
        source_ref = (doc.get("bns_inter_company_reference") or "").strip()
        legacy_ref = (doc.get("supplier_delivery_note") or "").strip()
        source_dn = None
        source_si = None

        if source_ref:
            if frappe.db.exists("Delivery Note", source_ref):
                source_dn = source_ref
                is_bns_internal = True
            elif frappe.db.exists("Sales Invoice", source_ref):
                source_si = source_ref
                is_bns_internal = False
        elif legacy_ref:
            if frappe.db.exists("Delivery Note", legacy_ref):
                source_dn = legacy_ref
                is_bns_internal = True
            elif frappe.db.exists("Sales Invoice", legacy_ref):
                source_si = legacy_ref
                is_bns_internal = False

        effective_date = None
        source_name = source_dn or source_si
        if source_name:
            for dt in ("Delivery Note", "Sales Invoice"):
                sd = frappe.db.get_value(dt, source_name, "posting_date")
                if sd:
                    effective_date = sd
                    break
        if not effective_date:
            effective_date = doc.get("posting_date")

        if not is_after_internal_transfer_cutoff(effective_date):
            return

        if is_bns_internal != doc.get("is_bns_internal_supplier"):
            doc.is_bns_internal_supplier = is_bns_internal

        if is_bns_internal:
            per_billed = 100
            doc.db_set("status", "BNS Internally Transferred", update_modified=False)
            doc.db_set("per_billed", per_billed, update_modified=False)
            doc.db_set("is_bns_internal_supplier", 1, update_modified=False)
            if source_dn:
                _update_delivery_note_reference(source_dn, doc.name)
                frappe.clear_cache(doctype="Delivery Note")
            if is_after_accounting_rewrite_cutoff(effective_date):
                if source_dn:
                    _sync_pr_item_transfer_rate_from_dn(source_dn, pr_name=doc.name)
                    _mirror_pr_item_valuation_from_transfer_rate(doc.name)
                    _sync_pr_sle_from_transfer_rate(doc.name)
                _trigger_bns_internal_gl_repost(doc, source="pr_on_submit_status_update")
            frappe.clear_cache(doctype="Purchase Receipt")
            logger.info(f"Updated Purchase Receipt {doc.name} status to BNS Internally Transferred (from DN)")
        else:
            if doc.status != "To Bill":
                doc.db_set("status", "To Bill", update_modified=False)
            doc.db_set("is_bns_internal_supplier", 0, update_modified=False)
            if source_si and is_after_accounting_rewrite_cutoff(effective_date):
                _sync_pr_item_transfer_rate_from_si(source_si, pr_name=doc.name)
                _mirror_pr_item_valuation_from_transfer_rate(doc.name)
                _sync_pr_sle_from_transfer_rate(doc.name)
                _trigger_bns_internal_gl_repost(doc, source="pr_si_on_submit_transfer_rate_sync")
            frappe.clear_cache(doctype="Purchase Receipt")
            logger.info(f"Updated Purchase Receipt {doc.name} status to To Bill (from SI)")

    except Exception as e:
        logger.error(f"Error updating Purchase Receipt status: {str(e)}")
        raise


# Temporarily disabled unused helper (kept commented for rollback safety).
# def _should_update_internal_status(doc, field_name: str, check_reference: bool = False) -> bool:
#     """Check if the document status should be updated for internal transfers."""
#     if doc.docstatus != 1:
#         return False
#
#     if check_reference:
#         return bool(doc.bns_inter_company_reference or getattr(doc, field_name, False))
#
#     return bool(getattr(doc, field_name, False))


def _get_submitted_prs_for_dn(dn_name: str) -> list[str]:
    """Get submitted Purchase Receipts linked to a Delivery Note for DN->PR flow."""
    pr_names = set(
        frappe.get_all(
            "Purchase Receipt",
            filters={"supplier_delivery_note": dn_name, "docstatus": 1},
            pluck="name",
        )
    )

    pr_names.update(
        frappe.get_all(
            "Purchase Receipt",
            filters={"bns_inter_company_reference": dn_name, "docstatus": 1},
            pluck="name",
        )
    )
    return list(pr_names)


def _get_submitted_prs_for_si(si_name: str) -> list[str]:
    """Get submitted Purchase Receipts linked to a Sales Invoice for SI->PR flow."""
    pr_names = set(
        frappe.get_all(
            "Purchase Receipt",
            filters={"bns_inter_company_reference": si_name, "docstatus": 1},
            pluck="name",
        )
    )
    pr_names.update(
        frappe.get_all(
            "Purchase Receipt",
            filters={"supplier_delivery_note": si_name, "docstatus": 1},
            pluck="name",
        )
    )
    return list(pr_names)


def _get_submitted_pis_for_si(si_name: str) -> list[str]:
    """Get submitted Purchase Invoices linked to a Sales Invoice for SI->PI flow."""
    pi_names = set(
        frappe.get_all(
            "Purchase Invoice",
            filters={"bns_inter_company_reference": si_name, "docstatus": 1},
            pluck="name",
        )
    )
    pr_names = _get_submitted_prs_for_si(si_name)
    if pr_names:
        linked_pi_names = frappe.get_all(
            "Purchase Invoice Item",
            filters={"purchase_receipt": ("in", pr_names), "docstatus": 1},
            pluck="parent",
        )
        if linked_pi_names:
            pi_names.update(linked_pi_names)
    return sorted(pi_names)


def _mirror_pr_item_valuation_from_transfer_rate(pr_name: str) -> int:
    """Mirror PR item valuation_rate from bns_transfer_rate for DN->PR same-GSTIN flow.

    Only applies when the PR's governing source date is after the accounting
    rewrite cutoff so that the GL rewrite is also active.
    """
    if not pr_name or not frappe.db.exists("Purchase Receipt", pr_name):
        return 0

    pr_meta = frappe.get_meta("Purchase Receipt Item")
    if not pr_meta.has_field("bns_transfer_rate"):
        return 0

    pr = frappe.get_doc("Purchase Receipt", pr_name)
    if pr.docstatus != 1:
        return 0
    source_ref = (pr.get("bns_inter_company_reference") or pr.get("supplier_delivery_note") or "").strip()
    if not source_ref:
        return 0
    if not (
        (pr.get("is_bns_internal_supplier") and frappe.db.exists("Delivery Note", source_ref))
        or frappe.db.exists("Sales Invoice", source_ref)
    ):
        return 0
    if not is_after_accounting_rewrite_cutoff(_resolve_source_posting_date(pr)):
        return 0

    updated_count = 0
    pr_items = frappe.get_all(
        "Purchase Receipt Item",
        filters={"parent": pr_name},
        fields=["name", "bns_transfer_rate", "valuation_rate"],
    )
    for item in pr_items:
        transfer_rate = flt(item.get("bns_transfer_rate") or 0)
        if transfer_rate <= 0:
            continue
        if flt(item.get("valuation_rate") or 0) != transfer_rate:
            frappe.db.set_value(
                "Purchase Receipt Item",
                item.get("name"),
                "valuation_rate",
                transfer_rate,
                update_modified=False,
            )
            updated_count += 1

    if updated_count:
        frappe.clear_cache(doctype="Purchase Receipt")
        logger.info("Mirrored valuation_rate from bns_transfer_rate for %s PR item rows in %s", updated_count, pr_name)

    return updated_count


def _sync_pr_sle_from_transfer_rate(pr_name: str) -> int:
    """Sync PR Stock Ledger Entry incoming values from PR Item transfer-rate.

    Only applies when the PR's governing source date is after the accounting
    rewrite cutoff. Modifying SLE without the corresponding GL rewrite causes
    valuation drift.
    """
    if not pr_name or not frappe.db.exists("Purchase Receipt", pr_name):
        return 0

    pr = frappe.get_doc("Purchase Receipt", pr_name)
    if pr.docstatus != 1:
        return 0

    source_ref = (pr.get("bns_inter_company_reference") or pr.get("supplier_delivery_note") or "").strip()
    if not source_ref:
        return 0
    if not (
        (pr.get("is_bns_internal_supplier") and frappe.db.exists("Delivery Note", source_ref))
        or frappe.db.exists("Sales Invoice", source_ref)
    ):
        return 0
    if not is_after_accounting_rewrite_cutoff(_resolve_source_posting_date(pr)):
        return 0

    transfer_rate_by_item = {}
    for row in (pr.items or []):
        transfer_rate = flt(row.get("bns_transfer_rate") or 0)
        if transfer_rate > 0:
            transfer_rate_by_item[row.name] = transfer_rate
    if not transfer_rate_by_item:
        return 0

    sle_rows = frappe.get_all(
        "Stock Ledger Entry",
        filters={"voucher_type": "Purchase Receipt", "voucher_no": pr_name},
        fields=["name", "voucher_detail_no", "actual_qty", "incoming_rate", "stock_value_difference"],
    )
    if not sle_rows:
        return 0

    updated_count = 0
    for sle in sle_rows:
        if flt(sle.get("actual_qty") or 0) <= 0:
            continue
        transfer_rate = transfer_rate_by_item.get(sle.get("voucher_detail_no"))
        if not transfer_rate:
            continue

        expected_svd = flt(sle.get("actual_qty") or 0) * transfer_rate
        updates = {}
        if flt(sle.get("incoming_rate") or 0) != transfer_rate:
            updates["incoming_rate"] = transfer_rate
        if flt(sle.get("stock_value_difference") or 0) != expected_svd:
            updates["stock_value_difference"] = expected_svd

        if updates:
            frappe.db.set_value("Stock Ledger Entry", sle.get("name"), updates, update_modified=False)
            updated_count += 1

    if updated_count:
        frappe.clear_cache(doctype="Stock Ledger Entry")
        logger.info(
            "Synced PR SLE incoming/stock diff from transfer-rate for %s rows in %s",
            updated_count,
            pr_name,
        )
    _force_rebuild_bns_gl_for_voucher("Purchase Receipt", pr_name, context="pr_transfer_rate_sle_sync")
    return updated_count


def _mirror_pi_item_valuation_from_transfer_rate(pi_name: str) -> int:
    """Mirror PI item valuation_rate from bns_transfer_rate for SI->PI flow.

    Only applies when the PI's governing source date is after the accounting
    rewrite cutoff so that the GL rewrite is also active. Without the GL rewrite,
    changing valuation_rate would cause a debit/credit imbalance during repost.
    """
    if not pi_name or not frappe.db.exists("Purchase Invoice", pi_name):
        return 0

    pi_meta = frappe.get_meta("Purchase Invoice Item")
    if not pi_meta.has_field("bns_transfer_rate"):
        return 0

    pi = frappe.get_doc("Purchase Invoice", pi_name)
    if pi.docstatus != 1 or not pi.get("is_bns_internal_supplier"):
        return 0
    if not cint(pi.get("update_stock")):
        return 0
    source_ref = (pi.get("bns_inter_company_reference") or "").strip()
    if not source_ref or not frappe.db.exists("Sales Invoice", source_ref):
        return 0
    if not is_after_accounting_rewrite_cutoff(_resolve_source_posting_date(pi)):
        return 0

    updated_count = 0
    pi_items = frappe.get_all(
        "Purchase Invoice Item",
        filters={"parent": pi_name},
        fields=["name", "bns_transfer_rate", "valuation_rate"],
    )
    for item in pi_items:
        transfer_rate = flt(item.get("bns_transfer_rate") or 0)
        if transfer_rate <= 0:
            continue
        if flt(item.get("valuation_rate") or 0) != transfer_rate:
            frappe.db.set_value(
                "Purchase Invoice Item",
                item.get("name"),
                "valuation_rate",
                transfer_rate,
                update_modified=False,
            )
            updated_count += 1

    if updated_count:
        frappe.clear_cache(doctype="Purchase Invoice")
        logger.info("Mirrored valuation_rate from bns_transfer_rate for %s PI item rows in %s", updated_count, pi_name)

    return updated_count


def _sync_pi_sle_from_transfer_rate(pi_name: str) -> int:
    """Sync PI Stock Ledger Entry incoming values from PI Item transfer-rate.

    Only applies when the PI's governing source date is after the accounting
    rewrite cutoff. Modifying SLE without the corresponding GL rewrite causes
    debit/credit imbalance on the PI.
    """
    if not pi_name or not frappe.db.exists("Purchase Invoice", pi_name):
        return 0

    pi = frappe.get_doc("Purchase Invoice", pi_name)
    if pi.docstatus != 1 or not cint(pi.get("update_stock")):
        return 0
    if not is_after_accounting_rewrite_cutoff(_resolve_source_posting_date(pi)):
        return 0

    transfer_rate_by_item = {}
    for row in (pi.items or []):
        transfer_rate = flt(row.get("bns_transfer_rate") or 0)
        if transfer_rate > 0:
            transfer_rate_by_item[row.name] = transfer_rate
    if not transfer_rate_by_item:
        return 0

    sle_rows = frappe.get_all(
        "Stock Ledger Entry",
        filters={"voucher_type": "Purchase Invoice", "voucher_no": pi_name},
        fields=["name", "voucher_detail_no", "actual_qty", "incoming_rate", "stock_value_difference"],
    )
    if not sle_rows:
        return 0

    updated_count = 0
    for sle in sle_rows:
        if flt(sle.get("actual_qty") or 0) <= 0:
            continue
        transfer_rate = transfer_rate_by_item.get(sle.get("voucher_detail_no"))
        if not transfer_rate:
            continue

        expected_svd = flt(sle.get("actual_qty") or 0) * transfer_rate
        updates = {}
        if flt(sle.get("incoming_rate") or 0) != transfer_rate:
            updates["incoming_rate"] = transfer_rate
        if flt(sle.get("stock_value_difference") or 0) != expected_svd:
            updates["stock_value_difference"] = expected_svd

        if updates:
            frappe.db.set_value("Stock Ledger Entry", sle.get("name"), updates, update_modified=False)
            updated_count += 1

    if updated_count:
        frappe.clear_cache(doctype="Stock Ledger Entry")
        logger.info(
            "Synced PI SLE incoming/stock diff from transfer-rate for %s rows in %s",
            updated_count,
            pi_name,
        )
    # Keep accounting ledger in lockstep with SLE transfer-rate authority.
    _force_rebuild_bns_gl_for_voucher(
        "Purchase Invoice",
        pi_name,
        context="pi_transfer_rate_sle_sync",
    )
    return updated_count


def _sync_pr_item_transfer_rate_from_dn(dn_name: str, pr_name: Optional[str] = None) -> int:
    """Sync Purchase Receipt Item.bns_transfer_rate from Delivery Note Item.incoming_rate."""
    if not dn_name or not frappe.db.exists("Delivery Note", dn_name):
        return 0

    pr_item_meta = frappe.get_meta("Purchase Receipt Item")
    if not pr_item_meta.has_field("bns_transfer_rate"):
        return 0

    dn_items = frappe.get_all(
        "Delivery Note Item",
        filters={"parent": dn_name},
        fields=["name", "incoming_rate"],
    )
    if not dn_items:
        return 0

    dn_rate_by_item = {d.name: flt(d.incoming_rate or 0) for d in dn_items}

    if pr_name:
        pr_names = [pr_name] if frappe.db.exists("Purchase Receipt", pr_name) else []
    else:
        pr_names = _get_submitted_prs_for_dn(dn_name)

    if not pr_names:
        return 0

    updated_count = 0
    for current_pr in pr_names:
        pr_items = frappe.get_all(
            "Purchase Receipt Item",
            filters={"parent": current_pr},
            fields=["name", "delivery_note_item", "bns_transfer_rate"],
        )
        for item in pr_items:
            source_dn_item = item.get("delivery_note_item")
            if not source_dn_item:
                continue

            source_rate = dn_rate_by_item.get(source_dn_item)
            if source_rate is None:
                continue

            if flt(item.get("bns_transfer_rate") or 0) != flt(source_rate):
                frappe.db.set_value(
                    "Purchase Receipt Item",
                    item.get("name"),
                    "bns_transfer_rate",
                    flt(source_rate),
                    update_modified=False,
                )
                updated_count += 1
        _sync_pr_sle_from_transfer_rate(current_pr)

    if updated_count:
        frappe.clear_cache(doctype="Purchase Receipt")
        logger.info("Synced bns_transfer_rate for %s PR items from Delivery Note %s", updated_count, dn_name)

    return updated_count


def _sync_si_item_incoming_rate_from_dn(
    dn_name: str, si_name: Optional[str] = None
) -> Tuple[int, Set[str]]:
    """
    Sync Sales Invoice Item.incoming_rate from Delivery Note Item.incoming_rate.

    This is required for DN->SI chains where ERPNext repost updates DN valuation
    but does not always push updated incoming_rate into existing SI item rows.

    Only applies when the DN posting date is after the accounting rewrite cutoff
    to keep SI incoming_rate stable for pre-Phase-2 documents.
    """
    if not dn_name or not frappe.db.exists("Delivery Note", dn_name):
        return 0, set()
    dn_posting_date = frappe.db.get_value("Delivery Note", dn_name, "posting_date")
    if not is_after_accounting_rewrite_cutoff(dn_posting_date):
        return 0, set()

    dn_items = frappe.get_all(
        "Delivery Note Item",
        filters={"parent": dn_name},
        fields=["name", "incoming_rate"],
    )
    if not dn_items:
        return 0, set()

    dn_rate_by_item = {d.name: flt(d.incoming_rate or 0) for d in dn_items}
    if not dn_rate_by_item:
        return 0, set()

    si_filters: Dict[str, Any] = {"delivery_note": dn_name}
    if si_name:
        si_filters["parent"] = si_name

    si_items = frappe.get_all(
        "Sales Invoice Item",
        filters=si_filters,
        fields=["name", "parent", "dn_detail", "incoming_rate"],
    )
    if not si_items:
        return 0, set()

    submitted_sis = set(
        frappe.get_all(
            "Sales Invoice",
            filters={"name": ("in", sorted({row.parent for row in si_items})), "docstatus": 1},
            pluck="name",
        )
    )
    if not submitted_sis:
        return 0, set()

    updated_count = 0
    impacted_sis: Set[str] = set()
    for row in si_items:
        if row.parent not in submitted_sis:
            continue
        dn_detail = (row.get("dn_detail") or "").strip()
        if not dn_detail:
            continue
        source_rate = dn_rate_by_item.get(dn_detail)
        if source_rate is None:
            continue
        if flt(row.get("incoming_rate") or 0) != flt(source_rate):
            frappe.db.set_value(
                "Sales Invoice Item",
                row.get("name"),
                "incoming_rate",
                flt(source_rate),
                update_modified=False,
            )
            updated_count += 1
            impacted_sis.add(row.parent)

    if updated_count:
        frappe.clear_cache(doctype="Sales Invoice")
        logger.info(
            "Synced SI incoming_rate from Delivery Note %s for %s SI item rows across %s SI docs",
            dn_name,
            updated_count,
            len(impacted_sis),
        )

    return updated_count, impacted_sis


def _sync_pr_item_transfer_rate_from_si(si_name: str, pr_name: Optional[str] = None) -> int:
    """Sync Purchase Receipt Item.bns_transfer_rate from Sales Invoice Item.incoming_rate."""
    if not si_name or not frappe.db.exists("Sales Invoice", si_name):
        return 0

    pr_item_meta = frappe.get_meta("Purchase Receipt Item")
    if not pr_item_meta.has_field("bns_transfer_rate"):
        return 0

    si_items = frappe.get_all(
        "Sales Invoice Item",
        filters={"parent": si_name},
        fields=["name", "incoming_rate"],
    )
    if not si_items:
        return 0

    si_rate_by_item = {d.name: flt(d.incoming_rate or 0) for d in si_items}
    if pr_name:
        pr_names = [pr_name] if frappe.db.exists("Purchase Receipt", pr_name) else []
    else:
        pr_names = _get_submitted_prs_for_si(si_name)
    if not pr_names:
        return 0

    updated_count = 0
    for current_pr in pr_names:
        pr_items = frappe.get_all(
            "Purchase Receipt Item",
            filters={"parent": current_pr},
            fields=["name", "sales_invoice_item", "bns_transfer_rate"],
        )
        for item in pr_items:
            source_si_item = item.get("sales_invoice_item")
            if not source_si_item:
                continue
            source_rate = si_rate_by_item.get(source_si_item)
            if source_rate is None:
                continue
            if flt(item.get("bns_transfer_rate") or 0) != flt(source_rate):
                frappe.db.set_value(
                    "Purchase Receipt Item",
                    item.get("name"),
                    "bns_transfer_rate",
                    flt(source_rate),
                    update_modified=False,
                )
                updated_count += 1
        _sync_pr_sle_from_transfer_rate(current_pr)

    if updated_count:
        frappe.clear_cache(doctype="Purchase Receipt")
        logger.info("Synced bns_transfer_rate for %s PR items from Sales Invoice %s", updated_count, si_name)

    return updated_count


def _sync_pi_item_transfer_rate_from_si(si_name: str, pi_name: Optional[str] = None) -> int:
    """Sync Purchase Invoice Item.bns_transfer_rate from Sales Invoice Item.incoming_rate."""
    if not si_name or not frappe.db.exists("Sales Invoice", si_name):
        return 0

    pi_item_meta = frappe.get_meta("Purchase Invoice Item")
    if not pi_item_meta.has_field("bns_transfer_rate"):
        return 0

    if pi_name:
        pi_names = [pi_name] if frappe.db.exists("Purchase Invoice", pi_name) else []
    else:
        pi_names = _get_submitted_pis_for_si(si_name)
    if not pi_names:
        return 0

    updated_count = 0
    for current_pi in pi_names:
        current_pi_updated = False
        si_rate_by_item, si_rows, si_item_buckets = _build_si_rate_maps_for_pi(si_name)
        if not si_rate_by_item:
            continue
        si_dn_map: Dict[str, str] = {}
        for d in si_rows:
            dn = (d.get("delivery_note") or "").strip()
            if dn:
                si_dn_map[d.name] = dn
        pi_items = frappe.get_all(
            "Purchase Invoice Item",
            filters={"parent": current_pi},
            fields=[
                "name",
                "item_code",
                "qty",
                "stock_qty",
                "warehouse",
                "sales_invoice_item",
                "purchase_receipt",
                "pr_detail",
                "bns_transfer_rate",
            ],
        )

        pr_item_rates: Dict[str, float] = {}
        pr_detail_names = sorted(
            {
                (item.get("pr_detail") or "").strip()
                for item in pi_items
                if (item.get("pr_detail") or "").strip()
            }
        )
        if pr_detail_names:
            pr_rows = frappe.get_all(
                "Purchase Receipt Item",
                filters={"name": ("in", pr_detail_names)},
                fields=["name", "bns_transfer_rate"],
            )
            pr_item_rates = {row.name: flt(row.bns_transfer_rate or 0) for row in pr_rows}

        for item in pi_items:
            source_rate = None
            # A direct Sales Invoice Item link gives the authoritative source
            # rate INCLUDING a genuine 0 (zero-cost / sample transfer): that 0
            # must be copied so the receiver books the stock at 0 and the chain
            # nets. Only a truly unresolved row (no source link) is skipped.
            source_confirmed = False
            source_si_item = (item.get("sales_invoice_item") or "").strip()
            if source_si_item and source_si_item in si_rate_by_item:
                source_rate = flt(si_rate_by_item.get(source_si_item) or 0)
                source_confirmed = True

            # For SI->PR->PI chain, keep PI transfer-rate aligned from PR item linkage.
            # PR owns stock SLE/GL legs, but PI transfer-rate should remain consistent.
            if not source_confirmed and (source_rate is None or flt(source_rate) <= 0):
                pr_detail = (item.get("pr_detail") or "").strip()
                if pr_detail:
                    source_rate = pr_item_rates.get(pr_detail)

            if not source_confirmed and (source_rate is None or flt(source_rate) <= 0):
                rate2, link2 = _resolve_pi_item_transfer_rate_extras(
                    item, si_name, si_rate_by_item, pr_item_rates, si_item_buckets,
                    si_dn_map=si_dn_map,
                )
                if rate2 > 0:
                    source_rate = rate2
                    link2 = (link2 or "").strip()
                    if link2 and pi_item_meta.has_field("sales_invoice_item"):
                        cur_link = (item.get("sales_invoice_item") or "").strip()
                        if not cur_link:
                            frappe.db.set_value(
                                "Purchase Invoice Item",
                                item.get("name"),
                                "sales_invoice_item",
                                link2,
                                update_modified=False,
                            )

            if source_confirmed:
                rate_to_set = flt(source_rate or 0)
            elif source_rate is None or flt(source_rate) <= 0:
                continue
            else:
                rate_to_set = flt(source_rate)

            if flt(item.get("bns_transfer_rate") or 0) != rate_to_set:
                frappe.db.set_value(
                    "Purchase Invoice Item",
                    item.get("name"),
                    "bns_transfer_rate",
                    rate_to_set,
                    update_modified=False,
                )
                updated_count += 1
                current_pi_updated = True

        if current_pi_updated:
            _sync_pi_sle_from_transfer_rate(current_pi)

    if updated_count:
        frappe.clear_cache(doctype="Purchase Invoice")
        logger.info("Synced bns_transfer_rate for %s PI items from Sales Invoice %s", updated_count, si_name)

    return updated_count


def _trigger_pr_repost_for_transfer_rate(pr_name: str, source_repost_name: str) -> bool:
    """Trigger PR repost after transfer-rate mirror with lock-first and finally cleanup.

    Only triggers when the PR's governing source date is after the accounting
    rewrite cutoff so the GL rewrite is active during the repost.
    """
    if not pr_name or not frappe.db.exists("Purchase Receipt", pr_name):
        return False
    per_repost_key = f"bns_transfer_rate_pr_repost::{source_repost_name}::{pr_name}"
    if frappe.cache().get_value(per_repost_key):
        return False
    is_real_repost_doc = bool(
        source_repost_name and frappe.db.exists("Repost Item Valuation", source_repost_name)
    )
    scope = "pr_transfer_rate_repost" if is_real_repost_doc else "bns_internal_gl_repost"
    repost_doc_name = source_repost_name if is_real_repost_doc else pr_name
    voucher_type = "Purchase Receipt"
    voucher_no = pr_name
    if not _claim_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no):
        return False
    pr = frappe.get_doc("Purchase Receipt", pr_name)
    if pr.docstatus != 1:
        _release_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no)
        return False
    source_ref = (pr.get("bns_inter_company_reference") or pr.get("supplier_delivery_note") or "").strip()
    if not source_ref:
        _release_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no)
        return False
    if not (
        (pr.get("is_bns_internal_supplier") and frappe.db.exists("Delivery Note", source_ref))
        or frappe.db.exists("Sales Invoice", source_ref)
    ):
        _release_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no)
        return False
    if not is_after_accounting_rewrite_cutoff(_resolve_source_posting_date(pr)):
        _release_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no)
        return False
    try:
        _apply_bns_transfer_rate_stock_ledger_patch()
        pr.repost_future_sle_and_gle(force=True)
        _mark_bns_repost_tracking_processed(scope, repost_doc_name, voucher_type, voucher_no)
        frappe.cache().set_value(per_repost_key, 1, expires_in_sec=6 * 60 * 60)
        logger.info("Triggered PR repost for transfer-rate sync: %s (source repost: %s)", pr_name, source_repost_name)
        return True
    except Exception as e:
        _mark_bns_repost_tracking_failed(scope, repost_doc_name, voucher_type, voucher_no, str(e))
        logger.error("PR repost for transfer-rate failed %s: %s", pr_name, str(e))
        return False
    finally:
        _release_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no)


def _trigger_pi_repost_for_transfer_rate(pi_name: str, source_repost_name: str) -> bool:
    """Trigger PI repost after transfer-rate mirror with lock-first and finally cleanup.

    Only triggers when the PI's governing source date is after the accounting
    rewrite cutoff so the GL rewrite is active during the repost. Without the GL
    rewrite, the repost would produce imbalanced GL entries.
    """
    if not pi_name or not frappe.db.exists("Purchase Invoice", pi_name):
        return False
    per_repost_key = f"bns_transfer_rate_pi_repost::{source_repost_name}::{pi_name}"
    if frappe.cache().get_value(per_repost_key):
        return False
    is_real_repost_doc = bool(
        source_repost_name and frappe.db.exists("Repost Item Valuation", source_repost_name)
    )
    scope = "pi_transfer_rate_repost" if is_real_repost_doc else "bns_internal_gl_repost"
    repost_doc_name = source_repost_name if is_real_repost_doc else pi_name
    voucher_type = "Purchase Invoice"
    voucher_no = pi_name
    if not _claim_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no):
        return False
    pi = frappe.get_doc("Purchase Invoice", pi_name)
    if pi.docstatus != 1:
        _release_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no)
        return False
    if not pi.get("is_bns_internal_supplier") or not cint(pi.get("update_stock")):
        _release_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no)
        return False
    source_ref = (pi.get("bns_inter_company_reference") or "").strip()
    if not source_ref or not frappe.db.exists("Sales Invoice", source_ref):
        _release_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no)
        return False
    if not is_after_accounting_rewrite_cutoff(_resolve_source_posting_date(pi)):
        _release_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no)
        return False
    try:
        _apply_bns_transfer_rate_stock_ledger_patch()
        pi.repost_future_sle_and_gle(force=True)
        _mark_bns_repost_tracking_processed(scope, repost_doc_name, voucher_type, voucher_no)
        frappe.cache().set_value(per_repost_key, 1, expires_in_sec=6 * 60 * 60)
        logger.info("Triggered PI repost for transfer-rate sync: %s (source repost: %s)", pi_name, source_repost_name)
        return True
    except Exception as e:
        _mark_bns_repost_tracking_failed(scope, repost_doc_name, voucher_type, voucher_no, str(e))
        logger.error("PI repost for transfer-rate failed %s: %s", pi_name, str(e))
        return False
    finally:
        _release_bns_repost_lock(scope, repost_doc_name, voucher_type, voucher_no)


def _resolve_impacted_vouchers_for_repost(
    doc, target_voucher_type: str
) -> Tuple[List[str], Dict[str, int]]:
    """
    Resolve impacted vouchers for repost callbacks across both repost modes.

    Sources:
    - direct transaction metadata on repost doc
    - get_affected_transactions(doc)
    - item+warehouse fallback via get_future_stock_vouchers
    """
    discovered: Set[str] = set()
    source_counts = {
        "transaction": 0,
        "affected_transactions": 0,
        "item_warehouse_fallback": 0,
    }

    def _add_if_valid(voucher_no: Optional[str], source_key: str) -> None:
        if (
            voucher_no
            and voucher_no not in discovered
            and frappe.db.exists(target_voucher_type, voucher_no)
        ):
            discovered.add(voucher_no)
            source_counts[source_key] += 1

    if (
        doc.get("based_on") == "Transaction"
        and doc.get("voucher_type") == target_voucher_type
        and doc.get("voucher_no")
    ):
        _add_if_valid(doc.get("voucher_no"), "transaction")

    try:
        from erpnext.stock.stock_ledger import get_affected_transactions

        affected = get_affected_transactions(doc)
    except Exception:
        affected = set()

    for voucher_type, voucher_no in affected:
        if voucher_type == target_voucher_type:
            _add_if_valid(voucher_no, "affected_transactions")

    # Item+warehouse repost can miss direct transaction context for SI/DN source docs.
    if (
        doc.get("based_on") == "Item and Warehouse"
        and doc.get("item_code")
        and doc.get("warehouse")
        and doc.get("company")
        and doc.get("posting_date")
    ):
        try:
            from erpnext.accounts.utils import get_future_stock_vouchers

            fallback_vouchers = get_future_stock_vouchers(
                posting_date=doc.get("posting_date"),
                posting_time=doc.get("posting_time") or "00:00:00",
                for_warehouses=[doc.get("warehouse")],
                for_items=[doc.get("item_code")],
                company=doc.get("company"),
            )
        except Exception:
            fallback_vouchers = []

        for voucher_type, voucher_no in fallback_vouchers:
            if voucher_type == target_voucher_type:
                _add_if_valid(voucher_no, "item_warehouse_fallback")

    return sorted(discovered), source_counts


def refresh_pr_transfer_rate_after_repost(doc, method: Optional[str] = None) -> None:
    """Refresh PR item bns_transfer_rate after repost completion (DN->PR same GSTIN)."""
    if doc.doctype != "Repost Item Valuation":
        return
    if doc.docstatus != 1 or doc.status != "Completed":
        return

    _apply_bns_transfer_rate_stock_ledger_patch()

    cache_key = f"bns_transfer_rate_repost_done::{doc.name}"
    if frappe.cache().get_value(cache_key):
        return

    dn_names, source_counts = _resolve_impacted_vouchers_for_repost(doc, "Delivery Note")

    if not dn_names:
        logger.info(
            "Repost %s: no Delivery Note sources resolved (sources=%s)",
            doc.name,
            source_counts,
        )
        frappe.cache().set_value(cache_key, 1, expires_in_sec=_BNS_REPOST_CACHE_TTL_SEC)
        return

    logger.info(
        "Repost %s: resolved Delivery Note sources=%s (count=%s)",
        doc.name,
        source_counts,
        len(dn_names),
    )

    total_updated = 0
    total_mirrored = 0
    si_incoming_sync_count = 0
    impacted_sis_from_dn: Set[str] = set()
    affected_prs = set()
    for dn_name in dn_names:
        si_updated, impacted_sis = _sync_si_item_incoming_rate_from_dn(dn_name)
        si_incoming_sync_count += si_updated
        impacted_sis_from_dn.update(impacted_sis)
        for pr_name in _get_submitted_prs_for_dn(dn_name):
            updated = _sync_pr_item_transfer_rate_from_dn(dn_name, pr_name=pr_name)
            mirrored = _mirror_pr_item_valuation_from_transfer_rate(pr_name)
            total_updated += updated
            total_mirrored += mirrored
            if updated or mirrored:
                affected_prs.add(pr_name)

    # DN->SI->PR chain: once SI incoming_rate is synced from DN, propagate SI->PR transfer-rate.
    affected_pis: Set[str] = set()
    for si_name in sorted(impacted_sis_from_dn):
        for pr_name in _get_submitted_prs_for_si(si_name):
            updated = _sync_pr_item_transfer_rate_from_si(si_name, pr_name=pr_name)
            mirrored = _mirror_pr_item_valuation_from_transfer_rate(pr_name)
            total_updated += updated
            total_mirrored += mirrored
            if updated or mirrored:
                affected_prs.add(pr_name)
        # DN->SI->PI chain: propagate SI->PI transfer-rate + valuation too, so a
        # PI receiving stock directly (update_stock, no PR) tracks the finalised
        # DN source cost. Without this, a DN repost leaves the PI's
        # bns_transfer_rate at the value captured when the PI was created, and
        # the difference strands in Stock-in-Transit (company-level inflation).
        for pi_name in _get_submitted_pis_for_si(si_name):
            updated = _sync_pi_item_transfer_rate_from_si(si_name, pi_name=pi_name)
            mirrored = _mirror_pi_item_valuation_from_transfer_rate(pi_name)
            total_updated += updated
            total_mirrored += mirrored
            if updated or mirrored:
                affected_pis.add(pi_name)

    triggered_count = 0
    for pr_name in sorted(affected_prs):
        if _trigger_pr_repost_for_transfer_rate(pr_name, source_repost_name=doc.name):
            triggered_count += 1
    for pi_name in sorted(affected_pis):
        if _trigger_pi_repost_for_transfer_rate(pi_name, source_repost_name=doc.name):
            triggered_count += 1

    if total_updated or total_mirrored or triggered_count:
        logger.info(
            "Repost %s: DN->SI incoming sync=%s (%s SI docs), transfer-rate sync=%s, valuation mirror=%s, PR repost triggered=%s for %s Delivery Notes and %s PRs",
            doc.name,
            si_incoming_sync_count,
            len(impacted_sis_from_dn),
            total_updated,
            total_mirrored,
            triggered_count,
            len(dn_names),
            len(affected_prs),
        )

    frappe.cache().set_value(cache_key, 1, expires_in_sec=_BNS_REPOST_CACHE_TTL_SEC)


def refresh_si_transfer_rate_after_repost(doc, method: Optional[str] = None) -> None:
    """Refresh PI/PR item transfer-rate after SI repost completion (SI->PI/SI->PR)."""
    if doc.doctype != "Repost Item Valuation":
        return
    if doc.docstatus != 1 or doc.status != "Completed":
        return

    _apply_bns_transfer_rate_stock_ledger_patch()

    cache_key = f"bns_transfer_rate_si_repost_done::{doc.name}"
    if frappe.cache().get_value(cache_key):
        return

    si_names, source_counts = _resolve_impacted_vouchers_for_repost(doc, "Sales Invoice")

    if not si_names:
        logger.info(
            "Repost %s: no Sales Invoice sources resolved (sources=%s)",
            doc.name,
            source_counts,
        )
        frappe.cache().set_value(cache_key, 1, expires_in_sec=_BNS_REPOST_CACHE_TTL_SEC)
        return

    logger.info(
        "Repost %s: resolved Sales Invoice sources=%s (count=%s)",
        doc.name,
        source_counts,
        len(si_names),
    )

    pi_total_updated = 0
    pi_total_mirrored = 0
    pi_triggered_count = 0
    pr_total_updated = 0
    pr_total_mirrored = 0
    affected_prs = set()

    for si_name in si_names:
        for pi_name in _get_submitted_pis_for_si(si_name):
            updated = _sync_pi_item_transfer_rate_from_si(si_name, pi_name=pi_name)
            mirrored = _mirror_pi_item_valuation_from_transfer_rate(pi_name)
            pi_total_updated += updated
            pi_total_mirrored += mirrored
            # Repost PI immediately when transfer-rate/valuation mirror changes so SLE is corrected right away.
            if updated or mirrored:
                if _trigger_pi_repost_for_transfer_rate(pi_name, source_repost_name=doc.name):
                    pi_triggered_count += 1

        for pr_name in _get_submitted_prs_for_si(si_name):
            updated = _sync_pr_item_transfer_rate_from_si(si_name, pr_name=pr_name)
            mirrored = _mirror_pr_item_valuation_from_transfer_rate(pr_name)
            pr_total_updated += updated
            pr_total_mirrored += mirrored
            if updated or mirrored:
                affected_prs.add(pr_name)

    pr_triggered_count = 0
    for pr_name in sorted(affected_prs):
        if _trigger_pr_repost_for_transfer_rate(pr_name, source_repost_name=doc.name):
            pr_triggered_count += 1

    if (
        pi_total_updated
        or pi_total_mirrored
        or pr_total_updated
        or pr_total_mirrored
        or pi_triggered_count
        or pr_triggered_count
    ):
        logger.info(
            "Repost %s: SI transfer-rate PI(sync=%s mirror=%s repost=%s) PR(sync=%s mirror=%s repost=%s) across %s SI docs",
            doc.name,
            pi_total_updated,
            pi_total_mirrored,
            pi_triggered_count,
            pr_total_updated,
            pr_total_mirrored,
            pr_triggered_count,
            len(si_names),
        )

    frappe.cache().set_value(cache_key, 1, expires_in_sec=_BNS_REPOST_CACHE_TTL_SEC)


def _is_bns_internal_purchase_invoice_from_si(doc) -> bool:
    """Return True when submitted PI belongs to BNS internal SI->PI/SI->PR flow.

    Delegates to is_bns_internal_supplier for direct flag check, then falls back
    to _resolve_si_name_for_internal_pi (header ref, bill_no, PR chain).
    """
    if not doc or doc.doctype != "Purchase Invoice" or doc.docstatus != 1:
        return False

    if is_bns_internal_supplier(doc):
        return True

    return bool(_resolve_si_name_for_internal_pi(doc))


def _reassert_sales_invoice_bns_internal_status(si_name: str) -> bool:
    """Re-apply BNS internal status for SI after ERPNext repost status recomputation."""
    if not si_name or not frappe.db.exists("Sales Invoice", si_name):
        return False

    si = frappe.get_doc("Sales Invoice", si_name)
    if not _should_update_sales_invoice_status(si):
        return False
    if si.status == "BNS Internally Transferred":
        return False

    si.db_set("status", "BNS Internally Transferred", update_modified=False)
    return True


def _reassert_purchase_invoice_bns_internal_status(pi_name: str) -> bool:
    """Re-apply BNS internal status for PI after ERPNext repost status recomputation."""
    if not pi_name or not frappe.db.exists("Purchase Invoice", pi_name):
        return False

    pi = frappe.get_doc("Purchase Invoice", pi_name)
    if not _is_bns_internal_purchase_invoice_from_si(pi):
        return False

    changed = False
    if not pi.get("is_bns_internal_supplier"):
        pi.db_set("is_bns_internal_supplier", 1, update_modified=False)
        changed = True
    if pi.status != "BNS Internally Transferred":
        pi.db_set("status", "BNS Internally Transferred", update_modified=False)
        changed = True

    return changed


def refresh_bns_internal_status_after_repost(doc, method: Optional[str] = None) -> None:
    """
    Re-assert BNS internal status after repost completion.

    ERPNext repost flow recomputes outstanding and runs set_status(), which can set
    SI/PI status to Unpaid/Overdue because core status logic does not know BNS flags.
    """
    if doc.doctype != "Repost Item Valuation":
        return
    if doc.docstatus != 1 or doc.status != "Completed":
        return

    cache_key = f"bns_internal_status_repost_done::{doc.name}"
    if frappe.cache().get_value(cache_key):
        return

    si_names, si_sources = _resolve_impacted_vouchers_for_repost(doc, "Sales Invoice")
    pi_names, pi_sources = _resolve_impacted_vouchers_for_repost(doc, "Purchase Invoice")

    linked_pi_names: Set[str] = set()
    for si_name in si_names:
        linked_pi_names.update(_get_submitted_pis_for_si(si_name))

    all_pi_names = set(pi_names) | linked_pi_names

    si_updated = sum(1 for si_name in sorted(si_names) if _reassert_sales_invoice_bns_internal_status(si_name))
    pi_updated = sum(1 for pi_name in sorted(all_pi_names) if _reassert_purchase_invoice_bns_internal_status(pi_name))

    if si_updated or pi_updated:
        logger.info(
            "Repost %s: reasserted BNS internal status SI=%s PI=%s (si_sources=%s pi_sources=%s)",
            doc.name,
            si_updated,
            pi_updated,
            si_sources,
            pi_sources,
        )

    frappe.cache().set_value(cache_key, 1, expires_in_sec=_BNS_REPOST_CACHE_TTL_SEC)


# Temporarily disabled unused helpers (kept commented for rollback safety).
# def _calculate_per_billed(doc) -> int:
#     """Calculate the per_billed value based on GSTIN comparison."""
#     per_billed = 100
#     billing_address_gstin = getattr(doc, "billing_address_gstin", None)
#     company_gstin = getattr(doc, "company_gstin", None)
#
#     if billing_address_gstin is not None and company_gstin is not None:
#         if billing_address_gstin != company_gstin:
#             per_billed = 0
#
#     return per_billed
#
#
# def _update_document_status(doc, doctype: str, per_billed: int) -> None:
#     """Update document status and per_billed value."""
#     update_fields = {"status": "BNS Internally Transferred"}
#
#     # Only set per_billed for doctypes that have this field (Delivery Note, Purchase Receipt)
#     if doctype in ["Delivery Note", "Purchase Receipt"]:
#         update_fields["per_billed"] = per_billed
#
#     frappe.db.set_value(doctype, doc.name, update_fields)
#     frappe.clear_cache(doctype=doctype)


@frappe.whitelist()
def make_bns_internal_purchase_invoice(source_name: str, target_doc: Optional[Dict] = None) -> Dict:
    """
    Create a Purchase Invoice from a Sales Invoice for internal customers when GST differs.
    
    Args:
        source_name (str): Name of the source Sales Invoice
        target_doc (Optional[Dict]): Target document for mapping
        
    Returns:
        Dict: Mapped Purchase Invoice document
        
    Raises:
        BNSValidationError: If validation fails
        BNSInternalTransferError: If internal transfer setup fails
    """
    _bns_require_doctype_write("Purchase Invoice")
    try:
        si = frappe.get_doc("Sales Invoice", source_name, for_update=True)

        if not is_after_internal_transfer_cutoff(si.get("posting_date")):
            frappe.throw(
                _("Cannot create internal Purchase Invoice: source Sales Invoice {0} is before the Internal Transfer Cutoff.").format(source_name),
                title=_("Cutoff Date Restriction"),
            )

        _validate_internal_sales_invoice(si)

        existing_pi = _get_existing_pi_for_source(si.name)
        if existing_pi:
            frappe.throw(
                _(
                    "A Purchase Invoice ({0}) already exists for this Sales Invoice in {1} state. You cannot create another one."
                ).format(existing_pi.get("name"), _docstatus_label(existing_pi.get("docstatus"))),
                title=_("Cannot Create Purchase Invoice"),
            )

        # Block PI creation when PR already exists from this SI (SI->PR flow takes precedence)
        existing_pr = _get_existing_pr_for_source(si.name)
        if existing_pr:
            frappe.throw(
                _(
                    "A Purchase Receipt ({0}) already exists for this Sales Invoice in {1} state. Purchase Invoice cannot be created when a Purchase Receipt exists."
                ).format(existing_pr.get("name"), _docstatus_label(existing_pr.get("docstatus"))),
                title=_("Cannot Create Purchase Invoice")
            )
        
        # Get representing company
        represents_company = _get_representing_company_from_customer(si.customer)
        
        # Validate inter-company party
        validate_inter_company_party("Purchase Invoice", si.customer, represents_company)
        
        # Create mapped document
        doclist = get_mapped_doc(
            "Sales Invoice",
            source_name,
            _get_sales_invoice_mapping(),
            target_doc,
            _set_missing_values_pi,
        )

        _enforce_one_to_one_item_and_amount_parity(
            source_doc=si,
            target_doc=doclist,
            source_link_field="sales_invoice_item",
            source_item_filter=lambda d: flt(d.get("qty") or 0) != 0,
            source_label="Sales Invoice",
            target_label="Purchase Invoice",
        )
        
        # Validate quantities
        validate_internal_transfer_qty(doclist)

        logger.info(f"Successfully created internal Purchase Invoice from Sales Invoice {source_name}")
        return doclist
        
    except Exception as e:
        logger.error(f"Error creating internal Purchase Invoice: {str(e)}")
        raise


def _validate_internal_sales_invoice(si) -> None:
    """Validate that the sales invoice is for an internal customer with different GST."""
    # Check if customer is BNS internal (only check is_bns_internal_customer)
    is_bns_internal = si.get("is_bns_internal_customer") or False
    if not is_bns_internal:
        # Check customer's is_bns_internal_customer field
        customer_internal = frappe.db.get_value("Customer", si.customer, "is_bns_internal_customer")
        if not customer_internal:
            raise BNSValidationError(_("Sales Invoice is not for a BNS internal customer"))
    
    # Validate GST mismatch condition
    billing_address_gstin = getattr(si, 'billing_address_gstin', None)
    company_gstin = getattr(si, 'company_gstin', None)
    
    if billing_address_gstin is None or company_gstin is None:
        raise BNSValidationError(_("GSTIN information is missing. Cannot create internal Purchase Invoice."))
    
    if billing_address_gstin == company_gstin:
        raise BNSValidationError(_("GSTINs are the same. Use Delivery Note/Purchase Receipt flow instead."))


def _get_representing_company_from_customer(customer: str) -> str:
    """Get the company that the customer represents."""
    represents_company = frappe.db.get_value("Customer", customer, "bns_represents_company")
    if not represents_company:
        raise BNSValidationError(_("No company is assigned to the internal customer"))
    return represents_company


def _get_sales_invoice_mapping() -> Dict[str, Any]:
    """Get the mapping configuration for Sales Invoice to Purchase Invoice."""
    mapping = {
        "Sales Invoice": {
            "doctype": "Purchase Invoice",
            "field_map": {},
            "field_no_map": [
                "set_warehouse", "cost_center", "project", "location", "bill_no", "bill_date",
                "dispatch_address", "dispatch_address_name", "dispatch_address_display", 
                "dispatch_address_template", "shipping_address_template"
            ],
            "validation": {"docstatus": ["=", 1]},
            "postprocess": _update_details_pi,
        },
        "Sales Invoice Item": {
            "doctype": "Purchase Invoice Item",
            "field_map": {
                "name": "sales_invoice_item",
            },
            # serial_no, batch_no, serial_and_batch_bundle are handled in
            # _update_item_pi() via _duplicate_serial_and_batch_bundle().
            "field_no_map": ["expense_account", "cost_center", "project", "location",
                             "serial_no", "batch_no", "serial_and_batch_bundle"],
            "condition": lambda item: flt(item.qty or 0) != 0,
            "postprocess": _update_item_pi,
        },
    }

    return mapping


def _set_missing_values_pi(source, target) -> None:
    """Set missing values for the target Purchase Invoice."""
    target.run_method("set_missing_values")
    
    # Get received items to track partial receipts
    received_items = get_received_items(source.name, "Purchase Invoice", "sales_invoice_item")
    
    # Strict one-to-one mode: do not allow partial PI generation.
    if _has_any_positive_received_qty(received_items):
        frappe.throw(
            _("Strict one-to-one mode: Purchase Invoice already exists for this Sales Invoice. Partial creation is not allowed."),
            title=_("Cannot Create Purchase Invoice"),
        )
    
    # Clear document level warehouses and accounting dimensions
    _clear_document_level_fields_pi(target)


def _clear_document_level_fields_pi(target) -> None:
    """Clear warehouse and accounting dimension fields at document level."""
    target.set_warehouse = None
    target.cost_center = None
    
    # Clear optional fields if they exist
    for field in ['location', 'project']:
        if hasattr(target, field):
            setattr(target, field, None)


def _update_details_pi(source_doc, target_doc, source_parent) -> None:
    """
    Update details for the Purchase Invoice from Sales Invoice.
    
    TRANSFER UNDER DIFFERENT GSTIN:
    - is_bns_internal_supplier = 1
    - supplier_invoice_number (bill_no) = SI name
    """
    represents_company = _get_representing_company_from_customer(source_doc.customer)
    target_doc.company = represents_company

    supplier = _find_internal_supplier(represents_company)
    target_doc.supplier = supplier

    target_doc.buying_price_list = source_doc.selling_price_list
    target_doc.bns_inter_company_reference = source_doc.name
    target_doc.is_bns_internal_supplier = 1
    target_doc.bill_no = source_doc.name

    if cint(source_doc.get("is_return")):
        target_doc.is_return = 1
        original_pi = _find_return_against_pi(source_doc.get("return_against"))
        if original_pi:
            target_doc.return_against = original_pi

    if source_parent is not None:
        _update_sales_invoice_reference(source_doc.name, target_doc.name)

    _update_addresses_pi(target_doc, source_doc)
    _update_taxes_pi(target_doc)


def _find_return_against_pi(original_si_name: Optional[str]) -> Optional[str]:
    """
    Find the Purchase Invoice created from the original Sales Invoice
    so it can be used as return_against for the debit note.

    Args:
        original_si_name: Name of the original SI that the credit note returns against.

    Returns:
        PI name if found, else None.
    """
    if not original_si_name:
        return None
    pi_name = frappe.db.get_value(
        "Purchase Invoice",
        {"bns_inter_company_reference": original_si_name, "docstatus": 1, "is_return": 0},
        "name",
    )
    return pi_name


def _update_addresses_pi(target_doc, source_doc) -> None:
    """Update addresses for internal transfer Purchase Invoice."""
    # Company address becomes supplier address
    update_address(target_doc, "supplier_address", "address_display", source_doc.company_address)
    # Customer address becomes billing address
    update_address(target_doc, "billing_address", "billing_address_display", source_doc.customer_address)
    # Shipping address = Dispatch address from source (inverse)
    if source_doc.dispatch_address_name:
        update_address(target_doc, "shipping_address", "shipping_address_display", source_doc.dispatch_address_name)
    else:
        # Clear shipping address if not in source document
        target_doc.shipping_address = None
        target_doc.shipping_address_name = None
        target_doc.shipping_address_display = None
    # Dispatch address = Shipping address from source (inverse)
    if source_doc.shipping_address_name:
        update_address(target_doc, "dispatch_address", "dispatch_address_display", source_doc.shipping_address_name)
    else:
        # Clear dispatch address if not in source document
        target_doc.dispatch_address = None
        target_doc.dispatch_address_name = None
        target_doc.dispatch_address_display = None
    # Clear templates for BNS internal transfers
    target_doc.dispatch_address_template = None
    target_doc.shipping_address_template = None


def _update_taxes_pi(target_doc) -> None:
    """Update taxes for the purchase invoice."""
    # Recalculate taxes based on supplier and addresses
    update_taxes(
        target_doc,
        party=target_doc.supplier,
        party_type="Supplier",
        company=target_doc.company,
        doctype=target_doc.doctype,
        party_address=target_doc.supplier_address,
        company_address=target_doc.shipping_address,
    )


def _update_item_pi(source, target, source_parent) -> None:
    """Update item details for the purchase invoice item."""
    # Sales Invoice Item doesn't have returned_qty or received_qty fields
    # Use qty directly
    source_qty = flt(source.qty or 0)
    target.qty = source_qty
    
    # Calculate stock_qty similarly
    source_stock_qty = flt(source.stock_qty if hasattr(source, 'stock_qty') else source_qty)
    target.stock_qty = source_stock_qty
    
    # Map net_rate and base_net_rate from source (taxable rate)
    if source.get("net_rate"):
        target.net_rate = flt(source.net_rate)
    if source.get("base_net_rate"):
        target.base_net_rate = flt(source.base_net_rate)
    
    # For internal SI->PI stock flow, use SI item costing mirror as transfer-rate.
    if getattr(target, "meta", None) and target.meta.has_field("bns_transfer_rate"):
        target.bns_transfer_rate = _get_si_item_transfer_rate(source)

    target_wh = target.warehouse

    # Clear accounting fields to let system auto-populate
    _clear_item_level_fields_pi(target)

    _duplicate_serial_and_batch_bundle(
        source, target,
        target_warehouse=target_wh,
        transaction_type="Inward",
    )


def _clear_item_level_fields_pi(target) -> None:
    """Clear accounting and warehouse fields at item level."""
    # Clear accounting fields
    target.expense_account = None
    target.cost_center = None
    
    # Clear warehouse fields
    target.warehouse = None
    
    # Clear other accounting dimensions
    for field in ['location', 'project']:
        if hasattr(target, field):
            setattr(target, field, None)


def _update_sales_invoice_reference(si_name: str, pi_name: str) -> None:
    """Update sales invoice with purchase invoice reference."""
    # Do NOT update status here - it's handled by on_submit hook
    frappe.db.set_value("Sales Invoice", si_name, {
        "bns_inter_company_reference": pi_name
    })


@frappe.whitelist()
def make_bns_internal_purchase_receipt_from_si(source_name: str, target_doc: Optional[Dict] = None) -> Dict:
    """
    Create a Purchase Receipt from a Sales Invoice for internal customers when update_stock is enabled.
    
    Args:
        source_name (str): Name of the source Sales Invoice
        target_doc (Optional[Dict]): Target document for mapping
        
    Returns:
        Dict: Mapped Purchase Receipt document
        
    Raises:
        BNSValidationError: If validation fails
        BNSInternalTransferError: If internal transfer setup fails
    """
    _bns_require_doctype_write("Purchase Receipt")
    try:
        si = frappe.get_doc("Sales Invoice", source_name)

        if not is_after_internal_transfer_cutoff(si.get("posting_date")):
            frappe.throw(
                _("Cannot create internal Purchase Receipt: source Sales Invoice {0} is before the Internal Transfer Cutoff.").format(source_name),
                title=_("Cutoff Date Restriction"),
            )

        has_dn_reference = False
        if si.items:
            has_dn_reference = any(item.get("delivery_note") for item in si.items if item.get("delivery_note"))

        if not has_dn_reference and not si.get("update_stock"):
            raise BNSValidationError(_("Sales Invoice must have 'Update Stock' enabled to create Purchase Receipt, or must be created from a Delivery Note"))

        _validate_internal_sales_invoice(si)

        existing_pr = _get_existing_pr_for_source(si.name)
        if existing_pr:
            frappe.throw(
                _(
                    "A Purchase Receipt ({0}) already exists for this Sales Invoice in {1} state. You cannot create another one."
                ).format(existing_pr.get("name"), _docstatus_label(existing_pr.get("docstatus"))),
                title=_("Cannot Create Purchase Receipt"),
            )
        
        # Check if Purchase Invoice already exists for this Sales Invoice
        # If PI exists, PR should not be created (PI is for non-stock items, PR is for stock items)
        existing_pi = _get_existing_pi_for_source(si.name)
        if existing_pi:
            frappe.throw(
                _(
                    "A Purchase Invoice ({0}) already exists for this Sales Invoice in {1} state. Purchase Receipt cannot be created when a Purchase Invoice exists."
                ).format(existing_pi.get("name"), _docstatus_label(existing_pi.get("docstatus"))),
                title=_("Cannot Create Purchase Receipt")
            )

        # Get representing company
        represents_company = _get_representing_company_from_customer(si.customer)

        # Validate inter-company party
        validate_inter_company_party("Purchase Receipt", si.customer, represents_company)

        # Create mapped document
        doclist = get_mapped_doc(
            "Sales Invoice",
            source_name,
            _get_sales_invoice_to_pr_mapping(),
            target_doc,
            _set_missing_values_pr_from_si,
        )

        _enforce_one_to_one_item_and_amount_parity(
            source_doc=si,
            target_doc=doclist,
            source_link_field="sales_invoice_item",
            source_item_filter=lambda d: flt(d.get("qty") or 0) > 0,
            source_label="Sales Invoice",
            target_label="Purchase Receipt",
        )
        
        # Validate quantities (using supplier_delivery_note as reference)
        # Note: For SI->PR, we validate against SI items
        if doclist.supplier_delivery_note == si.name:
            validate_internal_transfer_qty(doclist)
        
        # Update sales invoice with PR reference
        _update_sales_invoice_pr_reference(si.name, doclist.name)
        
        logger.info(f"Successfully created internal Purchase Receipt from Sales Invoice {source_name}")
        return doclist
        
    except Exception as e:
        logger.error(f"Error creating internal Purchase Receipt from Sales Invoice: {str(e)}")
        raise


def _get_sales_invoice_to_pr_mapping() -> Dict[str, Any]:
    """Get the mapping configuration for Sales Invoice to Purchase Receipt."""
    return {
        "Sales Invoice": {
            "doctype": "Purchase Receipt",
            "field_map": {},
            "field_no_map": [
                "set_warehouse", "rejected_warehouse", "cost_center", "project", "location",
                "dispatch_address", "dispatch_address_name", "dispatch_address_display", 
                "dispatch_address_template", "shipping_address_template"
            ],
            "validation": {"docstatus": ["=", 1]},
            "postprocess": _update_details_pr_from_si,
        },
        "Sales Invoice Item": {
            "doctype": "Purchase Receipt Item",
            "field_map": {
                "name": "sales_invoice_item",
                "warehouse": "from_warehouse",
            },
            # serial_no, batch_no, serial_and_batch_bundle are handled in
            # _update_item_pr_from_si() via _duplicate_serial_and_batch_bundle().
            "field_no_map": ["warehouse", "rejected_warehouse", "expense_account", "cost_center", "project", "location",
                             "serial_no", "batch_no", "serial_and_batch_bundle"],
            "condition": lambda item: flt(item.qty or 0) > 0,
            "postprocess": _update_item_pr_from_si,
        },
    }


def _set_missing_values_pr_from_si(source, target) -> None:
    """Set missing values for the target Purchase Receipt from Sales Invoice."""
    target.run_method("set_missing_values")
    
    # Get received items to track partial receipts (using supplier_delivery_note as reference)
    # For SI->PR, we track via supplier_delivery_note field; requires sales_invoice_item on Purchase Receipt Item
    received_items = {}
    pr_item_meta = frappe.get_meta("Purchase Receipt Item")
    if source.name and pr_item_meta.has_field("sales_invoice_item"):
        pr_list = frappe.get_all(
            "Purchase Receipt",
            filters={"supplier_delivery_note": source.name, "docstatus": 1},
            fields=["name"]
        )
        if pr_list:
            pr_names = [pr.name for pr in pr_list]
            pr_items = frappe.get_all(
                "Purchase Receipt Item",
                filters={"parent": ("in", pr_names)},
                fields=["sales_invoice_item", "item_code", "qty"]
            )
            for item in pr_items:
                key = (item.get("sales_invoice_item"), item.item_code)
                received_items[key] = received_items.get(key, 0) + flt(item.qty)
    
    # Strict one-to-one mode: do not allow partial PR generation from SI.
    if _has_any_positive_received_qty(received_items):
        frappe.throw(
            _("Strict one-to-one mode: Purchase Receipt already exists for this Sales Invoice. Partial creation is not allowed."),
            title=_("Cannot Create Purchase Receipt"),
        )
    
    # Clear document level warehouses and accounting dimensions
    _clear_document_level_fields(target)


def _update_details_pr_from_si(source_doc, target_doc, source_parent) -> None:
    """
    Update details for the Purchase Receipt from Sales Invoice.
    
    TRANSFER UNDER DIFFERENT GSTIN:
    - is_bns_internal_customer = 0
    - status = "To Bill" (set on submit)
    - supplier_delivery_note = SI name
    """
    if source_parent is None:
        represents_company = _get_representing_company_from_customer(source_doc.customer)
        target_doc.company = represents_company
        
        supplier = _find_internal_supplier(represents_company)
        target_doc.supplier = supplier
        
        target_doc.buying_price_list = source_doc.selling_price_list
        # Do NOT set is_internal_supplier - only set bns_inter_company_reference for BNS internal transfers
        target_doc.bns_inter_company_reference = source_doc.name
        
        # Set supplier_delivery_note = SI name (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.supplier_delivery_note = source_doc.name

        # Set is_bns_internal_customer = 0 (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.is_bns_internal_customer = 0
        
        _update_addresses(target_doc, source_doc)
        _update_taxes(target_doc)
    else:
        represents_company = _get_representing_company_from_customer(source_doc.customer)
        target_doc.company = represents_company
        supplier = _find_internal_supplier(represents_company)
        target_doc.supplier = supplier
        
        target_doc.buying_price_list = source_doc.selling_price_list
        # Do NOT set is_internal_supplier - only set bns_inter_company_reference for BNS internal transfers
        target_doc.bns_inter_company_reference = source_doc.name
        
        # Set supplier_delivery_note = SI name (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.supplier_delivery_note = source_doc.name

        # Set is_bns_internal_customer = 0 (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.is_bns_internal_customer = 0
        
        _update_sales_invoice_pr_reference(source_doc.name, target_doc.name)
        _update_addresses(target_doc, source_doc)
        _update_taxes(target_doc)


def _update_item_pr_from_si(source, target, source_parent) -> None:
    """Update item details for the purchase receipt item from sales invoice item."""
    # Sales Invoice Item doesn't have returned_qty or received_qty fields
    # Use qty directly
    source_qty = flt(source.qty or 0)
    target.qty = source_qty
    
    # Calculate stock_qty similarly
    source_stock_qty = flt(source.stock_qty if hasattr(source, 'stock_qty') else source_qty)
    target.stock_qty = source_stock_qty
    
    # Map net_rate and base_net_rate from source (taxable rate)
    if source.get("net_rate"):
        target.net_rate = flt(source.net_rate)
    if source.get("base_net_rate"):
        target.base_net_rate = flt(source.base_net_rate)

    # For internal SI->PR flow, keep transfer-rate separate from billing/net rate.
    if getattr(target, "meta", None) and target.meta.has_field("bns_transfer_rate"):
        target.bns_transfer_rate = _get_si_item_transfer_rate(source)

    target.received_qty = 0

    target_wh = target.warehouse or target.rejected_warehouse

    _clear_item_level_fields(target)

    _duplicate_serial_and_batch_bundle(
        source, target,
        target_warehouse=target_wh,
        transaction_type="Inward",
    )


def _update_sales_invoice_pr_reference(si_name: str, pr_name: str) -> None:
    """
    Update Sales Invoice with Purchase Receipt reference for record connections.

    Sets bns_purchase_receipt_reference so SI shows PR in Connections and vice versa.
    """
    if frappe.db.exists("Sales Invoice", si_name):
        si = frappe.get_doc("Sales Invoice", si_name)
        if si.meta.has_field("bns_purchase_receipt_reference"):
            si.db_set("bns_purchase_receipt_reference", pr_name, update_modified=False)
        frappe.clear_cache(doctype="Sales Invoice")


def update_sales_invoice_status_for_bns_internal(doc, method: Optional[str] = None) -> None:
    """
    Update the status of a Sales Invoice to "BNS Internally Transferred" 
    when submitted for a BNS internal customer with different GST.

    Args:
        doc: The Sales Invoice document
        method (Optional[str]): The method being called
    """
    if not is_after_internal_transfer_cutoff(doc.get("posting_date")):
        return

    if doc.status == "BNS Internally Transferred":
        return

    if not doc.get("is_bns_internal_customer") and doc.customer:
        customer_internal = frappe.db.get_value("Customer", doc.customer, "is_bns_internal_customer")
        if customer_internal:
            doc.set("is_bns_internal_customer", customer_internal)
    
    if not _should_update_sales_invoice_status(doc):
        return

    try:
        # Update status immediately on the document object so it shows without refresh
        doc.status = "BNS Internally Transferred"
        # Also update in database using db_set
        doc.db_set("status", "BNS Internally Transferred", update_modified=False)
        
        # Set bidirectional bns_inter_company_reference
        pi_name = None
        
        # Check if SI already has bns_inter_company_reference pointing to a PI
        if doc.bns_inter_company_reference and frappe.db.exists("Purchase Invoice", doc.bns_inter_company_reference):
            pi_name = doc.bns_inter_company_reference
        # Check if a PI exists with bill_no matching this SI name
        elif frappe.db.exists("Purchase Invoice", {"bill_no": doc.name, "docstatus": 1}):
            pi_name = frappe.db.get_value("Purchase Invoice", {"bill_no": doc.name, "docstatus": 1}, "name")
            # Set SI's bns_inter_company_reference if not already set
            if not doc.bns_inter_company_reference:
                doc.db_set("bns_inter_company_reference", pi_name, update_modified=False)
        
        # Update PI's bns_inter_company_reference to point back to SI
        if pi_name:
            pi = frappe.get_doc("Purchase Invoice", pi_name)
            if not pi.get("bns_inter_company_reference") or pi.bns_inter_company_reference != doc.name:
                pi.db_set("bns_inter_company_reference", doc.name, update_modified=False)
                # Also ensure PI status is updated if not already
                if pi.status != "BNS Internally Transferred":
                    pi.db_set("status", "BNS Internally Transferred", update_modified=False)
                # Ensure PI's is_bns_internal_supplier flag is set
                if not pi.get("is_bns_internal_supplier"):
                    pi.db_set("is_bns_internal_supplier", 1, update_modified=False)
                frappe.clear_cache(doctype="Purchase Invoice")
                logger.info(f"Updated Purchase Invoice {pi_name} bns_inter_company_reference to {doc.name}")
        
        frappe.clear_cache(doctype="Sales Invoice")
        logger.info(f"Updated Sales Invoice {doc.name} status to BNS Internally Transferred")
        
    except Exception as e:
        logger.error(f"Error updating Sales Invoice status: {str(e)}")
        raise


def update_purchase_invoice_status_for_bns_internal(doc, method: Optional[str] = None) -> None:
    """Set PI status to 'BNS Internally Transferred' on submit for SI-backed internal PIs.

    Uses the canonical _is_bns_internal_purchase_invoice_from_si detection
    and _resolve_si_name_for_internal_pi resolver so the same rule set governs
    submit-time status assignment and post-repost reassertion.

    Args:
        doc: The Purchase Invoice document.
        method: Hook method name (unused).
    """
    if doc.docstatus != 1:
        return

    if doc.status == "BNS Internally Transferred":
        return

    if not _is_bns_internal_purchase_invoice_from_si(doc):
        return

    effective_date = _resolve_source_posting_date(doc)
    if not is_after_internal_transfer_cutoff(effective_date):
        return

    try:
        if not doc.get("is_bns_internal_supplier"):
            doc.is_bns_internal_supplier = 1

        doc.status = "BNS Internally Transferred"
        doc.db_set("status", "BNS Internally Transferred", update_modified=False)
        doc.db_set("is_bns_internal_supplier", 1, update_modified=False)

        si_name = _resolve_si_name_for_internal_pi(doc)
        if si_name and not doc.get("bns_inter_company_reference"):
            doc.db_set("bns_inter_company_reference", si_name, update_modified=False)

        if si_name:
            si = frappe.get_doc("Sales Invoice", si_name)
            if not si.get("bns_inter_company_reference") or si.bns_inter_company_reference != doc.name:
                si.db_set("bns_inter_company_reference", doc.name, update_modified=False)
                if si.status != "BNS Internally Transferred":
                    si.db_set("status", "BNS Internally Transferred", update_modified=False)
                frappe.clear_cache(doctype="Sales Invoice")
                logger.info(f"Updated Sales Invoice {si_name} bns_inter_company_reference to {doc.name}")

        if si_name and is_after_accounting_rewrite_cutoff(effective_date):
            _sync_pi_item_transfer_rate_from_si(si_name, pi_name=doc.name)
            _mirror_pi_item_valuation_from_transfer_rate(doc.name)
            _trigger_pi_repost_for_transfer_rate(doc.name, source_repost_name=f"pi_submit::{doc.name}")
            _trigger_bns_internal_gl_repost(doc, source="pi_on_submit_transfer_rate_sync")

            doc.db_set("status", "BNS Internally Transferred", update_modified=False)

        frappe.clear_cache(doctype="Purchase Invoice")
        logger.info(f"Updated Purchase Invoice {doc.name} status to BNS Internally Transferred")

    except Exception as e:
        logger.error(f"Error updating Purchase Invoice status: {str(e)}")
        raise


def _should_update_sales_invoice_status(doc) -> bool:
    """Check if the Sales Invoice status should be updated for internal transfers."""
    if doc.docstatus != 1:
        return False
    
    # Check if customer is BNS internal
    if not is_bns_internal_customer(doc):
        return False

    # Check GST mismatch condition (different GST)
    billing_address_gstin = getattr(doc, 'billing_address_gstin', None)
    company_gstin = getattr(doc, 'company_gstin', None)
    
    if billing_address_gstin is None or company_gstin is None:
        return False
    
    # Only update if GST is different
    return billing_address_gstin != company_gstin


@frappe.whitelist()
def get_sales_invoice_by_bill_no(purchase_invoice: str) -> Dict:
    """
    Find Sales Invoice by bill_no (supplier_invoice_number) matching Purchase Invoice name.
    
    Args:
        purchase_invoice (str): Name of the Purchase Invoice
        
    Returns:
        Dict: Sales Invoice details if found, None otherwise
    """
    _bns_require_accounts_read()
    try:
        # Get Purchase Invoice to check bill_no
        pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
        
        # Find SI where name matches PI's bill_no (supplier_invoice_number)
        si_name = None
        if pi.bill_no:
            si_name = frappe.db.get_value("Sales Invoice", {"name": pi.bill_no, "docstatus": 1}, "name")
        
        if not si_name:
            return {"found": False}
        
        si = frappe.get_doc("Sales Invoice", si_name)
        
        # Get basic details
        return {
            "found": True,
            "name": si.name,
            "customer": si.customer,
            "posting_date": str(si.posting_date) if si.posting_date else None,
            "grand_total": si.grand_total or 0,
            "status": si.status,
            "is_bns_internal_customer": si.get("is_bns_internal_customer") or 0,
            "bns_inter_company_reference": si.get("bns_inter_company_reference") or None
        }
    except Exception as e:
        logger.error(f"Error finding Sales Invoice: {str(e)}")
        return {"found": False}


@frappe.whitelist()
def get_purchase_invoice_by_supplier_invoice(sales_invoice: str) -> Dict:
    """
    Find Purchase Invoice by supplier_invoice_number (bill_no) matching Sales Invoice name.
    
    Args:
        sales_invoice (str): Name of the Sales Invoice
        
    Returns:
        Dict: Purchase Invoice details if found, None otherwise
    """
    _bns_require_accounts_read()
    try:
        # Find PI where bill_no matches SI name
        pi_name = frappe.db.get_value("Purchase Invoice", {"bill_no": sales_invoice, "docstatus": 1}, "name")
        
        if not pi_name:
            return {"found": False}
        
        pi = frappe.get_doc("Purchase Invoice", pi_name)
        
        # Get basic details
        return {
            "found": True,
            "name": pi.name,
            "supplier": pi.supplier,
            "posting_date": str(pi.posting_date) if pi.posting_date else None,
            "grand_total": pi.grand_total or 0,
            "status": pi.status,
            "is_bns_internal_supplier": pi.get("is_bns_internal_supplier") or 0,
            "bns_inter_company_reference": pi.get("bns_inter_company_reference") or None
        }
    except Exception as e:
        logger.error(f"Error finding Purchase Invoice: {str(e)}")
        return {"found": False}


@frappe.whitelist()
def validate_si_pi_items_match(
    sales_invoice: str,
    purchase_invoice: str,
    check_all: bool = False,
    amount_tolerance: float = 0.0,
) -> Dict:
    """Validate that all Sales Invoice items and quantities match Purchase Invoice items.

    Args:
        sales_invoice: Name of the Sales Invoice.
        purchase_invoice: Name of the Purchase Invoice.
        check_all: If True, also validates taxable values, totals, and taxes.
        amount_tolerance: Absolute amount below which taxable value, grand total,
            and tax differences are ignored. Does not affect item/qty checks.

    Returns:
        Validation result with match status and details.
    """
    _bns_require_accounts_read()
    amount_tolerance = flt(amount_tolerance or 0)
    try:
        si = frappe.get_doc("Sales Invoice", sales_invoice)
        pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
        
        # Get SI items with taxable values
        si_items = {}
        for item in si.items:
            item_code = item.item_code
            qty = flt(item.qty or 0)
            stock_qty = flt(item.stock_qty or qty)
            net_amount = flt(item.net_amount or 0)
            base_net_amount = flt(item.base_net_amount or 0)
            
            if item_code not in si_items:
                si_items[item_code] = {
                    "qty": 0, 
                    "stock_qty": 0,
                    "net_amount": 0,
                    "base_net_amount": 0
                }
            si_items[item_code]["qty"] += qty
            si_items[item_code]["stock_qty"] += stock_qty
            si_items[item_code]["net_amount"] += net_amount
            si_items[item_code]["base_net_amount"] += base_net_amount
        
        # Get PI items with taxable values
        pi_items = {}
        for item in pi.items:
            item_code = item.item_code
            qty = flt(item.qty or 0)
            stock_qty = flt(item.stock_qty or qty)
            net_amount = flt(item.net_amount or 0)
            base_net_amount = flt(item.base_net_amount or 0)
            
            if item_code not in pi_items:
                pi_items[item_code] = {
                    "qty": 0, 
                    "stock_qty": 0,
                    "net_amount": 0,
                    "base_net_amount": 0
                }
            pi_items[item_code]["qty"] += qty
            pi_items[item_code]["stock_qty"] += stock_qty
            pi_items[item_code]["net_amount"] += net_amount
            pi_items[item_code]["base_net_amount"] += base_net_amount
        
        # Check if all SI items exist in PI and quantities match
        missing_items = []
        qty_mismatches = []
        taxable_value_mismatches = []
        
        for item_code, si_data in si_items.items():
            if item_code not in pi_items:
                missing_items.append({
                    "item_code": item_code,
                    "si_qty": si_data["qty"],
                    "pi_qty": 0
                })
            else:
                pi_data = pi_items[item_code]
                # Check stock_qty first, then qty (no tolerance: rounded comparison)
                if si_data["stock_qty"] > 0:
                    if round(flt(si_data["stock_qty"]), 6) != round(flt(pi_data["stock_qty"]), 6):
                        qty_mismatches.append({
                            "item_code": item_code,
                            "si_qty": si_data["stock_qty"],
                            "pi_qty": pi_data["stock_qty"]
                        })
                elif round(flt(si_data["qty"]), 6) != round(flt(pi_data["qty"]), 6):
                    qty_mismatches.append({
                        "item_code": item_code,
                        "si_qty": si_data["qty"],
                        "pi_qty": pi_data["qty"]
                    })
                
                if check_all:
                    si_taxable_value = si_data["base_net_amount"] if si_data["base_net_amount"] > 0 else si_data["net_amount"]
                    pi_taxable_value = pi_data["base_net_amount"] if pi_data["base_net_amount"] > 0 else pi_data["net_amount"]
                    diff = abs(round(flt(si_taxable_value), 2) - round(flt(pi_taxable_value), 2))
                    if diff > amount_tolerance:
                        taxable_value_mismatches.append({
                            "item_code": item_code,
                            "si_taxable_value": si_taxable_value,
                            "pi_taxable_value": pi_taxable_value
                        })
        
        # Check if PI has extra items (not in SI)
        extra_items = []
        for item_code, pi_data in pi_items.items():
            if item_code not in si_items:
                extra_items.append({
                    "item_code": item_code,
                    "pi_qty": pi_data["qty"]
                })
        
        # Check grand total and tax mismatches if check_all is True
        grand_total_mismatch = None
        tax_mismatch = None
        
        if check_all:
            si_grand_total = flt(si.grand_total or 0)
            pi_grand_total = flt(pi.grand_total or 0)
            gt_diff = abs(round(si_grand_total, 2) - round(pi_grand_total, 2))
            if gt_diff > amount_tolerance:
                grand_total_mismatch = {
                    "si_total": si_grand_total,
                    "pi_total": pi_grand_total,
                    "diff": si_grand_total - pi_grand_total
                }
            
            si_base_taxes = flt(si.base_total_taxes_and_charges or 0)
            if si_base_taxes == 0:
                si_base_taxes = flt(si.total_taxes_and_charges or 0)
            pi_base_taxes = flt(pi.base_total_taxes_and_charges or 0)
            if pi_base_taxes == 0:
                pi_base_taxes = flt(pi.total_taxes_and_charges or 0)

            tax_diff = abs(round(si_base_taxes, 2) - round(pi_base_taxes, 2))
            if tax_diff > amount_tolerance:
                tax_mismatch = {
                    "si_tax": si_base_taxes,
                    "pi_tax": pi_base_taxes,
                    "diff": si_base_taxes - pi_base_taxes
                }
        
        is_match = (
            len(missing_items) == 0 and 
            len(qty_mismatches) == 0 and 
            (not check_all or (
                len(taxable_value_mismatches) == 0 and 
                grand_total_mismatch is None and 
                tax_mismatch is None
            ))
        )
        
        result = {
            "match": is_match,
            "missing_items": missing_items,
            "qty_mismatches": qty_mismatches,
            "extra_items": extra_items,
            "message": _("Items and quantities match") if is_match else _("Items or quantities do not match")
        }
        
        if check_all:
            result.update({
                "taxable_value_mismatches": taxable_value_mismatches,
                "grand_total_mismatch": grand_total_mismatch,
                "tax_mismatch": tax_mismatch
            })
        
        return result
        
    except Exception as e:
        logger.error(f"Error validating SI-PI items match: {str(e)}")
        frappe.throw(_("Error validating items: {0}").format(str(e)))


def _match_and_set_item_references(si, pi) -> int:
    """
    Match SI items to PI items by item_code + qty and set sales_invoice_item on PI items.
    Uses exact qty match first, then first-available partial match.
    Returns the number of PI items updated.
    """
    si_item_map = defaultdict(list)
    for si_item in si.items:
        si_item_map[si_item.item_code].append({
            "name": si_item.name,
            "qty": flt(si_item.qty or 0),
            "stock_qty": flt(si_item.stock_qty or si_item.qty or 0),
            "remaining_qty": flt(si_item.qty or 0),
            "remaining_stock_qty": flt(si_item.stock_qty or si_item.qty or 0),
        })

    count = 0
    for pi_item in pi.items:
        item_code = pi_item.item_code
        pi_qty = flt(pi_item.qty or 0)
        pi_stock_qty = flt(pi_item.stock_qty or pi_qty)

        if item_code not in si_item_map or not si_item_map[item_code]:
            continue

        matched = False
        for si_item_data in si_item_map[item_code]:
            if si_item_data["remaining_qty"] <= 0:
                continue
            if pi_stock_qty > 0 and si_item_data["remaining_stock_qty"] > 0:
                if round(pi_stock_qty, 6) == round(si_item_data["remaining_stock_qty"], 6):
                    pi_item.db_set("sales_invoice_item", si_item_data["name"], update_modified=False)
                    si_item_data["remaining_qty"] = 0
                    si_item_data["remaining_stock_qty"] = 0
                    matched = True
                    count += 1
                    break
            elif round(pi_qty, 6) == round(si_item_data["remaining_qty"], 6):
                pi_item.db_set("sales_invoice_item", si_item_data["name"], update_modified=False)
                si_item_data["remaining_qty"] = 0
                si_item_data["remaining_stock_qty"] = 0
                matched = True
                count += 1
                break

        if not matched:
            for si_item_data in si_item_map[item_code]:
                if si_item_data["remaining_qty"] > 0:
                    pi_item.db_set("sales_invoice_item", si_item_data["name"], update_modified=False)
                    if pi_stock_qty > 0 and si_item_data["remaining_stock_qty"] > 0:
                        si_item_data["remaining_stock_qty"] -= pi_stock_qty
                    else:
                        si_item_data["remaining_qty"] -= pi_qty
                    count += 1
                    break
    return count


@frappe.whitelist()
def convert_sales_invoice_to_bns_internal(sales_invoice: str, purchase_invoice: Optional[str] = None) -> Dict:
    """
    Convert a Sales Invoice to BNS Internally Transferred status.
    
    This function:
    1. Marks Sales Invoice as BNS internal customer
    2. Updates status to "BNS Internally Transferred"
    3. If Purchase Invoice is provided, validates and links them properly
    
    Args:
        sales_invoice (str): Name of the Sales Invoice to convert
        purchase_invoice (Optional[str]): Optional Purchase Invoice name to link
        
    Returns:
        Dict: Result with success message and updated references
        
    Raises:
        BNSValidationError: If validation fails
    """
    _bns_require_doctype_write("Sales Invoice")
    try:
        # Get Sales Invoice
        si = frappe.get_doc("Sales Invoice", sales_invoice)
        
        # Validate Sales Invoice is submitted
        if si.docstatus != 1:
            raise BNSValidationError(_("Sales Invoice must be submitted before converting to BNS Internal"))
        
        # Check if customer is BNS internal
        customer_internal = frappe.db.get_value("Customer", si.customer, "is_bns_internal_customer")
        if not customer_internal:
            raise BNSValidationError(_("Customer {0} is not marked as BNS Internal Customer").format(si.customer))
        
        # Check if already fully converted (both flag and status are set)
        if si.get("is_bns_internal_customer") and si.status == "BNS Internally Transferred":
            frappe.msgprint(_("Sales Invoice is already marked as BNS Internally Transferred"))
            return {"success": True, "message": _("Already converted")}
        
        # Update Sales Invoice (even if flag is already set, ensure status is updated)
        si.db_set("is_bns_internal_customer", 1, update_modified=False)
        si.db_set("status", "BNS Internally Transferred", update_modified=False)
        
        result = {
            "success": True,
            "message": _("Sales Invoice converted to BNS Internally Transferred"),
            "sales_invoice": si.name
        }
        
        # Auto-find Purchase Invoice by bill_no if not provided
        if not purchase_invoice:
            pi_name = frappe.db.get_value("Purchase Invoice", {"bill_no": si.name, "docstatus": 1}, "name")
            if pi_name:
                purchase_invoice = pi_name
                logger.info(f"Auto-found Purchase Invoice {pi_name} for Sales Invoice {si.name} via bill_no")
        
        # If Purchase Invoice is found/provided, validate and link
        if purchase_invoice:
            _bns_require_doctype_write("Purchase Invoice")
            pi = frappe.get_doc("Purchase Invoice", purchase_invoice)

            # Validate PI is submitted
            if pi.docstatus != 1:
                raise BNSValidationError(_("Purchase Invoice {0} must be submitted before linking").format(purchase_invoice))
            
            # Validate items, quantities, rates, totals, and taxes
            amount_tolerance = flt(frappe.db.get_single_value("BNS Branch Accounting Settings", "si_pi_amount_tolerance") or 0)
            validation_result = validate_si_pi_items_match(si.name, pi.name, check_all=True, amount_tolerance=amount_tolerance)
            if not validation_result.get("match"):
                # Mismatch found — still convert (status already set above),
                # but skip linking so it surfaces in the mismatch report.
                mismatch_details = []
                for item in validation_result.get("missing_items", [])[:3]:
                    mismatch_details.append(_("Item {0}: SI has {1}, PI missing").format(item["item_code"], item["si_qty"]))
                for item in validation_result.get("qty_mismatches", [])[:3]:
                    mismatch_details.append(_("Item {0}: SI has {1}, PI has {2}").format(item["item_code"], item["si_qty"], item["pi_qty"]))
                gt = validation_result.get("grand_total_mismatch")
                if gt:
                    mismatch_details.append(_("Grand Total diff: ₹{0:.2f}").format(abs(gt["diff"])))

                warning = _("Converted to BNS Internally Transferred but PI {0} not linked (mismatch: {1}). Check Internal Transfer Mismatch report.").format(
                    pi.name, "; ".join(mismatch_details) or _("validation failed")
                )
                frappe.msgprint(warning, indicator="orange", title=_("Converted with Mismatch"))
                result["warning"] = warning
                result["purchase_invoice_found"] = pi.name
            else:
                # Validation passed — proceed to link
                # Get representing companies for validation
                si_customer_company = frappe.db.get_value("Customer", si.customer, "bns_represents_company")
                pi_supplier_company = None
                if pi.supplier:
                    pi_supplier_company = frappe.db.get_value("Supplier", pi.supplier, "bns_represents_company")
                    if not pi_supplier_company:
                        raise BNSValidationError(
                            _("Supplier {0} is missing bns_represents_company.").format(pi.supplier)
                        )

                # Validate companies match (PI supplier should represent SI's company)
                if si_customer_company and pi_supplier_company:
                    if pi_supplier_company != si_customer_company:
                        raise BNSValidationError(
                            _("Purchase Invoice supplier represents company {0}, but Sales Invoice customer represents {1}").format(
                                pi_supplier_company, si_customer_company
                            )
                        )

                # Check if PI already linked to another SI
                existing_ref = pi.get("bns_inter_company_reference")
                if existing_ref and existing_ref != si.name:
                    raise BNSValidationError(
                        _("Purchase Invoice {0} is already linked to Sales Invoice {1}").format(
                            purchase_invoice, existing_ref
                        )
                    )

                # Match SI items to PI items and set sales_invoice_item on PI items
                n_updated = _match_and_set_item_references(si, pi)

                # Update Purchase Invoice document-level fields first
                frappe.db.set_value("Purchase Invoice", pi.name, {
                    "is_bns_internal_supplier": 1,
                    "bns_inter_company_reference": si.name,
                    "status": "BNS Internally Transferred"
                }, update_modified=False)

                # Reload PI to get updated values
                pi.reload()

                # Then update Sales Invoice
                si.db_set("bns_inter_company_reference", pi.name, update_modified=False)

                # Clear cache for both documents
                frappe.clear_cache(doctype="Purchase Invoice")
                frappe.clear_cache(doctype="Sales Invoice")

                result["purchase_invoice"] = pi.name
                result["message"] = _("Sales Invoice and Purchase Invoice linked successfully")

                logger.info(f"Linked Sales Invoice {si.name} with Purchase Invoice {pi.name}, updated {n_updated} item references")
        
        frappe.clear_cache(doctype="Sales Invoice")
        
        logger.info(f"Converted Sales Invoice {si.name} to BNS Internally Transferred")
        return result
        
    except Exception as e:
        logger.error(f"Error converting Sales Invoice to BNS Internal: {str(e)}")
        frappe.throw(str(e))


@frappe.whitelist()
def convert_purchase_invoice_to_bns_internal(purchase_invoice: str, sales_invoice: Optional[str] = None) -> Dict:
    """
    Convert a Purchase Invoice to BNS Internally Transferred status.
    
    This function:
    1. Marks Purchase Invoice as BNS internal supplier
    2. Updates status to "BNS Internally Transferred"
    3. If Sales Invoice is provided, validates and links them properly
    
    Args:
        purchase_invoice (str): Name of the Purchase Invoice to convert
        sales_invoice (Optional[str]): Optional Sales Invoice name to link
        
    Returns:
        Dict: Result with success message and updated references
        
    Raises:
        BNSValidationError: If validation fails
    """
    _bns_require_doctype_write("Purchase Invoice")
    try:
        pi = frappe.get_doc("Purchase Invoice", purchase_invoice)

        if pi.docstatus != 1:
            raise BNSValidationError(_("Purchase Invoice must be submitted before converting to BNS Internal"))

        effective_date = _resolve_source_posting_date(pi)
        if not is_after_internal_transfer_cutoff(effective_date):
            frappe.throw(
                _("Cannot convert Purchase Invoice {0} to BNS Internal: source document is before the Internal Transfer Cutoff.").format(purchase_invoice),
                title=_("Cutoff Date Restriction"),
            )

        supplier_internal = frappe.db.get_value("Supplier", pi.supplier, "is_bns_internal_supplier")
        if not supplier_internal:
            raise BNSValidationError(_("Supplier {0} is not marked as BNS Internal Supplier").format(pi.supplier))
        
        # Check if already fully converted (both flag and status are set)
        if pi.get("is_bns_internal_supplier") and pi.status == "BNS Internally Transferred":
            frappe.msgprint(_("Purchase Invoice is already marked as BNS Internally Transferred"))
            return {"success": True, "message": _("Already converted")}
        
        # Update Purchase Invoice (even if flag is already set, ensure status is updated)
        pi.db_set("is_bns_internal_supplier", 1, update_modified=False)
        pi.db_set("status", "BNS Internally Transferred", update_modified=False)
        
        result = {
            "success": True,
            "message": _("Purchase Invoice converted to BNS Internally Transferred"),
            "purchase_invoice": pi.name
        }
        
        # Auto-find Sales Invoice by bill_no if not provided
        if not sales_invoice and pi.bill_no:
            si_exists = frappe.db.exists("Sales Invoice", {"name": pi.bill_no, "docstatus": 1})
            if si_exists:
                sales_invoice = pi.bill_no
                logger.info(f"Auto-found Sales Invoice {sales_invoice} for Purchase Invoice {pi.name} via bill_no")
        
        # If Sales Invoice is found/provided, validate and link
        if sales_invoice:
            _bns_require_doctype_write("Sales Invoice")
            si = frappe.get_doc("Sales Invoice", sales_invoice)

            # Validate SI is submitted
            if si.docstatus != 1:
                raise BNSValidationError(_("Sales Invoice {0} must be submitted before linking").format(sales_invoice))

            # Validate items, quantities, rates, totals, and taxes
            amount_tolerance = flt(frappe.db.get_single_value("BNS Branch Accounting Settings", "si_pi_amount_tolerance") or 0)
            validation_result = validate_si_pi_items_match(si.name, pi.name, check_all=True, amount_tolerance=amount_tolerance)
            if not validation_result.get("match"):
                # Mismatch found — still convert (status already set above),
                # but skip linking so it surfaces in the mismatch report.
                mismatch_details = []
                for item in validation_result.get("missing_items", [])[:3]:
                    mismatch_details.append(_("Item {0}: SI has {1}, PI missing").format(item["item_code"], item["si_qty"]))
                for item in validation_result.get("qty_mismatches", [])[:3]:
                    mismatch_details.append(_("Item {0}: SI has {1}, PI has {2}").format(item["item_code"], item["si_qty"], item["pi_qty"]))
                gt = validation_result.get("grand_total_mismatch")
                if gt:
                    mismatch_details.append(_("Grand Total diff: ₹{0:.2f}").format(abs(gt["diff"])))

                warning = _("Converted to BNS Internally Transferred but SI {0} not linked (mismatch: {1}). Check Internal Transfer Mismatch report.").format(
                    si.name, "; ".join(mismatch_details) or _("validation failed")
                )
                frappe.msgprint(warning, indicator="orange", title=_("Converted with Mismatch"))
                result["warning"] = warning
                result["sales_invoice_found"] = si.name
            else:
                # Validation passed — proceed to link
                # Get representing companies for validation
                si_customer_company = frappe.db.get_value("Customer", si.customer, "bns_represents_company")
                pi_supplier_company = None
                if pi.supplier:
                    pi_supplier_company = frappe.db.get_value("Supplier", pi.supplier, "bns_represents_company")
                    if not pi_supplier_company:
                        raise BNSValidationError(
                            _("Supplier {0} is missing bns_represents_company.").format(pi.supplier)
                        )

                # Validate companies match (PI supplier should represent SI's company)
                if si_customer_company and pi_supplier_company:
                    if pi_supplier_company != si_customer_company:
                        raise BNSValidationError(
                            _("Purchase Invoice supplier represents company {0}, but Sales Invoice customer represents {1}").format(
                                pi_supplier_company, si_customer_company
                            )
                        )

                # Check if SI already linked to another PI
                existing_ref = si.get("bns_inter_company_reference")
                if existing_ref and existing_ref != pi.name:
                    raise BNSValidationError(
                        _("Sales Invoice {0} is already linked to Purchase Invoice {1}").format(
                            sales_invoice, existing_ref
                        )
                    )

                # Match SI items to PI items and set sales_invoice_item on PI items
                n_updated = _match_and_set_item_references(si, pi)

                # Update Purchase Invoice document-level fields first
                frappe.db.set_value("Purchase Invoice", pi.name, {
                    "is_bns_internal_supplier": 1,
                    "bns_inter_company_reference": si.name,
                    "status": "BNS Internally Transferred"
                }, update_modified=False)

                # Reload PI to get updated values
                pi.reload()

                # Then update Sales Invoice
                si.db_set("bns_inter_company_reference", pi.name, update_modified=False)
                if si.status != "BNS Internally Transferred":
                    si.db_set("status", "BNS Internally Transferred", update_modified=False)
                if not si.get("is_bns_internal_customer"):
                    si.db_set("is_bns_internal_customer", 1, update_modified=False)

                # Clear cache for both documents
                frappe.clear_cache(doctype="Purchase Invoice")
                frappe.clear_cache(doctype="Sales Invoice")

                result["sales_invoice"] = si.name
                result["message"] = _("Purchase Invoice and Sales Invoice linked successfully")

                logger.info(f"Linked Purchase Invoice {pi.name} with Sales Invoice {si.name}, updated {n_updated} item references")
        
        frappe.clear_cache(doctype="Purchase Invoice")
        
        logger.info(f"Converted Purchase Invoice {pi.name} to BNS Internally Transferred")
        return result
        
    except Exception as e:
        logger.error(f"Error converting Purchase Invoice to BNS Internal: {str(e)}")
        frappe.throw(str(e))


@frappe.whitelist()
def get_purchase_receipt_by_supplier_delivery_note(delivery_note: str) -> Dict:
    """
    Find Purchase Receipt by supplier_delivery_note matching Delivery Note name.
    
    Args:
        delivery_note (str): Name of the Delivery Note
        
    Returns:
        Dict: Purchase Receipt details if found, None otherwise
    """
    _bns_require_accounts_read()
    try:
        # Find PR where supplier_delivery_note matches DN name
        pr_name = frappe.db.get_value("Purchase Receipt", {"supplier_delivery_note": delivery_note, "docstatus": 1}, "name")
        
        if not pr_name:
            return {"found": False}
        
        pr = frappe.get_doc("Purchase Receipt", pr_name)
        
        # Get basic details
        return {
            "found": True,
            "name": pr.name,
            "supplier": pr.supplier,
            "posting_date": str(pr.posting_date) if pr.posting_date else None,
            "grand_total": pr.grand_total or 0,
            "status": pr.status,
            "is_bns_internal_supplier": pr.get("is_bns_internal_supplier") or 0,
            "bns_inter_company_reference": pr.get("bns_inter_company_reference") or None
        }
    except Exception as e:
        logger.error(f"Error finding Purchase Receipt: {str(e)}")
        return {"found": False}


@frappe.whitelist()
def get_delivery_note_by_supplier_delivery_note(purchase_receipt: str) -> Dict:
    """
    Find Delivery Note by supplier_delivery_note from Purchase Receipt.
    
    Args:
        purchase_receipt (str): Name of the Purchase Receipt
        
    Returns:
        Dict: Delivery Note details if found, None otherwise
    """
    _bns_require_accounts_read()
    try:
        # Get Purchase Receipt to check supplier_delivery_note
        pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
        
        # Find DN where name matches PR's supplier_delivery_note
        dn_name = None
        if pr.supplier_delivery_note:
            dn_name = frappe.db.get_value("Delivery Note", {"name": pr.supplier_delivery_note, "docstatus": 1}, "name")
        
        if not dn_name:
            return {"found": False}
        
        dn = frappe.get_doc("Delivery Note", dn_name)
        
        # Get basic details
        return {
            "found": True,
            "name": dn.name,
            "customer": dn.customer,
            "posting_date": str(dn.posting_date) if dn.posting_date else None,
            "grand_total": dn.grand_total or 0,
            "status": dn.status,
            "is_bns_internal_customer": dn.get("is_bns_internal_customer") or 0,
            "billing_address_gstin": dn.get("billing_address_gstin"),
            "company_gstin": dn.get("company_gstin")
        }
    except Exception as e:
        logger.error(f"Error finding Delivery Note: {str(e)}")
        return {"found": False}


@frappe.whitelist()
def submit_diff_gstin_dn_for_internal_transfer(delivery_note: str) -> Dict[str, Any]:
    """Stamp the diff-GSTIN DN -> PR opt-in flag and submit the Delivery Note.

    Workflow:
      - Draft DN must exist, be for an internal customer, and have populated
        company GSTIN + billing GSTIN that differ.
      - Org-level setting ``allow_different_gstin_dn_to_pr`` must be ON.
      - Caller must hold write permission on Delivery Note AND on
        BNS Branch Accounting Settings (per Role Permission Manager).
      - Flag, enabling user, and timestamp are stamped before submit so the
        ``on_submit`` hooks (status update, GL rewrite trigger, e-Waybill
        auto-gen) see the per-doc opt-in.

    Once a DN is flagged + submitted, downstream behaviour (GL rewrite,
    repost, conversion/link, e-Waybill) stays active regardless of any
    future change to the org-level setting.

    Returns: {success, delivery_note, status, message}.
    """
    _bns_require_doctype_write("Delivery Note")
    _bns_require_accounts_write()

    if not delivery_note:
        frappe.throw(_("Delivery Note name is required."))
    if not frappe.db.exists("Delivery Note", delivery_note):
        frappe.throw(_("Delivery Note {0} does not exist.").format(delivery_note))

    if not _diff_gstin_dn_pr_global_enabled():
        frappe.throw(
            _(
                "Diff-GSTIN DN -> PR is not enabled at the company level. "
                "Enable 'Allow Different GSTIN DN → PR' in BNS Branch "
                "Accounting Settings first."
            ),
            title=_("Org Setting Disabled"),
        )

    dn = frappe.get_doc("Delivery Note", delivery_note)
    if dn.docstatus != 0:
        frappe.throw(
            _(
                "Diff-GSTIN DN -> PR opt-in can only be applied to a Draft "
                "Delivery Note. {0} is currently in '{1}' state."
            ).format(delivery_note, _docstatus_label(dn.docstatus)),
            title=_("Draft Only"),
        )

    if not is_bns_internal_customer(dn):
        frappe.throw(
            _("Delivery Note {0} customer is not marked as BNS Internal Customer.").format(delivery_note),
            title=_("Internal Customer Required"),
        )

    company_gstin = (dn.get("company_gstin") or "").strip()
    billing_gstin = (dn.get("billing_address_gstin") or "").strip()
    if not company_gstin or not billing_gstin:
        frappe.throw(
            _("Both Company GSTIN and Billing GSTIN must be populated on the Delivery Note before using this flow."),
            title=_("GSTIN Required"),
        )
    if company_gstin == billing_gstin:
        frappe.throw(
            _(
                "Company GSTIN and Billing GSTIN are the same on this Delivery Note. "
                "The diff-GSTIN opt-in is only for inter-state transfers; use the "
                "regular submit action for same-GSTIN movement."
            ),
            title=_("Use Standard DN Submit"),
        )

    if not is_after_internal_transfer_cutoff(dn.get("posting_date")):
        frappe.throw(
            _("Delivery Note {0} posting date is before the Internal Transfer Cutoff.").format(delivery_note),
            title=_("Cutoff Date Restriction"),
        )

    # Stamp the opt-in fields before submit so on_submit hooks observe them.
    dn.bns_allow_diff_gstin_dn_pr = 1
    dn.bns_diff_gstin_enabled_by = frappe.session.user
    dn.bns_diff_gstin_enabled_on = now_datetime()

    try:
        dn.submit()
    except Exception:
        logger.error(
            "submit_diff_gstin_dn_for_internal_transfer: submit failed for %s",
            delivery_note,
            exc_info=True,
        )
        raise

    _audit_unlink_action(
        "diff_gstin_dn_pr_opt_in_submitted",
        {
            "delivery_note": delivery_note,
            "company_gstin": company_gstin,
            "billing_address_gstin": billing_gstin,
            "enabled_by": frappe.session.user,
        },
    )

    return {
        "success": True,
        "delivery_note": dn.name,
        "status": dn.get("status"),
        "message": _(
            "Delivery Note {0} submitted as Diff GSTIN Internal Transfer."
        ).format(dn.name),
    }


@frappe.whitelist()
def convert_delivery_note_to_bns_internal(delivery_note: str, purchase_receipt: Optional[str] = None) -> Dict:
    """
    Convert a Delivery Note to BNS Internally Transferred status (same GSTIN only).
    
    This function:
    1. Validates GSTIN match (billing_address_gstin == company_gstin)
    2. Marks Delivery Note as BNS internal customer
    3. Updates status to "BNS Internally Transferred"
    4. Sets per_billed = 100%
    5. If Purchase Receipt is provided, validates and links them properly
    
    Args:
        delivery_note (str): Name of the Delivery Note to convert
        purchase_receipt (Optional[str]): Optional Purchase Receipt name to link
        
    Returns:
        Dict: Result with success message and updated references
        
    Raises:
        BNSValidationError: If validation fails
    """
    _bns_require_doctype_write("Delivery Note")
    _bns_require_doctype_write("Purchase Receipt")
    try:
        # Get Delivery Note
        dn = frappe.get_doc("Delivery Note", delivery_note)
        
        # Validate Delivery Note is submitted
        if dn.docstatus != 1:
            raise BNSValidationError(_("Delivery Note must be submitted before converting to BNS Internal"))
        
        # Check if customer is BNS internal
        customer_internal = frappe.db.get_value("Customer", dn.customer, "is_bns_internal_customer")
        if not customer_internal:
            raise BNSValidationError(_("Customer {0} is not marked as BNS Internal Customer").format(dn.customer))
        
        # Validate GSTIN match (same GSTIN only)
        billing_address_gstin = getattr(dn, 'billing_address_gstin', None)
        company_gstin = getattr(dn, 'company_gstin', None)
        
        if billing_address_gstin is None or company_gstin is None:
            raise BNSValidationError(_("GSTIN information is missing. Cannot convert to BNS Internal transfer."))
        
        if billing_address_gstin != company_gstin and not _diff_gstin_dn_pr_active_for_dn(dn):
            raise BNSValidationError(
                _("GSTIN mismatch: billing_address_gstin ({0}) != company_gstin ({1}). Only same GSTIN transfers can be converted. Use the 'Submit as Diff GSTIN Internal Transfer' button on the Delivery Note (requires 'Allow Different GSTIN DN → PR' enabled in BNS Branch Accounting Settings) to permit inter-state direct conversion.").format(
                    billing_address_gstin, company_gstin
                )
            )

        # Clear stale/wrong DN reference before checking "already converted"
        dn_ref = (dn.get("bns_inter_company_reference") or "").strip()
        if dn_ref:
            stale = _is_stale_inter_company_ref("Delivery Note", dn.name, dn_ref)
            if stale:
                logger.info("Clearing stale ref %s on DN %s (reason: %s)", dn_ref, dn.name, stale)
                _clear_counter_backref("Delivery Note", dn.name, dn_ref)
                dn.db_set("bns_inter_company_reference", "", update_modified=False)
                dn.bns_inter_company_reference = ""
                dn_ref = ""

        # Check if already fully converted (flag, status, AND reference are all set)
        if (
            dn.get("is_bns_internal_customer")
            and dn.status == "BNS Internally Transferred"
            and dn_ref
        ):
            return {"success": True, "message": _("Already converted")}
        
        # Auto-discover matching PR when none is provided
        if not purchase_receipt:
            pr_names = _get_submitted_prs_for_dn(dn.name)
            if pr_names:
                purchase_receipt = pr_names[0]

        # Update Delivery Note (even if flag is already set, ensure status is updated)
        dn.db_set("is_bns_internal_customer", 1, update_modified=False)
        dn.db_set("status", "BNS Internally Transferred", update_modified=False)
        dn.db_set("per_billed", 100, update_modified=False)
        
        # Clear cache to ensure changes are reflected
        frappe.clear_cache(doctype="Delivery Note")
        
        result = {
            "success": True,
            "message": _("Delivery Note converted to BNS Internally Transferred"),
            "delivery_note": dn.name
        }
        
        # If Purchase Receipt is provided (or auto-discovered), validate and link
        if purchase_receipt:
            pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
            
            # Validate PR is submitted
            if pr.docstatus != 1:
                raise BNSValidationError(_("Purchase Receipt {0} must be submitted before linking").format(purchase_receipt))
            
            # Validate PR traces back to this DN via supplier_delivery_note or bns_inter_company_reference
            pr_sdn = (pr.supplier_delivery_note or "").strip()
            pr_ref = (pr.get("bns_inter_company_reference") or "").strip()
            if pr_sdn != dn.name and pr_ref != dn.name:
                raise BNSValidationError(
                    _("Purchase Receipt {0} is not linked to Delivery Note {1}").format(
                        purchase_receipt, dn.name
                    )
                )
            
            # Validate PR GSTIN matches DN GSTIN
            pr_supplier_gstin = getattr(pr, 'supplier_gstin', None)
            pr_company_gstin = getattr(pr, 'company_gstin', None)
            
            if pr_company_gstin and pr_company_gstin != company_gstin:
                raise BNSValidationError(
                    _("Purchase Receipt company GSTIN ({0}) does not match Delivery Note company GSTIN ({1})").format(
                        pr_company_gstin, company_gstin
                    )
                )
            
            # Check if PR already linked to another DN — clear stale/wrong links
            existing_ref = (pr.get("bns_inter_company_reference") or "").strip()
            if existing_ref and existing_ref != dn.name:
                pr_sdn = (pr.get("supplier_delivery_note") or "").strip()
                stale = _is_stale_inter_company_ref(
                    "Purchase Receipt", pr.name, existing_ref
                )
                # supplier_delivery_note is the authoritative ERPNext link;
                # if it points to our DN, the bns ref is simply wrong.
                if stale or pr_sdn == dn.name:
                    reason = stale or f"supplier_delivery_note={pr_sdn}_matches_dn"
                    logger.info(
                        "Clearing wrong bns_inter_company_reference %s on PR %s (reason: %s)",
                        existing_ref, pr.name, reason,
                    )
                    _clear_counter_backref("Purchase Receipt", pr.name, existing_ref)
                    pr.db_set("bns_inter_company_reference", "", update_modified=False)
                    pr.bns_inter_company_reference = ""
                else:
                    raise BNSValidationError(
                        _("Purchase Receipt {0} is already linked to Delivery Note {1}").format(
                            purchase_receipt, existing_ref
                        )
                    )
            
            # Update Purchase Receipt document-level fields
            pr.db_set("is_bns_internal_supplier", 1, update_modified=False)
            pr.db_set("status", "BNS Internally Transferred", update_modified=False)
            pr.db_set("per_billed", 100, update_modified=False)
            if (pr.get("bns_inter_company_reference") or "") != dn.name:
                pr.db_set("bns_inter_company_reference", dn.name, update_modified=False)
            
            # Update Delivery Note reference
            if (dn.get("bns_inter_company_reference") or "") != pr.name:
                dn.db_set("bns_inter_company_reference", pr.name, update_modified=False)
            
            _remap_pr_delivery_note_items(dn, pr)

            # Clear cache for both documents
            frappe.clear_cache(doctype="Purchase Receipt")
            frappe.clear_cache(doctype="Delivery Note")
            
            result["purchase_receipt"] = pr.name
            result["message"] = _("Delivery Note and Purchase Receipt linked successfully")
            
            logger.info(f"Linked Delivery Note {dn.name} with Purchase Receipt {pr.name}")
        
        frappe.clear_cache(doctype="Delivery Note")
        
        logger.info(f"Converted Delivery Note {dn.name} to BNS Internally Transferred")
        return result
        
    except Exception as e:
        logger.error(f"Error converting Delivery Note to BNS Internal: {str(e)}")
        frappe.throw(str(e))


@frappe.whitelist()
def convert_purchase_receipt_to_bns_internal(purchase_receipt: str, delivery_note: Optional[str] = None) -> Dict:
    """
    Convert a Purchase Receipt to BNS Internally Transferred status (same GSTIN only).
    
    This function:
    1. Validates PR is from DN (via supplier_delivery_note)
    2. Validates GSTIN match (same GSTIN)
    3. Marks Purchase Receipt as BNS internal customer
    4. Updates status to "BNS Internally Transferred"
    5. Sets per_billed = 100%
    6. If Delivery Note is provided, validates and links them properly
    
    Args:
        purchase_receipt (str): Name of the Purchase Receipt to convert
        delivery_note (Optional[str]): Optional Delivery Note name to link
        
    Returns:
        Dict: Result with success message and updated references
        
    Raises:
        BNSValidationError: If validation fails
    """
    _bns_require_doctype_write("Purchase Receipt")
    _bns_require_doctype_write("Delivery Note")
    try:
        pr = frappe.get_doc("Purchase Receipt", purchase_receipt)

        if pr.docstatus != 1:
            raise BNSValidationError(_("Purchase Receipt must be submitted before converting to BNS Internal"))

        effective_date = _resolve_source_posting_date(pr)
        if not is_after_internal_transfer_cutoff(effective_date):
            frappe.throw(
                _("Cannot convert Purchase Receipt {0} to BNS Internal: source document is before the Internal Transfer Cutoff.").format(purchase_receipt),
                title=_("Cutoff Date Restriction"),
            )

        if not pr.supplier_delivery_note:
            raise BNSValidationError(_("Purchase Receipt must be created from a Delivery Note (supplier_delivery_note is missing)"))

        dn_exists = frappe.db.exists("Delivery Note", pr.supplier_delivery_note)
        if not dn_exists:
            raise BNSValidationError(_("Purchase Receipt supplier_delivery_note ({0}) is not a valid Delivery Note").format(pr.supplier_delivery_note))

        dn = frappe.get_doc("Delivery Note", pr.supplier_delivery_note)
        customer_internal = frappe.db.get_value("Customer", dn.customer, "is_bns_internal_customer")
        if not customer_internal:
            raise BNSValidationError(_("Delivery Note customer {0} is not marked as BNS Internal Customer").format(dn.customer))
        
        # Validate GSTIN match (same GSTIN only)
        dn_billing_gstin = getattr(dn, 'billing_address_gstin', None)
        dn_company_gstin = getattr(dn, 'company_gstin', None)
        pr_company_gstin = getattr(pr, 'company_gstin', None)
        
        if dn_billing_gstin is None or dn_company_gstin is None:
            raise BNSValidationError(_("Delivery Note GSTIN information is missing. Cannot convert to BNS Internal transfer."))
        
        if dn_billing_gstin != dn_company_gstin and not _diff_gstin_dn_pr_active_for_dn(dn):
            raise BNSValidationError(
                _("Delivery Note GSTIN mismatch: billing_address_gstin ({0}) != company_gstin ({1}). Only same GSTIN transfers can be converted. Use the 'Submit as Diff GSTIN Internal Transfer' button on the Delivery Note (requires 'Allow Different GSTIN DN → PR' enabled in BNS Branch Accounting Settings) to permit inter-state direct conversion.").format(
                    dn_billing_gstin, dn_company_gstin
                )
            )
        
        # Check if already fully converted (both flag and status are set)
        if pr.get("is_bns_internal_supplier") and pr.status == "BNS Internally Transferred":
            frappe.msgprint(_("Purchase Receipt is already marked as BNS Internally Transferred"))
            return {"success": True, "message": _("Already converted")}
        
        # Use delivery_note parameter if provided, otherwise use supplier_delivery_note
        linked_dn = delivery_note if delivery_note else pr.supplier_delivery_note
        
        # Validate linked DN matches supplier_delivery_note
        if linked_dn != pr.supplier_delivery_note:
            raise BNSValidationError(
                _("Delivery Note {0} does not match Purchase Receipt supplier_delivery_note ({1})").format(
                    linked_dn, pr.supplier_delivery_note
                )
            )
        
        # Clear stale/wrong bns_inter_company_reference on PR before setting
        pr_existing_ref = (pr.get("bns_inter_company_reference") or "").strip()
        if pr_existing_ref and pr_existing_ref != linked_dn:
            logger.info(
                "Overriding wrong bns_inter_company_reference %s on PR %s with %s (supplier_delivery_note is authoritative)",
                pr_existing_ref, pr.name, linked_dn,
            )
            _clear_counter_backref("Purchase Receipt", pr.name, pr_existing_ref)

        # Update Purchase Receipt (even if flag is already set, ensure status is updated)
        pr.db_set("is_bns_internal_supplier", 1, update_modified=False)
        pr.db_set("status", "BNS Internally Transferred", update_modified=False)
        pr.db_set("per_billed", 100, update_modified=False)
        if (pr.get("bns_inter_company_reference") or "") != linked_dn:
            pr.db_set("bns_inter_company_reference", linked_dn, update_modified=False)
        
        result = {
            "success": True,
            "message": _("Purchase Receipt converted to BNS Internally Transferred"),
            "purchase_receipt": pr.name
        }
        
        # Update Delivery Note
        if linked_dn:
            dn_reload = frappe.get_doc("Delivery Note", linked_dn)
            if (dn_reload.get("bns_inter_company_reference") or "") != pr.name:
                old_dn_ref = (dn_reload.get("bns_inter_company_reference") or "").strip()
                if old_dn_ref:
                    _clear_counter_backref("Delivery Note", dn_reload.name, old_dn_ref)
                dn_reload.db_set("bns_inter_company_reference", pr.name, update_modified=False)
            if dn_reload.status != "BNS Internally Transferred":
                dn_reload.db_set("status", "BNS Internally Transferred", update_modified=False)
            if not dn_reload.get("is_bns_internal_customer"):
                dn_reload.db_set("is_bns_internal_customer", 1, update_modified=False)
            if dn_reload.per_billed != 100:
                dn_reload.db_set("per_billed", 100, update_modified=False)
            
            _remap_pr_delivery_note_items(dn_reload, pr)

            result["delivery_note"] = linked_dn
            result["message"] = _("Purchase Receipt and Delivery Note linked successfully")
            
            logger.info(f"Linked Purchase Receipt {pr.name} with Delivery Note {linked_dn}")
        
        frappe.clear_cache(doctype="Purchase Receipt")
        frappe.clear_cache(doctype="Delivery Note")
        
        logger.info(f"Converted Purchase Receipt {pr.name} to BNS Internally Transferred")
        return result
        
    except Exception as e:
        logger.error(f"Error converting Purchase Receipt to BNS Internal: {str(e)}")
        frappe.throw(str(e))


def _cancel_submitted_docs(
    doctype: str, names: List[str], ignore_linked_doctypes: Optional[List[str]] = None
) -> int:
    """Cancel submitted documents safely and return cancelled count."""
    cancelled = 0
    ignore_linked_doctypes = ignore_linked_doctypes or []

    for name in names:
        if not name or not frappe.db.exists(doctype, name):
            continue

        linked_doc = frappe.get_doc(doctype, name)
        if linked_doc.docstatus != 1:
            continue

        linked_doc.ignore_linked_doctypes = ignore_linked_doctypes
        linked_doc.flags.ignore_linked_doctypes = ignore_linked_doctypes
        linked_doc.cancel()
        cancelled += 1

    return cancelled


def ignore_parent_cancellation_links_for_bns_internal(doc, method: Optional[str] = None) -> None:
    """
    On PR/PI cancel, skip backlink-enforced parent cancellation.

    Desired behavior:
    - Cancelling PR/PI should NOT force-cancel linked DN/SI.
    - Cancelling DN/SI should still be allowed to cancel linked PR/PI.
    """
    if doc.doctype == "Purchase Receipt":
        ignore_linked_doctypes = [
            # Keep core PR cancel ignores
            "GL Entry",
            "Stock Ledger Entry",
            "Repost Item Valuation",
            "Serial and Batch Bundle",
            # BNS parent-link policy
            "Delivery Note",
            "Sales Invoice",
            # Payment-ledger link safety
            "Payment Ledger Entry",
            "Advance Payment Ledger Entry",
            # Repost log must not block cancel (newer ERPNext ignores these too)
            "Repost Accounting Ledger",
            "Repost Accounting Ledger Items",
        ]
    elif doc.doctype == "Purchase Invoice":
        ignore_linked_doctypes = [
            "GL Entry",
            "Stock Ledger Entry",
            "Repost Item Valuation",
            "Serial and Batch Bundle",
            "Sales Invoice",
            "Payment Ledger Entry",
            "Advance Payment Ledger Entry",
            "Repost Accounting Ledger",
            "Repost Accounting Ledger Items",
        ]
    else:
        return

    doc.ignore_linked_doctypes = ignore_linked_doctypes
    doc.flags.ignore_linked_doctypes = ignore_linked_doctypes


# Repost Accounting Ledger is just a repost log; a submitted RAL referencing a
# voucher must never block that voucher's cancellation.
REPOST_LEDGER_LINK_DOCTYPES = ("Repost Accounting Ledger", "Repost Accounting Ledger Items")


def bns_ignore_repost_ledger_links_on_cancel(doc, method: Optional[str] = None) -> None:
    """Append Repost Accounting Ledger (+ child) to ignore_linked_doctypes on cancel.

    Newer ERPNext already ignores these, but older versions (and BNS's own
    before_cancel overrides) may not — leaving a submitted Repost Accounting
    Ledger to raise "linked with ... Repost Accounting Ledger" and block cancel.

    Hooked on ``on_cancel`` so it runs AFTER the controller's on_cancel (which
    may reset ``ignore_linked_doctypes``) and before ``check_no_back_links_exist``
    (frappe document.py). Appends rather than replaces, so it never drops any
    ignore another handler already set. The RAL is left intact (it's a log); the
    voucher's own cancel reposts its GL anyway.
    """
    existing = list(doc.get("ignore_linked_doctypes") or [])
    for dt in REPOST_LEDGER_LINK_DOCTYPES:
        if dt not in existing:
            existing.append(dt)
    doc.ignore_linked_doctypes = existing
    doc.flags.ignore_linked_doctypes = existing


def ignore_payment_ledger_cancellation_links_for_dn(doc, method: Optional[str] = None) -> None:
    """On DN cancel, skip backlink check against Payment Ledger Entry.

    BNS internal DN GL rewrite posts to a party-tracked debtor account
    (`internal_branch_debtor_account`), which makes ERPNext auto-create
    Payment Ledger Entry rows. Those PLE rows then block DN cancel via
    the standard link check. The reverse GL produced on cancel creates
    offsetting PLE rows that net to zero, so skipping the check is safe.
    Mirrors the PR/PI pattern in
    `ignore_parent_cancellation_links_for_bns_internal`.
    """
    if doc.doctype != "Delivery Note":
        return

    ignore_linked_doctypes = [
        # ERPNext's DN defaults (delivery_note.py:519-524).
        "GL Entry",
        "Stock Ledger Entry",
        "Repost Item Valuation",
        "Serial and Batch Bundle",
        # BNS additions: PLE rows auto-created by GL rewrite to
        # party-tracked accounts must not block DN cancel.
        "Payment Ledger Entry",
        "Advance Payment Ledger Entry",
        # Repost log must not block cancel.
        "Repost Accounting Ledger",
        "Repost Accounting Ledger Items",
    ]
    doc.ignore_linked_doctypes = ignore_linked_doctypes
    doc.flags.ignore_linked_doctypes = ignore_linked_doctypes


def unlink_references_on_purchase_cancel(doc, method: Optional[str] = None) -> None:
    """
    On PR/PI cancel, only remove BNS links; never cancel parent SI/DN.

    Policy:
    - Cancel PR/PI -> unlink references on both sides.
    - Cancel SI/DN -> handled by dedicated parent-side cascade methods.
    """
    # Re-apply ignore list after core on_cancel execution.
    # ERPNext checks backlinks after all on_cancel handlers, so this must be set here too.
    ignore_parent_cancellation_links_for_bns_internal(doc, method=method)

    if doc.docstatus != 2:
        return

    try:
        if doc.doctype == "Purchase Receipt":
            si_name = None
            dn_name = None

            # Resolve potential parent refs before clearing PR side.
            ref_name = doc.get("bns_inter_company_reference")
            supplier_ref = doc.get("supplier_delivery_note")
            if ref_name and frappe.db.exists("Sales Invoice", ref_name):
                si_name = ref_name
            elif ref_name and frappe.db.exists("Delivery Note", ref_name):
                dn_name = ref_name

            if supplier_ref and frappe.db.exists("Sales Invoice", supplier_ref):
                si_name = si_name or supplier_ref
            elif supplier_ref and frappe.db.exists("Delivery Note", supplier_ref):
                dn_name = dn_name or supplier_ref

            # Clear PR-side links.
            if doc.get("bns_inter_company_reference"):
                doc.db_set("bns_inter_company_reference", "", update_modified=False)
            if doc.get("supplier_delivery_note"):
                doc.db_set("supplier_delivery_note", "", update_modified=False)

            # Clear SI-side backlink (SI->PR flow) if this PR is currently referenced.
            if si_name and frappe.db.exists("Sales Invoice", si_name):
                si = frappe.get_doc("Sales Invoice", si_name)
                if si.meta.has_field("bns_purchase_receipt_reference") and si.get("bns_purchase_receipt_reference") == doc.name:
                    si.db_set("bns_purchase_receipt_reference", "", update_modified=False)
                frappe.clear_cache(doctype="Sales Invoice")

            # Clear DN-side backlink only when it points to this PR.
            if dn_name and frappe.db.exists("Delivery Note", dn_name):
                dn = frappe.get_doc("Delivery Note", dn_name)
                if dn.get("bns_inter_company_reference") == doc.name:
                    dn.db_set("bns_inter_company_reference", "", update_modified=False)
                frappe.clear_cache(doctype="Delivery Note")

            frappe.clear_cache(doctype="Purchase Receipt")

        elif doc.doctype == "Purchase Invoice":
            si_name = doc.get("bns_inter_company_reference")

            # Clear PI-side link.
            if doc.get("bns_inter_company_reference"):
                doc.db_set("bns_inter_company_reference", "", update_modified=False)

            # Clear SI-side backlink only when it points to this PI.
            if si_name and frappe.db.exists("Sales Invoice", si_name):
                si = frappe.get_doc("Sales Invoice", si_name)
                if si.get("bns_inter_company_reference") == doc.name:
                    si.db_set("bns_inter_company_reference", "", update_modified=False)
                frappe.clear_cache(doctype="Sales Invoice")

            frappe.clear_cache(doctype="Purchase Invoice")

    except Exception as e:
        # Do not block parent cancellation flow if unlink cleanup fails.
        logger.error("Failed unlink cleanup on %s cancel (%s): %s", doc.doctype, doc.name, str(e))


def validate_delivery_note_cancellation(doc, method: Optional[str] = None) -> None:
    """
    Cancel linked submitted Purchase Receipts when cancelling Delivery Note.

    One-way policy:
    - DN cancel -> cancel linked PRs
    - PR cancel -> does not cancel DN
    """
    if doc.docstatus != 2:
        return

    linked_pr_names = set()

    for row in frappe.get_all(
        "Purchase Receipt",
        filters={"supplier_delivery_note": doc.name, "docstatus": 1},
        pluck="name",
    ):
        linked_pr_names.add(row)

    for row in frappe.get_all(
        "Purchase Receipt",
        filters={"bns_inter_company_reference": doc.name, "docstatus": 1},
        pluck="name",
    ):
        linked_pr_names.add(row)

    if not linked_pr_names:
        return

    cancelled = _cancel_submitted_docs(
        "Purchase Receipt",
        sorted(linked_pr_names),
        ignore_linked_doctypes=["Delivery Note", "Sales Invoice"],
    )
    logger.info(
        "Cancelled %s linked Purchase Receipt(s) for Delivery Note %s",
        cancelled,
        doc.name,
    )


def cancel_linked_purchase_docs_for_sales_invoice(doc, method: Optional[str] = None) -> None:
    """
    Cancel linked submitted PI/PR when cancelling Sales Invoice.

    One-way policy:
    - SI cancel -> cancel linked PI/PR
    - PI/PR cancel -> does not cancel SI
    """
    if doc.docstatus != 2:
        return

    linked_pi_names = set(
        frappe.get_all(
            "Purchase Invoice",
            filters={"bns_inter_company_reference": doc.name, "docstatus": 1},
            pluck="name",
        )
    )
    linked_pr_names = set(
        frappe.get_all(
            "Purchase Receipt",
            filters={"supplier_delivery_note": doc.name, "docstatus": 1},
            pluck="name",
        )
    )

    pi_cancelled = _cancel_submitted_docs(
        "Purchase Invoice",
        sorted(linked_pi_names),
        ignore_linked_doctypes=["Sales Invoice"],
    )
    pr_cancelled = _cancel_submitted_docs(
        "Purchase Receipt",
        sorted(linked_pr_names),
        ignore_linked_doctypes=["Delivery Note", "Sales Invoice"],
    )

    if pi_cancelled or pr_cancelled:
        logger.info(
            "Cancelled linked docs for Sales Invoice %s: PI=%s, PR=%s",
            doc.name,
            pi_cancelled,
            pr_cancelled,
        )


def validate_bns_internal_customer_return(doc, method: Optional[str] = None) -> None:
    """
    Validate return entries (Credit Notes) for BNS internal customers.

    Previously blocked all returns; now allows them so that
    SI credit notes can be converted to PI debit notes.
    """
    pass


def validate_bns_internal_delivery_note_return(doc, method: Optional[str] = None) -> None:
    """
    Validate return entries for Delivery Notes with BNS internal customers.

    Previously blocked all returns; now allows them so that
    DN returns can be converted to PR returns.
    """
    pass


@frappe.whitelist()
def validate_dn_pr_items_match(delivery_note: str, purchase_receipt: str) -> Dict:
    """
    Validate that Delivery Note and Purchase Receipt items match.
    
    Args:
        delivery_note (str): Delivery Note name
        purchase_receipt (str): Purchase Receipt name
        
    Returns:
        Dict: Validation result with match status and details
    """
    _bns_require_accounts_read()
    try:
        dn = frappe.get_doc("Delivery Note", delivery_note)
        pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
        
        # Get DN items aggregated by item_code
        dn_items = {}
        for item in dn.items:
            item_code = item.item_code
            qty = flt(item.qty or 0)
            stock_qty = flt(item.stock_qty or qty)
            
            if item_code not in dn_items:
                dn_items[item_code] = {"qty": 0, "stock_qty": 0}
            dn_items[item_code]["qty"] += qty
            dn_items[item_code]["stock_qty"] += stock_qty
        
        # Get PR items aggregated by item_code
        pr_items = {}
        for item in pr.items:
            item_code = item.item_code
            qty = flt(item.qty or 0)
            stock_qty = flt(item.stock_qty or qty)
            
            if item_code not in pr_items:
                pr_items[item_code] = {"qty": 0, "stock_qty": 0}
            pr_items[item_code]["qty"] += qty
            pr_items[item_code]["stock_qty"] += stock_qty
        
        # Check if all DN items exist in PR and quantities match
        missing_items = []
        qty_mismatches = []
        
        for item_code, dn_data in dn_items.items():
            if item_code not in pr_items:
                missing_items.append({
                    "item_code": item_code,
                    "dn_qty": dn_data["qty"],
                    "pr_qty": 0
                })
            elif flt(dn_data["qty"]) != flt(pr_items[item_code]["qty"]):
                qty_mismatches.append({
                    "item_code": item_code,
                    "dn_qty": dn_data["qty"],
                    "pr_qty": pr_items[item_code]["qty"]
                })
        
        # Check if PR has extra items not in DN
        extra_items = []
        for item_code in pr_items:
            if item_code not in dn_items:
                extra_items.append({
                    "item_code": item_code,
                    "dn_qty": 0,
                    "pr_qty": pr_items[item_code]["qty"]
                })
        
        if missing_items or qty_mismatches or extra_items:
            error_msg = _("Item mismatches found:\n")
            
            if missing_items:
                error_msg += _("\nMissing items in Purchase Receipt:\n")
                for item in missing_items:
                    error_msg += _("  - {0}: DN qty = {1}, PR qty = {2}\n").format(
                        item["item_code"], item["dn_qty"], item["pr_qty"]
                    )
            
            if qty_mismatches:
                error_msg += _("\nQuantity mismatches:\n")
                for item in qty_mismatches:
                    error_msg += _("  - {0}: DN qty = {1}, PR qty = {2}\n").format(
                        item["item_code"], item["dn_qty"], item["pr_qty"]
                    )
            
            if extra_items:
                error_msg += _("\nExtra items in Purchase Receipt:\n")
                for item in extra_items:
                    error_msg += _("  - {0}: DN qty = {1}, PR qty = {2}\n").format(
                        item["item_code"], item["dn_qty"], item["pr_qty"]
                    )
            
            return {
                "match": False,
                "error": error_msg,
                "missing_items": missing_items,
                "qty_mismatches": qty_mismatches,
                "extra_items": extra_items
            }
        
        return {
            "match": True,
            "message": _("All items match successfully")
        }
        
    except Exception as e:
        logger.error(f"Error validating DN-PR items match: {str(e)}")
        frappe.throw(_("Error validating items: {0}").format(str(e)))


@frappe.whitelist()
def validate_si_pr_items_match(sales_invoice: str, purchase_receipt: str) -> Dict:
    """
    Validate that Sales Invoice and Purchase Receipt items match.

    Args:
        sales_invoice (str): Sales Invoice name
        purchase_receipt (str): Purchase Receipt name

    Returns:
        Dict: Validation result with match status and details
    """
    _bns_require_accounts_read()
    try:
        si = frappe.get_doc("Sales Invoice", sales_invoice)
        pr = frappe.get_doc("Purchase Receipt", purchase_receipt)

        si_items = {}
        for item in si.items:
            item_code = item.item_code
            qty = flt(item.qty or 0)
            stock_qty = flt(item.stock_qty or qty)
            if item_code not in si_items:
                si_items[item_code] = {"qty": 0, "stock_qty": 0}
            si_items[item_code]["qty"] += qty
            si_items[item_code]["stock_qty"] += stock_qty

        pr_items = {}
        for item in pr.items:
            item_code = item.item_code
            qty = flt(item.qty or 0)
            stock_qty = flt(item.stock_qty or qty)
            if item_code not in pr_items:
                pr_items[item_code] = {"qty": 0, "stock_qty": 0}
            pr_items[item_code]["qty"] += qty
            pr_items[item_code]["stock_qty"] += stock_qty

        missing_items = []
        qty_mismatches = []
        for item_code, si_data in si_items.items():
            if item_code not in pr_items:
                missing_items.append({"item_code": item_code, "si_qty": si_data["qty"], "pr_qty": 0})
            elif flt(si_data["qty"]) != flt(pr_items[item_code]["qty"]):
                qty_mismatches.append({
                    "item_code": item_code,
                    "si_qty": si_data["qty"],
                    "pr_qty": pr_items[item_code]["qty"]
                })

        extra_items = []
        for item_code in pr_items:
            if item_code not in si_items:
                extra_items.append({"item_code": item_code, "si_qty": 0, "pr_qty": pr_items[item_code]["qty"]})

        if missing_items or qty_mismatches or extra_items:
            error_msg = _("Item mismatches found:\n")
            if missing_items:
                error_msg += _("\nMissing items in Purchase Receipt:\n")
                for item in missing_items:
                    error_msg += _("  - {0}: SI qty = {1}, PR qty = {2}\n").format(item["item_code"], item["si_qty"], item["pr_qty"])
            if qty_mismatches:
                error_msg += _("\nQuantity mismatches:\n")
                for item in qty_mismatches:
                    error_msg += _("  - {0}: SI qty = {1}, PR qty = {2}\n").format(item["item_code"], item["si_qty"], item["pr_qty"])
            if extra_items:
                error_msg += _("\nExtra items in Purchase Receipt:\n")
                for item in extra_items:
                    error_msg += _("  - {0}: SI qty = {1}, PR qty = {2}\n").format(item["item_code"], item["si_qty"], item["pr_qty"])
            return {"match": False, "error": error_msg}
        return {"match": True, "message": _("All items match successfully")}
    except Exception as e:
        logger.error(f"Error validating SI-PR items match: {str(e)}")
        frappe.throw(_("Error validating items: {0}").format(str(e)))


@frappe.whitelist()
def link_dn_pr(delivery_note: str, purchase_receipt: str) -> Dict:
    """
    Link a Delivery Note with a Purchase Receipt for BNS Internal transfer.
    
    Args:
        delivery_note (str): Delivery Note name
        purchase_receipt (str): Purchase Receipt name
        
    Returns:
        Dict: Result with success message
    """
    _bns_require_doctype_write("Delivery Note")
    _bns_require_doctype_write("Purchase Receipt")
    try:
        dn = frappe.get_doc("Delivery Note", delivery_note, for_update=True)
        pr = frappe.get_doc("Purchase Receipt", purchase_receipt, for_update=True)

        if dn.docstatus != 1:
            raise BNSValidationError(_("Delivery Note must be submitted before linking"))
        if pr.docstatus != 1:
            raise BNSValidationError(_("Purchase Receipt must be submitted before linking"))

        if not is_after_internal_transfer_cutoff(dn.get("posting_date")):
            frappe.throw(
                _("Cannot link: Delivery Note {0} is before the Internal Transfer Cutoff.").format(delivery_note),
                title=_("Cutoff Date Restriction"),
            )

        if pr.supplier_delivery_note and pr.supplier_delivery_note != dn.name:
            logger.warning(f"Purchase Receipt {purchase_receipt} has supplier_delivery_note {pr.supplier_delivery_note} but linking to {delivery_note}")
        
        # Validate GSTIN match (same GSTIN only)
        dn_billing_gstin = getattr(dn, 'billing_address_gstin', None)
        dn_company_gstin = getattr(dn, 'company_gstin', None)
        
        if not dn_billing_gstin or not dn_company_gstin:
            raise BNSValidationError(_("Delivery Note GSTIN information is missing"))
        
        if dn_billing_gstin != dn_company_gstin and not _diff_gstin_dn_pr_active_for_dn(dn):
            raise BNSValidationError(
                _("GSTIN mismatch: Only same GSTIN transfers can be linked. billing_address_gstin ({0}) != company_gstin ({1}). Use the 'Submit as Diff GSTIN Internal Transfer' button on the Delivery Note (requires 'Allow Different GSTIN DN → PR' enabled in BNS Branch Accounting Settings) to permit inter-state direct linking.").format(
                    dn_billing_gstin, dn_company_gstin
                )
            )
        
        # Validate customer is BNS internal
        customer_internal = frappe.db.get_value("Customer", dn.customer, "is_bns_internal_customer")
        if not customer_internal:
            raise BNSValidationError(_("Customer {0} is not marked as BNS Internal Customer").format(dn.customer))
        
        # Check if already linked
        if dn.get("bns_inter_company_reference") == pr.name and pr.get("bns_inter_company_reference") == dn.name:
            frappe.msgprint(_("Delivery Note and Purchase Receipt are already linked"))
            return {"success": True, "message": _("Already linked")}
        
        # Check if DN is already linked to another PR — clear stale links
        dn_existing = (dn.get("bns_inter_company_reference") or "").strip()
        if dn_existing and dn_existing != pr.name:
            stale = _is_stale_inter_company_ref("Delivery Note", dn.name, dn_existing)
            if stale:
                logger.info("Clearing stale ref %s on DN %s (reason: %s)", dn_existing, dn.name, stale)
                dn.db_set("bns_inter_company_reference", "", update_modified=False)
                dn.bns_inter_company_reference = ""
            else:
                raise BNSValidationError(
                    _("Delivery Note {0} is already linked to Purchase Receipt {1}").format(
                        delivery_note, dn_existing
                    )
                )
        
        # Check if PR is already linked to another DN — clear stale links
        pr_existing = (pr.get("bns_inter_company_reference") or "").strip()
        if pr_existing and pr_existing != dn.name:
            stale = _is_stale_inter_company_ref("Purchase Receipt", pr.name, pr_existing)
            if stale:
                logger.info("Clearing stale ref %s on PR %s (reason: %s)", pr_existing, pr.name, stale)
                pr.db_set("bns_inter_company_reference", "", update_modified=False)
                pr.bns_inter_company_reference = ""
            else:
                raise BNSValidationError(
                    _("Purchase Receipt {0} is already linked to Delivery Note {1}").format(
                        purchase_receipt, pr_existing
                    )
                )
        
        # Validate items match
        items_validation = validate_dn_pr_items_match(delivery_note, purchase_receipt)
        if not items_validation.get("match"):
            raise BNSValidationError(_("Items do not match: {0}").format(items_validation.get("error")))
        
        # Set bidirectional references
        dn.db_set("bns_inter_company_reference", pr.name, update_modified=False)
        pr.db_set("bns_inter_company_reference", dn.name, update_modified=False)
        
        # Update status and flags if not already set
        if not dn.get("is_bns_internal_customer"):
            dn.db_set("is_bns_internal_customer", 1, update_modified=False)
        if dn.status != "BNS Internally Transferred":
            dn.db_set("status", "BNS Internally Transferred", update_modified=False)
        if dn.per_billed != 100:
            dn.db_set("per_billed", 100, update_modified=False)
        
        if not pr.get("is_bns_internal_supplier"):
            pr.db_set("is_bns_internal_supplier", 1, update_modified=False)
        if pr.status != "BNS Internally Transferred":
            pr.db_set("status", "BNS Internally Transferred", update_modified=False)
        if pr.per_billed != 100:
            pr.db_set("per_billed", 100, update_modified=False)
        
        _remap_pr_delivery_note_items(dn, pr)

        # Clear cache
        frappe.clear_cache(doctype="Delivery Note")
        frappe.clear_cache(doctype="Purchase Receipt")
        
        logger.info(f"Linked Delivery Note {delivery_note} with Purchase Receipt {purchase_receipt}")
        
        return {
            "success": True,
            "message": _("Delivery Note and Purchase Receipt linked successfully")
        }
        
    except Exception as e:
        logger.error(f"Error linking DN-PR: {str(e)}")
        frappe.throw(str(e))


def _enforce_unlink_recovery_permission(action: str) -> None:
    """Gate unlink recovery operations via the Role Permission Manager.

    Admin access is implicit (Administrator bypasses all perm checks),
    everyone else needs write permission on BNS Branch Accounting Settings
    — configured through the Desk UI, not hardcoded roles.
    """
    if frappe.session.user == "Administrator":
        return
    if frappe.has_permission(_BNS_BA_SETTINGS, "write"):
        return

    frappe.throw(
        _("You need write permission on {0} to run {1}. "
          "Ask an administrator to grant your role access via the "
          "Role Permission Manager.").format(_BNS_BA_SETTINGS, action),
        frappe.PermissionError,
        title=_("Not Permitted"),
    )


def _audit_unlink_action(action: str, payload: Dict[str, Any]) -> None:
    """Write a durable audit trail for manual unlink recovery operations."""
    audit_payload = {
        "action": action,
        "user": frappe.session.user,
        "timestamp": frappe.utils.now(),
        **(payload or {}),
    }
    message = frappe.as_json(audit_payload, indent=2)
    logger.warning("BNS unlink audit: %s", message)
    try:
        frappe.log_error(message=message, title=f"BNS Unlink Audit: {action}")
    except Exception:
        logger.exception("Failed to persist unlink audit log for action %s", action)


@frappe.whitelist()
def unlink_dn_pr(delivery_note: str = None, purchase_receipt: str = None) -> Dict:
    """
    Unlink a Delivery Note and Purchase Receipt.
    
    This function allows unlinking from either side, even if the other side
    doesn't have the reference set. It will clear references on both sides
    if they exist, but won't fail if one side is missing.
    
    Args:
        delivery_note (str): Delivery Note name (optional if purchase_receipt provided)
        purchase_receipt (str): Purchase Receipt name (optional if delivery_note provided)
        
    Returns:
        Dict: Result with success message
    """
    _bns_require_accounts_read()
    try:
        _enforce_unlink_recovery_permission("unlink_dn_pr")
        _audit_unlink_action(
            "unlink_dn_pr_requested",
            {"delivery_note": delivery_note, "purchase_receipt": purchase_receipt},
        )

        if not delivery_note and not purchase_receipt:
            raise BNSValidationError(_("Either delivery_note or purchase_receipt must be provided"))
        
        # If only one is provided, get the other from the reference
        if delivery_note and not purchase_receipt:
            dn = frappe.get_doc("Delivery Note", delivery_note)
            purchase_receipt = dn.get("bns_inter_company_reference")
            if not purchase_receipt:
                # DN doesn't have reference, but still allow clearing if needed
                # Just clear DN's reference and return
                dn.db_set("bns_inter_company_reference", "", update_modified=False)
                frappe.clear_cache(doctype="Delivery Note")
                logger.info(f"Cleared reference from Delivery Note {delivery_note} (no PR reference found)")
                return {
                    "success": True,
                    "message": _("Cleared reference from Delivery Note")
                }
        
        if purchase_receipt and not delivery_note:
            pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
            delivery_note = pr.get("bns_inter_company_reference")
            if not delivery_note:
                # PR doesn't have reference, but still allow clearing if needed
                # Just clear PR's reference and return
                pr.db_set("bns_inter_company_reference", "", update_modified=False)
                frappe.clear_cache(doctype="Purchase Receipt")
                logger.info(f"Cleared reference from Purchase Receipt {purchase_receipt} (no DN reference found)")
                return {
                    "success": True,
                    "message": _("Cleared reference from Purchase Receipt")
                }
        
        # Clear each side independently — the contra document may have been
        # cancelled or deleted, so we must not crash when it is missing.
        dn_cleared = False
        pr_cleared = False
        
        if delivery_note:
            if frappe.db.exists("Delivery Note", delivery_note):
                dn = frappe.get_doc("Delivery Note", delivery_note)
                if dn.get("bns_inter_company_reference"):
                    dn.db_set("bns_inter_company_reference", "", update_modified=False)
                dn.db_set("is_bns_internal_customer", 0, update_modified=False)
                dn.db_set("status", "To Bill", update_modified=False)
                dn.db_set("per_billed", 0, update_modified=False)
                dn_cleared = True
            else:
                logger.warning(f"Delivery Note {delivery_note} does not exist — skipping its side of unlink")

        if purchase_receipt:
            if frappe.db.exists("Purchase Receipt", purchase_receipt):
                pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
                if pr.get("bns_inter_company_reference"):
                    pr.db_set("bns_inter_company_reference", "", update_modified=False)
                if pr.get("supplier_delivery_note") == delivery_note:
                    pr.db_set("supplier_delivery_note", "", update_modified=False)
                pr.db_set("is_bns_internal_supplier", 0, update_modified=False)
                pr.db_set("status", "To Bill", update_modified=False)
                pr.db_set("per_billed", 0, update_modified=False)
                pr_cleared = True
            else:
                logger.warning(f"Purchase Receipt {purchase_receipt} does not exist — skipping its side of unlink")
        
        # Clear cache for whichever sides were touched
        if dn_cleared:
            frappe.clear_cache(doctype="Delivery Note")
        if pr_cleared:
            frappe.clear_cache(doctype="Purchase Receipt")
        
        logger.info(f"Unlinked Delivery Note {delivery_note} from Purchase Receipt {purchase_receipt}")
        _audit_unlink_action(
            "unlink_dn_pr_completed",
            {"delivery_note": delivery_note, "purchase_receipt": purchase_receipt},
        )
        
        return {
            "success": True,
            "message": _("Delivery Note and Purchase Receipt unlinked successfully")
        }
        
    except Exception as e:
        logger.error(f"Error unlinking DN-PR: {str(e)}")
        frappe.throw(str(e))


@frappe.whitelist()
def link_si_pr(sales_invoice: str, purchase_receipt: str) -> Dict:
    """
    Link a Sales Invoice with a Purchase Receipt for BNS Internal transfer (different GSTIN flow).

    Args:
        sales_invoice (str): Sales Invoice name
        purchase_receipt (str): Purchase Receipt name

    Returns:
        Dict: Result with success message
    """
    _bns_require_doctype_write("Sales Invoice")
    _bns_require_doctype_write("Purchase Receipt")
    try:
        si = frappe.get_doc("Sales Invoice", sales_invoice)
        pr = frappe.get_doc("Purchase Receipt", purchase_receipt)

        if si.docstatus != 1:
            raise BNSValidationError(_("Sales Invoice must be submitted before linking"))
        if pr.docstatus != 1:
            raise BNSValidationError(_("Purchase Receipt must be submitted before linking"))

        if not is_after_internal_transfer_cutoff(si.get("posting_date")):
            frappe.throw(
                _("Cannot link: Sales Invoice {0} is before the Internal Transfer Cutoff.").format(sales_invoice),
                title=_("Cutoff Date Restriction"),
            )

        si_billing_gstin = getattr(si, 'billing_address_gstin', None)
        si_company_gstin = getattr(si, 'company_gstin', None)
        if not si_billing_gstin or not si_company_gstin:
            raise BNSValidationError(_("Sales Invoice GSTIN information is missing"))
        if si_billing_gstin == si_company_gstin:
            raise BNSValidationError(
                _("GSTIN match: Only different GSTIN transfers can be linked. Use Link Delivery Note for same GSTIN.")
            )

        customer_internal = frappe.db.get_value("Customer", si.customer, "is_bns_internal_customer")
        if not customer_internal:
            raise BNSValidationError(_("Customer {0} is not marked as BNS Internal Customer").format(si.customer))

        if si.get("bns_inter_company_reference") == pr.name and pr.get("bns_inter_company_reference") == si.name:
            return {"success": True, "message": _("Already linked")}
        if pr.get("bns_inter_company_reference") and pr.get("bns_inter_company_reference") != si.name:
            raise BNSValidationError(
                _("Purchase Receipt {0} is already linked to {1}").format(purchase_receipt, pr.get("bns_inter_company_reference"))
            )

        items_validation = validate_si_pr_items_match(sales_invoice, purchase_receipt)
        if not items_validation.get("match"):
            raise BNSValidationError(_("Items do not match: {0}").format(items_validation.get("error")))

        pr.db_set("bns_inter_company_reference", si.name, update_modified=False)
        pr.db_set("supplier_delivery_note", si.name, update_modified=False)
        if not pr.get("is_bns_internal_supplier"):
            pr.db_set("is_bns_internal_supplier", 1, update_modified=False)
        if pr.status != "BNS Internally Transferred":
            pr.db_set("status", "BNS Internally Transferred", update_modified=False)
        if pr.per_billed != 100:
            pr.db_set("per_billed", 100, update_modified=False)

        if si.meta.has_field("bns_purchase_receipt_reference"):
            si.db_set("bns_purchase_receipt_reference", pr.name, update_modified=False)
        frappe.clear_cache(doctype="Sales Invoice")
        frappe.clear_cache(doctype="Purchase Receipt")

        logger.info(f"Linked Sales Invoice {sales_invoice} with Purchase Receipt {purchase_receipt}")
        return {"success": True, "message": _("Sales Invoice and Purchase Receipt linked successfully")}
    except Exception as e:
        logger.error(f"Error linking SI-PR: {str(e)}")
        frappe.throw(str(e))


@frappe.whitelist()
def unlink_si_pr(sales_invoice: str = None, purchase_receipt: str = None) -> Dict:
    """
    Unlink a Sales Invoice and Purchase Receipt (when PR was created from SI).

    Clears supplier_delivery_note and bns_inter_company_reference on both sides.

    Args:
        sales_invoice (str): Sales Invoice name (optional if purchase_receipt provided)
        purchase_receipt (str): Purchase Receipt name (optional if sales_invoice provided)

    Returns:
        Dict: Result with success message
    """
    _bns_require_accounts_read()
    try:
        _enforce_unlink_recovery_permission("unlink_si_pr")
        _audit_unlink_action(
            "unlink_si_pr_requested",
            {"sales_invoice": sales_invoice, "purchase_receipt": purchase_receipt},
        )

        if not sales_invoice and not purchase_receipt:
            raise BNSValidationError(_("Either sales_invoice or purchase_receipt must be provided"))

        if purchase_receipt and not sales_invoice:
            pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
            ref = pr.get("bns_inter_company_reference")
            if ref and frappe.db.exists("Sales Invoice", ref):
                sales_invoice = ref

        if sales_invoice and not purchase_receipt:
            pr_name = frappe.db.get_value(
                "Purchase Receipt",
                {"bns_inter_company_reference": sales_invoice, "docstatus": 1},
                "name"
            )
            if pr_name:
                purchase_receipt = pr_name

        if not purchase_receipt:
            return {"success": True, "message": _("No linked Purchase Receipt found")}

        pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
        if pr.get("bns_inter_company_reference"):
            pr.db_set("bns_inter_company_reference", "", update_modified=False)
        if pr.get("supplier_delivery_note") == sales_invoice:
            pr.db_set("supplier_delivery_note", "", update_modified=False)
        frappe.clear_cache(doctype="Purchase Receipt")

        # Clear SI's bns_purchase_receipt_reference if set
        if frappe.db.exists("Sales Invoice", sales_invoice):
            si = frappe.get_doc("Sales Invoice", sales_invoice)
            if si.meta.has_field("bns_purchase_receipt_reference") and si.get("bns_purchase_receipt_reference") == purchase_receipt:
                si.db_set("bns_purchase_receipt_reference", "", update_modified=False)
            frappe.clear_cache(doctype="Sales Invoice")

        logger.info(f"Unlinked Sales Invoice {sales_invoice} from Purchase Receipt {purchase_receipt}")
        _audit_unlink_action(
            "unlink_si_pr_completed",
            {"sales_invoice": sales_invoice, "purchase_receipt": purchase_receipt},
        )
        return {
            "success": True,
            "message": _("Sales Invoice and Purchase Receipt unlinked successfully")
        }
    except Exception as e:
        logger.error(f"Error unlinking SI-PR: {str(e)}")
        frappe.throw(str(e))


@frappe.whitelist()
def link_si_pi(sales_invoice: str, purchase_invoice: str) -> Dict:
    """
    Link a Sales Invoice with a Purchase Invoice for BNS Internal transfer.
    
    Args:
        sales_invoice (str): Sales Invoice name
        purchase_invoice (str): Purchase Invoice name
        
    Returns:
        Dict: Result with success message
    """
    _bns_require_doctype_write("Sales Invoice")
    _bns_require_doctype_write("Purchase Invoice")
    try:
        si = frappe.get_doc("Sales Invoice", sales_invoice, for_update=True)
        pi = frappe.get_doc("Purchase Invoice", purchase_invoice, for_update=True)

        if si.docstatus != 1:
            raise BNSValidationError(_("Sales Invoice must be submitted before linking"))
        if pi.docstatus != 1:
            raise BNSValidationError(_("Purchase Invoice must be submitted before linking"))

        if not is_after_internal_transfer_cutoff(si.get("posting_date")):
            frappe.throw(
                _("Cannot link: Sales Invoice {0} is before the Internal Transfer Cutoff.").format(sales_invoice),
                title=_("Cutoff Date Restriction"),
            )
        
        # Validate PI's bill_no matches SI name (only if bill_no is set)
        # Allow linking even if bill_no is empty or doesn't match
        if pi.bill_no and pi.bill_no != si.name:
            logger.warning(f"Purchase Invoice {purchase_invoice} has bill_no {pi.bill_no} but linking to {sales_invoice}")
            # Don't raise error - allow manual linking
        
        # Validate customer is BNS internal
        customer_internal = frappe.db.get_value("Customer", si.customer, "is_bns_internal_customer")
        if not customer_internal:
            raise BNSValidationError(_("Customer {0} is not marked as BNS Internal Customer").format(si.customer))
        
        # Validate supplier is BNS internal
        supplier_internal = frappe.db.get_value("Supplier", pi.supplier, "is_bns_internal_supplier")
        if not supplier_internal:
            raise BNSValidationError(_("Supplier {0} is not marked as BNS Internal Supplier").format(pi.supplier))
        
        # Validate inter-company party relationships using centralized function
        # This validates both directions: SI customer represents PI company, and PI supplier represents SI company
        validate_inter_company_party("Sales Invoice", si.customer, si.company, inter_company_reference=pi.name)
        
        # Check if already linked
        if si.get("bns_inter_company_reference") == pi.name and pi.get("bns_inter_company_reference") == si.name:
            frappe.msgprint(_("Sales Invoice and Purchase Invoice are already linked"))
            return {"success": True, "message": _("Already linked")}
        
        # Check if SI is already linked to another PI — clear stale links
        si_existing = (si.get("bns_inter_company_reference") or "").strip()
        if si_existing and si_existing != pi.name:
            stale = _is_stale_inter_company_ref("Sales Invoice", si.name, si_existing)
            if stale:
                logger.info("Clearing stale ref %s on SI %s (reason: %s)", si_existing, si.name, stale)
                si.db_set("bns_inter_company_reference", "", update_modified=False)
                si.bns_inter_company_reference = ""
            else:
                raise BNSValidationError(
                    _("Sales Invoice {0} is already linked to Purchase Invoice {1}").format(
                        sales_invoice, si_existing
                    )
                )

        # Check if PI is already linked to another SI — clear stale links
        pi_existing = (pi.get("bns_inter_company_reference") or "").strip()
        if pi_existing and pi_existing != si.name:
            stale = _is_stale_inter_company_ref("Purchase Invoice", pi.name, pi_existing)
            if stale:
                logger.info("Clearing stale ref %s on PI %s (reason: %s)", pi_existing, pi.name, stale)
                pi.db_set("bns_inter_company_reference", "", update_modified=False)
                pi.bns_inter_company_reference = ""
            else:
                raise BNSValidationError(
                    _("Purchase Invoice {0} is already linked to Sales Invoice {1}").format(
                        purchase_invoice, pi_existing
                    )
                )
        
        # Validate items match
        items_validation = validate_si_pi_items_match(sales_invoice, purchase_invoice)
        if not items_validation.get("match"):
            missing = items_validation.get("missing_items", [])
            qty_mismatches = items_validation.get("qty_mismatches", [])
            errors = []
            if missing:
                for item in missing[:3]:
                    errors.append(_("Item {0}: SI has {1}, PI missing").format(item["item_code"], item["si_qty"]))
            if qty_mismatches:
                for item in qty_mismatches[:3]:
                    errors.append(_("Item {0}: SI has {1}, PI has {2}").format(item["item_code"], item["si_qty"], item["pi_qty"]))
            if len(missing) > 3 or len(qty_mismatches) > 3:
                errors.append(_("... and more items"))
            raise BNSValidationError(_("Items do not match: {0}").format("; ".join(errors)))
        
        # Set bidirectional references
        si.db_set("bns_inter_company_reference", pi.name, update_modified=False)
        pi.db_set("bns_inter_company_reference", si.name, update_modified=False)
        
        # Set item-wise references for PI items (match by item_code + qty)
        _match_and_set_item_references(si, pi)

        # Update status and flags if not already set
        if not si.get("is_bns_internal_customer"):
            si.db_set("is_bns_internal_customer", 1, update_modified=False)
        if si.status != "BNS Internally Transferred":
            si.db_set("status", "BNS Internally Transferred", update_modified=False)
        
        if not pi.get("is_bns_internal_supplier"):
            pi.db_set("is_bns_internal_supplier", 1, update_modified=False)
        if pi.status != "BNS Internally Transferred":
            pi.db_set("status", "BNS Internally Transferred", update_modified=False)
        
        # Clear cache
        frappe.clear_cache(doctype="Sales Invoice")
        frappe.clear_cache(doctype="Purchase Invoice")
        
        logger.info(f"Linked Sales Invoice {sales_invoice} with Purchase Invoice {purchase_invoice}")
        
        return {
            "success": True,
            "message": _("Sales Invoice and Purchase Invoice linked successfully")
        }
        
    except Exception as e:
        logger.error(f"Error linking SI-PI: {str(e)}")
        frappe.throw(str(e))


@frappe.whitelist()
def unlink_si_pi(sales_invoice: str = None, purchase_invoice: str = None) -> Dict:
    """
    Unlink a Sales Invoice and Purchase Invoice.
    
    This function allows unlinking from either side, even if the other side
    doesn't have the reference set. It will clear references on both sides
    if they exist, but won't fail if one side is missing.
    
    Args:
        sales_invoice (str): Sales Invoice name (optional if purchase_invoice provided)
        purchase_invoice (str): Purchase Invoice name (optional if sales_invoice provided)
        
    Returns:
        Dict: Result with success message
    """
    _bns_require_accounts_read()
    try:
        _enforce_unlink_recovery_permission("unlink_si_pi")
        _audit_unlink_action(
            "unlink_si_pi_requested",
            {"sales_invoice": sales_invoice, "purchase_invoice": purchase_invoice},
        )

        if not sales_invoice and not purchase_invoice:
            raise BNSValidationError(_("Either sales_invoice or purchase_invoice must be provided"))
        
        # If only one is provided, get the other from the reference
        if sales_invoice and not purchase_invoice:
            si = frappe.get_doc("Sales Invoice", sales_invoice)
            purchase_invoice = si.get("bns_inter_company_reference")
            if not purchase_invoice:
                # SI doesn't have reference, but still allow clearing if needed
                si.db_set("bns_inter_company_reference", "", update_modified=False)
                frappe.clear_cache(doctype="Sales Invoice")
                logger.info(f"Cleared reference from Sales Invoice {sales_invoice} (no PI reference found)")
                return {
                    "success": True,
                    "message": _("Cleared reference from Sales Invoice")
                }
        
        if purchase_invoice and not sales_invoice:
            pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
            sales_invoice = pi.get("bns_inter_company_reference")
            if not sales_invoice:
                # PI doesn't have reference, but still allow clearing if needed
                pi.db_set("bns_inter_company_reference", "", update_modified=False)
                frappe.clear_cache(doctype="Purchase Invoice")
                logger.info(f"Cleared reference from Purchase Invoice {purchase_invoice} (no SI reference found)")
                return {
                    "success": True,
                    "message": _("Cleared reference from Purchase Invoice")
                }
        
        # Clear each side independently — the contra document may have been
        # cancelled or deleted, so we must not crash when it is missing.
        si_cleared = False
        pi_cleared = False
        
        if sales_invoice:
            if frappe.db.exists("Sales Invoice", sales_invoice):
                si = frappe.get_doc("Sales Invoice", sales_invoice)
                if si.get("bns_inter_company_reference"):
                    si.db_set("bns_inter_company_reference", "", update_modified=False)
                si.db_set("is_bns_internal_customer", 0, update_modified=False)
                si_status = "Unpaid" if flt(si.get("outstanding_amount")) > 0 else "Paid"
                si.db_set("status", si_status, update_modified=False)
                si_cleared = True
            else:
                logger.warning(f"Sales Invoice {sales_invoice} does not exist — skipping its side of unlink")

        if purchase_invoice:
            if frappe.db.exists("Purchase Invoice", purchase_invoice):
                pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
                if pi.get("bns_inter_company_reference"):
                    pi.db_set("bns_inter_company_reference", "", update_modified=False)
                for pi_item in pi.items:
                    if pi_item.get("sales_invoice_item"):
                        pi_item.db_set("sales_invoice_item", "", update_modified=False)
                pi.db_set("is_bns_internal_supplier", 0, update_modified=False)
                pi_status = "Unpaid" if flt(pi.get("outstanding_amount")) > 0 else "Paid"
                pi.db_set("status", pi_status, update_modified=False)
                pi_cleared = True
            else:
                logger.warning(f"Purchase Invoice {purchase_invoice} does not exist — skipping its side of unlink")
        
        # Clear cache for whichever sides were touched
        if si_cleared:
            frappe.clear_cache(doctype="Sales Invoice")
        if pi_cleared:
            frappe.clear_cache(doctype="Purchase Invoice")
        
        logger.info(f"Unlinked Sales Invoice {sales_invoice} from Purchase Invoice {purchase_invoice}")
        _audit_unlink_action(
            "unlink_si_pi_completed",
            {"sales_invoice": sales_invoice, "purchase_invoice": purchase_invoice},
        )
        
        return {
            "success": True,
            "message": _("Sales Invoice and Purchase Invoice unlinked successfully")
        }
        
    except Exception as e:
        logger.error(f"Error unlinking SI-PI: {str(e)}")
        frappe.throw(str(e))


def _eligible_internal_dn_names(internal_customers: List[str]) -> Set[str]:
    """Return submitted Delivery Notes that belong to an internal customer and
    are eligible for BNS conversion. Used to decide which Purchase
    Receipts are eligible for BNS conversion — PR eligibility is independent
    of the caller's posting-date window, because a PR in the window may
    reference a DN outside it (e.g. month-end GR crossing FY boundary).

    Eligibility rules:
      - Same-GSTIN DN: always eligible.
      - Diff-GSTIN DN: eligible only when the DN carries the per-document
        ``bns_allow_diff_gstin_dn_pr`` opt-in flag.
    """
    if not internal_customers:
        return set()
    rows = frappe.get_all(
        "Delivery Note",
        filters=[
            ["docstatus", "=", 1],
            ["customer", "in", internal_customers],
        ],
        fields=[
            "name", "billing_address_gstin", "company_gstin",
            "bns_allow_diff_gstin_dn_pr",
        ],
        limit_page_length=0,
    )
    eligible: Set[str] = set()
    for r in rows:
        billing = (r.get("billing_address_gstin") or "").strip()
        company = (r.get("company_gstin") or "").strip()
        if not billing or not company:
            continue
        if billing == company:
            eligible.add(r.name)
            continue
        if cint(r.get("bns_allow_diff_gstin_dn_pr")):
            eligible.add(r.name)
    return eligible


@frappe.whitelist()
def get_bulk_conversion_preview(from_date: str, to_date: str = None, force: int = 0) -> Dict:
    """
    Get preview of documents that can be bulk converted to BNS Internal.

    Args:
        from_date (str): Date filter (YYYY-MM-DD)
        to_date (str): Upper date bound (YYYY-MM-DD). Defaults to end of the
            fiscal year containing from_date to prevent cross-FY modifications.
        force (int): If 1, include documents even if flag is already set

    Returns:
        Dict: Counts of documents that can be converted
    """
    for _dt in ("Sales Invoice", "Purchase Invoice", "Delivery Note", "Purchase Receipt"):
        _bns_require_doctype_read(_dt)
    try:
        from_date_obj = frappe.utils.getdate(from_date)
        if to_date:
            to_date_obj = frappe.utils.getdate(to_date)
        else:
            to_date_obj = get_fiscal_year(from_date_obj)[2]

        internal_customers = frappe.get_all(
            "Customer", filters={"is_bns_internal_customer": 1}, pluck="name"
        )
        internal_suppliers = frappe.get_all(
            "Supplier", filters={"is_bns_internal_supplier": 1}, pluck="name"
        )

        # Get counts for Sales Invoice
        si_count = 0
        if internal_customers:
            si_list = frappe.get_all(
                "Sales Invoice",
                filters=[
                    ["docstatus", "=", 1],
                    ["posting_date", ">=", from_date_obj],
                    ["posting_date", "<=", to_date_obj],
                    ["customer", "in", internal_customers],
                ],
                fields=["name", "is_bns_internal_customer", "status"],
                limit_page_length=0,
            )
            for si in si_list:
                if force or not si.get("is_bns_internal_customer") or si.status != "BNS Internally Transferred":
                    si_count += 1

        # Get counts for Purchase Invoice
        pi_count = 0
        if internal_suppliers:
            pi_list = frappe.get_all(
                "Purchase Invoice",
                filters=[
                    ["docstatus", "=", 1],
                    ["posting_date", ">=", from_date_obj],
                    ["posting_date", "<=", to_date_obj],
                    ["supplier", "in", internal_suppliers],
                ],
                fields=["name", "is_bns_internal_supplier", "status"],
                limit_page_length=0,
            )
            for pi in pi_list:
                if force or not pi.get("is_bns_internal_supplier") or pi.status != "BNS Internally Transferred":
                    pi_count += 1

        # Get counts for Delivery Note (same GSTIN only, within date window).
        dn_count = 0
        if internal_customers:
            dn_list = frappe.get_all(
                "Delivery Note",
                filters=[
                    ["docstatus", "=", 1],
                    ["posting_date", ">=", from_date_obj],
                    ["posting_date", "<=", to_date_obj],
                    ["customer", "in", internal_customers],
                ],
                fields=["name", "is_bns_internal_customer", "status",
                        "billing_address_gstin", "company_gstin", "bns_inter_company_reference"],
                limit_page_length=0,
            )
            for dn in dn_list:
                billing_gstin = dn.get("billing_address_gstin")
                company_gstin = dn.get("company_gstin")
                if not (billing_gstin and company_gstin and billing_gstin == company_gstin):
                    continue
                dn_ref = (dn.get("bns_inter_company_reference") or "").strip()
                if (
                    force
                    or not dn.get("is_bns_internal_customer")
                    or dn.status != "BNS Internally Transferred"
                    or not dn_ref
                ):
                    dn_count += 1

        # Eligibility set for PR match: all internal-customer same-GSTIN DNs,
        # date-independent — a PR in the date window may reference a DN
        # outside the window (e.g. month-end GR crossing FY boundary).
        eligible_dn_names: Set[str] = _eligible_internal_dn_names(internal_customers)

        # Get counts for Purchase Receipt (linked to an eligible same-GSTIN DN)
        pr_count = 0
        if eligible_dn_names:
            pr_list = frappe.get_all(
                "Purchase Receipt",
                filters=[
                    ["docstatus", "=", 1],
                    ["posting_date", ">=", from_date_obj],
                    ["posting_date", "<=", to_date_obj],
                    ["supplier_delivery_note", "in", list(eligible_dn_names)],
                ],
                fields=["name", "is_bns_internal_supplier", "status"],
                limit_page_length=0,
            )
            for pr in pr_list:
                if force or not pr.get("is_bns_internal_supplier") or pr.status != "BNS Internally Transferred":
                    pr_count += 1
        
        total_count = si_count + pi_count + dn_count + pr_count
        
        return {
            "sales_invoice_count": si_count,
            "purchase_invoice_count": pi_count,
            "delivery_note_count": dn_count,
            "purchase_receipt_count": pr_count,
            "total_count": total_count
        }
        
    except Exception as e:
        logger.error(f"Error getting bulk conversion preview: {str(e)}")
        frappe.throw(_("Error getting preview: {0}").format(str(e)))


@frappe.whitelist()
def bulk_convert_to_bns_internal(from_date: str, to_date: str = None, force: int = 0) -> Dict:
    """
    Bulk convert documents to BNS Internally Transferred status.

    Args:
        from_date (str): Date filter (YYYY-MM-DD)
        to_date (str): Upper date bound (YYYY-MM-DD). Defaults to end of the
            fiscal year containing from_date to prevent cross-FY modifications.
        force (int): If 1, update even if flag is already set

    Returns:
        Dict: Results with counts of converted documents
    """
    for _dt in ("Sales Invoice", "Purchase Invoice", "Delivery Note", "Purchase Receipt"):
        _bns_require_doctype_write(_dt)
    try:
        from_date_obj = frappe.utils.getdate(from_date)
        if to_date:
            to_date_obj = frappe.utils.getdate(to_date)
        else:
            to_date_obj = get_fiscal_year(from_date_obj)[2]

        if force and to_date_obj > get_fiscal_year(from_date_obj)[2]:
            logger.warning(
                "bulk_convert_to_bns_internal: force=1 with date range %s to %s spans "
                "multiple fiscal years — documents will be stamped with current settings",
                from_date_obj, to_date_obj,
            )

        converted = {
            "sales_invoice": 0,
            "purchase_invoice": 0,
            "delivery_note": 0,
            "purchase_receipt": 0
        }

        internal_customers = frappe.get_all(
            "Customer", filters={"is_bns_internal_customer": 1}, pluck="name"
        )
        internal_suppliers = frappe.get_all(
            "Supplier", filters={"is_bns_internal_supplier": 1}, pluck="name"
        )

        # Convert Sales Invoices
        if internal_customers:
            si_list = frappe.get_all(
                "Sales Invoice",
                filters=[
                    ["docstatus", "=", 1],
                    ["posting_date", ">=", from_date_obj],
                    ["posting_date", "<=", to_date_obj],
                    ["customer", "in", internal_customers],
                ],
                fields=["name", "is_bns_internal_customer", "status"],
                limit_page_length=0,
            )
            for si in si_list:
                if force or not si.get("is_bns_internal_customer") or si.status != "BNS Internally Transferred":
                    try:
                        convert_sales_invoice_to_bns_internal(si.name, None)
                        converted["sales_invoice"] += 1
                    except Exception as e:
                        logger.error(f"Error converting Sales Invoice {si.name}: {str(e)}")
                        continue

        # Convert Purchase Invoices
        if internal_suppliers:
            pi_list = frappe.get_all(
                "Purchase Invoice",
                filters=[
                    ["docstatus", "=", 1],
                    ["posting_date", ">=", from_date_obj],
                    ["posting_date", "<=", to_date_obj],
                    ["supplier", "in", internal_suppliers],
                ],
                fields=["name", "is_bns_internal_supplier", "status"],
                limit_page_length=0,
            )
            for pi in pi_list:
                if force or not pi.get("is_bns_internal_supplier") or pi.status != "BNS Internally Transferred":
                    try:
                        convert_purchase_invoice_to_bns_internal(pi.name, None)
                        converted["purchase_invoice"] += 1
                    except Exception as e:
                        logger.error(f"Error converting Purchase Invoice {pi.name}: {str(e)}")
                        continue

        # Convert Delivery Notes (same GSTIN only, within date window)
        if internal_customers:
            dn_list = frappe.get_all(
                "Delivery Note",
                filters=[
                    ["docstatus", "=", 1],
                    ["posting_date", ">=", from_date_obj],
                    ["posting_date", "<=", to_date_obj],
                    ["customer", "in", internal_customers],
                ],
                fields=["name", "is_bns_internal_customer", "status",
                        "billing_address_gstin", "company_gstin", "bns_inter_company_reference"],
                limit_page_length=0,
            )
            for dn in dn_list:
                billing_gstin = dn.get("billing_address_gstin")
                company_gstin = dn.get("company_gstin")
                if not (billing_gstin and company_gstin and billing_gstin == company_gstin):
                    continue
                dn_ref = (dn.get("bns_inter_company_reference") or "").strip()
                needs_convert = (
                    force
                    or not dn.get("is_bns_internal_customer")
                    or dn.status != "BNS Internally Transferred"
                    or not dn_ref
                )
                if needs_convert:
                    try:
                        result = convert_delivery_note_to_bns_internal(dn.name, None)
                        if result.get("success"):
                            converted["delivery_note"] += 1
                    except Exception as e:
                        logger.error(f"Error converting Delivery Note {dn.name}: {str(e)}")
                        frappe.log_error(f"Error converting Delivery Note {dn.name}: {str(e)}", "BNS Bulk Conversion")
                        continue

        # Eligibility set for PR match: all internal-customer same-GSTIN DNs,
        # date-independent — a PR in the date window may reference a DN
        # outside the window (e.g. month-end GR crossing FY boundary).
        eligible_dn_names: Set[str] = _eligible_internal_dn_names(internal_customers)

        # Convert Purchase Receipts (linked to an eligible same-GSTIN DN)
        if eligible_dn_names:
            pr_list = frappe.get_all(
                "Purchase Receipt",
                filters=[
                    ["docstatus", "=", 1],
                    ["posting_date", ">=", from_date_obj],
                    ["posting_date", "<=", to_date_obj],
                    ["supplier_delivery_note", "in", list(eligible_dn_names)],
                ],
                fields=["name", "is_bns_internal_supplier", "status"],
                limit_page_length=0,
            )
            for pr in pr_list:
                if force or not pr.get("is_bns_internal_supplier") or pr.status != "BNS Internally Transferred":
                    try:
                        convert_purchase_receipt_to_bns_internal(pr.name, None)
                        converted["purchase_receipt"] += 1
                    except Exception as e:
                        logger.error(f"Error converting Purchase Receipt {pr.name}: {str(e)}")
                        continue
        
        total_converted = converted["sales_invoice"] + converted["purchase_invoice"] + converted["delivery_note"] + converted["purchase_receipt"]
        
        return {
            "success": True,
            "total_converted": total_converted,
            "details": converted,
            "message": _("Converted {0} Sales Invoice(s), {1} Purchase Invoice(s), {2} Delivery Note(s), {3} Purchase Receipt(s)").format(
                converted["sales_invoice"],
                converted["purchase_invoice"],
                converted["delivery_note"],
                converted["purchase_receipt"]
            )
        }
        
    except Exception as e:
        logger.error(f"Error in bulk conversion: {str(e)}")
        frappe.throw(_("Error in bulk conversion: {0}").format(str(e)))


def _match_and_set_dn_pr_item_references(dn, pr) -> int:
    """
    Match DN items to PR items by item_code + qty and set delivery_note_item on PR items.
    Returns the number of PR items updated.
    """
    dn_item_map = defaultdict(list)
    for dn_item in dn.items:
        dn_item_map[dn_item.item_code].append({
            "name": dn_item.name,
            "qty": flt(dn_item.qty or 0),
            "stock_qty": flt(dn_item.stock_qty or dn_item.qty or 0),
            "remaining_qty": flt(dn_item.qty or 0),
            "remaining_stock_qty": flt(dn_item.stock_qty or dn_item.qty or 0),
        })

    count = 0
    for pr_item in pr.items:
        item_code = pr_item.item_code
        pr_qty = flt(pr_item.qty or 0)
        pr_stock_qty = flt(pr_item.stock_qty or pr_qty)

        if item_code not in dn_item_map or not dn_item_map[item_code]:
            continue

        matched = False
        for dn_item_data in dn_item_map[item_code]:
            if dn_item_data["remaining_qty"] <= 0:
                continue
            if pr_stock_qty > 0 and dn_item_data["remaining_stock_qty"] > 0:
                if abs(pr_stock_qty - dn_item_data["remaining_stock_qty"]) < 0.001:
                    pr_item.db_set("delivery_note_item", dn_item_data["name"], update_modified=False)
                    dn_item_data["remaining_qty"] = 0
                    dn_item_data["remaining_stock_qty"] = 0
                    matched = True
                    count += 1
                    break
            elif abs(pr_qty - dn_item_data["remaining_qty"]) < 0.001:
                pr_item.db_set("delivery_note_item", dn_item_data["name"], update_modified=False)
                dn_item_data["remaining_qty"] = 0
                dn_item_data["remaining_stock_qty"] = 0
                matched = True
                count += 1
                break

        if not matched:
            for dn_item_data in dn_item_map[item_code]:
                if dn_item_data["remaining_qty"] > 0:
                    pr_item.db_set("delivery_note_item", dn_item_data["name"], update_modified=False)
                    if pr_stock_qty > 0 and dn_item_data["remaining_stock_qty"] > 0:
                        dn_item_data["remaining_stock_qty"] -= pr_stock_qty
                    else:
                        dn_item_data["remaining_qty"] -= pr_qty
                    count += 1
                    break
    return count


@frappe.whitelist()
def backfill_item_references(from_date: str) -> Dict:
    """
    Backfill sales_invoice_item on Purchase Invoice items and delivery_note_item on
    Purchase Receipt items for BNS internal transfers from a given date.
    Callable via bench console or one-time from BNS Settings.
    Returns a summary with counts of documents and items fixed.
    """
    _bns_require_accounts_write()
    from_date = frappe.utils.getdate(from_date)
    pi_docs_fixed = 0
    pi_items_fixed = 0
    pr_docs_fixed = 0
    pr_items_fixed = 0

    # SI-PI: PIs with is_bns_internal_supplier=1, posting_date >= from_date
    pi_list = frappe.get_all(
        "Purchase Invoice",
        filters={
            "is_bns_internal_supplier": 1,
            "docstatus": 1,
            "posting_date": [">=", from_date],
        },
        pluck="name",
    )
    for pi_name in pi_list:
        pi = frappe.get_doc("Purchase Invoice", pi_name)
        si_name = pi.get("bns_inter_company_reference")
        if not si_name or not frappe.db.exists("Sales Invoice", si_name):
            continue
        has_empty = any(not (pi_item.get("sales_invoice_item") or "").strip() for pi_item in pi.items)
        if not has_empty:
            continue
        si = frappe.get_doc("Sales Invoice", si_name)
        n = _match_and_set_item_references(si, pi)
        if n > 0:
            pi_docs_fixed += 1
            pi_items_fixed += n

    # DN-PR: PRs with is_bns_internal_supplier=1, posting_date >= from_date
    pr_list = frappe.get_all(
        "Purchase Receipt",
        filters={
            "is_bns_internal_supplier": 1,
            "docstatus": 1,
            "posting_date": [">=", from_date],
        },
        pluck="name",
    )
    for pr_name in pr_list:
        pr = frappe.get_doc("Purchase Receipt", pr_name)
        dn_name = pr.get("bns_inter_company_reference")
        if not dn_name or not frappe.db.exists("Delivery Note", dn_name):
            continue
        has_empty = any(not (pr_item.get("delivery_note_item") or "").strip() for pr_item in pr.items)
        if not has_empty:
            continue
        dn = frappe.get_doc("Delivery Note", dn_name)
        n = _match_and_set_dn_pr_item_references(dn, pr)
        if n > 0:
            pr_docs_fixed += 1
            pr_items_fixed += n

    return {
        "success": True,
        "purchase_invoice_docs_fixed": pi_docs_fixed,
        "purchase_invoice_items_fixed": pi_items_fixed,
        "purchase_receipt_docs_fixed": pr_docs_fixed,
        "purchase_receipt_items_fixed": pr_items_fixed,
        "message": _(
            "Backfill complete: {0} Purchase Invoice(s) ({1} items), {2} Purchase Receipt(s) ({3} items)."
        ).format(pi_docs_fixed, pi_items_fixed, pr_docs_fixed, pr_items_fixed),
    }


# ---------------------------------------------------------------------------
# Bulk Linkage Verification & Repost
# ---------------------------------------------------------------------------

def _qtys_equal_bulk(a, b):
    """Compare quantities with no tolerance; round to 6 decimals."""
    return round(flt(a or 0), 6) == round(flt(b or 0), 6)


def _verify_dn_pr_item_linkage(dn_name: str, pr_name: str) -> Dict[str, Any]:
    """
    Verify item-level linkage between DN and PR (same GSTIN).

    First attempts matching via delivery_note_item references. When all items
    are unlinked (common after DN amendment where IDs change), falls back to
    matching by item_code + qty so amended docs aren't falsely flagged.

    Args:
        dn_name: Delivery Note name
        pr_name: Purchase Receipt name

    Returns:
        Dict with keys: linked (bool), missing_items (list), qty_mismatches (list), item_mismatches (list)
    """
    dn_items = frappe.get_all(
        "Delivery Note Item",
        filters={"parent": dn_name},
        fields=["name", "item_code", "qty", "stock_qty"],
    )
    pr_items = frappe.get_all(
        "Purchase Receipt Item",
        filters={"parent": pr_name},
        fields=["name", "item_code", "qty", "stock_qty", "delivery_note_item"],
    )

    pr_by_dn_item = {}
    for pri in pr_items:
        dni_ref = (pri.get("delivery_note_item") or "").strip()
        if dni_ref:
            pr_by_dn_item.setdefault(dni_ref, []).append(pri)

    dn_item_ids = {d.name for d in dn_items}
    refs_valid = any(ref in dn_item_ids for ref in pr_by_dn_item)

    if refs_valid:
        missing_items = []
        qty_mismatches = []
        item_mismatches = []

        for dni in dn_items:
            linked_prs = pr_by_dn_item.get(dni.name, [])
            if not linked_prs:
                missing_items.append({"item_code": dni.item_code, "dn_item": dni.name})
                continue
            total_pr_qty = sum(flt(p.get("stock_qty") or p.get("qty") or 0) for p in linked_prs)
            dn_qty = flt(dni.stock_qty or dni.qty or 0)
            if not _qtys_equal_bulk(dn_qty, total_pr_qty):
                qty_mismatches.append({
                    "item_code": dni.item_code, "dn_qty": dn_qty, "pr_qty": total_pr_qty,
                })
            for pri in linked_prs:
                if (pri.item_code or "") != (dni.item_code or ""):
                    item_mismatches.append({
                        "dn_item_code": dni.item_code, "pr_item_code": pri.item_code,
                        "dn_item": dni.name, "pr_item": pri.name,
                    })

        fully_linked = not missing_items and not qty_mismatches and not item_mismatches
        return {
            "linked": fully_linked,
            "missing_items": missing_items,
            "qty_mismatches": qty_mismatches,
            "item_mismatches": item_mismatches,
        }

    # Fallback: refs are stale (e.g. DN was amended). Match by item_code + qty.
    dn_agg: Dict[str, float] = {}
    for d in dn_items:
        dn_agg[d.item_code] = dn_agg.get(d.item_code, 0) + flt(d.stock_qty or d.qty or 0)
    pr_agg: Dict[str, float] = {}
    for p in pr_items:
        pr_agg[p.item_code] = pr_agg.get(p.item_code, 0) + flt(p.stock_qty or p.qty or 0)

    missing_items = []
    qty_mismatches = []
    item_mismatches = []

    for code, dn_qty in dn_agg.items():
        if code not in pr_agg:
            missing_items.append({"item_code": code, "dn_item": "aggregate"})
        elif not _qtys_equal_bulk(dn_qty, pr_agg[code]):
            qty_mismatches.append({"item_code": code, "dn_qty": dn_qty, "pr_qty": pr_agg[code]})
    for code in pr_agg:
        if code not in dn_agg:
            item_mismatches.append({"dn_item_code": "", "pr_item_code": code, "dn_item": "", "pr_item": "aggregate"})

    fully_linked = not missing_items and not qty_mismatches and not item_mismatches
    return {
        "linked": fully_linked,
        "missing_items": missing_items,
        "qty_mismatches": qty_mismatches,
        "item_mismatches": item_mismatches,
    }


def _verify_si_pi_item_linkage(si_name: str, pi_name: str) -> Dict[str, Any]:
    """
    Verify item-level linkage between SI and PI (different GSTIN).

    Returns:
        Dict with keys: linked (bool), missing_items, qty_mismatches, item_mismatches
    """
    si_items = frappe.get_all(
        "Sales Invoice Item",
        filters={"parent": si_name},
        fields=["name", "item_code", "qty", "stock_qty"],
    )
    pi_items = frappe.get_all(
        "Purchase Invoice Item",
        filters={"parent": pi_name},
        fields=["name", "item_code", "qty", "stock_qty", "sales_invoice_item"],
    )

    pi_by_si_item = {}
    for pii in pi_items:
        si_ref = (pii.get("sales_invoice_item") or "").strip()
        if si_ref:
            pi_by_si_item.setdefault(si_ref, []).append(pii)

    missing_items = []
    qty_mismatches = []
    item_mismatches = []

    for sii in si_items:
        linked_pis = pi_by_si_item.get(sii.name, [])
        if not linked_pis:
            missing_items.append({"item_code": sii.item_code, "si_item": sii.name})
            continue
        total_pi_qty = sum(flt(p.get("stock_qty") or p.get("qty") or 0) for p in linked_pis)
        si_qty = flt(sii.stock_qty or sii.qty or 0)
        if not _qtys_equal_bulk(si_qty, total_pi_qty):
            qty_mismatches.append({
                "item_code": sii.item_code, "si_qty": si_qty, "pi_qty": total_pi_qty,
            })
        for pii in linked_pis:
            if (pii.item_code or "") != (sii.item_code or ""):
                item_mismatches.append({
                    "si_item_code": sii.item_code, "pi_item_code": pii.item_code,
                    "si_item": sii.name, "pi_item": pii.name,
                })

    fully_linked = not missing_items and not qty_mismatches and not item_mismatches
    return {
        "linked": fully_linked,
        "missing_items": missing_items,
        "qty_mismatches": qty_mismatches,
        "item_mismatches": item_mismatches,
    }


def _verify_si_pr_item_linkage(si_name: str, pr_name: str) -> Dict[str, Any]:
    """
    Verify item-level linkage between SI and PR (SI->PR flow).

    PR items reference SI via sales_invoice_item or item_code+qty matching.
    """
    si_items = frappe.get_all(
        "Sales Invoice Item",
        filters={"parent": si_name},
        fields=["name", "item_code", "qty", "stock_qty"],
    )
    pr_items = frappe.get_all(
        "Purchase Receipt Item",
        filters={"parent": pr_name},
        fields=["name", "item_code", "qty", "stock_qty", "sales_invoice_item"],
    )

    pr_meta = frappe.get_meta("Purchase Receipt Item")
    has_si_item_field = pr_meta.has_field("sales_invoice_item")

    pr_by_si_item = {}
    unlinked_pr_items = []
    if has_si_item_field:
        for pri in pr_items:
            si_ref = (pri.get("sales_invoice_item") or "").strip()
            if si_ref:
                pr_by_si_item.setdefault(si_ref, []).append(pri)
            else:
                unlinked_pr_items.append(pri)
    else:
        unlinked_pr_items = list(pr_items)

    missing_items = []
    qty_mismatches = []
    item_mismatches = []

    si_agg = defaultdict(float)
    for sii in si_items:
        si_agg[sii.item_code] += flt(sii.stock_qty or sii.qty or 0)

    pr_agg = defaultdict(float)
    for pri in pr_items:
        pr_agg[pri.item_code] += flt(pri.stock_qty or pri.qty or 0)

    for item_code, si_qty in si_agg.items():
        pr_qty = pr_agg.get(item_code, 0)
        if not _qtys_equal_bulk(si_qty, pr_qty):
            if pr_qty == 0:
                missing_items.append({"item_code": item_code})
            else:
                qty_mismatches.append({"item_code": item_code, "si_qty": si_qty, "pr_qty": pr_qty})

    for item_code in pr_agg:
        if item_code not in si_agg:
            item_mismatches.append({"si_item_code": None, "pr_item_code": item_code})

    fully_linked = not missing_items and not qty_mismatches and not item_mismatches
    return {
        "linked": fully_linked,
        "missing_items": missing_items,
        "qty_mismatches": qty_mismatches,
        "item_mismatches": item_mismatches,
    }


def _verify_pr_pi_item_linkage(pr_name: str, pi_name: str) -> Dict[str, Any]:
    """
    Verify item-level linkage between PR and PI (PR->PI flow).

    PI items reference PR via purchase_receipt + pr_detail.
    """
    pr_items = frappe.get_all(
        "Purchase Receipt Item",
        filters={"parent": pr_name},
        fields=["name", "item_code", "qty", "stock_qty"],
    )
    pi_items = frappe.get_all(
        "Purchase Invoice Item",
        filters={"parent": pi_name, "purchase_receipt": pr_name},
        fields=["name", "item_code", "qty", "stock_qty", "pr_detail"],
    )

    pr_agg = defaultdict(float)
    for pri in pr_items:
        pr_agg[pri.item_code] += flt(pri.stock_qty or pri.qty or 0)

    pi_agg = defaultdict(float)
    for pii in pi_items:
        pi_agg[pii.item_code] += flt(pii.stock_qty or pii.qty or 0)

    missing_items = []
    qty_mismatches = []
    item_mismatches = []

    for item_code, pr_qty in pr_agg.items():
        pi_qty = pi_agg.get(item_code, 0)
        if not _qtys_equal_bulk(pr_qty, pi_qty):
            if pi_qty == 0:
                missing_items.append({"item_code": item_code})
            else:
                qty_mismatches.append({"item_code": item_code, "pr_qty": pr_qty, "pi_qty": pi_qty})

    for item_code in pi_agg:
        if item_code not in pr_agg:
            item_mismatches.append({"pr_item_code": None, "pi_item_code": item_code})

    fully_linked = not missing_items and not qty_mismatches and not item_mismatches
    return {
        "linked": fully_linked,
        "missing_items": missing_items,
        "qty_mismatches": qty_mismatches,
        "item_mismatches": item_mismatches,
    }


def _verify_dn_si_item_linkage(dn_name: str, si_name: str) -> Dict[str, Any]:
    """
    Verify item-level linkage between DN and SI.

    SI items reference DN via delivery_note + dn_detail fields.
    """
    dn_items = frappe.get_all(
        "Delivery Note Item",
        filters={"parent": dn_name},
        fields=["name", "item_code", "qty", "stock_qty"],
    )
    si_items = frappe.get_all(
        "Sales Invoice Item",
        filters={"parent": si_name, "delivery_note": dn_name},
        fields=["name", "item_code", "qty", "stock_qty", "dn_detail"],
    )

    si_by_dn_detail = {}
    for sii in si_items:
        ref = (sii.get("dn_detail") or "").strip()
        if ref:
            si_by_dn_detail.setdefault(ref, []).append(sii)

    missing_items = []
    qty_mismatches = []
    item_mismatches = []

    for dni in dn_items:
        linked_sis = si_by_dn_detail.get(dni.name, [])
        if not linked_sis:
            missing_items.append({"item_code": dni.item_code, "dn_item": dni.name})
            continue
        total_si_qty = sum(flt(s.get("stock_qty") or s.get("qty") or 0) for s in linked_sis)
        dn_qty = flt(dni.stock_qty or dni.qty or 0)
        if not _qtys_equal_bulk(dn_qty, total_si_qty):
            qty_mismatches.append({
                "item_code": dni.item_code, "dn_qty": dn_qty, "si_qty": total_si_qty,
            })
        for sii in linked_sis:
            if (sii.item_code or "") != (dni.item_code or ""):
                item_mismatches.append({
                    "dn_item_code": dni.item_code, "si_item_code": sii.item_code,
                })

    fully_linked = not missing_items and not qty_mismatches and not item_mismatches
    return {
        "linked": fully_linked,
        "missing_items": missing_items,
        "qty_mismatches": qty_mismatches,
        "item_mismatches": item_mismatches,
    }


def _get_sis_from_dn(dn_name: str) -> List[str]:
    """Get submitted Sales Invoices created from a Delivery Note."""
    si_names = frappe.get_all(
        "Sales Invoice Item",
        filters={"delivery_note": dn_name, "docstatus": 1},
        pluck="parent",
    )
    return sorted(set(si_names))


def _detect_chain_type(doc_type: str, doc_name: str, doc: Dict) -> Dict[str, Any]:
    """
    Detect which internal transfer chain type a document belongs to.

    Args:
        doc_type: "Delivery Note" or "Sales Invoice"
        doc_name: Document name
        doc: Document dict with company_gstin, billing_address_gstin, etc.

    Returns:
        Dict with chain_type, docs dict keyed by role, and verification results.
    """
    company_gstin = (doc.get("company_gstin") or "").strip()
    billing_gstin = (doc.get("billing_address_gstin") or "").strip()
    same_gstin = company_gstin and billing_gstin and company_gstin == billing_gstin

    if doc_type == "Delivery Note":
        if same_gstin:
            # Chain 1: DN -> PR
            pr_names = _get_submitted_prs_for_dn(doc_name)
            if not pr_names:
                return {"chain_type": "DN->PR", "status": "unlinked", "docs": {"dn": doc_name}, "issues": ["No PR linked to DN"]}

            pr_name = pr_names[0]
            pr_ref = frappe.db.get_value("Purchase Receipt", pr_name, "bns_inter_company_reference")
            dn_ref = doc.get("bns_inter_company_reference") or ""

            issues = []
            if dn_ref != pr_name:
                issues.append(f"DN.bns_inter_company_reference ({dn_ref}) does not point to PR ({pr_name})")
            if pr_ref != doc_name:
                issues.append(f"PR.bns_inter_company_reference ({pr_ref}) does not point to DN ({doc_name})")

            item_check = _verify_dn_pr_item_linkage(doc_name, pr_name)
            if not item_check["linked"]:
                issues.extend(_format_item_issues("DN->PR", item_check))

            status = "fully_linked" if not issues else "partially_linked"
            return {
                "chain_type": "DN->PR",
                "status": status,
                "docs": {"dn": doc_name, "pr": pr_name},
                "issues": issues,
            }
        else:
            # Different GSTIN DN: look for SI made from this DN
            si_names = _get_sis_from_dn(doc_name)
            if not si_names:
                return {"chain_type": "DN->SI->?", "status": "unlinked", "docs": {"dn": doc_name}, "issues": ["No SI created from DN"]}

            si_name = si_names[0]
            issues = []

            dn_si_check = _verify_dn_si_item_linkage(doc_name, si_name)
            if not dn_si_check["linked"]:
                issues.extend(_format_item_issues("DN->SI", dn_si_check))

            si_data = frappe.db.get_value(
                "Sales Invoice", si_name,
                ["bns_inter_company_reference", "bns_purchase_receipt_reference"],
                as_dict=True,
            ) or {}

            si_pi_ref = (si_data.get("bns_inter_company_reference") or "").strip()
            si_pr_ref = (si_data.get("bns_purchase_receipt_reference") or "").strip()

            if si_pr_ref and frappe.db.exists("Purchase Receipt", si_pr_ref):
                # Chain 5: DN -> SI -> PR -> PI
                pr_name = si_pr_ref
                pr_data = frappe.db.get_value(
                    "Purchase Receipt", pr_name, "bns_inter_company_reference",
                )
                if (pr_data or "") != si_name:
                    issues.append(f"PR.bns_inter_company_reference ({pr_data}) does not point to SI ({si_name})")

                si_pr_check = _verify_si_pr_item_linkage(si_name, pr_name)
                if not si_pr_check["linked"]:
                    issues.extend(_format_item_issues("SI->PR", si_pr_check))

                pi_names = frappe.get_all(
                    "Purchase Invoice Item",
                    filters={"purchase_receipt": pr_name, "docstatus": 1},
                    pluck="parent",
                )
                pi_names = sorted(set(pi_names))

                if pi_names:
                    pi_name = pi_names[0]
                    pr_pi_check = _verify_pr_pi_item_linkage(pr_name, pi_name)
                    if not pr_pi_check["linked"]:
                        issues.extend(_format_item_issues("PR->PI", pr_pi_check))
                    status = "fully_linked" if not issues else "partially_linked"
                    return {
                        "chain_type": "DN->SI->PR->PI",
                        "status": status,
                        "docs": {"dn": doc_name, "si": si_name, "pr": pr_name, "pi": pi_name},
                        "issues": issues,
                    }
                else:
                    issues.append("No PI created from PR")
                    return {
                        "chain_type": "DN->SI->PR->PI",
                        "status": "partially_linked",
                        "docs": {"dn": doc_name, "si": si_name, "pr": pr_name},
                        "issues": issues,
                    }

            elif si_pi_ref and frappe.db.exists("Purchase Invoice", si_pi_ref):
                # Chain 4: DN -> SI -> PI
                pi_name = si_pi_ref
                pi_ref = frappe.db.get_value("Purchase Invoice", pi_name, "bns_inter_company_reference")
                if (pi_ref or "") != si_name:
                    issues.append(f"PI.bns_inter_company_reference ({pi_ref}) does not point to SI ({si_name})")

                si_pi_check = _verify_si_pi_item_linkage(si_name, pi_name)
                if not si_pi_check["linked"]:
                    issues.extend(_format_item_issues("SI->PI", si_pi_check))

                status = "fully_linked" if not issues else "partially_linked"
                return {
                    "chain_type": "DN->SI->PI",
                    "status": status,
                    "docs": {"dn": doc_name, "si": si_name, "pi": pi_name},
                    "issues": issues,
                }
            else:
                issues.append("SI has no PI or PR link")
                return {
                    "chain_type": "DN->SI->?",
                    "status": "partially_linked",
                    "docs": {"dn": doc_name, "si": si_name},
                    "issues": issues,
                }

    elif doc_type == "Sales Invoice":
        # Different GSTIN SI (not from DN -- DN-originated chains are handled above)
        si_items = frappe.get_all(
            "Sales Invoice Item",
            filters={"parent": doc_name},
            fields=["delivery_note"],
        )
        has_dn = any((sii.get("delivery_note") or "").strip() for sii in si_items)
        if has_dn:
            return None  # Will be handled via DN-originated chain detection

        si_pi_ref = (doc.get("bns_inter_company_reference") or "").strip()
        si_pr_ref = (doc.get("bns_purchase_receipt_reference") or "").strip() if hasattr(doc, "get") else ""

        if si_pr_ref and frappe.db.exists("Purchase Receipt", si_pr_ref):
            # Chain 3: SI -> PR -> PI
            pr_name = si_pr_ref
            issues = []

            pr_ref = frappe.db.get_value("Purchase Receipt", pr_name, "bns_inter_company_reference")
            if (pr_ref or "") != doc_name:
                issues.append(f"PR.bns_inter_company_reference ({pr_ref}) does not point to SI ({doc_name})")

            si_pr_check = _verify_si_pr_item_linkage(doc_name, pr_name)
            if not si_pr_check["linked"]:
                issues.extend(_format_item_issues("SI->PR", si_pr_check))

            pi_names = frappe.get_all(
                "Purchase Invoice Item",
                filters={"purchase_receipt": pr_name, "docstatus": 1},
                pluck="parent",
            )
            pi_names = sorted(set(pi_names))

            if pi_names:
                pi_name = pi_names[0]
                pr_pi_check = _verify_pr_pi_item_linkage(pr_name, pi_name)
                if not pr_pi_check["linked"]:
                    issues.extend(_format_item_issues("PR->PI", pr_pi_check))
                status = "fully_linked" if not issues else "partially_linked"
                return {
                    "chain_type": "SI->PR->PI",
                    "status": status,
                    "docs": {"si": doc_name, "pr": pr_name, "pi": pi_name},
                    "issues": issues,
                }
            else:
                issues.append("No PI created from PR")
                return {
                    "chain_type": "SI->PR->PI",
                    "status": "partially_linked",
                    "docs": {"si": doc_name, "pr": pr_name},
                    "issues": issues,
                }

        elif si_pi_ref and frappe.db.exists("Purchase Invoice", si_pi_ref):
            # Chain 2: SI -> PI (direct)
            pi_name = si_pi_ref
            issues = []

            pi_ref = frappe.db.get_value("Purchase Invoice", pi_name, "bns_inter_company_reference")
            if (pi_ref or "") != doc_name:
                issues.append(f"PI.bns_inter_company_reference ({pi_ref}) does not point to SI ({doc_name})")

            si_pi_check = _verify_si_pi_item_linkage(doc_name, pi_name)
            if not si_pi_check["linked"]:
                issues.extend(_format_item_issues("SI->PI", si_pi_check))

            status = "fully_linked" if not issues else "partially_linked"
            return {
                "chain_type": "SI->PI",
                "status": status,
                "docs": {"si": doc_name, "pi": pi_name},
                "issues": issues,
            }
        else:
            # Also check if PR links back via bns_inter_company_reference
            pr_names = _get_submitted_prs_for_si(doc_name)
            if pr_names:
                pr_name = pr_names[0]
                issues = []

                si_pr_check = _verify_si_pr_item_linkage(doc_name, pr_name)
                if not si_pr_check["linked"]:
                    issues.extend(_format_item_issues("SI->PR", si_pr_check))

                pi_names = frappe.get_all(
                    "Purchase Invoice Item",
                    filters={"purchase_receipt": pr_name, "docstatus": 1},
                    pluck="parent",
                )
                pi_names = sorted(set(pi_names))
                if pi_names:
                    pi_name = pi_names[0]
                    pr_pi_check = _verify_pr_pi_item_linkage(pr_name, pi_name)
                    if not pr_pi_check["linked"]:
                        issues.extend(_format_item_issues("PR->PI", pr_pi_check))
                    status = "fully_linked" if not issues else "partially_linked"
                    return {
                        "chain_type": "SI->PR->PI",
                        "status": status,
                        "docs": {"si": doc_name, "pr": pr_name, "pi": pi_name},
                        "issues": issues,
                    }
                else:
                    issues.append("No PI created from PR")
                    return {
                        "chain_type": "SI->PR->PI",
                        "status": "partially_linked",
                        "docs": {"si": doc_name, "pr": pr_name},
                        "issues": issues,
                    }

            # Check PI via bns_inter_company_reference pointing to this SI
            pi_name = frappe.db.get_value(
                "Purchase Invoice",
                {"bns_inter_company_reference": doc_name, "docstatus": 1},
                "name",
            )
            if pi_name:
                issues = []
                si_pi_check = _verify_si_pi_item_linkage(doc_name, pi_name)
                if not si_pi_check["linked"]:
                    issues.extend(_format_item_issues("SI->PI", si_pi_check))
                status = "fully_linked" if not issues else "partially_linked"
                return {
                    "chain_type": "SI->PI",
                    "status": status,
                    "docs": {"si": doc_name, "pi": pi_name},
                    "issues": issues,
                }

            return {
                "chain_type": "SI->?",
                "status": "unlinked",
                "docs": {"si": doc_name},
                "issues": ["No PI or PR linked to SI"],
            }

    return None


def _check_dn_pr_fixable(dn_name: str, pr_name: str) -> Dict[str, Any]:
    """
    Check whether a partially linked DN->PR pair can be auto-fixed.

    Skips (returns fixable=False) when any of these mismatches are found:
      - Item code mismatch (DN item not in PR or vice-versa)
      - Per-unit rate mismatch
      - Taxable amount mismatch
      - Location mismatch (DN target_warehouse vs PR warehouse)

    Args:
        dn_name: Delivery Note name
        pr_name: Purchase Receipt name

    Returns:
        Dict with fixable (bool) and skip_reasons (list of str).
    """
    dn_items = frappe.get_all(
        "Delivery Note Item",
        filters={"parent": dn_name},
        fields=["item_code", "qty", "rate", "amount", "warehouse", "target_warehouse"],
    )
    pr_items = frappe.get_all(
        "Purchase Receipt Item",
        filters={"parent": pr_name},
        fields=["item_code", "qty", "rate", "amount", "warehouse"],
    )

    skip_reasons: List[str] = []

    dn_agg: Dict[str, Dict] = {}
    for item in dn_items:
        code = item.item_code
        if code not in dn_agg:
            dn_agg[code] = {"qty": 0, "amount": 0, "target_warehouses": set()}
        dn_agg[code]["qty"] += flt(item.qty)
        dn_agg[code]["amount"] += flt(item.amount)
        tw = (item.target_warehouse or "").strip()
        if tw:
            dn_agg[code]["target_warehouses"].add(tw)

    pr_agg: Dict[str, Dict] = {}
    for item in pr_items:
        code = item.item_code
        if code not in pr_agg:
            pr_agg[code] = {"qty": 0, "amount": 0, "warehouses": set()}
        pr_agg[code]["qty"] += flt(item.qty)
        pr_agg[code]["amount"] += flt(item.amount)
        wh = (item.warehouse or "").strip()
        if wh:
            pr_agg[code]["warehouses"].add(wh)

    dn_codes = set(dn_agg.keys())
    pr_codes = set(pr_agg.keys())

    missing_in_pr = dn_codes - pr_codes
    extra_in_pr = pr_codes - dn_codes

    if missing_in_pr:
        skip_reasons.append(f"Item(s) in DN but not in PR: {', '.join(sorted(missing_in_pr))}")
    if extra_in_pr:
        skip_reasons.append(f"Item(s) in PR but not in DN: {', '.join(sorted(extra_in_pr))}")

    for code in sorted(dn_codes & pr_codes):
        dn_data = dn_agg[code]
        pr_data = pr_agg[code]

        dn_rate = flt(dn_data["amount"] / dn_data["qty"], 2) if dn_data["qty"] else 0
        pr_rate = flt(pr_data["amount"] / pr_data["qty"], 2) if pr_data["qty"] else 0
        if dn_rate != pr_rate:
            skip_reasons.append(f"Rate mismatch for {code}: DN rate={dn_rate}, PR rate={pr_rate}")

        if flt(dn_data["amount"], 2) != flt(pr_data["amount"], 2):
            skip_reasons.append(
                f"Taxable amount mismatch for {code}: DN={flt(dn_data['amount'], 2)}, PR={flt(pr_data['amount'], 2)}"
            )

        dn_targets = dn_data["target_warehouses"]
        pr_whs = pr_data["warehouses"]
        if dn_targets and pr_whs and dn_targets != pr_whs:
            skip_reasons.append(
                f"Location mismatch for {code}: DN target={', '.join(sorted(dn_targets))}, "
                f"PR warehouse={', '.join(sorted(pr_whs))}"
            )

    return {"fixable": len(skip_reasons) == 0, "skip_reasons": skip_reasons}


def _fix_dn_pr_link(dn_name: str, pr_name: str) -> Dict[str, Any]:
    """
    Fix a partially linked DN->PR pair by setting bidirectional references,
    status, and re-mapping stale delivery_note_item refs on PR items.

    When a DN has been amended, PR items still reference old DN item IDs.
    This function re-maps them by matching item_code + qty + rate.

    Args:
        dn_name: Delivery Note name
        pr_name: Purchase Receipt name

    Returns:
        Dict with success (bool) and message (str).
    """
    try:
        dn = frappe.get_doc("Delivery Note", dn_name)
        pr = frappe.get_doc("Purchase Receipt", pr_name)

        if dn.docstatus != 1 or pr.docstatus != 1:
            return {"success": False, "message": "Both documents must be submitted"}

        if dn.get("bns_inter_company_reference") != pr_name:
            dn.db_set("bns_inter_company_reference", pr_name, update_modified=False)
        if pr.get("bns_inter_company_reference") != dn_name:
            pr.db_set("bns_inter_company_reference", dn_name, update_modified=False)

        if not dn.get("is_bns_internal_customer"):
            dn.db_set("is_bns_internal_customer", 1, update_modified=False)
        if dn.status != "BNS Internally Transferred":
            dn.db_set("status", "BNS Internally Transferred", update_modified=False)
        if dn.per_billed != 100:
            dn.db_set("per_billed", 100, update_modified=False)

        if not pr.get("is_bns_internal_supplier"):
            pr.db_set("is_bns_internal_supplier", 1, update_modified=False)
        if pr.status != "BNS Internally Transferred":
            pr.db_set("status", "BNS Internally Transferred", update_modified=False)
        if pr.per_billed != 100:
            pr.db_set("per_billed", 100, update_modified=False)

        _remap_pr_delivery_note_items(dn, pr)

        frappe.clear_cache(doctype="Delivery Note")
        frappe.clear_cache(doctype="Purchase Receipt")

        logger.info("Fixed partial DN->PR link: %s <-> %s", dn_name, pr_name)
        return {"success": True, "message": f"Fixed link: DN {dn_name} <-> PR {pr_name}"}

    except Exception as e:
        logger.error("Error fixing DN-PR link %s <-> %s: %s", dn_name, pr_name, str(e))
        return {"success": False, "message": str(e)}


def _remap_pr_delivery_note_items(dn, pr) -> int:
    """
    Re-map stale delivery_note_item references on PR items to current DN item IDs.

    Matches by item_code + qty + rate. Only updates refs that are empty or
    point to IDs not present in the current DN (stale after amendment).

    Args:
        dn: Delivery Note doc object
        pr: Purchase Receipt doc object

    Returns:
        Number of PR items re-mapped.
    """
    dn_item_ids = {item.name for item in dn.items}

    pr_items_needing_remap = []
    for pri in pr.items:
        ref = (pri.get("delivery_note_item") or "").strip()
        if not ref or ref not in dn_item_ids:
            pr_items_needing_remap.append(pri)

    if not pr_items_needing_remap:
        return 0

    dn_pool = []
    for dni in dn.items:
        dn_pool.append({
            "name": dni.name,
            "item_code": dni.item_code,
            "qty": flt(dni.qty),
            "rate": flt(dni.rate),
            "stock_qty": flt(dni.stock_qty or dni.qty),
            "used": False,
        })

    remapped = 0
    for pri in pr_items_needing_remap:
        best = None
        for dn_entry in dn_pool:
            if dn_entry["used"]:
                continue
            if dn_entry["item_code"] != pri.item_code:
                continue
            if _qtys_equal_bulk(dn_entry["qty"], flt(pri.qty)):
                if best is None:
                    best = dn_entry
                elif flt(dn_entry["rate"], 2) == flt(pri.rate, 2):
                    best = dn_entry
                    break

        if best:
            best["used"] = True
            frappe.db.set_value(
                "Purchase Receipt Item", pri.name,
                "delivery_note_item", best["name"],
                update_modified=False,
            )
            remapped += 1

    if remapped:
        logger.info(
            "Re-mapped %d PR item refs on %s to current DN %s items",
            remapped, pr.name, dn.name,
        )

    return remapped


def _format_item_issues(link_label: str, check_result: Dict) -> List[str]:
    """Format item verification issues into human-readable strings."""
    issues = []
    for m in check_result.get("missing_items", [])[:3]:
        issues.append(f"{link_label}: item {m.get('item_code', '?')} not linked")
    for m in check_result.get("qty_mismatches", [])[:3]:
        keys = [k for k in m if k != "item_code"]
        detail = ", ".join(f"{k}={m[k]}" for k in keys)
        issues.append(f"{link_label}: qty mismatch {m.get('item_code', '?')} ({detail})")
    for m in check_result.get("item_mismatches", [])[:3]:
        src = m.get("dn_item_code") or m.get("si_item_code") or m.get("pr_item_code") or "?"
        dst = m.get("pr_item_code") or m.get("pi_item_code") or m.get("si_item_code") or "?"
        issues.append(f"{link_label}: item code mismatch {src} vs {dst}")
    return issues


def _repost_chain(chain: Dict[str, Any], allow_cross_fy_repost: bool = False) -> Dict[str, Any]:
    """
    Repost all documents in a fully-linked chain in dependency order.

    Includes a fiscal year guard: vouchers from a prior FY are skipped unless
    allow_cross_fy_repost is True, because account settings may have changed
    since the original posting and rewriting GL with current settings would
    break debit/credit pairing with the counter-document.

    Args:
        chain: Chain dict from _detect_chain_type with chain_type, docs, status
        allow_cross_fy_repost: If True, repost even when the voucher belongs
            to a prior fiscal year. Defaults to False.

    Returns:
        Dict with reposted doc names, skipped docs, and any errors
    """
    from erpnext.controllers.stock_controller import create_repost_item_valuation_entry

    chain_type = chain["chain_type"]
    docs = chain["docs"]
    reposted = []
    skipped = []
    errors = []

    current_fy = get_fiscal_year(getdate(frappe.utils.nowdate()))

    def _repost_voucher(voucher_type: str, voucher_no: str):
        """Repost a voucher: SLE recalc via RIV + full GL regen via RAL.

        RIV (`Repost Item Valuation`) handles stock ledger recalc and the
        BNS-specific bns_transfer_rate sync. RAL (`Repost Accounting Ledger`)
        unconditionally deletes and re-creates the voucher's full GL via
        ``make_gl_entries`` — which goes through the BNS patched
        ``get_gl_entries`` and emits any updated transfer-account routing
        (e.g., switch to internal_sales_non_gst_account). RIV alone leaves
        existing GL on the previously configured accounts when the new
        expected GL has the same shape but different account names.
        """
        try:
            doc = frappe.get_doc(voucher_type, voucher_no)
            if doc.docstatus != 1:
                return

            if not allow_cross_fy_repost:
                voucher_fy = get_fiscal_year(getdate(doc.posting_date))
                if voucher_fy[0] != current_fy[0]:
                    msg = (
                        f"Skipping repost of {voucher_type} {voucher_no} "
                        f"(FY {voucher_fy[0]}) — account settings may have changed "
                        f"since original posting. Repost manually after verifying accounts."
                    )
                    skipped.append(f"{voucher_type}:{voucher_no}")
                    logger.warning(msg)
                    return

            # RIV only for vouchers that own SLE (DN/PR, or update_stock=1
            # SI/PI). For an update_stock=0 invoice the stock lives on the
            # linked DN/PR (reposted via its own RIV in this same chain), so
            # RIV here would both throw (ERPNext validate_update_stock) and
            # have nothing to recompute — repost GL only via RAL.
            if _voucher_owns_sle(voucher_type, doc):
                create_repost_item_valuation_entry({
                    "based_on": "Transaction",
                    "voucher_type": voucher_type,
                    "voucher_no": voucher_no,
                    "posting_date": doc.posting_date,
                    "posting_time": getattr(doc, "posting_time", "00:00:00") or "00:00:00",
                    "company": doc.company,
                    "allow_zero_rate": 1,
                })

            # RAL submit triggers start_repost which calls make_gl_entries
            # synchronously (1 voucher ≤ 5 threshold). Per-voucher failure
            # is logged and continues — don't abort the whole chain.
            #
            # CRITICAL: ensure the BNS GL rewrite monkey-patch is active
            # before submitting RAL. Without it, start_repost would call
            # the unpatched get_gl_entries and rebuild GL with the standard
            # ERPNext pattern (COGS + Stock In Hand) — wiping out the BNS
            # internal-transfer rewrite. The patch is normally applied by
            # before_request/before_job hooks, but we apply defensively
            # here in case this runs outside those flows.
            try:
                _apply_bns_internal_gl_rewrite_patch()
                ral = frappe.new_doc("Repost Accounting Ledger")
                ral.company = doc.company
                ral.delete_cancelled_entries = 0
                ral.append("vouchers", {
                    "voucher_type": voucher_type,
                    "voucher_no": voucher_no,
                })
                ral.flags.ignore_permissions = True
                ral.save()
                ral.submit()
                logger.info("Bulk repost: submitted Repost Accounting Ledger for %s %s", voucher_type, voucher_no)
            except Exception as ral_err:
                ral_msg = f"RAL submit failed for {voucher_type} {voucher_no}: {str(ral_err)} (RIV still queued)"
                errors.append(ral_msg)
                logger.error(ral_msg)

            reposted.append(f"{voucher_type}:{voucher_no}")
            logger.info("Bulk repost: created Repost Item Valuation for %s %s", voucher_type, voucher_no)
        except Exception as e:
            error_msg = f"Failed to repost {voucher_type} {voucher_no}: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)

    if chain_type == "DN->PR":
        _repost_voucher("Delivery Note", docs["dn"])
        if "pr" in docs:
            _repost_voucher("Purchase Receipt", docs["pr"])

    elif chain_type == "SI->PI":
        _repost_voucher("Sales Invoice", docs["si"])
        if "pi" in docs:
            _repost_voucher("Purchase Invoice", docs["pi"])

    elif chain_type == "SI->PR->PI":
        _repost_voucher("Sales Invoice", docs["si"])
        if "pr" in docs:
            _repost_voucher("Purchase Receipt", docs["pr"])
        if "pi" in docs:
            _repost_voucher("Purchase Invoice", docs["pi"])

    elif chain_type == "DN->SI->PI":
        _repost_voucher("Delivery Note", docs["dn"])
        if "si" in docs:
            _repost_voucher("Sales Invoice", docs["si"])
        if "pi" in docs:
            _repost_voucher("Purchase Invoice", docs["pi"])

    elif chain_type == "DN->SI->PR->PI":
        _repost_voucher("Delivery Note", docs["dn"])
        if "si" in docs:
            _repost_voucher("Sales Invoice", docs["si"])
        if "pr" in docs:
            _repost_voucher("Purchase Receipt", docs["pr"])
        if "pi" in docs:
            _repost_voucher("Purchase Invoice", docs["pi"])

    return {"reposted": reposted, "skipped": skipped, "errors": errors}


@frappe.whitelist()
def verify_and_repost_internal_transfers(
    cutoff_date: str = None, repost: bool = True, fix_partial_dn_pr: bool = False,
    allow_cross_fy_repost: bool = False,
) -> Dict:
    """
    Verify all internal transfer chains after a cutoff date and optionally repost fully-linked ones.

    Detects 5 chain types:
      1. DN->PR (same GSTIN)
      2. SI->PI (different GSTIN, direct)
      3. SI->PR->PI (different GSTIN, via PR)
      4. DN->SI->PI (different GSTIN, DN-originated)
      5. DN->SI->PR->PI (different GSTIN, full chain)

    Args:
        cutoff_date: Posting date cutoff (ISO format). Falls back to BNS Branch Accounting Settings.
        repost: If True, repost all fully-linked chains. Defaults to True.
        fix_partial_dn_pr: If True, attempt to fix partially linked DN->PR chains.
            Skips any pair where item code, rate, taxable amount, or warehouse mismatches.
        allow_cross_fy_repost: If True, repost vouchers even when they belong to a
            prior fiscal year. Defaults to False to prevent GL account mismatches
            when BNS Branch Accounting Settings have changed between fiscal years.

    Returns:
        Dict with summary counts, chain details, repost results, and fix results.
    """
    _bns_require_accounts_write()
    if isinstance(repost, str):
        repost = repost.lower() in ("true", "1", "yes")
    if isinstance(fix_partial_dn_pr, str):
        fix_partial_dn_pr = fix_partial_dn_pr.lower() in ("true", "1", "yes")
    if isinstance(allow_cross_fy_repost, str):
        allow_cross_fy_repost = allow_cross_fy_repost.lower() in ("true", "1", "yes")

    if not cutoff_date:
        cutoff_date = _get_internal_transfer_cutoff_date()
    if not cutoff_date:
        frappe.throw(_("No cutoff date provided and no Internal Transfer Cutoff configured in BNS Branch Accounting Settings."))

    cutoff_date = getdate(cutoff_date)

    # Collect all source documents
    dn_rows = frappe.db.sql(
        """
        SELECT dn.name, dn.company_gstin, dn.billing_address_gstin,
               dn.bns_inter_company_reference, dn.posting_date, dn.company
        FROM `tabDelivery Note` dn
        JOIN `tabCustomer` c ON dn.customer = c.name
        WHERE dn.docstatus = 1
          AND c.is_bns_internal_customer = 1
          AND dn.posting_date >= %s
        ORDER BY dn.posting_date
        """,
        (cutoff_date,),
        as_dict=True,
    ) or []

    si_rows = frappe.db.sql(
        """
        SELECT si.name, si.company_gstin, si.billing_address_gstin,
               si.bns_inter_company_reference, si.posting_date, si.company
        FROM `tabSales Invoice` si
        JOIN `tabCustomer` c ON si.customer = c.name
        WHERE si.docstatus = 1
          AND c.is_bns_internal_customer = 1
          AND (si.company_gstin IS NOT NULL AND si.billing_address_gstin IS NOT NULL
               AND si.company_gstin != si.billing_address_gstin)
          AND si.is_return = 0
          AND si.posting_date >= %s
        ORDER BY si.posting_date
        """,
        (cutoff_date,),
        as_dict=True,
    ) or []

    # Also fetch bns_purchase_receipt_reference for SIs
    si_meta = frappe.get_meta("Sales Invoice")
    if si_meta.has_field("bns_purchase_receipt_reference"):
        for si in si_rows:
            si["bns_purchase_receipt_reference"] = frappe.db.get_value(
                "Sales Invoice", si["name"], "bns_purchase_receipt_reference"
            ) or ""

    chains = []
    seen_origins = set()

    # Process DNs first (they may originate multi-doc chains)
    for dn in dn_rows:
        if dn["name"] in seen_origins:
            continue
        seen_origins.add(dn["name"])
        chain = _detect_chain_type("Delivery Note", dn["name"], dn)
        if chain:
            # Mark downstream SIs as seen so they aren't double-counted
            if chain["docs"].get("si"):
                seen_origins.add(chain["docs"]["si"])
            chains.append(chain)

    # Process SIs not already handled via DN chains
    for si in si_rows:
        if si["name"] in seen_origins:
            continue
        seen_origins.add(si["name"])
        chain = _detect_chain_type("Sales Invoice", si["name"], si)
        if chain:
            chains.append(chain)

    # Categorize
    fully_linked = [c for c in chains if c["status"] == "fully_linked"]
    partially_linked = [c for c in chains if c["status"] == "partially_linked"]
    unlinked = [c for c in chains if c["status"] == "unlinked"]

    # Fix partial DN->PR chains if requested
    fix_results = []
    if fix_partial_dn_pr:
        partial_dn_pr = [c for c in partially_linked if c["chain_type"] == "DN->PR"]
        for chain in partial_dn_pr:
            dn_name = chain["docs"].get("dn")
            pr_name = chain["docs"].get("pr")
            if not dn_name or not pr_name:
                fix_results.append({
                    "dn": dn_name, "pr": pr_name, "action": "skipped",
                    "reason": "Missing DN or PR in chain",
                })
                continue

            check = _check_dn_pr_fixable(dn_name, pr_name)
            if not check["fixable"]:
                fix_results.append({
                    "dn": dn_name, "pr": pr_name, "action": "skipped",
                    "reason": "; ".join(check["skip_reasons"]),
                })
                continue

            result = _fix_dn_pr_link(dn_name, pr_name)
            if result["success"]:
                fix_results.append({
                    "dn": dn_name, "pr": pr_name, "action": "fixed",
                    "reason": result["message"],
                })
                chain["status"] = "fully_linked"
                chain["issues"] = []
            else:
                fix_results.append({
                    "dn": dn_name, "pr": pr_name, "action": "error",
                    "reason": result["message"],
                })

        # Re-categorize after fixes
        if fix_results:
            fully_linked = [c for c in chains if c["status"] == "fully_linked"]
            partially_linked = [c for c in chains if c["status"] == "partially_linked"]

    # Repost fully linked chains
    repost_results = []
    if repost and fully_linked:
        for chain in fully_linked:
            result = _repost_chain(chain, allow_cross_fy_repost=allow_cross_fy_repost)
            repost_results.append({
                "chain_type": chain["chain_type"],
                "docs": chain["docs"],
                "reposted": result["reposted"],
                "skipped": result.get("skipped", []),
                "errors": result["errors"],
            })

    fix_fixed_count = sum(1 for f in fix_results if f["action"] == "fixed")
    fix_skipped_count = sum(1 for f in fix_results if f["action"] == "skipped")
    fix_error_count = sum(1 for f in fix_results if f["action"] == "error")

    summary = {
        "cutoff_date": str(cutoff_date),
        "total_chains": len(chains),
        "fully_linked": len(fully_linked),
        "partially_linked": len(partially_linked),
        "unlinked": len(unlinked),
        "repost_enabled": repost,
        "reposted_count": sum(len(r["reposted"]) for r in repost_results),
        "repost_error_count": sum(len(r["errors"]) for r in repost_results),
        "fix_partial_dn_pr": fix_partial_dn_pr,
        "fix_fixed_count": fix_fixed_count,
        "fix_skipped_count": fix_skipped_count,
        "fix_error_count": fix_error_count,
        "chains_by_type": {},
    }

    for chain in chains:
        ct = chain["chain_type"]
        if ct not in summary["chains_by_type"]:
            summary["chains_by_type"][ct] = {"fully_linked": 0, "partially_linked": 0, "unlinked": 0}
        summary["chains_by_type"][ct][chain["status"]] += 1

    logger.info(
        "verify_and_repost_internal_transfers: cutoff=%s total=%s fully_linked=%s partially=%s unlinked=%s reposted=%s fixed=%s skipped=%s",
        cutoff_date, len(chains), len(fully_linked), len(partially_linked), len(unlinked),
        summary["reposted_count"], fix_fixed_count, fix_skipped_count,
    )

    fix_msg = ""
    if fix_partial_dn_pr:
        fix_msg = _(" DN->PR fix: {0} fixed, {1} skipped, {2} errors.").format(
            fix_fixed_count, fix_skipped_count, fix_error_count,
        )

    return {
        "success": True,
        "summary": summary,
        "fully_linked": [{"chain_type": c["chain_type"], "docs": c["docs"]} for c in fully_linked],
        "partially_linked": [
            {"chain_type": c["chain_type"], "docs": c["docs"], "issues": c["issues"]}
            for c in partially_linked
        ],
        "unlinked": [
            {"chain_type": c["chain_type"], "docs": c["docs"], "issues": c["issues"]}
            for c in unlinked
        ],
        "repost_results": repost_results,
        "fix_results": fix_results,
        "message": _(
            "Verification complete: {0} chains found. {1} fully linked, {2} partially linked, {3} unlinked. {4} documents reposted."
        ).format(
            len(chains), len(fully_linked), len(partially_linked), len(unlinked),
            summary["reposted_count"],
        ) + fix_msg,
    }


@frappe.whitelist()
def enqueue_verify_and_repost_internal_transfers(
    cutoff_date: str = None, repost: bool = True, fix_partial_dn_pr: bool = False
) -> Dict:
    """
    Enqueue bulk verification and repost as a background job.

    Args:
        cutoff_date: Posting date cutoff (ISO format).
        repost: If True, repost fully-linked chains.
        fix_partial_dn_pr: If True, attempt to fix partially linked DN->PR chains.

    Returns:
        Dict with job enqueue confirmation.
    """
    _bns_require_accounts_write()
    if isinstance(repost, str):
        repost = repost.lower() in ("true", "1", "yes")
    if isinstance(fix_partial_dn_pr, str):
        fix_partial_dn_pr = fix_partial_dn_pr.lower() in ("true", "1", "yes")

    frappe.enqueue(
        "business_needed_solutions.bns_branch_accounting.utils.verify_and_repost_internal_transfers",
        queue="long",
        timeout=3600,
        cutoff_date=cutoff_date,
        repost=repost,
        fix_partial_dn_pr=fix_partial_dn_pr,
    )

    return {
        "success": True,
        "message": _("Bulk verification and repost job has been enqueued. Check Background Jobs for progress."),
    }

# ── Internal reference glitch repair (Settings form button) ──────────────


@frappe.whitelist()
def repair_internal_reference_glitches(dry_run=1):
    """Repair legacy bns_inter_company_reference glitches in one pass.

    Handles the three states the Internal Transfer Receive Mismatch report
    tags as Duplicate claimants / Foreign-party reference / Conflicting
    claim (all produced before the ref field was no_copy and before the
    validate-time guards existed):

    - Foreign-party: PR/PI carrying a ref while the supplier is not BNS
      internal (and DN/SI back-refs with a non-internal customer) -> clear
      the ref. Skipped when the party MASTER is flagged internal — that
      doc should be fixed via Bulk Convert to BNS Internal instead.
    - Duplicate claimants: 2+ submitted PRs/PIs referencing one source ->
      keep the claimant the source back-references, clear the others.
      Skipped (manual decision) when the source back-references none.
    - Conflicting claim: PR refs a DN that back-refs a different PR ->
      same keeper rule.

    Only bns_inter_company_reference values are touched (plus the source
    back-ref when it points at a doc being cleared). No status, flags,
    per_billed, GL or SLE mutation. Each change drops an audit Comment on
    the document. dry_run=1 returns the plan without writing.
    """
    _bns_require_accounts_write()
    dry_run = cint(dry_run)

    actions = []   # {doctype, name, action, reason}
    skipped = []   # {doctype, name, reason}
    actioned = set()  # (doctype, name) already planned, to avoid double-clearing

    def _plan(doctype, name, action, reason):
        if (doctype, name) in actioned:
            return
        actioned.add((doctype, name))
        actions.append({"doctype": doctype, "name": name, "action": action, "reason": reason})

    def _source_doctype(name):
        if frappe.db.exists("Delivery Note", name):
            return "Delivery Note"
        if frappe.db.exists("Sales Invoice", name):
            return "Sales Invoice"
        return None

    # ── A. Foreign-party claimants (PR / PI; supplier not internal) ──
    for dt in ("Purchase Receipt", "Purchase Invoice"):
        rows = frappe.db.sql(
            f"""
            SELECT name, supplier, bns_inter_company_reference AS ref
            FROM `tab{dt}`
            WHERE docstatus = 1
              AND COALESCE(bns_inter_company_reference, '') != ''
              AND COALESCE(is_bns_internal_supplier, 0) = 0
            """,
            as_dict=True,
        ) or []
        for r in rows:
            if cint(frappe.db.get_value("Supplier", r.supplier, "is_bns_internal_supplier") or 0):
                skipped.append({
                    "doctype": dt, "name": r.name,
                    "reason": _("Supplier master IS flagged internal — fix the document flag via 'Bulk Convert to BNS Internal' instead of clearing the reference."),
                })
                continue
            _plan(dt, r.name, f"clear ref -> {r.ref}", "Foreign-party reference")
            # keep the pair symmetric: if the source back-refs this doc, clear that too
            src_dt = _source_doctype(r.ref)
            if src_dt:
                backref = (frappe.db.get_value(src_dt, r.ref, "bns_inter_company_reference") or "").strip()
                if backref == r.name:
                    _plan(src_dt, r.ref, f"clear back-ref -> {r.name}", "Counterpart of foreign-party clear")

    # ── A2. Foreign-party sources (DN / SI; customer not internal) ──
    for dt in ("Delivery Note", "Sales Invoice"):
        rows = frappe.db.sql(
            f"""
            SELECT name, customer, bns_inter_company_reference AS ref
            FROM `tab{dt}`
            WHERE docstatus = 1
              AND COALESCE(bns_inter_company_reference, '') != ''
              AND COALESCE(is_bns_internal_customer, 0) = 0
            """,
            as_dict=True,
        ) or []
        for r in rows:
            if cint(frappe.db.get_value("Customer", r.customer, "is_bns_internal_customer") or 0):
                skipped.append({
                    "doctype": dt, "name": r.name,
                    "reason": _("Customer master IS flagged internal — fix the document flag via 'Bulk Convert to BNS Internal' instead of clearing the reference."),
                })
                continue
            _plan(dt, r.name, f"clear back-ref -> {r.ref}", "Foreign-party reference")
            # symmetric clear (mirror of section A): any submitted PR/PI still
            # claiming this source would otherwise resurface as an asymmetric
            # back-ref row, which reads as "complete the link" — the opposite
            # of what this repair just decided.
            for claim_dt in ("Purchase Receipt", "Purchase Invoice"):
                claimers = frappe.get_all(
                    claim_dt,
                    filters={"bns_inter_company_reference": r.name, "docstatus": 1},
                    pluck="name",
                ) or []
                for claimer in claimers:
                    _plan(claim_dt, claimer, f"clear ref -> {r.name}",
                          "Counterpart of foreign-party clear")

    # ── B. Duplicate / conflicting claimants -> keeper rule ──
    for claim_dt in ("Purchase Receipt", "Purchase Invoice"):
        groups = frappe.db.sql(
            f"""
            SELECT bns_inter_company_reference AS source_ref,
                   GROUP_CONCAT(name ORDER BY name SEPARATOR ',') AS claimants
            FROM `tab{claim_dt}`
            WHERE docstatus = 1
              AND COALESCE(bns_inter_company_reference, '') != ''
            GROUP BY bns_inter_company_reference
            HAVING COUNT(*) > 1
            """,
            as_dict=True,
        ) or []
        for g in groups:
            claimants = (g.claimants or "").split(",")
            src_dt = _source_doctype(g.source_ref)
            if not src_dt:
                skipped.append({
                    "doctype": claim_dt, "name": g.claimants,
                    "reason": _("Source {0} does not exist — decide manually which claimant to keep.").format(g.source_ref),
                })
                continue
            backref = (frappe.db.get_value(src_dt, g.source_ref, "bns_inter_company_reference") or "").strip()
            if backref not in claimants:
                skipped.append({
                    "doctype": claim_dt, "name": g.claimants,
                    "reason": _("{0} {1} back-references none of the claimants — decide manually which to keep.").format(src_dt, g.source_ref),
                })
                continue
            for name in claimants:
                if name != backref:
                    _plan(claim_dt, name, f"clear ref -> {g.source_ref}",
                          f"Duplicate claimant (keeper: {backref})")

    # ── C. Single conflicting claim: PR refs DN, DN back-refs a different PR ──
    conflict_rows = frappe.db.sql(
        """
        SELECT pr.name AS pr_name, pr.bns_inter_company_reference AS dn_name,
               dn.bns_inter_company_reference AS dn_backref
        FROM `tabPurchase Receipt` pr
        JOIN `tabDelivery Note` dn
            ON dn.name = pr.bns_inter_company_reference AND dn.docstatus = 1
        WHERE pr.docstatus = 1
          AND COALESCE(pr.bns_inter_company_reference, '') != ''
          AND COALESCE(dn.bns_inter_company_reference, '') != ''
          AND dn.bns_inter_company_reference != pr.name
        """,
        as_dict=True,
    ) or []
    for r in conflict_rows:
        keeper_ref = (frappe.db.get_value("Purchase Receipt", r.dn_backref, "bns_inter_company_reference") or "").strip() \
            if frappe.db.exists("Purchase Receipt", r.dn_backref) else ""
        if keeper_ref == r.dn_name:
            _plan("Purchase Receipt", r.pr_name, f"clear ref -> {r.dn_name}",
                  f"Conflicting claim (DN back-references {r.dn_backref})")
        else:
            skipped.append({
                "doctype": "Purchase Receipt", "name": r.pr_name,
                "reason": _("DN {0} back-references {1}, which does not reference it back — chain is inconsistent, decide manually.").format(r.dn_name, r.dn_backref),
            })

    if not dry_run:
        for a in actions:
            frappe.db.set_value(a["doctype"], a["name"], "bns_inter_company_reference", None, update_modified=False)
            frappe.get_doc({
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": a["doctype"],
                "reference_name": a["name"],
                "content": _("BNS repair: {0} ({1})").format(a["action"], a["reason"]),
            }).insert(ignore_permissions=True)
        frappe.db.commit()

    return {
        "dry_run": dry_run,
        "total_planned": len(actions),
        "total_skipped": len(skipped),
        "actions": actions,
        "skipped": skipped,
    }
