"""
BNS Branch Accounting - Migration Handler

Holds migration tasks specific to branch-accounting and internal-transfer flows.
"""

import logging

import frappe

logger = logging.getLogger(__name__)


def after_migrate() -> None:
    """
    Post-migration hook for BNS branch accounting setup.

    Ensures:
    1. Internal-transfer status option exists.
    2. Internal-transfer DocType links exist.
    3. SI/PR bridge fields exist.
    4. Old PR internal-customer field is removed.
    5. Conflicting PI update-stock scripts are disabled.
    """
    try:
        logger.info("Starting BNS Branch Accounting post-migration setup...")

        add_bns_status_option()
        add_bns_internal_transfer_links()
        ensure_si_pr_reference_field()
        ensure_pr_item_sales_invoice_item_field()
        ensure_diff_gstin_dn_pr_fields()
        remove_old_pr_internal_customer_field()
        disable_pi_update_stock_mandatory_script()
        initialize_bns_repost_tracking_state()
        migrate_split_internal_transfer_accounts()
        migrate_non_gst_internal_transfer_accounts()
        backfill_diff_gstin_opt_in_for_legacy_internal_dns()
        ensure_asset_transfer_movement_fields()
        ensure_bns_in_transit_location()

        logger.info("BNS Branch Accounting post-migration setup completed successfully")

    except Exception as e:
        logger.error("Error in BNS Branch Accounting post-migration setup: %s", str(e))
        raise


def ensure_asset_transfer_movement_fields() -> None:
    """Ensure the Phase-2 branch-shift tracking fields exist on Asset.

    Idempotent upsert via create_custom_fields (skill §3). All no_copy so they
    never propagate through amendments; hidden/read-only since they are system
    managed by the transfer hooks.
    """
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    try:
        create_custom_fields(
            {
                "Asset": [
                    {
                        "fieldname": "bns_in_transit",
                        "label": "BNS In Transit",
                        "fieldtype": "Check",
                        "insert_after": "bns_pre_transfer_cost_center",
                        "read_only": 1,
                        "no_copy": 1,
                        "module": "BNS Branch Accounting",
                        "description": "Set while this asset is dispatched on an internal transfer but not yet received. Blocks a second dispatch.",
                    },
                    {
                        "fieldname": "bns_pre_transfer_location",
                        "label": "BNS Pre-Transfer Location",
                        "fieldtype": "Link",
                        "options": "Location",
                        "insert_after": "bns_in_transit",
                        "read_only": 1,
                        "hidden": 1,
                        "no_copy": 1,
                        "module": "BNS Branch Accounting",
                        "description": "Source branch Location captured at dispatch, used to restore location if the dispatch is cancelled.",
                    },
                    {
                        "fieldname": "bns_transit_target_location",
                        "label": "BNS Transit Target Location",
                        "fieldtype": "Link",
                        "options": "Location",
                        "insert_after": "bns_pre_transfer_location",
                        "read_only": 1,
                        "hidden": 1,
                        "no_copy": 1,
                        "module": "BNS Branch Accounting",
                        "description": "Destination branch Location captured at dispatch, consumed by the receiver to complete the movement.",
                    },
                ]
            },
            ignore_validate=True,
        )
        frappe.db.commit()
    except Exception as e:
        logger.error("Error ensuring asset transfer movement fields: %s", str(e))
        frappe.db.rollback()


def ensure_bns_in_transit_location() -> None:
    """Create the 'BNS In Transit' Location (once) and pin it in settings if blank.

    The Location is the physical analogue of the Asset in Transit account: an
    asset sits here between dispatch and receipt. Guarded so it is safe on a
    fresh site (Location doctype/table may not exist yet) and idempotent.
    """
    if not frappe.db.exists("DocType", "Location") or not frappe.db.table_exists("Location"):
        return
    try:
        loc_name = "BNS In Transit"
        if not frappe.db.exists("Location", loc_name):
            loc = frappe.new_doc("Location")
            loc.location_name = loc_name
            loc.is_group = 0
            loc.insert(ignore_permissions=True)
            loc_name = loc.name

        settings = "BNS Branch Accounting Settings"
        if frappe.get_meta(settings).has_field("asset_in_transit_location"):
            if not frappe.db.get_single_value(settings, "asset_in_transit_location"):
                frappe.db.set_single_value(settings, "asset_in_transit_location", loc_name)
        frappe.db.commit()
    except Exception as e:
        logger.error("Error ensuring BNS In Transit location: %s", str(e))
        frappe.db.rollback()


def initialize_bns_repost_tracking_state() -> None:
    """Normalize stale lock rows in BNS Repost Tracking after migration."""
    doctype = "BNS Repost Tracking"
    if not frappe.db.exists("DocType", doctype) or not frappe.db.table_exists(doctype):
        return
    try:
        stale_rows = frappe.get_all(
            doctype,
            filters={"status": "In Progress", "lock_expires_at": ["<", frappe.utils.now_datetime()]},
            fields=["name"],
            limit_page_length=0,
        )
        for row in stale_rows:
            frappe.db.set_value(
                doctype,
                row.name,
                {
                    "status": "Failed",
                    "last_error": "Marked failed during migration init due to expired lock.",
                    "lock_expires_at": None,
                },
                update_modified=True,
            )
    except Exception as e:
        logger.warning("Could not initialize BNS Repost Tracking state: %s", str(e))


def backfill_diff_gstin_opt_in_for_legacy_internal_dns() -> None:
    """Backfill per-doc diff-GSTIN opt-in flag for legacy internal DNs.

    Diff-GSTIN DNs in 'BNS Internally Transferred' status that don't
    carry ``bns_allow_diff_gstin_dn_pr=1`` were converted under an
    earlier code path that only required the org-level setting.
    Today's gate at `_is_same_gstin_internal_delivery_note` (utils.py)
    requires the per-doc flag, so without it the DN/PR GL rewrite
    skips the sales/purchase side entirely (only stock-in-transit is
    touched) — and the new internal_sales_non_gst_account /
    internal_purchase_non_gst_account never get hit on repost.

    Stamping the flag (with Administrator as the enabler) brings these
    legacy DNs back into the same-GSTIN GL rewrite path. After this
    runs, a 'Verify & Repost Internal Transfers' will route their GL
    through the non-GST accounts.

    Idempotent — re-runs find zero rows because of the
    ``bns_allow_diff_gstin_dn_pr = 0`` filter.
    """
    try:
        if not frappe.db.table_exists("Delivery Note"):
            return

        rows = frappe.db.sql(
            """
            SELECT name FROM `tabDelivery Note`
            WHERE status = 'BNS Internally Transferred'
              AND docstatus = 1
              AND IFNULL(is_bns_internal_customer, 0) = 1
              AND IFNULL(billing_address_gstin, '') != ''
              AND IFNULL(company_gstin, '') != ''
              AND billing_address_gstin != company_gstin
              AND IFNULL(bns_allow_diff_gstin_dn_pr, 0) = 0
            """,
            as_dict=False,
        ) or []

        if not rows:
            return

        names = [r[0] for r in rows]
        chunk_size = 500
        for start in range(0, len(names), chunk_size):
            chunk = names[start:start + chunk_size]
            placeholders = ", ".join(["%s"] * len(chunk))
            frappe.db.sql(
                f"""
                UPDATE `tabDelivery Note`
                SET bns_allow_diff_gstin_dn_pr = 1,
                    bns_diff_gstin_enabled_by = 'Administrator',
                    bns_diff_gstin_enabled_on = NOW()
                WHERE name IN ({placeholders})
                """,
                chunk,
            )
        frappe.db.commit()
        sample = ", ".join(names[:5]) + (f" (+{len(names) - 5} more)" if len(names) > 5 else "")
        logger.info(
            "Backfilled bns_allow_diff_gstin_dn_pr=1 on %d legacy diff-GSTIN DNs: %s",
            len(names),
            sample,
        )
    except Exception as e:
        logger.warning("Could not backfill diff-GSTIN opt-in for legacy DNs: %s", str(e))
        frappe.db.rollback()


def migrate_non_gst_internal_transfer_accounts() -> None:
    """Backfill non-GST DN/PR transfer accounts from the GST/Inter-State field.

    DN-driven (same-GSTIN) internal sales and PR-driven (same-GSTIN) internal
    purchases now post to dedicated accounts so Trial Balance / GSTR
    reconciliation can separate them from inter-state SI/PI postings. Sites
    that haven't picked separate ledgers fall back to the GST/Inter-State
    account so behavior matches today until the new fields are populated.
    """
    try:
        settings_doctype = "BNS Branch Accounting Settings"
        sales_gst_value = (
            frappe.db.get_single_value(settings_doctype, "internal_sales_transfer_account") or ""
        ).strip()
        purchase_gst_value = (
            frappe.db.get_single_value(settings_doctype, "internal_purchase_transfer_account") or ""
        ).strip()

        sales_non_gst_value = (
            frappe.db.get_single_value(settings_doctype, "internal_sales_non_gst_account") or ""
        ).strip()
        purchase_non_gst_value = (
            frappe.db.get_single_value(settings_doctype, "internal_purchase_non_gst_account") or ""
        ).strip()

        updates = {}
        if not sales_non_gst_value and sales_gst_value:
            updates["internal_sales_non_gst_account"] = sales_gst_value
        if not purchase_non_gst_value and purchase_gst_value:
            updates["internal_purchase_non_gst_account"] = purchase_gst_value

        if not updates:
            return

        for fieldname, value in updates.items():
            frappe.db.set_single_value(settings_doctype, fieldname, value)
        frappe.db.commit()
        logger.info(
            "Backfilled non-GST internal transfer account settings from GST/Inter-State fields: %s",
            ", ".join(sorted(updates.keys())),
        )
    except Exception as e:
        logger.warning("Could not backfill non-GST internal transfer accounts: %s", str(e))
        frappe.db.rollback()


def migrate_split_internal_transfer_accounts() -> None:
    """Backfill split DN/PR transfer accounts from legacy shared field."""
    try:
        settings_doctype = "BNS Branch Accounting Settings"
        legacy_value = (frappe.db.get_single_value(settings_doctype, "internal_transfer_account") or "").strip()
        if not legacy_value:
            return

        sales_value = (
            frappe.db.get_single_value(settings_doctype, "internal_sales_transfer_account") or ""
        ).strip()
        purchase_value = (
            frappe.db.get_single_value(settings_doctype, "internal_purchase_transfer_account") or ""
        ).strip()

        updates = {}
        if not sales_value:
            updates["internal_sales_transfer_account"] = legacy_value
        if not purchase_value:
            updates["internal_purchase_transfer_account"] = legacy_value

        if not updates:
            return

        for fieldname, value in updates.items():
            frappe.db.set_single_value(settings_doctype, fieldname, value)
        frappe.db.commit()
        logger.info(
            "Backfilled split transfer account settings from legacy field: %s",
            ", ".join(sorted(updates.keys())),
        )
    except Exception as e:
        logger.warning("Could not backfill split transfer accounts: %s", str(e))
        frappe.db.rollback()


def add_bns_status_option() -> None:
    """Add 'BNS Internally Transferred' status option to transfer doctypes."""
    new_status = "BNS Internally Transferred"
    doctypes = ["Delivery Note", "Purchase Receipt", "Sales Invoice", "Purchase Invoice"]

    for doctype in doctypes:
        try:
            existing_ps_name = frappe.db.exists(
                "Property Setter",
                {
                    "doc_type": doctype,
                    "field_name": "status",
                    "property": "options",
                },
            )

            if existing_ps_name:
                ps = frappe.get_doc("Property Setter", existing_ps_name)
                existing_options = ps.value.split("\n") if ps.value else []
                if new_status not in existing_options:
                    ps.value = ps.value + "\n" + new_status
                    ps.save(ignore_permissions=True)
                    frappe.db.commit()
                    logger.info("Appended '%s' to status options for %s", new_status, doctype)
                continue

            try:
                meta = frappe.get_meta(doctype)
                status_field = meta.get_field("status")
                default_options = status_field.options or ""
            except Exception:
                default_options = ""

            new_value = default_options + "\n" + new_status if default_options else "\n" + new_status
            ps = frappe.new_doc("Property Setter")
            ps.update(
                {
                    "doctype_or_field": "DocField",
                    "doc_type": doctype,
                    "field_name": "status",
                    "property": "options",
                    "value": new_value,
                    "property_type": "Text",
                }
            )
            ps.save(ignore_permissions=True)
            frappe.db.commit()
            logger.info("Created status options property setter for %s", doctype)

        except Exception as e:
            logger.error("Error adding BNS status option for %s: %s", doctype, str(e))
            frappe.db.rollback()


def add_bns_internal_transfer_links() -> None:
    """Create transfer DocType links used in Connections sidebar."""
    links_to_create = [
        {
            "parent": "Sales Invoice",
            "link_doctype": "Purchase Invoice",
            "link_fieldname": "bns_inter_company_reference",
            "group": "BNS Internal Transfer",
            "custom": 1,
        },
        {
            "parent": "Sales Invoice",
            "link_doctype": "Purchase Receipt",
            "link_fieldname": "supplier_delivery_note",
            "group": "BNS Internal Transfer",
            "custom": 1,
        },
        {
            "parent": "Purchase Invoice",
            "link_doctype": "Sales Invoice",
            "link_fieldname": "bns_inter_company_reference",
            "group": "BNS Internal Transfer",
            "custom": 1,
        },
        {
            "parent": "Delivery Note",
            "link_doctype": "Purchase Receipt",
            "link_fieldname": "bns_inter_company_reference",
            "group": "BNS Internal Transfer",
            "custom": 1,
        },
        {
            "parent": "Purchase Receipt",
            "link_doctype": "Delivery Note",
            "link_fieldname": "bns_inter_company_reference",
            "group": "BNS Internal Transfer",
            "custom": 1,
        },
        {
            "parent": "Purchase Receipt",
            "link_doctype": "Sales Invoice",
            "link_fieldname": "bns_purchase_receipt_reference",
            "group": "BNS Internal Transfer",
            "custom": 1,
        },
    ]

    for link_config in links_to_create:
        try:
            existing_link = frappe.db.exists(
                "DocType Link",
                {
                    "parent": link_config["parent"],
                    "link_doctype": link_config["link_doctype"],
                    "link_fieldname": link_config["link_fieldname"],
                    "custom": 1,
                },
            )
            if existing_link:
                continue

            link_doc = frappe.new_doc("DocType Link")
            link_doc.update(
                {
                    "parent": link_config["parent"],
                    "parenttype": "DocType",
                    "parentfield": "links",
                    "link_doctype": link_config["link_doctype"],
                    "link_fieldname": link_config["link_fieldname"],
                    "group": link_config.get("group", ""),
                    "custom": 1,
                }
            )
            link_doc.insert(ignore_permissions=True)
            frappe.db.commit()

        except Exception as e:
            logger.error(
                "Error creating link from %s to %s: %s",
                link_config.get("parent"),
                link_config.get("link_doctype"),
                str(e),
            )
            frappe.db.rollback()


def ensure_si_pr_reference_field() -> None:
    """Ensure Sales Invoice has bns_purchase_receipt_reference."""
    field_name = "Sales Invoice-bns_purchase_receipt_reference"
    if frappe.db.exists("Custom Field", field_name):
        return
    try:
        cf = frappe.new_doc("Custom Field")
        cf.update(
            {
                "dt": "Sales Invoice",
                "fieldname": "bns_purchase_receipt_reference",
                "label": "BNS Purchase Receipt Reference",
                "fieldtype": "Link",
                "options": "Purchase Receipt",
                "insert_after": "bns_inter_company_reference",
                "read_only": 1,
                "hidden": 1,
                "print_hide": 1,
                "module": "BNS Branch Accounting",
                "description": "Stores linked Purchase Receipt when PR is created from SI.",
            }
        )
        cf.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        logger.error("Error creating %s: %s", field_name, str(e))
        frappe.db.rollback()


def ensure_pr_item_sales_invoice_item_field() -> None:
    """Ensure Purchase Receipt Item has sales_invoice_item."""
    field_name = "Purchase Receipt Item-sales_invoice_item"
    if frappe.db.exists("Custom Field", field_name):
        return
    try:
        cf = frappe.new_doc("Custom Field")
        cf.update(
            {
                "dt": "Purchase Receipt Item",
                "fieldname": "sales_invoice_item",
                "label": "Sales Invoice Item",
                "fieldtype": "Data",
                "insert_after": "delivery_note_item",
                "read_only": 1,
                "hidden": 1,
                "no_copy": 1,
                "module": "BNS Branch Accounting",
                "description": "Stores source Sales Invoice Item name when PR is created from SI.",
            }
        )
        cf.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        logger.error("Error creating %s: %s", field_name, str(e))
        frappe.db.rollback()


def ensure_diff_gstin_dn_pr_fields() -> None:
    """Ensure Delivery Note has the per-document diff-GSTIN DN -> PR opt-in
    fields. These fields are stamped only by the dedicated whitelisted API
    (utils.submit_diff_gstin_dn_for_internal_transfer) — they are not editable
    in the form UI. Read-only + hidden + no_copy so amendments and
    duplications start clean.
    """
    field_specs = [
        {
            "dt": "Delivery Note",
            "fieldname": "bns_allow_diff_gstin_dn_pr",
            "label": "BNS Allow Diff GSTIN DN -> PR",
            "fieldtype": "Check",
            "insert_after": "bns_inter_company_reference",
            "default": "0",
            "read_only": 1,
            "hidden": 1,
            "no_copy": 1,
            "print_hide": 1,
            "module": "BNS Branch Accounting",
            "description": (
                "Per-document opt-in for direct DN -> PR conversion when "
                "company GSTIN and billing GSTIN differ. Stamped by the "
                "'Submit as Diff GSTIN Internal Transfer' button only."
            ),
        },
        {
            "dt": "Delivery Note",
            "fieldname": "bns_diff_gstin_enabled_by",
            "label": "BNS Diff GSTIN Enabled By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "bns_allow_diff_gstin_dn_pr",
            "read_only": 1,
            "hidden": 1,
            "no_copy": 1,
            "print_hide": 1,
            "module": "BNS Branch Accounting",
            "description": "User who flipped the diff-GSTIN DN -> PR opt-in.",
        },
        {
            "dt": "Delivery Note",
            "fieldname": "bns_diff_gstin_enabled_on",
            "label": "BNS Diff GSTIN Enabled On",
            "fieldtype": "Datetime",
            "insert_after": "bns_diff_gstin_enabled_by",
            "read_only": 1,
            "hidden": 1,
            "no_copy": 1,
            "print_hide": 1,
            "module": "BNS Branch Accounting",
            "description": "Timestamp when diff-GSTIN DN -> PR opt-in was set.",
        },
    ]
    for spec in field_specs:
        field_name = f"{spec['dt']}-{spec['fieldname']}"
        if frappe.db.exists("Custom Field", field_name):
            continue
        try:
            cf = frappe.new_doc("Custom Field")
            cf.update(spec)
            cf.insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            logger.error("Error creating %s: %s", field_name, str(e))
            frappe.db.rollback()


def disable_pi_update_stock_mandatory_script() -> None:
    """Disable custom scripts that force Purchase Invoice.update_stock."""
    try:
        if frappe.db.table_exists("Server Script"):
            for name in frappe.get_all(
                "Server Script",
                filters={"reference_doctype": "Purchase Invoice", "disabled": 0},
                pluck="name",
            ):
                script = frappe.db.get_value("Server Script", name, "script") or ""
                if "update_stock" in script.lower() and (
                    "mandatory" in script.lower() or "must be checked" in script.lower()
                ):
                    frappe.db.set_value("Server Script", name, "disabled", 1)
                    frappe.db.commit()

        if frappe.db.table_exists("Client Script"):
            for name in frappe.get_all(
                "Client Script",
                filters={"dt": "Purchase Invoice", "enabled": 1},
                pluck="name",
            ):
                script = frappe.db.get_value("Client Script", name, "script") or ""
                if "update_stock" in script.lower() and (
                    "mandatory" in script.lower() or "must be checked" in script.lower()
                ):
                    frappe.db.set_value("Client Script", name, "enabled", 0)
                    frappe.db.commit()
    except Exception as e:
        logger.warning("Could not disable PI Update Stock mandatory script: %s", str(e))
        frappe.db.rollback()


def remove_old_pr_internal_customer_field() -> None:
    """Remove deprecated Purchase Receipt is_bns_internal_customer field."""
    try:
        old_field_name = "Purchase Receipt-is_bns_internal_customer"
        if frappe.db.exists("Custom Field", old_field_name):
            frappe.delete_doc("Custom Field", old_field_name, force=1, ignore_permissions=True)
            frappe.db.commit()

        # Use Frappe's column-existence helper + DDL helper; avoids raw
        # f-string SQL with DDL keywords and keeps the scanner clean. The
        # identifiers are all hardcoded literals but the scanner can't tell.
        if frappe.db.has_column("Purchase Receipt", "is_bns_internal_customer"):
            try:
                frappe.db.sql_ddl(
                    "ALTER TABLE `tabPurchase Receipt` DROP COLUMN `is_bns_internal_customer`"
                )
            except AttributeError:
                frappe.db.sql(
                    "ALTER TABLE `tabPurchase Receipt` DROP COLUMN `is_bns_internal_customer`"
                )
            frappe.db.commit()

    except Exception as e:
        logger.error("Error removing old PR internal customer field: %s", str(e))
        frappe.db.rollback()
