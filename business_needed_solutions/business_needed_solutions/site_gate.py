"""Keep BNS's runtime patches to the sites that have BNS installed.

BNS replaces some ERPNext functions on their module or class, which changes them for the
whole worker process, and one worker serves every site on the bench. Each replacement is
installed through site_gated(), so a site without BNS keeps running ERPNext's original.
"""

import functools
import inspect

import frappe

APP = "business_needed_solutions"


def bns_installed() -> bool:
	"""True when BNS is installed on the current site; False outside a site."""
	try:
		return APP in frappe.get_installed_apps()
	except Exception:
		return False


def site_gated(original, replacement):
	"""A function that runs `replacement` on sites with BNS installed and `original` on others.

	Arguments pass through untouched, so each side is called exactly as if it were installed
	on its own. Marker attributes already set on `replacement` (used to detect an existing
	patch) carry over to the returned function.
	"""

	@functools.wraps(replacement)
	def gated(*args, **kwargs):
		if bns_installed():
			return replacement(*args, **kwargs)
		return original(*args, **kwargs)

	gated._bns_original = original
	return gated


def call_arguments(func, *args, **kwargs) -> dict:
	"""The arguments `func` would receive for this call, by parameter name, defaults included.

	BNS wrappers take ``*args, **kwargs`` and hand them to ERPNext unchanged, so a parameter
	ERPNext adds or renames in a later version can never break the call. When a wrapper also
	needs one of the values itself, it reads it here, through ERPNext's own signature, rather
	than from a hard-coded position. Returns {} if the call does not fit the signature (the
	original call then raises ERPNext's own error).
	"""
	try:
		bound = inspect.signature(func).bind(*args, **kwargs)
	except (TypeError, ValueError):
		return {}
	bound.apply_defaults()
	return dict(bound.arguments)
