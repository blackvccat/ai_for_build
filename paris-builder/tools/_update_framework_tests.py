"""Update framework-stage tests from five-candidate to single-design contract."""
import io

# --- tests/test_workflow.py -------------------------------------------------
p = 'tests/test_workflow.py'
s = io.open(p, encoding='utf-8').read()
pairs = [
    # 评审夹具：五候选 → 单候选
    ("        for i in range(5):\n            cid = 'c%d' % i", "        for i in range(1):\n            cid = 'c%d' % i"),
    ("    def test_framework_requires_five(self):", "    def test_framework_requires_one(self):"),
    ("assertRaisesRegex(ValueError, '5 candidates')", "assertRaisesRegex(ValueError, '1 candidates')"),
]
for old, new in pairs:
    if old not in s:
        print('WARN test_workflow: not found ->', old[:60].replace('\n', '\\n'))
    s = s.replace(old, new)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)

# --- tests/test_atelier_workflow.py ----------------------------------------
p = 'tests/test_atelier_workflow.py'
s = io.open(p, encoding='utf-8').read()
pairs = [
    ("    def test_frameworks_have_five_distinct_three_axis_options(self):",
     "    def test_framework_stage_yields_one_design(self):"),
    ("self.assertEqual(len(rows), 5)", "self.assertEqual(len(rows), 1)"),
    ("'framework_candidates': [{'parameters': {'bay_pitch': 4 + i, 'roof_height': 5 + i},",
     "'framework_candidates': [{'parameters': {'bay_pitch': 5, 'roof_height': 7},"),
    ("'rationale': 'Compliant massing variant'} for i in range(5)]}",
     "'rationale': 'Compliant single design'}]}"),
]
for old, new in pairs:
    if old not in s:
        print('WARN test_atelier: not found ->', old[:60])
    s = s.replace(old, new)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('test fixtures updated for the single-design framework contract')
