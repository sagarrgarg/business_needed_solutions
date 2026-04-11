// Warn the accountant when a Payment Entry or Journal Entry selects a party
// that has a Party Link with an opposite-signed outstanding on the counter-party.
// Purely a nudge — never blocks save/submit. Toggled by BNS Settings
// `common_party_warning_on_wrong_side`.
//
// Payment Entry: single party on the header (frm.doc.party / party_type).
// Journal Entry: party lives on each accounts child row (Journal Entry Account).

frappe.ui.form.on("Payment Entry", {
	party: function (frm) {
		bns_check_header_crossed(frm);
	},
	party_type: function (frm) {
		if (frm.doc.party) bns_check_header_crossed(frm);
	},
	company: function (frm) {
		if (frm.doc.party) bns_check_header_crossed(frm);
	},
});

frappe.ui.form.on("Journal Entry Account", {
	party: function (frm, cdt, cdn) {
		bns_check_row_crossed(frm, cdt, cdn);
	},
	party_type: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row && row.party) bns_check_row_crossed(frm, cdt, cdn);
	},
});

frappe.ui.form.on("Journal Entry", {
	company: function (frm) {
		// Recheck every populated party row when company changes.
		(frm.doc.accounts || []).forEach(function (row) {
			if (row.party_type && row.party) {
				bns_check_row_crossed(frm, row.doctype, row.name);
			}
		});
	},
});

function bns_check_header_crossed(frm) {
	if (!frm.doc.party || !frm.doc.party_type || !frm.doc.company) return;
	const key = `${frm.doc.party_type}|${frm.doc.party}|${frm.doc.company}`;
	if (frm.__bns_last_crossed_check === key) return;
	frm.__bns_last_crossed_check = key;
	bns_call_and_warn({
		party_type: frm.doc.party_type,
		party: frm.doc.party,
		company: frm.doc.company,
		row_label: "",
	});
}

function bns_check_row_crossed(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row || !row.party || !row.party_type || !frm.doc.company) return;
	const key = `${row.party_type}|${row.party}|${frm.doc.company}|${cdn}`;
	frm.__bns_row_crossed = frm.__bns_row_crossed || {};
	if (frm.__bns_row_crossed[cdn] === key) return;
	frm.__bns_row_crossed[cdn] = key;
	bns_call_and_warn({
		party_type: row.party_type,
		party: row.party,
		company: frm.doc.company,
		row_label: __("Row #{0}", [row.idx]),
	});
}

function bns_call_and_warn(args) {
	frappe.call({
		method:
			"business_needed_solutions.bns_branch_accounting.common_party_squareoff.check_linked_party_opposite_balance",
		args: {
			party_type: args.party_type,
			party: args.party,
			company: args.company,
		},
		callback: function (r) {
			const res = r.message;
			if (!res || !res.has_crossed) return;
			const amount = format_currency(res.square_off_amount);
			const prefix = args.row_label ? args.row_label + ": " : "";
			const msg = __(
				"{0}Linked {1} <b>{2}</b> has an open outstanding of <b>{3}</b> on the opposite side (via Party Link). " +
					"Posting here without using the linked counter-party will leave both Debtors and Creditors inflated on the Balance Sheet. " +
					"Double-check the party, or use BNS Dashboard \u2192 Linked Party Square-Off to reconcile.",
				[prefix, res.linked_party_type, res.linked_party, amount]
			);
			frappe.msgprint({
				title: __("Linked Party Has Opposite Outstanding"),
				message: msg,
				indicator: "orange",
			});
		},
	});
}
