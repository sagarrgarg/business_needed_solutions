"""
Business Needed Solutions - Auto-Paid Supplier

For suppliers flagged ``bns_auto_paid_supplier`` on the Supplier master,
every Purchase Invoice is forced to submit as fully paid via the
supplier's configured Mode of Payment. The cash/bank account is resolved
from the Mode of Payment's company-wise Accounts table (same lookup
ERPNext does client-side when a Mode of Payment is selected).

Result: PI submission posts a single GL that both creates and immediately
discharges the payable -- outstanding stays 0 from the moment of submit.
Returns are handled symmetrically (negative paid_amount -> refund).

Supplier master is authoritative: even if the user manually toggled
is_paid or picked a different Mode of Payment, this hook overwrites those
values when the flag is set. Misconfigured flagged suppliers throw a
clear error at validate time so the master record gets fixed instead of
surfacing as a cryptic ERPNext payment error later.

Internal-branch suppliers (``is_bns_internal_supplier``) are out of scope
-- they use the dedicated branch creditor flow.
"""

import frappe
from frappe import _, bold


def auto_mark_paid(doc, method=None):
    """
    ``validate`` hook for Purchase Invoice.

    No-op unless the supplier carries the ``bns_auto_paid_supplier`` flag.
    When flagged, forces the Is-Paid block on the PI to match the supplier
    master, throwing early on misconfiguration.
    """
    # Internal-branch flow is handled separately and must not be auto-paid.
    if doc.get("is_bns_internal_supplier"):
        return
    if not doc.supplier:
        return

    supplier = frappe.get_cached_doc("Supplier", doc.supplier)
    if not supplier.get("bns_auto_paid_supplier"):
        return

    mop = supplier.get("bns_auto_paid_mode_of_payment")
    if not mop:
        frappe.throw(
            _(
                "Supplier {0} is marked as auto-paid but no Mode of Payment "
                "is configured. Set 'Auto-Paid Mode of Payment' on the "
                "Supplier master."
            ).format(bold(doc.supplier)),
            title=_("Auto-Paid Supplier: Mode of Payment Missing"),
        )

    if not doc.company:
        # validate normally runs after company defaulting; defensive guard.
        return

    account = _resolve_mop_account(mop, doc.company)
    if not account:
        frappe.throw(
            _(
                "Mode of Payment {0} has no default account configured for "
                "company {1}. Add a row under the Mode of Payment's Accounts "
                "table before submitting Purchase Invoices for {2}."
            ).format(bold(mop), bold(doc.company), bold(doc.supplier)),
            title=_("Auto-Paid Supplier: Account Missing"),
        )

    # Supplier master is authoritative -- overwrite any manual entries.
    # paid_amount inherits sign from rounded_total, so returns refund
    # correctly without special-casing here.
    doc.is_paid = 1
    doc.mode_of_payment = mop
    doc.cash_bank_account = account
    doc.paid_amount = doc.rounded_total or doc.grand_total
    doc.base_paid_amount = doc.base_rounded_total or doc.base_grand_total


def _resolve_mop_account(mop, company):
    """Return the company-specific default account for a Mode of Payment.

    Same lookup ERPNext does client-side when a Mode of Payment is picked
    on a Payment Entry / Sales Invoice / Purchase Invoice.
    """
    if not (mop and company):
        return None
    return frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mop, "company": company},
        "default_account",
    )


# ---------------------------------------------------------------------------
# Backfill: bring historical PIs in line with the auto-paid policy
# ---------------------------------------------------------------------------

_BACKFILL_LIVE_LIMIT = 200


@frappe.whitelist()
def backfill_auto_paid_supplier(
    supplier=None,
    from_date=None,
    to_date=None,
    dry_run=1,
):
    """Bring historical Purchase Invoices for flagged suppliers in line with
    the auto-paid policy.

    For each submitted PI in scope:
      1. Inspect linked Payment Entries. PEs that used the wrong cash/bank
         account are cancelled and recreated against the supplier's MOP
         account (only if the PE references this PI alone; multi-PI PEs are
         reported and skipped).
      2. After step 1, any residual outstanding amount is paid via a new
         Payment Entry on the correct account.

    Returns a structured report; no direct GL Entry mutation.

    Args:
        supplier: Restrict to one Supplier name. Blank = every flagged supplier.
        from_date / to_date: Posting-date window. Blank = unbounded.
        dry_run: 1 (default) plans without writing. 0 actually applies changes
                 and is capped at ``_BACKFILL_LIVE_LIMIT`` PIs per call to
                 keep operations chunked.
    """
    from frappe.utils import cint

    # Permission gate: same role as BNS Settings write — operators only.
    if not frappe.has_permission("BNS Settings", "write"):
        frappe.throw(
            _("You need write permission on BNS Settings to run this backfill."),
            frappe.PermissionError,
        )

    dry_run = cint(dry_run)
    pis = _scope_pis_for_backfill(supplier, from_date, to_date)

    if not dry_run and len(pis) > _BACKFILL_LIVE_LIMIT:
        frappe.throw(
            _(
                "Backfill scope is {0} Purchase Invoices, above the live-run "
                "cap of {1}. Narrow the date range or run per supplier."
            ).format(len(pis), _BACKFILL_LIVE_LIMIT),
            title=_("Backfill Scope Too Large"),
        )

    rows = []
    for pi in pis:
        try:
            rows.append(_process_pi_for_backfill(pi, dry_run))
        except Exception as exc:
            frappe.log_error(
                title="Auto-Paid Supplier Backfill",
                message=f"PI {pi.name}: {exc}\n{frappe.get_traceback()}",
            )
            rows.append({"pi": pi.name, "status": "error", "reason": str(exc)})

    return {
        "dry_run": bool(dry_run),
        "total": len(rows),
        "by_status": _summarize(rows),
        "rows": rows,
    }


def _scope_pis_for_backfill(supplier, from_date, to_date):
    """Find candidate Purchase Invoices for the backfill.

    Submitted only. Excludes PIs already at outstanding=0 *and* with no
    linked PEs on a wrong account — re-running the backfill on an already-
    clean PI is harmless but wastes a round-trip, so we filter coarsely
    here and let _process_pi_for_backfill be the source of truth.
    """
    filters = {"docstatus": 1}
    if supplier:
        filters["supplier"] = supplier
    else:
        flagged = frappe.get_all(
            "Supplier",
            filters={"bns_auto_paid_supplier": 1},
            pluck="name",
        )
        if not flagged:
            return []
        filters["supplier"] = ("in", flagged)
    if from_date:
        filters["posting_date"] = (">=", from_date)
    if to_date:
        # Combine with from_date if both supplied
        if "posting_date" in filters:
            filters["posting_date"] = ("between", [from_date, to_date])
        else:
            filters["posting_date"] = ("<=", to_date)

    return frappe.get_all(
        "Purchase Invoice",
        filters=filters,
        fields=[
            "name", "supplier", "company", "posting_date",
            "outstanding_amount", "grand_total", "is_return",
        ],
        order_by="posting_date asc, name asc",
    )


def _linked_payment_entries(pi_name):
    """All submitted Payment Entries referencing this PI.

    Returns list of dicts with: ``name``, ``allocated_amount``,
    ``payment_type``, ``cash_bank_account`` (normalised for Pay vs Receive),
    ``mode_of_payment``, ``posting_date``, ``referenced_pis``.
    """
    rows = frappe.db.sql(
        """
        SELECT  per.parent           AS name,
                per.allocated_amount AS allocated_amount,
                pe.payment_type      AS payment_type,
                pe.paid_from         AS paid_from,
                pe.paid_to           AS paid_to,
                pe.mode_of_payment   AS mode_of_payment,
                pe.posting_date      AS posting_date
        FROM    `tabPayment Entry Reference` per
        JOIN    `tabPayment Entry`           pe ON pe.name = per.parent
        WHERE   per.reference_doctype = 'Purchase Invoice'
          AND   per.reference_name    = %s
          AND   pe.docstatus          = 1
        """,
        (pi_name,),
        as_dict=True,
    )
    for r in rows:
        # For a Pay-type PE against a PI, paid_from is the cash/bank account
        # (money leaving us). For Receive (refund from supplier), it's
        # paid_to. Normalise so callers compare against a single field.
        r["cash_bank_account"] = (
            r["paid_to"] if r["payment_type"] == "Receive" else r["paid_from"]
        )
        r["referenced_pis"] = frappe.get_all(
            "Payment Entry Reference",
            filters={"parent": r["name"], "reference_doctype": "Purchase Invoice"},
            pluck="reference_name",
        )
    return rows


def _make_pe_for_pi(pi_name, mop, account, amount, posting_date, reference_no):
    """Build (and save, not submit) a Payment Entry for a single PI allocation.

    Uses ERPNext's ``get_payment_entry`` to inherit party + currency wiring,
    then overrides MOP, cash/bank account, amount, and posting date.
    """
    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

    pe = get_payment_entry("Purchase Invoice", pi_name)
    pe.mode_of_payment = mop
    # Pay vs Receive: paid_from is cash/bank for Pay, paid_to for Receive.
    if pe.payment_type == "Receive":
        pe.paid_to = account
    else:
        pe.paid_from = account
    pe.paid_amount = abs(amount)
    pe.received_amount = abs(amount)
    pe.reference_no = reference_no
    pe.reference_date = posting_date
    pe.posting_date = posting_date
    # Trim references to just this PI and this allocation.
    pe.references = [r for r in pe.references if r.reference_name == pi_name]
    for r in pe.references:
        r.allocated_amount = abs(amount)
    pe.flags.ignore_permissions = True
    pe.save()
    return pe


def _process_pi_for_backfill(pi, dry_run):
    """Drive the per-PI flow described in ``backfill_auto_paid_supplier``."""
    from frappe.utils import flt

    supplier = frappe.get_cached_doc("Supplier", pi.supplier)
    mop = supplier.get("bns_auto_paid_mode_of_payment")
    target_account = _resolve_mop_account(mop, pi.company)
    if not (mop and target_account):
        return {
            "pi": pi.name, "status": "skipped",
            "reason": "supplier missing MOP or company-account mapping",
        }

    linked = _linked_payment_entries(pi.name)
    wrong_pes, multi_pi_pes = [], []
    for pe in linked:
        if len(pe["referenced_pis"]) > 1:
            multi_pi_pes.append(pe)
        elif pe["cash_bank_account"] != target_account:
            wrong_pes.append(pe)

    if multi_pi_pes:
        # Cancelling a multi-PI PE would un-pay other invoices; never auto.
        return {
            "pi": pi.name, "status": "needs-manual",
            "reason": "linked Payment Entry references multiple PIs",
            "pes": [p["name"] for p in multi_pi_pes],
        }

    # Phase 2: cancel wrong-account PEs and recreate on correct account
    reclassified = []
    for wrong in wrong_pes:
        if dry_run:
            reclassified.append({
                "old_pe": wrong["name"],
                "amount": wrong["allocated_amount"],
                "from_account": wrong["cash_bank_account"],
                "to_account": target_account,
                "action": "would cancel + recreate",
            })
            continue
        old_doc = frappe.get_doc("Payment Entry", wrong["name"])
        old_doc.flags.ignore_permissions = True
        old_doc.cancel()
        new_pe = _make_pe_for_pi(
            pi.name, mop, target_account,
            amount=wrong["allocated_amount"],
            posting_date=wrong["posting_date"],
            reference_no=f"BNS-RECLASS-{wrong['name']}",
        )
        new_pe.submit()
        reclassified.append({
            "old_pe": wrong["name"],
            "new_pe": new_pe.name,
            "amount": wrong["allocated_amount"],
            "from_account": wrong["cash_bank_account"],
            "to_account": target_account,
            "action": "cancelled + recreated",
        })

    # Phase 3: pay any residual outstanding on the correct account
    if dry_run:
        residual = flt(pi.outstanding_amount)
        # In dry-run we can't recompute outstanding after hypothetical
        # cancellations, so we report it as-is. Live-run re-fetches.
    else:
        pi_fresh = frappe.db.get_value(
            "Purchase Invoice", pi.name,
            ["outstanding_amount", "posting_date"], as_dict=True,
        )
        residual = flt(pi_fresh.outstanding_amount)

    if residual == 0:
        return {
            "pi": pi.name, "status": "ok",
            "reclassified": reclassified, "residual": 0,
        }

    if dry_run:
        return {
            "pi": pi.name, "status": "would-pay-residual",
            "amount": residual, "to_account": target_account,
            "reclassified": reclassified,
        }

    new_pe = _make_pe_for_pi(
        pi.name, mop, target_account,
        amount=residual,
        posting_date=pi_fresh.posting_date,
        reference_no=f"BNS-AUTOPAY-{pi.name}",
    )
    new_pe.submit()
    return {
        "pi": pi.name, "status": "paid",
        "new_pe": new_pe.name, "amount": residual,
        "reclassified": reclassified,
    }


def _summarize(rows):
    """Count rows per status for the report header."""
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts
