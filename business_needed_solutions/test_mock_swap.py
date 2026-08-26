import sys, os
frappe_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../apps/frappe"))
sys.path.insert(0, frappe_path)
import frappe
from business_needed_solutions.item_replacement import swap_items_in_mapped_doc

def test():
    frappe.init(site="dev-15.local")
    frappe.connect()
    
    try:
        old_item = "OLD-TEST"
        new_item = "NEW-TEST"
        
        # 1. Configure settings
        settings = frappe.get_doc("Item Replacement Settings")
        settings.enable_item_replacement = 1
        settings.set("replacements", [])
        settings.append("replacements", {
            "old_item": old_item,
            "new_item": new_item,
            "enabled": 1
        })
        settings.save(ignore_permissions=True)
        print("Configured Item Replacement Settings.")
        
        # 2. Mock a mapped doc
        class MockItem:
            def __init__(self, item_code, so_detail):
                self.item_code = item_code
                self.so_detail = so_detail
            def get(self, key):
                return getattr(self, key, None)
                
        class MockDoc:
            def __init__(self):
                self.items = [MockItem(old_item, "some-row-id")]
            def get(self, key):
                return self.items if key == "items" else None
                
        doc = MockDoc()
        
        print(f"Before swap: {doc.items[0].item_code}")
        swap_items_in_mapped_doc(doc, "so_detail")
        print(f"After swap: {doc.items[0].item_code}")
        
        if doc.items[0].item_code == new_item:
            print("SUCCESS: Items swapped correctly!")
        else:
            print("FAILED: Swap did not happen.")

    finally:
        frappe.db.rollback()
        frappe.destroy()

test()
