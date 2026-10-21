"""
Business Needed Solutions - Same Party / Company Address Validation

Blocks submission of a selling or buying document whose party address is the company's own
address: a challan "from Gurukul to Gurukul", or a receipt whose supplier is the receiving
branch itself. A same-GSTIN internal transfer is valid and passes, because its two branches
have different addresses; only the address deciding which branch is which is checked.

Two addresses are the same when they are one Address record, or when their printed text
matches above the threshold in BNS Settings AND carries exactly the same numbers. Numbers
are compared on their own because "Shed B-7" and "Shed B-8" score ~99% as text.

A different GSTIN on the two sides is a different legal entity at the same premises (a
sister concern sharing a shed), so that is allowed. Returns are skipped: a return against an
old document carries its addresses over and must stay possible.

Field names are the same on ERPNext v15 and v16. v16 stores the display fields as Text
Editor, so their text may carry HTML; normalization strips it before comparing.
"""

import re
from difflib import SequenceMatcher

import frappe
from frappe import _
from frappe.utils import cint, flt

try:
	from rapidfuzz import fuzz as _fuzz
except ImportError:  # rapidfuzz ships with ERPNext; difflib keeps this working without it
	_fuzz = None

DEFAULT_THRESHOLD = 90.0

# doctype -> (party address link, party display, company address link, company display,
#             party GSTIN, company GSTIN)
ADDRESS_FIELDS = {
	"Sales Order": (
		"customer_address",
		"address_display",
		"company_address",
		"company_address_display",
		"billing_address_gstin",
		"company_gstin",
	),
	"Sales Invoice": (
		"customer_address",
		"address_display",
		"company_address",
		"company_address_display",
		"billing_address_gstin",
		"company_gstin",
	),
	"Delivery Note": (
		"customer_address",
		"address_display",
		"company_address",
		"company_address_display",
		"billing_address_gstin",
		"company_gstin",
	),
	"Purchase Order": (
		"supplier_address",
		"address_display",
		"billing_address",
		"billing_address_display",
		"supplier_gstin",
		"company_gstin",
	),
	"Purchase Invoice": (
		"supplier_address",
		"address_display",
		"billing_address",
		"billing_address_display",
		"supplier_gstin",
		"company_gstin",
	),
	"Purchase Receipt": (
		"supplier_address",
		"address_display",
		"billing_address",
		"billing_address_display",
		"supplier_gstin",
		"company_gstin",
	),
}

# Lines the address template adds that say nothing about where the premises are
_NOISE_LINE = re.compile(r"(?im)^\s*(gstin|state code|phone|mobile|email|e-mail|fax)\b.*$")
_NOISE_WORD = re.compile(r"(?i)\b(pin\s*code|state\s*code|india)\b")
_LINE_BREAK = re.compile(r"(?i)<br\s*/?>|</p>|</div>")
_TAG = re.compile(r"<[^>]+>")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_NUMBER = re.compile(r"\d+")


def normalize_address(text: str | None) -> str:
	"""Address text reduced to lowercase words and numbers, without HTML or template labels."""
	text = _LINE_BREAK.sub("\n", text or "")
	text = _TAG.sub(" ", text)
	text = _NOISE_LINE.sub(" ", text)
	text = _NOISE_WORD.sub(" ", text)
	text = _NON_ALNUM.sub(" ", text.lower())
	return " ".join(text.split())


def address_similarity(a: str, b: str) -> float:
	"""0-100 similarity of two normalized addresses, word order ignored."""
	if not a or not b:
		return 0.0
	if _fuzz is not None:
		return float(_fuzz.token_sort_ratio(a, b))
	return SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split()))).ratio() * 100


def is_same_address(display_a: str | None, display_b: str | None, threshold: float) -> tuple[bool, float]:
	"""(same, score): text matches at or above `threshold` and every number in it matches."""
	a, b = normalize_address(display_a), normalize_address(display_b)
	score = address_similarity(a, b)
	return bool(score >= threshold and set(_NUMBER.findall(a)) == set(_NUMBER.findall(b))), score


def _gstin(doc, gstin_field: str, address: str | None) -> str:
	gstin = doc.get(gstin_field)
	if not gstin and address:
		gstin = frappe.db.get_value("Address", address, "gstin")
	return (gstin or "").strip().upper()


def _get_threshold() -> float:
	threshold = flt(frappe.db.get_single_value("BNS Settings", "same_address_match_threshold", cache=True))
	return threshold if 0 < threshold <= 100 else DEFAULT_THRESHOLD


def validate_party_company_address_differ(doc, method: str | None = None) -> None:
	"""Block submit when the party address is the company's own address (same GSTIN or none)."""
	fields = ADDRESS_FIELDS.get(doc.doctype)
	if not fields or cint(doc.get("is_return")):
		return
	if not cint(frappe.db.get_single_value("BNS Settings", "block_same_party_company_address", cache=True)):
		return

	party_link, party_display, company_link, company_display, party_gstin_field, company_gstin_field = fields
	party_address, company_address = doc.get(party_link), doc.get(company_link)
	party_text, company_text = doc.get(party_display), doc.get(company_display)

	if party_address and party_address == company_address:
		score = 100.0
	elif party_text and company_text:
		same, score = is_same_address(party_text, company_text, _get_threshold())
		if not same:
			return
	else:
		return

	party_gstin = _gstin(doc, party_gstin_field, party_address)
	company_gstin = _gstin(doc, company_gstin_field, company_address)
	if party_gstin and company_gstin and party_gstin != company_gstin:
		return

	meta = doc.meta
	frappe.throw(
		_(
			"{0} cannot be submitted: the {1} is the company's own address.<br><br>"
			"{1}: {2} (GSTIN {3})<br>"
			"{4}: {5} (GSTIN {6})<br>"
			"Match: {7}%<br><br>"
			"For an internal transfer, the {1} must be the receiving / sending branch, "
			"not the branch this document is made from. Select the correct address and submit again."
		).format(
			_(doc.doctype),
			_(meta.get_label(party_link)),
			frappe.bold(party_address or _("(no link)")),
			party_gstin or "-",
			_(meta.get_label(company_link)),
			frappe.bold(company_address or _("(no link)")),
			company_gstin or "-",
			round(score, 1),
		),
		title=_("Party Address Same as Company Address"),
	)
