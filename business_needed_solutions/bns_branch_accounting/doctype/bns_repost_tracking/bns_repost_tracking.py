# Copyright (c) 2026, BNS and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.query_builder import Interval
from frappe.query_builder.functions import Now


class BNSRepostTracking(Document):
    """Tracks repost lock and processing status for idempotent BNS repost flows."""

    @staticmethod
    def clear_old_logs(days: int = 90):
        """Make this doctype eligible for Log Settings auto-deletion.

        Implementing this static method satisfies Frappe's ``LogType`` protocol
        (``frappe.core.doctype.log_settings.log_settings``), so the doctype
        becomes selectable in **Log Settings -> Logs to Clear** and the daily
        ``run_log_clean_up`` scheduler job prunes rows not modified within the
        retention window.
        """
        table = frappe.qb.DocType("BNS Repost Tracking")
        frappe.db.delete(table, filters=(table.modified < (Now() - Interval(days=days))))
