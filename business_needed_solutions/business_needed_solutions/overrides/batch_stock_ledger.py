"""
Batch balance per warehouse, read from both batch ledgers:

- Serial and Batch Entry rows of the bundle on each Stock Ledger Entry (v15+).
  ERPNext leaves Stock Ledger Entry.batch_no empty on these rows, so a query on
  SLE.batch_no alone never sees bundle-era stock.
- Legacy Stock Ledger Entry rows that carry batch_no and no bundle.

Bundles are joined through their Stock Ledger Entry, as ERPNext does in
SerialandBatchBundle.get_batch_query_from_sabb, so posting order and
cancellation follow the stock ledger. Works on v15 and v16.
"""

import frappe
from frappe.utils import cint, flt, get_datetime


def get_sle_batch_qty(args):
	"""{batch_no: qty} this stock ledger row moves (negative = out)."""
	bundle = args.get("serial_and_batch_bundle")
	if bundle:
		sign = -1 if frappe.db.get_value("Serial and Batch Bundle", bundle, "type_of_transaction") == "Outward" else 1
		out = {}
		for row in frappe.get_all(
			"Serial and Batch Entry",
			filters={"parent": bundle, "batch_no": ("is", "set")},
			fields=["batch_no", "qty"],
		):
			out[row.batch_no] = out.get(row.batch_no, 0) + sign * abs(flt(row.qty))
		return out

	if args.get("batch_no"):
		return {args.get("batch_no"): flt(args.get("actual_qty"))}

	return {}


def get_batch_ledger(item_code, warehouse, batch_nos, exclude=None):
	"""Submitted batch movements in a warehouse, oldest first.

	exclude: the stock ledger row being checked (dict with name, serial_and_batch_bundle,
	voucher_no, voucher_detail_no), left out so it is not counted twice once posted.
	"""
	if not batch_nos:
		return []

	exclude = exclude or {}
	values = {
		"item_code": item_code,
		"warehouse": warehouse,
		"batch_nos": tuple(batch_nos),
		"exclude_sle": exclude.get("name") or "",
		"exclude_bundle": exclude.get("serial_and_batch_bundle") or "",
		"exclude_voucher": exclude.get("voucher_no") or "",
		"exclude_detail": exclude.get("voucher_detail_no") or "",
	}
	# Without the row's name (ERPNext does not always pass it), a legacy row is
	# known by voucher + voucher row.
	legacy_exclude = "and sle.name != %(exclude_sle)s"
	if not values["exclude_sle"] and values["exclude_detail"]:
		legacy_exclude = (
			"and not (sle.voucher_no = %(exclude_voucher)s and sle.voucher_detail_no = %(exclude_detail)s)"
		)

	return frappe.db.sql(
		f"""
		select sle.posting_date, sle.posting_time, sle.posting_datetime, sle.creation,
			sle.voucher_type, sle.voucher_no, sbe.batch_no, sbe.qty
		from `tabSerial and Batch Entry` sbe
		inner join `tabStock Ledger Entry` sle on sle.serial_and_batch_bundle = sbe.parent
		where sle.item_code = %(item_code)s
			and sle.warehouse = %(warehouse)s
			and sle.is_cancelled = 0
			and sle.name != %(exclude_sle)s
			and sle.serial_and_batch_bundle != %(exclude_bundle)s
			and sbe.batch_no in %(batch_nos)s

		union all

		select sle.posting_date, sle.posting_time, sle.posting_datetime, sle.creation,
			sle.voucher_type, sle.voucher_no, sle.batch_no, sle.actual_qty as qty
		from `tabStock Ledger Entry` sle
		where sle.item_code = %(item_code)s
			and sle.warehouse = %(warehouse)s
			and sle.is_cancelled = 0
			{legacy_exclude}
			and sle.batch_no in %(batch_nos)s
			and ifnull(sle.serial_and_batch_bundle, '') = ''

		order by posting_datetime, creation
		""",
		values,
		as_dict=True,
	)


def find_negative_batch_point(args):
	"""
	First place where a batch this row takes out goes below zero in its
	warehouse, counting this row. None if every batch stays at or above zero.

	args: item_code, warehouse, posting_date, posting_time, posting_datetime,
	voucher_type, voucher_no, voucher_detail_no, actual_qty, batch_no /
	serial_and_batch_bundle and, if known, name. The row itself is always counted
	from args and left out of the query, so pre- and post-insert calls agree.
	"""
	outward = {b: q for b, q in get_sle_batch_qty(args).items() if flt(q) < 0}
	if not outward:
		return None

	posting_datetime = get_datetime(args.get("posting_datetime"))
	precision = cint(frappe.db.get_default("float_precision")) or 2
	threshold = 0.0001 if precision <= 4 else 10 ** (-precision)

	def is_negative(qty):
		qty = flt(qty, precision)
		return qty < 0 and abs(qty) > threshold

	rows = get_batch_ledger(args.get("item_code"), args.get("warehouse"), list(outward), exclude=args)

	for batch_no, own_qty in outward.items():
		balance = 0.0
		future = []
		for row in rows:
			if row.batch_no != batch_no:
				continue
			if get_datetime(row.posting_datetime) <= posting_datetime:
				balance += flt(row.qty)
			else:
				future.append(row)

		balance += own_qty
		if is_negative(balance):
			return frappe._dict(
				batch_no=batch_no,
				qty=balance,
				posting_date=args.get("posting_date"),
				posting_time=args.get("posting_time"),
				voucher_type=args.get("voucher_type"),
				voucher_no=args.get("voucher_no"),
			)

		for row in future:
			balance += flt(row.qty)
			if is_negative(balance):
				return frappe._dict(
					batch_no=batch_no,
					qty=balance,
					posting_date=row.posting_date,
					posting_time=row.posting_time,
					voucher_type=row.voucher_type,
					voucher_no=row.voucher_no,
				)

	return None


def get_batch_qty_by_warehouse(item_code, batch_no):
	"""{warehouse: qty} of one batch today, from bundle entries and legacy rows."""
	rows = frappe.db.sql(
		"""
		select warehouse, sum(qty) as qty from (
			select sle.warehouse, sbe.qty
			from `tabSerial and Batch Entry` sbe
			inner join `tabStock Ledger Entry` sle on sle.serial_and_batch_bundle = sbe.parent
			where sle.item_code = %(item_code)s and sle.is_cancelled = 0 and sbe.batch_no = %(batch_no)s

			union all

			select sle.warehouse, sle.actual_qty as qty
			from `tabStock Ledger Entry` sle
			where sle.item_code = %(item_code)s and sle.is_cancelled = 0 and sle.batch_no = %(batch_no)s
				and ifnull(sle.serial_and_batch_bundle, '') = ''
		) batch_rows
		group by warehouse
		""",
		{"item_code": item_code, "batch_no": batch_no},
		as_dict=True,
	)
	return {row.warehouse: flt(row.qty) for row in rows}
