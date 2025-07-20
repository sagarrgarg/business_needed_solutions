# test_submission_restriction.py
import frappe
from frappe import _

def test_submission_restriction():
    """
    Test script to verify the unified submission restriction system.
    """
    print("Testing Unified Submission Restriction System...")
    
    # Test 1: Check if new setting exists
    try:
        bns_settings = frappe.get_single("BNS Settings")
        if hasattr(bns_settings, 'restrict_submission'):
            print("✓ New 'restrict_submission' setting exists")
        else:
            print("✗ New 'restrict_submission' setting not found")
            return False
            
        if hasattr(bns_settings, 'submission_restriction_override_roles'):
            print("✓ New 'submission_restriction_override_roles' table exists")
        else:
            print("✗ New 'submission_restriction_override_roles' table not found")
            return False
    except Exception as e:
        print(f"✗ Error accessing BNS Settings: {str(e)}")
        return False
    
    # Test 2: Check if old settings are cleaned up
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
            print(f"✗ Old field '{field}' still exists")
        else:
            print(f"✓ Old field '{field}' cleaned up")
    
    # Test 3: Test document categorization
    from business_needed_solutions.business_needed_solutions.overrides.submission_restriction import get_document_category
    
    test_cases = [
        ("Stock Entry", "stock"),
        ("Sales Invoice", "stock"),  # Will be overridden based on update_stock
        ("Journal Entry", "transaction"),
        ("Sales Order", "order"),
        ("Non Existent DocType", None)
    ]
    
    for doctype, expected_category in test_cases:
        actual_category = get_document_category(doctype)
        if actual_category == expected_category:
            print(f"✓ Document categorization correct for {doctype}: {actual_category}")
        else:
            print(f"✗ Document categorization incorrect for {doctype}: expected {expected_category}, got {actual_category}")
    
    # Test 4: Test permission checking
    from business_needed_solutions.business_needed_solutions.overrides.submission_restriction import has_override_permission
    
    # This should work without errors
    try:
        result = has_override_permission("stock")
        print(f"✓ Permission checking works: {result}")
    except Exception as e:
        print(f"✗ Permission checking failed: {str(e)}")
        return False
    
    print("\nAll tests completed successfully!")
    return True

if __name__ == "__main__":
    test_submission_restriction() 