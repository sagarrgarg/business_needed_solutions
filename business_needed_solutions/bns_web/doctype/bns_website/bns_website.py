# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class BNSWebsite(Document):
	def validate(self):
		self.normalize_site_key()
		self.normalize_base_url()
		self.validate_api_user()

	def normalize_site_key(self):
		self.site_key = (self.site_key or "").strip().lower().replace(" ", "-")
		if not self.site_key:
			frappe.throw(_("Site Key is required"))

	def normalize_base_url(self):
		# A trailing slash or stray whitespace here silently breaks every
		# canonical URL the API emits, so normalize instead of trusting input.
		self.base_url = (self.base_url or "").strip().rstrip("/")
		if "," in self.base_url or " " in self.base_url:
			frappe.throw(
				_(
					"Base URL must be a single URL (e.g. https://hingwala.com) — it is used to build "
					"canonical links. Alternate domains like www. belong on the website's own server "
					"as redirects, not here."
				)
			)
		if not self.base_url.startswith(("http://", "https://")):
			frappe.throw(_("Base URL must start with http:// or https://"))

	def validate_api_user(self):
		if self.api_user and self.api_user in ("Administrator", "Guest"):
			frappe.throw(_("API User cannot be Administrator or Guest"))

	def on_update(self):
		from business_needed_solutions.bns_web.blog_api import (
			clear_blog_api_cache,
		)

		clear_blog_api_cache()

	def on_trash(self):
		from business_needed_solutions.bns_web.blog_api import (
			clear_blog_api_cache,
		)

		clear_blog_api_cache()
