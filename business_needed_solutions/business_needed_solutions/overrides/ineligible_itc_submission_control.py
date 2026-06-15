import frappe
from frappe import _


def _will_make_itc_ineligible(doc) -> bool:
	"""True when this PR/PI would make GST ITC ineligible (capitalised to the
	GST Expense account) per India Compliance's own determination.

	Uses IC's IneligibleITC.update_item_ineligibility so the gate matches
	exactly what IC will book at submit — covers Section 17(5) item flags AND
	place-of-supply restrictions (which aren't persisted on the document).
	If India Compliance isn't installed, there's nothing to gate.
	"""
	try:
		from india_compliance.gst_india.overrides.ineligible_itc import DOCTYPE_MAPPING
	except Exception:
		return False

	if doc.doctype not in DOCTYPE_MAPPING:
		return False

	try:
		checker = DOCTYPE_MAPPING[doc.doctype](doc)
		checker.update_item_ineligibility()
		return bool(doc.get("_has_ineligible_itc_items"))
	except Exception:
		# Never block submission on a detection error — log and allow.
		frappe.log_error(title=f"BNS ineligible-ITC gate detection failed: {doc.doctype} {doc.name}")
		return False


def restrict_ineligible_itc_submission(doc, method=None):
	"""before_submit gate: a PR/PI that books ineligible ITC may be submitted
	only by the role configured in BNS Settings. Opt-in via
	`restrict_ineligible_itc_submission`; authorised role defaults to
	Accounts Manager."""
	if doc.doctype not in ("Purchase Receipt", "Purchase Invoice"):
		return

	# get_cached_doc().get() returns None for an unknown field (unlike
	# get_single_value, which throws) — safe if this runs before the field
	# is migrated onto a site.
	settings = frappe.get_cached_doc("BNS Settings")
	if not settings.get("restrict_ineligible_itc_submission"):
		return

	if not _will_make_itc_ineligible(doc):
		return

	role = settings.get("ineligible_itc_authorized_role") or "Accounts Manager"
	if role in frappe.get_roles(frappe.session.user):
		return

	frappe.throw(
		_(
			"This {0} books <b>ineligible GST ITC</b> (capitalised to the GST Expense "
			"account) — usually a Place-of-Supply or Section 17(5) restriction. Only "
			"users with the <b>{1}</b> role may submit such an entry. Please verify the "
			"Place of Supply / item ITC eligibility, or ask an authorised user to submit."
		).format(_(doc.doctype), role),
		title=_("Ineligible ITC — Submission Restricted"),
	)
