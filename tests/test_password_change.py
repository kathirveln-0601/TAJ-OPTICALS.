import http.cookiejar
import json
import os
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
import unittest

TMP = tempfile.TemporaryDirectory(prefix="taj-password-test-")
os.environ["TAJ_DB_PATH"] = str(Path(TMP.name) / "password.sqlite3")
os.environ["TAJ_UPLOAD_DIR"] = str(Path(TMP.name) / "uploads")

import server  # noqa: E402


class PasswordAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["TAJ_DB_PATH"] = str(Path(TMP.name) / "password.sqlite3")
        os.environ["TAJ_UPLOAD_DIR"] = str(Path(TMP.name) / "uploads")
        server.ensure_schema()
        server.create_admin_account("password-test@example.test", "Original-Password-42!")
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.TajHandler)
        cls.httpd.daemon_threads = True
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)
        TMP.cleanup()

    def setUp(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = ""

    def req(self, path, method="GET", body=None):
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if self.csrf and method != "GET":
            headers["X-CSRF-Token"] = self.csrf
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=8) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    def login(self, password):
        status, data = self.req("/api/admin/login", "POST", {"email": "password-test@example.test", "password": password})
        if status == 200:
            self.csrf = data["csrf_token"]
        return status, data

    def test_owner_can_rotate_password_and_old_password_stops_working(self):
        status, _ = self.login("Original-Password-42!")
        self.assertEqual(status, 200)
        new_password = "Rotated-Password-2026!"
        status, data = self.req("/api/admin/password", "POST", {"current_password": "Original-Password-42!", "new_password": new_password, "confirm_password": new_password})
        self.assertEqual(status, 200, data)
        self.assertIn("Password updated", data["message"])
        self.req("/api/admin/logout", "POST", {})
        self.csrf = ""
        self.assertEqual(self.login("Original-Password-42!")[0], 401)
        self.assertEqual(self.login(new_password)[0], 200)
        # Restore the test-only credential before teardown.
        status, data = self.req("/api/admin/password", "POST", {"current_password": new_password, "new_password": "Original-Password-42!", "confirm_password": "Original-Password-42!"})
        self.assertEqual(status, 200, data)


if __name__ == "__main__":
    unittest.main()
