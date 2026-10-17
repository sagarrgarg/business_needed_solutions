# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
Tests for bns_web/blog_compat (the blog doctypes BNS provides on Frappe v16 without the blog app).

The behaviour tests need BNS to be the provider (a v16 site without frappe/blog) and skip
themselves elsewhere. Nothing is committed: every test runs in a transaction rolled back in
tearDown, and the provider tests only flip DocType flags, never create tables.

    bench --site <site> run-tests --module business_needed_solutions.bns_web.test_blog_compat

The upgrade paths that need a real migrate (orphaned v15 definitions adopted before Frappe's
orphan cleanup; definitions already deleted and recreated over the old tables; the frappe/blog
app taking over later) were exercised with bench migrate on a test site; see blog_compat's
docstring for the states.
"""

import glob
import json
import os
import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from business_needed_solutions.bns_web import blog_compat, web_view_guard

CATEGORY = "bns-compat-category"


class TestDefinitions(unittest.TestCase):
	"""The bundled definitions are v15's schema and stay compatible with the frappe/blog app."""

	def test_every_doctype_has_a_definition(self):
		for doctype in blog_compat.BLOG_DOCTYPES:
			self.assertEqual(blog_compat.load_definition(doctype)["name"], doctype)

	def test_custom_definition_shape(self):
		for doctype in blog_compat.BLOG_DOCTYPES:
			source = blog_compat.load_definition(doctype)
			doc = blog_compat.as_custom_definition(source)
			self.assertEqual((doc["custom"], doc["module"], doc["doctype"]), (1, "Website", "DocType"))
			for key, value in blog_compat.WEB_PROPERTIES_OFF.items():
				self.assertEqual(doc[key], value, f"{doctype}.{key}")
			for key in ("creation", "modified", "owner", "links", "actions"):
				self.assertNotIn(key, doc)
			self.assertEqual(
				[f["fieldname"] for f in doc["fields"]], [f["fieldname"] for f in source["fields"]]
			)
			self.assertEqual(
				[p["role"] for p in doc["permissions"]], [p["role"] for p in source.get("permissions", [])]
			)

	def test_definitions_match_the_blog_app_schema(self):
		"""Same data fields as frappe/blog, so the app can take the doctypes over later."""
		blog_app = os.path.join(frappe.get_app_path("frappe"), "..", "..", "blog")
		if not os.path.isdir(blog_app):
			self.skipTest("frappe/blog is not in this bench")
		layout = ("Section Break", "Column Break", "Tab Break")
		for doctype in blog_compat.BLOG_DOCTYPES:
			name = frappe.scrub(doctype)
			found = glob.glob(os.path.join(blog_app, "**", "doctype", name, f"{name}.json"), recursive=True)
			if not found:
				self.skipTest(f"{doctype} not in this frappe/blog version")
			with open(found[0]) as f:
				app = json.load(f)
			ours = {
				(f["fieldname"], f["fieldtype"], f.get("options"))
				for f in blog_compat.load_definition(doctype)["fields"]
				if f["fieldtype"] not in layout
			}
			theirs = {
				(f["fieldname"], f["fieldtype"], f.get("options"))
				for f in app["fields"]
				if f["fieldtype"] not in layout
			}
			self.assertEqual(ours, theirs, doctype)


class TestProvider(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_cache()

	def test_provider_states(self):
		self.assertEqual(blog_compat.provider_of("ToDo"), "app")
		self.assertEqual(blog_compat.provider_of("BNS No Such DocType"), "missing")

	def test_orphaned_v15_definition_is_adopted_not_lost(self):
		if blog_compat.provider_of("Blog Category") != "bns":
			self.skipTest("an app provides the blog doctypes on this site")
		# What an upgraded v15 database holds: a standard doctype whose file is gone.
		frappe.db.set_value(
			"DocType", "Blog Category", {"custom": 0, "has_web_view": 1}, update_modified=False
		)
		frappe.clear_cache(doctype="Blog Category")
		self.assertEqual(blog_compat.provider_of("Blog Category"), "orphan")

		actions = blog_compat.ensure_blog_doctypes()

		self.assertEqual(actions["Blog Category"], "adopted")
		row = frappe.db.get_value(
			"DocType", "Blog Category", ["custom", "has_web_view", "module"], as_dict=True
		)
		self.assertEqual((row.custom, row.has_web_view, row.module), (1, 0, "Website"))

	def test_ensure_is_idempotent(self):
		first = blog_compat.ensure_blog_doctypes()
		self.assertTrue(set(first.values()) <= {"app", "bns"}, first)
		self.assertEqual(blog_compat.ensure_blog_doctypes(), first)

	def test_bns_fixture_field_is_on_blog_post(self):
		# The one BNS custom field on Blog Post; without the doctype Frappe skips the whole fixture.
		self.assertTrue(frappe.get_meta("Blog Post").has_field("bns_websites"))


class BNSBlogTestCase(FrappeTestCase):
	def setUp(self):
		if blog_compat.provider_of("Blog Post") != "bns":  # DB state, not the function under test
			self.skipTest("BNS does not provide the blog doctypes on this site (v15 or frappe/blog)")
		frappe.set_user("Administrator")
		if not frappe.db.exists("Blogger", "bns-compat"):
			frappe.get_doc(
				{"doctype": "Blogger", "short_name": "bns-compat", "full_name": "Compat Writer"}
			).insert()
		if not frappe.db.exists("Blog Category", CATEGORY):
			frappe.get_doc(
				{"doctype": "Blog Category", "title": "BNS Compat Category", "published": 1}
			).insert()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def post(self, title, **values):
		doc = frappe.get_doc(
			{
				"doctype": "Blog Post",
				"title": title,
				"blog_category": CATEGORY,
				"blogger": "bns-compat",
				"content_type": "Rich Text",
				"content": "<p>Short body.</p>",
				**values,
			}
		)
		return doc.insert()


class TestV15SaveBehaviour(BNSBlogTestCase):
	def test_category_name_and_route(self):
		self.assertEqual(frappe.db.get_value("Blog Category", CATEGORY, "route"), f"blog/{CATEGORY}")

	def test_published_post_gets_v15_name_route_and_dates(self):
		doc = self.post("Teak & Rain: A Field Guide!", published=1)
		self.assertEqual(doc.name, "teak-rain-a-field-guide")
		self.assertEqual(doc.route, f"blog/{CATEGORY}/teak-rain-a-field-guide")
		self.assertEqual(str(doc.published_on), frappe.utils.today())

	def test_unpublished_post_gets_no_route_or_date(self):
		doc = self.post("Draft Notes")
		self.assertFalse(doc.route)
		self.assertFalse(doc.published_on)

	def test_route_is_trimmed_like_v15(self):
		doc = self.post("Custom Route", published=1, route="/custom/route/.")
		self.assertEqual(doc.route, "custom/route")
		# Titles are capped at 140 characters; category route + slug still runs past 139.
		long = self.post("L" + "o" * 130 + "ng", published=1)
		self.assertGreater(len(f"blog/{CATEGORY}/{long.name}"), 139)
		self.assertEqual(len(long.route), 139)

	def test_intro_and_meta_defaults(self):
		body = "<p><b>Bold</b> " + "x" * 300 + "</p>"
		doc = self.post("Intro Check", content=body)
		self.assertNotIn("<", doc.blog_intro)
		self.assertLessEqual(len(doc.blog_intro), 200)
		self.assertEqual(doc.meta_title, "Intro Check")
		self.assertEqual(doc.meta_description, doc.blog_intro[:140])
		titled = self.post("T" * 80, meta_title="M" * 80, meta_description="D" * 200)
		self.assertEqual((len(titled.meta_title), len(titled.meta_description)), (60, 140))

	def test_read_time_rich_text_and_markdown(self):
		self.assertEqual(self.post("Read RT", content="<p>" + "word " * 600 + "</p>").read_time, 3)
		md = self.post("Read MD", content_type="Markdown", content="", content_md="word " * 251)
		self.assertEqual(md.read_time, 2)

	def test_featured_needs_a_cover_and_is_unique(self):
		with self.assertRaisesRegex(frappe.ValidationError, "cover image"):
			self.post("Featured Without Cover", featured=1)
		first = self.post("First Featured", featured=1, meta_image="/files/cover-1.png")
		self.post("Second Featured", featured=1, meta_image="/files/cover-2.png")
		self.assertEqual(frappe.db.get_value("Blog Post", first.name, "featured"), 0)

	def test_duplicate_title_is_refused_like_v15(self):
		self.post("Same Title")
		with self.assertRaises(frappe.DuplicateEntryError):
			self.post("Same Title")

	def test_blogger_restricts_user_and_claims_their_older_posts(self):
		# As in v15, the user must already exist: links are checked before validate runs.
		email = "bns-compat-writer@example.com"
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "Writer"}).insert()
		legacy = self.post("Legacy Post")
		frappe.db.set_value("Blog Post", legacy.name, {"owner": email, "blogger": ""})  # pre-blogger data

		blogger = frappe.get_doc(
			{"doctype": "Blogger", "short_name": "bns-compat-2", "full_name": "Writer Two", "user": email}
		).insert()

		self.assertEqual(frappe.db.get_value("Blog Post", legacy.name, "blogger"), blogger.name)
		self.assertTrue(
			frappe.db.exists(
				"User Permission", {"user": email, "allow": "Blogger", "for_value": blogger.name}
			)
		)


class TestInertWhenAnAppProvides(BNSBlogTestCase):
	def test_hooks_do_nothing_when_bns_is_not_the_provider(self):
		with patch.object(blog_compat, "bns_provides", return_value=False):
			doc = frappe.get_doc(
				{"doctype": "Blog Category", "title": "Inert Check", "published": 1}
			).insert()
		self.assertNotEqual(doc.name, "inert-check")  # BNS naming did not run
		self.assertFalse(doc.route)


class TestWebViewGuard(unittest.TestCase):
	def test_missing_blog_doctypes_never_break_guest_pages(self):
		frappe.cache.delete_value(web_view_guard.WEB_ROUTES_CACHE_KEY)
		with patch.object(web_view_guard.frappe, "get_all", side_effect=frappe.DoesNotExistError):
			self.assertEqual(web_view_guard._blog_web_routes(), set())
