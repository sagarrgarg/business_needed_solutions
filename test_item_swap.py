import frappe
from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

def test():
    # 1. Create a dummy item
    frappe.get_doc({
        "doctype": "Item",
        "item_code": "ITEM-TEST-OLD",
        "item_group": "Products",
        "is_stock_item": 1,
        "stock_uom": "Nos"
    }).insert(ignore_permissions=True, ignore_if_duplicate=True)
    
    frappe.get_doc({
        "doctype": "Item",
        "item_code": "ITEM-TEST-NEW",
        "item_group": "Products",
        "is_stock_item": 1,
        "stock_uom": "Nos"
    }).insert(ignore_permissions=True, ignore_if_duplicate=True)
    
    # 2. Create an SO for ITEM-TEST-OLD
    so = frappe.get_doc({
        "doctype": "Sales Order",
        "customer": frappe.db.get_value("Customer", None, "name") or "Test Customer",
        "items": [{
            "item_code": "ITEM-TEST-OLD",
            "qty": 10,
            "rate": 100,
            "delivery_date": frappe.utils.today()
        }]
    }).insert(ignore_permissions=True)
    so.submit()
    
    print(f"Created SO: {so.name}")
    
    # 3. Make DN
    dn = make_delivery_note(so.name)
    print(f"Mapped DN with item: {dn.items[0].item_code}")
    
    # 4. Change item code
    dn.items[0].item_code = "ITEM-TEST-NEW"
    try:
        dn.insert(ignore_permissions=True)
        print("DN saved successfully with new item code!")
        
        # Optionally try to submit, though it might fail due to stock
    except Exception as e:
        print(f"Failed to save DN: {e}")

test()
