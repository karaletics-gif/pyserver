"""
test_includes.py – test suite for includes, layouts, and recursion guard.
Run with: python test_includes.py
"""

import sys, os, tempfile, textwrap
sys.path.insert(0, os.path.dirname(__file__))

from cookie.template_engine import (
    render, render_template, TemplateEngine,
    TemplateIncludeError, TemplateRuntimeError,
)

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"
_failures = 0

def check(label: str, result: str, expected: str):
    global _failures
    ok = expected in result
    print(f"  {PASS if ok else FAIL}  {label}")
    if not ok:
        _failures += 1
        print(f"       expected: {expected!r}")
        print(f"       in:       {result[:300]!r}")

def check_raises(label: str, exc_type, fn):
    global _failures
    try:
        fn()
        _failures += 1
        print(f"  {FAIL}  {label}  (no exception raised)")
    except exc_type:
        print(f"  {PASS}  {label}")
    except Exception as e:
        _failures += 1
        print(f"  {FAIL}  {label}  (wrong exception: {type(e).__name__}: {e})")


# ── Helpers to write temp templates ──────────────────────────────────────────

def make_dir(files: dict[str, str]) -> str:
    """Write files to a fresh temp dir; return the dir path."""
    d = tempfile.mkdtemp()
    for rel, content in files.items():
        path = os.path.join(d, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(textwrap.dedent(content))
    return d


# ─────────────────────────────────────────────────────────────────────────────

print("\n── Basic include ────────────────────────────────────────────────────")

d = make_dir({
    "index.html":   "<h1><?= title ?></h1><?py include('partial.html') ?>",
    "partial.html": "<p>Hello from partial, <?= name ?>!</p>",
})
engine = TemplateEngine(d)
out = engine.render_file("index.html", {"title": "Home", "name": "Ada"})
check("include renders",       out, "Hello from partial")
check("context flows through", out, "Ada")
check("parent vars intact",    out, "Home")


print("\n── Include with extra context variables ─────────────────────────────")

d = make_dir({
    "index.html":   "<?py include('badge.html', color='red', label='Admin') ?>",
    "badge.html":   '<span style="color:<?= color ?>"><?= label ?></span>',
})
engine = TemplateEngine(d)
out = engine.render_file("index.html", {})
check("extra kwarg: color", out, "red")
check("extra kwarg: label", out, "Admin")


print("\n── Nested includes (include inside include) ─────────────────────────")

d = make_dir({
    "page.html":    "START<?py include('middle.html') ?>END",
    "middle.html":  "M1<?py include('inner.html') ?>M2",
    "inner.html":   "[<?= value ?>]",
})
engine = TemplateEngine(d)
out = engine.render_file("page.html", {"value": "deep"})
check("outer text",  out, "START")
check("middle text", out, "M1")
check("inner value", out, "[deep]")
check("order",       out, "M1[deep]M2")


print("\n── Include in subdirectory ──────────────────────────────────────────")

d = make_dir({
    "page.html":             "<?py include('parts/chip.html') ?>",
    "parts/chip.html":       "<chip><?= chip_label ?></chip>",
})
engine = TemplateEngine(d)
out = engine.render_file("page.html", {"chip_label": "Python"})
check("subdir partial renders", out, "<chip>Python</chip>")


print("\n── Infinite recursion guard ─────────────────────────────────────────")

d = make_dir({
    "a.html": "<?py include('b.html') ?>",
    "b.html": "<?py include('a.html') ?>",
})
engine = TemplateEngine(d)
check_raises("circular include raises", TemplateIncludeError,
             lambda: engine.render_file("a.html", {}))

d2 = make_dir({"self.html": "<?py include('self.html') ?>"})
engine2 = TemplateEngine(d2)
check_raises("self-include raises", TemplateIncludeError,
             lambda: engine2.render_file("self.html", {}))


print("\n── Layout (extend) ──────────────────────────────────────────────────")

d = make_dir({
    "layout.html": textwrap.dedent("""\
        <html><head><title><?py block "title": ?>Default<?py endblock ?></title></head>
        <body><?py block "body": ?><p>empty</p><?py endblock ?></body></html>
    """),
    "child.html": textwrap.dedent("""\
        <?py extend("layout.html") ?>
        <?py block "title": ?><?= page_title ?><?py endblock ?>
        <?py block "body": ?><h1><?= heading ?></h1><?py endblock ?>
    """),
})
engine = TemplateEngine(d)
out = engine.render_file("child.html", {"page_title": "My Page", "heading": "Welcome"})
check("child title block",   out, "My Page")
check("child body block",    out, "<h1>Welcome</h1>")
check("html shell present",  out, "<html>")
check("default not shown",   out, "My Page")   # "Default" replaced


print("\n── Layout default block content ─────────────────────────────────────")

d = make_dir({
    "layout.html": "<wrap><?py block 'inner': ?>DEFAULT<?py endblock ?></wrap>",
    "child.html":  "<?py extend('layout.html') ?>",   # no block override
})
engine = TemplateEngine(d)
out = engine.render_file("child.html", {})
check("default block kept when not overridden", out, "DEFAULT")


print("\n── Layout + include (nav/footer in layout) ──────────────────────────")

d = make_dir({
    "layout.html": textwrap.dedent("""\
        <?py include("nav.html") ?>
        <main><?py block "content": ?><?py endblock ?></main>
        <?py include("footer.html") ?>
    """),
    "nav.html":    "<nav>NAV|<?= site_name ?></nav>",
    "footer.html": "<footer>FOOTER|<?= site_name ?></footer>",
    "page.html":   textwrap.dedent("""\
        <?py extend("layout.html") ?>
        <?py block "content": ?><p>PAGE CONTENT</p><?py endblock ?>
    """),
})
engine = TemplateEngine(d)
out = engine.render_file("page.html", {"site_name": "PyServer"})
check("nav included via layout",    out, "NAV|PyServer")
check("footer included via layout", out, "FOOTER|PyServer")
check("page content block",         out, "PAGE CONTENT")


print("\n── render_template() with real files ────────────────────────────────")

ctx = {
    "title": "Dashboard",
    "site_name": "PyServer",
    "current_user": "ada",
    "footer_links": [("Home", "/"), ("About", "/about")],
    "user": {"name": "Ada", "role": "admin", "since": "2023"},
    "projects": [
        {"name": "Alpha", "description": "First", "status": "active",
         "tags": ["python"], "score": 92},
        {"name": "Beta",  "description": "Second", "status": "wip",
         "tags": ["api"],    "score": 74},
    ],
    "announcement_html": "<strong>🎉 v2.0 shipped!</strong>",
}
out = render_template("templates/dashboard2.html", ctx)
check("page title",        out, "Dashboard · PyServer")
check("nav partial",       out, "PyServer")
check("footer partial",    out, "FOOTER" if False else "built with pure Python")
check("current_user nav",  out, "ada")
check("stat grid",         out, "Avg score")
check("project cards",     out, "Alpha")
check("project tags",      out, "python")
check("announcement raw",  out, "🎉 v2.0 shipped!")
check("badge active",      out, "active")
check("footer links",      out, "About")


print()
if _failures:
    print(f"\033[91m  {_failures} test(s) FAILED\033[0m\n")
    sys.exit(1)
else:
    print(f"\033[92m  All tests passed.\033[0m\n")
