"""
Backfill counter repacks for stock that was sold before Repack from Bulk existed.

A one-off cleanup tool, run from the console or `bench execute`, one warehouse at a time:

	bench --site <site> execute business_needed_solutions.bns_counter_repack.backfill.run \
		--kwargs "{'company': '...', 'warehouse': '...', 'from_date': '2025-04-01', 'dry_run': 1}"

It walks the warehouse's stock ledger from from_date in posting order and keeps, in memory, the
quantity of every bulk lot and every sold grade that has an active Counter Repack Rule. Then:

- Opening stock of a grade on from_date is folded into its bulk lot (grade out, lot in as plug).
- A return of a grade (credit note / returned delivery note) is folded into the lot the same way,
  at the return's own posting time, so the grade never sits on stock it did not buy.
- A sale (Sales Invoice with Update Stock, or Delivery Note) of a grade gets a counter repack one
  millisecond before it, for whatever the grade is short of: the whole lot out, the shortfall in at
  the rule's margin cost, the rest of the lot back as the plug. Stock the grade holds from other
  receipts (an internal purchase, say) is used first.

Everything is posted with the ledger as it stands, and the whole warehouse is reposted once at the
end: the plug (Stock Value Conservation) and the typed grade rates make the final values exact
whatever the interim rates were. The repost jobs that each backdated entry queues are skipped in
favour of that single pass.

Stock Value Conservation must be active for Repack on from_date, and the bulk item must use Moving
Average, as for counter repack at the till.
"""

import datetime
import json

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime

from business_needed_solutions.bns_counter_repack import counter_repack as cr
from business_needed_solutions.business_needed_solutions.overrides import stock_value_conservation as svc

TOLERANCE = 0.0005
BEFORE_SALE = datetime.timedelta(milliseconds=1)


def run(
	company: str,
	warehouse: str,
	from_date: str,
	dry_run: int = 1,
	log_path: str | None = None,
	to_date: str | None = None,
	fold_receipts_of: list | None = None,
):
	rules = _rules(company, from_date)
	if not rules:
		frappe.throw(_("No active Counter Repack Rules for {0} on {1}.").format(company, from_date))
	rule = svc.get_active_rule(company, from_date)
	if not rule or not cint(rule.get("apply_to_repack")):
		frappe.throw(_("Stock Value Conservation is not active for Repack on {0}.").format(from_date))

	actions, final = plan(company, warehouse, from_date, rules, to_date, fold_receipts_of)
	summary = _summary(actions, final)
	if cint(dry_run) or summary["refusals"]:
		return summary

	started = now_datetime()
	done = post(company, warehouse, actions)
	skipped = _skip_queued_reposts(started)
	# every grade a repack feeds, not just the first: a multi-grade repack leaves the others stale
	items = sorted(
		{a["item"] for a in actions}
		| {line["item"] for a in actions if a["kind"] == "repack" for line in a["lines"]}
		| {r.bulk_item for r in rules.values()}
	)
	failed = repost(company, warehouse, from_date, items)
	parked = _skip_queued_reposts(started)
	summary.update(
		posted=done,
		auto_reposts_skipped=skipped,
		repost_failed=failed,
		cascade_parked=parked,
		stock_adjustment_left=verify(company),
	)
	if log_path:
		with open(log_path, "w") as f:
			json.dump({"summary": summary, "actions": actions}, f, default=str, indent=1)
	return summary


def _rules(company: str, from_date) -> dict:
	"""sold item -> rule effective on from_date. Rules that start later are out of scope."""
	out = {}
	for name in frappe.get_all(
		"BNS Counter Repack Rule", filters={"company": company, "disabled": 0}, pluck="sold_item"
	):
		rule = cr.get_rule(company, name, from_date)
		if rule:
			out[name] = rule
	return out


def plan(company: str, warehouse: str, from_date, rules: dict, to_date=None, fold_receipts_of=None):
	"""Walk the ledger from from_date (to the end of to_date, when given) and decide every fold and
	repack. Returns (actions, final positions)."""
	bulk_items = sorted({r.bulk_item for r in rules.values()})
	# Items whose receipts join the lot on arrival: an internal branch transfer keeps the sending
	# branch's item code on the invoice, but the goods are part of the same bulk stock here.
	folded = {i: bulk_items[0] for i in (fold_receipts_of or []) if i not in bulk_items}
	items = sorted(set(rules) | set(bulk_items) | set(folded))
	start = get_datetime(f"{from_date} 00:00:00")

	pos = {}
	for item in items:
		sle = frappe.db.sql(
			"""select qty_after_transaction q, stock_value v from `tabStock Ledger Entry`
			where is_cancelled=0 and item_code=%s and warehouse=%s and posting_datetime<%s
			order by posting_datetime desc, creation desc limit 1""",
			(item, warehouse, start),
			as_dict=True,
		)
		pos[item] = frappe._dict(qty=flt(sle[0].q) if sle else 0.0, value=flt(sle[0].v) if sle else 0.0)

	# Resumable: entries an earlier run posted are already in the ledger walked below. A posted
	# repack shows up as grade stock, so the sale it fed needs no new one; a posted fold is matched
	# by its remarks and not planned (or counted) again.
	posted = set(
		frappe.get_all(
			"Stock Entry",
			filters={
				"docstatus": 1,
				"company": company,
				"remarks": ("like", "Counter repack backfill: fold%"),
			},
			pluck="remarks",
		)
	)
	actions = []

	def fold(item, when, qty, why, value=None):
		bulk = rules[item].bulk_item if item in rules else folded[item]
		action = {"kind": "fold", "item": item, "bulk": bulk, "at": when, "qty": qty, "why": why}
		if _fold_remarks(action) not in posted:
			_move(pos, item, action["bulk"], qty, value)
			actions.append(action)

	def opening(item):
		return pos[item].qty > TOLERANCE

	for item in sorted(set(rules) | set(folded)):
		if opening(item):
			fold(item, start, pos[item].qty, "opening stock")

	sles = frappe.db.sql(
		"""select name, item_code, voucher_type, voucher_no, voucher_detail_no, posting_datetime,
			actual_qty, stock_value_difference, qty_after_transaction
		from `tabStock Ledger Entry`
		where is_cancelled=0 and warehouse=%s and posting_datetime>=%s and posting_datetime<%s
			and item_code in %s
		order by posting_datetime, creation""",
		(
			warehouse,
			start,
			get_datetime(f"{to_date} 23:59:59.999999") if to_date else get_datetime("2999-12-31"),
			tuple(items),
		),
		as_dict=True,
	)
	returns = _return_vouchers(sles)
	i = 0
	while i < len(sles):
		sle = sles[i]
		item = sle.item_code
		if item in bulk_items:
			if sle.voucher_type == "Stock Reconciliation":
				frappe.throw(
					_("Bulk item {0} has a Stock Reconciliation ({1}); settle it first.").format(
						item, sle.voucher_no
					)
				)
			pos[item].qty += flt(sle.actual_qty)
			pos[item].value += flt(sle.stock_value_difference)
			i += 1
			continue

		is_sale = sle.voucher_type in ("Sales Invoice", "Delivery Note") and flt(sle.actual_qty) < 0
		if is_sale and sle.voucher_no not in returns:
			# every row of this voucher at this moment, so one repack serves the whole bill
			j = i
			batch = []
			while (
				j < len(sles)
				and sles[j].voucher_no == sle.voucher_no
				and sles[j].posting_datetime == sle.posting_datetime
			):
				if sles[j].item_code in rules and flt(sles[j].actual_qty) < 0:
					batch.append(sles[j])
				j += 1
			action = _repack(batch, rules, pos, warehouse)
			if action:
				actions.append(action)
			for s in sles[i:j]:
				_apply(pos, s)
			i = j
			continue

		_apply(pos, sle)
		if (
			item in folded
			and sle.voucher_type in ("Purchase Invoice", "Purchase Receipt")
			and flt(sle.actual_qty) > 0
		):
			# valued at what the receipt brought in
			fold(
				item,
				sle.posting_datetime,
				flt(sle.actual_qty),
				f"receipt {sle.voucher_no}",
				flt(sle.stock_value_difference),
			)
		elif sle.voucher_no in returns and flt(sle.actual_qty) > 0:
			# valued at what the return brought in: the grade's running value is not reliable while
			# later sales are still unfed
			fold(
				item,
				sle.posting_datetime,
				flt(sle.actual_qty),
				f"return {sle.voucher_no}",
				flt(sle.stock_value_difference),
			)
		i += 1
	return actions, pos


def _apply(pos, sle):
	p = pos[sle.item_code]
	if sle.voucher_type == "Stock Reconciliation":
		# a reco states the counted quantity; its actual_qty was worked out against the old ledger
		counted = frappe.db.get_value("Stock Reconciliation Item", sle.voucher_detail_no, "qty")
		p.value = flt(p.value) + flt(sle.stock_value_difference)
		p.qty = flt(counted)
		return
	p.qty += flt(sle.actual_qty)
	p.value += flt(sle.stock_value_difference)


def _return_vouchers(sles) -> set:
	out = set()
	for dt in ("Sales Invoice", "Delivery Note"):
		names = {s.voucher_no for s in sles if s.voucher_type == dt}
		if names:
			out |= set(
				frappe.get_all(dt, filters={"name": ("in", list(names)), "is_return": 1}, pluck="name")
			)
	return out


def _move(pos, item, bulk, qty, value=None) -> None:
	"""A fold, in memory: qty of the grade into the lot, at value if given, else at the grade's
	current rate."""
	if value is None:
		value = qty * (flt(pos[item].value) / flt(pos[item].qty) if flt(pos[item].qty) else 0.0)
	pos[item].qty -= qty
	pos[item].value -= value
	pos[bulk].qty += qty
	pos[bulk].value += value


def _repack(batch, rules, pos, warehouse):
	lines = []
	need = {}
	for s in batch:
		item = s.item_code
		sold = -flt(s.actual_qty)
		held = max(flt(pos[item].qty) - need.get(item, 0.0), 0.0)
		short = sold - min(held, sold)
		need[item] = need.get(item, 0.0) + sold
		if short <= TOLERANCE:
			continue
		rule = rules[item]
		rate = _row_unit_cost(s, rule)
		lines.append(
			{
				"item": item,
				"qty": short,
				"rate": rate,
				"rule": rule.name,
				"row": s.voucher_detail_no,
				"bulk": rule.bulk_item,
			}
		)
	if not lines:
		return None
	bulks = {line["bulk"] for line in lines}
	if len(bulks) > 1:
		frappe.throw(
			_("{0} draws on more than one bulk item; not supported by backfill.").format(batch[0].voucher_no)
		)
	bulk = bulks.pop()
	need_bulk = sum(line["qty"] * flt(rules[line["item"]].bulk_qty_per_unit) for line in lines)
	cost = sum(line["qty"] * line["rate"] for line in lines)
	lot = pos[bulk]
	refusal = None
	if flt(lot.qty) <= need_bulk:
		refusal = f"lot {flt(lot.qty):.3f} <= needed {need_bulk:.3f}"
	elif flt(lot.value) - cost <= 0:
		refusal = f"lot value {flt(lot.value):.2f} - cost {cost:.2f} <= 0"
	action = {
		"kind": "repack",
		"at": batch[0].posting_datetime - BEFORE_SALE,
		"voucher_type": batch[0].voucher_type,
		"voucher_no": batch[0].voucher_no,
		"bulk": bulk,
		"lot_qty": flt(lot.qty),
		"lines": lines,
		"item": lines[0]["item"],
		"refusal": refusal,
	}
	lot.qty -= need_bulk
	lot.value -= cost
	for line in lines:
		pos[line["item"]].qty += line["qty"]
		pos[line["item"]].value += line["qty"] * line["rate"]
	return action


def _row_unit_cost(sle, rule) -> float:
	child = "Sales Invoice Item" if sle.voucher_type == "Sales Invoice" else "Delivery Note Item"
	row = frappe.db.get_value(
		child, sle.voucher_detail_no, ["base_net_rate", "conversion_factor", "incoming_rate"], as_dict=True
	)
	voucher = frappe.db.get_value(
		sle.voucher_type, sle.voucher_no, ["is_bns_internal_customer", "customer"], as_dict=True
	)
	if cr.is_internal_sale(voucher) and flt(row.incoming_rate):
		# an internal sale's stock leaves at the row's transfer cost (incoming_rate), which can differ
		# from its billed rate; bring the grade in at exactly that
		return flt(row.incoming_rate) / (flt(row.conversion_factor) or 1.0)
	return cr.unit_cost(row, cr.margin_for(voucher, rule))


def _summary(actions, final) -> dict:
	repacks = [a for a in actions if a["kind"] == "repack"]
	folds = [a for a in actions if a["kind"] == "fold"]
	refusals = [a for a in repacks if a["refusal"]]
	return {
		"repacks": len(repacks),
		"repack_lines": sum(len(a["lines"]) for a in repacks),
		"repack_qty": round(sum(line["qty"] for a in repacks for line in a["lines"]), 3),
		"folds": len(folds),
		"fold_qty": round(sum(a["qty"] for a in folds), 3),
		"refusals": [(str(a["at"]), a["voucher_no"], a["refusal"]) for a in refusals[:20]],
		"refusal_count": len(refusals),
		"final_positions": {
			k: (round(v.qty, 3), round(v.value, 2)) for k, v in final.items() if abs(v.qty) > TOLERANCE
		},
	}


def post(company: str, warehouse: str, actions: list) -> int:
	frappe.flags.bns_counter_repack_backfill = True
	try:
		return _post(company, warehouse, actions)
	finally:
		frappe.flags.bns_counter_repack_backfill = False


def _post(company: str, warehouse: str, actions: list) -> int:
	done = 0
	for action in actions:
		doc = frappe.get_doc(_entry(company, warehouse, action))
		doc.flags.ignore_permissions = True
		doc.flags.bns_counter_repack_backfill = True
		doc.insert()
		doc.submit()
		if action["kind"] == "repack" and action["voucher_type"] == "Sales Invoice":
			for line in action["lines"]:
				frappe.db.set_value(
					"Sales Invoice Item",
					line["row"],
					{"bns_counter_repack": 1, "bns_counter_repack_entry": doc.name},
					update_modified=False,
				)
		action["entry"] = doc.name
		frappe.db.commit()
		done += 1
	return done


def _entry(company, warehouse, action) -> dict:
	at = get_datetime(action["at"])
	head = {
		"doctype": "Stock Entry",
		"purpose": "Repack",
		"stock_entry_type": "Repack",
		"company": company,
		"set_posting_time": 1,
		"posting_date": at.date(),
		"posting_time": at.time().strftime("%H:%M:%S.%f"),
	}
	uom = lambda item: frappe.get_cached_value("Item", item, "stock_uom")  # noqa: E731
	if action["kind"] == "fold":
		head["remarks"] = _fold_remarks(action)
		head["items"] = [
			{
				"item_code": action["item"],
				"s_warehouse": warehouse,
				"qty": action["qty"],
				"conversion_factor": 1,
			},
			{
				"item_code": action["bulk"],
				"t_warehouse": warehouse,
				"qty": action["qty"],
				"conversion_factor": 1,
				"is_finished_item": 1,
			},
		]
	else:
		head["remarks"] = _("Counter repack backfill for {0} {1}").format(
			action["voucher_type"], action["voucher_no"]
		)
		group = frappe._dict(
			bulk_item=action["bulk"],
			warehouse=warehouse,
			bulk_needed=sum(line["qty"] for line in action["lines"]),
			lines=[
				frappe._dict(sold_item=line["item"], qty=line["qty"], rate=line["rate"])
				for line in action["lines"]
			],
		)
		head["items"] = cr.stock_entry_dict(
			frappe._dict(company=company, name=action["voucher_no"]),
			group,
			frappe._dict(qty=action["lot_qty"]),
		)["items"]
	for d in head["items"]:
		d["uom"] = d["stock_uom"] = uom(d["item_code"])
		d["transfer_qty"] = d["qty"]
	return head


def verify(company: str) -> list:
	"""Backfill entries that still carry a balance on Stock Adjustment after the repost."""
	account = frappe.get_cached_value("Company", company, "stock_adjustment_account")
	return frappe.db.sql(
		"""select gle.voucher_no, round(sum(gle.debit - gle.credit), 2) net
		from `tabGL Entry` gle join `tabStock Entry` se on se.name = gle.voucher_no
		where gle.voucher_type='Stock Entry' and gle.is_cancelled=0 and gle.account=%s
			and se.docstatus=1 and se.remarks like 'Counter repack backfill%%'
		group by gle.voucher_no having abs(net) > 1""",
		account,
	)


def _fold_remarks(action) -> str:
	return f"Counter repack backfill: fold {action['item']} into {action['bulk']} ({action['why']})"


def _skip_queued_reposts(since) -> int:
	names = frappe.get_all(
		"Repost Item Valuation",
		filters={"docstatus": 1, "status": "Queued", "creation": (">=", since)},
		pluck="name",
	)
	if names:
		frappe.db.sql(
			"update `tabRepost Item Valuation` set status='Skipped' where name in %s", [tuple(names)]
		)
		frappe.db.commit()
	return len(names)


def repost(company, warehouse, from_date, items) -> list:
	from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import repost as run_repost
	from erpnext.stock.stock_balance import repost_stock

	failed = []
	for item in items:
		riv = frappe.get_doc(
			{
				"doctype": "Repost Item Valuation",
				"based_on": "Item and Warehouse",
				"item_code": item,
				"warehouse": warehouse,
				"company": company,
				"posting_date": from_date,
				"posting_time": "00:00:00",
				"allow_negative_stock": 1,
			}
		).insert(ignore_permissions=True)
		riv.submit()
		frappe.db.commit()
		run_repost(riv)
		riv.reload()
		repost_stock(item, warehouse)
		frappe.db.commit()
		if riv.status != "Completed":
			failed.append((item, riv.name))
	frappe.flags.through_repost_item_valuation = False
	return failed
