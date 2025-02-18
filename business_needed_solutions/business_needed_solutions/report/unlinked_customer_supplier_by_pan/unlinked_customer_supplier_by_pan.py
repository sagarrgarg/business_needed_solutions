import frappe
from frappe import _
import urllib.parse

def execute(filters=None):
    columns = [
        {"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 150},
        {"label": _("Customer PAN"), "fieldname": "customer_pan", "fieldtype": "Data", "width": 120},
        {"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 150},
        {"label": _("Supplier PAN"), "fieldname": "supplier_pan", "fieldtype": "Data", "width": 120},
        {"label": _("Customer → Supplier"), "fieldname": "customer_to_supplier", "fieldtype": "HTML", "width": 150},
        {"label": _("Supplier → Customer"), "fieldname": "supplier_to_customer", "fieldtype": "HTML", "width": 150}
    ]

    data = []

    # Fetch Active Customers with PAN
    customers = frappe.db.get_list(
        "Customer",
        filters=[["pan", "!=", ""], ["disabled", "=", 0]],
        fields=["name", "pan"]
    )

    # Fetch Active Suppliers with PAN
    suppliers = frappe.db.get_list(
        "Supplier",
        filters=[["pan", "!=", ""], ["disabled", "=", 0]],
        fields=["name", "pan"]
    )

    # Create a Supplier lookup dictionary by PAN for quick matching
    supplier_dict = {s["pan"]: s["name"] for s in suppliers}

    for customer in customers:
        pan = customer["pan"]
        if pan in supplier_dict:
            supplier_name = supplier_dict[pan]

            # Check Party Link in Both Directions
            party_link = frappe.db.exists(
                "Party Link",
                {
                    "primary_party": customer["name"],
                    "secondary_party": supplier_name
                }
            ) or frappe.db.exists(
                "Party Link",
                {
                    "primary_party": supplier_name,
                    "secondary_party": customer["name"]
                }
            )

            if not party_link:
                # Separate Buttons for Each Direction
                customer_to_supplier_btn = (
                    f"<button class='btn btn-success' style='margin-right:5px;'"
                    f" onclick=\"createPartyLink('{customer['name']}', '{supplier_name}', 'Customer', 'Supplier')\">"
                    f"Create</button>"
                )

                supplier_to_customer_btn = (
                    f"<button class='btn btn-primary'"
                    f" onclick=\"createPartyLink('{supplier_name}', '{customer['name']}', 'Supplier', 'Customer')\">"
                    f"Create</button>"
                )

                data.append({
                    "customer": customer["name"],
                    "customer_pan": pan,
                    "supplier": supplier_name,
                    "supplier_pan": pan,
                    "customer_to_supplier": customer_to_supplier_btn,
                    "supplier_to_customer": supplier_to_customer_btn
                })

    return columns, data
