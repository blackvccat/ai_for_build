#!/usr/bin/env python3
"""Report every .read_text( encoding="utf-8")/.write_text( encoding="utf-8") call site still missing an encoding.

Static report only; it never rewrites files. Used to prove the cross-platform
handoff is clean across src/, tools/ and tests/ (runs/ evidence is out of scope
because it is a recorded snapshot, not executable source).
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / 'src' / 'paris_builder', ROOT / 'tools', ROOT / 'tests']
CALL = re.compile(r'\.(read_text|write_text)\(')


def find_close(text, open_index):
    depth = 0
    quote = None
    escape = False
    for i in range(open_index, len(text)):
        ch = text[i]
        if quote:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in '"\'':  # string literal: brackets inside are not code
            quote = ch
        elif ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
            if depth == 0:
                return i
    return -1


def main():
    missing = 0
    checked = 0
    for target in TARGETS:
        for path in sorted(target.rglob('*.py')):
            if '__pycache__' in path.parts or path.name in ('check_utf8_encoding.py', 'apply_utf8_encoding.py'):
                continue
            text = path.read_text(encoding='utf-8')
            for m in CALL.finditer(text):
                close = find_close(text, m.end() - 1)
                if close < 0:
                    continue
                checked += 1
                if 'encoding' not in text[m.end():close]:
                    line = text[:m.start()].count('\n') + 1
                    print('%s:%d %s without encoding' % (path.relative_to(ROOT), line, m.group(1)))
                    missing += 1
    print('checked %d call sites, %d missing encoding' % (checked, missing))
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main())
