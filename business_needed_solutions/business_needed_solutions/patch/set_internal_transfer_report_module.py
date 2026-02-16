"""
Set Report "Internal Transfer Receive Mismatch" module to BNS Branch Accounting.

After the report was moved from business_needed_solutions.report to
bns_branch_accounting.report, existing sites still have the Report doc with
module "Business Needed Solutions", so Frappe loads the wrong path. This patch
updates the module so execute_module uses bns_branch_accounting.report....
"""

import frappe


def execute():
    if not frappe.db.exists("Report", "Internal Transfer Receive Mismatch"):
        return
    frappe.db.set_value(
        "Report",
        "Internal Transfer Receive Mismatch",
        "module",
        "BNS Branch Accounting",
        update_modified=False,
    )
    frappe.db.commit()
