# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""Bulk cancel submitted documents in background.

Generic over a fixed allow-list of supported doctypes (Sales Invoice,
Purchase Invoice, Delivery Note, Purchase Receipt, Stock Entry, Journal
Entry, Payment Entry). Caller passes list-view filters (same shape as
frappe.get_list accepts). We resolve the document set, enqueue chunked jobs
on the long queue, and emit realtime progress so the UI can show a bar.

Gated by a single master switch ``enable_bulk_cancel`` in BNS Settings.
Cancellation is best-effort: a doc blocked by linked submitted documents is
recorded as failed (logged to Error Log) and the run continues.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _

# --- Allow-list. The whitelisted API can ONLY ever act on these doctypes. ---
SUPPORTED_DOCTYPES = (
	"Sales Invoice",
	"Purchase Invoice",
	"Delivery Note",
	"Purchase Receipt",
	"Stock Entry",
	"Journal Entry",
	"Payment Entry",
)

BATCH_SIZE = 50
QUEUE = "long"
JOB_TIMEOUT = 3600
REALTIME_EVENT = "bns_bulk_cancel_progress"
SETTINGS_FLAG = "enable_bulk_cancel"

# Job-id prefix so Stop-All / list_active_jobs can identify our jobs.
JOB_PREFIX = "bns_bulk_cancel_"
# Legacy prefix from the SI-only implementation (job_name based). Kept so any
# jobs queued by the old code are still recognised by Stop-All.
LEGACY_PREFIX = "bns_si_cancel_"

CANCEL_BATCH_METHOD = (
	"business_needed_solutions.business_needed_solutions.bulk_cancel.cancel_batch"
)


# --------------------------------------------------------------------------- #
# Guards / helpers
# --------------------------------------------------------------------------- #
def _validate_doctype(doctype: str) -> None:
	if doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(
			_("Bulk Cancel is not supported for {0}.").format(frappe.bold(doctype or "")),
			frappe.PermissionError,
		)


def _ensure_enabled() -> None:
	if not frappe.db.get_single_value("BNS Settings", SETTINGS_FLAG):
		frappe.throw(
			_("Bulk Cancel is disabled. Enable it in BNS Settings → General."),
			frappe.PermissionError,
		)


def _parse_filters(filters: Any) -> Any:
	if filters is None:
		return None
	if isinstance(filters, str):
		try:
			return json.loads(filters)
		except Exception:
			frappe.throw(_("Invalid filters payload"))
	return filters


def _resolve_names(doctype: str, filters: Any, limit: int | None = None) -> list[str]:
	# get_list honours the user's permissions; bulk cancel should respect them too.
	kwargs = dict(
		doctype=doctype,
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


def _force_docstatus(doctype: str, filters: Any, docstatus: int) -> Any:
	"""Strip any caller-supplied docstatus filter and pin it to ``docstatus``."""
	if isinstance(filters, list):
		cleaned = [
			f
			for f in filters
			if not (isinstance(f, (list, tuple)) and len(f) >= 3 and f[-3] == "docstatus")
		]
		cleaned.append([doctype, "docstatus", "=", docstatus])
		return cleaned
	filters = dict(filters or {})
	filters["docstatus"] = docstatus
	return filters


# --------------------------------------------------------------------------- #
# Whitelisted API
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def is_enabled(doctype: str | None = None) -> dict:
	"""Lightweight check for the UI so it can hide the menu items."""
	if frappe.session.user == "Guest":
		raise frappe.PermissionError
	if doctype:
		if doctype not in SUPPORTED_DOCTYPES:
			return {"enabled": False, "supported": list(SUPPORTED_DOCTYPES)}
		frappe.has_permission(doctype, ptype="read", throw=True)
	return {
		"enabled": bool(frappe.db.get_single_value("BNS Settings", SETTINGS_FLAG)),
		"supported": list(SUPPORTED_DOCTYPES),
	}


@frappe.whitelist()
def preview(doctype: str, filters: Any = None) -> dict:
	"""Return submitted / draft / cancelled counts for the given filters.

	UI calls this first so the user sees the impact before kicking off.
	"""
	_validate_doctype(doctype)
	frappe.has_permission(doctype, ptype="cancel", throw=True)
	_ensure_enabled()
	filters = _parse_filters(filters)

	submitted = len(_resolve_names(doctype, _force_docstatus(doctype, filters, 1)))
	drafts = len(_resolve_names(doctype, _force_docstatus(doctype, filters, 0)))
	cancelled = len(_resolve_names(doctype, _force_docstatus(doctype, filters, 2)))

	return {
		"doctype": doctype,
		"submitted": submitted,
		"drafts": drafts,
		"cancelled": cancelled,
		"total_actionable": submitted,
	}


@frappe.whitelist()
def enqueue_bulk_cancel(doctype: str, filters: Any = None, max_docs: int | None = None) -> dict:
	"""Enqueue background jobs to cancel all submitted docs matching filters.

	Only docstatus=1 docs are cancelled. Drafts and already-cancelled are
	skipped. Returns the job batch token so UI can subscribe to progress.
	"""
	_validate_doctype(doctype)
	_ensure_enabled()
	if not frappe.has_permission(doctype, ptype="cancel"):
		frappe.throw(_("You do not have permission to cancel {0}").format(doctype))

	filters = _force_docstatus(doctype, _parse_filters(filters), 1)

	names = _resolve_names(doctype, filters, limit=max_docs)
	total = len(names)
	if not total:
		return {"enqueued_jobs": 0, "total": 0, "token": None}

	token = frappe.generate_hash(length=10)
	user = frappe.session.user
	slug = frappe.scrub(doctype)

	# Marker doc in cache so workers can update shared progress counter
	frappe.cache().set_value(
		f"bns_bulk_cancel:{token}",
		{"total": total, "done": 0, "failed": 0, "user": user, "doctype": doctype},
		expires_in_sec=24 * 3600,
	)

	jobs = 0
	for i in range(0, total, BATCH_SIZE):
		chunk = names[i : i + BATCH_SIZE]
		frappe.enqueue(
			CANCEL_BATCH_METHOD,
			queue=QUEUE,
			timeout=JOB_TIMEOUT,
			# Explicit job_id so the prefix lands in job.id (Stop-All relies on it).
			job_id=f"{JOB_PREFIX}{slug}_{token}_{i // BATCH_SIZE}",
			doctype=doctype,
			token=token,
			names=chunk,
			user=user,
		)
		jobs += 1

	frappe.msgprint(
		_("Queued {0} background jobs to cancel {1} {2}.").format(jobs, total, doctype),
		alert=True,
		indicator="blue",
	)
	return {
		"doctype": doctype,
		"enqueued_jobs": jobs,
		"total": total,
		"token": token,
		"batch_size": BATCH_SIZE,
	}


def cancel_batch(doctype: str, token: str, names: list[str], user: str) -> None:
	"""Worker entry. Cancels one chunk, updates shared counter, emits progress."""
	done = 0
	failed = 0
	for name in names:
		try:
			doc = frappe.get_doc(doctype, name)
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
				title=f"bns_bulk_cancel:{doctype}:{name}"[:140],
			)

	key = f"bns_bulk_cancel:{token}"
	state = frappe.cache().get_value(key) or {
		"total": len(names),
		"done": 0,
		"failed": 0,
		"user": user,
		"doctype": doctype,
	}
	state["done"] = int(state.get("done", 0)) + done
	state["failed"] = int(state.get("failed", 0)) + failed
	frappe.cache().set_value(key, state, expires_in_sec=24 * 3600)

	frappe.publish_realtime(
		event=REALTIME_EVENT,
		message={
			"token": token,
			"doctype": doctype,
			"total": state.get("total"),
			"done": state["done"],
			"failed": state["failed"],
		},
		user=user,
	)


def cancel_si_batch(token: str, names: list[str], user: str) -> None:
	"""Back-compat shim for jobs queued by the old SI-only implementation."""
	return cancel_batch("Sales Invoice", token, names, user)


@frappe.whitelist()
def get_progress(token: str) -> dict:
	state = frappe.cache().get_value(f"bns_bulk_cancel:{token}") or {}
	# Only the user who started the run (or a System Manager) may poll it.
	if state and state.get("user") not in (frappe.session.user,):
		if "System Manager" not in frappe.get_roles():
			raise frappe.PermissionError
	return {
		"token": token,
		"doctype": state.get("doctype"),
		"total": state.get("total", 0),
		"done": state.get("done", 0),
		"failed": state.get("failed", 0),
	}


# --------------------------------------------------------------------------- #
# Stop-All
# --------------------------------------------------------------------------- #
def _job_haystack(job) -> str:
	"""All identity strings for a job, joined — robust to frappe's execute_job
	wrapper (real method lives in job.kwargs['method'], not job.func_name)."""
	kw = getattr(job, "kwargs", None) or {}
	parts = [
		str(getattr(job, "id", "") or ""),
		str(kw.get("method") or ""),
		str(kw.get("job_name") or ""),
		str(getattr(job, "func_name", "") or ""),
	]
	return " ".join(parts)


def _is_bulk_cancel_job(job, doctype: str | None = None) -> bool:
	"""Match our bulk-cancel jobs by job_id prefix or the real method path.

	Frappe enqueues every job through ``execute_job``; the target method is in
	``job.kwargs['method']``, and the id we set carries ``JOB_PREFIX``. The old
	code only inspected ``job.id`` / ``job.func_name`` — neither ever matched,
	which is why Stop-All did nothing.
	"""
	try:
		hay = _job_haystack(job)
	except Exception:
		return False

	ours = (
		"bulk_cancel.cancel_batch" in hay
		or "bulk_cancel.cancel_si_batch" in hay
		or JOB_PREFIX in hay
		or LEGACY_PREFIX in hay
	)
	if not ours:
		return False
	if not doctype:
		return True

	# Legacy SI jobs used LEGACY_PREFIX and carried no doctype slug.
	if doctype == "Sales Invoice" and LEGACY_PREFIX in hay:
		return True
	return f"{JOB_PREFIX}{frappe.scrub(doctype)}_" in hay


@frappe.whitelist()
def list_active_jobs(doctype: str | None = None) -> dict:
	"""Return queued + running bulk-cancel jobs so UI can confirm before stopping."""
	if doctype:
		_validate_doctype(doctype)
		frappe.has_permission(doctype, ptype="cancel", throw=True)
	elif "System Manager" not in frappe.get_roles():
		raise frappe.PermissionError

	from frappe.utils.background_jobs import get_queue

	q = get_queue(QUEUE)
	queued = [j.id for j in list(q.jobs) if _is_bulk_cancel_job(j, doctype)]

	running = []
	try:
		from rq.job import Job

		for job_id in q.started_job_registry.get_job_ids():
			try:
				j = Job.fetch(job_id, connection=q.connection)
				if _is_bulk_cancel_job(j, doctype):
					running.append(job_id)
			except Exception:
				continue
	except Exception:
		pass

	return {
		"doctype": doctype,
		"queued": queued,
		"running": running,
		"queued_count": len(queued),
		"running_count": len(running),
	}


@frappe.whitelist()
def stop_all(doctype: str | None = None, force_running: int = 0) -> dict:
	"""Cancel queued bulk-cancel jobs. Optionally stop currently-running ones too.

	Scoped to ``doctype`` when given, else all bulk-cancel jobs (System Manager
	only). Queued jobs are dropped cleanly. Running jobs are mid-batch — by
	default left to finish; pass force_running=1 to SIGINT the worker (kills the
	current batch; the single in-flight doc may need manual cleanup, others
	already committed are safe).
	"""
	if doctype:
		_validate_doctype(doctype)
		_ensure_enabled()
		if not frappe.has_permission(doctype, ptype="cancel"):
			frappe.throw(_("You do not have permission to manage {0} cancellations").format(doctype))
	elif "System Manager" not in frappe.get_roles():
		raise frappe.PermissionError

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
			if not _is_bulk_cancel_job(job, doctype):
				continue
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
		from rq.job import Job

		for job_id in q.started_job_registry.get_job_ids():
			try:
				job = Job.fetch(job_id, connection=q.connection)
				if not _is_bulk_cancel_job(job, doctype):
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
