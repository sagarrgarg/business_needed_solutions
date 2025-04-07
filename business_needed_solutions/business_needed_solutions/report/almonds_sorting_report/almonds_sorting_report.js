// Copyright (c) 2025, Sagar Ratan Garg and contributors
// For license information, please see license.txt

frappe.query_reports["Almonds Sorting Report"] = {
	"filters": [
		{
            fieldname: 'batch_no',
            label: __('Batch No'),
            fieldtype: "Link",
			options: "Batch",
			reqd:1,
        },
		{
            fieldname: 'item_code',
            label: __('Item Code'),
            fieldtype: "Link",
			options: "Item",
        },
	]
};
