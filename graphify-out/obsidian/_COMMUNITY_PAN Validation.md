---
type: community
cohesion: 0.20
members: 14
---

# PAN Validation

**Cohesion:** 0.20 - loosely connected
**Members:** 14 nodes

## Members
- [[Business Needed Solutions - PAN Validation System  This module provides validati]] - rationale - business_needed_solutions/business_needed_solutions/overrides/pan_validation.py
- [[Check if PAN uniqueness enforcement is enabled in BNS Settings.          Returns]] - rationale - business_needed_solutions/business_needed_solutions/overrides/pan_validation.py
- [[Check if the PAN number is unique across all customers and suppliers.          A]] - rationale - business_needed_solutions/business_needed_solutions/overrides/pan_validation.py
- [[Find existing document with the same PAN number.          Args         doctype]] - rationale - business_needed_solutions/business_needed_solutions/overrides/pan_validation.py
- [[Get the human-readable label for the doctype.          Args         doctype (st]] - rationale - business_needed_solutions/business_needed_solutions/overrides/pan_validation.py
- [[Raise a PAN uniqueness error with appropriate message.          Args         do]] - rationale - business_needed_solutions/business_needed_solutions/overrides/pan_validation.py
- [[Validate PAN uniqueness for both Customer and Supplier documents.          This]] - rationale - business_needed_solutions/business_needed_solutions/overrides/pan_validation.py
- [[_check_pan_uniqueness()]] - code - business_needed_solutions/business_needed_solutions/overrides/pan_validation.py
- [[_find_existing_pan_document()]] - code - business_needed_solutions/business_needed_solutions/overrides/pan_validation.py
- [[_get_doctype_label()]] - code - business_needed_solutions/business_needed_solutions/overrides/pan_validation.py
- [[_is_pan_uniqueness_enabled()]] - code - business_needed_solutions/business_needed_solutions/overrides/pan_validation.py
- [[_raise_pan_uniqueness_error()]] - code - business_needed_solutions/business_needed_solutions/overrides/pan_validation.py
- [[pan_validation.py]] - code - business_needed_solutions/business_needed_solutions/overrides/pan_validation.py
- [[validate_pan_uniqueness()]] - code - business_needed_solutions/business_needed_solutions/overrides/pan_validation.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/PAN_Validation
SORT file.name ASC
```
