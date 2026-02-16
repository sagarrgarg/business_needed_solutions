// FSSAI License No.: hidden by default, shown only when linked Company has Is a Food Company

frappe.ui.form.on("Address", {
	refresh(frm) {
		bns_toggle_fssai(frm);
	},
	is_your_company_address(frm) {
		bns_toggle_fssai(frm);
	},
});

function bns_toggle_fssai(frm) {
	if (!frm.fields_dict.bns_fssai_license_no) return;

	frm.set_df_property("bns_fssai_license_no", "hidden", 1);

	if (!frm.doc.is_your_company_address) return;

	const companyRow = (frm.doc.links || []).find(
		(r) => r.link_doctype === "Company" && r.link_name
	);
	if (!companyRow) return;

	frappe.db.get_value(
		"Company",
		companyRow.link_name,
		"bns_is_food_company",
		(r) => {
			if (r && r.bns_is_food_company) {
				frm.set_df_property("bns_fssai_license_no", "hidden", 0);
			}
		}
	);
}
