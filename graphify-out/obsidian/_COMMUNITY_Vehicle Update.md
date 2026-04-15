---
type: community
cohesion: 0.20
members: 16
---

# Vehicle Update

**Cohesion:** 0.20 - loosely connected
**Members:** 16 nodes

## Members
- [[Business Needed Solutions - Vehicle Update System  This module provides function]] - rationale - business_needed_solutions/update_vehicle.py
- [[Custom exception for vehicle update errors.]] - rationale - business_needed_solutions/update_vehicle.py
- [[Load the document to be updated.          Args         doctype (str) The docum]] - rationale - business_needed_solutions/update_vehicle.py
- [[Prepare the data to be updated.          Args         vehicle_no (Optionalstr]] - rationale - business_needed_solutions/update_vehicle.py
- [[Show a success message after successful update.          Args         doctype (]] - rationale - business_needed_solutions/update_vehicle.py
- [[Update the document with the provided data.          Args         doc The docu]] - rationale - business_needed_solutions/update_vehicle.py
- [[Update vehicle number and transporter details for a document.      This function]] - rationale - business_needed_solutions/update_vehicle.py
- [[Validate that the e-Waybill status allows updates.          Args         doc T]] - rationale - business_needed_solutions/update_vehicle.py
- [[VehicleUpdateError]] - code - business_needed_solutions/update_vehicle.py
- [[_load_document()]] - code - business_needed_solutions/update_vehicle.py
- [[_prepare_update_data()]] - code - business_needed_solutions/update_vehicle.py
- [[_show_success_message()]] - code - business_needed_solutions/update_vehicle.py
- [[_update_document()]] - code - business_needed_solutions/update_vehicle.py
- [[_validate_ewaybill_status()]] - code - business_needed_solutions/update_vehicle.py
- [[update_vehicle.py]] - code - business_needed_solutions/update_vehicle.py
- [[update_vehicle_or_transporter()]] - code - business_needed_solutions/update_vehicle.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Vehicle_Update
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Stock Update Validation]]

## Top bridge nodes
- [[VehicleUpdateError]] - degree 7, connects to 1 community