import contextlib
import io
import unittest

import demo


class DemoTests(unittest.TestCase):
    def test_fictional_examples(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            demo.main()
        text = output.getvalue()
        self.assertIn("Evening talk, reported end", text)
        self.assertIn("No review prompted by this report", text)
        unknown = text.split("Evening talk, end unknown", 1)[1]
        self.assertIn("Outage end: not confirmed", unknown)
        self.assertIn("Statement channel: event page", unknown)
        self.assertIn("Statement result: Review needed", unknown)
        self.assertNotIn("Information needed:", text)
        self.assertIn("Page and ticket marked checked.", text)
        self.assertNotIn("checks recorded", text)


if __name__ == "__main__":
    unittest.main()
