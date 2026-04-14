"""
core/hooks.py – a clean hook & filter system (WordPress-style, better names).

Concepts
--------
Hook   : fire-and-forget.  run_hook() calls every registered function;
         return values are discarded.
Filter : value-transforming.  apply_filters() passes a value through a
         chain of functions, each receiving the output of the previous one,
         and returns the final result.

Both support priority ordering (lower number = runs first) and multiple
functions per name.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from typing import Any, Callable


# ── Internal registry entry ──────────────────────────────────────────────────

class _Entry:
    """One registered callable with a priority."""

    __slots__ = ("priority", "_seq", "fn")

    _counter = 0  # tie-breaker so equal-priority hooks run in insertion order

    def __init__(self, priority: int, fn: Callable):
        self.priority = priority
        _Entry._counter += 1
        self._seq = _Entry._counter
        self.fn = fn

    # heapq uses < for ordering
    def __lt__(self, other: "_Entry") -> bool:
        return (self.priority, self._seq) < (other.priority, other._seq)


# ── Registry ─────────────────────────────────────────────────────────────────

class HookRegistry:
    """
    Central in-memory store for hooks and filters.

    Typical usage
    -------------
    hooks = HookRegistry()

    # ── action hooks ──────────────────────────────────────────────────────────
    @hooks.hook("request.start")
    def log_request(request):
        print(f"→ {request.method} {request.path}")

    hooks.run_hook("request.start", request)

    # ── filters ───────────────────────────────────────────────────────────────
    @hooks.filter("response.body")
    def inject_banner(body):
        return body + "<!-- served by pyserver -->"

    body = hooks.apply_filters("response.body", raw_body)
    """

    def __init__(self):
        # name → min-heap of _Entry objects
        self._hooks:   dict[str, list[_Entry]] = defaultdict(list)
        self._filters: dict[str, list[_Entry]] = defaultdict(list)

    # ── Hooks (actions) ──────────────────────────────────────────────────────

    def add_hook(self, name: str, fn: Callable, priority: int = 10) -> None:
        """Register *fn* to be called when *name* is fired."""
        heapq.heappush(self._hooks[name], _Entry(priority, fn))

    def run_hook(self, name: str, *args: Any, **kwargs: Any) -> None:
        """
        Call every function registered under *name* in priority order.
        Return values are ignored.
        """
        for entry in sorted(self._hooks.get(name, [])):
            entry.fn(*args, **kwargs)

    def hook(self, name: str, priority: int = 10):
        """Decorator shorthand for add_hook."""
        def decorator(fn: Callable) -> Callable:
            self.add_hook(name, fn, priority)
            return fn
        return decorator

    # ── Filters ──────────────────────────────────────────────────────────────

    def add_filter(self, name: str, fn: Callable, priority: int = 10) -> None:
        """Register *fn* as a filter stage for *name*."""
        heapq.heappush(self._filters[name], _Entry(priority, fn))

    def apply_filters(self, name: str, value: Any, *args: Any, **kwargs: Any) -> Any:
        """
        Pass *value* through every filter registered under *name* in priority
        order.  Each function receives the current value (plus any extra
        *args*/*kwargs*) and must return the (possibly modified) value.
        """
        for entry in sorted(self._filters.get(name, [])):
            value = entry.fn(value, *args, **kwargs)
        return value

    def filter(self, name: str, priority: int = 10):
        """Decorator shorthand for add_filter."""
        def decorator(fn: Callable) -> Callable:
            self.add_filter(name, fn, priority)
            return fn
        return decorator

    # ── Introspection ─────────────────────────────────────────────────────────

    def registered_hooks(self) -> dict[str, list[str]]:
        """Return a dict of hook_name → [fn_name, ...] in priority order."""
        return {
            name: [e.fn.__name__ for e in sorted(entries)]
            for name, entries in self._hooks.items()
        }

    def registered_filters(self) -> dict[str, list[str]]:
        """Return a dict of filter_name → [fn_name, ...] in priority order."""
        return {
            name: [e.fn.__name__ for e in sorted(entries)]
            for name, entries in self._filters.items()
        }

    def remove_hook(self, name: str, fn: Callable) -> bool:
        """Remove a specific function from a hook. Returns True if found."""
        return self._remove(self._hooks, name, fn)

    def remove_filter(self, name: str, fn: Callable) -> bool:
        """Remove a specific function from a filter. Returns True if found."""
        return self._remove(self._filters, name, fn)

    @staticmethod
    def _remove(store: dict, name: str, fn: Callable) -> bool:
        if name not in store:
            return False
        before = len(store[name])
        store[name] = [e for e in store[name] if e.fn is not fn]
        heapq.heapify(store[name])
        return len(store[name]) < before


# ── Global singleton (optional convenience) ───────────────────────────────────

hooks = HookRegistry()
