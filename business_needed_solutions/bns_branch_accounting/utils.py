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
from frappe.utils import flt, cint, get_link_to_form, getdate
from frappe import bold
from typing import Optional, Dict, Any, List, Tuple, Set
from collections import defaultdict
import logging

# Configure logging
logger = logging.getLogger(__name__)

_BNS_INTERNAL_GL_PATCHED = False
_BNS_REPOST_GL_FAILSAFE_PATCHED = False
_BNS_TRANSFER_RATE_STOCK_LEDGER_PATCHED = False
_BNS_REPOST_ACCOUNTING_LEDGER_PATCHED = False


def _get_bns_transfer_rate_for_pr_sle(sle) -> float:
    """
    Resolve bns_transfer_rate for a Purchase Receipt SLE row.

    Scope:
    - Purchase Receipt only
    - Submitted PR only
    - BNS internal supplier only
    - DN-linked (same GSTIN DN->PR flow)
    """
    if not sle or getattr(sle, "voucher_type", None) != "Purchase Receipt":
        return 0.0
    if not getattr(sle, "voucher_detail_no", None):
        return 0.0
    if flt(getattr(sle, "actual_qty", 0)) <= 0:
        return 0.0

    pri_meta = frappe.get_meta("Purchase Receipt Item")
    if not pri_meta.has_field("bns_transfer_rate"):
        return 0.0

    pr_item = frappe.db.get_value(
        "Purchase Receipt Item",
        sle.voucher_detail_no,
        ["parent", "bns_transfer_rate"],
        as_dict=True,
    )
    if not pr_item:
        return 0.0

    transfer_rate = flt(pr_item.get("bns_transfer_rate") or 0)
    if transfer_rate <= 0:
        return 0.0

    pr = frappe.db.get_value(
        "Purchase Receipt",
        pr_item.get("parent"),
        ["docstatus", "is_bns_internal_supplier", "bns_inter_company_reference", "posting_date"],
        as_dict=True,
    )
    if not pr or pr.docstatus != 1:
        return 0.0
    if not is_after_internal_validation_cutoff(pr.get("posting_date")):
        return 0.0
    if not pr.get("is_bns_internal_supplier"):
        return 0.0
    if not pr.get("bns_inter_company_reference") or not frappe.db.exists(
        "Delivery Note", pr.get("bns_inter_company_reference")
    ):
        return 0.0

    return transfer_rate


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
            transfer_rate = _get_bns_transfer_rate_for_pr_sle(sle)
            if transfer_rate > 0:
                sle.incoming_rate = transfer_rate
                return transfer_rate
            return rate

        def patched_process_sle(self, sle):
            transfer_rate = _get_bns_transfer_rate_for_pr_sle(sle)
            if transfer_rate > 0:
                sle.incoming_rate = transfer_rate
                sle.recalculate_rate = 1
            return original_process_sle(self, sle)

        patched_get_incoming_outgoing_rate_from_transaction._bns_transfer_rate_patched = True
        patched_process_sle._bns_transfer_rate_patched = True
        update_entries_after.get_incoming_outgoing_rate_from_transaction = patched_get_incoming_outgoing_rate_from_transaction
        update_entries_after.process_sle = patched_process_sle
        _BNS_TRANSFER_RATE_STOCK_LEDGER_PATCHED = True
        logger.info("Applied BNS stock-ledger patch: PR repost valuation uses bns_transfer_rate")
    except Exception as e:
        logger.error(f"Failed to apply BNS transfer-rate stock-ledger patch: {str(e)}")


def _get_bns_branch_accounting_accounts() -> Dict[str, Any]:
    """Get BNS Branch Accounting account settings required for GL rewrite."""
    settings = {
        "stock_in_transit_account": frappe.db.get_single_value(
            "BNS Branch Accounting Settings", "stock_in_transit_account"
        ),
        "internal_transfer_account": frappe.db.get_single_value(
            "BNS Branch Accounting Settings", "internal_transfer_account"
        ),
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
        "internal_transfer_account",
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

    required_fields = {
        "internal_transfer_account": _("Internal Transfer Account"),
        "stock_in_transit_account": _("Stock in Transit Account"),
        "internal_branch_debtor_account": _("Internal Branch Debtor Account"),
        "internal_branch_creditor_account": _("Internal Branch Creditor Account"),
    }

    configured = {
        fieldname: (frappe.db.get_single_value("BNS Branch Accounting Settings", fieldname) or "").strip()
        for fieldname in required_fields
    }
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


def _get_internal_validation_cutoff_date():
    """Return configured posting-date cutoff for internal validations, if any."""
    cutoff = frappe.db.get_single_value(
        "BNS Branch Accounting Settings", "internal_validation_cutoff_date"
    )
    if not cutoff:
        return None
    try:
        return getdate(cutoff)
    except Exception:
        return None


def is_after_internal_validation_cutoff(posting_date) -> bool:
    """Return True when posting_date is on/after cutoff, or when no cutoff is set."""
    cutoff = _get_internal_validation_cutoff_date()
    if not cutoff:
        return True
    if not posting_date:
        return False
    try:
        return getdate(posting_date) >= cutoff
    except Exception:
        return False


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
    """Resolve PR GST scope as 'same' or 'different'."""
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
    """Check DN is in scoped BNS internal same-GSTIN flow."""
    return bool(
        doc
        and doc.doctype == "Delivery Note"
        and doc.docstatus == 1
        and is_after_internal_validation_cutoff(doc.get("posting_date"))
        and is_bns_internal_customer(doc)
        and (doc.get("billing_address_gstin") or "") == (doc.get("company_gstin") or "")
    )


def _get_linked_delivery_note_for_pr(doc) -> Optional[str]:
    """Resolve linked Delivery Note for Purchase Receipt in same-GSTIN flow."""
    candidate = doc.get("bns_inter_company_reference")
    if candidate and frappe.db.exists("Delivery Note", candidate):
        return candidate
    return None


def _is_bns_internal_same_gstin_purchase_receipt(doc) -> bool:
    """Check PR is in scoped BNS internal same-GSTIN DN->PR flow."""
    if not (
        doc
        and doc.doctype == "Purchase Receipt"
        and doc.docstatus == 1
        and is_bns_internal_supplier(doc)
        and is_after_internal_validation_cutoff(doc.get("posting_date"))
    ):
        return False

    dn_name = _get_linked_delivery_note_for_pr(doc)
    if not dn_name:
        return False

    dn_gstin = frappe.db.get_value("Delivery Note", dn_name, "billing_address_gstin")
    dn_company_gstin = frappe.db.get_value("Delivery Note", dn_name, "company_gstin")
    return bool((dn_gstin or "") == (dn_company_gstin or ""))


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
    if not is_bns_internal_supplier(doc) and not source_ref:
        return
    # Hard lock PRs that carry BNS source reference, regardless of cutoff.
    if not is_after_internal_validation_cutoff(doc.get("posting_date")) and not source_ref:
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
    if not is_bns_internal_supplier(doc):
        return
    if not is_after_internal_validation_cutoff(doc.get("posting_date")):
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


def _get_dn_item_transfer_rate_for_gl(dn_item) -> float:
    """Get transfer rate from Delivery Note Item incoming_rate with DB fallback."""
    rate = flt(dn_item.get("incoming_rate") or 0)
    if rate > 0:
        return rate

    if dn_item.get("name") and frappe.db.exists("Delivery Note Item", dn_item.get("name")):
        return flt(frappe.db.get_value("Delivery Note Item", dn_item.get("name"), "incoming_rate") or 0)

    return 0


def _resolve_dn_transfer_amount(doc, force_mode: bool = False) -> Tuple[float, str]:
    """Resolve DN transfer amount from billing rate side (not valuation)."""
    total = 0.0
    missing = False
    for item in doc.get("items") or []:
        line_amount = flt(item.get("base_net_amount") or 0)
        if line_amount <= 0:
            line_amount = flt(item.get("base_amount") or 0)
        if line_amount <= 0:
            # Fallback path when base amounts are not populated.
            qty = abs(flt(item.get("qty") or 0))
            rate = flt(item.get("base_net_rate") or item.get("rate") or 0)
            line_amount = qty * rate

        if line_amount <= 0:
            missing = True
            continue
        total += line_amount

    if total <= 0:
        return 0.0, "no_transfer_amount"
    if missing and not force_mode:
        return 0.0, "missing_item_transfer_rate"
    return total, ""


def _resolve_pr_transfer_amount(doc, force_mode: bool = False) -> Tuple[float, str]:
    """Resolve PR transfer amount from billing rate side (not valuation)."""
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
            missing = True
            continue
        total += line_amount

    if total <= 0:
        return 0.0, "no_transfer_amount"
    if missing and not force_mode:
        return 0.0, "missing_item_transfer_rate"
    return total, ""


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
    party_type = template.get("party_type")
    party = template.get("party")

    if not party_type or not party:
        account_type = frappe.get_cached_value("Account", account, "account_type")
        if account_type == "Receivable":
            party_type = "Customer"
            party = getattr(doc, "customer", None)
        elif account_type == "Payable":
            party_type = "Supplier"
            party = getattr(doc, "supplier", None)

    args = {
        "account": account,
        "debit": flt(debit),
        "credit": flt(credit),
        "against": against,
        "party_type": party_type,
        "party": party,
        "cost_center": template.get("cost_center"),
        "project": template.get("project"),
        "finance_book": template.get("finance_book"),
        "remarks": template.get("remarks") or _("BNS internal transfer accounting rewrite"),
    }
    return doc.get_gl_dict(args)


def _rewrite_bns_internal_dn_gl_entries(doc, gl_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rewrite DN GL entries into BNS internal branch-accounting pattern."""
    if not _is_bns_internal_same_gstin_delivery_note(doc):
        return gl_entries

    settings = _get_bns_branch_accounting_accounts()
    if not settings:
        return gl_entries

    force_mode = bool(settings.get("force_bns_internal_gl_rewrite"))
    transfer_amount, transfer_reason = _resolve_dn_transfer_amount(doc, force_mode=force_mode)
    valuation_amount, stock_account, valuation_reason = _resolve_valuation_from_gl_entries(
        gl_entries, side="credit", company=doc.company
    )

    if transfer_amount <= 0 or valuation_amount <= 0 or not stock_account:
        logger.warning(
            "Skipping DN GL rewrite for %s due to transfer_reason=%s valuation_reason=%s",
            doc.name,
            transfer_reason or "ok",
            valuation_reason or "ok",
        )
        return gl_entries

    template = next((row for row in gl_entries if row.get("account") == stock_account and flt(row.get("credit") or 0) > 0), None)
    if not template and gl_entries:
        template = gl_entries[0]
    if not template:
        return gl_entries

    rewritten = [
        _make_bns_gl_entry(doc, settings["internal_branch_debtor_account"], debit=transfer_amount, against=settings["internal_transfer_account"], template=template),
        _make_bns_gl_entry(doc, settings["stock_in_transit_account"], debit=valuation_amount, against=stock_account, template=template),
        _make_bns_gl_entry(doc, settings["internal_transfer_account"], credit=transfer_amount, against=settings["internal_branch_debtor_account"], template=template),
        _make_bns_gl_entry(doc, stock_account, credit=valuation_amount, against=settings["stock_in_transit_account"], template=template),
    ]

    debit_total = sum(flt(row.get("debit") or 0) for row in rewritten)
    credit_total = sum(flt(row.get("credit") or 0) for row in rewritten)
    if abs(debit_total - credit_total) > 0.01:
        logger.error("Skipping DN GL rewrite for %s due to balance mismatch %s vs %s", doc.name, debit_total, credit_total)
        return gl_entries

    return rewritten


def _rewrite_bns_internal_pr_gl_entries(doc, gl_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rewrite PR GL entries into BNS internal branch-accounting pattern."""
    if not _is_bns_internal_same_gstin_purchase_receipt(doc):
        return gl_entries

    settings = _get_bns_branch_accounting_accounts()
    if not settings:
        return gl_entries

    force_mode = bool(settings.get("force_bns_internal_gl_rewrite"))
    transfer_amount, transfer_reason = _resolve_pr_transfer_amount(doc, force_mode=force_mode)
    valuation_amount, stock_account, valuation_reason = _resolve_valuation_from_gl_entries(
        gl_entries, side="debit", company=doc.company
    )

    if transfer_amount <= 0 or valuation_amount <= 0 or not stock_account:
        logger.warning(
            "Skipping PR GL rewrite for %s due to transfer_reason=%s valuation_reason=%s",
            doc.name,
            transfer_reason or "ok",
            valuation_reason or "ok",
        )
        return gl_entries

    template = next((row for row in gl_entries if row.get("account") == stock_account and flt(row.get("debit") or 0) > 0), None)
    if not template and gl_entries:
        template = gl_entries[0]
    if not template:
        return gl_entries

    rewritten = [
        _make_bns_gl_entry(doc, settings["internal_transfer_account"], debit=transfer_amount, against=settings["internal_branch_creditor_account"], template=template),
        _make_bns_gl_entry(doc, stock_account, debit=valuation_amount, against=settings["stock_in_transit_account"], template=template),
        _make_bns_gl_entry(doc, settings["internal_branch_creditor_account"], credit=transfer_amount, against=settings["internal_transfer_account"], template=template),
        _make_bns_gl_entry(doc, settings["stock_in_transit_account"], credit=valuation_amount, against=stock_account, template=template),
    ]

    debit_total = sum(flt(row.get("debit") or 0) for row in rewritten)
    credit_total = sum(flt(row.get("credit") or 0) for row in rewritten)
    if abs(debit_total - credit_total) > 0.01:
        logger.error("Skipping PR GL rewrite for %s due to balance mismatch %s vs %s", doc.name, debit_total, credit_total)
        return gl_entries

    return rewritten


def _apply_bns_internal_gl_rewrite_patch() -> None:
    """Patch ERPNext GL generation for DN and PR in BNS internal same-GSTIN scope."""
    global _BNS_INTERNAL_GL_PATCHED
    if _BNS_INTERNAL_GL_PATCHED:
        return

    try:
        from erpnext.controllers.stock_controller import StockController
        from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt

        original_stock_get_gl_entries = StockController.get_gl_entries
        original_pr_get_gl_entries = PurchaseReceipt.get_gl_entries

        if getattr(original_stock_get_gl_entries, "_bns_internal_gl_rewrite_patched", False):
            _BNS_INTERNAL_GL_PATCHED = True
            return

        def patched_stock_get_gl_entries(self, warehouse_account=None, default_expense_account=None, default_cost_center=None):
            gl_entries = original_stock_get_gl_entries(self, warehouse_account, default_expense_account, default_cost_center)
            if getattr(self, "doctype", None) == "Delivery Note":
                return _rewrite_bns_internal_dn_gl_entries(self, gl_entries)
            return gl_entries

        def patched_pr_get_gl_entries(self, warehouse_account=None, via_landed_cost_voucher=False):
            gl_entries = original_pr_get_gl_entries(self, warehouse_account, via_landed_cost_voucher)
            return _rewrite_bns_internal_pr_gl_entries(self, gl_entries)

        patched_stock_get_gl_entries._bns_internal_gl_rewrite_patched = True
        patched_pr_get_gl_entries._bns_internal_gl_rewrite_patched = True
        StockController.get_gl_entries = patched_stock_get_gl_entries
        PurchaseReceipt.get_gl_entries = patched_pr_get_gl_entries
        _BNS_INTERNAL_GL_PATCHED = True
        logger.info("Applied BNS internal GL rewrite patch for Delivery Note and Purchase Receipt")

    except Exception as e:
        logger.error("Failed to apply BNS internal GL rewrite patch: %s", str(e))


def _run_bns_gl_repost_correction(doc, force_override: bool = False) -> None:
    """Re-run repost GLE only for scoped DN/PR vouchers as failsafe."""
    cache_key = f"bns_gl_repost_correction::{doc.name}"
    if not force_override and frappe.cache().get_value(cache_key):
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
        if voucher_type == "Delivery Note" and _is_bns_internal_same_gstin_delivery_note(voucher_doc):
            filtered_vouchers.append((voucher_type, voucher_no))
        elif voucher_type == "Purchase Receipt" and _is_bns_internal_same_gstin_purchase_receipt(voucher_doc):
            filtered_vouchers.append((voucher_type, voucher_no))

    if filtered_vouchers:
        _apply_bns_internal_gl_rewrite_patch()
        settings = _get_bns_branch_accounting_accounts()
        force_mode = bool(settings and settings.get("force_bns_internal_gl_rewrite")) or bool(force_override)
        if force_mode:
            rebuilt = 0
            for voucher_type, voucher_no in filtered_vouchers:
                if _force_rebuild_bns_gl_for_voucher(
                    voucher_type, voucher_no, context="repost_item_valuation"
                ):
                    rebuilt += 1
                    if not force_override:
                        _mark_bns_repost_voucher_processed(
                            "repost_item_valuation", doc.name, voucher_type, voucher_no
                        )
            logger.info(
                "BNS repost GL force-rebuild applied for repost %s on %s/%s vouchers",
                doc.name,
                rebuilt,
                len(filtered_vouchers),
            )
        else:
            from erpnext.accounts.utils import repost_gle_for_stock_vouchers

            before_counts = {
                (voucher_type, voucher_no): _get_ledger_row_counts_for_voucher(voucher_type, voucher_no)
                for voucher_type, voucher_no in filtered_vouchers
            }
            repost_gle_for_stock_vouchers(filtered_vouchers, doc.posting_date, doc.company, repost_doc=doc)
            for voucher_type, voucher_no in filtered_vouchers:
                after_counts = _get_ledger_row_counts_for_voucher(voucher_type, voucher_no)
                logger.info(
                    "BNS repost audit %s",
                    frappe.as_json(
                        {
                            "scope": "repost_item_valuation",
                            "mode": "repost_gle_for_stock_vouchers",
                            "repost_doc": doc.name,
                            "voucher_type": voucher_type,
                            "voucher_no": voucher_no,
                            "before_count": before_counts[(voucher_type, voucher_no)],
                            "after_count": after_counts,
                        }
                    ),
                )
                if not force_override:
                    _mark_bns_repost_voucher_processed(
                        "repost_item_valuation", doc.name, voucher_type, voucher_no
                    )
            logger.info("BNS repost GL failsafe applied for repost %s on %s vouchers", doc.name, len(filtered_vouchers))

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


def _bns_repost_voucher_marker_key(
    scope: str, repost_doc: str, voucher_type: str, voucher_no: str
) -> str:
    return f"bns_repost_voucher::{scope}::{repost_doc}::{voucher_type}::{voucher_no}"


def _is_bns_repost_voucher_processed(
    scope: str, repost_doc: str, voucher_type: str, voucher_no: str
) -> bool:
    return bool(frappe.cache().get_value(_bns_repost_voucher_marker_key(scope, repost_doc, voucher_type, voucher_no)))


def _mark_bns_repost_voucher_processed(
    scope: str, repost_doc: str, voucher_type: str, voucher_no: str
) -> None:
    frappe.cache().set_value(
        _bns_repost_voucher_marker_key(scope, repost_doc, voucher_type, voucher_no),
        1,
        expires_in_sec=6 * 60 * 60,
    )


def _force_rebuild_bns_gl_for_voucher(
    voucher_type: str, voucher_no: str, context: str = "manual"
) -> bool:
    """Force rebuild GL entries for a single DN/PR voucher using patched get_gl_entries."""
    if voucher_type not in ("Delivery Note", "Purchase Receipt") or not voucher_no:
        return False
    if not frappe.db.exists(voucher_type, voucher_no):
        return False

    doc = frappe.get_doc(voucher_type, voucher_no)
    if doc.docstatus != 1:
        return False

    if voucher_type == "Delivery Note" and not _is_bns_internal_same_gstin_delivery_note(doc):
        return False
    if voucher_type == "Purchase Receipt" and not _is_bns_internal_same_gstin_purchase_receipt(doc):
        return False

    _apply_bns_internal_gl_rewrite_patch()
    save_point = "bns_force_rebuild_voucher"
    before_counts = _get_ledger_row_counts_for_voucher(voucher_type, voucher_no)

    try:
        frappe.db.savepoint(save_point)
        # Symmetric replacement: remove ledger rows for voucher and rebuild.
        _delete_ledger_rows_for_voucher(voucher_type, voucher_no)
        doc.make_gl_entries(from_repost=True)
        after_counts = _get_ledger_row_counts_for_voucher(voucher_type, voucher_no)
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
        return True
    except Exception as e:
        frappe.db.rollback(save_point=save_point)
        logger.error("Force rebuild failed for %s %s: %s", voucher_type, voucher_no, str(e))
        return False


def _run_bns_gl_repost_accounting_correction(repost_doc_name: str, force_override: bool = False) -> None:
    """Apply BNS GL correction for vouchers included in Repost Accounting Ledger."""
    if not repost_doc_name or not frappe.db.exists("Repost Accounting Ledger", repost_doc_name):
        return

    cache_key = f"bns_gl_accounting_repost_correction::{repost_doc_name}"
    if not force_override and frappe.cache().get_value(cache_key):
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
            continue
        doc = frappe.get_doc(voucher_type, voucher_no)
        if voucher_type == "Delivery Note" and _is_bns_internal_same_gstin_delivery_note(doc):
            filtered.append((voucher_type, voucher_no))
        elif voucher_type == "Purchase Receipt" and _is_bns_internal_same_gstin_purchase_receipt(doc):
            filtered.append((voucher_type, voucher_no))

    if not filtered:
        if force_override:
            frappe.cache().delete_value(cache_key)
        else:
            frappe.cache().set_value(cache_key, 1, expires_in_sec=6 * 60 * 60)
        return

    _apply_bns_internal_gl_rewrite_patch()
    settings = _get_bns_branch_accounting_accounts()
    force_mode = bool(settings and settings.get("force_bns_internal_gl_rewrite")) or bool(force_override)
    if force_mode:
        rebuilt = 0
        for voucher_type, voucher_no in filtered:
            if _force_rebuild_bns_gl_for_voucher(
                voucher_type, voucher_no, context="repost_accounting_ledger"
            ):
                rebuilt += 1
                if not force_override:
                    _mark_bns_repost_voucher_processed(
                        "repost_accounting_ledger", repost_doc_name, voucher_type, voucher_no
                    )
        logger.info(
            "BNS Repost Accounting Ledger force-rebuild applied for %s on %s/%s vouchers",
            repost_doc_name,
            rebuilt,
            len(filtered),
        )
    else:
        from erpnext.accounts.utils import repost_gle_for_stock_vouchers
        before_counts = {
            (voucher_type, voucher_no): _get_ledger_row_counts_for_voucher(voucher_type, voucher_no)
            for voucher_type, voucher_no in filtered
        }
        repost_gle_for_stock_vouchers(filtered, repost_doc.posting_date, repost_doc.company, repost_doc=repost_doc)
        for voucher_type, voucher_no in filtered:
            after_counts = _get_ledger_row_counts_for_voucher(voucher_type, voucher_no)
            logger.info(
                "BNS repost audit %s",
                frappe.as_json(
                    {
                        "scope": "repost_accounting_ledger",
                        "mode": "repost_gle_for_stock_vouchers",
                        "repost_doc": repost_doc_name,
                        "voucher_type": voucher_type,
                        "voucher_no": voucher_no,
                        "before_count": before_counts[(voucher_type, voucher_no)],
                        "after_count": after_counts,
                    }
                ),
            )
            if not force_override:
                _mark_bns_repost_voucher_processed(
                    "repost_accounting_ledger", repost_doc_name, voucher_type, voucher_no
                )
        logger.info(
            "BNS Repost Accounting Ledger correction applied for %s on %s vouchers",
            repost_doc_name,
            len(filtered),
        )

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
        "is_dn_scope": _is_bns_internal_same_gstin_delivery_note(doc) if voucher_type == "Delivery Note" else None,
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
            original_repost_gl_entries(doc)
            try:
                _run_bns_gl_repost_correction(doc)
            except Exception as e:
                logger.error("BNS repost GL failsafe error for %s: %s", doc.name, str(e))

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
            try:
                _run_bns_gl_repost_accounting_correction(account_repost_doc)
            except Exception as e:
                logger.error("BNS repost accounting correction failed for %s: %s", account_repost_doc, str(e))
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

    cache_key = f"bns_internal_gl_repost::{doc.doctype}::{doc.name}"
    if frappe.cache().get_value(cache_key):
        return False

    try:
        _apply_bns_internal_gl_rewrite_patch()
        doc.repost_future_sle_and_gle(force=True)
        frappe.cache().set_value(cache_key, 1, expires_in_sec=10 * 60)
        logger.info("Triggered guarded BNS GL repost for %s %s (%s)", doc.doctype, doc.name, source)
        return True
    except Exception as e:
        logger.error("Failed guarded BNS GL repost for %s %s (%s): %s", doc.doctype, doc.name, source, str(e))
        return False


# Best-effort eager patching on module import.
_apply_bns_transfer_rate_stock_ledger_patch()
_apply_bns_internal_gl_rewrite_patch()
_apply_bns_repost_gl_failsafe_patch()
_apply_bns_repost_accounting_ledger_patch()


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
    try:
        dn = frappe.get_doc("Delivery Note", source_name)
        
        # Validate delivery note for internal customer
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
        
        # Update delivery note with reference (this needs to be done after the document is created)
        _update_delivery_note_reference(dn.name, doclist.name)
        
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
                "serial_no": "serial_no",
                "batch_no": "batch_no",
            },
            # Deliberately exclude purchase_order / purchase_order_item:
            # The DN items may reference a PO whose supplier differs from
            # the BNS internal supplier on the new PR.  Carrying them over
            # triggers ERPNext's validate_with_previous_doc() which
            # compares PR.supplier against PO.supplier and throws
            # "Incorrect value: Supplier must be equal to …".
            "field_no_map": ["warehouse", "rejected_warehouse", "expense_account", "cost_center", "project", "location",
                             "purchase_order", "purchase_order_item"],
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
    # Calculate quantity considering returned_qty and received_qty
    source_qty = flt(source.qty or 0)
    returned_qty = flt(source.returned_qty or 0)
    received_qty = flt(source.received_qty or 0)
    target.qty = source_qty + returned_qty - received_qty
    
    # Calculate stock_qty similarly
    source_stock_qty = flt(source.stock_qty or source_qty)
    target.stock_qty = source_stock_qty + returned_qty - received_qty
    
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
    
    # Clear accounting fields to let system auto-populate
    _clear_item_level_fields(target)
    
    if source.get("use_serial_batch_fields"):
        target.set("use_serial_batch_fields", 1)


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
    
    # Guard: prevent infinite loops - if already updated, skip
    if doc.status == "BNS Internally Transferred":
        return
    
    # Check if customer is BNS internal
    if not is_bns_internal_customer(doc):
        return

    try:
        # Check GSTIN match
        billing_address_gstin = getattr(doc, 'billing_address_gstin', None)
        company_gstin = getattr(doc, 'company_gstin', None)
        
        if billing_address_gstin is not None and company_gstin is not None:
            if billing_address_gstin == company_gstin:
                # SAME GSTIN - Set as internal transfer
                per_billed = 100
                doc.db_set("status", "BNS Internally Transferred", update_modified=False)
                doc.db_set("per_billed", per_billed, update_modified=False)
                doc.db_set("is_bns_internal_customer", 1, update_modified=False)
                # Ensure GL gets rebuilt with BNS rewrite even if initial submit happened
                # before patch load in this process.
                _trigger_bns_internal_gl_repost(doc, source="dn_on_submit_status_update")
                frappe.clear_cache(doctype="Delivery Note")
                logger.info(f"Updated Delivery Note {doc.name} status to BNS Internally Transferred (same GSTIN)")
            else:
                # DIFFERENT GSTIN - Set as To Bill
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
    
    # Guard: prevent infinite loops - if already updated, skip
    if doc.status == "BNS Internally Transferred":
        return

    try:
        # Canonical-first source resolution:
        # 1) bns_inter_company_reference (authoritative)
        # 2) supplier_delivery_note (legacy fallback only when canonical ref is absent)
        source_dn = None
        source_si = None
        canonical_ref = (doc.get("bns_inter_company_reference") or "").strip()
        legacy_ref = (doc.get("supplier_delivery_note") or "").strip()

        if canonical_ref:
            if frappe.db.exists("Delivery Note", canonical_ref):
                source_dn = canonical_ref
            elif frappe.db.exists("Sales Invoice", canonical_ref):
                source_si = canonical_ref
        elif legacy_ref:
            if frappe.db.exists("Delivery Note", legacy_ref):
                source_dn = legacy_ref
            elif frappe.db.exists("Sales Invoice", legacy_ref):
                source_si = legacy_ref

        # Same GSTIN/DN source => internal supplier flag on PR.
        # Different GSTIN/SI source => not internal supplier for PR.
        is_bns_internal = bool(source_dn)
        
        # Update is_bns_internal_supplier field
        if is_bns_internal != doc.get("is_bns_internal_supplier"):
            doc.is_bns_internal_supplier = is_bns_internal
        
        if is_bns_internal:
            # TRANSFER UNDER SAME GSTIN - from DN
            per_billed = 100
            doc.db_set("status", "BNS Internally Transferred", update_modified=False)
            doc.db_set("per_billed", per_billed, update_modified=False)
            doc.db_set("is_bns_internal_supplier", 1, update_modified=False)
            # Keep item-level BNS transfer rates aligned with DN item incoming_rate.
            if source_dn:
                _sync_pr_item_transfer_rate_from_dn(source_dn, pr_name=doc.name)
                _mirror_pr_item_valuation_from_transfer_rate(doc.name)
            # Ensure GL gets rebuilt with BNS rewrite even if initial submit happened
            # before patch load in this process.
            _trigger_bns_internal_gl_repost(doc, source="pr_on_submit_status_update")
            # Ensure Delivery Note is updated with linked PR (bidirectional link)
            if source_dn:
                _update_delivery_note_reference(source_dn, doc.name)
                frappe.clear_cache(doctype="Delivery Note")
            frappe.clear_cache(doctype="Purchase Receipt")
            logger.info(f"Updated Purchase Receipt {doc.name} status to BNS Internally Transferred (from DN)")
        else:
            # TRANSFER UNDER DIFFERENT GSTIN - from SI
            # Status should remain "To Bill" (default), but ensure it's set
            if doc.status != "To Bill":
                doc.db_set("status", "To Bill", update_modified=False)
            doc.db_set("is_bns_internal_supplier", 0, update_modified=False)
            frappe.clear_cache(doctype="Purchase Receipt")
            logger.info(f"Updated Purchase Receipt {doc.name} status to To Bill (from SI)")
        
    except Exception as e:
        logger.error(f"Error updating Purchase Receipt status: {str(e)}")
        raise


def _should_update_internal_status(doc, field_name: str, check_reference: bool = False) -> bool:
    """Check if the document status should be updated for internal transfers."""
    if doc.docstatus != 1:
        return False
        
    if check_reference:
        return bool(doc.bns_inter_company_reference or getattr(doc, field_name, False))
    
    return bool(getattr(doc, field_name, False))


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


def _mirror_pr_item_valuation_from_transfer_rate(pr_name: str) -> int:
    """Mirror PR item valuation_rate from bns_transfer_rate for DN->PR same-GSTIN flow."""
    if not pr_name or not frappe.db.exists("Purchase Receipt", pr_name):
        return 0

    pr_meta = frappe.get_meta("Purchase Receipt Item")
    if not pr_meta.has_field("bns_transfer_rate"):
        return 0

    pr = frappe.get_doc("Purchase Receipt", pr_name)
    if pr.docstatus != 1 or not pr.get("is_bns_internal_supplier"):
        return 0
    if not pr.get("supplier_delivery_note") or not frappe.db.exists("Delivery Note", pr.get("supplier_delivery_note")):
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

    if updated_count:
        frappe.clear_cache(doctype="Purchase Receipt")
        logger.info("Synced bns_transfer_rate for %s PR items from Delivery Note %s", updated_count, dn_name)

    return updated_count


def _trigger_pr_repost_for_transfer_rate(pr_name: str, source_repost_name: str) -> bool:
    """Trigger PR repost after transfer-rate mirror with cache guards."""
    if not pr_name or not frappe.db.exists("Purchase Receipt", pr_name):
        return False

    per_repost_key = f"bns_transfer_rate_pr_repost::{source_repost_name}::{pr_name}"
    if frappe.cache().get_value(per_repost_key):
        return False

    lock_key = f"bns_transfer_rate_pr_repost_lock::{pr_name}"
    if frappe.cache().get_value(lock_key):
        return False

    pr = frappe.get_doc("Purchase Receipt", pr_name)
    if pr.docstatus != 1:
        return False
    if not pr.get("is_bns_internal_supplier"):
        return False
    if not pr.get("supplier_delivery_note") or not frappe.db.exists("Delivery Note", pr.get("supplier_delivery_note")):
        return False

    _apply_bns_transfer_rate_stock_ledger_patch()
    pr.repost_future_sle_and_gle(force=True)
    frappe.cache().set_value(per_repost_key, 1, expires_in_sec=6 * 60 * 60)
    frappe.cache().set_value(lock_key, 1, expires_in_sec=10 * 60)
    logger.info("Triggered PR repost for transfer-rate sync: %s (source repost: %s)", pr_name, source_repost_name)
    return True


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

    dn_names = set()
    if doc.get("based_on") == "Transaction" and doc.get("voucher_type") == "Delivery Note" and doc.get("voucher_no"):
        dn_names.add(doc.get("voucher_no"))

    try:
        from erpnext.stock.stock_ledger import get_affected_transactions
        affected = get_affected_transactions(doc)
    except Exception:
        affected = set()

    for voucher_type, voucher_no in affected:
        if voucher_type == "Delivery Note" and voucher_no:
            dn_names.add(voucher_no)

    if not dn_names:
        frappe.cache().set_value(cache_key, 1, expires_in_sec=6 * 60 * 60)
        return

    total_updated = 0
    total_mirrored = 0
    affected_prs = set()
    for dn_name in dn_names:
        for pr_name in _get_submitted_prs_for_dn(dn_name):
            updated = _sync_pr_item_transfer_rate_from_dn(dn_name, pr_name=pr_name)
            mirrored = _mirror_pr_item_valuation_from_transfer_rate(pr_name)
            total_updated += updated
            total_mirrored += mirrored
            if updated or mirrored:
                affected_prs.add(pr_name)

    triggered_count = 0
    for pr_name in sorted(affected_prs):
        if _trigger_pr_repost_for_transfer_rate(pr_name, source_repost_name=doc.name):
            triggered_count += 1

    if total_updated or total_mirrored or triggered_count:
        logger.info(
            "Repost %s: transfer-rate sync=%s, valuation mirror=%s, PR repost triggered=%s for %s Delivery Notes and %s PRs",
            doc.name,
            total_updated,
            total_mirrored,
            triggered_count,
            len(dn_names),
            len(affected_prs),
        )

    frappe.cache().set_value(cache_key, 1, expires_in_sec=6 * 60 * 60)


def _calculate_per_billed(doc) -> int:
    """Calculate the per_billed value based on GSTIN comparison."""
    per_billed = 100
    billing_address_gstin = getattr(doc, 'billing_address_gstin', None)
    company_gstin = getattr(doc, 'company_gstin', None)
    
    if billing_address_gstin is not None and company_gstin is not None:
        if billing_address_gstin != company_gstin:
            per_billed = 0
            
    return per_billed


def _update_document_status(doc, doctype: str, per_billed: int) -> None:
    """Update document status and per_billed value."""
    update_fields = {
        "status": "BNS Internally Transferred"
    }
    
    # Only set per_billed for doctypes that have this field (Delivery Note, Purchase Receipt)
    if doctype in ["Delivery Note", "Purchase Receipt"]:
        update_fields["per_billed"] = per_billed
    
    frappe.db.set_value(doctype, doc.name, update_fields)
    frappe.clear_cache(doctype=doctype) 


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
    try:
        si = frappe.get_doc("Sales Invoice", source_name)
        
        # Validate sales invoice for internal customer
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
            source_item_filter=lambda d: flt(d.get("qty") or 0) > 0,
            source_label="Sales Invoice",
            target_label="Purchase Invoice",
        )
        
        # Validate quantities
        validate_internal_transfer_qty(doclist)
        
        # Update sales invoice with reference (this needs to be done after the document is created)
        _update_sales_invoice_reference(si.name, doclist.name)
        
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
            "field_no_map": ["expense_account", "cost_center", "project", "location"],
            "condition": lambda item: flt(item.qty or 0) > 0,
            "postprocess": _update_item_pi,
        },
    }
    
    # Add warehouse, serial_no, batch_no mapping if update_stock is enabled
    # Note: We'll check this in postprocess, but prepare the mapping structure
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
    # Handle case where source_parent might be None (when called as postprocess)
    if source_parent is None:
        # This is being called as a postprocess function, so we need to get the data differently
        # The source_doc is the Sales Invoice, and target_doc is the Purchase Invoice
        represents_company = _get_representing_company_from_customer(source_doc.customer)
        target_doc.company = represents_company
        
        # Find supplier representing the sales invoice's company
        supplier = _find_internal_supplier(represents_company)
        target_doc.supplier = supplier
        
        # Set internal transfer fields
        target_doc.buying_price_list = source_doc.selling_price_list
        # Do NOT set is_internal_supplier - only set is_bns_internal_supplier for BNS internal transfers
        # Use bns_inter_company_reference instead of inter_company_invoice_reference to avoid ERPNext validation
        target_doc.bns_inter_company_reference = source_doc.name
        
        # Set is_bns_internal_supplier = 1 (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.is_bns_internal_supplier = 1
        
        # Set supplier_invoice_number (bill_no) = SI name (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.bill_no = source_doc.name

        # Handle addresses
        _update_addresses_pi(target_doc, source_doc)
        
        # Handle taxes
        _update_taxes_pi(target_doc)
    else:
        # This is being called from the main function with proper parameters
        represents_company = _get_representing_company_from_customer(source_doc.customer)
        target_doc.company = represents_company
        
        # Find supplier representing the sales invoice's company
        supplier = _find_internal_supplier(represents_company)
        target_doc.supplier = supplier
        
        # Set internal transfer fields
        target_doc.buying_price_list = source_doc.selling_price_list
        # Do NOT set is_internal_supplier - only set is_bns_internal_supplier for BNS internal transfers
        # Use bns_inter_company_reference instead of inter_company_invoice_reference to avoid ERPNext validation
        target_doc.bns_inter_company_reference = source_doc.name
        
        # Set is_bns_internal_supplier = 1 (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.is_bns_internal_supplier = 1

        # Set supplier_invoice_number (bill_no) = SI name (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.bill_no = source_doc.name
        
        # Update sales invoice with reference
        _update_sales_invoice_reference(source_doc.name, target_doc.name)
        
        # Handle addresses
        _update_addresses_pi(target_doc, source_doc)
        
        # Handle taxes
        _update_taxes_pi(target_doc)


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
    
    # Map serial_no and batch_no if they exist (for stock items)
    if source.get("serial_no"):
        target.serial_no = source.serial_no
    if source.get("batch_no"):
        target.batch_no = source.batch_no
    
    # Clear accounting fields to let system auto-populate
    _clear_item_level_fields_pi(target)
    
    if source.get("use_serial_batch_fields"):
        target.set("use_serial_batch_fields", 1)


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
    try:
        si = frappe.get_doc("Sales Invoice", source_name)
        
        # Check if SI is made from Delivery Note (check items for delivery_note reference)
        has_dn_reference = False
        if si.items:
            has_dn_reference = any(item.get("delivery_note") for item in si.items if item.get("delivery_note"))
        
        # Validate sales invoice for internal customer
        # Only require update_stock if SI is NOT made from DN
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
                "serial_no": "serial_no",
                "batch_no": "batch_no",
            },
            "field_no_map": ["warehouse", "rejected_warehouse", "expense_account", "cost_center", "project", "location"],
            "condition": lambda item: flt(item.qty or 0) > 0,  # Sales Invoice Item doesn't have returned_qty or received_qty
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
    
    target.received_qty = 0
    
    _clear_item_level_fields(target)
    
    if source.get("use_serial_batch_fields"):
        target.set("use_serial_batch_fields", 1)


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
    # Guard: prevent infinite loops - if already updated, skip
    if doc.status == "BNS Internally Transferred":
        return
    
    # Ensure is_bns_internal_customer is set from Customer if not already set
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
    """
    Update the status of a Purchase Invoice to "BNS Internally Transferred" 
    when submitted for a BNS internal supplier with inter company reference.
    
    This handles:
    1. PI created directly from SI (via bns_inter_company_reference)
    2. PI created from PR that was created from SI (via PR.bns_inter_company_reference)
    
    Args:
        doc: The Purchase Invoice document
        method (Optional[str]): The method being called
    """
    if doc.docstatus != 1:
        return
    
    # Guard: prevent infinite loops - if already updated, skip
    if doc.status == "BNS Internally Transferred":
        return
    
    # Check if it's a BNS internal transfer
    is_bns_internal = is_bns_internal_supplier(doc)
    is_from_si = False

    if is_bns_internal:
        is_from_si = True
    elif doc.bns_inter_company_reference:
        # Directly created from Sales Invoice (using bns_inter_company_reference)
        # Check if bns_inter_company_reference points to a Sales Invoice
        if frappe.db.exists("Sales Invoice", doc.bns_inter_company_reference):
            is_from_si = True
    elif doc.items:
        # Check if PI is created from PR that was created from SI
        # Get Purchase Receipt references from items
        pr_names = set()
        for item in doc.items:
            if item.get("purchase_receipt"):
                pr_names.add(item.purchase_receipt)
        
        # Check if any PR was created from SI
        if pr_names:
            for pr_name in pr_names:
                pr_bns_ref = frappe.db.get_value("Purchase Receipt", pr_name, "bns_inter_company_reference")

                if pr_bns_ref and frappe.db.exists("Sales Invoice", pr_bns_ref):
                    is_from_si = True
                    break
    
    if not is_from_si:
        return
    
    try:
        # Ensure is_bns_internal_supplier is set
        if not doc.get("is_bns_internal_supplier"):
            doc.is_bns_internal_supplier = 1
        
        # Do not set standard represents_company on PI; use BNS fields only.
        
        # Update status immediately on document and in database using db_set
        doc.status = "BNS Internally Transferred"
        doc.db_set("status", "BNS Internally Transferred", update_modified=False)
        doc.db_set("is_bns_internal_supplier", 1, update_modified=False)
        
        # Set bidirectional bns_inter_company_reference
        si_name = None
        
        # Check bns_inter_company_reference first
        if doc.bns_inter_company_reference and frappe.db.exists("Sales Invoice", doc.bns_inter_company_reference):
            si_name = doc.bns_inter_company_reference
        # Check bill_no (supplier_invoice_no) - if it matches an SI name, use it
        elif doc.bill_no and frappe.db.exists("Sales Invoice", {"name": doc.bill_no, "docstatus": 1}):
            si_name = doc.bill_no
            # Set PI's bns_inter_company_reference if not already set
            if not doc.bns_inter_company_reference:
                doc.db_set("bns_inter_company_reference", si_name, update_modified=False)
        # Update SI's bns_inter_company_reference to point back to PI
        if si_name:
            si = frappe.get_doc("Sales Invoice", si_name)
            if not si.get("bns_inter_company_reference") or si.bns_inter_company_reference != doc.name:
                si.db_set("bns_inter_company_reference", doc.name, update_modified=False)
                # Also ensure SI status is updated if not already
                if si.status != "BNS Internally Transferred":
                    si.db_set("status", "BNS Internally Transferred", update_modified=False)
                frappe.clear_cache(doctype="Sales Invoice")
                logger.info(f"Updated Sales Invoice {si_name} bns_inter_company_reference to {doc.name}")
        
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
def validate_si_pi_items_match(sales_invoice: str, purchase_invoice: str, check_all: bool = False) -> Dict:
    """
    Validate that all Sales Invoice items and quantities match Purchase Invoice items.
    Optionally also validates taxable values, grand totals, and taxes.
    
    Args:
        sales_invoice (str): Name of the Sales Invoice
        purchase_invoice (str): Name of the Purchase Invoice
        check_all (bool): If True, also validates taxable values, totals, and taxes
        
    Returns:
        Dict: Validation result with match status and details
    """
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
                
                # Check taxable value mismatch if check_all is True (no tolerance)
                if check_all:
                    si_taxable_value = si_data["base_net_amount"] if si_data["base_net_amount"] > 0 else si_data["net_amount"]
                    pi_taxable_value = pi_data["base_net_amount"] if pi_data["base_net_amount"] > 0 else pi_data["net_amount"]
                    if round(flt(si_taxable_value), 2) != round(flt(pi_taxable_value), 2):
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
            if round(si_grand_total, 2) != round(pi_grand_total, 2):
                grand_total_mismatch = {
                    "si_total": si_grand_total,
                    "pi_total": pi_grand_total,
                    "diff": si_grand_total - pi_grand_total
                }
            
            # Compare total taxes and charges in company currency (no tolerance)
            si_base_taxes = flt(si.base_total_taxes_and_charges or 0)
            if si_base_taxes == 0:
                si_base_taxes = flt(si.total_taxes_and_charges or 0)
            pi_base_taxes = flt(pi.base_total_taxes_and_charges or 0)
            if pi_base_taxes == 0:
                pi_base_taxes = flt(pi.total_taxes_and_charges or 0)
            
            if round(si_base_taxes, 2) != round(pi_base_taxes, 2):
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
            pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
            
            # Validate PI is submitted
            if pi.docstatus != 1:
                raise BNSValidationError(_("Purchase Invoice {0} must be submitted before linking").format(purchase_invoice))
            
            # Validate items, quantities, rates, totals, and taxes (comprehensive check for auto-linking)
            validation_result = validate_si_pi_items_match(si.name, pi.name, check_all=True)
            if not validation_result.get("match"):
                missing = validation_result.get("missing_items", [])
                qty_mismatches = validation_result.get("qty_mismatches", [])
                taxable_value_mismatches = validation_result.get("taxable_value_mismatches", [])
                grand_total_mismatch = validation_result.get("grand_total_mismatch")
                tax_mismatch = validation_result.get("tax_mismatch")
                errors = []
                if missing:
                    for item in missing[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI has {1}, PI missing").format(item["item_code"], item["si_qty"]))
                if qty_mismatches:
                    for item in qty_mismatches[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI has {1}, PI has {2}").format(item["item_code"], item["si_qty"], item["pi_qty"]))
                if taxable_value_mismatches:
                    for item in taxable_value_mismatches[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI Taxable Value ₹{1:.2f}, PI Taxable Value ₹{2:.2f}").format(
                            item["item_code"], item["si_taxable_value"], item["pi_taxable_value"]
                        ))
                if grand_total_mismatch:
                    errors.append(_("Grand Total: SI ₹{0:.2f} vs PI ₹{1:.2f} (Diff: ₹{2:.2f})").format(
                        grand_total_mismatch["si_total"], grand_total_mismatch["pi_total"], abs(grand_total_mismatch["diff"])
                    ))
                if tax_mismatch:
                    errors.append(_("Total Taxes and Charges: SI ₹{0:.2f} vs PI ₹{1:.2f} (Diff: ₹{2:.2f})").format(
                        tax_mismatch["si_tax"], tax_mismatch["pi_tax"], abs(tax_mismatch["diff"])
                    ))
                
                if len(missing) > 3 or len(qty_mismatches) > 3 or len(taxable_value_mismatches) > 3:
                    errors.append(_("... and more mismatches"))
                raise BNSValidationError(_("Items, quantities, taxable values, totals, or taxes do not match: {0}").format("; ".join(errors)))
            
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
    try:
        # Get Purchase Invoice
        pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
        
        # Validate Purchase Invoice is submitted
        if pi.docstatus != 1:
            raise BNSValidationError(_("Purchase Invoice must be submitted before converting to BNS Internal"))
        
        # Check if supplier is BNS internal
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
            si = frappe.get_doc("Sales Invoice", sales_invoice)
            
            # Validate SI is submitted
            if si.docstatus != 1:
                raise BNSValidationError(_("Sales Invoice {0} must be submitted before linking").format(sales_invoice))
            
            # Validate items, quantities, rates, totals, and taxes (comprehensive check for auto-linking)
            validation_result = validate_si_pi_items_match(si.name, pi.name, check_all=True)
            if not validation_result.get("match"):
                missing = validation_result.get("missing_items", [])
                qty_mismatches = validation_result.get("qty_mismatches", [])
                taxable_value_mismatches = validation_result.get("taxable_value_mismatches", [])
                grand_total_mismatch = validation_result.get("grand_total_mismatch")
                tax_mismatch = validation_result.get("tax_mismatch")
                errors = []
                if missing:
                    for item in missing[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI has {1}, PI missing").format(item["item_code"], item["si_qty"]))
                if qty_mismatches:
                    for item in qty_mismatches[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI has {1}, PI has {2}").format(item["item_code"], item["si_qty"], item["pi_qty"]))
                if taxable_value_mismatches:
                    for item in taxable_value_mismatches[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI Taxable Value ₹{1:.2f}, PI Taxable Value ₹{2:.2f}").format(
                            item["item_code"], item["si_taxable_value"], item["pi_taxable_value"]
                        ))
                if grand_total_mismatch:
                    errors.append(_("Grand Total: SI ₹{0:.2f} vs PI ₹{1:.2f} (Diff: ₹{2:.2f})").format(
                        grand_total_mismatch["si_total"], grand_total_mismatch["pi_total"], abs(grand_total_mismatch["diff"])
                    ))
                if tax_mismatch:
                    errors.append(_("Total Taxes and Charges: SI ₹{0:.2f} vs PI ₹{1:.2f} (Diff: ₹{2:.2f})").format(
                        tax_mismatch["si_tax"], tax_mismatch["pi_tax"], abs(tax_mismatch["diff"])
                    ))
                
                if len(missing) > 3 or len(qty_mismatches) > 3 or len(taxable_value_mismatches) > 3:
                    errors.append(_("... and more mismatches"))
                raise BNSValidationError(_("Items, quantities, taxable values, totals, or taxes do not match: {0}").format("; ".join(errors)))
            
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
        
        if billing_address_gstin != company_gstin:
            raise BNSValidationError(
                _("GSTIN mismatch: billing_address_gstin ({0}) != company_gstin ({1}). Only same GSTIN transfers can be converted.").format(
                    billing_address_gstin, company_gstin
                )
            )
        
        # Check if already fully converted (both flag and status are set)
        if dn.get("is_bns_internal_customer") and dn.status == "BNS Internally Transferred":
            # Already converted, but still return success for bulk operations
            return {"success": True, "message": _("Already converted")}
        
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
        
        # If Purchase Receipt is provided, validate and link
        if purchase_receipt:
            pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
            
            # Validate PR is submitted
            if pr.docstatus != 1:
                raise BNSValidationError(_("Purchase Receipt {0} must be submitted before linking").format(purchase_receipt))
            
            # Validate PR's supplier_delivery_note matches DN name
            if pr.supplier_delivery_note != dn.name:
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
            
            # Check if PR already linked to another DN
            existing_ref = pr.get("bns_inter_company_reference")
            if existing_ref and existing_ref != dn.name:
                raise BNSValidationError(
                    _("Purchase Receipt {0} is already linked to Delivery Note {1}").format(
                        purchase_receipt, existing_ref
                    )
                )
            
            # Update Purchase Receipt document-level fields
            pr.db_set("is_bns_internal_supplier", 1, update_modified=False)
            pr.db_set("status", "BNS Internally Transferred", update_modified=False)
            pr.db_set("per_billed", 100, update_modified=False)
            if not pr.get("bns_inter_company_reference"):
                pr.db_set("bns_inter_company_reference", dn.name, update_modified=False)
            
            # Then update Delivery Note reference
            if not dn.get("bns_inter_company_reference"):
                dn.db_set("bns_inter_company_reference", pr.name, update_modified=False)
            
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
    try:
        # Get Purchase Receipt
        pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
        
        # Validate Purchase Receipt is submitted
        if pr.docstatus != 1:
            raise BNSValidationError(_("Purchase Receipt must be submitted before converting to BNS Internal"))
        
        # Check if supplier_delivery_note exists and is a DN
        if not pr.supplier_delivery_note:
            raise BNSValidationError(_("Purchase Receipt must be created from a Delivery Note (supplier_delivery_note is missing)"))
        
        dn_exists = frappe.db.exists("Delivery Note", pr.supplier_delivery_note)
        if not dn_exists:
            raise BNSValidationError(_("Purchase Receipt supplier_delivery_note ({0}) is not a valid Delivery Note").format(pr.supplier_delivery_note))
        
        # Get the Delivery Note to validate GSTIN
        dn = frappe.get_doc("Delivery Note", pr.supplier_delivery_note)
        
        # Validate DN customer is BNS internal
        customer_internal = frappe.db.get_value("Customer", dn.customer, "is_bns_internal_customer")
        if not customer_internal:
            raise BNSValidationError(_("Delivery Note customer {0} is not marked as BNS Internal Customer").format(dn.customer))
        
        # Validate GSTIN match (same GSTIN only)
        dn_billing_gstin = getattr(dn, 'billing_address_gstin', None)
        dn_company_gstin = getattr(dn, 'company_gstin', None)
        pr_company_gstin = getattr(pr, 'company_gstin', None)
        
        if dn_billing_gstin is None or dn_company_gstin is None:
            raise BNSValidationError(_("Delivery Note GSTIN information is missing. Cannot convert to BNS Internal transfer."))
        
        if dn_billing_gstin != dn_company_gstin:
            raise BNSValidationError(
                _("Delivery Note GSTIN mismatch: billing_address_gstin ({0}) != company_gstin ({1}). Only same GSTIN transfers can be converted.").format(
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
        
        # Update Purchase Receipt (even if flag is already set, ensure status is updated)
        pr.db_set("is_bns_internal_supplier", 1, update_modified=False)
        pr.db_set("status", "BNS Internally Transferred", update_modified=False)
        pr.db_set("per_billed", 100, update_modified=False)
        if not pr.get("bns_inter_company_reference"):
            pr.db_set("bns_inter_company_reference", linked_dn, update_modified=False)
        
        result = {
            "success": True,
            "message": _("Purchase Receipt converted to BNS Internally Transferred"),
            "purchase_receipt": pr.name
        }
        
        # Update Delivery Note if not already updated
        if linked_dn:
            dn_reload = frappe.get_doc("Delivery Note", linked_dn)
            if not dn_reload.get("bns_inter_company_reference"):
                dn_reload.db_set("bns_inter_company_reference", pr.name, update_modified=False)
            if dn_reload.status != "BNS Internally Transferred":
                dn_reload.db_set("status", "BNS Internally Transferred", update_modified=False)
            if not dn_reload.get("is_bns_internal_customer"):
                dn_reload.db_set("is_bns_internal_customer", 1, update_modified=False)
            if dn_reload.per_billed != 100:
                dn_reload.db_set("per_billed", 100, update_modified=False)
            
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
        ]
    elif doc.doctype == "Purchase Invoice":
        ignore_linked_doctypes = [
            # Keep accounting-link safety consistent
            "GL Entry",
            "Sales Invoice",
            "Payment Ledger Entry",
            "Advance Payment Ledger Entry",
        ]
    else:
        return

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
    Block return entries (Credit Notes) for BNS internal customers.
    
    Args:
        doc: The Sales Invoice document
        method (Optional[str]): The method being called
    """
    if not doc.is_return or not doc.return_against:
        return
    
    try:
        # Get the original Sales Invoice
        original_si = frappe.get_doc("Sales Invoice", doc.return_against)
        
        # Check if original SI is for BNS internal customer
        is_bns_internal = original_si.get("is_bns_internal_customer") or False
        if not is_bns_internal:
            # Check customer's is_bns_internal_customer field
            customer_internal = frappe.db.get_value("Customer", original_si.customer, "is_bns_internal_customer")
            if customer_internal:
                is_bns_internal = True
        
        if is_bns_internal:
            frappe.throw(
                _("Returns (Credit Notes) are not allowed for BNS Internal Customers. Original Sales Invoice {0} is for a BNS Internal Customer.").format(
                    get_link_to_form("Sales Invoice", doc.return_against)
                ),
                title=_("Return Not Allowed")
            )
    except frappe.DoesNotExistError:
        # Original document doesn't exist, let ERPNext handle this validation
        pass
    except Exception as e:
        logger.error(f"Error validating BNS internal customer return for Sales Invoice: {str(e)}")
        # Don't block if there's an error, but log it
        pass


def validate_bns_internal_delivery_note_return(doc, method: Optional[str] = None) -> None:
    """
    Block return entries for Delivery Notes with BNS internal customers.
    
    Args:
        doc: The Delivery Note document
        method (Optional[str]): The method being called
    """
    if not doc.is_return or not doc.return_against:
        return
    
    try:
        # Get the original Delivery Note
        original_dn = frappe.get_doc("Delivery Note", doc.return_against)
        
        # Check if original DN is for BNS internal customer
        is_bns_internal = original_dn.get("is_bns_internal_customer") or False
        if not is_bns_internal:
            # Check customer's is_bns_internal_customer field
            customer_internal = frappe.db.get_value("Customer", original_dn.customer, "is_bns_internal_customer")
            if customer_internal:
                is_bns_internal = True
        
        if is_bns_internal:
            frappe.throw(
                _("Returns are not allowed for BNS Internal Customers. Original Delivery Note {0} is for a BNS Internal Customer.").format(
                    get_link_to_form("Delivery Note", doc.return_against)
                ),
                title=_("Return Not Allowed")
            )
    except frappe.DoesNotExistError:
        # Original document doesn't exist, let ERPNext handle this validation
        pass
    except Exception as e:
        logger.error(f"Error validating BNS internal customer return for Delivery Note: {str(e)}")
        # Don't block if there's an error, but log it
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
    try:
        dn = frappe.get_doc("Delivery Note", delivery_note)
        pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
        
        # Validate both documents are submitted
        if dn.docstatus != 1:
            raise BNSValidationError(_("Delivery Note must be submitted before linking"))
        
        if pr.docstatus != 1:
            raise BNSValidationError(_("Purchase Receipt must be submitted before linking"))
        
        # Validate PR's supplier_delivery_note matches DN name (only if supplier_delivery_note is set)
        # Allow linking even if supplier_delivery_note is empty or doesn't match
        if pr.supplier_delivery_note and pr.supplier_delivery_note != dn.name:
            # If supplier_delivery_note is set but doesn't match, warn but allow
            logger.warning(f"Purchase Receipt {purchase_receipt} has supplier_delivery_note {pr.supplier_delivery_note} but linking to {delivery_note}")
            # Don't raise error - allow manual linking
        
        # Validate GSTIN match (same GSTIN only)
        dn_billing_gstin = getattr(dn, 'billing_address_gstin', None)
        dn_company_gstin = getattr(dn, 'company_gstin', None)
        
        if not dn_billing_gstin or not dn_company_gstin:
            raise BNSValidationError(_("Delivery Note GSTIN information is missing"))
        
        if dn_billing_gstin != dn_company_gstin:
            raise BNSValidationError(
                _("GSTIN mismatch: Only same GSTIN transfers can be linked. billing_address_gstin ({0}) != company_gstin ({1})").format(
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
        
        # Check if DN is already linked to another PR
        if dn.get("bns_inter_company_reference") and dn.get("bns_inter_company_reference") != pr.name:
            raise BNSValidationError(
                _("Delivery Note {0} is already linked to Purchase Receipt {1}").format(
                    delivery_note, dn.get("bns_inter_company_reference")
                )
            )
        
        # Check if PR is already linked to another DN
        if pr.get("bns_inter_company_reference") and pr.get("bns_inter_company_reference") != dn.name:
            raise BNSValidationError(
                _("Purchase Receipt {0} is already linked to Delivery Note {1}").format(
                    purchase_receipt, pr.get("bns_inter_company_reference")
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
    """Allow unlink recovery operations only to Administrator/System Manager."""
    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    if user == "Administrator" or "System Manager" in roles:
        return

    frappe.throw(
        _("Only Administrator/System Manager can run {0}.").format(action),
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
    try:
        si = frappe.get_doc("Sales Invoice", sales_invoice)
        pr = frappe.get_doc("Purchase Receipt", purchase_receipt)

        if si.docstatus != 1:
            raise BNSValidationError(_("Sales Invoice must be submitted before linking"))
        if pr.docstatus != 1:
            raise BNSValidationError(_("Purchase Receipt must be submitted before linking"))

        # Validate different GSTIN only (SI->PR flow)
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
    try:
        si = frappe.get_doc("Sales Invoice", sales_invoice)
        pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
        
        # Validate both documents are submitted
        if si.docstatus != 1:
            raise BNSValidationError(_("Sales Invoice must be submitted before linking"))
        
        if pi.docstatus != 1:
            raise BNSValidationError(_("Purchase Invoice must be submitted before linking"))
        
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
        
        # Check if SI is already linked to another PI
        if si.get("bns_inter_company_reference") and si.get("bns_inter_company_reference") != pi.name:
            raise BNSValidationError(
                _("Sales Invoice {0} is already linked to Purchase Invoice {1}").format(
                    sales_invoice, si.get("bns_inter_company_reference")
                )
            )
        
        # Check if PI is already linked to another SI
        if pi.get("bns_inter_company_reference") and pi.get("bns_inter_company_reference") != si.name:
            raise BNSValidationError(
                _("Purchase Invoice {0} is already linked to Sales Invoice {1}").format(
                    purchase_invoice, pi.get("bns_inter_company_reference")
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
                si_cleared = True
            else:
                logger.warning(f"Sales Invoice {sales_invoice} does not exist — skipping its side of unlink")
        
        if purchase_invoice:
            if frappe.db.exists("Purchase Invoice", purchase_invoice):
                pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
                if pi.get("bns_inter_company_reference"):
                    pi.db_set("bns_inter_company_reference", "", update_modified=False)
                # Clear item-wise references
                for pi_item in pi.items:
                    if pi_item.get("sales_invoice_item"):
                        pi_item.db_set("sales_invoice_item", "", update_modified=False)
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


@frappe.whitelist()
def get_bulk_conversion_preview(from_date: str, force: int = 0) -> Dict:
    """
    Get preview of documents that can be bulk converted to BNS Internal.
    
    Args:
        from_date (str): Date filter (YYYY-MM-DD)
        force (int): If 1, include documents even if flag is already set
        
    Returns:
        Dict: Counts of documents that can be converted
    """
    try:
        from_date_obj = frappe.utils.getdate(from_date)
        
        # Build filters
        si_filters = [
            ["docstatus", "=", 1],
            ["posting_date", ">=", from_date_obj],
            ["customer", "!=", ""]
        ]
        
        pi_filters = [
            ["docstatus", "=", 1],
            ["posting_date", ">=", from_date_obj],
            ["supplier", "!=", ""]
        ]
        
        dn_filters = [
            ["docstatus", "=", 1],
            ["posting_date", ">=", from_date_obj],
            ["customer", "!=", ""]
        ]
        
        pr_filters = [
            ["docstatus", "=", 1],
            ["posting_date", ">=", from_date_obj],
            ["supplier_delivery_note", "!=", ""]
        ]
        
        # Get counts for Sales Invoice
        si_count = 0
        si_list = frappe.get_all(
            "Sales Invoice",
            filters=si_filters,
            fields=["name", "customer", "is_bns_internal_customer", "status"],
            limit=10000
        )
        for si in si_list:
            customer_internal = frappe.db.get_value("Customer", si.customer, "is_bns_internal_customer")
            if customer_internal:
                if force or not si.get("is_bns_internal_customer") or si.status != "BNS Internally Transferred":
                    si_count += 1
        
        # Get counts for Purchase Invoice
        pi_count = 0
        pi_list = frappe.get_all(
            "Purchase Invoice",
            filters=pi_filters,
            fields=["name", "supplier", "is_bns_internal_supplier", "status"],
            limit=10000
        )
        for pi in pi_list:
            supplier_internal = frappe.db.get_value("Supplier", pi.supplier, "is_bns_internal_supplier")
            if supplier_internal:
                if force or not pi.get("is_bns_internal_supplier") or pi.status != "BNS Internally Transferred":
                    pi_count += 1
        
        # Get counts for Delivery Note (same GSTIN only)
        dn_count = 0
        dn_list = frappe.get_all(
            "Delivery Note",
            filters=dn_filters,
            fields=["name", "customer", "is_bns_internal_customer", "status", "billing_address_gstin", "company_gstin"],
            limit=10000
        )
        for dn in dn_list:
            customer_internal = frappe.db.get_value("Customer", dn.customer, "is_bns_internal_customer")
            if customer_internal:
                # Check GSTIN match (same GSTIN only)
                billing_gstin = dn.get("billing_address_gstin")
                company_gstin = dn.get("company_gstin")
                if billing_gstin and company_gstin and billing_gstin == company_gstin:
                    if force or not dn.get("is_bns_internal_customer") or dn.status != "BNS Internally Transferred":
                        dn_count += 1
        
        # Get counts for Purchase Receipt (from DN with same GSTIN)
        pr_count = 0
        pr_list = frappe.get_all(
            "Purchase Receipt",
            filters=pr_filters,
            fields=["name", "supplier_delivery_note", "is_bns_internal_supplier", "status"],
            limit=10000
        )
        for pr in pr_list:
            if pr.supplier_delivery_note:
                # Check if supplier_delivery_note is a Delivery Note
                if frappe.db.exists("Delivery Note", pr.supplier_delivery_note):
                    dn_name = pr.supplier_delivery_note
                    dn_customer = frappe.db.get_value("Delivery Note", dn_name, "customer")
                    if dn_customer:
                        customer_internal = frappe.db.get_value("Customer", dn_customer, "is_bns_internal_customer")
                        if customer_internal:
                            # Check GSTIN match
                            dn_billing_gstin = frappe.db.get_value("Delivery Note", dn_name, "billing_address_gstin")
                            dn_company_gstin = frappe.db.get_value("Delivery Note", dn_name, "company_gstin")
                            if dn_billing_gstin and dn_company_gstin and dn_billing_gstin == dn_company_gstin:
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
def bulk_convert_to_bns_internal(from_date: str, force: int = 0) -> Dict:
    """
    Bulk convert documents to BNS Internally Transferred status.
    
    Args:
        from_date (str): Date filter (YYYY-MM-DD)
        force (int): If 1, update even if flag is already set
        
    Returns:
        Dict: Results with counts of converted documents
    """
    try:
        from_date_obj = frappe.utils.getdate(from_date)
        converted = {
            "sales_invoice": 0,
            "purchase_invoice": 0,
            "delivery_note": 0,
            "purchase_receipt": 0
        }
        
        # Convert Sales Invoices
        si_list = frappe.get_all(
            "Sales Invoice",
            filters=[
                ["docstatus", "=", 1],
                ["posting_date", ">=", from_date_obj],
                ["customer", "!=", ""]
            ],
            fields=["name", "customer", "is_bns_internal_customer", "status"],
            limit=10000
        )
        for si in si_list:
            customer_internal = frappe.db.get_value("Customer", si.customer, "is_bns_internal_customer")
            if customer_internal:
                if force or not si.get("is_bns_internal_customer") or si.status != "BNS Internally Transferred":
                    try:
                        convert_sales_invoice_to_bns_internal(si.name, None)
                        converted["sales_invoice"] += 1
                    except Exception as e:
                        logger.error(f"Error converting Sales Invoice {si.name}: {str(e)}")
                        continue
        
        # Convert Purchase Invoices
        pi_list = frappe.get_all(
            "Purchase Invoice",
            filters=[
                ["docstatus", "=", 1],
                ["posting_date", ">=", from_date_obj],
                ["supplier", "!=", ""]
            ],
            fields=["name", "supplier", "is_bns_internal_supplier", "status"],
            limit=10000
        )
        for pi in pi_list:
            supplier_internal = frappe.db.get_value("Supplier", pi.supplier, "is_bns_internal_supplier")
            if supplier_internal:
                if force or not pi.get("is_bns_internal_supplier") or pi.status != "BNS Internally Transferred":
                    try:
                        convert_purchase_invoice_to_bns_internal(pi.name, None)
                        converted["purchase_invoice"] += 1
                    except Exception as e:
                        logger.error(f"Error converting Purchase Invoice {pi.name}: {str(e)}")
                        continue
        
        # Convert Delivery Notes (same GSTIN only)
        dn_list = frappe.get_all(
            "Delivery Note",
            filters=[
                ["docstatus", "=", 1],
                ["posting_date", ">=", from_date_obj],
                ["customer", "!=", ""]
            ],
            fields=["name", "customer", "is_bns_internal_customer", "status", "billing_address_gstin", "company_gstin"],
            limit=10000
        )
        for dn in dn_list:
            customer_internal = frappe.db.get_value("Customer", dn.customer, "is_bns_internal_customer")
            if customer_internal:
                billing_gstin = dn.get("billing_address_gstin")
                company_gstin = dn.get("company_gstin")
                if billing_gstin and company_gstin and billing_gstin == company_gstin:
                    if force or not dn.get("is_bns_internal_customer") or dn.status != "BNS Internally Transferred":
                        try:
                            result = convert_delivery_note_to_bns_internal(dn.name, None)
                            if result.get("success"):
                                converted["delivery_note"] += 1
                        except Exception as e:
                            logger.error(f"Error converting Delivery Note {dn.name}: {str(e)}")
                            frappe.log_error(f"Error converting Delivery Note {dn.name}: {str(e)}", "BNS Bulk Conversion")
                            continue
        
        # Convert Purchase Receipts (from DN with same GSTIN)
        pr_list = frappe.get_all(
            "Purchase Receipt",
            filters=[
                ["docstatus", "=", 1],
                ["posting_date", ">=", from_date_obj],
                ["supplier_delivery_note", "!=", ""]
            ],
            fields=["name", "supplier_delivery_note", "is_bns_internal_supplier", "status"],
            limit=10000
        )
        for pr in pr_list:
            if pr.supplier_delivery_note and frappe.db.exists("Delivery Note", pr.supplier_delivery_note):
                dn_name = pr.supplier_delivery_note
                dn_customer = frappe.db.get_value("Delivery Note", dn_name, "customer")
                if dn_customer:
                    customer_internal = frappe.db.get_value("Customer", dn_customer, "is_bns_internal_customer")
                    if customer_internal:
                        dn_billing_gstin = frappe.db.get_value("Delivery Note", dn_name, "billing_address_gstin")
                        dn_company_gstin = frappe.db.get_value("Delivery Note", dn_name, "company_gstin")
                        if dn_billing_gstin and dn_company_gstin and dn_billing_gstin == dn_company_gstin:
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