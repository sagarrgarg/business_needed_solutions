"""
Business Needed Solutions - Stock Value Conservation

On Repack and Manufacture, ERPNext freezes every incoming rate the user types (Set Basic Rate
Manually) and, when a later or backdated voucher reprices the outgoing side, posts
incoming - outgoing to the Stock Adjustment account. This module makes exactly one incoming line
the plug: it takes whatever value the outgoing side leaves after the fixed-rate lines, at submit
and again whenever Repost Item Valuation reprices the entry, so the entry never posts to Stock
Adjustment. Stock Reconciliation stays the one stock document that may.

Configuration lives on BNS Settings (Manufacturing tab, Stock Value Conservation section) and is
fail-closed: switched off, or no active rule for the company, or a posting date before the
Effective From date, means ERPNext behaves exactly as standard.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

# Stock Entry purpose -> the rule column that switches it on.
PURPOSE_FIELDS = {
	"Repack": "apply_to_repack",
	"Manufacture": "apply_to_manufacture",
}


def _settings():
	# get_cached_doc().get() returns None for a field that is not migrated yet, where
	# frappe.db.get_single_value would throw — so a half-migrated site stays off, not broken.
	return frappe.get_cached_doc("BNS Settings")


def get_active_rule(company, posting_date):
	"""The company's active rule, if conservation covers this posting date; otherwise None."""
	if not company or not posting_date:
		return None
	settings = _settings()
	if not cint(settings.get("enable_stock_value_conservation")):
		return None
	effective_from = settings.get("stock_value_conservation_effective_from")
	if not effective_from or getdate(posting_date) < getdate(effective_from):
		return None
	for row in settings.get("stock_value_conservation_rules") or []:
		if row.company == company and cint(row.is_active):
			return row
	return None


def is_conservation_active(stock_entry) -> bool:
	"""Whether the plug rule governs this Stock Entry."""
	field = PURPOSE_FIELDS.get(stock_entry.purpose)
	if not field:
		return False
	rule = get_active_rule(stock_entry.company, stock_entry.posting_date)
	return bool(rule and cint(rule.get(field)))


# The two opt-outs below are phrased so that their zero value is the strict one. A new field on
# a Single that already has rows never receives its JSON default (Document.load_from_db only
# builds defaults for a Single with no rows at all), so on every existing site these read as 0
# until somebody deliberately ticks them.


# Vouchers that have no business posting a net balance to Stock Adjustment. Material Issue and
# Material Receipt are deliberately absent: writing stock off or on against the Difference
# Account is their legitimate use. Stock Reconciliation is absent because it is the one stock
# document that is supposed to post there.
GUARDED_TRANSACTION_DOCTYPES = ("Purchase Receipt", "Purchase Invoice", "Sales Invoice", "Delivery Note")
GUARDED_TRANSFER_PURPOSES = ("Material Transfer",)


def is_adjustment_guard_active(doc) -> bool:
	"""Whether the no-net-Stock-Adjustment submit guard applies to this voucher.

	Repack/Manufacture under an active rule are always guarded; the transaction doctypes and
	Material Transfer only while the transaction guard has not been switched off.
	"""
	if get_active_rule(doc.company, doc.posting_date) is None:
		return False
	if doc.doctype == "Stock Entry":
		if doc.purpose in PURPOSE_FIELDS:
			# Guarded exactly when the plug governs it. A Manufacture with no outgoing rows is costed
			# from a paired Material Consumption entry: unbalanced on its own by design, so not guarded.
			return governs(doc)
		if doc.purpose not in GUARDED_TRANSFER_PURPOSES:
			return False
	elif doc.doctype not in GUARDED_TRANSACTION_DOCTYPES:
		return False
	return not cint(_settings().get("exclude_transactions_from_adjustment_guard"))


def requires_single_plug() -> bool:
	return not cint(_settings().get("allow_balanced_entries_without_plug"))


# ─── The plug ────────────────────────────────────────────────────────────────


def governs(stock_entry) -> bool:
	"""Whether the plug rule applies to this Stock Entry right now.

	A submitted entry keeps the method it was submitted under: the flag stamped at submit decides,
	not today's settings. Otherwise switching the feature off — or Effective From moving —
	would silently reprice already-conserved entries the next time a backdated voucher reposts them,
	and would leave their plug to ERPNext's fallback pricing.

	A Manufacture with no outgoing rows is left to ERPNext: its finished good is costed from a paired
	Material Consumption entry or from BOM rates, and there is nothing on this entry to conserve.
	"""
	if _is_submitted_record(stock_entry):
		return bool(cint(stock_entry.get("bns_value_conserved")))
	if not is_conservation_active(stock_entry):
		return False
	return any(_is_outgoing(d) for d in stock_entry.get("items"))


def _is_submitted_record(stock_entry) -> bool:
	"""Submitted or cancelled, and not in the middle of being submitted right now."""
	return cint(stock_entry.docstatus) >= 1 and getattr(stock_entry, "_action", None) != "submit"


def record_submit_snapshot(stock_entry) -> None:
	"""At submit, stamp whether conservation governs this entry and the rate of every incoming line.

	Called from validate once rates are final. The stamped rates are what a repost rescales from,
	so a rescale can never compound across the many recalculations one repost performs, and the
	typed rates come back if a later repost leaves the plug positive again.
	"""
	if getattr(stock_entry, "_action", None) != "submit":
		return
	conserved = governs(stock_entry)
	stock_entry.bns_value_conserved = 1 if conserved else 0
	for d in stock_entry.get("items"):
		d.bns_fixed_rate = flt(d.basic_rate) if conserved and _is_incoming(d) else 0.0


def _is_outgoing(row) -> bool:
	return bool(row.s_warehouse and not row.t_warehouse)


def _is_incoming(row) -> bool:
	# A row with both warehouses is a transfer inside the entry: value-neutral, never a plug.
	return bool(row.t_warehouse and not row.s_warehouse)


def _is_plug_candidate(stock_entry, row) -> bool:
	if not _is_incoming(row):
		return False
	if cint(row.set_basic_rate_manually) or cint(row.allow_zero_valuation_rate):
		return False
	# In a Manufacture only the finished good can be the plug. Scrap keeps the value ERPNext gives
	# it and counts as a fixed incoming line. Repack marks every incoming row as a finished good.
	return bool(cint(row.is_finished_item))


def get_plug_rows(stock_entry) -> list:
	"""Incoming rows eligible to take the balancing value. Valid entries have exactly one."""
	return [d for d in stock_entry.get("items") if _is_plug_candidate(stock_entry, d)]


def get_plug_row(stock_entry):
	plugs = get_plug_rows(stock_entry)
	return plugs[0] if len(plugs) == 1 else None


def _row_list(rows) -> str:
	return ", ".join(f"{frappe.bold(d.idx)} ({d.item_code})" for d in rows)


def prepare_conserved_entry(stock_entry) -> None:
	"""Validate-time setup for a governed entry. Replaces ERPNext's validate_repack_entry.

	ERPNext demands that every finished good of a multi-output Repack be typed by hand, which is
	exactly what freezes the incoming side. Here the rule is the opposite: one line — the plug —
	is left untyped and takes the balance.
	"""
	plugs = get_plug_rows(stock_entry)
	if len(plugs) > 1:
		frappe.throw(
			_(
				"Only one incoming line can take the balancing value, but rows {0} all have Set Basic Rate "
				"Manually unticked. Tick it on every line whose rate you know, and leave it unticked on the "
				"one line that should absorb whatever value remains."
			).format(_row_list(plugs)),
			title=_("More Than One Plug Line"),
		)
	if not plugs and requires_single_plug():
		frappe.throw(
			_(
				"Every incoming line has a rate typed by hand (or Allow Zero Valuation Rate), so nothing "
				"can absorb the difference between what goes in and what comes out, and it would be posted "
				"to Stock Adjustment. Untick Set Basic Rate Manually on the one line that should take the "
				"balancing value."
			),
			title=_("No Plug Line"),
		)

	# The difference between in and out is, by definition, a valuation adjustment. With every row on
	# the same Difference Account a conserved entry nets to zero there, and the submit guard can
	# check one account instead of guessing which one a row happened to default to.
	adjustment_account = frappe.get_cached_value("Company", stock_entry.company, "stock_adjustment_account")
	if adjustment_account:
		for d in stock_entry.get("items"):
			d.expense_account = adjustment_account


def apply_plug_rate(stock_entry, plug, in_recalculation: bool) -> None:
	"""Set the plug's basic rate to what the outgoing side leaves after the fixed incoming lines.

	plug basic = (sum outgoing basic - sum other incoming basic) / plug qty

	Additional costs are not in this formula: they are added on top of the plug's basic amount by
	distribute_additional_costs, and baking them in here would count them twice.
	"""
	outgoing = sum(flt(d.basic_amount) for d in stock_entry.get("items") if _is_outgoing(d))
	fixed = 0.0
	for d in stock_entry.get("items"):
		if not _is_incoming(d) or d is plug:
			continue
		if in_recalculation and cint(d.set_basic_rate_manually) and d.get("bns_fixed_rate"):
			# A typed rate is the one stamped at submit, even if an earlier repost rescaled this row.
			d.basic_rate = flt(d.bns_fixed_rate)
		# ERPNext skips manual rows entirely, so their basic_amount is whatever the client last sent.
		d.basic_amount = flt(flt(d.transfer_qty) * flt(d.basic_rate), d.precision("basic_amount"))
		fixed += flt(d.basic_amount)

	if plug is None:
		# No plug is only reachable with Allow Entries Without a Plug When They Balance switched on.
		if (
			not in_recalculation
			and stock_entry.docstatus == 1
			and abs(fixed - outgoing) > tolerance(stock_entry)
		):
			frappe.throw(
				_(
					"This entry has no plug line, so its typed values must balance on their own. Outgoing "
					"value is {0} and incoming value is {1}: a difference of {2} would be posted to Stock "
					"Adjustment."
				).format(
					_fmt(stock_entry, outgoing), _fmt(stock_entry, fixed), _fmt(stock_entry, fixed - outgoing)
				),
				title=_("Stock Value Not Conserved"),
			)
		return

	qty = flt(plug.transfer_qty)
	if qty <= 0:
		return  # ERPNext's own qty validation reports this

	rate = (outgoing - fixed) / qty
	# A negative plug is refused on save as well as submit: ERPNext's non-negative check on
	# basic_rate would refuse the save anyway, with a message that says nothing about why. Zero is
	# only refused at submit, so a draft can be saved before its outgoing lines are filled in.
	if not in_recalculation and (rate < 0 or (rate == 0 and stock_entry.docstatus == 1)):
		frappe.throw(
			_(
				"The other outgoing and incoming lines leave nothing for row {0} ({1}). Outgoing value is "
				"{2}, but the lines with typed rates already add up to {3}. Lower the typed rates by at "
				"least {4}."
			).format(
				frappe.bold(plug.idx),
				plug.item_code,
				_fmt(stock_entry, outgoing),
				_fmt(stock_entry, fixed),
				_fmt(stock_entry, fixed - outgoing),
			),
			title=_("Plug Line Would Be Zero or Negative"),
		)

	if rate <= 0 and in_recalculation:
		# A repost (or ERPNext's submit-time bundle recalculation) repriced the outgoing side below
		# what the typed lines are worth. Nothing may be thrown here: an exception inside a repost
		# rolls it back and marks it Failed for good.
		_handle_non_positive_plug_in_recalculation(stock_entry, plug, outgoing, fixed)
		return

	# Not rounded, like ERPNext's own basic_rate, to avoid precision loss.
	plug.basic_rate = rate
	plug.basic_amount = flt(qty * rate, plug.precision("basic_amount"))


def _handle_non_positive_plug_in_recalculation(stock_entry, plug, outgoing: float, fixed: float) -> None:
	"""
	Repack: rescale every incoming line in proportion to its value at submit, so the entry still
	conserves exactly and no line goes negative. The counter's price ratios between grades survive.

	Manufacture: floor the finished good at zero. Only the plug's ledger entry is re-rated on a
	Manufacture repost, so the other lines cannot be rescaled; the residual reaches Stock Adjustment
	and is logged as a data error to trace back to the backdated voucher that caused it.

	A Repack falls back to the Manufacture treatment when the rescale would not reach the ledger
	(see _rescale_reaches_ledger): rescaling a row whose ledger entry is never re-rated would leave
	the row and its ledger entry disagreeing, which is worse than a logged residual.
	"""
	if stock_entry.purpose == "Repack" and _rescale_reaches_ledger(stock_entry, plug):
		incoming = [d for d in stock_entry.get("items") if _is_incoming(d)]
		weight = sum(flt(d.transfer_qty) * flt(d.get("bns_fixed_rate")) for d in incoming)
		factor = outgoing / weight if outgoing > 0 and weight > 0 else 0.0
		for d in incoming:
			d.basic_rate = flt(d.get("bns_fixed_rate")) * factor
			d.basic_amount = flt(flt(d.transfer_qty) * d.basic_rate, d.precision("basic_amount"))
		_flag(
			stock_entry,
			"rescaled" if factor > 0 else "zero-valued",
			(
				f"A repost left {_fmt(stock_entry, outgoing)} of outgoing value against typed incoming lines "
				f"worth {_fmt(stock_entry, fixed)}, so the plug would have gone to zero or below. Every "
				f"incoming line was rescaled by {factor:.6f} from its rate at submit, so the entry still "
				"conserves value. Find the backdated voucher that repriced the outgoing items."
			),
		)
		if outgoing < 0:
			_flag(
				stock_entry,
				"negative-outgoing",
				f"The outgoing side is valued at {_fmt(stock_entry, outgoing)} (below zero), which cannot "
				"be conserved without negative incoming rates. The difference reaches Stock Adjustment.",
			)
		return

	# Typed lines are already back on their stamped rates: apply_plug_rate restores them first.
	plug.basic_rate = 0.0
	plug.basic_amount = 0.0
	_flag(
		stock_entry,
		"floored",
		(
			f"A repost left {_fmt(stock_entry, outgoing)} of outgoing value against fixed incoming lines "
			f"worth {_fmt(stock_entry, fixed)}. Row {plug.idx} ({plug.item_code}) was floored at zero, and "
			f"{_fmt(stock_entry, fixed - outgoing)} reaches Stock Adjustment. This is a data error: find "
			"the backdated voucher that repriced the raw materials."
		),
	)


def _rescale_reaches_ledger(stock_entry, plug) -> bool:
	"""Whether a repost that reprices ANY outgoing row re-rates EVERY incoming ledger entry.

	ERPNext re-queues a Repack's incoming entries only from an outgoing entry that carries a
	dependant (stock_ledger.py: repost_stock_ledgers -> include_dependant_sle_in_reposting), and it
	gives no dependant to an outgoing row with the same item and warehouse as the finished-item
	row — here the plug (stock_entry.py: get_sle_for_source_warehouse). That is the common
	"H-MAX in, HG-15 and leftover H-MAX out" shape: a backdated H-MAX voucher then re-rates the
	plug (same item and warehouse, so already in the chain) but never the HG-15 entry.
	"""
	return all(
		(d.item_code, d.s_warehouse) != (plug.item_code, plug.t_warehouse)
		for d in stock_entry.get("items")
		if _is_outgoing(d)
	)


def _flag(stock_entry, kind: str, message: str) -> None:
	"""Record a repost-time decision in the Error Log, once per entry and kind per job.

	One repost recalculates the same entry many times; the log should say it once. Never raises:
	this runs inside Repost Item Valuation.
	"""
	try:
		seen = getattr(frappe.local, "bns_svc_flagged", None)
		if seen is None:
			seen = frappe.local.bns_svc_flagged = set()
		key = (stock_entry.name, kind)
		if key in seen:
			return
		seen.add(key)
		title = f"BNS stock value conservation: {kind} {stock_entry.name}"
		if frappe.db.exists("Error Log", {"method": title}):
			return  # said already, by an earlier repost of the same entry
		frappe.log_error(
			title=title,
			message=message,
			reference_doctype="Stock Entry",
			reference_name=stock_entry.name,
		)
	except Exception:
		pass


def put_additional_costs_on_plug(stock_entry, plug) -> None:
	"""All additional cost goes to the plug; lines with typed rates keep exactly the rate typed.

	ERPNext spreads additional cost over every finished good by basic amount. For a line whose rate
	was typed that would move its valuation away from the typed rate — and on Manufacture, where
	repost re-rates only the plug's ledger entry, a later change to that share would leave the
	other lines' ledger entries stale and post the difference to Stock Adjustment.
	"""
	total = flt(stock_entry.total_additional_costs)
	for d in stock_entry.get("items"):
		d.additional_cost = total if d is plug else 0.0


def tolerance(stock_entry) -> float:
	"""A paisa per row. Every row's value is rounded to currency precision separately."""
	return 0.01 * max(1, len(stock_entry.get("items") or []))


def _fmt(doc, value) -> str:
	from frappe.utils import fmt_money

	return fmt_money(value, currency=frappe.get_cached_value("Company", doc.company, "default_currency"))


# ─── Submit guard: no net Stock Adjustment ────────────────────────────────────

# On a BNS internal transfer, branch accounting rewrites the GL and its Phase-1 balancer falls back
# to Stock Adjustment when no row carries an expense account. That is branch accounting's own
# design, governed by its cutoffs, and this guard does not second-guess it.
_INTERNAL_FLAG = {
	"Sales Invoice": "is_bns_internal_customer",
	"Delivery Note": "is_bns_internal_customer",
	"Purchase Invoice": "is_bns_internal_supplier",
	"Purchase Receipt": "is_bns_internal_supplier",
}


def guard_stock_adjustment(doc, method=None) -> None:
	"""on_submit doc_event: refuse a voucher that leaves a net balance on Stock Adjustment.

	Runs after the controller's own on_submit, so the voucher's GL already exists and a throw rolls
	the whole submit back. Does not run during Repost Item Valuation, which never fires doc_events;
	the repost side is covered by the plug itself and by the post-repost check.
	"""
	if not is_adjustment_guard_active(doc):
		return
	flag = _INTERNAL_FLAG.get(doc.doctype)
	if flag and cint(doc.get(flag)):
		return
	# Counter repack backfill posts onto a ledger it reposts only once, at the end, so values at
	# submit are provisional; it checks Stock Adjustment on every entry after that repost instead.
	if doc.flags.get("bns_counter_repack_backfill"):
		return
	account = frappe.get_cached_value("Company", doc.company, "stock_adjustment_account")
	if not account:
		return

	net = _net_on_account(doc.doctype, doc.name, account)
	if doc.doctype == "Stock Entry":
		from erpnext.controllers.stock_controller import repost_required_for_queue

		# The same item leaving the same warehouse on two rows under FIFO/LIFO: ERPNext knowingly posts
		# estimated values at submit and queues a repost to correct them. The post-repost check sees
		# the corrected figures; judging the estimates here would block a legitimate entry.
		if repost_required_for_queue(doc):
			return

	if abs(net) <= tolerance(doc):
		return

	frappe.throw(
		_(
			"{0} {1} would leave {2} on the Stock Adjustment account {3}. Only Stock Reconciliation may "
			"post there.{4}"
		).format(
			_(doc.doctype),
			frappe.bold(doc.name),
			frappe.bold(_fmt(doc, net)),
			frappe.bold(account),
			_explain(doc, account),
		),
		title=_("Stock Adjustment Not Allowed"),
	)


def _net_on_account(voucher_type: str, voucher_no: str, account: str) -> float:
	"""Debit minus credit on one account for one voucher. No row means the entries netted to zero."""
	result = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(debit - credit), 0)
		FROM `tabGL Entry`
		WHERE voucher_type = %s AND voucher_no = %s AND account = %s AND is_cancelled = 0
		""",
		(voucher_type, voucher_no, account),
	)
	return flt(result[0][0]) if result else 0.0


def negative_stock_fills(stock_entry, account: str) -> list:
	"""Rows of a Stock Entry that received into stock at or below zero, with the revaluation that caused.

	Receiving into a negative (or zero-qty, non-zero-value) balance revalues what was issued before
	it existed: the ledger's stock value difference is not qty x rate, and the gap lands on the row's
	Difference Account. That is not exempt from the guard — a negative balance is itself the thing to
	fix — but the message has to say so, or the user hunts for a typed rate that is not wrong.
	"""
	rows = frappe.db.sql(
		"""
		SELECT sed.idx, sle.item_code, sle.stock_value_difference, sle.actual_qty, sle.incoming_rate,
			sle.qty_after_transaction
		FROM `tabStock Ledger Entry` sle
		INNER JOIN `tabStock Entry Detail` sed ON sed.name = sle.voucher_detail_no
		WHERE sle.voucher_type = 'Stock Entry' AND sle.voucher_no = %s AND sle.is_cancelled = 0
			AND sle.actual_qty > 0 AND sed.expense_account = %s
		""",
		(stock_entry.name, account),
		as_dict=True,
	)
	fills = []
	for r in rows:
		if flt(r.qty_after_transaction) - flt(r.actual_qty) > 0:
			continue
		revaluation = flt(r.stock_value_difference) - flt(r.actual_qty) * flt(r.incoming_rate)
		if abs(revaluation) > 0.01:
			fills.append(frappe._dict(idx=r.idx, item_code=r.item_code, revaluation=revaluation))
	return fills


def _explain(doc, account: str) -> str:
	"""Point at the configuration that routed value to Stock Adjustment."""
	if doc.doctype == "Stock Entry":
		fills = negative_stock_fills(doc, account)
		if fills:
			return "<br><br>" + _(
				"These rows received into stock that was already negative: {0}. Receiving revalues stock "
				"that was issued before it existed, and that revaluation lands on Stock Adjustment. Clear "
				"the negative balance first, then submit this entry."
			).format(
				"; ".join(
					_("row {0} ({1}), revaluation {2}").format(f.idx, f.item_code, _fmt(doc, f.revaluation))
					for f in fills
				)
			)
		if governs(doc):
			return "<br><br>" + _(
				"This entry is conserved by BNS, so its plug line should have balanced it. Check for "
				"additional costs booked to Stock Adjustment itself, or rows with Allow Zero Valuation Rate."
			)
		return "<br><br>" + _(
			"A transfer should move value unchanged. Check additional costs on rows whose value is zero."
		)
	rows = [d.idx for d in doc.get("items") or [] if d.get("expense_account") == account]
	hints = []
	if rows:
		hints.append(_("Rows {0} use it as their expense account.").format(", ".join(str(i) for i in rows)))
	for field, label in (
		("default_expense_account", _("Default Cost of Goods Sold Account")),
		("round_off_account", _("Round Off Account")),
	):
		if frappe.get_cached_value("Company", doc.company, field) == account:
			hints.append(_("It is the Company's {0}.").format(label))
	return ("<br><br>" + " ".join(hints)) if hints else ""


# ─── After a repost ───────────────────────────────────────────────────────────


def verify_after_repost(doc, method=None) -> None:
	"""Repost Item Valuation on_change: after a completed repost, check every conserved Stock Entry
	it touched and log any that still carry a Stock Adjustment balance.

	Read-only and exception-proof. on_change fires from db_set inside ERPNext's repost(), where an
	escaping exception rolls the repost back and marks it Failed for good. Logs go to the Error Log
	(frappe.log_error), which is where somebody will look; the std-lib logger reaches nobody.
	"""
	try:
		_verify_after_repost(doc)
	except Exception:
		try:
			frappe.log_error(
				title=f"BNS stock value conservation: post-repost check failed {doc.name}",
				reference_doctype="Repost Item Valuation",
				reference_name=doc.name,
			)
		except Exception:
			pass


def _verify_after_repost(riv) -> None:
	# on_change fires for In Progress and twice for Completed; the first Completed call is the one
	# that still has reposting_data_file, which lists the vouchers affected through dependants.
	if cint(riv.docstatus) != 1 or riv.status != "Completed":
		return
	if not frappe.db.has_column("Stock Entry", "bns_value_conserved"):
		return
	cache_key = f"bns_svc_repost_checked:{riv.name}"
	if frappe.cache.get_value(cache_key):
		return
	frappe.cache.set_value(cache_key, 1, expires_in_sec=86400)

	account = frappe.get_cached_value("Company", riv.company, "stock_adjustment_account")
	if not account:
		return

	from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import (
		_get_directly_dependent_vouchers,
	)
	from erpnext.stock.stock_ledger import get_affected_transactions

	# Exactly the set ERPNext just reposted GL for (repost_item_valuation.repost_gl_entries).
	touched = set(_get_directly_dependent_vouchers(riv)) | set(get_affected_transactions(riv))
	names = sorted({voucher_no for voucher_type, voucher_no in touched if voucher_type == "Stock Entry"})
	if not names:
		return
	# frappe.db.sql rather than frappe.get_all: confidential_app filters Stock Entry lists in web
	# contexts even with ignore_permissions, and a hidden entry would be a silently skipped check.
	conserved = frappe.db.sql_list(
		"""SELECT name FROM `tabStock Entry` WHERE name IN %s AND docstatus = 1 AND bns_value_conserved = 1""",
		(tuple(names),),
	)

	leaks = []
	for name in conserved:
		stub = frappe._dict(name=name, items=[None] * frappe.db.count("Stock Entry Detail", {"parent": name}))
		net = _net_on_account("Stock Entry", name, account)
		if abs(net) > tolerance(stub):
			fill = sum(f.revaluation for f in negative_stock_fills(stub, account))
			leaks.append(
				f"{name}: {flt(net, 2)}" + (f" (negative-stock fill: {flt(fill, 2)})" if fill else "")
			)
	if not leaks:
		return

	# on_change reports Completed more than once per repost (set_status, the data-file db_set, and in
	# tests the RIV's own submit), and a process-wide cache.clear can drop the key above. Error Log is
	# MyISAM — written at once, never rolled back — so an existing row is a reliable "already said".
	title = f"BNS stock value conservation: Stock Adjustment after repost {riv.name}"
	if frappe.db.exists("Error Log", {"method": title}):
		return
	pending = frappe.db.count(
		"Repost Item Valuation",
		{"company": riv.company, "docstatus": 1, "status": ("in", ("Queued", "In Progress"))},
	)
	frappe.log_error(
		title=title,
		message=(
			f"Repost {riv.name} ({riv.based_on}: {riv.voucher_no or riv.item_code}, from {riv.posting_date}) "
			f"left a balance on {account} for conserved Stock Entries:\n"
			+ "\n".join(leaks)
			+ (
				f"\n\n{pending} other repost(s) for this company are still queued; an entry priced from "
				"several items can be mid-way until they finish. Re-check after they complete."
				if pending
				else ""
			)
			+ "\nA 'floored' entry in the Error Log for the same Stock Entry explains a residual on purpose."
		),
		reference_doctype="Repost Item Valuation",
		reference_name=riv.name,
	)
