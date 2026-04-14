"""
core/template_engine.py – custom template engine with includes & layouts.

Syntax
------
  <?= expr ?>              Output expr (HTML-escaped).
  <?=! expr ?>             Output expr (raw HTML, unescaped).
  <?py code ?>             Execute arbitrary Python.
  <?py end ?>              Close the current if/for/while block.

  <?py include("file") ?>              Include a partial, inheriting context.
  <?py include("file", key=val) ?>     Include with extra context variables.

  <?py extend("layout.html") ?>        Declare a layout parent.
  <?py block "name": ?>                Open a named content block.
  <?py endblock ?>                     Close a named content block.

How it works
------------
  1. Tokenise  – regex splits source into (type, value) pairs.
  2. Resolve includes – partials are inlined, carrying an include-stack
     for circular-reference detection.
  3. Resolve layouts – if extend() is declared, the child's blocks are
     spliced into the parent layout.
  4. Compile  – tokens → a Python function with correct indentation.
  5. Execute  – exec() the function with context vars as locals.

Public API
----------
  render(source, context, base_dir)       → str
  render_template(file_path, context)     → str
  TemplateEngine(base_dir)                → reusable engine
"""

from __future__ import annotations

import os
import re
import textwrap
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Token types
# ─────────────────────────────────────────────────────────────────────────────

_T_TEXT   = "text"
_T_EXPR   = "expr"       # <?= expr ?>
_T_RAWEX  = "raw_expr"   # <?=! expr ?>
_T_CODE   = "code"       # <?py code ?>
_T_ASSIGN = "assign"     # synthetic: "key=val, key2=val2" → local vars
_T_INCLUDE = "include"   # <?py include("f") ?>  – resolved before compile
_T_EXTEND  = "extend"    # <?py extend("layout") ?>
_T_BLOCK   = "block"     # <?py block "name": ?>
_T_ENDBLK  = "endblock"  # <?py endblock ?>

_TAG_RE = re.compile(
    r"<\?=!(?P<raw>.*?)\?>"
    r"|<\?=(?P<expr>.*?)\?>"
    r"|<\?py(?P<code>.*?)\?>",
    re.DOTALL,
)

_RE_INCLUDE = re.compile(
    r"""^\s*include\s*\(\s*['"](?P<path>[^'"]+)['"]\s*(?P<extra>(?:,.*)?)\)\s*$"""
)
_RE_EXTEND  = re.compile(r"""^\s*extend\s*\(\s*['"](?P<path>[^'"]+)['"]\s*\)\s*$""")
_RE_BLOCK   = re.compile(r"""^\s*block\s+['"](?P<name>[^'"]+)['"]\s*:\s*$""")
_RE_ENDBLK  = re.compile(r"""^\s*endblock\s*$""")


# ─────────────────────────────────────────────────────────────────────────────
# Tokeniser
# ─────────────────────────────────────────────────────────────────────────────

def _tokenise(source: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    for m in _TAG_RE.finditer(source):
        if m.start() > pos:
            tokens.append((_T_TEXT, source[pos:m.start()]))

        if m.group("raw") is not None:
            tokens.append((_T_RAWEX, m.group("raw").strip()))
        elif m.group("expr") is not None:
            tokens.append((_T_EXPR, m.group("expr").strip()))
        else:
            code = m.group("code").strip()
            if _RE_INCLUDE.match(code):
                tokens.append((_T_INCLUDE, code))
            elif _RE_EXTEND.match(code):
                tokens.append((_T_EXTEND, code))
            elif _RE_BLOCK.match(code):
                tokens.append((_T_BLOCK, code))
            elif _RE_ENDBLK.match(code):
                tokens.append((_T_ENDBLK, code))
            else:
                tokens.append((_T_CODE, code))
        pos = m.end()

    if pos < len(source):
        tokens.append((_T_TEXT, source[pos:]))
    return tokens


# ─────────────────────────────────────────────────────────────────────────────
# Include resolution  (pre-compile pass)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_kwargs(extra_str: str) -> dict[str, str]:
    """
    Parse "key=expr, key2=expr2" into {"key": "expr", "key2": "expr2"}.
    Simple but sufficient: splits on top-level commas.
    """
    result: dict[str, str] = {}
    depth = 0
    current = ""
    for ch in extra_str:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            k, _, v = current.partition("=")
            result[k.strip()] = v.strip()
            current = ""
        else:
            current += ch
    if current.strip():
        k, _, v = current.partition("=")
        result[k.strip()] = v.strip()
    return result


def _resolve_includes(
    tokens: list[tuple[str, str]],
    base_dir: str,
    stack: list[str],
) -> list[tuple[str, str]]:
    """
    Replace every _T_INCLUDE token with the inlined tokens of the partial.
    Extra kwargs become _T_ASSIGN tokens that emit direct local-variable
    assignments in the compiled function.
    """
    out: list[tuple[str, str]] = []

    for kind, value in tokens:
        if kind != _T_INCLUDE:
            out.append((kind, value))
            continue

        m = _RE_INCLUDE.match(value)
        rel_path = m.group("path")
        extra_str = (m.group("extra") or "").lstrip(",").strip()

        abs_path = os.path.normpath(os.path.join(base_dir, rel_path))

        # ── Circular-include guard ────────────────────────────────────────
        if abs_path in stack:
            chain = " → ".join(os.path.basename(p) for p in stack)
            raise TemplateIncludeError(
                f"Circular include: {chain} → {os.path.basename(abs_path)}"
            )
        if not os.path.isfile(abs_path):
            raise TemplateIncludeError(f"Included template not found: {abs_path}")

        # ── Extra kwargs → _T_ASSIGN tokens (resolved at compile time) ────
        kwargs = _parse_kwargs(extra_str) if extra_str else {}
        if kwargs:
            # Save original values, inject new ones
            for k, v in kwargs.items():
                out.append((_T_ASSIGN, f"_save_{k} = {k} if '{k}' in dir() else None"))
                out.append((_T_ASSIGN, f"{k} = {v}"))

        # ── Inline the partial ────────────────────────────────────────────
        with open(abs_path, encoding="utf-8") as fh:
            partial_source = fh.read()

        partial_tokens = _tokenise(partial_source)
        partial_dir    = os.path.dirname(abs_path)
        resolved = _resolve_includes(partial_tokens, partial_dir, stack + [abs_path])
        out.extend(resolved)

        # ── Restore overwritten vars ──────────────────────────────────────
        if kwargs:
            for k in kwargs:
                out.append((_T_ASSIGN, f"{k} = _save_{k}"))

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Layout (extend) resolution  (pre-compile pass)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_blocks(tokens: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """Walk tokens; return {block_name: [contained tokens]}."""
    blocks: dict[str, list] = {"": []}
    current = ""
    depth   = 0

    for kind, value in tokens:
        if kind == _T_BLOCK:
            m = _RE_BLOCK.match(value)
            name = m.group("name")
            if depth == 0:
                current = name
                blocks.setdefault(name, [])
            depth += 1
        elif kind == _T_ENDBLK:
            depth -= 1
            if depth == 0:
                current = ""
        else:
            blocks[current].append((kind, value))

    return blocks


def _inject_blocks(
    layout_tokens: list[tuple[str, str]],
    child_blocks: dict[str, list[tuple[str, str]]],
) -> list[tuple[str, str]]:
    """Splice child blocks into layout, keeping layout defaults for missing blocks."""
    out:     list[tuple[str, str]] = []
    current: str | None = None
    depth   = 0
    buf:     list[tuple[str, str]] = []

    for kind, value in layout_tokens:
        if kind == _T_BLOCK:
            m = _RE_BLOCK.match(value)
            name = m.group("name")
            if depth == 0:
                current = name
                buf = []
            depth += 1
        elif kind == _T_ENDBLK:
            depth -= 1
            if depth == 0:
                out.extend(child_blocks.get(current, buf))
                current = None
                buf = []
        elif current is not None:
            buf.append((kind, value))
        else:
            out.append((kind, value))

    return out


def _resolve_layout(
    tokens: list[tuple[str, str]],
    base_dir: str,
    stack: list[str],
) -> list[tuple[str, str]]:
    """If tokens declare extend(), load the layout and splice child blocks in."""
    extend_token = None
    for kind, value in tokens:
        if kind == _T_TEXT and not value.strip():
            continue
        if kind == _T_EXTEND:
            extend_token = value
        break

    if extend_token is None:
        return tokens

    m = _RE_EXTEND.match(extend_token)
    layout_path = os.path.normpath(os.path.join(base_dir, m.group("path")))

    if layout_path in stack:
        chain = " → ".join(os.path.basename(p) for p in stack)
        raise TemplateIncludeError(
            f"Circular layout: {chain} → {os.path.basename(layout_path)}"
        )
    if not os.path.isfile(layout_path):
        raise TemplateIncludeError(f"Layout not found: {layout_path}")

    child_blocks = _extract_blocks(tokens)

    with open(layout_path, encoding="utf-8") as fh:
        layout_source = fh.read()

    layout_tokens = _tokenise(layout_source)
    layout_dir    = os.path.dirname(layout_path)
    layout_tokens = _resolve_includes(layout_tokens, layout_dir, stack + [layout_path])
    layout_tokens = _resolve_layout(layout_tokens, layout_dir, stack + [layout_path])

    return _inject_blocks(layout_tokens, child_blocks)


# ─────────────────────────────────────────────────────────────────────────────
# Code generator
# ─────────────────────────────────────────────────────────────────────────────

_BLOCK_OPEN_RE = re.compile(
    r"^(if|elif|else|for|while|with|try|except|finally|def|class)\b.*:$"
)
_BLOCK_CONT_RE = re.compile(r"^(elif|else|except|finally)\b")
_INDENT = "    "


def _compile(tokens: list[tuple[str, str]], context_keys: list[str]) -> str:
    """
    Translate tokens into:

        import html as _html
        def _render(_ctx):
            _out  = []
            title = _ctx.get('title')   ← one line per context key
            ...                         ← token-derived lines
            return ''.join(_out)
    """
    body:  list[str] = []
    depth: int = 1

    def emit(line: str) -> None:
        body.append(f"{_INDENT * depth}{line}")

    # Unpack every context key as a real local variable
    for key in context_keys:
        emit(f"{key} = _ctx.get({key!r})")

    for kind, value in tokens:

        # Pre-compile tokens that were fully resolved – skip any stragglers
        if kind in (_T_EXTEND, _T_BLOCK, _T_ENDBLK, _T_INCLUDE):
            continue

        if kind == _T_ASSIGN:
            # Direct Python assignment emitted verbatim
            emit(value.strip())

        elif kind == _T_TEXT:
            parts = value.split("\n")
            for i, part in enumerate(parts):
                chunk = part if i == len(parts) - 1 else part + "\n"
                if chunk:
                    emit(f"_out.append({repr(chunk)})")

        elif kind == _T_EXPR:
            emit(f"_out.append(_html.escape(str({value})))")

        elif kind == _T_RAWEX:
            emit(f"_out.append(str({value}))")

        elif kind == _T_CODE:
            block = textwrap.dedent(value)
            for raw_line in block.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line in ("end", "end;"):
                    depth = max(1, depth - 1)
                    continue
                if _BLOCK_CONT_RE.match(line):
                    depth = max(1, depth - 1)
                emit(line)
                if _BLOCK_OPEN_RE.match(line):
                    depth += 1

    emit("return ''.join(_out)")

    return "\n".join([
        "import html as _html",
        "def _render(_ctx):",
        f"{_INDENT}_out = []",
        *body,
    ])


# ─────────────────────────────────────────────────────────────────────────────
# Executor
# ─────────────────────────────────────────────────────────────────────────────

def _execute(code_str: str, context: dict) -> str:
    globs: dict[str, Any] = {"__builtins__": __builtins__}
    try:
        exec(compile(code_str, "<template>", "exec"), globs)
    except SyntaxError as exc:
        raise TemplateSyntaxError(str(exc), code_str) from exc
    try:
        return globs["_render"](context)
    except Exception as exc:
        raise TemplateRuntimeError(str(exc)) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────

class TemplateSyntaxError(Exception):
    def __init__(self, message: str, generated_code: str = ""):
        super().__init__(message)
        self.generated_code = generated_code

class TemplateRuntimeError(Exception):
    pass

class TemplateIncludeError(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

class TemplateEngine:
    """
    Reusable engine bound to a base directory.
    All relative paths in include() / extend() resolve from base_dir.
    """

    def __init__(self, base_dir: str = "."):
        self.base_dir = os.path.abspath(base_dir)

    def render(self, source: str, context: dict | None = None,
               source_path: str | None = None) -> str:
        ctx      = dict(context or {})
        base     = os.path.dirname(source_path) if source_path else self.base_dir
        src_key  = source_path or "<string>"
        tokens   = _tokenise(source)
        tokens   = _resolve_includes(tokens, base, [src_key])
        tokens   = _resolve_layout(tokens, base, [src_key])
        code_str = _compile(tokens, list(ctx.keys()))
        return _execute(code_str, ctx)

    def render_file(self, rel_path: str, context: dict | None = None) -> str:
        abs_path = os.path.normpath(os.path.join(self.base_dir, rel_path))
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"Template not found: {abs_path}")
        with open(abs_path, encoding="utf-8") as fh:
            source = fh.read()
        return self.render(source, context, source_path=abs_path)


def render(template_str: str, context: dict | None = None,
           base_dir: str | None = None) -> str:
    """Compile *template_str* and render it with *context*."""
    return TemplateEngine(base_dir or os.getcwd()).render(template_str, context)


def render_template(file_path: str, context: dict | None = None) -> str:
    """Load *file_path*, compile it, and render with *context*."""
    abs_path = os.path.abspath(file_path)
    engine   = TemplateEngine(base_dir=os.path.dirname(abs_path))
    return engine.render_file(os.path.basename(abs_path), context)
