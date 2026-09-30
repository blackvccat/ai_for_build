"""Second pass: update test_workflow fixtures for the single-framework contract."""
import io

path = 'tests/test_workflow.py'
text = io.open(path, encoding='utf-8').read()
pairs = [
    ("        for i in range(5):\n            cid = 'c' + str(i)",
     "        for i in range(1):\n            cid = 'c' + str(i)"),
    ("        self.t['stage'] = 'frameworks'\n"
     "        with self.assertRaisesRegex(ValueError, '1 candidates'): w.submit_review(self.t, self.review())",
     "        self.t['stage'] = 'frameworks'\n"
     "        review = self.review(); review['candidates'] = []\n"
     "        with self.assertRaisesRegex(ValueError, '1 candidates'): w.submit_review(self.t, review)"),
]
for old, new in pairs:
    if old not in text:
        print('WARN not found:', old[:56].replace('\n', '|'))
    text = text.replace(old, new)
io.open(path, 'w', encoding='utf-8', newline='\n').write(text)
print('fixtures updated')
