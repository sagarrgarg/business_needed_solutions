# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""GL/SLE Audit — find submitted docs missing or imbalanced in GL Entry
and Stock Ledger Entry.

Catches the well-known half-commit bug where on_submit raised after
db_update wrote docstatus=1 but before make_gl_entries / update_stock_ledger
completed, and the outer caller's frappe.db.commit() flushed the partial
state. Result: docstatus=1 with missing or imbalanced GL/SLE.

Scope (each row in audit output is a doc, NOT a GL/SLE row):
  * Sales Invoice, Purchase Invoice  — GL always; SLE iff update_stock=1
  * Delivery Note, Purchase Receipt  — SLE always; GL iff perpetual inventory
  * Stock Entry, Stock Reconciliation — SLE always; GL iff perpetual inventory
  * Journal Entry, Landed Cost Voucher — GL always; no SLE

Tolerance: 0.01 currency unit for GL dr/cr balance.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import cint, flt, getdate

import erpnext

# Permission gates routed through Role Permission Manager rather than
# hardcoded role lists, matching the rest of BNS. See the helpers in
# bns_branch_accounting/utils.py for the rationale (admins grant access
# via Desk → Setup → Role Permission Manager on BNS Branch Accounting
# Settings, no code edits required).
from business_needed_solutions.bns_branch_accounting.utils import (
    _bns_require_accounts_read,
    _bns_require_accounts_write,
)


GL_TOLERANCE = 0.01

# Hard safety cap on the per-doctype document SCAN (not the output). The
# audit is scoped by the cutoff window; this only prevents a truly unbounded
# scan when cutoff is None on a very large site. The user-facing `limit`
# caps the returned (flagged) rows instead — see _audit_one_doctype.
_SCAN_CAP = 1_000_000

# If a repair batch is at or above this size, the request is enqueued as a
# background job instead of running inline (avoids HTTP timeout, frees the
# UI). Smaller batches run synchronously so the result popup is immediate.
REPAIR_INLINE_THRESHOLD = 50

# Per-doctype audit spec.
#   expect_gl:  "always" | "if_update_stock" | "if_perpetual_and_stock" |
#               "if_has_stock_item" | "never"
#   expect_sle: "always" | "if_update_stock_and_stock_item" |
#               "if_has_stock_item" | "never"
#   posting_field: column on parent table holding the posting date
#   has_update_stock: bool — controller exposes update_stock field
#   item_doctype: child item-table doctype for is_stock_item lookup
#                 (None when doc has no item table)
#
# Rule mirrors ERPNext's `get_accounting_ledger_preview` / `get_stock_ledger_preview`
# in erpnext/controllers/stock_controller.py:1537+. Non-stock-item-only
# documents (e.g. DN delivering a Fixed Asset, SI billing services only)
# generate no SLE; DN/PR with no stock items also generate no GL.
# SI/PI always generate GL (debtors/creditors/tax/asset legs).
AUDIT_SPEC: Dict[str, Dict[str, Any]] = {
    "Sales Invoice": {
        "expect_gl": "always",
        "expect_sle": "if_update_stock_and_stock_item",
        "posting_field": "posting_date",
        "has_update_stock": True,
        "item_doctype": "Sales Invoice Item",
        "total_field": "grand_total",
    },
    "Purchase Invoice": {
        "expect_gl": "always",
        "expect_sle": "if_update_stock_and_stock_item",
        "posting_field": "posting_date",
        "has_update_stock": True,
        "item_doctype": "Purchase Invoice Item",
        "total_field": "grand_total",
    },
    "Delivery Note": {
        # DN with only non-stock items (e.g. fixed asset deliveries) generates
        # nothing on its own; GL/SLE happen on the SI / Asset side. DN with
        # all zero-value items / zero-valuation stock also produces no GL.
        "expect_gl": "if_perpetual_and_stock",
        "expect_sle": "if_has_stock_item",
        "posting_field": "posting_date",
        "has_update_stock": False,
        "item_doctype": "Delivery Note Item",
        "total_field": "grand_total",
    },
    "Purchase Receipt": {
        "expect_gl": "if_perpetual_and_stock",
        "expect_sle": "if_has_stock_item",
        "posting_field": "posting_date",
        "has_update_stock": False,
        "item_doctype": "Purchase Receipt Item",
        "total_field": "grand_total",
    },
    "Stock Entry": {
        # GL on Stock Entry depends on stock_entry_type + additional_costs +
        # cross-company. Material Transfer within one company doesn't make GL.
        # Auto-detecting that here is fragile, so we audit SLE only and let
        # GL checks happen via the per-doc check downstream.
        "expect_gl": "never",
        "expect_sle": "if_has_stock_item",
        "posting_field": "posting_date",
        "has_update_stock": False,
        "item_doctype": "Stock Entry Detail",
        "total_field": None,
    },
    "Stock Reconciliation": {
        # GL on Stock Reconciliation only fires on valuation difference rows.
        # Skip blanket GL check for the same reason as Stock Entry.
        "expect_gl": "never",
        "expect_sle": "if_has_stock_item",
        "posting_field": "posting_date",
        "has_update_stock": False,
        "item_doctype": "Stock Reconciliation Item",
        "total_field": None,
    },
    "Journal Entry": {
        # Account-based; no item table. JE always has GL (it IS GL).
        "expect_gl": "always",
        "expect_sle": "never",
        "posting_field": "posting_date",
        "has_update_stock": False,
        "item_doctype": None,
        "total_field": None,
    },
    "Landed Cost Voucher": {
        "expect_gl": "always",
        "expect_sle": "never",
        "posting_field": "posting_date",
        "has_update_stock": False,
        "item_doctype": None,
        "total_field": None,
    },
    "Payment Entry": {
        # PE always books GL: cash/bank dr + party account cr (or vice versa
        # for receive/pay flips). No item table, no stock impact.
        "expect_gl": "always",
        "expect_sle": "never",
        "posting_field": "posting_date",
        "has_update_stock": False,
        "item_doctype": None,
        "total_field": "paid_amount",
    },
}

STATUS_MISSING_GL = "Missing GL"
STATUS_MISSING_SLE = "Missing SLE"
STATUS_MISSING_BOTH = "Missing GL & SLE"
STATUS_IMBALANCED_GL = "Imbalanced GL"
# Imbalanced SLE intentionally dropped — sign mismatches are byproducts
# of upstream negative-stock issues, NOT bugs in the GL/SLE pipeline.
# Use BNS Settings `enable_per_warehouse_negative_stock_disallow` +
# `negative_stock_cutoff_date` to prevent the root cause going forward.


def _company_perpetual_cache() -> Dict[str, bool]:
    """Per-request cache of perpetual-inventory flag by company."""
    cache = frappe.local.flags.get("_bns_perpetual_cache")
    if cache is None:
        cache = {}
        frappe.local.flags["_bns_perpetual_cache"] = cache
    return cache


def _is_perpetual(company: Optional[str]) -> bool:
    if not company:
        return False
    cache = _company_perpetual_cache()
    if company not in cache:
        cache[company] = bool(erpnext.is_perpetual_inventory_enabled(company))
    return cache[company]


def _audit_one_doctype(
    doctype: str,
    cutoff_date: Optional[str],
    company: Optional[str] = None,
    limit: int = 50000,
) -> List[Dict[str, Any]]:
    """Run a single SQL aggregation per doctype, returning only mismatches."""
    spec = AUDIT_SPEC[doctype]
    posting_field = spec["posting_field"]
    has_update_stock = spec["has_update_stock"]
    item_doctype = spec.get("item_doctype")
    total_field = spec.get("total_field")
    is_stock_recon = doctype == "Stock Reconciliation"

    parent_table = f"tab{doctype}"

    select_update_stock = "p.update_stock" if has_update_stock else "0"
    # doc_total: parent's booking amount. Used to gate GL expectation for
    # SI/PI/DN/PR — zero-amount docs legitimately produce no GL. None
    # for doctypes where the field doesn't apply (SE, SR, JE, LCV).
    select_doc_total = f"p.{total_field}" if total_field else "0"

    # Stock-item subquery: counts stock items + fixed assets per parent doc.
    # Defaults to (0, 0) when the doc has no item table (JE, LCV) — those
    # never need a stock-item check.
    if item_doctype:
        item_table = f"tab{item_doctype}"
        # Stock Reconciliation Item exposes quantity_difference and
        # amount_difference. SR with zero-change items is a no-op — ERPNext
        # throws "No stock ledger entries were created" rather than booking
        # SLE — so we add a per-doc "has actual change" indicator and gate
        # SR's expects_sle on it.
        recon_select_extra = (
            "SUM(ABS(COALESCE(ii.quantity_difference, 0)) + ABS(COALESCE(ii.amount_difference, 0))) AS recon_change_signal,"
            if is_stock_recon
            else "0 AS recon_change_signal,"
        )
        stock_join_sql = f"""
        LEFT JOIN (
            SELECT ii.parent,
                   SUM(CASE WHEN i.is_stock_item = 1 THEN 1 ELSE 0 END) AS stock_items,
                   SUM(CASE WHEN i.is_fixed_asset = 1 THEN 1 ELSE 0 END) AS asset_items,
                   COUNT(*) AS total_items,
                   {recon_select_extra}
                   0 AS _pad
            FROM `{item_table}` ii
            JOIN `tabItem` i ON i.name = ii.item_code
            GROUP BY ii.parent
        ) it ON it.parent = p.name
        """
        stock_select_sql = """
            COALESCE(it.stock_items, 0) AS stock_item_count,
            COALESCE(it.asset_items, 0) AS asset_item_count,
            COALESCE(it.total_items, 0) AS total_item_count,
            COALESCE(it.recon_change_signal, 0) AS recon_change_signal,
        """
    else:
        stock_join_sql = ""
        stock_select_sql = """
            0 AS stock_item_count,
            0 AS asset_item_count,
            0 AS total_item_count,
            0 AS recon_change_signal,
        """

    where_clauses = ["p.docstatus = 1"]
    params: Dict[str, Any] = {}

    if cutoff_date:
        where_clauses.append(f"p.{posting_field} >= %(cutoff)s")
        params["cutoff"] = getdate(cutoff_date)
    if company:
        where_clauses.append("p.company = %(company)s")
        params["company"] = company

    where_sql = " AND ".join(where_clauses)

    sql = f"""
        SELECT
            p.name,
            p.{posting_field} AS posting_date,
            p.company,
            {select_update_stock} AS update_stock,
            {select_doc_total}   AS doc_total,
            {stock_select_sql}
            COALESCE(gl.gl_count, 0) AS gl_count,
            COALESCE(gl.gl_dr, 0)    AS gl_dr,
            COALESCE(gl.gl_cr, 0)    AS gl_cr,
            COALESCE(sle.sle_count, 0)              AS sle_count,
            COALESCE(sle.sle_value_movement, 0)     AS sle_value_movement,
            COALESCE(sle.sle_value_net, 0)          AS sle_value_net
        FROM `{parent_table}` p
        {stock_join_sql}
        LEFT JOIN (
            SELECT voucher_no,
                   COUNT(*) AS gl_count,
                   SUM(debit)  AS gl_dr,
                   SUM(credit) AS gl_cr
            FROM `tabGL Entry`
            WHERE voucher_type = %(doctype)s AND is_cancelled = 0
            GROUP BY voucher_no
        ) gl ON gl.voucher_no = p.name
        LEFT JOIN (
            -- SLE aggregate is "movement only" — we no longer try to detect
            -- imbalance inside SLE rows. Sign mismatches and value drift
            -- here are byproducts of upstream negative-stock issues
            -- (transactions allowed without opening stock, repost arithmetic
            -- against negative balances, etc.). The right tool for that is
            -- BNS Settings `enable_per_warehouse_negative_stock_disallow` +
            -- `negative_stock_cutoff_date` — preventing the root cause
            -- going forward, not flagging the historical bookkeeping.
            SELECT voucher_no,
                   COUNT(*) AS sle_count,
                   SUM(ABS(stock_value_difference)) AS sle_value_movement,
                   SUM(stock_value_difference)      AS sle_value_net
            FROM `tabStock Ledger Entry`
            WHERE voucher_type = %(doctype)s AND is_cancelled = 0
            GROUP BY voucher_no
        ) sle ON sle.voucher_no = p.name
        WHERE {where_sql}
        ORDER BY p.{posting_field} DESC, p.name DESC
        LIMIT {_SCAN_CAP}
    """
    params["doctype"] = doctype

    rows = frappe.db.sql(sql, params, as_dict=True)

    output: List[Dict[str, Any]] = []
    for r in rows:
        perpetual = _is_perpetual(r.get("company"))
        expects_gl, expects_sle = _resolve_expectations(spec, r, perpetual, doctype=doctype)

        statuses: List[str] = []

        if expects_gl and not r["gl_count"]:
            statuses.append(STATUS_MISSING_GL)
        elif expects_gl and abs(flt(r["gl_dr"]) - flt(r["gl_cr"])) > GL_TOLERANCE:
            statuses.append(STATUS_IMBALANCED_GL)

        if expects_sle and not r["sle_count"]:
            statuses.append(STATUS_MISSING_SLE)

        if not statuses:
            continue

        # Collapse "Missing GL" + "Missing SLE" into a single readable label.
        if STATUS_MISSING_GL in statuses and STATUS_MISSING_SLE in statuses:
            status_label = STATUS_MISSING_BOTH
        else:
            status_label = " + ".join(statuses)

        output.append({
            "doctype": doctype,
            "name": r["name"],
            "posting_date": r["posting_date"],
            "company": r["company"],
            "update_stock": cint(r.get("update_stock")),
            "perpetual": int(perpetual),
            "expected_gl": int(expects_gl),
            "expected_sle": int(expects_sle),
            "gl_count": cint(r["gl_count"]),
            "gl_dr": flt(r["gl_dr"]),
            "gl_cr": flt(r["gl_cr"]),
            "gl_imbalance": flt(r["gl_dr"]) - flt(r["gl_cr"]),
            "sle_count": cint(r["sle_count"]),
            "stock_item_count": cint(r.get("stock_item_count")),
            "asset_item_count": cint(r.get("asset_item_count")),
            "total_item_count": cint(r.get("total_item_count")),
            "status": status_label,
        })

    # `limit` caps the OUTPUT (flagged rows) — NOT the document scan. The scan
    # is bounded only by the cutoff window (+ a large _SCAN_CAP safety), so
    # every in-window document is examined and old issues are never silently
    # hidden behind newer documents.
    return output[: int(limit)] if limit else output


def _resolve_expectations(
    spec: Dict[str, Any],
    row: Dict[str, Any],
    perpetual: bool,
    doctype: Optional[str] = None,
) -> tuple[bool, bool]:
    """Return (expects_gl, expects_sle) for this row based on spec + flags.

    Zero-value gating: ERPNext's make_gl_entries / make_item_gl_entries
    legitimately produces NO GL when the doc's booking amount is zero
    (zero-amount SI/PI/PR, or DN with zero-valuation stock). Those are
    correct system states, not bugs — so we drop the "expects GL" flag.
    """
    expect_gl = spec["expect_gl"]
    expect_sle = spec["expect_sle"]
    update_stock = cint(row.get("update_stock"))
    has_stock_item = cint(row.get("stock_item_count")) > 0
    doc_total = flt(row.get("doc_total"))
    sle_value_movement = flt(row.get("sle_value_movement"))

    if expect_gl == "always":
        # SI/PI: GL only when there is a booking amount to record.
        # If parent has a total_field declared, gate on it. (JE/LCV have
        # total_field=None so doc_total stays 0 in the SELECT — those
        # doctypes always book GL regardless and need the bypass.)
        if spec.get("total_field"):
            gl = abs(doc_total) > 0.001
        else:
            gl = True
    elif expect_gl == "if_perpetual":
        gl = perpetual
    elif expect_gl == "if_perpetual_and_stock":
        # DN/PR perpetual-inventory GL = stock value movement.
        # Two cases where no GL is produced even with perpetual inventory:
        #   (a) all SLE rows have stock_value_difference = 0 (zero-value
        #       receipt/issue — gate: sle_value_movement > 0)
        #   (b) SLE rows net to zero across the doc (intra-company
        #       warehouse-to-warehouse transfer landing on the SAME
        #       parent stock account → entries collapse to 0 in
        #       process_gl_map and get filtered out — gate:
        #       |sle_value_net| > 0).
        sle_value_net = flt(row.get("sle_value_net"))
        gl = (
            perpetual
            and has_stock_item
            and sle_value_movement > 0.001
            and abs(sle_value_net) > 0.001
        )
    elif expect_gl == "if_has_stock_item":
        gl = has_stock_item
    elif expect_gl == "if_update_stock":
        gl = bool(update_stock)
    else:
        gl = False

    if expect_sle == "always":
        sle = True
    elif expect_sle == "if_update_stock":
        sle = bool(update_stock)
    elif expect_sle == "if_update_stock_and_stock_item":
        sle = bool(update_stock) and has_stock_item
    elif expect_sle == "if_has_stock_item":
        sle = has_stock_item
    else:
        sle = False

    # Stock Reconciliation extra gate: zero-change reconciliations
    # (qty == current_qty AND rate == current_valuation_rate across all
    # items) are no-ops. ERPNext refuses to create SLE for them and
    # throws "No stock ledger entries were created". Don't flag.
    if sle and doctype == "Stock Reconciliation":
        recon_signal = flt(row.get("recon_change_signal"))
        if recon_signal <= 0.001:
            sle = False

    return gl, sle


@frappe.whitelist()
def audit_gl_sle(cutoff_date=None, doctypes=None, company=None, statuses=None, limit=50000):
    _bns_require_accounts_read()
    """Run audit across selected doctypes. Returns list of mismatch rows.

    Args:
        cutoff_date: Only include docs with posting_date >= cutoff.
            None = no cutoff (audits everything; can be slow on big sites).
        doctypes: Restrict scan to these doctypes. Default: all in AUDIT_SPEC.
        company: Restrict to single company.
        statuses: Post-filter to these status labels.
        limit: Hard cap on rows per doctype.
    """

    # Normalize list args. The frappe.whitelist HTTP layer may deliver them
    # as JSON-encoded strings (e.g. '["Sales Invoice","Purchase Invoice"]').
    # Statuses are whitelist-validated; doctypes are filtered against AUDIT_SPEC
    # at the next step.
    doctypes = _normalize_list_arg(doctypes)
    statuses = _normalize_list_arg(statuses, allowed=_VALID_STATUSES)

    if doctypes:
        target_doctypes = [dt for dt in doctypes if dt in AUDIT_SPEC]
    else:
        target_doctypes = list(AUDIT_SPEC.keys())

    all_rows: List[Dict[str, Any]] = []
    for dt in target_doctypes:
        try:
            all_rows.extend(
                _audit_one_doctype(dt, cutoff_date, company=company, limit=int(limit))
            )
        except Exception as e:
            frappe.log_error(
                title=f"GL/SLE Audit failed for {dt}",
                message=frappe.get_traceback(),
            )
            # Don't leak raw exception strings into the response — full
            # traceback already went to Error Log above.
            all_rows.append({
                "doctype": dt,
                "name": "(audit failed)",
                "posting_date": None,
                "company": company or "",
                "update_stock": 0,
                "perpetual": 0,
                "expected_gl": 0,
                "expected_sle": 0,
                "gl_count": 0,
                "gl_dr": 0,
                "gl_cr": 0,
                "gl_imbalance": 0,
                "sle_count": 0,
                "status": f"AUDIT ERROR ({dt}) — see Error Log",
            })

    if statuses:
        wanted = set(statuses)
        all_rows = [r for r in all_rows if r["status"] in wanted or r["status"].startswith("AUDIT ERROR")]

    return all_rows


_VALID_STATUSES = frozenset({
    STATUS_MISSING_GL,
    STATUS_MISSING_SLE,
    STATUS_MISSING_BOTH,
    STATUS_IMBALANCED_GL,
})


def _normalize_list_arg(value: Any, *, allowed: Optional[frozenset] = None) -> Optional[List[str]]:
    """Parse a string / list arg from the HTTP layer.

    `allowed` (optional): whitelist of acceptable values — anything else is
    dropped silently. Use this for filter args that flow into a set membership
    check downstream so unexpected strings can't survive.
    """
    if value is None or value == "":
        return None
    parsed: List[str]
    if isinstance(value, str):
        # Could be JSON-encoded array or comma-separated.
        s = value.strip()
        parsed = []
        if s.startswith("[") and s.endswith("]"):
            import json
            try:
                obj = json.loads(s)
                if isinstance(obj, list):
                    parsed = [str(x) for x in obj if x]
            except Exception:
                parsed = []
        if not parsed:
            parsed = [p.strip() for p in s.split(",") if p.strip()]
    elif isinstance(value, (list, tuple)):
        parsed = [str(x) for x in value if x]
    else:
        return None
    if allowed is not None:
        parsed = [v for v in parsed if v in allowed]
    return parsed or None


@frappe.whitelist()
def repair_gl_sle(docs, cutoff_date=None, fix_missing=True, fix_imbalanced=False, dry_run=True, force_sync=False):
    _bns_require_accounts_write()
    """Attempt to regenerate missing GL/SLE for the given docs.

    Args:
        docs: List of {"doctype": "...", "name": "...", "status": "..."} dicts,
            typically the selected rows from the audit report. Strings of JSON
            also accepted.
        cutoff_date: Records the cutoff that the operator applied (audit log).
        fix_missing: Re-run make_gl_entries / update_stock_ledger for docs
            where GL or SLE is missing. Safe.
        fix_imbalanced: Reverse existing GL and rebuild. Slower and riskier;
            off by default.
        dry_run: When True, only count what would be done. Default True so the
            UI can preview before mutating.
        force_sync: When True, run inline even for large batches. Default
            False — batches >= REPAIR_INLINE_THRESHOLD enqueue as a
            background job and the caller receives `{"queued": True,
            "job_name": "..."}` instead of the results.

    Returns: inline mode → {"attempted": N, "repaired": [...], ...}
             background mode → {"queued": True, "job_name": "...", "attempted": N}
    """

    docs = _normalize_doc_list(docs)
    fix_missing = cint(fix_missing)
    fix_imbalanced = cint(fix_imbalanced)
    dry_run = cint(dry_run)
    force_sync = cint(force_sync)

    # Background mode for large mutating batches. Dry-run always stays inline
    # (it doesn't write anything, finishes fast).
    if not dry_run and not force_sync and len(docs) >= REPAIR_INLINE_THRESHOLD:
        job_name = f"bns_gl_sle_repair_{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}_{frappe.generate_hash(length=6)}"
        frappe.enqueue(
            method="business_needed_solutions.business_needed_solutions.gl_sle_audit._run_repair_in_background",
            queue="long",
            timeout=14400,  # 4 hours, ~17 docs/sec gives 240k docs
            job_name=job_name,
            now=False,
            docs=docs,
            cutoff_date=cutoff_date,
            fix_missing=fix_missing,
            fix_imbalanced=fix_imbalanced,
            user=frappe.session.user,
            # Pass job_name into the worker so it can cache progress under it.
            # Use a non-reserved kwarg name — `job_name` is consumed by Frappe's
            # own enqueue wrapper for RQ job naming.
            target_job_name=job_name,
        )
        return {
            "queued": True,
            "job_name": job_name,
            "attempted": len(docs),
            "dry_run": False,
            "fix_missing": bool(fix_missing),
            "fix_imbalanced": bool(fix_imbalanced),
            "cutoff_date": cutoff_date,
        }

    return _run_repair_loop(
        docs=docs,
        cutoff_date=cutoff_date,
        fix_missing=fix_missing,
        fix_imbalanced=fix_imbalanced,
        dry_run=dry_run,
        publish_progress=False,
    )


def _run_repair_in_background(
    docs: List[Dict[str, str]],
    cutoff_date: Optional[str],
    fix_missing: int,
    fix_imbalanced: int,
    user: str,
    target_job_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Worker entry point for background repair. Publishes realtime progress
    and ALSO stashes the final result in the Redis cache keyed by job_name,
    so the JS can poll as a fallback if realtime events were missed
    (subscribe-after-publish race, SocketIO reconnect, etc.).
    """
    # Run with the originating user's perms so the per-doc permission gate
    # in _run_repair_loop reflects them, not the worker's superuser context.
    frappe.set_user(user)
    try:
        result = _run_repair_loop(
            docs=docs,
            cutoff_date=cutoff_date,
            fix_missing=fix_missing,
            fix_imbalanced=fix_imbalanced,
            dry_run=False,
            publish_progress=True,
            progress_job_name=target_job_name,
        )
        # Persist the final result for poll-based fallback. 1-hour TTL is
        # plenty for the UI to fetch it.
        if target_job_name:
            try:
                frappe.cache().set_value(
                    f"bns_gl_sle_repair_result::{target_job_name}",
                    result,
                    expires_in_sec=3600,
                )
            except Exception:
                pass
        # Fire BOTH user-scoped AND site-room events so a fresh subscriber
        # that joined the global socket but missed the user-room handshake
        # still gets the done signal. after_commit=True so the worker's
        # in-flight transaction is fully flushed before delivery.
        frappe.publish_realtime(
            event="gl_sle_repair_done",
            message=result,
            user=user,
            after_commit=True,
        )
        return result
    finally:
        # Defensive: don't leak the set_user context.
        try:
            frappe.set_user("Administrator") if user == "Administrator" else None
        except Exception:
            pass


def _run_repair_loop(
    docs: List[Dict[str, str]],
    cutoff_date: Optional[str],
    fix_missing: int,
    fix_imbalanced: int,
    dry_run: int,
    publish_progress: bool,
    progress_job_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Core repair loop. Used by both inline and background paths.

    Per-doc transaction boundary: each successful repair commits, each failure
    rolls back. An earlier doc's writes cannot leak into a later doc's
    rollback because the prior commit closed the transaction.
    """
    result: Dict[str, Any] = {
        "attempted": len(docs),
        "dry_run": bool(dry_run),
        "fix_missing": bool(fix_missing),
        "fix_imbalanced": bool(fix_imbalanced),
        "cutoff_date": cutoff_date,
        "repaired": [],
        "skipped": [],
        "errors": [],
    }

    total = len(docs)
    for idx, entry in enumerate(docs, start=1):
        dt = entry.get("doctype")
        name = entry.get("name")
        status = (entry.get("status") or "").strip()

        if dt not in AUDIT_SPEC or not name:
            result["skipped"].append({"doctype": dt, "name": name, "reason": "unknown doctype"})
            _maybe_progress(publish_progress, idx, total, dt, name, "skipped", progress_job_name)
            continue

        # Per-doc permission check — `frappe.only_for` on the endpoint only
        # checks roles, not per-document write/submit permission. Submitting
        # a forged docs list against doctypes the user can't otherwise touch
        # would slip past the role gate without this.
        if not frappe.has_permission(dt, "submit", doc=name):
            result["skipped"].append({
                "doctype": dt, "name": name,
                "reason": "no submit permission for this doc",
            })
            _maybe_progress(publish_progress, idx, total, dt, name, "skipped", progress_job_name)
            continue

        is_missing = STATUS_MISSING_GL in status or STATUS_MISSING_SLE in status or STATUS_MISSING_BOTH in status
        is_imbalanced = STATUS_IMBALANCED_GL in status

        will_fix = (is_missing and fix_missing) or (is_imbalanced and fix_imbalanced)
        if not will_fix:
            result["skipped"].append({
                "doctype": dt, "name": name, "reason": f"status='{status}' not in fix scope"
            })
            _maybe_progress(publish_progress, idx, total, dt, name, "skipped", progress_job_name)
            continue

        plan = _plan_repair(dt, status)
        if dry_run:
            result["repaired"].append({"doctype": dt, "name": name, "plan": plan, "applied": False})
            _maybe_progress(publish_progress, idx, total, dt, name, "preview", progress_job_name)
            continue

        try:
            details = _execute_repair(dt, name, plan)
            frappe.db.commit()
            result["repaired"].append({
                "doctype": dt,
                "name": name,
                "plan": plan,
                "applied": True,
                "details": details,
            })
            _maybe_progress(publish_progress, idx, total, dt, name, "repaired", progress_job_name)
        except Exception as e:
            frappe.db.rollback()
            frappe.log_error(
                title=f"GL/SLE Repair failed for {dt} {name}",
                message=frappe.get_traceback(),
            )
            result["errors"].append({"doctype": dt, "name": name, "error": str(e)[:500]})
            _maybe_progress(publish_progress, idx, total, dt, name, "error", progress_job_name)

    return result


def _maybe_progress(
    publish: bool,
    current: int,
    total: int,
    doctype: Optional[str],
    name: Optional[str],
    outcome: str,
    job_name: Optional[str] = None,
) -> None:
    """Emit a realtime progress tick + update a Redis-cached snapshot.

    Realtime is best-effort: if the browser subscribed late or the socket
    reconnected mid-job, ticks are lost. The cached snapshot lets the JS
    poll `get_repair_status` as a fallback and recover state.
    """
    if not publish:
        return
    percent = int((current / total) * 100) if total else 100
    snapshot = {
        "current": current,
        "total": total,
        "doctype": doctype,
        "name": name,
        "outcome": outcome,
        "percent": percent,
        "job_name": job_name,
    }
    if job_name:
        try:
            frappe.cache().set_value(
                f"bns_gl_sle_repair_progress::{job_name}",
                snapshot,
                expires_in_sec=3600,
            )
        except Exception:
            pass
    try:
        frappe.publish_realtime(
            event="gl_sle_repair_progress",
            message=snapshot,
            user=frappe.session.user,
            after_commit=False,
        )
    except Exception:
        # Realtime publishing is best-effort; never let it abort a repair.
        pass


@frappe.whitelist()
def get_repair_status(job_name):
    _bns_require_accounts_read()
    """Poll-based fallback for the repair UI. Returns the latest progress
    snapshot and (if available) the final result for a given job_name.
    """
    if not job_name or not isinstance(job_name, str):
        return {"found": False}
    # Light sanity check on shape — only accept the prefix we emit.
    if not job_name.startswith("bns_gl_sle_repair_"):
        return {"found": False}
    progress = frappe.cache().get_value(f"bns_gl_sle_repair_progress::{job_name}")
    result = frappe.cache().get_value(f"bns_gl_sle_repair_result::{job_name}")
    return {
        "found": bool(progress or result),
        "job_name": job_name,
        "progress": progress,
        "result": result,
        "done": bool(result),
    }


def _normalize_doc_list(docs: Any) -> List[Dict[str, str]]:
    if isinstance(docs, str):
        import json
        try:
            docs = json.loads(docs)
        except Exception:
            return []
    if not isinstance(docs, list):
        return []
    out: List[Dict[str, str]] = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        if d.get("doctype") and d.get("name"):
            out.append({
                "doctype": str(d["doctype"]),
                "name": str(d["name"]),
                "status": str(d.get("status") or ""),
            })
    return out


def _plan_repair(doctype: str, status: str) -> List[str]:
    """Decide which repair actions to run for this doctype + status."""
    plan: List[str] = []
    spec = AUDIT_SPEC[doctype]
    if STATUS_MISSING_SLE in status and spec["expect_sle"] != "never":
        plan.append("update_stock_ledger")
    if STATUS_MISSING_GL in status or STATUS_MISSING_BOTH in status:
        plan.append("make_gl_entries")
    if STATUS_IMBALANCED_GL in status:
        plan.append("repost_accounting_entries")
    return plan


def _live_gl_sle_counts(doctype: str, name: str) -> tuple[int, int]:
    """Current live GL + SLE row counts for a voucher."""
    gl = frappe.db.count("GL Entry", {
        "voucher_type": doctype, "voucher_no": name, "is_cancelled": 0,
    })
    sle = frappe.db.count("Stock Ledger Entry", {
        "voucher_type": doctype, "voucher_no": name, "is_cancelled": 0,
    })
    return int(gl), int(sle)


def _inspect_doc_expectations(doctype: str, name: str) -> Dict[str, Any]:
    """Live-inspect a doc to decide if it actually expects GL / SLE.

    Used by `_execute_repair` to drop plan steps that don't apply for THIS
    doc's content — even if the audit row (or a forged selection) says
    otherwise. Defensive layer so we never call `update_stock_ledger` /
    `make_gl_entries` on a doc that ERPNext won't produce entries for
    (which crashes in obscure ways inside the controllers).
    """
    spec = AUDIT_SPEC.get(doctype, {})
    has_update_stock = spec.get("has_update_stock", False)
    item_doctype = spec.get("item_doctype")
    total_field = spec.get("total_field")

    # Pull update_stock + company + total in one shot.
    parent_fields = ["company"]
    if has_update_stock:
        parent_fields.append("update_stock")
    if total_field:
        parent_fields.append(total_field)
    parent = frappe.db.get_value(doctype, name, parent_fields, as_dict=True) or {}

    stock_item_count = 0
    asset_item_count = 0
    if item_doctype:
        row = frappe.db.sql(
            f"""SELECT
                    SUM(CASE WHEN i.is_stock_item = 1 THEN 1 ELSE 0 END) AS s,
                    SUM(CASE WHEN i.is_fixed_asset = 1 THEN 1 ELSE 0 END) AS a
                FROM `tab{item_doctype}` ii
                JOIN `tabItem` i ON i.name = ii.item_code
                WHERE ii.parent = %s""",
            (name,),
        )
        if row and row[0]:
            stock_item_count = cint(row[0][0])
            asset_item_count = cint(row[0][1])

    # Live SLE value movement + net signed sum for this voucher.
    sle_row = frappe.db.sql(
        """SELECT COALESCE(SUM(ABS(stock_value_difference)), 0) AS mov,
                  COALESCE(SUM(stock_value_difference), 0)      AS net
           FROM `tabStock Ledger Entry`
           WHERE voucher_type = %s AND voucher_no = %s AND is_cancelled = 0""",
        (doctype, name),
        as_dict=True,
    )
    sle_value_movement = flt(sle_row[0]["mov"]) if sle_row else 0.0
    sle_value_net = flt(sle_row[0]["net"]) if sle_row else 0.0

    # Stock Reconciliation: live check for "has actual change". Used to
    # skip repair on no-op SRs (qty == current_qty, rate == current rate).
    recon_change_signal = 0.0
    if doctype == "Stock Reconciliation":
        rs = frappe.db.sql(
            """SELECT COALESCE(SUM(
                       ABS(COALESCE(quantity_difference, 0)) +
                       ABS(COALESCE(amount_difference, 0))
                   ), 0)
               FROM `tabStock Reconciliation Item` WHERE parent = %s""",
            (name,),
        )
        recon_change_signal = flt(rs[0][0]) if rs else 0.0

    company = parent.get("company")
    perpetual = _is_perpetual(company)
    update_stock = cint(parent.get("update_stock")) if has_update_stock else 0
    has_stock = stock_item_count > 0
    doc_total = flt(parent.get(total_field)) if total_field else 0.0

    fake_row = {
        "update_stock": update_stock,
        "stock_item_count": stock_item_count,
        "doc_total": doc_total,
        "sle_value_movement": sle_value_movement,
        "sle_value_net": sle_value_net,
        "recon_change_signal": recon_change_signal,
    }
    expects_gl, expects_sle = _resolve_expectations(spec, fake_row, perpetual, doctype=doctype)

    return {
        "expects_gl": bool(expects_gl),
        "expects_sle": bool(expects_sle),
        "has_stock_items": has_stock,
        "asset_item_count": asset_item_count,
        "update_stock": update_stock,
        "perpetual": bool(perpetual),
        "doc_total": doc_total,
        "sle_value_movement": sle_value_movement,
        "sle_value_net": sle_value_net,
        "recon_change_signal": recon_change_signal,
        "company": company,
    }


def _repair_lock_key(doctype: str, name: str) -> str:
    """MariaDB GET_LOCK key per (doctype, name). 64-byte max; safe under hash."""
    import hashlib
    raw = f"{doctype}::{name}"
    if len(raw) <= 60:
        return f"bns_repair_{raw}"
    # Long names — hash to keep within MariaDB's 64-byte lock-name limit.
    return "bns_repair_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _execute_repair(doctype: str, name: str, plan: List[str]) -> Dict[str, Any]:
    """Run the planned repair steps for one doc — IDEMPOTENT + LOCKED.

    Acquires a MariaDB named lock per (doctype, name) so concurrent workers
    serialize. Re-checks live GL/SLE counts inside the transaction. If the
    gap has already been filled (by a parallel worker, prior repair, or a
    scheduled repost), the step is skipped to prevent double-writes.

    For imbalanced cases, existing entries are reversed via
    `make_reverse_gl_entries` before regeneration.

    Returns: {"actions_run": [...], "skipped": [...], "live_gl_before",
              "live_gl_after", "live_sle_before", "live_sle_after"}
    """
    from erpnext.accounts.general_ledger import make_reverse_gl_entries

    lock_key = _repair_lock_key(doctype, name)
    # GET_LOCK(name, timeout) returns 1 on success, 0 on timeout, NULL on error.
    # Timeout of 10s is enough for any single repair; if exceeded another
    # worker is doing the same doc — bail out cleanly.
    lock_result = frappe.db.sql("SELECT GET_LOCK(%s, 10)", (lock_key,))
    got_lock = bool(lock_result and lock_result[0] and lock_result[0][0] == 1)
    if not got_lock:
        raise frappe.ValidationError(
            f"Could not acquire repair lock for {doctype} {name} "
            f"(another worker is repairing it)"
        )

    try:
        doc = frappe.get_doc(doctype, name)
        if cint(doc.docstatus) != 1:
            raise frappe.ValidationError(
                f"{doctype} {name} is not submitted (docstatus={doc.docstatus})"
            )

        # Live inspection — what does THIS doc actually expect to produce?
        # Filters the plan against the doc's real content so we don't call
        # ERPNext mutators on docs they were never meant to fire on (e.g. a
        # DN delivering only a fixed asset → make_gl_entries / update_stock_
        # ledger have no GL/SLE to make and can crash on internal helpers).
        live = _inspect_doc_expectations(doctype, name)
        gl_before, sle_before = _live_gl_sle_counts(doctype, name)

        actions_run: List[str] = []
        skipped: List[Dict[str, str]] = []

        # SLE missing → write SLE (only when this doc expects SLE per its
        # actual content; non-stock-only docs don't produce SLE).
        if "update_stock_ledger" in plan and hasattr(doc, "update_stock_ledger"):
            if not live["expects_sle"]:
                skipped.append({
                    "step": "update_stock_ledger",
                    "reason": (
                        f"doc not expected to produce SLE "
                        f"(stock_items=0, asset_items={live['asset_item_count']})"
                    ),
                })
            elif sle_before > 0:
                skipped.append({"step": "update_stock_ledger", "reason": f"SLE already present ({sle_before} rows)"})
            else:
                doc.update_stock_ledger()
                actions_run.append("update_stock_ledger")
                # Re-load the doc so item-level fields refreshed by
                # update_stock_ledger (e.g. incoming_rate, valuation_rate)
                # are visible to make_gl_entries below.
                doc = frappe.get_doc(doctype, name)

        # GL missing → write GL (only when zero rows exist; never additive).
        # Same expectation gate as SLE — protects against forged or stale
        # audit rows asking us to make GL on docs ERPNext won't book.
        if "make_gl_entries" in plan and hasattr(doc, "make_gl_entries"):
            if not live["expects_gl"]:
                skipped.append({
                    "step": "make_gl_entries",
                    "reason": (
                        f"doc not expected to produce GL "
                        f"(stock_items={int(live['has_stock_items'])}, "
                        f"asset_items={live['asset_item_count']}, "
                        f"perpetual={int(live['perpetual'])}, "
                        f"doc_total={live['doc_total']:.2f}, "
                        f"sle_value_movement={live['sle_value_movement']:.2f}, "
                        f"sle_value_net={live['sle_value_net']:.2f})"
                    ),
                })
            else:
                live_gl_now = frappe.db.count("GL Entry", {
                    "voucher_type": doctype, "voucher_no": name, "is_cancelled": 0,
                })
                if live_gl_now > 0:
                    skipped.append({"step": "make_gl_entries", "reason": f"GL already present ({live_gl_now} rows)"})
                else:
                    doc.make_gl_entries(from_repost=True)
                    actions_run.append("make_gl_entries")

        # Imbalanced GL → reverse then rebuild — gated on live expectation.
        if "repost_accounting_entries" in plan:
            if not live["expects_gl"]:
                skipped.append({
                    "step": "repost_accounting_entries",
                    "reason": "doc not expected to produce GL — nothing to repost",
                })
            else:
                live_gl_now = frappe.db.count("GL Entry", {
                    "voucher_type": doctype, "voucher_no": name, "is_cancelled": 0,
                })
                if live_gl_now == 0:
                    # Imbalance turned into a missing case while we waited — handle.
                    if hasattr(doc, "make_gl_entries"):
                        doc.make_gl_entries(from_repost=True)
                        actions_run.append("make_gl_entries (post-reversal recovery)")
                else:
                    # Use ERPNext's reverse helper to mark existing GL is_cancelled=1,
                    # then re-build from doc.
                    try:
                        make_reverse_gl_entries(voucher_type=doctype, voucher_no=name)
                    except Exception:
                        # Fallback: manual is_cancelled flip.
                        frappe.db.sql(
                            """UPDATE `tabGL Entry` SET is_cancelled=1, modified=NOW()
                               WHERE voucher_type=%s AND voucher_no=%s AND is_cancelled=0""",
                            (doctype, name),
                        )
                    if hasattr(doc, "make_gl_entries"):
                        doc.make_gl_entries(from_repost=True)
                        actions_run.append("reverse_then_rewrite_gl")

        # (Imbalanced SLE no longer flagged by the audit — that signal was
        # driven by upstream negative-stock data corruption, not GL/SLE
        # pipeline bugs. Use BNS negative-stock-disallow settings to
        # prevent the root cause.)

        gl_after, sle_after = _live_gl_sle_counts(doctype, name)

        return {
            "actions_run": actions_run,
            "skipped": skipped,
            "live_gl_before": gl_before,
            "live_gl_after": gl_after,
            "live_sle_before": sle_before,
            "live_sle_after": sle_after,
        }
    finally:
        # Always release the lock — even on exception. RELEASE_LOCK is a no-op
        # if the lock isn't held by this connection, so this is safe.
        try:
            frappe.db.sql("SELECT RELEASE_LOCK(%s)", (lock_key,))
        except Exception:
            pass


@frappe.whitelist()
def get_audit_spec():
    _bns_require_accounts_read()
    """Expose the spec so report / JS can build dropdowns without hardcoding."""
    return {
        "doctypes": list(AUDIT_SPEC.keys()),
        "statuses": [
            STATUS_MISSING_GL,
            STATUS_MISSING_SLE,
            STATUS_MISSING_BOTH,
            STATUS_IMBALANCED_GL,
        ],
        "tolerance": GL_TOLERANCE,
    }


def scheduled_auto_fix_missing_ledgers() -> None:
    """Weekly scheduler — auto-fix vouchers with missing GL or SLE.

    Gated by two BNS Branch Accounting Settings fields:
      * enable_auto_fix_missing_ledgers (Check) — off by default
      * auto_fix_lookback_days (Int, default 7)  — scan window

    Behavior:
      1. Run audit_gl_sle for the lookback window, statuses Missing-only
         (imbalanced is NOT auto-fixed — that needs human review).
      2. Repair each via repair_gl_sle(fix_missing=1, fix_imbalanced=0).
         Repair uses doc.make_gl_entries / doc.update_stock_ledger
         directly — never cancel + resubmit.
      3. Result summary written to Error Log titled
         'GL SLE Auto-Fix Weekly Run' for the admin to inspect.

    No FY guard — the lookback window is the only safety boundary.
    Wired in hooks.py:scheduler_events.weekly.
    """
    from datetime import timedelta

    import logging

    logger = logging.getLogger(__name__)

    settings_doctype = "BNS Branch Accounting Settings"

    if not cint(frappe.db.get_single_value(settings_doctype, "enable_auto_fix_missing_ledgers")):
        return

    lookback_days = cint(frappe.db.get_single_value(settings_doctype, "auto_fix_lookback_days")) or 7
    cutoff_date = (getdate(frappe.utils.nowdate()) - timedelta(days=lookback_days))

    try:
        rows = audit_gl_sle(
            cutoff_date=str(cutoff_date),
            statuses=[STATUS_MISSING_GL, STATUS_MISSING_SLE, STATUS_MISSING_BOTH],
            limit=10000,
        )
        candidates = [
            {"doctype": r["doctype"], "name": r["name"], "status": r["status"]}
            for r in rows
            if r.get("name") and r.get("name") != "(audit failed)"
            and not (r.get("status") or "").startswith("AUDIT ERROR")
        ]
        if not candidates:
            logger.info(
                "GL SLE Auto-Fix: no missing-ledger docs found (cutoff=%s, lookback=%dd)",
                cutoff_date, lookback_days,
            )
            return

        result = repair_gl_sle(
            docs=candidates,
            cutoff_date=str(cutoff_date),
            fix_missing=1,
            fix_imbalanced=0,
            dry_run=0,
            force_sync=1,
        )

        # Inline result (force_sync=1 keeps it synchronous). Build a
        # human-readable summary and log it.
        attempted = result.get("attempted", 0)
        repaired_list = result.get("repaired", []) or []
        skipped_list = result.get("skipped", []) or []
        errors_list = result.get("errors", []) or []

        actually_mutated = sum(
            1
            for row in repaired_list
            if (row.get("details") or {}).get("actions_run")
        )

        summary_lines = [
            "GL SLE Auto-Fix Weekly Run",
            "",
            f"Cutoff date: {cutoff_date} ({lookback_days} days back)",
            f"Attempted:        {attempted}",
            f"Mutated:          {actually_mutated}",
            f"Already OK:       {len(repaired_list) - actually_mutated}",
            f"Skipped by guard: {len(skipped_list)}",
            f"Errors:           {len(errors_list)}",
        ]
        if errors_list:
            summary_lines.append("")
            summary_lines.append("First 5 errors:")
            for err in errors_list[:5]:
                summary_lines.append(
                    f"  - {err.get('doctype')} {err.get('name')}: {err.get('error')}"
                )
        summary = "\n".join(summary_lines)

        frappe.log_error(
            title=f"GL SLE Auto-Fix: {actually_mutated} mutated, {len(errors_list)} errors",
            message=summary,
        )
        logger.info(summary.replace("\n", " | "))
    except Exception:
        frappe.log_error(
            title="GL SLE Auto-Fix scheduler crashed",
            message=frappe.get_traceback(),
        )
