"""
Minimal offline static checker (no third-party linters installed).

Reports per file:
  UNDEF   name used but never bound in any enclosing scope, module, or builtins
  UNUSED  import never referenced (module level)
  SWALLOW `except` whose body is only `pass` / `continue`
  BARE    bare `except:`
  REDEF   function defined twice in the same scope (later one silently wins)
Usage: python scripts/static_check.py [paths...]
"""
import ast
import builtins
import os
import sys

BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__builtins__", "__spec__", "__package__"}


class Scope:
    def __init__(self, parent=None, kind="module"):
        self.parent, self.kind, self.bound = parent, kind, set()

    def has(self, name):
        s = self
        while s:
            if name in s.bound:
                return True
            s = s.parent
        return False


def bind_targets(node, scope):
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            scope.bound.add(n.id)
        elif isinstance(n, ast.arg):
            scope.bound.add(n.arg)


def collect_bindings(body_nodes, scope):
    """Python binds names for the whole scope regardless of order."""
    for node in body_nodes:
        for n in ast.walk(node):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scope.bound.add(n.name)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    scope.bound.add((a.asname or a.name).split(".")[0])
            elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                scope.bound.add(n.id)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                scope.bound.add(n.name)
            elif isinstance(n, (ast.Global, ast.Nonlocal)):
                scope.bound.update(n.names)
            elif isinstance(n, ast.MatchAs) and n.name:
                scope.bound.add(n.name)
            elif isinstance(n, ast.arg):
                scope.bound.add(n.arg)


def check(path):
    src = open(path, encoding="utf-8", errors="replace").read()
    try:
        tree = ast.parse(src, path)
    except SyntaxError as e:
        return [f"{path}:{e.lineno}: SYNTAX {e.msg}"]
    out = []
    module = Scope()
    module.bound |= BUILTINS
    collect_bindings(tree.body, module)
    star = any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names) for n in ast.walk(tree))

    used = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            used.add(n.id)
        elif isinstance(n, ast.Attribute):
            base = n
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                used.add(base.id)
    if "__all__" in src:
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                used.add(n.value)

    # UNDEF: Python name resolution is lexical; collect_bindings over the whole module
    # already covers every scope, so this only finds names bound nowhere at all.
    if not star:
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and not module.has(n.id):
                out.append(f"{path}:{n.lineno}: UNDEF {n.id}")

    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)) and not isinstance(n, ast.ImportFrom) or \
                (isinstance(n, ast.ImportFrom) and n.module != "__future__"):
            for a in n.names:
                nm = (a.asname or a.name).split(".")[0]
                if nm != "*" and nm not in used and not path.endswith("__init__.py"):
                    out.append(f"{path}:{n.lineno}: UNUSED import {nm}")

    for n in ast.walk(tree):
        if isinstance(n, ast.ExceptHandler):
            if n.type is None:
                out.append(f"{path}:{n.lineno}: BARE except:")
            if all(isinstance(b, (ast.Pass, ast.Continue)) for b in n.body):
                out.append(f"{path}:{n.lineno}: SWALLOW except -> pass")
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            seen = {}
            for b in n.body:
                if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if b.name in seen and not b.decorator_list:
                        out.append(f"{path}:{b.lineno}: REDEF {b.name} (first at line {seen[b.name]})")
                    seen[b.name] = b.lineno
    return out


def main():
    roots = sys.argv[1:] or ["backend", "tests", "scripts", "."]
    seen = set()
    for r in roots:
        paths = [r] if r.endswith(".py") else [
            os.path.join(d, f) for d, ds, fs in os.walk(r)
            for f in fs if f.endswith(".py")
            if not any(x in d for x in ("venv", ".venv", "__pycache__", "site-packages", "Datasets"))
        ] if r != "." else [f for f in os.listdir(".") if f.endswith(".py")]
        for p in paths:
            p = os.path.normpath(p)
            if p in seen:
                continue
            seen.add(p)
            for line in check(p):
                print(line)


if __name__ == "__main__":
    main()
