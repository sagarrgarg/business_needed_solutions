# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""Bulk cancel Sales Invoice in background.

Caller passes list-view filters (same shape as frappe.get_list accepts).
We resolve the SI set, enqueue chunked jobs on the long queue, and emit
realtime progress so the UI can show a progress bar.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _

BATCH_SIZE = 50
QUEUE = "long"
JOB_TIMEOUT = 3600
REALTIME_EVENT = "bns_bulk_cancel_si_progress"
SETTINGS_FLAG = "enable_bulk_cancel_sales_invoice"


def _ensure_enabled() -> None:
	if not frappe.db.get_single_value("BNS Settings", SETTINGS_FLAG):
		frappe.throw(
			_("Bulk Cancel for Sales Invoice is disabled. Enable it in BNS Settings → General."),
			frappe.PermissionError,
		)


@frappe.whitelist()
def is_enabled() -> dict:
	"""Lightweight check for the UI so it can hide the menu items."""
	if frappe.session.user == "Guest":
		raise frappe.PermissionError
	frappe.has_permission("Sales Invoice", ptype="read", throw=True)
	return {"enabled": bool(frappe.db.get_single_value("BNS Settings", SETTINGS_FLAG))}


def _parse_filters(filters: Any) -> Any:
	if filters is None:
		return None
	if isinstance(filters, str):
		try:
			return json.loads(filters)
		except Exception:
			frappe.throw(_("Invalid filters payload"))
	return filters


def _resolve_names(filters: Any, limit: int | None = None) -> list[str]:
	# get_list honours the user's permissions; bulk cancel should respect them too.
	kwargs = dict(
		doctype="Sales Invoice",
		filters=filters or {},
		fields=["name"],
		order_by="posting_date desc, name desc",
		limit_page_length=0,
		ignore_permissions=False,
	)
	if limit:
		kwargs["limit_page_length"] = int(limit)
	rows = frappe.get_list(**kwargs)
	return [r["name"] for r in rows]


@frappe.whitelist()
def preview(filters: Any = None) -> dict:
	"""Return submitted / draft / cancelled counts for the given filters.

	UI calls this first so the user sees the impact before kicking off.
	"""
	frappe.has_permission("Sales Invoice", ptype="cancel", throw=True)
	_ensure_enabled()
	filters = _parse_filters(filters)
	base = filters if isinstance(filters, dict) else None

	if isinstance(filters, list):
		def _with(extra):
			return filters + [["Sales Invoice", "docstatus", "=", extra]]
		submitted = len(_resolve_names(_with(1)))
		drafts = len(_resolve_names(_with(0)))
		cancelled = len(_resolve_names(_with(2)))
	else:
		base = dict(base or {})
		submitted = len(_resolve_names({**base, "docstatus": 1}))
		drafts = len(_resolve_names({**base, "docstatus": 0}))
		cancelled = len(_resolve_names({**base, "docstatus": 2}))

	return {
		"submitted": submitted,
		"drafts": drafts,
		"cancelled": cancelled,
		"total_actionable": submitted,
	}


@frappe.whitelist()
def enqueue_bulk_cancel(filters: Any = None, max_docs: int | None = None) -> dict:
	"""Enqueue background jobs to cancel all submitted SI matching filters.

	Only docstatus=1 docs are cancelled. Drafts and already-cancelled are
	skipped. Returns the job batch token so UI can subscribe to progress.
	"""
	_ensure_enabled()
	if not frappe.has_permission("Sales Invoice", ptype="cancel"):
		frappe.throw(_("You do not have permission to cancel Sales Invoice"))

	filters = _parse_filters(filters)

	# Force docstatus=1 regardless of what the user passed
	if isinstance(filters, list):
		filters = [f for f in filters if not (
			isinstance(f, (list, tuple)) and len(f) >= 3 and f[-3] == "docstatus"
		)]
		filters.append(["Sales Invoice", "docstatus", "=", 1])
	else:
		filters = dict(filters or {})
		filters["docstatus"] = 1

	names = _resolve_names(filters, limit=max_docs)
	total = len(names)
	if not total:
		return {"enqueued_jobs": 0, "total": 0, "token": None}

	token = frappe.generate_hash(length=10)
	user = frappe.session.user

	# Marker doc in cache so workers can update shared progress counter
	frappe.cache().set_value(
		f"bns_bulk_cancel:{token}",
		{"total": total, "done": 0, "failed": 0, "user": user},
		expires_in_sec=24 * 3600,
	)

	jobs = 0
	for i in range(0, total, BATCH_SIZE):
		chunk = names[i : i + BATCH_SIZE]
		frappe.enqueue(
			"business_needed_solutions.business_needed_solutions.bulk_cancel.cancel_si_batch",
			queue=QUEUE,
			timeout=JOB_TIMEOUT,
			job_name=f"bns_si_cancel_{token}_{i // BATCH_SIZE}",
			token=token,
			names=chunk,
			user=user,
		)
		jobs += 1

	frappe.msgprint(
		_("Queued {0} background jobs to cancel {1} Sales Invoices.").format(jobs, total),
		alert=True,
		indicator="blue",
	)
	return {"enqueued_jobs": jobs, "total": total, "token": token, "batch_size": BATCH_SIZE}


def cancel_si_batch(token: str, names: list[str], user: str) -> None:
	"""Worker entry. Cancels one chunk, updates shared counter, emits progress."""
	done = 0
	failed = 0
	for name in names:
		try:
			doc = frappe.get_doc("Sales Invoice", name)
			if doc.docstatus == 1:
				doc.flags.ignore_permissions = False  # respect cancel perms
				doc.cancel()
				done += 1
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			failed += 1
			frappe.log_error(
				message=frappe.get_traceback()[:140000],
				title=f"bns_bulk_cancel_si:{name}",
			)

	key = f"bns_bulk_cancel:{token}"
	state = frappe.cache().get_value(key) or {"total": len(names), "done": 0, "failed": 0, "user": user}
	state["done"] = int(state.get("done", 0)) + done
	state["failed"] = int(state.get("failed", 0)) + failed
	frappe.cache().set_value(key, state, expires_in_sec=24 * 3600)

	frappe.publish_realtime(
		event=REALTIME_EVENT,
		message={
			"token": token,
			"total": state.get("total"),
			"done": state["done"],
			"failed": state["failed"],
		},
		user=user,
	)


@frappe.whitelist()
def get_progress(token: str) -> dict:
	frappe.has_permission("Sales Invoice", ptype="cancel", throw=True)
	state = frappe.cache().get_value(f"bns_bulk_cancel:{token}") or {}
	return {
		"token": token,
		"total": state.get("total", 0),
		"done": state.get("done", 0),
		"failed": state.get("failed", 0),
	}


JOB_PREFIX = "bns_si_cancel_"


@frappe.whitelist()
def stop_all(force_running: int = 0) -> dict:
	"""Cancel all queued bulk-cancel jobs. Optionally stop currently-running ones too.

	Queued jobs are cancelled cleanly (removed from queue, no work done).
	Running jobs are mid-batch — by default we leave them; pass force_running=1
	to send SIGINT to the worker (kills the current batch, may leave the
	in-flight doc in inconsistent state for that single SI — others already
	committed are safe).
	"""
	_ensure_enabled()
	if not frappe.has_permission("Sales Invoice", ptype="cancel"):
		frappe.throw(_("You do not have permission to manage Sales Invoice cancellations"))

	from frappe.utils.background_jobs import get_queue
	from rq.command import send_stop_job_command
	from rq.exceptions import InvalidJobOperation, NoSuchJobError

	q = get_queue(QUEUE)

	cancelled_queued = 0
	stopped_running = 0
	left_running = 0

	# Queued jobs — drop them.
	for job in list(q.jobs):
		try:
			name = (getattr(job, "id", "") or "") + " " + (getattr(job, "kwargs", {}) or {}).get("job_name", "")
			if JOB_PREFIX in name or _is_bulk_cancel_job(job):
				job.cancel()
				try:
					job.delete()
				except Exception:
					pass
				cancelled_queued += 1
		except (InvalidJobOperation, NoSuchJobError):
			continue
		except Exception:
			frappe.log_error(frappe.get_traceback()[:140000], "bns_bulk_cancel_stop_all:queued")

	# Running jobs.
	try:
		registry = q.started_job_registry
		from rq.job import Job
		for job_id in registry.get_job_ids():
			try:
				job = Job.fetch(job_id, connection=q.connection)
				if not _is_bulk_cancel_job(job):
					continue
				if int(force_running or 0):
					send_stop_job_command(q.connection, job_id)
					stopped_running += 1
				else:
					left_running += 1
			except (InvalidJobOperation, NoSuchJobError):
				continue
			except Exception:
				frappe.log_error(frappe.get_traceback()[:140000], "bns_bulk_cancel_stop_all:running")
	except Exception:
		frappe.log_error(frappe.get_traceback()[:140000], "bns_bulk_cancel_stop_all:registry")

	# Wipe progress markers so UI doesn't keep polling dead tokens.
	try:
		frappe.cache().delete_keys("bns_bulk_cancel:")
	except Exception:
		frappe.log_error(frappe.get_traceback()[:140000], "bns_bulk_cancel_stop_all:cache_clear")

	frappe.msgprint(
		_("Cancelled {0} queued jobs. Stopped {1} running. Left {2} running.").format(
			cancelled_queued, stopped_running, left_running
		),
		alert=True,
		indicator="orange",
	)
	return {
		"cancelled_queued": cancelled_queued,
		"stopped_running": stopped_running,
		"left_running": left_running,
	}


def _is_bulk_cancel_job(job) -> bool:
	"""Best-effort match: job id contains our token prefix, or func path matches."""
	try:
		jid = getattr(job, "id", "") or ""
		if JOB_PREFIX in jid:
			return True
		func = getattr(job, "func_name", "") or ""
		if func.endswith("bulk_cancel.cancel_si_batch"):
			return True
	except Exception:
		pass
	return False


@frappe.whitelist()
def list_active_jobs() -> dict:
	"""Return queued + running bulk-cancel jobs so UI can confirm before stopping."""
	frappe.has_permission("Sales Invoice", ptype="cancel", throw=True)
	from frappe.utils.background_jobs import get_queue

	q = get_queue(QUEUE)
	queued = [j.id for j in list(q.jobs) if _is_bulk_cancel_job(j)]

	running = []
	try:
		from rq.job import Job
		for job_id in q.started_job_registry.get_job_ids():
			try:
				j = Job.fetch(job_id, connection=q.connection)
				if _is_bulk_cancel_job(j):
					running.append(job_id)
			except Exception:
				continue
	except Exception:
		pass

	return {"queued": queued, "running": running, "queued_count": len(queued), "running_count": len(running)}
