"""
Override for Frappe's CustomizeForm to fix a TimestampMismatchError bug
in Frappe v15.

Root Cause:
    `save_customization()` internally calls `set_property_setters_for_actions_and_links()`
    which saves custom DocType Link / Action / State records via `d.save()`.
    Frappe's `check_if_latest()` compares the browser-sent `modified` timestamp
    against the live DB timestamp. Within the same HTTP request, earlier DB writes
    (in `set_property_setters()`) advance the DB timestamp, making the browser's
    timestamp stale by a few milliseconds — causing a false-positive
    TimestampMismatchError and blocking the save entirely.

Fix:
    Before calling `d.save()`, re-fetch the latest `modified` timestamp from the
    database and assign it to the document object. This ensures `check_if_latest()`
    compares identical timestamps and does not raise an error.
"""

import frappe
from frappe.custom.doctype.customize_form.customize_form import CustomizeForm


doctype_link_properties = {
    "group": "Data",
    "hidden": "Check",
    "custom": "Check",
}
doctype_action_properties = {
    "group": "Data",
    "hidden": "Check",
    "custom": "Check",
}
doctype_state_properties = {
    "title": "Data",
    "color": "Data",
    "custom": "Check",
}


class BNSCustomizeForm(CustomizeForm):
    def set_property_setters_for_actions_and_links(self, meta):
        """
        Override to fix TimestampMismatchError caused by stale browser timestamps
        on custom DocType Link / Action / State records.

        Original bug: Frappe passes browser-sent `modified` timestamp to d.save(),
        but earlier writes in the same request have already advanced the DB timestamp.
        Fix: Sync the DB-fresh `modified` timestamp onto `d` before saving.
        """
        for doctype, fieldname, field_map in (
            ("DocType Link", "links", doctype_link_properties),
            ("DocType Action", "actions", doctype_action_properties),
            ("DocType State", "states", doctype_state_properties),
        ):
            has_custom = False
            items = []
            for i, d in enumerate(self.get(fieldname) or []):
                d.idx = i
                if frappe.db.exists(doctype, d.name) and not d.custom:
                    # Standard record — use property setters (unchanged behaviour)
                    original = frappe.get_doc(doctype, d.name)
                    for prop, prop_type in field_map.items():
                        if d.get(prop) != original.get(prop):
                            self.make_property_setter(
                                prop, d.get(prop), prop_type, apply_on=doctype, row_name=d.name
                            )
                    items.append(d.name)
                else:
                    # Custom record — insert / update
                    d.parent = self.doc_type
                    d.custom = 1
                    # --- FIX: Sync DB timestamp to prevent TimestampMismatchError ---
                    # The browser-sent `modified` may be stale because earlier steps
                    # in this same request already wrote to the DB. Re-fetching the
                    # latest value ensures check_if_latest() sees matching timestamps.
                    if frappe.db.exists(doctype, d.name):
                        d.modified = frappe.db.get_value(doctype, d.name, "modified")
                    # ----------------------------------------------------------------
                    d.save(ignore_permissions=True)
                    has_custom = True
                    items.append(d.name)

            self.update_order_property_setter(has_custom, fieldname)
            self.clear_removed_items(doctype, items)
