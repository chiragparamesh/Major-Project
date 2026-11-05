"""Update one FILE_REVIEW.md row: python scripts/ledger.py <path> <STATUS> <bugs> "<notes>" """
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(REPO, "FILE_REVIEW.md")


def update(path, status, bugs, notes):
    lines = open(LEDGER, encoding="utf-8").read().splitlines()
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0] == path:
            lines[i] = f"| {path} | {cells[1]} | {status} | {bugs} | {notes.replace('|', '/')} |"
            break
    else:
        raise SystemExit(f"not in ledger: {path}")
    open(LEDGER, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    args = sys.argv[1:]
    for j in range(0, len(args), 4):
        update(*args[j:j + 4])
