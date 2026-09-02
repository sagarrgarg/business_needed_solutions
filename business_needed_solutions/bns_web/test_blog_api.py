# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""Tests for the BNS Web blog delivery API.

Focus is the two properties that actually matter for an auth-bearing public
endpoint: one site can never read another's content, and a post that stops
qualifying is reported as a removal rather than silently vanishing.

Run:
    bench --site <site> run-tests --app business_needed_solutions \\
        --module business_needed_solutions.bns_web.test_blog_api
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from business_needed_solutions.bns_web import blog_api


def _user(email):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	return email


def _website(site_key, user):
	if frappe.db.exists("BNS Website", site_key):
		return frappe.get_doc("BNS Website", site_key)
	return frappe.get_doc(
		{
			"doctype": "BNS Website",
			"site_key": site_key,
			"title": site_key,
			"base_url": f"https://{site_key}.example.com",
			"enabled": 1,
			"api_user": user,
		}
	).insert(ignore_permissions=True)


def _blogger():
	if not frappe.db.exists("Blogger", "bns-test"):
		frappe.get_doc(
			{
				"doctype": "Blogger",
				"short_name": "bns-test",
				"full_name": "BNS Test Author",
			}
		).insert(ignore_permissions=True)
	return "bns-test"


def _category():
	if not frappe.db.exists("Blog Category", "bns-test-cat"):
		frappe.get_doc(
			{"doctype": "Blog Category", "title": "BNS Test Cat", "published": 1}
		).insert(ignore_permissions=True)
	return frappe.db.get_value("Blog Category", {"title": "BNS Test Cat"}, "name")


def _post(title, sites, published=1):
	doc = frappe.get_doc(
		{
			"doctype": "Blog Post",
			"title": title,
			"blog_category": _category(),
			"blogger": _blogger(),
			"content_type": "Rich Text",
			"content": f"<p>{title} body</p>",
			"published": published,
			"bns_websites": [{"website": s} for s in sites],
		}
	).insert(ignore_permissions=True)
	return doc


class TestBlogAPI(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.user_a = _user("bns-web-a@example.com")
		cls.user_b = _user("bns-web-b@example.com")
		cls.site_a = _website("bnstesta", cls.user_a).name
		cls.site_b = _website("bnstestb", cls.user_b).name

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	# -- isolation ------------------------------------------------------

	def test_site_cannot_read_another_sites_post(self):
		post = _post("BNS Only For B", [self.site_b])

		frappe.set_user(self.user_a)
		with self.assertRaises(frappe.DoesNotExistError):
			blog_api.get_post(post.route)

		routes = [i["route"] for i in blog_api.get_posts(limit=50)["items"]]
		self.assertNotIn(post.route, routes)

	def test_site_reads_its_own_post(self):
		post = _post("BNS Only For A", [self.site_a])

		frappe.set_user(self.user_a)
		self.assertEqual(blog_api.get_post(post.route)["route"], post.route)

	def test_unmapped_user_is_refused(self):
		frappe.set_user(_user("bns-web-nobody@example.com"))
		with self.assertRaises(frappe.PermissionError):
			blog_api.get_posts()

	def test_guest_is_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.AuthenticationError):
			blog_api.get_posts()

	def test_drafts_excluded_from_listing(self):
		post = _post("BNS Draft For A", [self.site_a], published=0)

		frappe.set_user(self.user_a)
		routes = [i["route"] for i in blog_api.get_posts(limit=50)["items"]]
		self.assertNotIn(post.route, routes)

	# -- removals -------------------------------------------------------

	def test_unpublishing_is_reported_as_removal(self):
		post = _post("BNS To Unpublish", [self.site_a])
		since = frappe.utils.now()

		post.reload()
		post.published = 0
		post.save(ignore_permissions=True)

		frappe.set_user(self.user_a)
		self.assertIn(post.route, blog_api.get_changes(since=since)["removed"])

	def test_unserving_is_reported_as_removal(self):
		post = _post("BNS To Unserve", [self.site_a])
		since = frappe.utils.now()

		post.reload()
		post.bns_websites = []
		post.save(ignore_permissions=True)

		frappe.set_user(self.user_a)
		self.assertIn(post.route, blog_api.get_changes(since=since)["removed"])

	def test_removal_is_not_reported_to_other_sites(self):
		post = _post("BNS B Unpublished", [self.site_b])
		since = frappe.utils.now()

		post.reload()
		post.published = 0
		post.save(ignore_permissions=True)

		frappe.set_user(self.user_a)
		self.assertNotIn(post.route, blog_api.get_changes(since=since)["removed"])

	def test_full_export_returns_no_removals(self):
		frappe.set_user(self.user_a)
		self.assertEqual(blog_api.get_changes()["removed"], [])

	# -- cursor ---------------------------------------------------------

	def test_invalid_since_is_rejected(self):
		frappe.set_user(self.user_a)
		with self.assertRaises(frappe.ValidationError):
			blog_api.get_changes(since="not-a-date")

	def test_changed_post_appears_in_delta(self):
		since = frappe.utils.now()
		post = _post("BNS Fresh For A", [self.site_a])

		frappe.set_user(self.user_a)
		result = blog_api.get_changes(since=since)
		self.assertIn(post.name, [c["name"] for c in result["changed"]])
		self.assertTrue(result["next_since"])
