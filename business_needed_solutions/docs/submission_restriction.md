# Unified Submission Restriction System

## Overview

The Business Needed Solutions app now features a unified submission restriction system that consolidates the previously separate stock, transaction, and order restriction features into a single, more maintainable solution.

## What Changed

### Before (Separate Systems)
- `restrict_stock_entry` - Controlled Stock Entry, Stock Reconciliation, etc.
- `restrict_transaction_entry` - Controlled Sales Invoice, Purchase Invoice, etc.
- `restrict_order_entry` - Controlled Sales Order, Purchase Order, etc.
- Separate override role tables for each restriction type
- Duplicate code across multiple files

### After (Unified System)
- `restrict_submission` - Single setting controlling all document submissions
- `submission_restriction_override_roles` - Single override role table
- Single validation function handling all document types
- Cleaner, more maintainable codebase

## Document Categories

The unified system automatically categorizes documents into three types:

### Stock Documents
- **Stock Entry**
- **Stock Reconciliation**
- **Sales Invoice** (when `update_stock` is enabled)
- **Purchase Invoice** (when `update_stock` is enabled)
- **Delivery Note**
- **Purchase Receipt**

### Transaction Documents
- **Sales Invoice** (when `update_stock` is disabled)
- **Purchase Invoice** (when `update_stock` is disabled)
- **Delivery Note**
- **Purchase Receipt**
- **Journal Entry**
- **Payment Entry**

### Order Documents
- **Sales Order**
- **Purchase Order**
- **Payment Request**

## Configuration

### Enabling Submission Restriction

1. Navigate to **BNS Settings** in the Frappe Desk
2. Locate the **"Restrict Document Submission"** checkbox
3. Check the box to enable the restriction
4. Save the settings

### Setting Override Roles

1. In **BNS Settings**, locate the **"Override Submission Restriction"** table
2. Add roles that should be exempt from submission restrictions
3. These roles will be able to submit documents even when restrictions are enabled
4. Save the settings

## How It Works

### Automatic Document Categorization

The system automatically determines which category a document belongs to based on its doctype and properties:

```python
# Example: Sales Invoice categorization
if doc.doctype == "Sales Invoice":
    if doc.update_stock:
        category = "stock"  # Affects inventory
    else:
        category = "transaction"  # Only financial transaction
```

### Permission Checking

1. **Check Restriction Status**: Verifies if `restrict_submission` is enabled
2. **Categorize Document**: Determines which category the document belongs to
3. **Check Override Roles**: Verifies if user has any override roles
4. **Apply Restriction**: Blocks submission if user lacks permission

### Error Messages

The system provides clear, contextual error messages:

- **Stock Documents**: "Submitting Stock Entry has been restricted. You may save as draft, but only authorized users can submit."
- **Transaction Documents**: "Submitting Sales Invoice has been restricted. You may save as draft, but only authorized users can submit."
- **Order Documents**: "Submitting Sales Order has been restricted. You may save as draft, but only authorized users can submit."

## Benefits of the Unified System

### 1. Simplified Configuration
- **Before**: 3 separate checkboxes and 3 separate role tables
- **After**: 1 checkbox and 1 role table

### 2. Reduced Code Duplication
- **Before**: 3 separate validation functions with similar logic
- **After**: 1 unified validation function

### 3. Better Maintainability
- Single point of configuration
- Easier to add new document types
- Consistent behavior across all restrictions

### 4. Improved User Experience
- Clearer settings interface
- Consistent error messages
- Single role management

### 5. Enhanced Flexibility
- Easy to extend to new document types
- Centralized permission logic
- Better debugging capabilities

## Technical Implementation

### Core Files

1. **`submission_restriction.py`**: Main validation logic
2. **`bns_settings.json`**: Updated settings configuration
3. **`hooks.py`**: Updated event registrations
4. **`migration.py`**: Migration script for existing installations

### Key Functions

#### `validate_submission_permission(doc, method)`
Main validation function that handles all document types.

#### `get_document_category(doctype)`
Determines which category a document type belongs to.

#### `has_override_permission(category)`
Checks if the current user has override permissions for a category.

### Document Categories Configuration

```python
DOCUMENT_CATEGORIES = {
    "stock": {
        "doctypes": ["Stock Entry", "Stock Reconciliation", ...],
        "setting_field": "restrict_submission",
        "override_field": "submission_restriction_override_roles",
        "error_message": _("Submitting {doctype} has been restricted...")
    },
    # ... other categories
}
```

## Migration from Old System

### Automatic Migration

The migration script automatically:

1. **Detects Old Settings**: Checks if any old restriction settings were enabled
2. **Enables New Setting**: Activates `restrict_submission` if any old settings were active
3. **Merges Override Roles**: Combines all override roles into the new unified table
4. **Cleans Up**: Removes old fields and settings

### Manual Migration (if needed)

If automatic migration fails:

1. **Enable New Setting**: Manually check `restrict_submission` in BNS Settings
2. **Migrate Roles**: Copy roles from old override tables to new unified table
3. **Test Functionality**: Verify that restrictions work as expected

## Adding New Document Types

To add a new document type to the restriction system:

1. **Update Categories**: Add the doctype to the appropriate category in `DOCUMENT_CATEGORIES`
2. **Register Hook**: Add the validation function to the document's `on_submit` event in `hooks.py`
3. **Test**: Verify the restriction works correctly

### Example: Adding a New Stock Document

```python
# In submission_restriction.py
DOCUMENT_CATEGORIES = {
    "stock": {
        "doctypes": [
            "Stock Entry",
            "Stock Reconciliation",
            "New Stock Document",  # Add here
            # ...
        ],
        # ...
    }
}
```

```python
# In hooks.py
doc_events = {
    "New Stock Document": {
        "on_submit": "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission"
    }
}
```

## Troubleshooting

### Common Issues

1. **Restriction Not Working**
   - Check if `restrict_submission` is enabled in BNS Settings
   - Verify the document type is included in the appropriate category
   - Check if user has override roles assigned

2. **Migration Issues**
   - Check error logs for migration errors
   - Manually verify settings after migration
   - Contact support if issues persist

3. **Performance Issues**
   - The unified system is more efficient than the old separate systems
   - If performance issues occur, check for other system bottlenecks

### Debug Mode

Enable debug logging to troubleshoot issues:

```python
# In submission_restriction.py
import frappe
frappe.logger().debug(f"Document category: {document_category}")
frappe.logger().debug(f"User roles: {user_roles}")
frappe.logger().debug(f"Override roles: {override_roles}")
```

## Best Practices

1. **Role Management**: Use specific roles for override permissions rather than broad roles
2. **Testing**: Test restrictions thoroughly before enabling in production
3. **Documentation**: Keep track of which roles have override permissions
4. **Monitoring**: Monitor restriction usage and adjust as needed

## Future Enhancements

The unified system provides a foundation for future enhancements:

1. **Time-based Restrictions**: Restrict submissions during specific time periods
2. **Amount-based Restrictions**: Restrict based on document amounts
3. **Conditional Restrictions**: Apply restrictions based on document properties
4. **Audit Trail**: Enhanced logging of restriction events

## Support

For issues or questions about the unified submission restriction system:

1. Check this documentation first
2. Review error logs for specific error messages
3. Contact the development team with detailed information about the issue 