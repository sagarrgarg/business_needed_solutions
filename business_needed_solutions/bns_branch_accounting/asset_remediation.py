# Copyright (c) 2026, Business Needed Solutions and Contributors
# License: Commercial

"""One-off remediation for BNS internal fixed-asset transfers posted BEFORE the
asset-transfer feature existed.

Before the feature, an internal transfer of a fixed-asset item:
  - the DN posted no asset GL / the SI posted disposal GL,
  - the receiving PR/PI auto-created a DUPLICATE Asset and posted CWIP/ARBNB,
so the asset was double-counted at company level and no Asset-in-Transit GL was
posted.

This module previews and repairs such documents:
  1. backfill `bns_transferred_asset` on the receiver row from the source asset
     (PI <- the linked SI item's native `asset`; a DN->PR receiver has no native
     source-asset link, so it is reported for MANUAL mapping),
  2. optionally delete the duplicate auto-created asset (only when it is a Draft
     and un-depreciated -- submitted/depreciated duplicates are reported, never
     force-deleted),
  3. repost the doc so the asset-aware GL rewrite posts the NBV transfer legs.

`preview_asset_transfer_remediation` is read-only. `apply_asset_transfer_remediation`
is gated by BNS Branch Accounting Settings write and runs as a background job.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint

from business_needed_solutions.bns_branch_accounting.utils import _bns_repost_voucher_gl, get_bns_repost_job_timeout

_RECEIVER_TYPES = ("Purchase Receipt", "Purchase Invoice")
_SENDER_TYPES = ("Delivery Note", "Sales Invoice")
_RECEIVER_ASSET_PARENT_FIELD = {
	"Purchase Receipt": "purchase_receipt",
	"Purchase Invoice": "purchase_invoice",
}


def _is_fixed_asset_item(item_code):
	return bool(item_code and cint(frappe.db.get_value("Item", item_code, "is_fixed_asset")))


def _fixed_asset_rows(voucher_type, voucher_no):
	"""Item rows on a doc that are fixed-asset items, with current transfer link."""
	child = voucher_type + " Item"
	link_field = "asset" if voucher_type == "Sales Invoice" else "bns_transferred_asset"
	meta = frappe.get_meta(child)
	fields = ["name", "item_code", "idx"]
	if meta.has_field(link_field):
		fields.append(link_field)
	if meta.has_field("sales_invoice_item"):
		fields.append("sales_invoice_item")
	rows = frappe.get_all(child, filters={"parent": voucher_no}, fields=fields, order_by="idx")
	out = []
	for r in rows:
		if _is_fixed_asset_item(r.get("item_code")):
			r["_link_field"] = link_field
			r["_linked_asset"] = (r.get(link_field) or "")
			out.append(r)
	return out


def _duplicate_assets_for_receiver(voucher_type, voucher_no):
	"""Assets auto-created by a receiving PR/PI (linked via purchase_receipt /
	purchase_invoice)."""
	field = _RECEIVER_ASSET_PARENT_FIELD.get(voucher_type)
	if not field:
		return []
	return frappe.get_all(
		"Asset",
		filters={field: voucher_no},
		fields=["name", "docstatus", "status", "calculate_depreciation"],
	)


def _resolve_source_asset_for_pi_row(pi_name, pi_row):
	"""Original asset for a PI row, from the linked Sales Invoice item's native
	`asset` field. Returns None when the source SI/asset cannot be resolved."""
	si = (
		frappe.db.get_value("Purchase Invoice", pi_name, "bns_inter_company_reference")
		or frappe.db.get_value("Purchase Invoice", pi_name, "bill_no")
		or ""
	).strip()
	if not si or not frappe.db.exists("Sales Invoice", si):
		return None
	sii = (pi_row.get("sales_invoice_item") or "").strip()
	if sii:
		asset = frappe.db.get_value("Sales Invoice Item", sii, "asset")
		if asset:
			return asset
	for r in frappe.get_all(
		"Sales Invoice Item",
		filters={"parent": si, "item_code": pi_row.get("item_code")},
		fields=["asset"],
	):
		if r.get("asset"):
			return r.asset
	return None


def _internal_asset_transfer_docs(company=None):
	"""Submitted BNS internal DN/SI/PR/PI that carry fixed-asset item rows."""
	docs = []
	for dt in _SENDER_TYPES + _RECEIVER_TYPES:
		flag = "is_bns_internal_customer" if dt in _SENDER_TYPES else "is_bns_internal_supplier"
		conds = {"docstatus": 1, flag: 1}
		if company:
			conds["company"] = company
		for name in frappe.get_all(dt, filters=conds, pluck="name"):
			if _fixed_asset_rows(dt, name):
				docs.append((dt, name))
	return docs


@frappe.whitelist()
def preview_asset_transfer_remediation(company=None):
	"""Read-only report of internal fixed-asset transfers needing remediation.

	Returns a list of dicts describing each doc: its fixed-asset rows, whether the
	transfer link is set, the resolvable source asset (PI only), duplicate
	auto-created assets, whether Asset-in-Transit GL was already posted, and the
	recommended action.
	"""
	transit = (
		frappe.db.get_single_value("BNS Branch Accounting Settings", "asset_in_transit_account") or ""
	).strip()
	report = []
	for voucher_type, voucher_no in _internal_asset_transfer_docs(company):
		rows = _fixed_asset_rows(voucher_type, voucher_no)
		posted = bool(
			transit
			and frappe.db.exists(
				"GL Entry",
				{"voucher_type": voucher_type, "voucher_no": voucher_no, "account": transit, "is_cancelled": 0},
			)
		)
		duplicates = (
			_duplicate_assets_for_receiver(voucher_type, voucher_no)
			if voucher_type in _RECEIVER_TYPES
			else []
		)
		row_info = []
		needs_link_backfill = False
		for r in rows:
			resolved = None
			if voucher_type == "Purchase Invoice" and not r["_linked_asset"]:
				resolved = _resolve_source_asset_for_pi_row(voucher_no, r)
			if not r["_linked_asset"] and (resolved or voucher_type in ("Purchase Receipt", "Delivery Note")):
				needs_link_backfill = True
			row_info.append({
				"idx": r.get("idx"),
				"item_code": r.get("item_code"),
				"linked_asset": r["_linked_asset"],
				"resolvable_source_asset": resolved,
			})

		if posted and not duplicates and not needs_link_backfill:
			action = "ok"
		elif voucher_type == "Purchase Invoice":
			action = "auto: backfill link + delete draft duplicate + repost"
		elif voucher_type == "Purchase Receipt":
			action = "manual: set bns_transferred_asset (source DN has no native asset link), then repost"
		else:
			action = "repost (sender) once receiver is linked"

		report.append({
			"voucher_type": voucher_type,
			"voucher_no": voucher_no,
			"asset_in_transit_posted": posted,
			"rows": row_info,
			"duplicate_assets": duplicates,
			"action": action,
		})
	return report


@frappe.whitelist()
def apply_asset_transfer_remediation(documents, delete_draft_duplicates=0):
	"""Repair the given documents and repost. Gated by BNS Settings write; enqueued.

	Args:
		documents: JSON list of [{voucher_type, voucher_no}, ...].
		delete_draft_duplicates: when truthy, delete duplicate auto-created assets
			that are still Draft (submitted/depreciated duplicates are never touched).
	"""
	if not frappe.has_permission("BNS Branch Accounting Settings", "write"):
		frappe.throw(
			_("BNS Branch Accounting Settings write permission required."),
			frappe.PermissionError,
		)
	if isinstance(documents, str):
		documents = json.loads(documents)
	if not documents:
		frappe.throw(_("No documents provided for asset-transfer remediation."))

	frappe.enqueue(
		"business_needed_solutions.bns_branch_accounting.asset_remediation._process_asset_remediation_batch",
		queue="long",
		timeout=get_bns_repost_job_timeout(),
		documents=documents,
		delete_draft_duplicates=cint(delete_draft_duplicates),
	)
	return {
		"success": True,
		"message": _("Asset-transfer remediation enqueued for {0} document(s). Check Background Jobs.").format(
			len(documents)
		),
	}


def _process_asset_remediation_batch(documents, delete_draft_duplicates=0):
	"""Worker: backfill receiver asset links, optionally delete draft duplicate
	assets, then repost so the asset-aware GL rewrite posts the transfer legs."""
	success = 0
	errors = 0
	skipped = []
	failures = []

	for entry in documents:
		voucher_type = entry.get("voucher_type") or entry.get("document_type") or ""
		voucher_no = entry.get("voucher_no") or entry.get("document_name") or ""
		if voucher_type not in (_SENDER_TYPES + _RECEIVER_TYPES) or not voucher_no:
			errors += 1
			failures.append(f"{voucher_type or '?'} {voucher_no or '?'}: unsupported")
			continue
		try:
			if frappe.db.get_value(voucher_type, voucher_no, "docstatus") != 1:
				errors += 1
				failures.append(f"{voucher_type} {voucher_no}: not submitted")
				continue

			# 1. Backfill bns_transferred_asset on a Purchase Invoice from the SI.
			if voucher_type == "Purchase Invoice":
				for r in _fixed_asset_rows(voucher_type, voucher_no):
					if r["_linked_asset"]:
						continue
					resolved = _resolve_source_asset_for_pi_row(voucher_no, r)
					if resolved:
						frappe.db.set_value(
							"Purchase Invoice Item", r["name"], "bns_transferred_asset", resolved,
							update_modified=False,
						)
					else:
						skipped.append(f"{voucher_no} row#{r.get('idx')}: source asset unresolved")

			# 2. A Purchase Receipt cannot auto-resolve its source asset; only
			#    proceed if the link was already set manually.
			if voucher_type == "Purchase Receipt":
				unresolved = [r for r in _fixed_asset_rows(voucher_type, voucher_no) if not r["_linked_asset"]]
				if unresolved:
					skipped.append(
						f"{voucher_no}: {len(unresolved)} PR row(s) need manual bns_transferred_asset"
					)

			# 3. Delete duplicate auto-created assets (Draft + un-depreciated only).
			if delete_draft_duplicates and voucher_type in _RECEIVER_TYPES:
				for dup in _duplicate_assets_for_receiver(voucher_type, voucher_no):
					if dup.get("docstatus") == 0:
						frappe.delete_doc("Asset", dup["name"], force=1, ignore_permissions=True)
					else:
						skipped.append(
							f"{voucher_no}: duplicate asset {dup['name']} is submitted "
							f"(status {dup.get('status')}) -- cancel/scrap manually"
						)

			# 4. Repost so the asset-aware GL rewrite posts the NBV transfer legs.
			_bns_repost_voucher_gl(voucher_type, voucher_no)

			success += 1
			frappe.db.commit()
		except Exception as e:
			errors += 1
			frappe.db.rollback()
			failures.append(f"{voucher_type} {voucher_no}: {str(e)[:200]}")
			frappe.log_error(title=f"Asset remediation error: {voucher_type} {voucher_no}")

	message = _("Asset-transfer remediation: {0} reposted, {1} failed, {2} note(s).").format(
		success, errors, len(skipped)
	)
	detail = (failures + skipped)[:30]
	if detail:
		message += "<br><br>" + "<br>".join(frappe.utils.escape_html(d) for d in detail)

	frappe.publish_realtime(
		"msgprint",
		{
			"message": message,
			"title": _("Asset Transfer Remediation"),
			"indicator": "green" if errors == 0 else "orange",
		},
	)
