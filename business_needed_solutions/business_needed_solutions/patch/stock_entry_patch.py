import frappe
from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry

# safe replacement of get_bom_raw_materials
def patched_get_bom_raw_materials(self, qty):
    from erpnext.manufacturing.doctype.bom.bom import get_bom_items_as_dict
    from erpnext.manufacturing.doctype.work_order.work_order import get_used_alternative_items

    # item dict = { item_code: {qty, description, stock_uom} }
    item_dict = get_bom_items_as_dict(
        self.bom_no,
        self.company,
        qty=qty,
        fetch_exploded=self.use_multi_level_bom,
        fetch_qty_in_stock_uom=False,
    )

    used_alternative_items = get_used_alternative_items(
        subcontract_order_field=getattr(self.subcontract_data, "order_field", None),
        work_order=self.work_order,
    )

    for item in item_dict.values():
        # keep allow_alternative_item behaviour
        if item["allow_alternative_item"]:
            item["allow_alternative_item"] = frappe.db.get_value(
                "Work Order", self.work_order, "allow_alternative_item"
            )

        result = (
            frappe.get_value(
                "Work Order",
                self.work_order,
                ["skip_transfer", "from_wip_warehouse"],
            )
            if self.work_order
            else None
        )

        if result:
            skip_transfer, from_wip_warehouse = result
        else:
            skip_transfer, from_wip_warehouse = 0, None

        item.from_warehouse = (
            frappe.get_value(
                "Work Order Item",
                {"parent": self.work_order, "item_code": item.item_code},
                "source_warehouse",
            )
            if skip_transfer and not from_wip_warehouse
            else self.from_warehouse or item.source_warehouse or item.default_warehouse
        )

        if item.item_code in used_alternative_items:
            alt = used_alternative_items.get(item.item_code)
            item.item_code = alt.item_code
            item.item_name = alt.item_name
            item.stock_uom = alt.stock_uom
            item.uom = alt.uom
            item.conversion_factor = alt.conversion_factor
            item.description = alt.description

    return item_dict


def execute():
    # monkey patch StockEntry method
    StockEntry.get_bom_raw_materials = patched_get_bom_raw_materials
