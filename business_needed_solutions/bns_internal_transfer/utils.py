"""
Compatibility shim: BNS Internal Transfer was renamed to BNS Branch Accounting.
Re-exports all utils for backward compatibility with stale Client Scripts, cached assets, etc.
"""
from business_needed_solutions.bns_branch_accounting.utils import *  # noqa: F401, F403
