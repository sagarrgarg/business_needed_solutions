"""
Auto Payment Reconciliation Service - FIFO Style

This module provides automated FIFO-based payment reconciliation for all
customers and suppliers in a company. It mimics the behavior of the
manual Payment Reconciliation tool but runs automatically across all parties.

Features:
- FIFO allocation: oldest invoices are matched with oldest payments first
- Support for future-dated payments (optional)
- Batch processing with logging
- Dry-run mode for testing
- Manual trigger via whitelisted function
- Scheduled job integration
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate
from frappe.utils.background_jobs import is_job_enqueued
import erpnext
from erpnext.accounts.party import get_party_account
from erpnext.accounts.utils import get_outstanding_invoices, reconcile_against_document
from erpnext.controllers.accounts_controller import get_advance_payment_entries_for_regional
import logging

logger = logging.getLogger(__name__)


def get_parties_with_unreconciled_balances(company, party_type, party=None):
    """
    Get list of parties (Customers or Suppliers) that have unreconciled balances.
    """
    from frappe.query_builder.functions import Sum
    
    account_type = "Receivable" if party_type == "Customer" else "Payable"
    
    ple = frappe.qb.DocType("Payment Ledger Entry")
    
    query = (
        frappe.qb.from_(ple)
        .select(ple.party)
        .distinct()
        .where(
            (ple.company == company)
            & (ple.party_type == party_type)
            & (ple.account_type == account_type)
            & (ple.delinked == 0)
        )
        .groupby(ple.party)
        .having(Sum(ple.amount_in_account_currency) != 0)
    )
    
    if party:
        query = query.where(ple.party == party)
    
    parties_with_outstanding = [row[0] for row in query.run()]
    
    return parties_with_outstanding if parties_with_outstanding else []


def get_unallocated_payments(company, party_type, party, receivable_payable_account,
                             include_future_payments=True, to_date=None):
    """Get unallocated payments for a party."""
    to_date = to_date or nowdate()
    order_doctype = "Sales Order" if party_type == "Customer" else "Purchase Order"
    
    condition = frappe._dict({
        "company": company,
        "get_payments": True,
    })
    
    if not include_future_payments:
        condition["to_payment_date"] = to_date
    
    payment_entries = get_advance_payment_entries_for_regional(
        party_type,
        party,
        [receivable_payable_account],
        order_doctype,
        against_all_orders=True,
        limit=1000,
        condition=condition,
    )
    
    journal_entries = get_unallocated_journal_entries(
        company, party_type, party, receivable_payable_account,
        include_future_payments, to_date
    )
    
    dr_cr_notes = get_outstanding_dr_cr_notes(
        company, party_type, party, receivable_payable_account,
        include_future_payments, to_date
    )
    
    all_payments = payment_entries + journal_entries + dr_cr_notes
    
    all_payments = sorted(
        all_payments, 
        key=lambda k: k.get("posting_date") or getdate(nowdate())
    )
    
    return all_payments


def get_unallocated_journal_entries(company, party_type, party, receivable_payable_account,
                                     include_future_payments=True, to_date=None):
    """Get unallocated Journal Entries for a party."""
    to_date = to_date or nowdate()
    
    je = frappe.qb.DocType("Journal Entry")
    jea = frappe.qb.DocType("Journal Entry Account")
    
    account_type = erpnext.get_party_account_type(party_type)
    
    if account_type == "Receivable":
        dr_or_cr = jea.credit_in_account_currency - jea.debit_in_account_currency
    else:
        dr_or_cr = jea.debit_in_account_currency - jea.credit_in_account_currency
    
    conditions = [
        je.docstatus == 1,
        jea.party_type == party_type,
        jea.party == party,
        jea.account == receivable_payable_account,
        (
            (jea.reference_type == "")
            | (jea.reference_type.isnull())
            | (jea.reference_type.isin(("Sales Order", "Purchase Order")))
        ),
        dr_or_cr > 0
    ]
    
    if not include_future_payments:
        conditions.append(je.posting_date <= to_date)
    
    from frappe.query_builder import Criterion
    from frappe.query_builder.custom import ConstantColumn
    
    journal_query = (
        frappe.qb.from_(je)
        .inner_join(jea).on(jea.parent == je.name)
        .select(
            ConstantColumn("Journal Entry").as_("reference_type"),
            je.name.as_("reference_name"),
            je.posting_date,
            je.remark.as_("remarks"),
            jea.name.as_("reference_row"),
            dr_or_cr.as_("amount"),
            jea.is_advance,
            jea.exchange_rate,
            jea.account_currency.as_("currency"),
            jea.cost_center,
        )
        .where(Criterion.all(conditions))
        .orderby(je.posting_date)
        .limit(1000)
    )
    
    return list(journal_query.run(as_dict=True))


def get_outstanding_dr_cr_notes(company, party_type, party, receivable_payable_account,
                                 include_future_payments=True, to_date=None):
    """Get outstanding debit/credit notes for a party."""
    to_date = to_date or nowdate()
    voucher_type = "Sales Invoice" if party_type == "Customer" else "Purchase Invoice"
    
    from frappe.query_builder import Criterion
    from frappe.query_builder.custom import ConstantColumn
    from erpnext.accounts.utils import QueryPaymentLedger
    
    doc = frappe.qb.DocType(voucher_type)
    ple = frappe.qb.DocType("Payment Ledger Entry")
    
    conditions = [
        doc.docstatus == 1,
        doc[frappe.scrub(party_type)] == party,
        doc.is_return == 1,
        doc.outstanding_amount != 0
    ]
    
    if not include_future_payments:
        conditions.append(doc.posting_date <= to_date)
    
    return_invoices_query = (
        frappe.qb.from_(doc)
        .select(
            ConstantColumn(voucher_type).as_("voucher_type"),
            doc.name.as_("voucher_no"),
            doc.return_against,
        )
        .where(Criterion.all(conditions))
        .limit(1000)
    )
    
    return_invoices = return_invoices_query.run(as_dict=True)
    
    if not return_invoices:
        return []
    
    account_type = "Receivable" if party_type == "Customer" else "Payable"
    common_filter = [
        ple.account_type == account_type,
        ple.account == receivable_payable_account,
        ple.party_type == party_type,
        ple.party == party,
    ]
    
    ple_query = QueryPaymentLedger()
    return_outstanding = ple_query.get_voucher_outstandings(
        vouchers=return_invoices,
        common_filter=common_filter,
        posting_date=[],
        get_payments=True,
    )
    
    outstanding_dr_or_cr = []
    for inv in return_outstanding:
        if inv.outstanding != 0:
            outstanding_dr_or_cr.append(
                frappe._dict({
                    "reference_type": inv.voucher_type,
                    "reference_name": inv.voucher_no,
                    "amount": -(inv.outstanding_in_account_currency),
                    "posting_date": inv.posting_date,
                    "currency": inv.currency,
                    "cost_center": inv.cost_center,
                    "remarks": inv.remarks if hasattr(inv, 'remarks') else "",
                })
            )
    
    return outstanding_dr_or_cr


def allocate_fifo(invoices, payments, max_allocations=0):
    """
    Allocate payments to invoices using FIFO logic.
    
    Args:
        invoices: List of outstanding invoices
        payments: List of unallocated payments
        max_allocations: Maximum number of allocations to generate (0 = unlimited)
    
    Returns:
        Tuple of (allocations list, has_more boolean)
    """
    if not invoices or not payments:
        return [], False
    
    invoices = sorted(invoices, key=lambda x: x.get("posting_date") or getdate("1900-01-01"))
    payments = sorted(payments, key=lambda x: x.get("posting_date") or getdate("1900-01-01"))
    
    allocations = []
    has_more = False
    
    for pay in payments:
        original_amount = flt(pay.get("amount"))
        pay["unreconciled_amount"] = original_amount  # Total unallocated amount at start
        pay_remaining = original_amount  # Track what's left to allocate
        
        if pay_remaining <= 0:
            continue
            
        for inv in invoices:
            # Check if we've reached the batch limit
            if max_allocations > 0 and len(allocations) >= max_allocations:
                has_more = True
                break
                
            inv_outstanding = flt(inv.get("outstanding_amount", 0))
            
            if inv_outstanding <= 0:
                continue
                
            allocated = min(pay_remaining, inv_outstanding)
            
            if allocated > 0:
                allocation = frappe._dict({
                    "reference_type": pay.get("reference_type"),
                    "reference_name": pay.get("reference_name"),
                    "reference_row": pay.get("reference_row"),
                    "invoice_type": inv.get("voucher_type"),
                    "invoice_number": inv.get("voucher_no"),
                    "allocated_amount": allocated,
                    "unreconciled_amount": original_amount,  # Original total amount
                    "unadjusted_amount": pay_remaining,  # Amount before this allocation
                    "cost_center": pay.get("cost_center"),
                    "currency": inv.get("currency"),
                })
                allocations.append(allocation)
                
                pay_remaining -= allocated
                inv["outstanding_amount"] = inv_outstanding - allocated
                
            if pay_remaining <= 0:
                break
        
        # Check again after inner loop
        if max_allocations > 0 and len(allocations) >= max_allocations:
            has_more = True
            break
    
    return allocations, has_more


def reconcile_party_fifo(company, party_type, party, include_future_payments=True, 
                         dry_run=False, max_allocations=0):
    """
    Reconcile all payments for a single party using FIFO logic.
    
    Args:
        company: Company name
        party_type: "Customer" or "Supplier"
        party: Party name
        include_future_payments: Include future-dated payments
        dry_run: If True, don't actually reconcile
        max_allocations: Max allocations to process (0 = unlimited)
    
    Returns:
        Dict with status, allocations count, and has_more flag
    """
    result = {
        "party": party,
        "party_type": party_type,
        "status": "success",
        "allocations": 0,
        "has_more": False,
        "error": None,
        "details": []
    }
    
    try:
        receivable_payable_account = get_party_account(party_type, party, company)
        
        if not receivable_payable_account:
            result["status"] = "skipped"
            result["error"] = "No receivable/payable account found"
            return result
        
        invoices = get_outstanding_invoices(
            party_type,
            party,
            [receivable_payable_account],
            common_filter=None,
            posting_date=None,
            limit=1000,
        )
        
        if not invoices:
            result["status"] = "skipped"
            result["error"] = "No outstanding invoices"
            return result
        
        payments = get_unallocated_payments(
            company, party_type, party, receivable_payable_account,
            include_future_payments=include_future_payments
        )
        
        if not payments:
            result["status"] = "skipped"
            result["error"] = "No unallocated payments"
            return result
        
        allocations, has_more = allocate_fifo(invoices, payments, max_allocations)
        
        if not allocations:
            result["status"] = "skipped"
            result["error"] = "No allocations generated"
            return result
        
        result["allocations"] = len(allocations)
        result["has_more"] = has_more
        result["details"] = [
            {
                "payment": f"{a['reference_type']}:{a['reference_name']}",
                "invoice": f"{a['invoice_type']}:{a['invoice_number']}",
                "amount": a['allocated_amount']
            }
            for a in allocations
        ]
        
        if dry_run:
            result["status"] = "dry_run"
            return result
        
        dr_or_cr = (
            "credit_in_account_currency"
            if erpnext.get_party_account_type(party_type) == "Receivable"
            else "debit_in_account_currency"
        )
        
        entry_list = []
        dr_or_cr_notes = []
        
        for alloc in allocations:
            payment_details = frappe._dict({
                "voucher_type": alloc.get("reference_type"),
                "voucher_no": alloc.get("reference_name"),
                "voucher_detail_no": alloc.get("reference_row"),
                "against_voucher_type": alloc.get("invoice_type"),
                "against_voucher": alloc.get("invoice_number"),
                "account": receivable_payable_account,
                "party_type": party_type,
                "party": party,
                "dr_or_cr": dr_or_cr,
                "unreconciled_amount": flt(alloc.get("unreconciled_amount")),
                "unadjusted_amount": flt(alloc.get("unadjusted_amount")),  # Amount before this allocation
                "allocated_amount": flt(alloc.get("allocated_amount")),
                "difference_amount": 0,
                "cost_center": alloc.get("cost_center"),
            })
            
            if alloc.get("reference_type") in ("Sales Invoice", "Purchase Invoice"):
                dr_or_cr_notes.append(payment_details)
            else:
                entry_list.append(payment_details)
        
        if entry_list:
            reconcile_against_document(entry_list)
        
        if dr_or_cr_notes:
            from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import (
                reconcile_dr_cr_note
            )
            reconcile_dr_cr_note(dr_or_cr_notes, company)
        
        frappe.db.commit()
        result["status"] = "reconciled"
        
    except Exception as e:
        frappe.db.rollback()
        result["status"] = "error"
        result["error"] = str(e)
        logger.exception(f"Error reconciling {party_type} {party}: {e}")
    
    return result


@frappe.whitelist()
def reconcile_all_parties(company=None, include_future_payments=True, dry_run=False,
                          party_types=None, specific_party=None, specific_party_type=None,
                          batch_size=0):
    """
    Reconcile all customers and suppliers in a company using FIFO logic.
    
    Args:
        company: Company name (defaults to default company)
        include_future_payments: Whether to include future-dated payments (default True)
        dry_run: If True, don't actually reconcile, just return what would be done
        party_types: List or JSON string of party types (default: ["Customer", "Supplier"])
        specific_party: Optional specific party to reconcile
        specific_party_type: Required if specific_party is provided
        batch_size: Max total allocations across all parties (0 = unlimited)
    """
    import json as json_module
    
    # Handle string to boolean/int conversion
    if isinstance(include_future_payments, str):
        include_future_payments = include_future_payments.lower() in ("true", "1", "yes")
    if isinstance(dry_run, str):
        dry_run = dry_run.lower() in ("true", "1", "yes")
    if isinstance(batch_size, str):
        batch_size = int(batch_size) if batch_size.isdigit() else 0
    batch_size = int(batch_size or 0)
    
    company = company or frappe.defaults.get_global_default("company")
    
    if not company:
        frappe.throw(_("Please specify a company"))
    
    # Handle party_types - can be None, string (JSON), or list
    if party_types is None:
        party_types = ["Customer", "Supplier"]
    elif isinstance(party_types, str):
        try:
            party_types = json_module.loads(party_types)
        except (json_module.JSONDecodeError, ValueError):
            party_types = [party_types]
    
    if not isinstance(party_types, list):
        party_types = [party_types]
    
    results = {
        "company": company,
        "dry_run": dry_run,
        "include_future_payments": include_future_payments,
        "batch_size": batch_size,
        "summary": {
            "total_parties": 0,
            "reconciled": 0,
            "skipped": 0,
            "errors": 0,
            "total_allocations": 0,
            "has_more": False,
        },
        "details": []
    }
    
    total_allocations = 0
    batch_exhausted = False
    
    for party_type in party_types:
        if batch_exhausted:
            break
            
        if specific_party and specific_party_type:
            if party_type != specific_party_type:
                continue
            parties = [specific_party]
        else:
            parties = get_parties_with_unreconciled_balances(company, party_type)
        
        for idx, party in enumerate(parties):
            if batch_exhausted:
                break
                
            results["summary"]["total_parties"] += 1
            
            # Calculate remaining batch for this party
            remaining_batch = 0
            if batch_size > 0:
                remaining_batch = batch_size - total_allocations
                if remaining_batch <= 0:
                    batch_exhausted = True
                    results["summary"]["has_more"] = True
                    break
            
            party_result = reconcile_party_fifo(
                company=company,
                party_type=party_type,
                party=party,
                include_future_payments=include_future_payments,
                dry_run=dry_run,
                max_allocations=remaining_batch
            )
            
            if party_result["status"] in ("reconciled", "dry_run"):
                results["summary"]["reconciled"] += 1
            elif party_result["status"] == "skipped":
                results["summary"]["skipped"] += 1
            else:
                results["summary"]["errors"] += 1
            
            alloc_count = party_result.get("allocations", 0)
            total_allocations += alloc_count
            results["summary"]["total_allocations"] = total_allocations
            
            # Check if this party had more to process
            if party_result.get("has_more"):
                results["summary"]["has_more"] = True
                batch_exhausted = True
            
            # Check if we've hit the overall batch limit
            if batch_size > 0 and total_allocations >= batch_size:
                batch_exhausted = True
                results["summary"]["has_more"] = True
            
            if party_result["allocations"] > 0 or party_result["status"] == "error":
                results["details"].append(party_result)
    
    return results


def run_scheduled_reconciliation():
    """Scheduled job entry point for auto FIFO reconciliation."""
    bns_settings = frappe.get_single("BNS Settings")
    
    if not bns_settings.enable_auto_fifo_reconciliation:
        logger.info("Auto FIFO reconciliation is disabled in BNS Settings")
        return
    
    include_future_payments = bns_settings.include_future_payments_in_reconciliation
    batch_size = int(bns_settings.reconciliation_batch_size or 0)
    
    companies = frappe.get_all("Company", filters={"is_group": 0}, pluck="name")
    
    for company in companies:
        job_name = f"auto_fifo_reconcile_{frappe.scrub(company)}"
        
        if is_job_enqueued(job_name):
            logger.info(f"Auto FIFO reconciliation job already running for {company}")
            continue
        
        frappe.enqueue(
            method="business_needed_solutions.business_needed_solutions.auto_payment_reconcile._run_reconciliation_for_company",
            queue="long",
            timeout=3600,
            is_async=True,
            job_name=job_name,
            company=company,
            include_future_payments=include_future_payments,
            batch_size=batch_size,
        )
        
        logger.info(f"Enqueued auto FIFO reconciliation for {company} (batch_size={batch_size})")


def _run_reconciliation_for_company(company, include_future_payments=True, batch_size=0):
    """Internal function to run reconciliation for a single company."""
    result = reconcile_all_parties(
        company=company,
        include_future_payments=include_future_payments,
        dry_run=False,
        batch_size=batch_size,
    )
    
    try:
        status_msg = (
            f"Allocations: {result['summary']['total_allocations']}, "
            f"Parties: {result['summary']['reconciled']}, "
            f"Errors: {result['summary']['errors']}"
        )
        if result['summary'].get('has_more'):
            status_msg += " (more pending)"
        
        frappe.db.set_value("BNS Settings", "BNS Settings", {
            "last_reconciliation_run": frappe.utils.now(),
            "last_reconciliation_status": status_msg
        })
        frappe.db.commit()
    except Exception as e:
        logger.warning(f"Could not update BNS Settings status: {e}")
    
    return result


@frappe.whitelist()
def get_reconciliation_preview(company, party_type, party, include_future_payments=True):
    """Get a preview of what would be reconciled for a specific party."""
    if isinstance(include_future_payments, str):
        include_future_payments = include_future_payments.lower() in ("true", "1", "yes")
    
    receivable_payable_account = get_party_account(party_type, party, company)
    
    if not receivable_payable_account:
        return {"error": "No receivable/payable account found"}
    
    invoices = get_outstanding_invoices(
        party_type,
        party,
        [receivable_payable_account],
        limit=100,
    )
    
    payments = get_unallocated_payments(
        company, party_type, party, receivable_payable_account,
        include_future_payments=include_future_payments
    )
    
    allocations, has_more = allocate_fifo(list(invoices), list(payments))
    
    return {
        "company": company,
        "party_type": party_type,
        "party": party,
        "receivable_payable_account": receivable_payable_account,
        "invoices": [
            {
                "voucher_no": inv.get("voucher_no"),
                "voucher_type": inv.get("voucher_type"),
                "posting_date": str(inv.get("posting_date")),
                "due_date": str(inv.get("due_date")) if inv.get("due_date") else None,
                "invoice_amount": inv.get("invoice_amount"),
                "outstanding_amount": inv.get("outstanding_amount"),
            }
            for inv in invoices
        ],
        "payments": [
            {
                "reference_name": pay.get("reference_name"),
                "reference_type": pay.get("reference_type"),
                "posting_date": str(pay.get("posting_date")),
                "amount": pay.get("amount"),
            }
            for pay in payments
        ],
        "allocations": [
            {
                "payment": f"{a['reference_type']}:{a['reference_name']}",
                "invoice": f"{a['invoice_type']}:{a['invoice_number']}",
                "amount": a['allocated_amount'],
            }
            for a in allocations
        ]
    }
