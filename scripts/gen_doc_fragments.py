"""
Generate the code-derived tables for the complete project PDF (routes, DB schema, tests, config, files).
Reads source with `ast`; never reads .env, so no secret value can end up in the output.
Usage: python scripts/gen_doc_fragments.py <output_dir>
"""
import ast
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)


def md_escape(t):
    return str(t).replace("|", "\\|").replace("\n", " ")


def write(name, text):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
        fh.write(text)


# ------------------------------------------------------------------ routes
def parse_routes(path, prefix):
    tree = ast.parse(open(path, encoding="utf-8").read())
    rows = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        routes, jwt, limits = [], "-", []
        for d in node.decorator_list:
            if isinstance(d, ast.Call):
                fn = ast.unparse(d.func)
                if fn.endswith(".route"):
                    path_ = ast.literal_eval(d.args[0]) if d.args else "?"
                    methods = ["GET"]
                    for kw in d.keywords:
                        if kw.arg == "methods":
                            methods = ast.literal_eval(kw.value)
                    routes.append((path_, methods))
                elif fn.endswith("jwt_required"):
                    jwt = "JWT optional" if any(k.arg == "optional" for k in d.keywords) else "JWT required"
                elif fn.endswith("limiter.limit"):
                    limits.append(ast.literal_eval(d.args[0]))
            elif isinstance(d, ast.Attribute) and d.attr == "jwt_required":
                jwt = "JWT required"
        for r, methods in routes:
            doc = (ast.get_docstring(node) or "").strip().split("\n")[0]
            rows.append((prefix + r, ",".join(methods), jwt, "; ".join(limits) or "default", node.name, doc))
    return rows


rows = parse_routes(os.path.join(REPO, "backend", "api.py"), "/api")
rows += parse_routes(os.path.join(REPO, "backend", "app.py"), "")
rows.sort(key=lambda r: (not r[0].startswith("/api"), r[0]))
txt = "| Route | Methods | Auth | Rate limit | Handler | Purpose (docstring) |\n|---|---|---|---|---|---|\n"
for r in rows:
    txt += "| `%s` | %s | %s | %s | `%s` | %s |\n" % tuple(md_escape(x) for x in r)
write("routes.md", txt)
write("route_count.txt", str(len(rows)))

# ------------------------------------------------------------------ DB schema
tree = ast.parse(open(os.path.join(REPO, "backend", "database.py"), encoding="utf-8").read())
schema = ""
ntables = 0
for node in tree.body:
    if not isinstance(node, ast.ClassDef):
        continue
    tname = None
    cols = []
    for item in node.body:
        if isinstance(item, ast.Assign) and isinstance(item.targets[0], ast.Name):
            name = item.targets[0].id
            v = item.value
            if name == "__tablename__":
                tname = ast.literal_eval(v)
            elif isinstance(v, ast.Call) and ast.unparse(v.func).endswith("Column"):
                typ = ast.unparse(v.args[0]) if v.args else "?"
                typ = typ.replace("db.", "")
                flags = []
                for a in v.args[1:]:
                    if "ForeignKey" in ast.unparse(a):
                        flags.append("FK " + ast.unparse(a).split("(")[1].strip("')\""))
                for kw in v.keywords:
                    if kw.arg in ("primary_key", "unique", "index") and ast.unparse(kw.value) == "True":
                        flags.append(kw.arg)
                    elif kw.arg == "nullable" and ast.unparse(kw.value) == "False":
                        flags.append("NOT NULL")
                    elif kw.arg == "default":
                        flags.append("default " + ast.unparse(kw.value))
                cols.append((name, typ, ", ".join(flags)))
    if tname:
        ntables += 1
        schema += f"\n### Table `{tname}` (model `{node.name}`)\n\n| Column | Type | Constraints / default |\n|---|---|---|\n"
        for c in cols:
            schema += "| `%s` | %s | %s |\n" % tuple(md_escape(x) for x in c)
write("schema.md", schema)
write("table_count.txt", str(ntables))

# ------------------------------------------------------------------ tests
tests = ""
total = 0
tdir = os.path.join(REPO, "tests")
for fn in sorted(os.listdir(tdir)):
    if not (fn.startswith("test_") and fn.endswith(".py")):
        continue
    t = ast.parse(open(os.path.join(tdir, fn), encoding="utf-8").read())
    names = [n.name for n in ast.walk(t) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    total += len(names)
    tests += f"\n**{fn}** ({len(names)} test functions)\n\n" + "".join(f"- `{n}`\n" for n in names)
write("tests.md", tests)
write("test_count.txt", str(total))

# ------------------------------------------------------------------ config constants
tree = ast.parse(open(os.path.join(REPO, "backend", "config.py"), encoding="utf-8").read())
cfg = "| Setting | How it is read / default |\n|---|---|\n"
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "Config":
        for item in node.body:
            if isinstance(item, ast.Assign) and isinstance(item.targets[0], ast.Name):
                name = item.targets[0].id
                if name.isupper():
                    cfg += "| `%s` | `%s` |\n" % (name, md_escape(ast.unparse(item.value))[:140])
write("config.md", cfg)

# ------------------------------------------------------------------ env variable NAMES only
names = []
for line in open(os.path.join(REPO, ".env.example"), encoding="utf-8"):
    m = re.match(r"^([A-Z][A-Z0-9_]*)=", line.strip())
    if m:
        names.append(m.group(1))
write("env_names.md", "".join(f"- `{n}`\n" for n in names))

# ------------------------------------------------------------------ file inventory
inv = open(os.path.join(REPO, "FILE_REVIEW.md"), encoding="utf-8").read()
inv = inv[inv.index("| path |"):]
write("files.md", inv)
write("file_count.txt", str(len([l for l in inv.splitlines() if l.startswith("| ") and not l.startswith("| path") and not l.startswith("| ---")])))

# ------------------------------------------------------------------ requirements
write("requirements.md", "```\n" + open(os.path.join(REPO, "backend", "requirements.txt"), encoding="utf-8").read() + "```\n")
print("routes", len(rows), "tables", ntables, "tests", total)
