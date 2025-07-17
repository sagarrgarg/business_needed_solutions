# BNS Settings Features

## Overview

BNS Settings provides several features to control and customize stock entry behavior in ERPNext. This document covers the available features and their configuration.

## Features

### 1. Warehouse Restriction Feature

The Warehouse Restriction feature allows administrators to prevent users from creating Stock Entries where the source and target warehouses are the same. This restriction applies to all Stock Entry types, including Material Transfer entries which normally allow same warehouse transfers.

### 2. Auto Transit for Material Transfer Feature

The Auto Transit feature automatically sets the "Add to Transit" checkbox to enabled for Material Transfer type Stock Entries. This is useful for companies that want to track all material transfers through transit warehouses by default.

### 3. Warehouse Filtering for Material Transfer Feature

When "Auto Set Transit for Material Transfer" is enabled, additional warehouse filtering rules are automatically applied to ensure proper transit workflow:

1. **New Material Transfer Entries** (without outgoing_stock_entry):
   - Source warehouse cannot be a transit warehouse
   - Target warehouse must be a transit warehouse

2. **Receipt from Transit Entries** (with outgoing_stock_entry):
   - Source warehouse must be a transit warehouse
   - Target warehouse must match the "For Which Warehouse to Transfer" field from the outgoing stock entry

## Configuration

### Enabling Warehouse Restriction

1. Navigate to **BNS Settings** in the Frappe Desk
2. Locate the **"Restrict Same Warehouse in Source and Target"** checkbox
3. Check the box to enable the restriction
4. Save the settings

### Enabling Auto Transit for Material Transfer

1. Navigate to **BNS Settings** in the Frappe Desk
2. Locate the **"Auto Set Transit for Material Transfer"** checkbox
3. Check the box to enable the feature
4. Save the settings

**Note**: When this feature is enabled, warehouse filtering rules are automatically applied to Material Transfer entries.

### Default Behavior

#### Warehouse Restriction
- **Disabled (Default)**: Users can create Stock Entries with the same warehouse in source and target
- **Enabled**: Users cannot create Stock Entries with the same warehouse in source and target

#### Auto Transit for Material Transfer
- **Disabled**: Users need to manually check the "Add to Transit" checkbox for Material Transfer entries, no warehouse filtering applied
- **Enabled (Default)**: The "Add to Transit" checkbox is automatically checked for new Material Transfer entries, warehouse filtering rules applied

#### Warehouse Filtering for Material Transfer
- **Disabled**: No warehouse type restrictions applied to Material Transfer entries
- **Enabled**: Warehouse filtering rules are enforced based on entry type (new transfer vs receipt from transit)

## How It Works

### Warehouse Restriction

When the restriction is enabled:

1. **Validation Trigger**: The validation runs during the `validate` event of Stock Entry documents
2. **Scope**: Applies to all Stock Entry types (Material Transfer, Material Issue, Material Receipt, etc.)
3. **Row-level Check**: Each item row is validated individually
4. **Error Message**: Clear error message indicating which row has the issue and that it's due to BNS Settings

### Auto Transit for Material Transfer

When the feature is enabled:

1. **Trigger**: Runs during the `validate` event of Stock Entry documents
2. **Scope**: Only applies to Material Transfer entries that are not outgoing stock entries
3. **Action**: Automatically sets `add_to_transit` to `1` for qualifying entries
4. **Conditions**: 
   - Stock Entry Type must be "Material Transfer"
   - Purpose must be "Material Transfer"
   - Outgoing Stock Entry must not be set (i.e., not a receipt from transit)

### Warehouse Filtering for Material Transfer

When the feature is enabled:

1. **Trigger**: Runs during the `validate` event of Stock Entry documents
2. **Scope**: Only applies to Material Transfer entries when auto_transit_material_transfer is enabled
3. **Rules for New Material Transfer Entries** (without outgoing_stock_entry):
   - Validates that source warehouse is not a transit warehouse
   - Validates that target warehouse is a transit warehouse
   - Applies validation to both header-level and item-level warehouses
4. **Rules for Receipt from Transit Entries** (with outgoing_stock_entry):
   - Validates that source warehouse is a transit warehouse
   - Validates that target warehouse matches the `custom_for_which_warehouse_to_transfer` from the outgoing stock entry
   - Auto-sets target warehouse if not specified
   - Applies validation to both header-level and item-level warehouses

## Error Messages

### Warehouse Restriction

When a user tries to create a Stock Entry with the same warehouse in source and target:

```
Row 1: Source and target warehouse cannot be same (Warehouse Name). 
This restriction is enabled in BNS Settings.
```

### Warehouse Filtering

When warehouse filtering rules are violated:

**For New Material Transfer Entries:**
```
Target warehouse 'Warehouse Name' must be a transit warehouse for new Material Transfer entries.
```

```
Source warehouse 'Warehouse Name' cannot be a transit warehouse for new Material Transfer entries.
```

**For Receipt from Transit Entries:**
```
Source warehouse 'Warehouse Name' must be a transit warehouse for receipt from transit entries.
```

```
Target warehouse must be 'Target Warehouse Name' as specified in the outgoing stock entry.
```

```
Outgoing Stock Entry STE-001 does not have 'For Which Warehouse to Transfer' set. 
Please set the target warehouse in the outgoing entry first.
```

## Use Cases

### Warehouse Restriction

This feature is useful for:

- **Inventory Control**: Preventing accidental transfers within the same warehouse
- **Audit Trail**: Ensuring all stock movements are properly tracked between different locations
- **Process Compliance**: Enforcing business rules that require physical movement between warehouses
- **Data Integrity**: Maintaining clean stock movement records

### Auto Transit for Material Transfer

This feature is useful for:

- **Transit Tracking**: Automatically tracking all material transfers through transit warehouses
- **Process Standardization**: Ensuring consistent handling of material transfers across the organization
- **Audit Compliance**: Meeting regulatory requirements for transit documentation
- **Operational Efficiency**: Reducing manual steps in material transfer processes

### Warehouse Filtering for Material Transfer

This feature is useful for:

- **Transit Workflow Enforcement**: Ensuring proper transit workflow (source → transit → destination)
- **Data Integrity**: Preventing incorrect warehouse selections in transit processes
- **Process Compliance**: Enforcing business rules for transit warehouse usage
- **Error Prevention**: Automatically setting correct target warehouses for receipt from transit entries

## Technical Implementation

### Warehouse Restriction
- **Hook**: Registered in `hooks.py` under `doc_events` for Stock Entry validation
- **Function**: `validate_warehouse_restriction()` in `warehouse_validation.py`
- **Setting**: `restrict_same_warehouse` field in BNS Settings
- **Scope**: All users (no role-based overrides)

### Auto Transit for Material Transfer
- **Hook**: Registered in `hooks.py` under `doc_events` for Stock Entry validation
- **Function**: `auto_set_transit_for_material_transfer()` in `auto_transit_validation.py`
- **Setting**: `auto_transit_material_transfer` field in BNS Settings
- **Scope**: All users (no role-based overrides)
- **Backend Implementation**: Moved from client script to server-side validation

### Warehouse Filtering for Material Transfer
- **Hook**: Registered in `hooks.py` under `doc_events` for Stock Entry validation
- **Function**: `validate_warehouse_filtering()` in `warehouse_filtering.py`
- **Setting**: `auto_transit_material_transfer` field in BNS Settings (same as Auto Transit)
- **Scope**: All users (no role-based overrides)
- **Dependencies**: Requires transit warehouses to be properly configured with `warehouse_type = "Transit"`

## Testing

The features include comprehensive tests covering:

### Warehouse Restriction
1. **Restriction Disabled**: Same warehouse transfers are allowed
2. **Restriction Enabled**: Same warehouse transfers are blocked
3. **Different Warehouses**: Transfers between different warehouses work normally

### Auto Transit for Material Transfer
1. **Feature Disabled**: "Add to Transit" checkbox is not automatically set
2. **Feature Enabled**: "Add to Transit" checkbox is automatically set for Material Transfer entries
3. **Non-Applicable Entries**: Feature does not affect non-Material Transfer entries
4. **Outgoing Stock Entries**: Feature does not affect outgoing stock entries (receipts from transit)

### Warehouse Filtering for Material Transfer
1. **Feature Disabled**: No warehouse type restrictions applied
2. **New Transfer Entries**: Source cannot be transit, target must be transit
3. **Receipt from Transit**: Source must be transit, target must match outgoing entry's custom field
4. **Error Handling**: Proper error messages for various validation failures

## Migration

The feature is automatically available after installation. No additional migration steps are required. 