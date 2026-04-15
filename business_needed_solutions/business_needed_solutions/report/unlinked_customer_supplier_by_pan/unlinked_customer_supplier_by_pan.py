import frappe
from frappe import _
from frappe.utils import escape_html
import urllib.parse

def execute(filters=None):
    columns = [
        {"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 150},
        {"label": _("Customer Name"), "fieldname": "customer_name", "fieldtype": "Data", "width": 150},
        {"label": _("Customer PAN"), "fieldname": "customer_pan", "fieldtype": "Data", "width": 120},
        {"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 150},
        # {"label": _("Supplier Name"), "fieldname": "supplier_name", "fieldtype": "Data", "width": 150},
        {"label": _("Supplier PAN"), "fieldname": "supplier_pan", "fieldtype": "Data", "width": 120},
        {"label": _("Customer → Supplier"), "fieldname": "customer_to_supplier", "fieldtype": "HTML", "width": 150},
        {"label": _("Supplier → Customer"), "fieldname": "supplier_to_customer", "fieldtype": "HTML", "width": 150}
    ]

    data = []

    # Fetch Active Customers with PAN
    customers = frappe.db.get_list(
        "Customer",
        filters=[["pan", "!=", ""], ["disabled", "=", 0]],
        fields=["name", "pan","customer_name"]
    )

    # Fetch Active Suppliers with PAN
    suppliers = frappe.db.get_list(
        "Supplier",
        filters=[["pan", "!=", ""], ["disabled", "=", 0]],
        fields=["name", "pan","supplier_name"]
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
                esc_cust = escape_html(customer['name'])
                esc_supp = escape_html(supplier_name)

                customer_to_supplier_btn = (
                    f'<button class="btn btn-success" style="margin-right:5px;"'
                    f' data-primary="{esc_cust}" data-secondary="{esc_supp}"'
                    f' data-primary-type="Customer" data-secondary-type="Supplier"'
                    f' onclick="createPartyLink(this.dataset.primary, this.dataset.secondary,'
                    f' this.dataset.primaryType, this.dataset.secondaryType)">'
                    f'Create</button>'
                )

                supplier_to_customer_btn = (
                    f'<button class="btn btn-primary"'
                    f' data-primary="{esc_supp}" data-secondary="{esc_cust}"'
                    f' data-primary-type="Supplier" data-secondary-type="Customer"'
                    f' onclick="createPartyLink(this.dataset.primary, this.dataset.secondary,'
                    f' this.dataset.primaryType, this.dataset.secondaryType)">'
                    f'Create</button>'
                )

                data.append({
                    "customer": customer["name"],
                    "customer_name":customer["customer_name"],
                    "customer_pan": pan,
                    "supplier": supplier_name,
                    "supplier_pan": pan,
                    "customer_to_supplier": customer_to_supplier_btn,
                    "supplier_to_customer": supplier_to_customer_btn
                })

    return columns, data
