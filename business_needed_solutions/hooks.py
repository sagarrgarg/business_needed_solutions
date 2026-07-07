app_name = "business_needed_solutions"
app_title = "Business Needed Solutions"
app_publisher = "Sagar Ratan Garg"
app_description = "Enterprise-grade business solutions for ERPNext including document submission controls, PAN validation, dynamic print formats, internal transfer management, and Indian compliance features. Perfect for businesses requiring advanced workflow controls and professional document management."
app_email = "sagar1ratan1garg1@gmail.com"
app_license = "Commercial"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "business_needed_solutions",
# 		"logo": "/assets/business_needed_solutions/logo.png",
# 		"title": "Business Needed Solutions",
# 		"route": "/business_needed_solutions",
# 		"has_permission": "business_needed_solutions.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/business_needed_solutions/css/business_needed_solutions.css"
app_include_js = ["/assets/business_needed_solutions/js/sales_invoice_form.js?v=122",
                  "/assets/business_needed_solutions/js/purchase_invoice_form.js?v=218",
                  "/assets/business_needed_solutions/js/purchase_receipt_form.js?v=52",
                  "/assets/business_needed_solutions/js/delivery_note.js?v=137",
                  "/assets/business_needed_solutions/js/discount_manipulation_by_type.js?v=38",
                  "/assets/business_needed_solutions/js/direct_print.js?v=50",
                  "/assets/business_needed_solutions/js/item.js",
                  "/assets/business_needed_solutions/js/pan_gstin_mismatch_banner.js?v=1",
                  "/assets/business_needed_solutions/js/bulk_cancel.js?v=1",
                  "/assets/business_needed_solutions/js/posting_time_edit.js?v=1",
                  "/assets/business_needed_solutions/js/tds_backfill.js?v=1",
                ]

# include js, css files in header of web template
# web_include_css = "/assets/business_needed_solutions/css/business_needed_solutions.css"
# web_include_js = "/assets/business_needed_solutions/js/business_needed_solutions.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "business_needed_solutions/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
doctype_js = {
              # Address (FSSAI visibility for food companies)
              "Address": "public/js/address.js",
              # BNS internal: hide standard internal when BNS internal is on
              "Customer": "public/js/bns_customer.js",
              "Supplier": "public/js/bns_supplier.js",
              # Stock Transactions
              "Stock Entry" : "public/js/doctype_item_grid_controls.js",
              
              # Sales Documents
              "Sales Invoice" : "public/js/doctype_item_grid_controls.js",
              "Sales Order" : ["public/js/doctype_item_grid_controls.js", "public/js/update_items_override.js"],
              "Delivery Note" : "public/js/doctype_item_grid_controls.js",
              
              # Purchase Documents
              "Purchase Invoice" : ["public/js/doctype_item_grid_controls.js", "public/js/purchase_attachment_fields.js"],
              "Purchase Order" : ["public/js/doctype_item_grid_controls.js", "public/js/update_items_override.js"],
              "Purchase Receipt" : ["public/js/doctype_item_grid_controls.js", "public/js/purchase_attachment_fields.js"],
              
              # Warehouse
              "Warehouse" : "public/js/warehouse.js",

              # Warn when posting against wrong side of linked Customer/Supplier
              # (Payment Entry = header party; Journal Entry = accounts child rows).
              "Payment Entry": "public/js/linked_party_warning.js",
              "Journal Entry": "public/js/linked_party_warning.js",

              # BNS Branch Accounting Settings
              "BNS Branch Accounting Settings": "bns_branch_accounting/doctype/bns_branch_accounting_settings/bns_branch_accounting_settings.js"
}


# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
doctype_list_js = {
    "Delivery Note" : "public/js/delivery_note_list.js",
    "Purchase Receipt" : "public/js/purchase_receipt_list.js",
    "Sales Invoice" : "public/js/sales_invoice_list.js",
    "Purchase Invoice" : "public/js/purchase_invoice_list.js",
    "Supplier" : "public/js/supplier_list.js"
}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "business_needed_solutions/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
jinja = {
    "methods": [
        "business_needed_solutions.bns_branch_accounting.gst_integration.get_ewaybill_data_for_print"
    ]
}

# Installation
# ------------

# before_install = "business_needed_solutions.install.before_install"
# after_install = "business_needed_solutions.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "business_needed_solutions.uninstall.before_uninstall"
# after_uninstall = "business_needed_solutions.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "business_needed_solutions.utils.before_app_install"
# after_app_install = "business_needed_solutions.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "business_needed_solutions.utils.before_app_uninstall"
# after_app_uninstall = "business_needed_solutions.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "business_needed_solutions.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

override_doctype_class = {
	"Stock Entry": "business_needed_solutions.business_needed_solutions.overrides.stock_entry_component_qty_variance.BNSStockEntry"
}

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

doc_events = {
    "Address": {
        "before_save": "business_needed_solutions.business_needed_solutions.overrides.address_preferred_flags.enforce_suppress_preferred_address"
    },
    "Customer": {
        "validate": [
            "business_needed_solutions.business_needed_solutions.overrides.pan_validation.validate_pan_uniqueness",
            "business_needed_solutions.bns_branch_accounting.overrides.internal_party.enforce_bns_over_standard_internal_customer",
        ]
    },
    "Supplier": {
        "validate": [
            "business_needed_solutions.business_needed_solutions.overrides.pan_validation.validate_pan_uniqueness",
            "business_needed_solutions.bns_branch_accounting.overrides.internal_party.enforce_bns_over_standard_internal_supplier",
        ]
    },
    "Item": {
        "validate": "business_needed_solutions.business_needed_solutions.overrides.item_validation.validate_expense_account_for_non_stock_items"
    },
    "Stock Ledger Entry": {
        "validate": [
            "business_needed_solutions.business_needed_solutions.overrides.warehouse_negative_stock.validate_sle_warehouse_negative_stock",
            "business_needed_solutions.business_needed_solutions.overrides.negative_stock_override.validate_sle_negative_stock_cutoff",
        ]
    },
    "Stock Entry": {
        "before_submit": [
            "business_needed_solutions.business_needed_solutions.overrides.ensure_stock_patches.before_submit",
        ],
        "on_submit": "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission",
        "on_cancel": "business_needed_solutions.bns_branch_accounting.utils.bns_ignore_repost_ledger_links_on_cancel"
    },
    "Delivery Note": {
        "validate": [
            "business_needed_solutions.bns_branch_accounting.overrides.billing_location.set_customer_address_from_billing_location",
            "business_needed_solutions.bns_branch_accounting.utils.validate_bns_internal_delivery_note_return"
        ],
        "before_submit": [
            "business_needed_solutions.business_needed_solutions.overrides.ensure_stock_patches.before_submit",
            "business_needed_solutions.bns_branch_accounting.utils.validate_bns_internal_accounting_settings_for_dn_pr",
            "business_needed_solutions.bns_branch_accounting.utils.validate_internal_return_credit_note_parity",
        ],
        "on_submit": [
            "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission",
            "business_needed_solutions.bns_branch_accounting.gst_integration.validate_internal_dn_vehicle_no",
            "business_needed_solutions.bns_branch_accounting.utils.update_delivery_note_status_for_bns_internal",
            "business_needed_solutions.bns_branch_accounting.utils.backlink_internal_return_debit_note",
            "business_needed_solutions.bns_branch_accounting.gst_integration.maybe_generate_internal_dn_ewaybill"
        ],
        "on_cancel": [
            "business_needed_solutions.bns_branch_accounting.utils.validate_delivery_note_cancellation",
            "business_needed_solutions.bns_branch_accounting.utils.ignore_payment_ledger_cancellation_links_for_dn",
            "business_needed_solutions.bns_branch_accounting.utils.bns_ignore_repost_ledger_links_on_cancel"
        ]
    },
    "Purchase Receipt": {
        "validate": "business_needed_solutions.bns_branch_accounting.utils.validate_internal_purchase_receipt_linkage",
        "before_submit": [
            "business_needed_solutions.business_needed_solutions.overrides.ensure_stock_patches.before_submit",
            "business_needed_solutions.bns_branch_accounting.utils.validate_bns_internal_accounting_settings_for_dn_pr",
            "business_needed_solutions.bns_branch_accounting.utils.validate_internal_purchase_receipt_linkage",
            "business_needed_solutions.business_needed_solutions.overrides.attachment_validation.validate_purchase_attachments",
            "business_needed_solutions.business_needed_solutions.overrides.ineligible_itc_submission_control.restrict_ineligible_itc_submission"
        ],
        "on_submit": [
            "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission",
            "business_needed_solutions.bns_branch_accounting.utils.update_purchase_receipt_status_for_bns_internal",
            "business_needed_solutions.bns_branch_accounting.utils.bns_apply_asset_transfer"
        ],
        "before_cancel": "business_needed_solutions.bns_branch_accounting.utils.ignore_parent_cancellation_links_for_bns_internal",
        "on_cancel": [
            "business_needed_solutions.bns_branch_accounting.utils.unlink_references_on_purchase_cancel",
            "business_needed_solutions.bns_branch_accounting.utils.bns_revert_asset_transfer",
            "business_needed_solutions.bns_branch_accounting.utils.bns_ignore_repost_ledger_links_on_cancel"
        ]
    },
    "Stock Reconciliation": {
        "before_submit": [
            "business_needed_solutions.business_needed_solutions.overrides.ensure_stock_patches.before_submit",
        ],
        "on_submit": "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission"
    },
    "Sales Invoice": {
        "validate": [
            "business_needed_solutions.business_needed_solutions.overrides.invoice_discount_credit_note.normalize_invoice_discount_credit_note",
            "business_needed_solutions.bns_branch_accounting.overrides.billing_location.set_customer_address_from_billing_location",
            "business_needed_solutions.business_needed_solutions.overrides.stock_update_validation.validate_stock_update_or_reference",
            "business_needed_solutions.bns_branch_accounting.utils.validate_bns_internal_customer_return",
            "business_needed_solutions.bns_branch_accounting.utils.validate_internal_sales_invoice_linkage",
        ],
        "before_submit": [
            "business_needed_solutions.business_needed_solutions.overrides.ensure_stock_patches.before_submit",
            "business_needed_solutions.bns_branch_accounting.utils.validate_internal_stock_movement_captured",
            "business_needed_solutions.bns_branch_accounting.utils.validate_internal_return_credit_note_parity",
        ],
        "on_submit": [
            "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission",
            "business_needed_solutions.bns_branch_accounting.utils.update_sales_invoice_status_for_bns_internal",
            "business_needed_solutions.bns_branch_accounting.utils.backlink_internal_return_debit_note"
        ],
        "on_cancel": [
            "business_needed_solutions.bns_branch_accounting.utils.cancel_linked_purchase_docs_for_sales_invoice",
            "business_needed_solutions.bns_branch_accounting.utils.bns_ignore_repost_ledger_links_on_cancel"
        ]
    },
    "Purchase Invoice": {
        "before_submit": [
            "business_needed_solutions.business_needed_solutions.overrides.ensure_stock_patches.before_submit",
            "business_needed_solutions.business_needed_solutions.overrides.attachment_validation.validate_purchase_attachments",
            "business_needed_solutions.bns_branch_accounting.utils.validate_internal_purchase_invoice_si_parity",
            "business_needed_solutions.bns_branch_accounting.utils.validate_internal_purchase_return_linkage",
            "business_needed_solutions.bns_branch_accounting.utils.validate_internal_stock_movement_captured",
            "business_needed_solutions.business_needed_solutions.overrides.ineligible_itc_submission_control.restrict_ineligible_itc_submission",
        ],
        "on_submit": [
            "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission",
            "business_needed_solutions.bns_branch_accounting.utils.update_purchase_invoice_status_for_bns_internal",
            "business_needed_solutions.bns_branch_accounting.utils.bns_apply_asset_transfer"
        ],
        "validate": [
            "business_needed_solutions.business_needed_solutions.overrides.stock_update_validation.validate_stock_update_or_reference",
            "business_needed_solutions.business_needed_solutions.overrides.gst_compliance.validate_purchase_invoice_same_gstin",
            "business_needed_solutions.bns_branch_accounting.utils.validate_internal_purchase_invoice_transfer_rate",
            "business_needed_solutions.business_needed_solutions.overrides.auto_paid_supplier.auto_mark_paid"
        ],
        "before_cancel": "business_needed_solutions.bns_branch_accounting.utils.ignore_parent_cancellation_links_for_bns_internal",
        "on_cancel": [
            "business_needed_solutions.bns_branch_accounting.utils.unlink_references_on_purchase_cancel",
            "business_needed_solutions.bns_branch_accounting.utils.bns_revert_asset_transfer",
            "business_needed_solutions.bns_branch_accounting.utils.bns_ignore_repost_ledger_links_on_cancel"
        ]
    },
    "Repost Item Valuation": {
        "on_change": [
            "business_needed_solutions.bns_branch_accounting.utils.refresh_pr_transfer_rate_after_repost",
            "business_needed_solutions.bns_branch_accounting.utils.refresh_si_transfer_rate_after_repost",
            "business_needed_solutions.bns_branch_accounting.utils.refresh_bns_internal_status_after_repost",
        ]
    },
    "Journal Entry": {
        "on_submit": [
            "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission",
            "business_needed_solutions.bns_branch_accounting.utils.bns_repost_asset_transfers_on_depreciation"
        ],
        "on_cancel": [
            "business_needed_solutions.bns_branch_accounting.utils.bns_repost_asset_transfers_on_depreciation",
            "business_needed_solutions.bns_branch_accounting.utils.bns_ignore_repost_ledger_links_on_cancel"
        ]
    },
    "Payment Entry": {
        "on_submit": "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission",
        "on_cancel": "business_needed_solutions.bns_branch_accounting.utils.bns_ignore_repost_ledger_links_on_cancel"
    },
    "Sales Order": {
        "validate": "business_needed_solutions.bns_branch_accounting.overrides.billing_location.set_customer_address_from_billing_location",
        "on_submit": "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission"
    },
    "Purchase Order": {
        "on_submit": "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission"
    },
    "Payment Request": {
        "on_submit": "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission"
    }
}

fixtures = [
            # {"doctype": "Client Script", "filters": [["module" , "in" , ("Business Needed Solutions" )]]},
            # {"doctype": "Print Format", "filters": [["module" , "in" , ("Business Needed Solutions" )]],"overwrite": True},
            {"doctype": "Custom Field", "filters": [["module" , "in" , ("Business Needed Solutions", "BNS Branch Accounting")]],"overwrite": True},
            {"doctype":"Terms and Conditions", "filters": [["name" , "in" , ("General" )]],"overwrite": True},
            {"doctype":"Property Setter", "filters": [["module" , "in" , ("Business Needed Solutions", "BNS Branch Accounting")]],"overwrite": True}
        ]
# fixtures = [{"doctype": "Report", "filters": [["module" , "in" , ("Business Needed Solutions" )]]}]


# Scheduled Tasks
# ---------------

# Daily tick for the Common Party auto square-off. The function itself checks
# the BNS Settings schedule (Disabled/Weekly/Monthly/Quarterly/Yearly) and the
# last_run_on stamp, so ticking daily is cheap and lets operators change the
# cadence without restarting anything.
scheduler_events = {
    "daily": [
        "business_needed_solutions.bns_branch_accounting.common_party_squareoff.scheduled_squareoff_run",
        "business_needed_solutions.bns_branch_accounting.utils.reassert_bns_internal_invoice_status"
    ],
    "weekly": [
        "business_needed_solutions.business_needed_solutions.gl_sle_audit.scheduled_auto_fix_missing_ledgers"
    ],
    "cron": {
        "*/5 * * * *": [
            "business_needed_solutions.bns_branch_accounting.utils.bns_prioritize_repost_item_valuation"
        ]
    }
}

# Testing
# -------

# before_tests = "business_needed_solutions.install.before_tests"

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
	"frappe.desk.form.linked_with.get_submitted_linked_docs": "business_needed_solutions.bns_branch_accounting.overrides.cancel_dialog.get_submitted_linked_docs",
	"frappe.client.get_value": "business_needed_solutions.business_needed_solutions.overrides.get_value_filters_fix.get_value",
}

# Allow Delivery Note in Repost Accounting Ledger processing.
repost_allowed_doctypes = ["Delivery Note"]
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "business_needed_solutions.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["business_needed_solutions.utils.before_request"]
# after_request = ["business_needed_solutions.utils.after_request"]

# Job Events
# ----------
# before_job = ["business_needed_solutions.utils.before_job"]
# after_job = ["business_needed_solutions.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"business_needed_solutions.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Migration hook to ensure BNS branch-accounting setup is applied after migrations
after_migrate = "business_needed_solutions.bns_branch_accounting.migration.after_migrate"

# Runtime monkey-patches that must be available on any request/job.
# Stock-specific patches are applied via doc_events (before_submit) instead.
# get_value_filters_fix is handled via override_whitelisted_methods.
_global_runtime_patches = [
	"business_needed_solutions.bns_branch_accounting.utils.apply_bns_runtime_patches",
	# Temporary: fix Purchase Register tax doubling when PI name = PR name
	# Remove when ERPNext merges upstream fix
	"business_needed_solutions.business_needed_solutions.overrides.purchase_register_fix.apply_purchase_register_fix",
]
before_request = _global_runtime_patches
before_job = _global_runtime_patches

