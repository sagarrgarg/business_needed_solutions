def normalize_invoice_discount_credit_note(doc, method=None):
	"""A discount credit note is a money-only return: no stock moves back.

	Runs as before_validate, so ERPNext validates it as the non-stock return it
	becomes (update_stock off, no Serial and Batch Bundles to create or leave
	behind) instead of as the stock return it was mapped from.
	"""
	if not (doc.get("is_return") and doc.get("bns_is_invoice_discount_credit_note")):
		return
	if doc.update_stock:
		doc.update_stock = 0
	for it in doc.items or []:
		for fld in ("delivery_note", "dn_detail", "sales_order", "so_detail", "serial_and_batch_bundle"):
			if it.get(fld):
				it.set(fld, None)
