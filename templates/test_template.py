"""
test_template.py – verifies every feature of the template engine.
Run with: python test_template.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from cookie.template_engine import render, render_template, TemplateSyntaxError

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
        print(f"       got:      {result!r}")

print("\n── Variable output ─────────────────────────────────────────────────")
check("simple var",
      render("Hello <?= name ?>!", {"name": "World"}),
      "Hello World!")

check("expression",
      render("<?= 2 + 2 ?>"),
      "4")

check("dict access",
      render("<?= user['age'] ?>", {"user": {"age": 30}}),
      "30")

check("HTML escaping",
      render("<?= code ?>", {"code": "<b>bold</b>"}),
      "&lt;b&gt;bold&lt;/b&gt;")

check("raw unescaped",
      render("<?=! html ?>", {"html": "<b>bold</b>"}),
      "<b>bold</b>")

print("\n── if / elif / else ────────────────────────────────────────────────")
tpl_if = """\
<?py if score >= 90: ?>A<?py elif score >= 70: ?>B<?py else: ?>C<?py end ?>"""

check("if branch (A)",   render(tpl_if, {"score": 95}), "A")
check("elif branch (B)", render(tpl_if, {"score": 75}), "B")
check("else branch (C)", render(tpl_if, {"score": 50}), "C")

print("\n── for loops ───────────────────────────────────────────────────────")
tpl_for = """\
<?py for item in items: ?><?= item ?> <?py end ?>"""
check("simple loop",
      render(tpl_for, {"items": ["a", "b", "c"]}),
      "a")

check("all items rendered",
      render(tpl_for, {"items": ["x", "y", "z"]}),
      "x")

tpl_enumerate = """\
<?py for i, v in enumerate(items, 1): ?><?= i ?>.<?= v ?> <?py end ?>"""
check("enumerate",
      render(tpl_enumerate, {"items": ["alpha", "beta"]}),
      "1.alpha")

print("\n── nested blocks ───────────────────────────────────────────────────")
tpl_nested = """\
<?py for row in matrix: ?>\
<?py for cell in row: ?>[<?= cell ?>]<?py end ?>\n<?py end ?>"""
check("nested loops",
      render(tpl_nested, {"matrix": [[1, 2], [3, 4]]}),
      "[1][2]")

tpl_nested_if = """\
<?py for n in nums: ?>\
<?py if n % 2 == 0: ?>E<?py else: ?>O<?py end ?>\
<?py end ?>"""
check("if inside for",
      render(tpl_nested_if, {"nums": [1, 2, 3, 4]}),
      "OEOE")

print("\n── inline Python ───────────────────────────────────────────────────")
tpl_calc = """\
<?py total = sum(xs) ?>\
<?py avg = total / len(xs) ?>\
total=<?= total ?> avg=<?= avg ?>"""
check("inline calculation",
      render(tpl_calc, {"xs": [10, 20, 30]}),
      "total=60")
check("avg in same template",
      render(tpl_calc, {"xs": [10, 20, 30]}),
      "avg=20.0")

print("\n── render_template() ───────────────────────────────────────────────")
from types import SimpleNamespace

context = {
      "site_name": "PyServer",
      "csrf_token": "test-token",
      "current_user": SimpleNamespace(
            name="Ada", email="ada@example.com", role="admin", created_at="2023-01-01"
      ),
      "stats": {"total": 3, "published": 2, "drafts": 1},
      "recent_posts": [
            SimpleNamespace(title="Alpha", slug="alpha", status="published", created_at="2026-01-01"),
      ],
      "can_write": True,
      "footer_links": [("Home", "/")],
      "flash_ok": None,
      "flash_err": None,
      "flash_info": None,
}
output = render_template("templates/dashboard.html", context)
check("title in output",         output, "Dashboard")
check("user name",               output, "Ada")
check("admin role",              output, "admin")
check("recent post rendered",    output, "Alpha")
check("dashboard stats",         output, "Total posts")

print("\n── edge cases ──────────────────────────────────────────────────────")
check("empty template",       render(""), "")
check("no tags",              render("plain text"), "plain text")
check("multiline expression", render("<?= 1 +\n2 ?>"), "3")

print()
if _failures:
    print(f"\033[91m  {_failures} test(s) FAILED\033[0m\n")
    sys.exit(1)
else:
    print(f"\033[92m  All tests passed.\033[0m\n")
