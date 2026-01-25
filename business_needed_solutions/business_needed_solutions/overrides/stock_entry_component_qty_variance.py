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


class BNSStockEntry(StockEntry):
    """
    Extended Stock Entry class with BNS manufacturing controls.
    
    Features:
    - Component quantity variance tolerance (±%) instead of strict BOM matching
    - BOM enforcement for Manufacture purpose Stock Entries
    """
    
    def validate(self):
        """
        Extended validation with BNS manufacturing controls.
        """
        # Run standard ERPNext validations first
        super().validate()
        
        # BNS: Enforce BOM for Manufacture purpose
        self._validate_bom_for_manufacture()
    
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

        self._validate_bom_components_exact_match()

    def _validate_bom_components_exact_match(self):
        """
        Ensure Stock Entry components match the BOM exactly.

        - All BOM components must be present in Stock Entry.
        - No extra components outside the BOM are allowed.
        """
        expected_item_codes = self._get_expected_bom_item_codes()
        if not expected_item_codes:
            return

        component_rows = [
            row
            for row in self.items
            if row.s_warehouse and not row.is_finished_item and not row.is_scrap_item
        ]

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
    
    def validate_component_and_quantities(self):
        """
        Validate component quantities against BOM with variance tolerance.
        
        If BNS variance feature is disabled, falls back to ERPNext's strict validation.
        Otherwise, allows quantities within the configured ±% tolerance.
        """
        # Early exit conditions (same as ERPNext)
        if self.purpose not in ["Manufacture", "Material Transfer for Manufacture"]:
            return
        
        if not frappe.db.get_single_value("Manufacturing Settings", "validate_components_quantities_per_bom"):
            return
        
        if not self.fg_completed_qty:
            return
        
        # Check if BNS variance feature is enabled
        if not self._is_bns_variance_enabled():
            # Fall back to ERPNext's strict validation
            super().validate_component_and_quantities()
            return
        
        # BNS variance validation
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
    
    def _validate_with_variance_tolerance(self):
        """
        Validate component quantities with variance tolerance.
        
        Computes expected quantities from BOM (respecting multi-level setting),
        calculates allowed variance for each item, and validates actual
        quantities are within tolerance.
        """
        # Get expected raw materials from BOM
        raw_materials = self.get_bom_raw_materials(self.fg_completed_qty)
        
        # Build variance map from BOM items
        variance_map = self._build_variance_map()
        default_variance = self._get_default_variance()
        
        precision = frappe.get_precision("Stock Entry Detail", "qty")
        
        for item_code, details in raw_materials.items():
            matched_item = self.get_matched_items(item_code)
            
            if not matched_item:
                # Item missing from stock entry
                frappe.throw(
                    _("According to the BOM {0}, the Item '{1}' is missing in the stock entry.").format(
                        get_link_to_form("BOM", self.bom_no),
                        frappe.bold(item_code)
                    ),
                    title=_("Missing Item")
                )
                continue
            
            expected_qty = flt(details.get("qty"), precision)
            actual_qty = flt(matched_item.qty, precision)
            
            # Get variance for this item (per-item override or default)
            variance_pct = self._get_item_variance(item_code, variance_map, default_variance)
            
            # Calculate allowed absolute variance
            allowed_abs = flt(expected_qty * variance_pct / 100, precision)
            
            # Check if actual quantity is within tolerance
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
            variance = flt(item.get("bns_variance_qty"))
            
            # Only add if variance is explicitly set and not already in map
            if variance > 0 and item_code not in variance_map:
                variance_map[item_code] = variance
    
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
            variance = flt(item.get("bns_variance_qty"))
            child_bom = item.get("bom_no")
            
            # Collect variance for this item
            if variance > 0 and item_code not in variance_map:
                variance_map[item_code] = variance
            
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
