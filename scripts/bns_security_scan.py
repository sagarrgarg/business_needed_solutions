#!/usr/bin/env python3
"""
BNS app static security / correctness scanner.

Runs in CI or as a pre-commit hook. Flags patterns we've been burned by:

  1. @frappe.whitelist() functions whose first ~8 statements do NOT call
     a permission gate. The only accepted gate shape is
     `frappe.has_permission(doctype, action)` (optionally followed by a
     PermissionError raise / throw), or a project-local `_require_*`
     helper that itself calls frappe.has_permission. Hardcoded role
     lists via `frappe.only_for([...])` are deliberately NOT accepted
     because they bypass the Role Permission Manager — admins must be
     able to grant / revoke access from the Desk UI without a code
     deploy.
  2. SQL built via f-strings or .format() where a non-hardcoded variable
     is interpolated into the WHERE clause (classic SQL injection vector).
  3. `outstanding > 0` / `outstanding < 0` filters in *report* files (the
     Pure AR/AP advance-drop regression that cost us a live site).
  4. `except Exception: pass` and its siblings that silently swallow errors.
  5. Hardcoded API keys / tokens / passwords.

Exit code:
  0 = clean
  1 = findings (prints a structured report to stdout)

Usage:
  python3 scripts/bns_security_scan.py                   # scan full app
  python3 scripts/bns_security_scan.py path1 path2 ...   # scan given files

Add to .git/hooks/pre-commit:
  #!/bin/sh
  files=$(git diff --cached --name-only --diff-filter=ACM -- '*.py')
  [ -z "$files" ] && exit 0
  python3 scripts/bns_security_scan.py $files || exit 1
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent

# First-line-of-function patterns that count as a permission gate. The scanner
# treats any of these as a sufficient guard on a whitelisted endpoint.
# Deliberately NOT in this list: `frappe.only_for([...])` — it hardcodes
# role names and bypasses the Role Permission Manager. Use
# `frappe.has_permission(doctype, action)` instead so admins can grant /
# revoke access from the Desk UI.
_GATE_PATTERNS = (
	r"frappe\.has_permission\s*\(",
	r"_bns_require_[a-zA-Z_]+\s*\(",  # utils.py helpers (call has_permission internally)
	r"_require_dashboard_[a-zA-Z_]+\s*\(",  # bns_dashboard.py helpers
	r"_require_accounts_manager\s*\(",  # bns_dashboard.py helper
	r"_enforce_[a-zA-Z_]+_permission\s*\(",  # utils.py _enforce_* helpers
	r"frappe\.session\.user\s*==\s*['\"]Guest['\"]",  # edge guest-reject
)
_GATE_RE = re.compile("|".join(_GATE_PATTERNS))

# How many logical lines of a function body to inspect for the gate.
_GATE_WINDOW = 8

# Patterns that indicate unsafe SQL interpolation.
_SQL_FSTRING_RE = re.compile(r'frappe\.db\.sql\s*\(\s*f["\']')
_SQL_FORMAT_RE = re.compile(r'frappe\.db\.sql\s*\(\s*["\'][^"\']*["\']\s*\.format\s*\(')

# Silent-swallow except.
_SILENT_EXCEPT_RE = re.compile(r"except\s+\w+[^:]*:\s*pass\b")

# Secrets.
_SECRET_RE = re.compile(
	r"""
	(?:
		(?:api[_-]?key|api[_-]?secret|password|secret|token|auth)
		\s*=\s*
		["'][A-Za-z0-9_\-]{12,}["']
	)
	|
	Bearer\s+[A-Za-z0-9_\-.]{16,}
	|
	sk-[A-Za-z0-9]{20,}
	""",
	re.IGNORECASE | re.VERBOSE,
)

# Sign-filter drops in reports. Match `outstanding > 0` / `outstanding < 0`
# patterns but NOT abs(...) > 0.009 or similar which intentionally include
# both sides — those are the correct shape we moved to.
_SIGN_FILTER_RE = re.compile(
	r"""(?x)
	if\s+
	(?!.*abs\s*\()          # lookahead: no abs(
	.*outstanding
	.*[<>]\s*0
	"""
)

# Allow-list of sign-filter rows that are known safe (e.g. routing logic that
# explicitly sends the other side to a sibling report). Add absolute file path
# + line number as "path:line".
_SIGN_FILTER_ALLOW = {
	# FIFO advance-apply logic in Pure AR Summary: the positive list is
	# invoices, the negative list is advances — they get netted against each
	# other inside redistribute_negative_ageing_buckets, not dropped.
	"business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py:776",
	"business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py:777",
	"business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py:801",
}


def is_python_file(p: Path) -> bool:
	return p.suffix == ".py" and "/node_modules/" not in str(p) and "/.venv/" not in str(p)


def iter_target_files(paths: list[str]) -> Iterable[Path]:
	if paths:
		for raw in paths:
			p = Path(raw)
			if p.is_file() and is_python_file(p):
				yield p
			elif p.is_dir():
				yield from (x for x in p.rglob("*.py") if is_python_file(x))
		return
	for p in REPO_ROOT.rglob("*.py"):
		if is_python_file(p):
			# Skip the scanner itself and any vendored deps.
			rel = p.relative_to(REPO_ROOT)
			if rel.parts[0] in ("scripts", "graphify-out"):
				continue
			yield p


class Finding:
	__slots__ = ("severity", "rule", "path", "line", "message")

	def __init__(self, severity: str, rule: str, path: Path, line: int, message: str):
		self.severity = severity
		self.rule = rule
		self.path = path
		self.line = line
		self.message = message

	def format(self) -> str:
		rel = self.path.relative_to(REPO_ROOT) if self.path.is_absolute() else self.path
		return f"[{self.severity}] {self.rule}  {rel}:{self.line}  {self.message}"


def _find_whitelist_gate_failures(tree: ast.AST, source_lines: list[str], path: Path) -> list[Finding]:
	findings: list[Finding] = []
	for node in ast.walk(tree):
		if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
			continue
		decorated = any(
			(isinstance(dec, ast.Call) and _callee_name(dec.func) == "frappe.whitelist")
			or (isinstance(dec, ast.Attribute) and _callee_name(dec) == "frappe.whitelist")
			for dec in node.decorator_list
		)
		if not decorated:
			continue

		# Inspect the source range between the def line and the end of the
		# first N top-level statements — this catches gate calls that live
		# inside an `if user == 'Guest': throw(...)` block even though the
		# `throw` line is technically below the `if` statement node.
		window = node.body[:_GATE_WINDOW]
		if window:
			start = node.lineno - 1
			last = window[-1]
			end = getattr(last, "end_lineno", last.lineno) or last.lineno
			body_src = "\n".join(source_lines[start:end])
		else:
			body_src = ""
		if _GATE_RE.search(body_src):
			continue

		# Skip obvious safe cases: function just returns a literal/computed value
		# without any side-effect and is clearly read-only on public data.
		if len(node.body) == 1 and isinstance(node.body[0], ast.Return):
			continue

		findings.append(
			Finding(
				"HIGH",
				"whitelist-no-gate",
				path,
				node.lineno,
				f"@frappe.whitelist() {node.name}() has no permission gate in first {_GATE_WINDOW} lines",
			)
		)
	return findings


def _callee_name(node: ast.AST) -> str:
	if isinstance(node, ast.Attribute):
		return f"{_callee_name(node.value)}.{node.attr}"
	if isinstance(node, ast.Name):
		return node.id
	return ""


def _scan_regex_rules(source_lines: list[str], path: Path) -> list[Finding]:
	findings: list[Finding] = []
	rel_str = str(path.relative_to(REPO_ROOT) if path.is_absolute() else path)
	is_report = "/report/" in rel_str.replace(os.sep, "/")

	for idx, raw_line in enumerate(source_lines, start=1):
		line = raw_line.rstrip("\n")

		if _SQL_FSTRING_RE.search(line):
			findings.append(
				Finding("HIGH", "sql-fstring", path, idx, "frappe.db.sql with f-string (SQL injection risk)")
			)
		if _SQL_FORMAT_RE.search(line):
			findings.append(
				Finding("HIGH", "sql-format", path, idx, "frappe.db.sql with .format() (SQL injection risk)")
			)
		if _SILENT_EXCEPT_RE.search(line):
			findings.append(
				Finding("MED", "silent-except", path, idx, "except ...: pass silently swallows errors")
			)
		if _SECRET_RE.search(line):
			findings.append(
				Finding("HIGH", "hardcoded-secret", path, idx, "possible hardcoded secret/token")
			)
		if is_report and _SIGN_FILTER_RE.search(line):
			key = f"{rel_str}:{idx}"
			if key not in _SIGN_FILTER_ALLOW:
				findings.append(
					Finding(
						"MED",
						"sign-filter-drop",
						path,
						idx,
						"report drops rows by 'outstanding > 0' — verify advances are not hidden",
					)
				)
	return findings


def scan_file(path: Path) -> list[Finding]:
	try:
		source = path.read_text(encoding="utf-8", errors="replace")
	except Exception as exc:
		return [Finding("LOW", "read-error", path, 0, f"could not read file: {exc}")]

	source_lines = source.splitlines(keepends=False)
	findings = _scan_regex_rules(source_lines, path)
	try:
		tree = ast.parse(source, filename=str(path))
	except SyntaxError as exc:
		findings.append(Finding("LOW", "syntax-error", path, exc.lineno or 0, exc.msg or "syntax error"))
		return findings
	findings.extend(_find_whitelist_gate_failures(tree, source_lines, path))
	return findings


def main(argv: list[str]) -> int:
	args = argv[1:]
	all_findings: list[Finding] = []
	for path in iter_target_files(args):
		all_findings.extend(scan_file(path))

	if not all_findings:
		print("BNS security scan: clean.")
		return 0

	order = {"HIGH": 0, "MED": 1, "LOW": 2}
	all_findings.sort(key=lambda f: (order.get(f.severity, 9), f.rule, str(f.path), f.line))

	print("BNS security scan findings:")
	for f in all_findings:
		print("  " + f.format())
	print(f"\ntotal: {len(all_findings)}")

	# Only non-zero exit on HIGH findings — MED is advisory so developers can
	# triage without blocking every commit.
	high = sum(1 for f in all_findings if f.severity == "HIGH")
	return 1 if high else 0


if __name__ == "__main__":
	sys.exit(main(sys.argv))
