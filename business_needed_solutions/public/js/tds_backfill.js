// TDS on submitted Purchase Invoices: the shared preview dialog, and the
// "Change TDS Category" button on a submitted Purchase Invoice of the current
// fiscal year. Server side: overrides/tds_backfill.py. Every change is previewed;
// applying needs the preview's token, so nothing is written that was not shown.
frappe.provide("bns_tds");

const BNS_TDS = "business_needed_solutions.business_needed_solutions.overrides.tds_backfill.";

bns_tds.fmt = function (v) {
	return format_currency(flt(v), "INR");
};

bns_tds.esc = function (v) {
	return frappe.utils.escape_html(v === undefined || v === null ? "" : String(v));
};

bns_tds.render_preview = function (p) {
	const esc = bns_tds.esc;
	const fmt = bns_tds.fmt;
	const s = p.summary || {};
	let html = `<div class="bns-tds-preview" style="font-size: var(--text-sm);">`;
	html += `<p>${__("TDS changes on {0} invoice(s): {1} → {2}.", [s.ledger_changes || 0, fmt(s.tds_before), "<b>" + fmt(s.tds_after) + "</b>"])}`;
	if (s.flag_changes) html += ` ${__("{0} more only get their TDS category set (nothing due on them; no ledger change).", [s.flag_changes])}`;
	if (s.blocked) html += ` <span class="text-danger">${__("{0} cannot be changed (see below).", [s.blocked])}</span>`;
	if (flt(s.late_interest) > 0) html += `<br><span class="text-warning">${__("Interest for late deduction, roughly {0} (1% a month from the invoice date).", [fmt(s.late_interest)])}</span>`;
	html += `</p>`;
	if (p.filed_upto) html += `<p class="text-muted">${__("TDS returns filed up to {0} (BNS Settings).", [esc(frappe.datetime.str_to_user(p.filed_upto))])}</p>`;

	(p.plans || []).forEach(function (plan) {
		html += `<h6 class="mt-3">${esc(plan.supplier_name)} <span class="text-muted">· ${esc(plan.company)} · ${esc(frappe.datetime.str_to_user(plan.fiscal_year_start))} – ${esc(frappe.datetime.str_to_user(plan.fiscal_year_end))} · ${__("TDS for the year after this")}: ${fmt(plan.year_tds)}</span></h6>`;
		const notes = (plan.problems || []).map((x) => `<li class="text-danger">${esc(x)}</li>`)
			.concat((plan.warnings || []).map((x) => `<li class="text-warning">${esc(x)}</li>`));
		if (notes.length) html += `<ul>${notes.join("")}</ul>`;
		const flag_rows = (plan.rows || []).filter((x) => x.action === "flags" && !x.blocked);
		const rows = (plan.rows || []).filter((x) => !(x.action === "flags" && !x.blocked));
		if (flag_rows.length) {
			html += `<p class="text-muted small">${__("Category set only, no TDS due and no ledger change ({0}):", [flag_rows.length])} `
				+ flag_rows.map((x) => `<a href="/app/purchase-invoice/${encodeURIComponent(x.name)}" target="_blank">${esc(x.name)}</a>`).join(", ") + `</p>`;
		}
		if (!rows.length) {
			if (!flag_rows.length) html += `<p class="text-success">${__("Nothing to change.")}</p>`;
			return;
		}
		html += `<div style="overflow-x:auto"><table class="table table-sm table-bordered"><thead><tr>
			<th>${__("Invoice")}</th><th>${__("Date")}</th><th>${__("Category")}</th>
			<th class="text-right">${__("TDS now")}</th><th class="text-right">${__("TDS after")}</th>
			<th>${__("Account")}</th><th>${__("Late")}</th><th class="text-right">${__("Challans that month")}</th><th>${__("Status")}</th>
		</tr></thead><tbody>`;
		rows.forEach(function (r) {
			const cat = (r.current_category || "—") === (r.category || "—") || r.action === "none"
				? esc(r.category || "—")
				: `<span class="text-danger">${esc(r.current_category || "—")}</span> → <span class="text-success">${esc(r.category || "—")}</span>`;
			const accounts = (r.current_accounts || []).join(", ");
			const account = r.target_account && accounts && accounts !== r.target_account
				? `<span class="text-danger">${esc(accounts)}</span> → <span class="text-success">${esc(r.target_account)}</span>`
				: esc(r.target_account || accounts || "");
			let status;
			if (r.blocked) status = `<span class="text-danger">${esc(r.blocked)}</span>`;
			else if (r.action === "flags") status = `<span class="text-muted">${__("Category fields only, no ledger change")}</span>`;
			else if (r.action === "ledger") status = `<span class="text-success">${__("Change")}</span>`;
			else status = "";
			(r.caps || []).forEach(function (c) {
				status += `<br><small class="text-warning">${__("{0} {1}: allocation {2} → {3}", [esc(c.voucher_type), esc(c.voucher_no), fmt(c.allocated), fmt(c.new_allocated)])}</small>`;
			});
			const late = r.months_late ? `${__("{0} mo", [r.months_late])}<br><small>${fmt(r.late_interest)}</small>` : "";
			html += `<tr>
				<td><a href="/app/purchase-invoice/${encodeURIComponent(r.name)}" target="_blank">${esc(r.name)}</a>${r.is_return ? ` <span class="badge badge-secondary">${__("Return")}</span>` : ""}</td>
				<td>${esc(frappe.datetime.str_to_user(r.posting_date))}${r.quarter ? `<br><small>${esc(r.quarter)}${r.filed ? " · " + __("filed") : ""}</small>` : ""}</td>
				<td><small>${cat}</small></td>
				<td class="text-right">${fmt(r.current_tds)}</td>
				<td class="text-right"><b>${fmt(r.target_tds)}</b></td>
				<td><small>${account}</small></td>
				<td><small>${late}</small></td>
				<td class="text-right">${r.action === "ledger" ? fmt(r.challans) : ""}</td>
				<td><small>${status}</small></td>
			</tr>`;
		});
		html += `</tbody></table></div>`;
	});

	if (p.challans && p.challans.length) {
		html += `<h6 class="mt-3 text-danger">${__("Challans still on the old TDS account ({0})", [fmt(p.challan_amount)])}</h6>`;
		html += `<p>${__("Re-mapping moves the invoices only. Until these payments are moved too (cancel and amend each with the new account, same date, amount and bank reference), the old account keeps a debit balance and the new one a credit.")}</p><ul>`;
		p.challans.forEach(function (c) {
			html += `<li>${esc(c.voucher_type)} <a href="/app/${frappe.router.slug(c.voucher_type)}/${encodeURIComponent(c.voucher_no)}" target="_blank">${esc(c.voucher_no)}</a> · ${esc(frappe.datetime.str_to_user(c.posting_date))} · ${esc(c.account)} · ${fmt(c.amount)}</li>`;
		});
		html += `</ul>`;
	}
	if (p.skipped && p.skipped.length) {
		html += `<h6 class="mt-3">${__("Not included")}</h6><ul>` + p.skipped.map((x) => `<li>${esc(x.purchase_invoice)}: ${esc(x.reason)}</li>`).join("") + `</ul>`;
	}
	html += `</div>`;
	return html;
};

bns_tds.summary_html = function (s) {
	const esc = bns_tds.esc;
	const fmt = bns_tds.fmt;
	s = s || {};
	let msg = __("{0} invoice(s) changed: TDS {1} → {2}.", [s.changed || 0, fmt(s.tds_before), fmt(s.tds_after)]);
	if (s.flagged) msg += "<br>" + __("{0} invoice(s) had only their category fields set.", [s.flagged]);
	(s.payments_cut || []).forEach(function (c) {
		msg += "<br>" + __("{0} {1}: allocation {2} → {3}", [esc(c.voucher_type), esc(c.voucher_no), fmt(c.allocated), fmt(c.new_allocated)]);
	});
	if ((s.skipped || []).length) {
		msg += "<br><br>" + __("Not changed:") + "<br>" + s.skipped.slice(0, 20).map((x) => esc(x.purchase_invoice + ": " + x.reason)).join("<br>");
	}
	if (s.error_count) {
		msg += "<br><br><span class='text-danger'>" + __("Stopped at an error; later invoices of that supplier were left as they were:") + "</span><br>"
			+ (s.errors || []).slice(0, 10).map((e) => esc(e.purchase_invoice + ": " + e.error)).join("<br>");
	}
	if (s.remaining && !s.remaining.done) {
		msg += "<br><br><span class='text-danger'>" + __("Not done: {0} challan(s) worth {1} are still on the old TDS account. Move them by hand.", [(s.remaining.challans || []).length, fmt(s.remaining.challan_amount)]) + "</span>";
	}
	return msg;
};

bns_tds.show_summary = function (s, title) {
	frappe.msgprint({
		title: title || __("TDS changes applied"),
		message: bns_tds.summary_html(s),
		indicator: (s && s.error_count) || (s && s.remaining && !s.remaining.done) ? "orange" : "green",
	});
};

// opts: title, preview_method, apply_method, args, on_done
bns_tds.open_preview = function (opts) {
	let allow_filed = 0;
	let dialog = null;
	let preview = null;

	const load = function () {
		frappe.call({
			method: opts.preview_method,
			args: Object.assign({}, opts.args, { allow_filed: allow_filed }),
			freeze: true,
			freeze_message: __("Working out TDS for the year..."),
			callback: function (r) {
				preview = r.message || {};
				show();
			},
		});
	};

	const show = function () {
		const s = preview.summary || {};
		const filed_blocked = (preview.plans || []).some((p) => (p.rows || []).some((x) => x.filed && x.blocked));
		if (!dialog) {
			dialog = new frappe.ui.Dialog({
				title: opts.title,
				size: "extra-large",
				fields: [
					{ fieldtype: "HTML", fieldname: "body" },
					{
						fieldtype: "Check", fieldname: "allow_filed",
						label: __("Also change invoices in quarters already filed (System Manager)"),
						hidden: 1,
						change: function () {
							allow_filed = dialog.get_value("allow_filed") ? 1 : 0;
							load();
						},
					},
				],
				primary_action_label: __("Apply"),
				primary_action: function () { apply(); },
			});
		}
		dialog.fields_dict.body.$wrapper.html(bns_tds.render_preview(preview));
		dialog.set_df_property("allow_filed", "hidden", preview.can_override_filed && (filed_blocked || allow_filed) ? 0 : 1);
		dialog.get_primary_btn().prop("disabled", !(s.changes > 0));
		dialog.show();
	};

	const apply = function () {
		const s = preview.summary || {};
		frappe.confirm(
			__("Change TDS on {0} submitted invoice(s) and set the category on {1} more? Each changed invoice's ledger is rebuilt from the invoice, and every change is logged on the invoice.", [s.ledger_changes || 0, s.flag_changes || 0]),
			function () {
				frappe.call({
					method: opts.apply_method,
					args: Object.assign({}, opts.args, { token: preview.token, allow_filed: allow_filed }),
					freeze: true,
					freeze_message: __("Applying TDS..."),
					callback: function (r) {
						dialog.hide();
						const m = r.message || {};
						if (m.status === "queued") {
							frappe.show_alert({ message: __("{0} invoice changes queued. You will get a message when they finish.", [m.count]), indicator: "blue" }, 8);
						} else {
							bns_tds.show_summary(m.summary || m);
						}
						if (opts.on_done) opts.on_done(m);
					},
				});
			}
		);
	};

	load();
};

if (!bns_tds._realtime_bound) {
	bns_tds._realtime_bound = true;
	frappe.realtime.on("bns_tds_apply_complete", function (s) {
		bns_tds.show_summary(s);
	});
}

bns_tds.add_category_button = function (frm) {
	if (frm.doc.docstatus !== 1) return;
	frappe.call({
		method: BNS_TDS + "get_tds_category_button",
		args: { name: frm.doc.name },
		callback: function (r) {
			const state = r.message || {};
			if (!state.show) return;
			frm.add_custom_button(__("Change TDS Category"), function () {
				const d = new frappe.ui.Dialog({
					title: __("Change TDS Category — {0}", [frm.doc.name]),
					fields: [
						{
							fieldtype: "Link", fieldname: "category", options: "Tax Withholding Category",
							label: __("TDS Category"),
							default: state.current_category || state.supplier_category || "",
							description: (state.follows
								? __("This debit note takes the TDS category of {0}, the invoice it returns, so the change is made on {0}; the preview shows both. Its own TDS amount is not changed.", [state.follows]) + " "
								: state.is_return ? __("A debit note's own TDS amount is not changed; it lowers the TDS of later invoices.") + " " : "")
								+ __("Leave empty to take TDS off. Now: {0}. Supplier: {1}.", [
									state.current_category || __("none"), state.supplier_category || __("none"),
								]),
						},
					],
					primary_action_label: __("Preview"),
					primary_action: function (values) {
						d.hide();
						bns_tds.open_preview({
							title: __("TDS Category for {0}: preview", [frm.doc.name]),
							preview_method: BNS_TDS + "preview_tds_category_change",
							apply_method: BNS_TDS + "apply_tds_category_change",
							args: { name: frm.doc.name, category: values.category || "" },
							on_done: function () { frm.reload_doc(); },
						});
					},
				});
				d.show();
			}, __("Actions"));
		},
	});
};

frappe.ui.form.on("Purchase Invoice", {
	refresh: function (frm) {
		bns_tds.add_category_button(frm);
	},
});
