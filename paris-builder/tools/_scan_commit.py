# -*- coding: utf-8 -*-
"""Scan exactly the files staged for commit for secrets and oversized blobs.

Run from the repository root. Reads `git diff --cached --name-only` so it covers
precisely what a push would publish — not the whole working tree.
"""
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [
    ('openai/deepseek style key', re.compile(r'sk-[A-Za-z0-9_\-]{16,}')),
    ('aws access key', re.compile(r'AKIA[0-9A-Z]{16}')),
    ('github token', re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}')),
    ('github fine-grained pat', re.compile(r'github_pat_[A-Za-z0-9_]{30,}')),
    ('slack token', re.compile(r'xox[baprs]-[A-Za-z0-9\-]{10,}')),
    ('private key block', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    ('bearer literal', re.compile(r'[Bb]earer\s+[A-Za-z0-9_\-\.]{24,}')),
    ('assigned secret', re.compile(
        r'(?i)\b(api[_-]?key|secret|passwd|password|token)\b\s*[:=]\s*["\']([^"\'\s]{20,})["\']')),
]

# Values that look like secrets but are documented placeholders / env indirection.
ALLOW = re.compile(r'(?i)(\$\{|\$\w|os\.environ|getenv|api_key_env|YOUR_|EXAMPLE|PLACEHOLDER|'
                   r'CHANGE_?ME|<[^>]+>|\.\.\.|redacted|xxx+)')

SIZE_LIMIT_MB = 50


def staged():
    out = subprocess.run(['git', 'diff', '--cached', '--name-only', '-z'],
                         capture_output=True, check=True).stdout
    return [name for name in out.decode('utf-8').split('\0') if name]


def main():
    names = staged()
    print('staged files: %d' % len(names))
    findings = 0
    biggest = []
    for name in names:
        path = Path(name)
        if not path.is_file():
            continue
        size = path.stat().st_size
        biggest.append((size, name))
        if size > SIZE_LIMIT_MB * 1024 * 1024:
            print('  OVERSIZE  %6.1f MB  %s' % (size / 1048576, name))
            findings += 1
        if size > 5 * 1024 * 1024 or path.suffix.lower() in (
                '.png', '.jpg', '.jpeg', '.zip', '.jar', '.onnx', '.schem', '.gz'):
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        for label, pattern in PATTERNS:
            for match in pattern.finditer(text):
                line = text.count('\n', 0, match.start()) + 1
                snippet = match.group(0)
                if ALLOW.search(snippet):
                    continue
                print('  %-26s %s:%d  %s' % (label, name, line, snippet[:48]))
                findings += 1

    total = sum(size for size, _ in biggest)
    print('total size: %.2f MB' % (total / 1048576))
    print('largest 5:')
    for size, name in sorted(biggest, reverse=True)[:5]:
        print('  %8.2f KB  %s' % (size / 1024, name))
    print()
    print('RESULT:', 'CLEAN' if findings == 0 else '%d FINDING(S)' % findings)
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
