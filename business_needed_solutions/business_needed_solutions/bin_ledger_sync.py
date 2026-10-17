"""
Keep every Bin equal to the last live Stock Ledger Entry of its item and warehouse.

ERPNext writes ``actual_qty``, ``stock_value`` and ``valuation_rate`` on the Bin from the
stock ledger as each entry is processed (``update_entries_after.update_bin``). The Bin
drifts from the ledger when that write never lands: a Repost Item Valuation that fails
or is skipped, a cancellation whose repost dies, a bin left behind after its ledger was
emptied (``reset_bin_without_stock_ledger_entries`` only runs inside a repost that names
the pair), or legacy rows imported straight into ``tabBin``. Once a Bin is wrong,
Stock Projected Qty, availability checks, reorder and reservations are wrong with it,
and nothing in ERPNext revisits it until the next repost of that exact pair.

This module makes the ledger the only source of truth for those three fields:

- ``audit_bin_ledger``  -- read only; lists every pair where Bin and ledger disagree.
- ``sync_bin_ledger``   -- rewrites the disagreeing Bins from the ledger (dry run by default).
- ``scheduled_bin_ledger_sync_recent`` (hourly) -- pairs whose ledger or Bin changed in the
  last ``RECENT_HOURS`` hours.
- ``scheduled_bin_ledger_sync_full`` (daily) and ``after_migrate_bin_ledger_sync`` -- every pair.

A pair with a Repost Item Valuation currently ``In Progress`` for that item and warehouse
is skipped: its ledger is mid-rewrite and the repost itself will set the Bin when it ends.

Gate: ``BNS Branch Accounting Settings.sync_bins_with_ledger`` (default ON; a missing field
during the deploy -> migrate window also counts as ON, because the whole point is that the
Bin matches the ledger in every circumstance).
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, flt, now_datetime

QTY_TOLERANCE = 1e-6
VALUE_TOLERANCE = 0.01
RECENT_HOURS = 26
LOG_TITLE = "BNS Bin Ledger Sync"
SETTINGS_DOCTYPE = "BNS Branch Accounting Settings"
SETTINGS_FIELD = "sync_bins_with_ledger"

Pair = tuple[str, str]


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


def bin_ledger_sync_enabled() -> bool:
	"""Live, uncached read of the toggle. Missing row or field -> ON."""
	try:
		rows = frappe.db.sql(
			"""SELECT value FROM `tabSingles`
               WHERE doctype=%s AND field=%s""",
			(SETTINGS_DOCTYPE, SETTINGS_FIELD),
		)
	except Exception:
		return True
	if not rows:
		return True
	return bool(cint(rows[0][0]))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _scope_conditions(
	company: str | None, item_code: str | None, warehouse: str | None, alias: str = ""
) -> tuple[str, dict[str, Any]]:
	"""SQL tail (starting with AND) and params for the optional scope filters."""
	prefix = f"{alias}." if alias else ""
	conds, params = [], {}
	if company:
		conds.append(f"{prefix}company = %(company)s")
		params["company"] = company
	if item_code:
		conds.append(f"{prefix}item_code = %(item_code)s")
		params["item_code"] = item_code
	if warehouse:
		conds.append(f"{prefix}warehouse = %(warehouse)s")
		params["warehouse"] = warehouse
	return (" AND " + " AND ".join(conds)) if conds else "", params


def last_ledger_rows(
	company: str | None = None,
	item_code: str | None = None,
	warehouse: str | None = None,
	pairs: list[Pair] | None = None,
) -> dict[Pair, dict[str, Any]]:
	"""Last live SLE per (item_code, warehouse): what the Bin must say.

	Ordering is ERPNext's own (``posting_datetime desc, creation desc``), the same one
	``get_balance_qty_from_sle`` and the stock ledger reposter use.
	"""
	extra, params = _scope_conditions(company, item_code, warehouse)
	pair_filter = ""
	if pairs is not None:
		if not pairs:
			return {}
		pair_filter = " AND (item_code, warehouse) IN %(pairs)s"
		params["pairs"] = tuple(pairs)
	rows = frappe.db.sql(
		f"""
        SELECT s.item_code, s.warehouse, s.company, s.qty_after_transaction AS actual_qty,
               s.stock_value, s.valuation_rate
        FROM (
            SELECT item_code, warehouse, company, qty_after_transaction, stock_value, valuation_rate,
                   ROW_NUMBER() OVER (
                       PARTITION BY item_code, warehouse
                       ORDER BY posting_datetime DESC, creation DESC
                   ) AS rn
            FROM `tabStock Ledger Entry`
            WHERE is_cancelled = 0 {extra} {pair_filter}
        ) s
        WHERE s.rn = 1
        """,
		params,
		as_dict=True,
	)
	return {(r.item_code, r.warehouse): r for r in rows}


def bin_rows(
	company: str | None = None,
	item_code: str | None = None,
	warehouse: str | None = None,
	pairs: list[Pair] | None = None,
) -> dict[Pair, dict[str, Any]]:
	extra, params = _scope_conditions(None, item_code, warehouse, alias="b")
	pair_filter = ""
	if pairs is not None:
		if not pairs:
			return {}
		pair_filter = " AND (b.item_code, b.warehouse) IN %(pairs)s"
		params["pairs"] = tuple(pairs)
	company_join = ""
	if company:
		company_join = " INNER JOIN `tabWarehouse` w ON w.name = b.warehouse AND w.company = %(company)s"
		params["company"] = company
	rows = frappe.db.sql(
		f"""
        SELECT b.name, b.item_code, b.warehouse, b.actual_qty, b.stock_value, b.valuation_rate
        FROM `tabBin` b {company_join}
        WHERE 1 = 1 {extra} {pair_filter}
        """,
		params,
		as_dict=True,
	)
	return {(r.item_code, r.warehouse): r for r in rows}


def recently_touched_pairs(hours: int = RECENT_HOURS) -> list[Pair]:
	"""Pairs whose ledger rows or Bin were written in the window (incremental scope)."""
	since = add_to_date(now_datetime(), hours=-abs(hours))
	sle = frappe.db.sql(
		"""SELECT DISTINCT item_code, warehouse FROM `tabStock Ledger Entry`
           WHERE modified >= %s OR creation >= %s""",
		(since, since),
	)
	bins = frappe.db.sql(
		"""SELECT DISTINCT item_code, warehouse FROM `tabBin` WHERE modified >= %s""",
		(since,),
	)
	return sorted({(r[0], r[1]) for r in sle} | {(r[0], r[1]) for r in bins})


def pairs_with_repost_in_progress() -> set:
	rows = frappe.db.sql(
		"""SELECT item_code, warehouse FROM `tabRepost Item Valuation`
           WHERE docstatus = 1 AND status = 'In Progress'
             AND IFNULL(item_code, '') != '' AND IFNULL(warehouse, '') != ''"""
	)
	return {(r[0], r[1]) for r in rows}


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------


def expected_bin_values(ledger_row: dict[str, Any] | None) -> dict[str, float]:
	"""What the Bin must carry for a pair; no live ledger row means an empty bin."""
	if not ledger_row:
		return {"actual_qty": 0.0, "stock_value": 0.0}
	values = {
		"actual_qty": flt(ledger_row.get("actual_qty")),
		"stock_value": flt(ledger_row.get("stock_value")),
	}
	if ledger_row.get("valuation_rate") is not None:
		values["valuation_rate"] = flt(ledger_row.get("valuation_rate"))
	return values


def bin_differs(bin_row: dict[str, Any] | None, expected: dict[str, float]) -> list[str]:
	"""Names of the fields on which the Bin disagrees with the ledger."""
	if bin_row is None:
		# No bin yet: only a non-empty ledger position needs one.
		return [f for f in ("actual_qty", "stock_value") if abs(expected.get(f, 0.0)) > _tol(f)]
	return [f for f, v in expected.items() if abs(flt(bin_row.get(f)) - flt(v)) > _tol(f)]


def _tol(field: str) -> float:
	return QTY_TOLERANCE if field == "actual_qty" else VALUE_TOLERANCE


def audit_bin_ledger(
	company: str | None = None,
	item_code: str | None = None,
	warehouse: str | None = None,
	pairs: list[Pair] | None = None,
) -> dict[str, Any]:
	"""Read-only comparison. Returns the pairs to fix and why."""
	ledger = last_ledger_rows(company, item_code, warehouse, pairs)
	bins = bin_rows(company, item_code, warehouse, pairs)
	in_progress = pairs_with_repost_in_progress()

	mismatched, orphan_bins, missing_bins, skipped = [], [], [], []
	for pair in sorted(set(ledger) | set(bins)):
		if pair in in_progress:
			skipped.append({"item_code": pair[0], "warehouse": pair[1], "reason": "repost in progress"})
			continue
		ledger_row = ledger.get(pair)
		bin_row = bins.get(pair)
		expected = expected_bin_values(ledger_row)
		fields = bin_differs(bin_row, expected)
		if not fields:
			continue
		entry = {
			"item_code": pair[0],
			"warehouse": pair[1],
			"bin": bin_row.get("name") if bin_row else None,
			"fields": fields,
			"bin_values": {f: flt(bin_row.get(f)) for f in expected} if bin_row else None,
			"ledger_values": expected,
		}
		if bin_row is None:
			missing_bins.append(entry)
		elif ledger_row is None:
			orphan_bins.append(entry)
		else:
			mismatched.append(entry)

	return {
		"pairs_checked": len(set(ledger) | set(bins)),
		"mismatched": mismatched,
		"orphan_bins": orphan_bins,
		"missing_bins": missing_bins,
		"skipped": skipped,
	}


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def _write_bin(entry: dict[str, Any]) -> None:
	from erpnext.stock.utils import get_or_make_bin

	bin_name = entry.get("bin") or get_or_make_bin(entry["item_code"], entry["warehouse"])
	bin_doc = frappe.get_doc("Bin", bin_name)
	for field, value in entry["ledger_values"].items():
		bin_doc.set(field, flt(value))
	bin_doc.set_projected_qty()
	bin_doc.db_update()
	bin_doc.clear_cache()


def sync_bin_ledger(
	dry_run: bool = True,
	company: str | None = None,
	item_code: str | None = None,
	warehouse: str | None = None,
	pairs: list[Pair] | None = None,
	limit: int | None = None,
	log: bool = True,
) -> dict[str, Any]:
	"""Rewrite every disagreeing Bin from the ledger. Dry run returns the plan only."""
	audit = audit_bin_ledger(company, item_code, warehouse, pairs)
	plan = audit["mismatched"] + audit["orphan_bins"] + audit["missing_bins"]
	if limit:
		plan = plan[: cint(limit)]

	fixed, failed = [], []
	if not dry_run:
		for entry in plan:
			try:
				_write_bin(entry)
				fixed.append(entry)
			except Exception as exc:  # keep going: one bad pair must not stop the rest
				failed.append({**entry, "error": str(exc)[:300]})
		if fixed or failed:
			frappe.db.commit()

	summary = {
		"dry_run": bool(dry_run),
		"pairs_checked": audit["pairs_checked"],
		"planned": len(plan),
		"fixed": len(fixed),
		"failed": len(failed),
		"skipped_in_progress": len(audit["skipped"]),
		"mismatched": len(audit["mismatched"]),
		"orphan_bins": len(audit["orphan_bins"]),
		"missing_bins": len(audit["missing_bins"]),
		"rows": plan if dry_run else fixed,
		"failures": failed,
	}
	if log and not dry_run and (fixed or failed):
		_log_summary(summary)
	return summary


def _log_summary(summary: dict[str, Any]) -> None:
	lines = [
		f"pairs checked {summary['pairs_checked']}, fixed {summary['fixed']}, failed {summary['failed']}, "
		f"skipped (repost in progress) {summary['skipped_in_progress']}"
	]
	for row in summary["rows"][:200]:
		lines.append(
			f"{row['item_code']} @ {row['warehouse']}: {row['fields']} bin={row['bin_values']} "
			f"ledger={row['ledger_values']}"
		)
	for row in summary["failures"][:50]:
		lines.append(f"FAILED {row['item_code']} @ {row['warehouse']}: {row['error']}")
	if len(summary["rows"]) > 200:
		lines.append(f"... {len(summary['rows']) - 200} more")
	frappe.log_error(message="\n".join(lines), title=LOG_TITLE)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


@frappe.whitelist()
def run_bin_ledger_sync(
	dry_run: int = 1,
	company: str | None = None,
	item_code: str | None = None,
	warehouse: str | None = None,
	limit: int | None = None,
) -> dict[str, Any]:
	"""Manual run. Needs write on Bin (Stock Manager) because it rewrites Bins."""
	if not frappe.has_permission("Bin", "write"):
		frappe.throw(
			_("You need write permission on Bin to run the bin-ledger sync."), frappe.PermissionError
		)
	return sync_bin_ledger(
		dry_run=bool(cint(dry_run)),
		company=company or None,
		item_code=item_code or None,
		warehouse=warehouse or None,
		limit=cint(limit) or None,
	)


def scheduled_bin_ledger_sync_recent() -> None:
	"""Hourly: pairs whose ledger or Bin moved in the last RECENT_HOURS hours."""
	if not bin_ledger_sync_enabled():
		return
	pairs = recently_touched_pairs()
	if not pairs:
		return
	sync_bin_ledger(dry_run=False, pairs=pairs)


def scheduled_bin_ledger_sync_full() -> None:
	"""Daily: every pair."""
	if not bin_ledger_sync_enabled():
		return
	sync_bin_ledger(dry_run=False)


def after_migrate_bin_ledger_sync() -> None:
	"""Post-migrate: bring every Bin in line once the new code is live. Never fails a migrate."""
	try:
		if not bin_ledger_sync_enabled():
			return
		sync_bin_ledger(dry_run=False)
	except Exception:
		frappe.log_error(title=LOG_TITLE, message=frappe.get_traceback())
