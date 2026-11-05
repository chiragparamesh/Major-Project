"""
Build docs/MLBFD_Complete_Project_Details.pdf from docs/COMPLETE_PROJECT_DETAILS.template.md.

Steps: generate code-derived fragments -> splice into the template -> Markdown to HTML -> Chrome headless to PDF.
Run with the project venv (needs the `markdown` package) and Chrome or Edge installed.
"""
import glob
import os
import re
import subprocess
import sys
import tempfile

import markdown

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(REPO, "docs", "COMPLETE_PROJECT_DETAILS.template.md")
OUT_PDF = os.path.join(REPO, "docs", "MLBFD_Complete_Project_Details.pdf")
OUT_MD = os.path.join(REPO, "docs", "MLBFD_Complete_Project_Details.md")

work = tempfile.mkdtemp(prefix="mlbfd_doc_")
frag = os.path.join(work, "frag")
subprocess.run([sys.executable, os.path.join(REPO, "scripts", "gen_doc_fragments.py"), frag], check=True)

text = open(TEMPLATE, encoding="utf-8").read()


def include(m):
    return open(os.path.join(frag, m.group(1)), encoding="utf-8").read()


text = re.sub(r"\{\{INCLUDE:([a-z_.]+)\}\}", include, text)
n_tests_files = len(glob.glob(os.path.join(REPO, "tests", "test_*.py")))
text = text.replace("in 30 test files", f"in {n_tests_files} test files")
open(OUT_MD, "w", encoding="utf-8").write(text)

body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists", "toc"])

css = """
@page { size: A4; margin: 16mm 13mm 16mm 13mm; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 9.6pt; line-height: 1.42; color: #1b1f24; }
h1 { font-size: 17pt; color: #12306b; border-bottom: 2px solid #12306b; padding-bottom: 3px; margin-top: 26px; page-break-before: always; }
h1:first-of-type { page-break-before: avoid; font-size: 22pt; border: none; }
h2 { font-size: 13pt; color: #1d4ed8; margin-top: 18px; }
h3 { font-size: 11pt; color: #1e40af; margin-top: 14px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px 0; font-size: 8.3pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th { background: #12306b; color: #fff; text-align: left; padding: 4px 6px; }
td { border: 1px solid #cbd5e1; padding: 3px 6px; vertical-align: top; word-break: break-word; }
tr:nth-child(even) td { background: #f4f7fb; }
code { font-family: Consolas, 'Courier New', monospace; font-size: 8.4pt; background: #eef2f7; padding: 0 2px; border-radius: 2px; }
pre { background: #0f172a; color: #e2e8f0; padding: 8px 10px; font-size: 7.6pt; line-height: 1.25; border-radius: 4px; white-space: pre-wrap; }
pre code { background: none; color: inherit; }
hr { border: none; border-top: 1px solid #cbd5e1; margin: 14px 0; }
ul, ol { margin: 4px 0 8px 0; padding-left: 20px; }
"""
html = f"<!doctype html><html><head><meta charset='utf-8'><title>MLBFD Complete Project Details</title><style>{css}</style></head><body>{body}</body></html>"
html_path = os.path.join(work, "doc.html")
open(html_path, "w", encoding="utf-8").write(html)

browsers = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
exe = next((b for b in browsers if os.path.exists(b)), None)
if not exe:
    sys.exit("Chrome or Edge not found")
subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-sandbox",
                f"--print-to-pdf={OUT_PDF}", "--no-pdf-header-footer",
                "file:///" + html_path.replace("\\", "/")], check=True, timeout=300,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print("PDF:", OUT_PDF, os.path.getsize(OUT_PDF) // 1024, "KB")
