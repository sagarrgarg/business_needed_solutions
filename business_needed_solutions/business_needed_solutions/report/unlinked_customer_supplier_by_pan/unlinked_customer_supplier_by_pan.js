// Copyright (c) 2025, Sagar Ratan Garg and contributors
// For license information, please see license.txt

frappe.query_reports["Unlinked Customer-Supplier by PAN"] = {
	"filters": [

	]
};


async function createPartyLink(primaryParty, secondaryParty, primaryRole, secondaryRole) {
    const apiUrl = "/api/method/erpnext.accounts.doctype.party_link.party_link.create_party_link";

    const payload = {
        primary_party: primaryParty,
        secondary_party: secondaryParty,
        primary_role: primaryRole,
        secondary_role: secondaryRole
    };

    try {
        const response = await fetch(apiUrl, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Frappe-CSRF-Token": frappe.csrf_token // Important for security
            },
            body: JSON.stringify(payload)
        });

        const result = await response.json();

        if (response.ok && result.message) {
            frappe.msgprint({
                title: __('Success'),
                indicator: 'green',
                message: `Party Link Created Successfully: ${result.message}`
            });
        } else {
            frappe.msgprint({
                title: __('Error'),
                indicator: 'red',
                message: result.exc || "Failed to create Party Link."
            });
        }
    } catch (error) {
        frappe.msgprint({
            title: __('API Error'),
            indicator: 'red',
            message: `Error: ${error.message}`
        });
    }
}
