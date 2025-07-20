# migration.py
import frappe
from frappe import _

def after_migrate():
    """
    Migration script to handle transition from separate restriction settings
    to unified submission restriction system.
    """
    migrate_restriction_settings()

def migrate_restriction_settings():
    """
    Migrate old restriction settings to new unified submission restriction.
    
    This function:
    1. Checks if any of the old restriction settings are enabled
    2. Enables the new unified restriction if any old ones were enabled
    3. Merges override roles from all old settings into the new unified setting
    4. Cleans up old settings after migration
    """
    try:
        # Get current BNS Settings
        bns_settings = frappe.get_single("BNS Settings")
        
        # Check if any old restriction settings are enabled
        old_settings_enabled = any([
            bns_settings.get("restrict_stock_entry", 0),
            bns_settings.get("restrict_transaction_entry", 0),
            bns_settings.get("restrict_order_entry", 0)
        ])
        
        # If any old settings were enabled, enable the new unified setting
        if old_settings_enabled:
            bns_settings.restrict_submission = 1
            frappe.msgprint(_("Migration: Unified submission restriction enabled based on previous settings."))
        
        # Migrate override roles
        migrate_override_roles(bns_settings)
        
        # Clean up old fields
        cleanup_old_fields(bns_settings)
        
        # Save the updated settings
        bns_settings.save()
        
        frappe.msgprint(_("Migration: Restriction settings successfully migrated to unified system."))
        
    except Exception as e:
        frappe.log_error(f"Error during restriction settings migration: {str(e)}", "BNS Migration Error")
        frappe.msgprint(_("Migration: Error occurred during settings migration. Please check error logs."))

def migrate_override_roles(bns_settings):
    """
    Migrate override roles from old settings to new unified setting.
    """
    # Get all override roles from old settings
    all_override_roles = set()
    
    # Stock restriction override roles
    if hasattr(bns_settings, 'stock_restriction_override_roles'):
        for role_entry in bns_settings.get('stock_restriction_override_roles', []):
            if role_entry.role:
                all_override_roles.add(role_entry.role)
    
    # Transaction restriction override roles
    if hasattr(bns_settings, 'transaction_restriction_override_roles'):
        for role_entry in bns_settings.get('transaction_restriction_override_roles', []):
            if role_entry.role:
                all_override_roles.add(role_entry.role)
    
    # Order restriction override roles
    if hasattr(bns_settings, 'order_restriction_override_roles'):
        for role_entry in bns_settings.get('order_restriction_override_roles', []):
            if role_entry.role:
                all_override_roles.add(role_entry.role)
    
    # Clear existing unified override roles
    if hasattr(bns_settings, 'submission_restriction_override_roles'):
        bns_settings.submission_restriction_override_roles = []
    
    # Add all unique roles to the new unified setting
    for role in all_override_roles:
        bns_settings.append('submission_restriction_override_roles', {
            'role': role
        })
    
    if all_override_roles:
        frappe.msgprint(_("Migration: {0} override roles migrated to unified system.").format(len(all_override_roles)))

def cleanup_old_fields(bns_settings):
    """
    Clean up old restriction fields from BNS Settings.
    """
    old_fields = [
        'restrict_stock_entry',
        'stock_restriction_override_roles',
        'restrict_transaction_entry', 
        'transaction_restriction_override_roles',
        'restrict_order_entry',
        'order_restriction_override_roles'
    ]
    
    for field in old_fields:
        if hasattr(bns_settings, field):
            delattr(bns_settings, field)
    
    frappe.msgprint(_("Migration: Old restriction fields cleaned up.")) 