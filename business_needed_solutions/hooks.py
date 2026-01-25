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
app_include_js = ["/assets/business_needed_solutions/js/sales_invoice_form.js?v=114",
                  "/assets/business_needed_solutions/js/purchase_invoice_form.js?v=211",
                  "/assets/business_needed_solutions/js/purchase_receipt_form.js?v=44",
                  "/assets/business_needed_solutions/js/delivery_note.js?v=130",
                  "/assets/business_needed_solutions/js/discount_manipulation_by_type.js?v=34",
                  "/assets/business_needed_solutions/js/direct_print.js?v=45",
                  "/assets/business_needed_solutions/js/item.js",
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
              # Stock Transactions
              "Stock Entry" : "public/js/doctype_item_grid_controls.js",
              
              # Sales Documents
              "Sales Invoice" : "public/js/doctype_item_grid_controls.js",
              "Sales Order" : ["public/js/doctype_item_grid_controls.js", "public/js/update_items_override.js"],
              "Delivery Note" : ["public/js/delivery_note.js?v=130", "public/js/doctype_item_grid_controls.js"],
              
              # Purchase Documents
              "Purchase Invoice" : "public/js/doctype_item_grid_controls.js",
              "Purchase Order" : ["public/js/doctype_item_grid_controls.js", "public/js/update_items_override.js"],
              "Purchase Receipt" : ["public/js/purchase_receipt_form.js", "public/js/doctype_item_grid_controls.js"],
              
              # Warehouse
              "Warehouse" : "public/js/warehouse.js"
}


# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
doctype_list_js = {
    "Delivery Note" : "public/js/delivery_note_list.js",
    "Purchase Receipt" : "public/js/purchase_receipt_list.js",
    "Sales Invoice" : "public/js/sales_invoice_list.js",
    "Purchase Invoice" : "public/js/purchase_invoice_list.js"
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
# jinja = {
# 	"methods": "business_needed_solutions.utils.jinja_methods",
# 	"filters": "business_needed_solutions.utils.jinja_filters"
# }

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
    "Customer": {
        "validate": "business_needed_solutions.business_needed_solutions.overrides.pan_validation.validate_pan_uniqueness"
    },
    "Supplier": {
        "validate": "business_needed_solutions.business_needed_solutions.overrides.pan_validation.validate_pan_uniqueness"
    },
    "Item": {
        "validate": "business_needed_solutions.business_needed_solutions.overrides.item_validation.validate_expense_account_for_non_stock_items"
    },
    "Stock Ledger Entry": {
        "validate": "business_needed_solutions.business_needed_solutions.overrides.warehouse_negative_stock.validate_sle_warehouse_negative_stock"
    },
    "Stock Entry": {
        "on_submit": "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission"
    },
    "Delivery Note": {
        "validate": "business_needed_solutions.business_needed_solutions.utils.validate_bns_internal_delivery_note_return",
        "on_submit": [
            "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission",
            "business_needed_solutions.business_needed_solutions.utils.update_delivery_note_status_for_bns_internal",
            "business_needed_solutions.business_needed_solutions.overrides.gst_compliance.maybe_generate_internal_dn_ewaybill"
        ],
        "on_cancel": "business_needed_solutions.business_needed_solutions.utils.validate_delivery_note_cancellation"
    },
    "Purchase Receipt": {
        "on_submit": [
            "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission",
            "business_needed_solutions.business_needed_solutions.utils.update_purchase_receipt_status_for_bns_internal"
        ]
    },
    "Stock Reconciliation": {
        "on_submit": "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission"
    },
    "Sales Invoice": {
        "validate": [
            "business_needed_solutions.business_needed_solutions.overrides.stock_update_validation.validate_stock_update_or_reference",
            "business_needed_solutions.business_needed_solutions.utils.validate_bns_internal_customer_return"
        ],
        "on_submit": [
            "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission",
            "business_needed_solutions.business_needed_solutions.utils.update_sales_invoice_status_for_bns_internal"
        ]
    },
    "Purchase Invoice": {
        "on_submit": [
            "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission",
            "business_needed_solutions.business_needed_solutions.utils.update_purchase_invoice_status_for_bns_internal",
            "business_needed_solutions.business_needed_solutions.overrides.gst_compliance.validate_purchase_invoice_same_gstin"
        ],
        "validate": "business_needed_solutions.business_needed_solutions.overrides.stock_update_validation.validate_stock_update_or_reference"
    },
    "Journal Entry": {
        "on_submit": "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission"
    },
    "Payment Entry": {
        "on_submit": "business_needed_solutions.business_needed_solutions.overrides.submission_restriction.validate_submission_permission"
    },
    "Sales Order": {
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
            {"doctype": "Custom Field", "filters": [["module" , "in" , ("Business Needed Solutions" )]],"overwrite": True},
            {"doctype":"Terms and Conditions", "filters": [["name" , "in" , ("General" )]],"overwrite": True}
        ]
# fixtures = [{"doctype": "Report", "filters": [["module" , "in" , ("Business Needed Solutions" )]]}]


# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"business_needed_solutions.tasks.all"
# 	],
# 	"daily": [
# 		"business_needed_solutions.tasks.daily"
# 	],
# 	"hourly": [
# 		"business_needed_solutions.tasks.hourly"
# 	],
# 	"weekly": [
# 		"business_needed_solutions.tasks.weekly"
# 	],
# 	"monthly": [
# 		"business_needed_solutions.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "business_needed_solutions.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "business_needed_solutions.event.get_events"
# }
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

# Migration hook to ensure BNS settings are applied after migrations
after_migrate = "business_needed_solutions.business_needed_solutions.migration.after_migrate"

# Apply warehouse negative stock restriction patches on app initialization
after_app_init = "business_needed_solutions.business_needed_solutions.overrides.warehouse_negative_stock.apply_patches"

