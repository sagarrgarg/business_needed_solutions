"""
Temporary fix for ERPNext Purchase Register tax doubling bug.

Bug: get_invoice_tax_map() in erpnext purchase_register.py queries
`tabPurchase Taxes and Charges` without filtering by parenttype.
When a Purchase Invoice and Purchase Receipt share the same name,
tax amounts are doubled because both document's tax rows get SUMmed.

Fix: Add `and parenttype = 'Purchase Invoice'` to the WHERE clause.

Remove when: ERPNext merges the upstream fix.
Upstream issue: https://github.com/frappe/erpnext/issues/<TBD>
Affected file: erpnext/accounts/report/purchase_register/purchase_register.py
Affected function: get_invoice_tax_map (lines 497-526)
"""

import frappe
from frappe.utils import flt
from erpnext.accounts.report.utils import get_advance_taxes_and_charges

_PATCHED = False


def get_invoice_tax_map(invoice_list, invoice_expense_map, expense_accounts, include_payments=False):
    """Patched version — adds `parenttype = 'Purchase Invoice'` filter."""
    tax_details = frappe.db.sql(
        """
        select parent, account_head, case add_deduct_tax when "Add" then sum(base_tax_amount_after_discount_amount)
        else sum(base_tax_amount_after_discount_amount) * -1 end as tax_amount
        from `tabPurchase Taxes and Charges`
        where parent in (%s) and parenttype = 'Purchase Invoice'
            and category in ('Total', 'Valuation and Total')
            and base_tax_amount_after_discount_amount != 0
        group by parent, account_head, add_deduct_tax
    """
        % ", ".join(["%s"] * len(invoice_list)),
        tuple(inv.name for inv in invoice_list),
        as_dict=1,
    )

    if include_payments:
        tax_details += get_advance_taxes_and_charges(invoice_list)

    invoice_tax_map = {}
    for d in tax_details:
        if d.account_head in expense_accounts:
            if d.account_head in invoice_expense_map[d.parent]:
                invoice_expense_map[d.parent][d.account_head] += flt(d.tax_amount)
            else:
                invoice_expense_map[d.parent][d.account_head] = flt(d.tax_amount)
        else:
            invoice_tax_map.setdefault(d.parent, frappe._dict()).setdefault(d.account_head, [])
            invoice_tax_map[d.parent][d.account_head] = flt(d.tax_amount)

    return invoice_expense_map, invoice_tax_map


def _upstream_is_fixed(func) -> bool:
    """True once the installed function already filters by parenttype: fixed upstream
    by erpnext#54272 / #54443 (v15.106.0+ and v16), where this copy changes nothing and
    would only mask later upstream changes to the function."""
    import inspect
    import re

    try:
        return bool(re.search(r"parenttype\s*=\s*'Purchase Invoice'", inspect.getsource(func)))
    except (OSError, TypeError):
        return False


def apply_purchase_register_fix():
    """Monkey-patch the broken function in ERPNext's purchase_register module."""
    global _PATCHED
    if _PATCHED:
        return
    from erpnext.accounts.report.purchase_register import purchase_register
    if _upstream_is_fixed(purchase_register.get_invoice_tax_map):
        _PATCHED = True
        return
    from business_needed_solutions.business_needed_solutions.site_gate import site_gated

    # site_gated: other sites served by this worker keep ERPNext's own function.
    purchase_register.get_invoice_tax_map = site_gated(purchase_register.get_invoice_tax_map, get_invoice_tax_map)
    _PATCHED = True
