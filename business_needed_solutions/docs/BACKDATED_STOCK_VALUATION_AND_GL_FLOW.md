# Backdated Stock Entries: How Valuation and Accounting Get Updated

> **Purpose:** Explain in plain language and in detail what happens when you post a stock or sales document with a date in the past, and how the system keeps stock values and accounting entries correct.  
> **Audience:** Implementation leads, support, and developers working on BNS internal transfers and reposting.

---

## Table of Contents

1. [Plain-language overview](#1-plain-language-overview)
2. [How Delivery Note and Sales Invoice handle item-wise cost](#2-how-delivery-note-and-sales-invoice-handle-item-wise-cost)
3. [What “backdated” means and why it’s tricky](#3-what-backdated-means-and-why-its-tricky)
4. [High-level flow when a backdated entry is submitted](#4-high-level-flow-when-a-backdated-entry-is-submitted)
5. [Detailed flow: Stock Ledger (SLE) repost](#5-detailed-flow-stock-ledger-sle-repost)
6. [Detailed flow: Accounting (GL) repost](#6-detailed-flow-accounting-gl-repost)
7. [Flowcharts](#7-flowcharts)
8. [BNS internal transfers and backdated repost](#8-bns-internal-transfers-and-backdated-repost)
9. [Reference: Key files in ERPNext](#9-reference-key-files-in-erpnext)

---

## 1. Plain-language overview

- **Stock documents** (Delivery Note, Purchase Receipt, Sales Invoice with stock, Stock Entry, etc.) move quantity in/out of warehouses and assign a **cost (valuation rate)** to each movement.
- That cost is stored in:
  - The **Stock Ledger** (per item, per warehouse, per transaction), and
  - Often **written back** onto the document’s item row (e.g. “incoming rate” or “valuation rate”) so the document shows what cost was actually used.
- When you submit a document **with a date in the past** (a “backdated” entry), every **later** transaction that used stock from the same item/warehouse was calculated using the **old** sequence of events. So the system must **re-run** the valuation and **update**:
  - All affected **Stock Ledger** rows (rates and values), and
  - All affected **accounting (GL)** entries that depend on those stock values.

This document describes how that re-run works and how Delivery Note / Sales Invoice fit in (item-wise rate on the document and auto-update from the ledger).

---

## 2. How Delivery Note and Sales Invoice handle item-wise cost

### In simple terms

- **Delivery Note** and **Sales Invoice** (when they update stock) need a **cost per item** for:
  - Reducing stock value (outgoing),
  - COGS (Cost of Goods Sold),
  - And for internal transfers, the “transfer rate” the receiving side (e.g. Purchase Receipt) will use.
- That cost is stored **on the document itself**, on each **item row**, in a field called **incoming rate** (not “valuation rate” — that name is used on purchase-side documents).
- The system does two things:
  1. **Before submit:** It can **pre-fill** that rate from stock (e.g. “what would this item cost if we take it out today?”).
  2. **At submit:** When the stock ledger actually runs (FIFO/LIFO, etc.), it computes the **real** cost used for that line and **writes it back** to the same item row. So the document always ends up with the **actual** rate that was used in the ledger.

So: **Yes, Delivery Note and Sales Invoice manage item-wise valuation rate.** They keep it in the **child table** (item row), and it is **auto-updated** from the stock ledger after the movement is processed. You do **not** need to go and read from the Stock Ledger again for normal use — the document is updated to match.

### In more detail (for developers)

| Aspect | What happens |
|--------|----------------|
| **Field on the document** | Delivery Note Item and Sales Invoice Item have **`incoming_rate`**. There is no “valuation_rate” on these child tables. |
| **Where the rate comes from at first** | `SellingController.set_incoming_rate()` runs for DN/SI. For stock items it calls `get_incoming_rate(...)` with item, warehouse, posting date/time, qty, serial/batch, etc. So the **initial** value can come from **stock** (valuation method / queue). |
| **When creating the Stock Ledger entry** | When building the SLE, the system reads the rate **from the document**: it uses the item row’s **incoming_rate** for Delivery Note / Sales Invoice (see `stock_ledger.py`: `rate_field = "incoming_rate"` for these doctypes). So the SLE is created using the value **already on the child table**. |
| **Auto-update after processing** | After the SLE is processed, `update_outgoing_rate_on_transaction()` runs. For DN/SI it calls `update_rate_on_delivery_and_sales_return(sle, outgoing_rate)`, which does `frappe.db.set_value(sle.voucher_type + " Item", sle.voucher_detail_no, "incoming_rate", outgoing_rate)`. So the **computed outgoing rate** (from FIFO/LIFO, etc.) is **written back** to the document’s item row. |
| **Do we need to “get it from Stock Ledger”?** | For normal display and for BNS “transfer rate” from DN/SI, **no**. The document’s item row is the source of truth once the SLE has been processed. You can take the source document’s **incoming_rate** (or a BNS **transfer_rate** copied from it) and use it on the receiving document (e.g. PR/PI). |

---

## 3. What “backdated” means and why it’s tricky

- **Backdated** = the document’s **posting date** (and possibly time) is **earlier** than some other documents you already submitted.
- Example: You already submitted a Delivery Note dated 15th and a Purchase Receipt dated 20th. Then you submit a **Stock Entry dated 10th**. The system has to:
  - Recompute stock quantities and **valuation** from 10th onward (as if the new entry had always been there).
  - Update every **Stock Ledger** row that is “after” 10th for the same item/warehouse.
  - Then redo **accounting** for every voucher that uses those stock values (e.g. DN on 15th, PR on 20th), so that the books match the new stock values.

So: one backdated submission can trigger a **chain of updates** to both the Stock Ledger and the General Ledger. The next sections describe that chain in plain language first, then in technical detail.

---

## 4. High-level flow when a backdated entry is submitted

1. **User action**  
   User submits (or cancels) a stock document whose posting date is in the past.

2. **System decides repost is needed**  
   The document’s submit/cancel logic calls **repost_future_sle_and_gle()**. That creates or reuses a **Repost Item Valuation** job (per company, date, and voucher or per item/warehouse).

3. **Two big steps**
   - **Step A — Stock Ledger repost**  
     The system takes every “item + warehouse” affected by the backdated document and, from that date/time onward, **re-processes** every Stock Ledger entry in order. For each entry it:
     - Recomputes valuation rate, stock value, and quantity after transaction.
     - **Updates the Stock Ledger row** in the database.
     - Where designed (e.g. DN/SI), **updates the document’s item row** (e.g. incoming_rate) so the document stays in sync with the ledger.
   - **Step B — Accounting repost**  
     The system finds **all vouchers** that have stock movements “after” the backdated date and that are affected by the same item/warehouse. For each such voucher it:
     - **Deletes** the existing GL entries for that voucher.
     - **Regenerates** GL entries using the **current** document and stock values (after the SLE repost).
     - **Posts** the new GL entries.

4. **Result**  
   Stock Ledger and General Ledger are both consistent with the new “history” that includes the backdated entry.

---

## 5. Detailed flow: Stock Ledger (SLE) repost

- Entry point: **Repost Item Valuation** runs **repost_sl_entries(doc)** (in `repost_item_valuation.py`), which calls **repost_future_sle(...)** in `stock_ledger.py`.

- **repost_future_sle**:
  - Builds a list of **(item_code, warehouse, posting_date, posting_time)** to repost (from the backdated voucher or from “Item Warehouse” selection).
  - For each of these, it calls **update_entries_after(args)**.

- **update_entries_after** (class in `stock_ledger.py`):
  - Loads **previous state** for that item/warehouse: quantity after transaction, valuation rate, stock value, stock queue (for FIFO/LIFO) **just before** the first SLE that will be reposted.
  - Fetches **all future SLEs** for this item/warehouse (ordered by posting date/time and creation).
  - For **each** of those SLEs:
    1. **process_sle(sle)**  
       - Uses the current warehouse state and the SLE’s **incoming_rate** or **outgoing_rate** (from the transaction row or from inter-company logic) to recompute:
         - valuation_rate  
         - stock_value_difference  
         - qty_after_transaction  
         - stock_queue (if FIFO/LIFO)  
       - **Updates the SLE row** in the database with these new values.
    2. **update_outgoing_rate_on_transaction(sle)**  
       - For **Delivery Note** and **Sales Invoice**: writes back the computed **outgoing rate** to the document’s item row:  
         `frappe.db.set_value("Delivery Note Item" or "Sales Invoice Item", sle.voucher_detail_no, "incoming_rate", outgoing_rate)`.  
       - So the **document’s item-wise rate is auto-updated** even during repost.
    3. **update_bin_data(sle)**  
       - Updates the **Bin** (item/warehouse summary): actual_qty, valuation_rate, stock_value.

- So: **SLE rows are updated in place**; document item rows (e.g. incoming_rate) and Bins are updated so everything stays in sync.

---

## 6. Detailed flow: Accounting (GL) repost

- Entry point: **Repost Item Valuation** runs **repost_gl_entries(doc)** (in `repost_item_valuation.py`). This only runs if **perpetual inventory** is enabled for the company.

- **repost_gl_entries**:
  - Collects **affected vouchers**: all future stock vouchers that touch the same item(s) and warehouse(s) as the repost (via **get_future_stock_vouchers** and **get_affected_transactions**).
  - Calls **repost_gle_for_stock_vouchers**(list of (voucher_type, voucher_no), posting_date, company, ...) in `erpnext/accounts/utils.py`.

- **repost_gle_for_stock_vouchers**:
  - Sorts the list of vouchers by **posting date** (so earlier documents are handled first).
  - For **each** (voucher_type, voucher_no):
    1. **Delete** all existing GL (and payment ledger) entries for that voucher: **\_delete_accounting_ledger_entries(voucher_type, voucher_no)**.
    2. **Reload** the document: **voucher_obj = frappe.get_doc(voucher_type, voucher_no)**.  
       This loads the **current** state (including any item rates that were updated during the SLE repost, e.g. incoming_rate on DN/SI).
    3. **Regenerate** GL: **expected_gle = voucher_obj.get_gl_entries(warehouse_account)**.  
       This uses the document’s current item rates and stock values (which now reflect the reposted SLE).
    4. **Post** the new GL: **voucher_obj.make_gl_entries(gl_entries=expected_gle, from_repost=True)**.

- So: **Accounting is updated** by deleting old GL and recreating it from the **updated** document and stock data. No manual “edit old GL rows” — it’s always delete + regenerate.

---

## 7. Flowcharts

### 7.1 Overall: What happens when you submit a backdated document

```
[User submits/cancels a document with a date in the past]
                            |
                            v
            [Document's on_submit / on_cancel]
                            |
                            v
            [repost_future_sle_and_gle() is called]
                            |
                            v
            [Repost Item Valuation record is created or used]
                            |
            +---------------+---------------+
            |                               |
            v                               v
   [SLE repost]                     [GL repost]
   (see 7.2)                        (see 7.3)
```

### 7.2 Stock Ledger (SLE) repost — step by step

```
repost_future_sle(args)
    |
    v
[Get list of (item_code, warehouse, posting_date, posting_time) to repost]
    |
    v
[For each (item, warehouse, date, time):]
    |
    v
update_entries_after(args)
    |
    +-- Load "previous" state (qty, valuation rate, stock value, queue) before this point
    |
    +-- Get all future SLEs for this item/warehouse (in time order)
    |
    v
[For each future SLE:]
    |
    +-- process_sle(sle)
    |       - Recompute valuation_rate, stock_value, qty_after_transaction, queue
    |       - UPDATE the SLE row in the database
    |
    +-- update_outgoing_rate_on_transaction(sle)
    |       - For DN/SI: set document item's "incoming_rate" = computed outgoing rate
    |       - For PR/PI (internal): can set item's "valuation_rate"
    |
    +-- update_bin_data(sle)
    |       - Update Bin: actual_qty, valuation_rate, stock_value
    |
    v
[Next SLE ... until no more future SLEs]
```

### 7.3 Accounting (GL) repost — step by step

```
repost_gl_entries(doc)
    |
    +-- If perpetual inventory disabled → exit
    |
    v
[Get all "affected" vouchers: future stock vouchers that use same item/warehouse]
    |
    v
repost_gle_for_stock_vouchers(vouchers, posting_date, company)
    |
    v
[Sort vouchers by posting date]
    |
    v
[For each (voucher_type, voucher_no):]
    |
    +-- _delete_accounting_ledger_entries(voucher_type, voucher_no)
    |       - Removes all GL and payment ledger entries for this voucher
    |
    +-- voucher_obj = frappe.get_doc(voucher_type, voucher_no)
    |       - Reloads document (with updated item rates from SLE repost)
    |
    +-- expected_gle = voucher_obj.get_gl_entries(warehouse_account)
    |       - Builds new GL entries from current document + stock values
    |
    +-- voucher_obj.make_gl_entries(gl_entries=expected_gle, from_repost=True)
    |       - Inserts new GL entries
    |
    v
[Next voucher ...]
```

---

## 8. BNS internal transfers and backdated repost

- In **BNS internal transfer** flow, a **Purchase Receipt** (or Purchase Invoice) can be created from a **Delivery Note** (or Sales Invoice). The **valuation rate** on the PR/PI should match the **outgoing rate** from the DN/SI (often stored as **transfer_rate** on the PR/PI item).
- When a **backdated** entry is submitted:
  - The **DN’s** Stock Ledger (and its item **incoming_rate**) get reposted first (DN is usually before PR in time).
  - The **PR’s** SLEs are then reposted. If the PR’s rate was originally taken from the DN at submit time, the **PR’s stored rate** might still be the “old” one unless we sync it from the DN again.
- So the **BNS internal accounting plan** says: **before** processing the PR’s SLEs during repost, **sync** the PR’s SLE valuation (and if needed the PR item’s **transfer_rate**) from the **already reposted** DN (e.g. from DN’s SLE or from DN item’s **incoming_rate**). That way the PR’s stock value and GL stay consistent with the DN’s updated valuation.
- Implementation idea (as in the plan): in the repost loop, when about to process an SLE for a **Purchase Receipt** that is BNS internal (e.g. `is_bns_internal_supplier`), call a helper like **sync_pr_sle_valuation_from_dn(pr_name)** that:
  - Finds the linked DN (e.g. via `bns_inter_company_reference` or `supplier_delivery_note`).
  - For each PR item (using `bns_internal_delivery_note_item` or `delivery_note_item`), gets the corresponding DN item’s rate (or DN SLE rate).
  - Updates the PR SLE’s **valuation_rate** and **stock_value_difference** (and optionally the PR item’s **transfer_rate**) before the normal **process_sle** runs.

---

## 9. Reference: Key files in ERPNext

| What | File (ERPNext) |
|------|----------------|
| Repost trigger (create job, call SLE + GL repost) | `stock/doctype/repost_item_valuation/repost_item_valuation.py` |
| SLE repost loop | `stock/stock_ledger.py`: `repost_future_sle`, class `update_entries_after` |
| Process one SLE, update doc item rate | `stock/stock_ledger.py`: `process_sle`, `update_outgoing_rate_on_transaction`, `update_rate_on_delivery_and_sales_return` |
| GL repost (delete + regenerate) | `accounts/utils.py`: `repost_gle_for_stock_vouchers` |
| DN/SI set incoming rate from stock (before submit) | `controllers/selling_controller.py`: `set_incoming_rate` |
| Where SLE gets rate from document (DN/SI use incoming_rate) | `stock/stock_ledger.py`: `get_incoming_outgoing_rate_from_transaction` (rate_field = "incoming_rate" for DN/SI) |
| Document calling repost on submit/cancel | e.g. `stock/doctype/delivery_note/delivery_note.py`, `stock/doctype/purchase_receipt/purchase_receipt.py`, `stock/doctype/stock_entry/stock_entry.py`: `repost_future_sle_and_gle()` |

---

*Last updated: 2026. For BNS internal transfer accounting and transfer_rate, see the BNS Internal Accounting Override plan and `bns_branch_accounting` implementation.*
