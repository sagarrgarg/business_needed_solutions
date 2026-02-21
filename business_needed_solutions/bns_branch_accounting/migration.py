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
        remove_old_pr_internal_customer_field()
        disable_pi_update_stock_mandatory_script()
        initialize_bns_repost_tracking_state()
        migrate_split_internal_transfer_accounts()

        logger.info("BNS Branch Accounting post-migration setup completed successfully")

    except Exception as e:
        logger.error("Error in BNS Branch Accounting post-migration setup: %s", str(e))


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

        table_name = "tabPurchase Receipt"
        column_name = "is_bns_internal_customer"
        columns = frappe.db.sql(f"SHOW COLUMNS FROM `{table_name}` LIKE '{column_name}'", as_dict=True)
        if columns:
            frappe.db.sql(f"ALTER TABLE `{table_name}` DROP COLUMN `{column_name}`")
            frappe.db.commit()

    except Exception as e:
        logger.error("Error removing old PR internal customer field: %s", str(e))
        frappe.db.rollback()
