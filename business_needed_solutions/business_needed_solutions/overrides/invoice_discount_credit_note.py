def normalize_invoice_discount_credit_note(doc, method=None):
	if not (doc.get("is_return") and doc.get("bns_is_invoice_discount_credit_note")):
		return
	if doc.update_stock:
		doc.update_stock = 0
	for it in doc.items or []:
		for fld in ("delivery_note", "dn_detail", "sales_order", "so_detail"):
			if it.get(fld):
				it.set(fld, None)
