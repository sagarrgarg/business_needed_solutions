#!/usr/bin/env bash
# Install BNS pre-commit hooks into .git/hooks/pre-commit.
# Run once after cloning the repo:
#   bash scripts/install_hooks.sh
#
# The hook runs scripts/bns_security_scan.py on the staged .py files and
# blocks the commit on any HIGH finding. MED/LOW findings are printed but
# do not block.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK="$REPO_ROOT/.git/hooks/pre-commit"

cat > "$HOOK" <<'HOOK_EOF'
#!/usr/bin/env bash
# BNS pre-commit security gate.
#
# Blocks commits that introduce:
#   - @frappe.whitelist() without a permission gate in the first 8 stmts
#   - SQL injection patterns (f-string / .format() SQL)
#   - Silent `except: pass`
#   - Hardcoded credentials / API tokens
#   - `outstanding > 0`-style report drops that silently hide advances
#
# Override for a single commit:  git commit --no-verify
# (Frowned upon — prefer fixing the finding.)

set -e

files=$(git diff --cached --name-only --diff-filter=ACM -- '*.py')
if [ -z "$files" ]; then
    exit 0
fi

# shellcheck disable=SC2086
python3 scripts/bns_security_scan.py $files
HOOK_EOF

chmod +x "$HOOK"
echo "Installed $HOOK"
