"""
Business Needed Solutions - Submission Restriction Test Suite

This module provides comprehensive testing for the unified submission restriction system,
including validation of settings, document categorization, and permission checking.
"""

import frappe
from frappe import _
from typing import List, Tuple, Optional
import logging

# Configure logging
logger = logging.getLogger(__name__)


class SubmissionRestrictionTestError(Exception):
    """Custom exception for submission restriction test errors."""
    pass


def test_submission_restriction() -> bool:
    """
    Test script to verify the unified submission restriction system.
    
    This function runs a comprehensive test suite to validate:
    1. BNS Settings configuration
    2. Document categorization
    3. Permission checking
    4. Legacy field cleanup
    
    Returns:
        bool: True if all tests pass, False otherwise
    """
    try:
        logger.info("Starting Unified Submission Restriction System tests...")
        
        # Run all test cases
        test_results = [
            _test_bns_settings_configuration(),
            _test_document_categorization(),
            _test_permission_checking(),
            _test_legacy_field_cleanup()
        ]
        
        # Check if all tests passed
        all_passed = all(test_results)
        
        if all_passed:
            logger.info("All tests completed successfully!")
            print("\nAll tests completed successfully!")
        else:
            logger.error("Some tests failed!")
            print("\nSome tests failed!")
            
        return all_passed
        
    except Exception as e:
        logger.error(f"Error during test execution: {str(e)}")
        print(f"✗ Error during test execution: {str(e)}")
        return False


def _test_bns_settings_configuration() -> bool:
    """
    Test BNS Settings configuration for new unified system.
    
    Returns:
        bool: True if test passes, False otherwise
    """
    try:
        print("Testing BNS Settings Configuration...")
        
        # Get BNS Settings
        bns_settings = _get_bns_settings()
        
        # Test new setting existence
        if not _test_new_setting_exists(bns_settings):
            return False
            
        # Test new table existence
        if not _test_new_table_exists(bns_settings):
            return False
            
        print("✓ BNS Settings configuration test passed")
        return True
        
    except Exception as e:
        logger.error(f"Error in BNS Settings configuration test: {str(e)}")
        print(f"✗ BNS Settings configuration test failed: {str(e)}")
        return False


def _test_document_categorization() -> bool:
    """
    Test document categorization functionality.
    
    Returns:
        bool: True if test passes, False otherwise
    """
    try:
        print("Testing Document Categorization...")
        
        from business_needed_solutions.business_needed_solutions.overrides.submission_restriction import get_document_category
        
        # Define test cases
        test_cases = [
            ("Stock Entry", "stock"),
            ("Sales Invoice", "stock"),  # Will be overridden based on update_stock
            ("Journal Entry", "transaction"),
            ("Sales Order", "order"),
            ("Non Existent DocType", None)
        ]
        
        # Run test cases
        for doctype, expected_category in test_cases:
            if not _test_single_categorization(doctype, expected_category, get_document_category):
                return False
        
        print("✓ Document categorization test passed")
        return True
        
    except Exception as e:
        logger.error(f"Error in document categorization test: {str(e)}")
        print(f"✗ Document categorization test failed: {str(e)}")
        return False


def _test_permission_checking() -> bool:
    """
    Test permission checking functionality.
    
    Returns:
        bool: True if test passes, False otherwise
    """
    try:
        print("Testing Permission Checking...")
        
        from business_needed_solutions.business_needed_solutions.overrides.submission_restriction import has_override_permission
        
        # Test permission checking without errors
        result = has_override_permission("stock")
        print(f"✓ Permission checking works: {result}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error in permission checking test: {str(e)}")
        print(f"✗ Permission checking test failed: {str(e)}")
        return False


def _test_legacy_field_cleanup() -> bool:
    """
    Test that old restriction fields have been cleaned up.
    
    Returns:
        bool: True if test passes, False otherwise
    """
    try:
        print("Testing Legacy Field Cleanup...")
        
        bns_settings = _get_bns_settings()
        
        # Define old fields that should be cleaned up
        old_fields = [
            'restrict_stock_entry',
            'stock_restriction_override_roles',
            'restrict_transaction_entry',
            'transaction_restriction_override_roles',
            'restrict_order_entry',
            'order_restriction_override_roles'
        ]
        
        # Check each field
        for field in old_fields:
            if hasattr(bns_settings, field):
                print(f"✗ Old field '{field}' still exists")
                return False
            else:
                print(f"✓ Old field '{field}' cleaned up")
        
        print("✓ Legacy field cleanup test passed")
        return True
        
    except Exception as e:
        logger.error(f"Error in legacy field cleanup test: {str(e)}")
        print(f"✗ Legacy field cleanup test failed: {str(e)}")
        return False


def _get_bns_settings():
    """
    Get BNS Settings document for testing.
    
    Returns:
        The BNS Settings document
        
    Raises:
        SubmissionRestrictionTestError: If BNS Settings cannot be loaded
    """
    try:
        return frappe.get_single("BNS Settings")
    except Exception as e:
        raise SubmissionRestrictionTestError(f"Could not load BNS Settings: {str(e)}")


def _test_new_setting_exists(bns_settings) -> bool:
    """
    Test that the new 'restrict_submission' setting exists.
    
    Args:
        bns_settings: The BNS Settings document
        
    Returns:
        bool: True if setting exists, False otherwise
    """
    if hasattr(bns_settings, 'restrict_submission'):
        print("✓ New 'restrict_submission' setting exists")
        return True
    else:
        print("✗ New 'restrict_submission' setting not found")
        return False


def _test_new_table_exists(bns_settings) -> bool:
    """
    Test that the new 'submission_restriction_override_roles' table exists.
    
    Args:
        bns_settings: The BNS Settings document
        
    Returns:
        bool: True if table exists, False otherwise
    """
    if hasattr(bns_settings, 'submission_restriction_override_roles'):
        print("✓ New 'submission_restriction_override_roles' table exists")
        return True
    else:
        print("✗ New 'submission_restriction_override_roles' table not found")
        return False


def _test_single_categorization(
    doctype: str, 
    expected_category: Optional[str], 
    categorization_function
) -> bool:
    """
    Test categorization for a single document type.
    
    Args:
        doctype (str): The document type to test
        expected_category (Optional[str]): The expected category
        categorization_function: The function to test
        
    Returns:
        bool: True if categorization is correct, False otherwise
    """
    actual_category = categorization_function(doctype)
    
    if actual_category == expected_category:
        print(f"✓ Document categorization correct for {doctype}: {actual_category}")
        return True
    else:
        print(f"✗ Document categorization incorrect for {doctype}: expected {expected_category}, got {actual_category}")
        return False


if __name__ == "__main__":
    test_submission_restriction() 