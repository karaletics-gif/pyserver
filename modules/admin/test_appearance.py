"""Tests for theme zip install, child themes and safe deletion (temporary themes folder)."""

import io
import os
import shutil
import tempfile
import unittest
import zipfile

from blocks.theme_loader import ThemeError, ThemeLoader
from cookie.hooks import HookRegistry


def make_zip(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


PARENT = {
    "base/theme.py": 'THEME_NAME = "Base"\n@hooks.filter("theme.body_class")\ndef c(v): return v + " base"\n',
    "base/index.html": "<html><head></head><body>PARENT <?= theme_body_class ?></body></html>",
    "base/partials/nav.html": "parent-nav",
    "base/assets/style.css": "body{}",
}


class ThemeLoaderTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.themes = os.path.join(self.root, "themes")
        os.makedirs(self.themes)
        self.loader = ThemeLoader(self.themes, hooks=HookRegistry(),
                                  cache_dir=os.path.join(self.root, "cache"))
        self.loader.install_zip(make_zip(PARENT))

    def test_install_and_activate(self):
        self.assertIn("base", self.loader.discover())
        self.loader.activate("base")
        self.assertIn("PARENT", self.loader.render("index", {}))

    def test_rejects_unsafe_and_invalid_archives(self):
        for files in ({"../evil/theme.py": "x=1", "evil/index.html": "x"},
                      {"readme.txt": "no theme"},
                      {"bad/theme.py": "def (", "bad/index.html": "x"}):
            with self.assertRaises(ThemeError):
                self.loader.install_zip(make_zip(files))
        with self.assertRaises(ThemeError):
            self.loader.install_zip(b"not a zip")
        with self.assertRaises(ThemeError):
            self.loader.install_zip(make_zip(PARENT))  # already installed
        self.assertEqual(self.loader.discover(), ["base"])

    def test_child_theme_overrides_parent_and_inherits_rest(self):
        slug = self.loader.create_child_theme("base", "My Child")
        with open(os.path.join(self.themes, slug, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<html><head></head><body>CHILD <?= theme_body_class ?></body></html>")
        theme = self.loader.activate(slug)
        self.assertTrue(theme.is_child)
        html = self.loader.render("index", {})
        self.assertIn("CHILD", html)
        self.assertIn("base", html)  # parent's hook still runs
        self.assertTrue(os.path.isfile(os.path.join(theme.template_dir, "partials", "nav.html")))
        self.assertIsNotNone(self.loader.serve_asset(slug, "style.css"))  # parent asset fallback

    def test_child_without_template_uses_parent(self):
        slug = self.loader.create_child_theme("base", "Plain Child")
        self.loader.activate(slug)
        self.assertIn("PARENT", self.loader.render("index", {}))

    def test_missing_parent_cannot_activate(self):
        self.loader.install_zip(make_zip({"orphan/theme.py": 'THEME_PARENT = "gone"\n'}))
        with self.assertRaises(ThemeError):
            self.loader.activate("orphan")

    def test_delete_rules(self):
        child = self.loader.create_child_theme("base", "Kid")
        self.loader.activate(child)
        with self.assertRaises(ThemeError):
            self.loader.delete_theme(child)   # active
        with self.assertRaises(ThemeError):
            self.loader.delete_theme("base")  # parent of active
        self.loader.activate("base")
        self.loader.delete_theme(child)
        self.assertNotIn(child, self.loader.discover())

    def test_asset_traversal_blocked(self):
        self.assertIsNone(self.loader.serve_asset("base", "../theme.py"))
        self.assertIsNone(self.loader.serve_asset("..", "x"))


if __name__ == "__main__":
    unittest.main()
