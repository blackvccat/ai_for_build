"""Provider reply parsing: real model replies are not always bare JSON."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from paris_builder.providers import ProviderError, parse_json_object  # noqa: E402


class ParseJsonObjectTests(unittest.TestCase):
    def test_bare_object(self):
        self.assertEqual(parse_json_object('{"a": 1}'), {'a': 1})

    def test_fenced_object(self):
        self.assertEqual(parse_json_object('```json\n{"a": 1}\n```'), {'a': 1})
        self.assertEqual(parse_json_object('```\n{"a": 1}\n```'), {'a': 1})

    def test_prose_around_object(self):
        self.assertEqual(parse_json_object('Here is the review:\n{"a": 1}\nHope this helps.'), {'a': 1})

    def test_nested_braces_and_braces_inside_strings(self):
        text = 'note: {"outer": {"inner": [1, 2]}, "label": "use {braces} here", "n": 3} tail'
        self.assertEqual(parse_json_object(text)['label'], 'use {braces} here')
        self.assertEqual(parse_json_object(text)['outer']['inner'], [1, 2])

    def test_real_review_shape_is_recovered(self):
        reply = ('```json\n{"decision": "reject", "view_observations": {"front": "flat wall"}, '
                 '"failure_modes": ["no storefront"], "rollback_stage": "frameworks", "rationale": "r"}\n```')
        parsed = parse_json_object(reply)
        self.assertEqual(parsed['decision'], 'reject')
        self.assertEqual(parsed['failure_modes'], ['no storefront'])

    def test_unparseable_reply_raises(self):
        for bad in ('', 'no json at all', '[1, 2, 3]', '{"broken": '):
            with self.assertRaises(ProviderError):
                parse_json_object(bad)

    def test_non_string_input_raises(self):
        with self.assertRaises(ProviderError):
            parse_json_object(None)


if __name__ == '__main__':
    unittest.main()
