---
type: community
cohesion: 0.06
members: 45
---

# Submission & Stock Validation

**Cohesion:** 0.06 - loosely connected
**Members:** 45 nodes

## Members
- [[BNS Settings (single doctype holding restrict_submission)]] - code - business_needed_solutions/business_needed_solutions/doctype/bns_settings/bns_settings.py
- [[BNSInternalTransferError]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[Business Needed Solutions - Submission Restriction Test Suite  This module provi]] - rationale - business_needed_solutions/test_submission_restriction.py
- [[Business Needed Solutions - Vehicle Update System  This module provides function]] - rationale - business_needed_solutions/update_vehicle.py
- [[Custom exception for BNS internal transfer operations.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Custom exception for stock update validation errors.]] - rationale - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[Custom exception for submission restriction test errors.]] - rationale - business_needed_solutions/test_submission_restriction.py
- [[Custom exception for vehicle update errors.]] - rationale - business_needed_solutions/update_vehicle.py
- [[Exception]] - code
- [[Get BNS Settings document for testing.          Returns         The BNS Setting]] - rationale - business_needed_solutions/test_submission_restriction.py
- [[Load the document to be updated.          Args         doctype (str) The docum]] - rationale - business_needed_solutions/update_vehicle.py
- [[Prepare the data to be updated.          Args         vehicle_no (Optionalstr]] - rationale - business_needed_solutions/update_vehicle.py
- [[Show a success message after successful update.          Args         doctype (]] - rationale - business_needed_solutions/update_vehicle.py
- [[StockUpdateValidationError]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[SubmissionRestrictionTestError]] - code - business_needed_solutions/test_submission_restriction.py
- [[Test BNS Settings configuration for new unified system.          Returns]] - rationale - business_needed_solutions/test_submission_restriction.py
- [[Test categorization for a single document type.          Args         doctype (]] - rationale - business_needed_solutions/test_submission_restriction.py
- [[Test document categorization functionality.          Returns         bool True]] - rationale - business_needed_solutions/test_submission_restriction.py
- [[Test permission checking functionality.          Returns         bool True if]] - rationale - business_needed_solutions/test_submission_restriction.py
- [[Test script to verify the unified submission restriction system.          This f]] - rationale - business_needed_solutions/test_submission_restriction.py
- [[Test that old restriction fields have been cleaned up.          Returns]] - rationale - business_needed_solutions/test_submission_restriction.py
- [[Test that the new 'restrict_submission' setting exists.          Args         b]] - rationale - business_needed_solutions/test_submission_restriction.py
- [[Test that the new 'submission_restriction_override_roles' table exists.]] - rationale - business_needed_solutions/test_submission_restriction.py
- [[Update the document with the provided data.          Args         doc The docu]] - rationale - business_needed_solutions/update_vehicle.py
- [[Update vehicle number and transporter details for a document.          This func]] - rationale - business_needed_solutions/update_vehicle.py
- [[Validate that the e-Waybill status allows updates.          Args         doc T]] - rationale - business_needed_solutions/update_vehicle.py
- [[VehicleUpdateError]] - code - business_needed_solutions/update_vehicle.py
- [[_get_bns_settings()]] - code - business_needed_solutions/test_submission_restriction.py
- [[_load_document()]] - code - business_needed_solutions/update_vehicle.py
- [[_prepare_update_data()]] - code - business_needed_solutions/update_vehicle.py
- [[_show_success_message()]] - code - business_needed_solutions/update_vehicle.py
- [[_test_bns_settings_configuration()]] - code - business_needed_solutions/test_submission_restriction.py
- [[_test_document_categorization()]] - code - business_needed_solutions/test_submission_restriction.py
- [[_test_legacy_field_cleanup()]] - code - business_needed_solutions/test_submission_restriction.py
- [[_test_new_setting_exists()]] - code - business_needed_solutions/test_submission_restriction.py
- [[_test_new_table_exists()]] - code - business_needed_solutions/test_submission_restriction.py
- [[_test_permission_checking()]] - code - business_needed_solutions/test_submission_restriction.py
- [[_test_single_categorization()]] - code - business_needed_solutions/test_submission_restriction.py
- [[_update_document()]] - code - business_needed_solutions/update_vehicle.py
- [[_validate_ewaybill_status()]] - code - business_needed_solutions/update_vehicle.py
- [[submission_restriction overrides module]] - code - business_needed_solutions/business_needed_solutions/overrides/submission_restriction.py
- [[test_submission_restriction()]] - code - business_needed_solutions/test_submission_restriction.py
- [[test_submission_restriction.py]] - code - business_needed_solutions/test_submission_restriction.py
- [[update_vehicle.py]] - code - business_needed_solutions/update_vehicle.py
- [[update_vehicle_or_transporter()]] - code - business_needed_solutions/update_vehicle.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Submission_&_Stock_Validation
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Core Utils & Runtime Patches]]
- 1 edge to [[_COMMUNITY_Branch Accounting Settings]]
- 1 edge to [[_COMMUNITY_Submission Role Overrides]]
- 1 edge to [[_COMMUNITY_PR Return Linking & Internal Supplier]]
- 1 edge to [[_COMMUNITY_Stock Update Guard]]
- 1 edge to [[_COMMUNITY_Frappe Overrides & Integration]]

## Top bridge nodes
- [[Exception]] - degree 8, connects to 3 communities
- [[BNSInternalTransferError]] - degree 4, connects to 2 communities
- [[StockUpdateValidationError]] - degree 3, connects to 1 community
- [[submission_restriction overrides module]] - degree 3, connects to 1 community