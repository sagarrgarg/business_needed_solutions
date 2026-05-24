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

# Live runs above this size go to the long queue; the request returns
# immediately and the result is published via realtime when the worker
# finishes. Dry runs are always inline (read-only) regardless of size.
_BACKFILL_ENQUEUE_THRESHOLD = 10
# Hard ceiling even for enqueued runs — keeps one job from chewing through
# the entire ledger in a single shot if a filter is forgotten.
_BACKFILL_HARD_MAX = 2000
# Realtime event name used to deliver the worker's report to the UI.
_BACKFILL_REALTIME_EVENT = "bns_auto_paid_backfill_done"


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
      1. Cancel every linked Payment Entry that paid against the wrong
         cash/bank account (only if the PE references this PI alone;
         multi-PI PEs are reported and skipped — cancelling them would
         un-pay other invoices).
      2. Pay the resulting outstanding (original residual + amount freed
         by cancellations) as ONE new Payment Entry on the correct account.

    Returns a structured report; no direct GL Entry mutation.

    Sync vs enqueue: dry runs always return inline. Live runs with more
    than ``_BACKFILL_ENQUEUE_THRESHOLD`` PIs are enqueued to the long
    queue and the report is published via the ``bns_auto_paid_backfill_done``
    realtime event to the calling user when the worker finishes.

    Args:
        supplier: Restrict to one Supplier name. Blank = every flagged supplier.
        from_date / to_date: Posting-date window. Blank = unbounded.
        dry_run: 1 (default) plans without writing. 0 actually applies changes.
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

    if len(pis) > _BACKFILL_HARD_MAX:
        frappe.throw(
            _(
                "Backfill scope is {0} Purchase Invoices, above the hard cap "
                "of {1}. Narrow the date range or run per supplier."
            ).format(len(pis), _BACKFILL_HARD_MAX),
            title=_("Backfill Scope Too Large"),
        )

    # Live runs above the inline threshold go to the long queue. The
    # caller receives an enqueue confirmation immediately; the worker
    # publishes the report via realtime when it finishes.
    if not dry_run and len(pis) > _BACKFILL_ENQUEUE_THRESHOLD:
        pi_names = [pi.name for pi in pis]
        frappe.enqueue(
            "business_needed_solutions.business_needed_solutions.overrides.auto_paid_supplier._backfill_runner",
            queue="long",
            timeout=3600,
            job_name=f"bns_auto_paid_backfill:{frappe.session.user}:{len(pi_names)}",
            pi_names=pi_names,
            user=frappe.session.user,
        )
        return {
            "enqueued": True,
            "dry_run": False,
            "total": len(pi_names),
        }

    rows = _run_backfill_inline(pis, dry_run)
    return {
        "enqueued": False,
        "dry_run": bool(dry_run),
        "total": len(rows),
        "by_status": _summarize(rows),
        "rows": rows,
    }


def _run_backfill_inline(pis, dry_run):
    """Process a list of PI rows synchronously, with per-PI error capture."""
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
            if not dry_run:
                # Don't poison subsequent PIs with a half-applied transaction.
                frappe.db.rollback()
    return rows


def _backfill_runner(pi_names, user):
    """Background worker: process a fixed PI list and publish the report.

    Re-fetches each PI from the DB so the worker isn't dependent on the
    enqueue snapshot, then runs the same per-PI flow as the inline path.
    Errors are logged and reported per PI; one failure does not abort
    the batch.
    """
    rows = []
    for name in pi_names:
        pi = frappe.db.get_value(
            "Purchase Invoice", name,
            [
                "name", "supplier", "company", "posting_date",
                "outstanding_amount", "grand_total", "is_return",
            ],
            as_dict=True,
        )
        if not pi:
            rows.append({"pi": name, "status": "error", "reason": "PI not found"})
            continue
        try:
            rows.append(_process_pi_for_backfill(pi, dry_run=0))
        except Exception as exc:
            frappe.log_error(
                title="Auto-Paid Supplier Backfill (BG)",
                message=f"PI {name}: {exc}\n{frappe.get_traceback()}",
            )
            rows.append({"pi": name, "status": "error", "reason": str(exc)})
            frappe.db.rollback()

    frappe.publish_realtime(
        event=_BACKFILL_REALTIME_EVENT,
        message={
            "dry_run": False,
            "enqueued": True,
            "total": len(rows),
            "by_status": _summarize(rows),
            "rows": rows,
        },
        user=user,
    )


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


def _make_pe_paying_outstanding(pi_name, mop, account, posting_date, reference_no):
    """Build (and save, not submit) a Payment Entry that pays the PI's
    current full outstanding through the target MOP account.

    Trusts ERPNext's ``get_payment_entry`` to size paid_amount /
    received_amount / references / exchange rates correctly. We only
    override the routing fields (MOP + cash/bank account) and the
    reference metadata. No reference trimming, no allocated_amount
    override — which is what caused the "Allocated Amount cannot be
    greater than outstanding amount" validator error in the previous
    per-PE recreate path.
    """
    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

    pe = get_payment_entry("Purchase Invoice", pi_name)
    pe.mode_of_payment = mop
    # Pay vs Receive: paid_from is cash/bank for Pay, paid_to for Receive.
    if pe.payment_type == "Receive":
        pe.paid_to = account
    else:
        pe.paid_from = account
    pe.reference_no = reference_no
    pe.reference_date = posting_date
    pe.posting_date = posting_date
    pe.flags.ignore_permissions = True
    pe.save()
    return pe


def _process_pi_for_backfill(pi, dry_run):
    """Per-PI flow.

    1. Resolve supplier's MOP account; skip if misconfigured.
    2. Inspect linked PEs. Any PE that paid through a different cash/bank
       account is a wrong-account PE. Multi-PI PEs are reported as
       needs-manual (cancelling would un-pay other invoices).
    3. Cancel every wrong-account PE.
    4. Pay the resulting full outstanding as ONE new PE.
    """
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

    cancelled = []
    cancelled_total = 0.0
    if wrong_pes and dry_run:
        for wrong in wrong_pes:
            cancelled.append({
                "old_pe": wrong["name"],
                "amount": wrong["allocated_amount"],
                "from_account": wrong["cash_bank_account"],
                "to_account": target_account,
                "action": "would cancel",
            })
            cancelled_total += flt(wrong["allocated_amount"])
    elif wrong_pes:
        for wrong in wrong_pes:
            old_doc = frappe.get_doc("Payment Entry", wrong["name"])
            old_doc.flags.ignore_permissions = True
            old_doc.cancel()
            cancelled.append({
                "old_pe": wrong["name"],
                "amount": wrong["allocated_amount"],
                "from_account": wrong["cash_bank_account"],
                "to_account": target_account,
                "action": "cancelled",
            })

    # Compute residual after (real or hypothetical) cancellations.
    if dry_run:
        # Approximate: cancelling a Pay PE adds its allocation back to
        # PI outstanding. Live-run reads the actual post-cancel value.
        residual = flt(pi.outstanding_amount) + cancelled_total
    else:
        residual = flt(frappe.db.get_value(
            "Purchase Invoice", pi.name, "outstanding_amount"))

    # Tolerate sub-paisa rounding noise.
    if abs(residual) < 0.01:
        return {
            "pi": pi.name, "status": "ok",
            "cancelled": cancelled, "residual": 0,
        }

    if dry_run:
        return {
            "pi": pi.name, "status": "would-pay",
            "amount": residual, "to_account": target_account,
            "cancelled": cancelled,
        }

    posting_date = frappe.db.get_value(
        "Purchase Invoice", pi.name, "posting_date")
    new_pe = _make_pe_paying_outstanding(
        pi.name, mop, target_account,
        posting_date=posting_date,
        reference_no=f"BNS-AUTOPAY-{pi.name}",
    )
    new_pe.submit()
    return {
        "pi": pi.name, "status": "paid",
        "new_pe": new_pe.name, "amount": residual,
        "cancelled": cancelled,
    }


def _summarize(rows):
    """Count rows per status for the report header."""
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts
