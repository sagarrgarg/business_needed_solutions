"""
Business Needed Solutions - Stock Entry Component Quantity Variance

This module provides tolerance-based validation for BOM component quantities
in Stock Entry, replacing ERPNext's strict equality check with a ±% variance system.

Supports both single-level and multi-level BOMs.
"""

import frappe
from frappe import _
from frappe.utils import flt, cint, get_link_to_form
from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry

from business_needed_solutions.business_needed_solutions.overrides import stock_value_conservation as svc


class BNSStockEntry(StockEntry):
    """
    Extended Stock Entry class with BNS manufacturing controls.
    
    Features:
    - Component quantity variance tolerance (±%) instead of strict BOM matching
    - BOM enforcement for Manufacture purpose Stock Entries
    - Stock value conservation on Repack / Manufacture: one plug line takes the balance
      (logic in overrides/stock_value_conservation.py; off unless configured in BNS Settings)
    """
    
    def validate(self):
        """
        Extended validation with BNS manufacturing controls.
        """
        # Run standard ERPNext validations first
        super().validate()
        
        # BNS: Enforce BOM for Manufacture purpose
        self._validate_bom_for_manufacture()

        # BNS: at submit, stamp whether value conservation governs this entry and the submit-time
        # rate of every incoming line (the basis for a non-compounding rescale on repost)
        svc.record_submit_snapshot(self)
    
    # ─── Stock value conservation ─────────────────────────────────────────────
    # Each override falls back to ERPNext unchanged unless svc.governs(self): conservation switched
    # on, an active rule for this company covering this posting date, and a configured purpose.

    def validate_repack_entry(self):
        """Replace ERPNext's 'type every finished good' rule with 'exactly one untyped plug line'."""
        if svc.governs(self):
            svc.prepare_conserved_entry(self)
            return
        super().validate_repack_entry()

    def set_basic_rate(self, reset_outgoing_rate=True, raise_error_if_no_rate=True):
        """
        Price the plug from the outgoing side after ERPNext has priced everything else.

        Also runs during Repost Item Valuation (recalculate_amounts_in_stock_entry reloads this
        class with reset_outgoing_rate=False), which is how a backdated voucher reprices the plug.
        """
        if not svc.governs(self):
            return super().set_basic_rate(reset_outgoing_rate, raise_error_if_no_rate)

        plug = svc.get_plug_row(self)
        # Keep ERPNext's pass away from the plug: for a multi-output Repack it would otherwise price
        # the plug from the item's current valuation, which throws for a grade with no history yet.
        # Restored in finally, because a repost db_updates every row and would persist a leaked flag.
        if plug is not None:
            plug.set_basic_rate_manually = 1
        try:
            super().set_basic_rate(reset_outgoing_rate, raise_error_if_no_rate)
        finally:
            if plug is not None:
                plug.set_basic_rate_manually = 0

        if reset_outgoing_rate:
            svc.apply_plug_rate(self, plug, in_recalculation=False)
            return

        # reset_outgoing_rate=False is ERPNext re-pricing a submitted entry from its ledger: Repost
        # Item Valuation, or the submit-time Serial and Batch Bundle recalculation. An exception
        # here rolls a repost back and marks it Failed permanently, so a defect in our code must
        # never escape — log it and leave ERPNext's figures in place.
        try:
            svc.apply_plug_rate(self, plug, in_recalculation=True)
        except Exception:
            frappe.log_error(
                title=f"BNS stock value conservation: recalculation failed {self.name}",
                reference_doctype="Stock Entry",
                reference_name=self.name,
            )

    def distribute_additional_costs(self):
        """Under conservation all additional cost lands on the plug; typed lines keep their rate."""
        super().distribute_additional_costs()
        if svc.governs(self):
            plug = svc.get_plug_row(self)
            if plug is not None:
                svc.put_additional_costs_on_plug(self, plug)

    def get_finished_item_row(self):
        """
        The row whose ledger entry ERPNext re-rates when an outgoing line is repriced.

        ERPNext picks the LAST finished good, and on Manufacture that is the only incoming row a
        repost re-rates. Returning the plug makes the outgoing rows point at it, so a backdated
        voucher moves the plug's ledger entry and not some other line's.
        """
        if svc.governs(self):
            plug = svc.get_plug_row(self)
            if plug is not None:
                return plug
        return super().get_finished_item_row()

    def _validate_bom_for_manufacture(self):
        """
        Validate that BOM is provided when Stock Entry purpose is Manufacture.
        
        Only enforced when 'Enforce BOM for Manufacture Stock Entry' is enabled
        in BNS Settings.
        """
        if self.purpose != "Manufacture":
            return
        
        if not cint(frappe.db.get_single_value("BNS Settings", "enforce_bom_for_manufacture", cache=True)):
            return
        
        if not self.bom_no:
            frappe.throw(
                _("BOM is mandatory for Stock Entry with purpose 'Manufacture'. "
                  "Please select a valid BOM before proceeding."),
                title=_("BOM Required")
            )
            return

        if not cint(self.from_bom):
            frappe.throw(
                _("'From BOM' must be checked when BOM is enforced for Manufacture. "
                  "Please check 'From BOM' to ensure items are sourced from the BOM."),
                title=_("From BOM Required")
            )
            return

        self._validate_bom_components_exact_match()

    def _validate_bom_components_exact_match(self):
        """
        Ensure Stock Entry components match the BOM exactly.

        - All BOM components must be present in Stock Entry.
        - No extra components outside the BOM are allowed.

        Batch/Serial safety: Uses set-based item_code matching, so the
        same item_code appearing in multiple rows (e.g. different batches
        via Serial and Batch Bundle) is correctly deduplicated.  BOM
        quantities are per-item_code regardless of batch.

        FG-only carve-out: a Manufacture entry with zero raw component
        rows is allowed only when it belongs to a Work Order AND that
        Work Order already has a submitted ``Material Consumption for
        Manufacture`` entry — i.e. raw was consumed in a paired
        consumption entry (WarehouseSuite continuous-manufacturing).
        Without the paired consumption entry the BOM-completeness check
        still fires below, so a stray empty Manufacture entry cannot
        slip through.
        """
        expected_item_codes = self._get_expected_bom_item_codes()
        if not expected_item_codes:
            return

        component_rows = [
            row
            for row in self.items
            if row.s_warehouse and not row.is_finished_item and not row.is_scrap_item
        ]

        if not component_rows and self._has_paired_consumption_entry():
            return

        present_item_codes = set()
        for row in component_rows:
            item_code = row.original_item or row.item_code
            if item_code:
                present_item_codes.add(item_code)

        extra_item_codes = sorted(code for code in present_item_codes if code not in expected_item_codes)
        if extra_item_codes:
            extra_items = ", ".join(frappe.bold(code) for code in extra_item_codes)
            frappe.throw(
                _(
                    "Only BOM components are allowed in the Stock Entry. "
                    "The following items are not part of BOM {0}: {1}"
                ).format(get_link_to_form("BOM", self.bom_no), extra_items),
                title=_("Invalid BOM Components"),
            )

        missing_item_codes = sorted(code for code in expected_item_codes if code not in present_item_codes)
        if missing_item_codes:
            missing_items = ", ".join(frappe.bold(code) for code in missing_item_codes)
            frappe.throw(
                _(
                    "The following BOM components are missing in the Stock Entry: {0}. "
                    "BOM: {1}"
                ).format(missing_items, get_link_to_form("BOM", self.bom_no)),
                title=_("Missing BOM Components"),
            )

    def _get_expected_bom_item_codes(self):
        """
        Get expected BOM component item codes for component matching.

        Returns:
            set: Expected BOM component item codes
        """
        if not self.bom_no:
            return set()

        fg_qty = self.fg_completed_qty or 1
        raw_materials = self.get_bom_raw_materials(fg_qty)
        return set(raw_materials.keys())

    def _has_paired_consumption_entry(self):
        """
        True iff this entry is linked to a Work Order AND at least one
        submitted ``Material Consumption for Manufacture`` Stock Entry
        already exists against that same Work Order.

        Excludes ``self.name`` so re-validation of an in-flight document
        doesn't match itself (defensive — this method is called from a
        Manufacture-purpose entry, not an MCM, so collision is unlikely
        but cheap to guard).
        """
        if not self.work_order:
            return False
        return bool(
            frappe.db.exists(
                "Stock Entry",
                {
                    "work_order": self.work_order,
                    "purpose": "Material Consumption for Manufacture",
                    "docstatus": 1,
                    "name": ("!=", self.name or ""),
                },
            )
        )
    
    def validate_component_and_quantities(self):
        """
        Validate component quantities against BOM with variance tolerance.

        If BNS variance feature is disabled, falls back to ERPNext's strict validation.
        Otherwise, allows quantities within the configured +/- % tolerance.
        """
        if self.purpose not in ["Manufacture", "Material Transfer for Manufacture"]:
            return

        if not self.fg_completed_qty:
            return

        if not self._is_bns_variance_enabled():
            super().validate_component_and_quantities()
            return

        self._validate_with_variance_tolerance()
    
    def _is_bns_variance_enabled(self):
        """
        Check if BNS variance feature is enabled in BNS Settings.
        
        Returns:
            bool: True if feature is enabled, False otherwise
        """
        return cint(
            frappe.db.get_single_value("BNS Settings", "enable_bns_variance_qty", cache=True)
        )
    
    def _get_default_variance(self):
        """
        Get default variance percentage from BNS Settings.
        
        Returns:
            float: Default variance percentage
        """
        return flt(
            frappe.db.get_single_value("BNS Settings", "bns_default_variance_qty", cache=True)
        )
    
    def _get_aggregated_qty(self, item_code):
        """Sum qty across all Stock Entry rows matching the item_code."""
        total = 0
        found = False
        for row in self.items:
            if row.item_code == item_code or row.original_item == item_code:
                if row.s_warehouse and not row.is_finished_item and not row.is_scrap_item:
                    total += flt(row.qty)
                    found = True
        return total if found else None

    def _validate_with_variance_tolerance(self):
        """
        Validate component quantities with variance tolerance.

        Aggregates qty across all rows of the same item_code (handles
        batch-tracked items split into multiple rows) before comparing
        against the BOM expected qty.
        """
        raw_materials = self.get_bom_raw_materials(self.fg_completed_qty)

        variance_map = self._build_variance_map()
        default_variance = self._get_default_variance()

        precision = frappe.get_precision("Stock Entry Detail", "qty")

        for item_code, details in raw_materials.items():
            actual_qty_raw = self._get_aggregated_qty(item_code)

            if actual_qty_raw is None:
                frappe.throw(
                    _("According to the BOM {0}, the Item '{1}' is missing in the stock entry.").format(
                        get_link_to_form("BOM", self.bom_no),
                        frappe.bold(item_code)
                    ),
                    title=_("Missing Item")
                )
                continue

            expected_qty = flt(details.get("qty"), precision)
            actual_qty = flt(actual_qty_raw, precision)

            variance_pct = self._get_item_variance(item_code, variance_map, default_variance)

            allowed_abs = flt(expected_qty * variance_pct / 100, precision)

            lower_bound = flt(expected_qty - allowed_abs, precision)
            upper_bound = flt(expected_qty + allowed_abs, precision)

            if actual_qty < lower_bound or actual_qty > upper_bound:
                frappe.throw(
                    _("For the item {0}, the quantity {1} is outside the allowed variance range.<br><br>"
                      "Expected: {2}<br>"
                      "Allowed Range: {3} to {4} (±{5}%)<br>"
                      "BOM: {6}").format(
                        frappe.bold(item_code),
                        frappe.bold(actual_qty),
                        frappe.bold(expected_qty),
                        frappe.bold(lower_bound),
                        frappe.bold(upper_bound),
                        frappe.bold(variance_pct),
                        get_link_to_form("BOM", self.bom_no)
                    ),
                    title=_("Quantity Outside Variance Tolerance")
                )
    
    def _build_variance_map(self):
        """
        Build a map of item_code -> variance_pct from BOM items.
        
        For multi-level BOMs, traverses the BOM tree and collects variance
        values from all BOM Item rows. If an item appears in multiple BOMs
        with different variance values, uses the first non-zero value found.
        
        Returns:
            dict: Map of item_code -> variance_pct (only for items with explicit variance)
        """
        variance_map = {}
        
        if not self.bom_no:
            return variance_map
        
        if self.use_multi_level_bom:
            # Traverse BOM tree for multi-level BOM
            self._collect_variance_from_bom_tree(self.bom_no, variance_map)
        else:
            # Single-level: just get from current BOM
            self._collect_variance_from_bom(self.bom_no, variance_map)
        
        return variance_map
    
    def _collect_variance_from_bom(self, bom_no, variance_map):
        """
        Collect variance values from a single BOM's items.

        Args:
            bom_no (str): BOM name
            variance_map (dict): Map to populate with item_code -> variance_pct
        """
        bom_items = frappe.get_all(
            "BOM Item",
            filters={"parent": bom_no, "parenttype": "BOM"},
            fields=["item_code", "bns_variance_qty"]
        )

        for item in bom_items:
            item_code = item.get("item_code")
            raw_variance = item.get("bns_variance_qty")

            # Distinguish "not set" (None/empty) from "explicitly 0%"
            if raw_variance is not None and raw_variance != "" and item_code not in variance_map:
                variance_map[item_code] = flt(raw_variance)
    
    def _collect_variance_from_bom_tree(self, bom_no, variance_map, visited=None):
        """
        Recursively collect variance values from BOM tree.
        
        Args:
            bom_no (str): BOM name to start from
            variance_map (dict): Map to populate with item_code -> variance_pct
            visited (set): Set of already-visited BOM names to prevent infinite loops
        """
        if visited is None:
            visited = set()
        
        if bom_no in visited:
            return
        
        visited.add(bom_no)
        
        # Get items from this BOM
        bom_items = frappe.get_all(
            "BOM Item",
            filters={"parent": bom_no, "parenttype": "BOM"},
            fields=["item_code", "bom_no", "bns_variance_qty"]
        )
        
        for item in bom_items:
            item_code = item.get("item_code")
            raw_variance = item.get("bns_variance_qty")
            child_bom = item.get("bom_no")

            if raw_variance is not None and raw_variance != "" and item_code not in variance_map:
                variance_map[item_code] = flt(raw_variance)
            
            # Recurse into child BOM if exists
            if child_bom:
                self._collect_variance_from_bom_tree(child_bom, variance_map, visited)
    
    def _get_item_variance(self, item_code, variance_map, default_variance):
        """
        Get variance percentage for an item.
        
        Uses per-item override if available, otherwise falls back to default.
        
        Args:
            item_code (str): Item code
            variance_map (dict): Map of item_code -> variance_pct
            default_variance (float): Default variance from BNS Settings
            
        Returns:
            float: Variance percentage to use
        """
        if item_code in variance_map:
            return variance_map[item_code]
        
        return default_variance
