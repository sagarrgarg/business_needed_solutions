"""Point internal SI/PI debit_to / credit_to at the account their GL is on.

The BNS internal rewrite posts the receivable / payable to the Internal Debtor /
Creditor, but submitted invoices still named Debtors / Creditors. ERPNext's
Payment Entry, reconciliation and outstanding updates follow the invoice's
account, so they missed these invoices. New invoices are aligned at submit
(prepare_internal_invoice_for_gl_rewrite); this aligns the ones already posted.

Only the account field changes, and only where the invoice's own live party GL
row already sits on the internal account. No GL or ledger row is touched. An
invoice that another voucher (e.g. a common-party Journal Entry) still settles on
the old account is left as it is, so that voucher is not orphaned.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "BNS Branch Accounting Settings"):
		return
	settings = frappe.get_single("BNS Branch Accounting Settings")
	pairs = (
		("Sales Invoice", "debit_to", "Customer", settings.get("internal_branch_debtor_account")),
		("Purchase Invoice", "credit_to", "Supplier", settings.get("internal_branch_creditor_account")),
	)
	for doctype, field, party_type, account in pairs:
		if not account:
			continue
		frappe.db.sql(
			f"""
			UPDATE `tab{doctype}` inv
			SET inv.`{field}` = %(account)s
			WHERE inv.docstatus = 1
			  AND inv.`{field}` != %(account)s
			  AND EXISTS (
				SELECT 1 FROM `tabGL Entry` gle
				WHERE gle.voucher_type = %(doctype)s AND gle.voucher_no = inv.name
				  AND gle.is_cancelled = 0 AND gle.account = %(account)s
				  AND gle.party_type = %(party_type)s
			  )
			  AND NOT EXISTS (
				SELECT 1 FROM `tabGL Entry` gle
				WHERE gle.voucher_type = %(doctype)s AND gle.voucher_no = inv.name
				  AND gle.is_cancelled = 0 AND gle.account = inv.`{field}`
			  )
			  AND NOT EXISTS (
				SELECT 1 FROM `tabPayment Ledger Entry` ple
				WHERE ple.against_voucher_type = %(doctype)s AND ple.against_voucher_no = inv.name
				  AND ple.voucher_no != inv.name AND ple.delinked = 0
				  AND ple.account = inv.`{field}`
			  )
			""",
			{"account": account, "doctype": doctype, "party_type": party_type},
		)
