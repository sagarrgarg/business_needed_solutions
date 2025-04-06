import frappe

def after_migrate():
    """Reapply BNS Settings after migration"""
    try:
        # Get the current BNS Settings
        bns_settings = frappe.get_single("BNS Settings")
        if bns_settings:
            # Reapply the settings
            bns_settings.apply_settings()
    except Exception as e:
        frappe.log_error(f"Error reapplying BNS Settings after migration: {str(e)}") 