import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import server


class TeeTimeRequestFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        server.DB_PATH = os.path.join(cls.tempdir.name, "test.db")
        server.init_db()
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}/api"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        cls.tempdir.cleanup()

    def request(self, method, path, token=None, body=None, expected=200):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as res:
                status = res.status
                payload = json.load(res)
        except urllib.error.HTTPError as err:
            status = err.code
            payload = json.load(err)
        self.assertEqual(expected, status, payload)
        return payload

    def signup(self, name, email):
        return self.request("POST", "/signup", body={
            "name": name,
            "email": email,
            "password": "testpass123",
        })

    def test_host_can_accept_and_decline_requests(self):
        host = self.signup("Test Host", "host@example.com")
        accepted = self.signup("Accepted Golfer", "accepted@example.com")
        declined = self.signup("Declined Golfer", "declined@example.com")

        self.request("POST", "/teetimes", host["token"], {
            "title": "Pilot test round",
            "course": "Test course",
            "when": "Saturday 10 AM",
            "zipCode": "75218",
            "spots": 1,
        })
        listings = self.request("GET", "/teetimes", host["token"])["teetimes"]
        tee_time = next(t for t in listings if t["title"] == "Pilot test round")
        tee_id = tee_time["id"]

        self.request("POST", f"/teetimes/{tee_id}/join", accepted["token"])
        self.request("POST", f"/teetimes/{tee_id}/join", declined["token"])

        host_listing = next(
            t for t in self.request("GET", "/teetimes", host["token"])["teetimes"]
            if t["id"] == tee_id)
        self.assertEqual(2, len(host_listing["requests"]))
        self.assertEqual({"pending"}, {r["status"] for r in host_listing["requests"]})

        self.request(
            "POST", f"/teetimes/{tee_id}/requests/{accepted['user']['id']}/accept",
            host["token"])
        self.request(
            "POST", f"/teetimes/{tee_id}/requests/{declined['user']['id']}/decline",
            host["token"])

        host_listing = next(
            t for t in self.request("GET", "/teetimes", host["token"])["teetimes"]
            if t["id"] == tee_id)
        self.assertEqual(0, host_listing["spotsLeft"])
        self.assertEqual(
            [{"name": "Accepted Golfer", "status": "accepted"}],
            [{"name": r["name"], "status": r["status"]}
             for r in host_listing["requests"]])

        accepted_listing = next(
            t for t in self.request("GET", "/teetimes", accepted["token"])["teetimes"]
            if t["id"] == tee_id)
        declined_listing = next(
            t for t in self.request("GET", "/teetimes", declined["token"])["teetimes"]
            if t["id"] == tee_id)
        self.assertEqual("accepted", accepted_listing["requestStatus"])
        self.assertEqual("declined", declined_listing["requestStatus"])

        accepted_notifications = self.request(
            "GET", "/notifications", accepted["token"])["notifications"]
        declined_notifications = self.request(
            "GET", "/notifications", declined["token"])["notifications"]
        self.assertTrue(any("confirmed" in n["text"] for n in accepted_notifications))
        self.assertTrue(any("declined" in n["text"] for n in declined_notifications))

        # Hosts get their own listings automatically; accepted golfers choose whether to add it.
        host_calendar = self.request("GET", "/calendar", host["token"])["events"]
        accepted_calendar = self.request("GET", "/calendar", accepted["token"])["events"]
        self.assertTrue(any(e["id"] == tee_id for e in host_calendar))
        self.assertFalse(any(e["id"] == tee_id for e in accepted_calendar))

        self.request("POST", f"/teetimes/{tee_id}/calendar", accepted["token"])
        accepted_calendar = self.request("GET", "/calendar", accepted["token"])["events"]
        self.assertTrue(any(e["id"] == tee_id for e in accepted_calendar))

        self.request("DELETE", f"/teetimes/{tee_id}/calendar", accepted["token"])
        accepted_calendar = self.request("GET", "/calendar", accepted["token"])["events"]
        self.assertFalse(any(e["id"] == tee_id for e in accepted_calendar))

        self.request(
            "POST", f"/teetimes/{tee_id}/calendar", declined["token"], expected=403)

    def test_zip_course_lookup_endpoint(self):
        golfer = self.signup("ZIP Golfer", "zip@example.com")
        original = server.lookup_golf_courses
        server.lookup_golf_courses = lambda postal_code, radius: {
            "zipCode": postal_code,
            "radiusMiles": radius,
            "location": "Dallas, TX",
            "courses": [{"name": "Tenison Park", "distanceMiles": 2.4,
                         "city": "Dallas", "state": "TX"}],
        }
        try:
            result = self.request("GET", "/courses?zip=75218&radius=10", golfer["token"])
        finally:
            server.lookup_golf_courses = original
        self.assertEqual("75218", result["zipCode"])
        self.assertEqual(10, result["radiusMiles"])
        self.assertEqual("Tenison Park", result["courses"][0]["name"])


if __name__ == "__main__":
    unittest.main()
