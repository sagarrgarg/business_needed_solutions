# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""BOM Reconciliation Engine.

Reconstructs raw / semi-finished material demand from finished-goods (FG)
production, so an inter-company stock transfer (e.g. RKCW -> GGIL) can be
sequenced *before* consumption instead of dumped at year-end.

Pipeline (FG-first):
  1. FG production  = sum of Manufacture Stock Entry output per FG in window.
  2. BOM explosion  = explode each FG through its formal BOM (multi-level,
                      semi-finished expanded). Fallback to the FG's actual
                      Manufacture-SE component consumption where no active
                      BOM exists.
  3. Component demand = aggregate exploded requirement across all FG.
  4. Local supply/consumption = this company's actual SLE inflow / outflow
                      per component, plus the date consumption first drove
                      the item negative (the DN-must-precede anchor).
  5. Gap            = demand vs local supply; the shortfall is what an
                      inter-company DN must deliver, dated before
                      `first_consumption`.

The report is single-site safe: it computes everything from the company it
runs on. The counter-party (supplier company) availability is optional and
supplied via the `supplier_stock` filter (JSON map item_code -> available
qty) so no cross-site credentials are stored. When supplied, the shortfall
is split into:
  * deliver_via_dn  = min(gap, supplier_available)   -> create DN, dated
                      before first_consumption.
  * unexplained     = gap - supplier_available        -> needs a supplier
                      stock-basis receipt or a production-record fix.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import flt, getdate

# Guard: same Role-Permission-Manager gate used across BNS reports.
from business_needed_solutions.bns_branch_accounting.utils import _bns_require_accounts_read

MANUFACTURE_PURPOSE = "Manufacture"
MAX_BOM_DEPTH = 6  # safety bound for multi-level explosion / cycle guard


def execute(filters: Optional[Dict[str, Any]] = None):
    _bns_require_accounts_read()
    filters = frappe._dict(filters or {})
    _validate_filters(filters)

    fg_items = _resolve_fg_items(filters)
    production = _fg_production(filters, fg_items)
    bom_cache: Dict[str, Optional[List[Dict[str, Any]]]] = {}

    demand: Dict[str, float] = defaultdict(float)
    fg_explosion_source: Dict[str, str] = {}
    for fg, qty in production.items():
        if qty <= 0:
            continue
        components, source = _explode(fg, qty, filters, bom_cache, depth=0, seen=set())
        fg_explosion_source[fg] = source
        for comp, cqty in components.items():
            demand[comp] += cqty

    supplier_stock = _parse_supplier_stock(filters)
    rows = _build_component_rows(filters, demand, supplier_stock, filters.get("negative_only"))
    return _columns(bool(supplier_stock)), rows


def _validate_filters(filters):
    if not filters.get("company"):
        frappe.throw(_("Company is required."))
    if not filters.get("from_date") or not filters.get("to_date"):
        frappe.throw(_("From Date and To Date are required."))
    if getdate(filters.from_date) > getdate(filters.to_date):
        frappe.throw(_("From Date cannot be after To Date."))


def _resolve_fg_items(filters) -> List[str]:
    """FG = items with an active BOM, optionally narrowed by item_group or a
    code prefix. Items that are produced (appear as Manufacture SE output)
    but have no BOM are still picked up via the production scan downstream."""
    conditions = {"docstatus": 1, "is_active": 1, "is_default": 1}
    bom_items = set(
        frappe.get_all("BOM", filters=conditions, pluck="item", limit_page_length=0)
    )
    # Also include any item produced via Manufacture SE in the window, so
    # BOM-less but produced FG are not silently dropped.
    produced = _produced_items(filters)
    fg = bom_items | produced

    if filters.get("fg_item_group"):
        grp_items = set(
            frappe.get_all(
                "Item",
                filters={"item_group": filters.fg_item_group, "is_stock_item": 1},
                pluck="name",
                limit_page_length=0,
            )
        )
        fg &= grp_items
    if filters.get("fg_code_prefix"):
        prefix = filters.fg_code_prefix
        fg = {i for i in fg if i.startswith(prefix)}
    return sorted(fg)


def _produced_items(filters) -> set:
    rows = frappe.db.sql(
        """
        SELECT DISTINCT sed.item_code
        FROM `tabStock Entry Detail` sed
        JOIN `tabStock Entry` se ON se.name = sed.parent
        WHERE se.docstatus = 1
          AND se.purpose = %(purpose)s
          AND se.company = %(company)s
          AND se.posting_date BETWEEN %(from_date)s AND %(to_date)s
          AND sed.is_finished_item = 1
        """,
        {
            "purpose": MANUFACTURE_PURPOSE,
            "company": filters.company,
            "from_date": filters.from_date,
            "to_date": filters.to_date,
        },
        as_dict=False,
    )
    return {r[0] for r in rows}


def _fg_production(filters, fg_items: List[str]) -> Dict[str, float]:
    """Produced qty per FG = positive Manufacture SE output in window."""
    if not fg_items:
        return {}
    rows = frappe.db.sql(
        """
        SELECT sed.item_code, SUM(sed.qty) AS qty
        FROM `tabStock Entry Detail` sed
        JOIN `tabStock Entry` se ON se.name = sed.parent
        WHERE se.docstatus = 1
          AND se.purpose = %(purpose)s
          AND se.company = %(company)s
          AND se.posting_date BETWEEN %(from_date)s AND %(to_date)s
          AND sed.is_finished_item = 1
        GROUP BY sed.item_code
        """,
        {
            "purpose": MANUFACTURE_PURPOSE,
            "company": filters.company,
            "from_date": filters.from_date,
            "to_date": filters.to_date,
        },
        as_dict=True,
    )
    fg_set = set(fg_items)
    return {r.item_code: flt(r.qty) for r in rows if r.item_code in fg_set}


def _get_active_bom_components(fg: str, bom_cache) -> Optional[List[Dict[str, Any]]]:
    """Return per-unit component list for FG's default active BOM, or None."""
    if fg in bom_cache:
        return bom_cache[fg]
    bom_name = frappe.db.get_value(
        "BOM", {"item": fg, "is_active": 1, "is_default": 1, "docstatus": 1}, "name"
    )
    if not bom_name:
        bom_cache[fg] = None
        return None
    bom = frappe.get_doc("BOM", bom_name)
    batch = flt(bom.quantity) or 1.0
    comps = [
        {"item_code": it.item_code, "per_unit": flt(it.stock_qty or it.qty) / batch}
        for it in bom.items
    ]
    bom_cache[fg] = comps
    return comps


def _se_effective_components(fg: str, fg_qty: float, filters) -> List[Dict[str, Any]]:
    """Fallback recipe: actual components consumed across the FG's Manufacture
    Stock Entries in the window, normalized per 1 FG unit produced."""
    rows = frappe.db.sql(
        """
        SELECT consumed.item_code,
               SUM(consumed.qty) AS consumed_qty,
               prod.fg_qty AS fg_qty
        FROM `tabStock Entry Detail` consumed
        JOIN `tabStock Entry` se ON se.name = consumed.parent
        JOIN (
            SELECT se2.name, SUM(sed2.qty) AS fg_qty
            FROM `tabStock Entry Detail` sed2
            JOIN `tabStock Entry` se2 ON se2.name = sed2.parent
            WHERE se2.docstatus = 1 AND se2.purpose = %(purpose)s
              AND se2.company = %(company)s
              AND se2.posting_date BETWEEN %(from_date)s AND %(to_date)s
              AND sed2.is_finished_item = 1 AND sed2.item_code = %(fg)s
            GROUP BY se2.name
        ) prod ON prod.name = se.name
        WHERE consumed.s_warehouse IS NOT NULL
          AND consumed.is_finished_item = 0
        GROUP BY consumed.item_code
        """,
        {
            "purpose": MANUFACTURE_PURPOSE,
            "company": filters.company,
            "from_date": filters.from_date,
            "to_date": filters.to_date,
            "fg": fg,
        },
        as_dict=True,
    )
    total_fg = flt(fg_qty) or 1.0
    return [
        {"item_code": r.item_code, "per_unit": flt(r.consumed_qty) / total_fg}
        for r in rows
    ]


def _explode(fg: str, fg_qty: float, filters, bom_cache, depth: int, seen: set
             ) -> Tuple[Dict[str, float], str]:
    """Multi-level explosion. Returns (component->qty, source_tag)."""
    if depth >= MAX_BOM_DEPTH or fg in seen:
        return {}, "depth_guard"
    seen = seen | {fg}

    comps = _get_active_bom_components(fg, bom_cache)
    source = "formal_bom"
    if comps is None:
        comps = _se_effective_components(fg, fg_qty, filters)
        source = "se_actual"

    out: Dict[str, float] = defaultdict(float)
    for c in comps:
        comp = c["item_code"]
        need = fg_qty * c["per_unit"]
        # If the component is itself produced (has a BOM), recurse so semi-
        # finished items expand to their raws.
        sub_comps = _get_active_bom_components(comp, bom_cache)
        if sub_comps is not None and comp not in seen:
            sub, _ = _explode(comp, need, filters, bom_cache, depth + 1, seen)
            # keep the semi-finished line too (it moves between companies as SF)
            out[comp] += need
            for k, v in sub.items():
                out[k] += v
        else:
            out[comp] += need
    return out, source


def _parse_supplier_stock(filters) -> Dict[str, float]:
    raw = filters.get("supplier_stock")
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return {str(k): flt(v) for k, v in data.items()}
    except Exception:
        frappe.throw(_("Supplier Stock must be valid JSON: {\"item_code\": qty, ...}"))


def _build_component_rows(filters, demand, supplier_stock, negative_only) -> List[Dict[str, Any]]:
    if not demand:
        return []
    items = list(demand.keys())
    consume, supply, first_consume, min_balance = _local_flows(filters, items)
    item_names = dict(
        frappe.get_all("Item", filters={"name": ["in", items]},
                       fields=["name", "item_name"], as_list=True, limit_page_length=0)
    )

    from frappe.utils import cint
    negative_only = True if negative_only in (None, "") else bool(cint(negative_only))

    rows = []
    for comp in sorted(demand, key=lambda x: -demand[x]):
        mn = flt(min_balance.get(comp, 0.0))
        # When negative_only, restrict to components whose stock actually went
        # negative somewhere during the window (true negative-stock episodes),
        # not merely components with a demand/supply gap.
        if negative_only and mn >= 0:
            continue
        dem = flt(demand[comp])
        cons = flt(consume.get(comp, 0.0))
        sup = flt(supply.get(comp, 0.0))
        gap = max(0.0, cons - sup)  # what local supply could not cover
        avail = flt(supplier_stock.get(comp, 0.0)) if supplier_stock else 0.0
        deliver_dn = min(gap, avail) if supplier_stock else 0.0
        unexplained = max(0.0, gap - avail) if supplier_stock else gap
        rows.append({
            "component": comp,
            "component_name": item_names.get(comp, ""),
            "bom_demand": round(dem, 2),
            "local_consumed": round(cons, 2),
            "local_supply": round(sup, 2),
            "min_balance": round(mn, 2),
            "gap": round(gap, 2),
            "bom_vs_actual_var": round(cons - dem, 2),
            "supplier_available": round(avail, 2),
            "deliver_via_dn": round(deliver_dn, 2),
            "unexplained": round(unexplained, 2),
            "first_consumption": first_consume.get(comp),
            "dn_must_predate": first_consume.get(comp),
        })
    return rows


def _local_flows(filters, items) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, Any], Dict[str, float]]:
    """Per-item: total inflow, total outflow (consumption), the first
    consumption date in the window (the DN-must-precede anchor), and the
    minimum running balance reached during the window (negative => the item
    had a real negative-stock episode). min balance uses qty_after_transaction
    (the true per-warehouse running balance, opening stock included)."""
    consume = defaultdict(float)
    supply = defaultdict(float)
    first_consume: Dict[str, Any] = {}
    min_balance: Dict[str, float] = {}
    # chunk the IN() to keep the query sane
    for i in range(0, len(items), 300):
        chunk = items[i:i + 300]
        placeholders = ", ".join(["%s"] * len(chunk))
        rows = frappe.db.sql(
            """
            SELECT item_code, posting_date, actual_qty, qty_after_transaction
            FROM `tabStock Ledger Entry`
            WHERE is_cancelled = 0
              AND company = %s
              AND posting_date BETWEEN %s AND %s
              AND item_code IN ({ph})
            ORDER BY posting_date ASC, creation ASC
            """.format(ph=placeholders),
            tuple([filters.company, filters.from_date, filters.to_date] + chunk),
            as_dict=True,
        )
        for r in rows:
            q = flt(r.actual_qty)
            if q > 0:
                supply[r.item_code] += q
            else:
                consume[r.item_code] += -q
                if r.item_code not in first_consume:
                    first_consume[r.item_code] = r.posting_date
            bal = flt(r.qty_after_transaction)
            if r.item_code not in min_balance or bal < min_balance[r.item_code]:
                min_balance[r.item_code] = bal
    return consume, supply, first_consume, min_balance


def _columns(has_supplier: bool) -> List[Dict[str, Any]]:
    cols = [
        {"label": _("Component"), "fieldname": "component", "fieldtype": "Link", "options": "Item", "width": 130},
        {"label": _("Name"), "fieldname": "component_name", "fieldtype": "Data", "width": 200},
        {"label": _("BOM Demand"), "fieldname": "bom_demand", "fieldtype": "Float", "width": 120},
        {"label": _("Local Consumed"), "fieldname": "local_consumed", "fieldtype": "Float", "width": 120},
        {"label": _("Local Supply"), "fieldname": "local_supply", "fieldtype": "Float", "width": 120},
        {"label": _("Min Balance (period)"), "fieldname": "min_balance", "fieldtype": "Float", "width": 130},
        {"label": _("Gap (need from supplier)"), "fieldname": "gap", "fieldtype": "Float", "width": 150},
        {"label": _("BOM vs Actual Var"), "fieldname": "bom_vs_actual_var", "fieldtype": "Float", "width": 130},
    ]
    if has_supplier:
        cols += [
            {"label": _("Supplier Available"), "fieldname": "supplier_available", "fieldtype": "Float", "width": 130},
            {"label": _("Deliver via DN"), "fieldname": "deliver_via_dn", "fieldtype": "Float", "width": 120},
            {"label": _("Unexplained"), "fieldname": "unexplained", "fieldtype": "Float", "width": 120},
        ]
    cols.append({"label": _("DN Must Pre-date"), "fieldname": "dn_must_predate", "fieldtype": "Date", "width": 130})
    return cols
