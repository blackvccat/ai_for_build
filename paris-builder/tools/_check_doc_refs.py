# -*- coding: utf-8 -*-
"""Verify every line reference in the handover/logic docs against the real source.

Docs that cite line numbers rot silently; this checks them so a reader who jumps to
"line 343" actually lands on `def build_stage(`.
"""
import io
import os
import re
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src', 'paris_builder')
FILES = {
    'A': 'atelier_workflow.py',
    'W': 'workflow.py',
    'G': 'generator_repair.py',
    'T': 'technique_library.py',
}
SRC = {key: io.open(os.path.join(BASE, name), encoding='utf-8').read().splitlines()
       for key, name in FILES.items()}

CHECKS = [
    ('A', 22, 'STAGES ='),
    ('A', 104, 'def plans('),
    ('A', 242, 'def candidate('),
    ('A', 343, 'def build_stage('),
    ('A', 377, 'def deliver('),
    ('A', 494, 'def agent_review('),
    ('A', 664, 'def collect_architectural_verdict('),
    ('A', 779, 'def run_autonomous('),
    ('A', 811, 'def reviewed('),
    ('A', 839, 'def budget_check('),
    ('A', 915, 'def apply_generator_repair('),
    ('A', 807, 'hard_limit = 8'),
    ('A', 625, "row['decision'] = 'reject'"),
    ('A', 626, "row['decision'] = 'reject'"),
    ('G', 19, 'MODULES ='),
    ('W', 60, 'def score_profile('),
    ('W', 64, 'def score_gate_failure('),
    ('W', 144, 'def validate_review('),
    ('W', 293, 'def rollback('),
]

print('=== line references ===')
bad = 0
for key, line, needle in CHECKS:
    rows = SRC[key]
    actual = rows[line - 1] if 0 < line <= len(rows) else '<EOF>'
    ok = needle in actual
    bad += 0 if ok else 1
    print('  %-3s L%-4d %s  %s' % (FILES[key][:12], line, 'OK      ' if ok else 'MISMATCH',
                                   actual.strip()[:72]))
print('mismatches:', bad)

print()
print('=== SCORE_PROFILES literal ===')
for i, row in enumerate(SRC['W'], 1):
    if 'SCORE_PROFILES' in row and '=' in row:
        print('  L%d: %s' % (i, row.strip()))
        for j in range(i, min(i + 4, len(SRC['W']))):
            print('        %s' % SRC['W'][j].strip())
        break

print()
print('=== scope text anchors actually present ===')
A = '\n'.join(SRC['A'])
for phrase in ('ELEVATION COMPOSITION only', 'TWO DIFFERENT LISTS, DO NOT MERGE THEM',
               'record uncertainty as fail rather than guessing pass',
               'NOT a defect, NOT a failure mode, and must not lower any score',
               'verify_stamp_audit'):
    print('  %-58s %s' % (phrase[:58], 'FOUND' if phrase in A else 'MISSING'))

print()
print('=== technique_library public API ===')
T = '\n'.join(SRC['T'])
for name in ('def catalogue(', 'def cards(', 'def brief(', 'def load_detail(', 'def size_of(',
             'def stamp(', 'def registry(', 'def verify_stamp_audit(', 'def _state_at('):
    print('  %-26s %s' % (name, 'FOUND' if name in T else 'MISSING'))
