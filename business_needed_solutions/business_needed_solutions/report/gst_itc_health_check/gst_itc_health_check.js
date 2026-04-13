frappe.query_reports["GST ITC Health Check"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier",
		},
		{
			fieldname: "issue_type",
			label: __("Issue Type"),
			fieldtype: "MultiSelectList",
			get_data: function (txt) {
				const options = [
					"POS Mismatch",
					"Tax Type Mismatch",
					"ITC Expensed PoS",
					"ITC Expensed 17(5)",
				];
				return options
					.filter((o) => !txt || o.toLowerCase().includes(txt.toLowerCase()))
					.map((o) => ({ value: o, description: "" }));
			},
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.fieldname === "issue_type" && data) {
			const colors = {
				"POS Mismatch": "orange",
				"Tax Type Mismatch": "red",
				"ITC Expensed PoS": "blue",
				"ITC Expensed 17(5)": "grey",
			};
			const color = colors[data.issue_type];
			if (color) {
				value = `<span class="indicator-pill ${color}">${data.issue_type}</span>`;
			}
		}

		return value;
	},
};
