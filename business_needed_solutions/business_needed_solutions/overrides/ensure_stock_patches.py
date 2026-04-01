"""
Ensure warehouse-level negative stock monkey-patches are applied before
stock documents are submitted. Called via before_submit doc_events.

The apply_patches() function has an internal guard, so this is
a no-op after the first call per worker process.
"""


def before_submit(doc, method=None):
	from business_needed_solutions.business_needed_solutions.overrides.warehouse_negative_stock import (
		apply_patches,
	)

	apply_patches()
