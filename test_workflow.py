import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode

import workflow


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), workflow.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=data, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read().decode("utf-8")
        finally:
            connection.close()

    def test_default_page_and_styles(self):
        status, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Afternoon workshop", page)
        self.assertIn("Review needed", page)
        self.assertIn("No review prompted", page)
        self.assertIn("Selections apply to this assessment and are not saved.", page)
        self.assertIn("Ticket marked not checked", page)
        self.assertIn("Page and ticket marked checked", page)
        self.assertNotIn("checks recorded", page)
        self.assertEqual(self.request("GET", "/style.css")[0], 200)
        self.assertEqual(self.request("GET", "/missing")[0], 404)

    def test_unknown_end_and_ticket_statement(self):
        data = urlencode({"token": workflow.TOKEN, "status": "unavailable", "end": "unknown", "workshop": "available", "talk": "none"})
        status, page = self.request("POST", "/", data, {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 200)
        self.assertEqual(page.count("Review needed"), 3)
        self.assertIn("Not confirmed", page)
        self.assertIn("<span class=\"channel\">Ticket</span>", page)
        self.assertIn("Selections apply to this assessment and are not saved.", page)
        self.assertIn('<option value="unknown" selected>Not confirmed</option>', page)
        status, fresh_page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn('<option value="16" selected>16:00 UTC</option>', fresh_page)
        self.assertNotIn('<option value="unknown" selected>Not confirmed</option>', fresh_page)

    def test_form_security_and_validation(self):
        base = {"status": "unavailable", "end": "16", "workshop": "unchecked", "talk": "none"}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        self.assertEqual(self.request("POST", "/", urlencode(base), headers)[0], 403)
        self.assertEqual(self.request("POST", "/", urlencode({**base, "token": "\u00e9"}), headers)[0], 403)
        self.assertEqual(self.request("POST", "/", urlencode({**base, "token": workflow.TOKEN, "status": "invalid"}), headers)[0], 400)
        self.assertEqual(self.request("POST", "/", urlencode({**base, "token": workflow.TOKEN}), {**headers, "Origin": "https://example.com"})[0], 403)
        self.assertEqual(self.request("GET", "/", headers={"Host": "example.com"})[0], 403)


if __name__ == "__main__":
    unittest.main()
