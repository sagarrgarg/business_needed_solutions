"""BNS structured Asset naming (Phase 1 — Business Needed Solutions core).

New Asset names follow ``{company_abbr}/{category_abbr}/{item_code}/{###}``
(e.g. ``KGOPL/OE/FA-01/001``). The ``###`` is a 3-digit unit counter scoped per
unique ``(company_abbr, category_abbr, item_code)`` prefix, so repeat units of
the same item increment while any new combination restarts at 001.

Gated by ``BNS Settings.enable_bns_asset_naming``. When the toggle is off (or the
inputs can't be resolved), the ``autoname`` hook leaves ``doc.name`` unset and
ERPNext falls back to the standard ``naming_series`` (``ACC-ASS-.YYYY.-``).
Existing assets keep their old names — this only affects newly created ones.
"""

import frappe
from frappe import _
from frappe.model.naming import make_autoname

CATEGORY_ABBR_FIELD = "bns_category_abbr"


def _asset_naming_enabled() -> bool:
	"""True only when the BNS Settings toggle exists (§1 migrate guard) and is on."""
	try:
		if not frappe.get_meta("BNS Settings").has_field("enable_bns_asset_naming"):
			return False
	except Exception:
		return False
	return bool(frappe.db.get_single_value("BNS Settings", "enable_bns_asset_naming"))


def bns_asset_autoname(doc, method=None):
	"""``autoname`` hook on Asset. Sets a structured name when enabled; otherwise
	returns quietly so ERPNext's naming_series takes over."""
	# Amended docs are named ORIGINAL-1 upstream before autoname runs; belt-and-
	# braces guard in case name is already resolved.
	if doc.get("name"):
		return
	if not _asset_naming_enabled():
		return

	company = doc.get("company")
	category = doc.get("asset_category")
	item_code = doc.get("item_code")
	if not (company and category and item_code):
		# Missing inputs — let the standard series handle it rather than throw.
		return

	company_abbr = frappe.get_cached_value("Company", company, "abbr")
	if not company_abbr:
		return

	category_abbr = frappe.get_cached_value("Asset Category", category, CATEGORY_ABBR_FIELD)
	if not category_abbr:
		frappe.throw(
			_("Set the Series Abbreviation on Asset Category {0} before creating assets under it.").format(category),
			title=_("Asset Series Abbreviation Missing"),
		)

	prefix = f"{company_abbr}/{str(category_abbr).strip()}/{item_code}/"
	doc.name = make_autoname(prefix + ".###", doc=doc)


def validate_asset_category_abbr(doc, method=None):
	"""``validate`` hook on Asset Category. The series abbreviation is immutable
	once set (changing it would fork the counter and desync existing names) and
	unique across categories (two categories must not share a prefix space)."""
	if not frappe.get_meta("Asset Category").has_field(CATEGORY_ABBR_FIELD):
		return

	abbr = (doc.get(CATEGORY_ABBR_FIELD) or "").strip()
	if not abbr:
		return

	if "/" in abbr:
		frappe.throw(_("Series Abbreviation cannot contain '/', it is the name separator."))

	# Normalise the stored value to the stripped form.
	if doc.get(CATEGORY_ABBR_FIELD) != abbr:
		doc.set(CATEGORY_ABBR_FIELD, abbr)

	# Immutable once set.
	if not doc.is_new():
		old = frappe.db.get_value("Asset Category", doc.name, CATEGORY_ABBR_FIELD)
		if old and old != abbr:
			frappe.throw(
				_("Series Abbreviation cannot be changed once set (was {0}). It would desync existing asset names.").format(old)
			)

	# Unique across categories (case-insensitive).
	dupe = frappe.db.sql(
		"""SELECT name FROM `tabAsset Category`
		WHERE UPPER(TRIM(IFNULL(bns_category_abbr, ''))) = UPPER(%s) AND name != %s LIMIT 1""",
		(abbr, doc.name or ""),
	)
	if dupe:
		frappe.throw(
			_("Series Abbreviation {0} is already used by Asset Category {1}.").format(abbr, dupe[0][0])
		)
