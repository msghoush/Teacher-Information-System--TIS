"""Mechanical discovery helpers shared by the whole-application permission audit tests.

These helpers only READ non-test source (routers, main, auth, authorization, ui_shell,
saas, templates, static js). They never import a second permission registry; they read
`permission_registry` and the real FastAPI route table.
"""
from __future__ import annotations

import ast
import inspect
import os
import re
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("TIS_SESSION_SECRET", "permission-audit-support-secret-long-enough")

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------
_EXCLUDED_PY = {"permission_registry.py"}


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def non_test_python_files():
    files = []
    for pattern in ("*.py", "routers/*.py", "saas/*.py"):
        for path in sorted(ROOT.glob(pattern)):
            if path.name in _EXCLUDED_PY:
                continue
            files.append(path)
    return files


def template_files():
    return sorted(ROOT.glob("templates/**/*.html"))


def static_js_files():
    return sorted(ROOT.glob("static/**/*.js"))


# ---------------------------------------------------------------------------
# Guard-context discovery for keys
# ---------------------------------------------------------------------------
GUARD_CALLS = frozenset(
    {
        "has_permission", "has_any_permission", "has_all_permissions",
        "require_permission", "require_any_permission", "require_all_permissions",
        "get_allowed_permission_keys", "can", "can_any", "PermissionRule",
        "EntitlementRule", "can_use_feature", "_authorize", "_has", "_allowed",
        "_can", "_has_permission", "_has_any", "_perm", "_require",
    }
)
_GUARD_KWARGS = frozenset({"permission_key", "permission_keys", "required_permissions"})
_DISPLAY_ONLY_CALLS = frozenset({"build_access_denied_response"})


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _annotate_parents(tree: ast.AST) -> None:
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._parent = parent  # type: ignore[attr-defined]


def _is_guard_context(node: ast.AST) -> bool:
    """True when a string constant is an argument of a permission guard call/rule,
    a permission_key(s)= keyword, or an `in <allowed set>` membership test."""
    cur = node
    while getattr(cur, "_parent", None) is not None:
        parent = cur._parent
        if isinstance(parent, ast.keyword) and parent.arg in _GUARD_KWARGS:
            # `permission_keys=` on a denial response only LABELS the denial; it is
            # not itself a guard, so it is not counted as a consumer.
            call = getattr(parent, "_parent", None)
            if isinstance(call, ast.Call) and _call_name(call) in _DISPLAY_ONLY_CALLS:
                return False
            return True
        if isinstance(parent, ast.Call):
            name = _call_name(parent)
            if name in _DISPLAY_ONLY_CALLS:
                return False
            if name in GUARD_CALLS or re.match(r"^_?(can|has|require|authorize|allowed)_?", name):
                return True
        if isinstance(parent, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in parent.ops):
            return True
        if isinstance(parent, ast.Assign):
            for target in parent.targets:
                if isinstance(target, ast.Name) and re.search(r"(permission|PERMISSION)", target.id):
                    return True
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            return False
        cur = parent
    return False


def discover_python_guard_files(keys):
    """key -> set(relative python file) where the literal sits in a guard context."""
    found = {key: set() for key in keys}
    wanted = set(keys)
    for path in non_test_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        _annotate_parents(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in wanted:
                if _is_guard_context(node):
                    found[node.value].add(_rel(path))
    return found


def discover_python_literal_files(keys):
    """key -> set(relative python file) where the literal appears at all (guard or not)."""
    found = {key: set() for key in keys}
    wanted = set(keys)
    for path in non_test_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in wanted:
                found[node.value].add(_rel(path))
    return found


_TEMPLATE_CAN = re.compile(r"""\bcan(?:_any)?\(([^)]*)\)""")
_QUOTED = re.compile(r"""['"]([a-z_]+\.[a-z_]+)['"]""")


def discover_template_can_files(keys):
    wanted = set(keys)
    found = {key: set() for key in keys}
    for path in template_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in _TEMPLATE_CAN.finditer(text):
            for key in _QUOTED.findall(match.group(1)):
                if key in wanted:
                    found[key].add(_rel(path))
    return found


def discover_static_js_files(keys):
    wanted = set(keys)
    found = {key: set() for key in keys}
    for path in static_js_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for key in wanted:
            if re.search(r"""['"]""" + re.escape(key) + r"""['"]""", text):
                found[key].add(_rel(path))
    return found


# ---------------------------------------------------------------------------
# Route table
# ---------------------------------------------------------------------------
def walk_routes(routes, prefix=""):
    for route in routes:
        if type(route).__name__ == "_IncludedRouter":
            yield from walk_routes(route.original_router.routes, prefix + route.include_context.prefix)
        elif getattr(route, "methods", None):
            for method in sorted(route.methods):
                if method in ("HEAD", "OPTIONS"):
                    continue
                yield method, prefix + route.path, route.endpoint
        else:
            yield "MOUNT", prefix + getattr(route, "path", ""), None


def all_routes():
    import main

    return [item for item in walk_routes(main.app.routes) if item[0] != "MOUNT"]


def sample_path(path: str) -> str:
    return re.sub(r"\{[^}:]+(:[^}]*)?\}", "1", path)


_MOD_CACHE: dict = {}


def _module_info(module):
    if module not in _MOD_CACHE:
        tree = ast.parse(inspect.getsource(module))
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        _MOD_CACHE[module] = functions
    return _MOD_CACHE[module]


def _names_in(node):
    out = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name):
            out.add(inner.id)
        elif isinstance(inner, ast.Attribute):
            out.add(inner.attr)
    return out


def _constants_in(node):
    return {
        inner.value
        for inner in ast.walk(node)
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str)
    }


def handler_closure(endpoint):
    """Names and string constants reachable from the handler through same-module helpers."""
    module = inspect.getmodule(endpoint)
    functions = _module_info(module)
    if endpoint.__name__ not in functions:
        return None, None
    seen = {endpoint.__name__}
    queue = [endpoint.__name__]
    names, constants = set(), set()
    while queue:
        current = queue.pop()
        node = functions[current]
        names |= _names_in(node)
        constants |= _constants_in(node)
        for name in _names_in(node):
            if name in functions and name not in seen:
                seen.add(name)
                queue.append(name)
    return names, constants


# ---------------------------------------------------------------------------
# Guard-capable function discovery (project wide, by function name)
# ---------------------------------------------------------------------------
CORE_PERMISSION_GUARDS = frozenset(
    {
        "has_permission", "has_any_permission", "has_all_permissions",
        "require_permission", "require_any_permission", "require_all_permissions",
        "get_allowed_permission_keys",
    }
)
PLATFORM_IDENTITY_GUARDS = frozenset(
    {
        "is_platform_user", "is_platform_owner", "is_primary_platform_owner",
        "is_platform_developer", "is_developer",
    }
)


def _module_function_map(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _closure_names(functions, start):
    seen = {start}
    queue = [start]
    names = set()
    while queue:
        current = queue.pop()
        node = functions[current]
        names |= _names_in(node)
        for name in _names_in(node):
            if name in functions and name not in seen:
                seen.add(name)
                queue.append(name)
    return names


def guard_capable_functions():
    """(permission_guard_names, platform_guard_names): project functions whose own
    same-module closure reaches a core permission guard / platform identity check."""
    permission, platform = set(CORE_PERMISSION_GUARDS), set()
    for path in non_test_python_files():
        functions = _module_function_map(path)
        for name in functions:
            names = _closure_names(functions, name)
            if names & CORE_PERMISSION_GUARDS:
                permission.add(name)
            if names & PLATFORM_IDENTITY_GUARDS or re.match(r"^_?(require|get)_platform_", name):
                platform.add(name)
    platform |= set(PLATFORM_IDENTITY_GUARDS)
    return permission, platform
