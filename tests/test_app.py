import http.cookiejar
import json
import os
import socketserver
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

TMP = tempfile.TemporaryDirectory(prefix="taj-tests-")
os.environ["TAJ_DB_PATH"] = str(Path(TMP.name) / "test.sqlite3")
os.environ["TAJ_UPLOAD_DIR"] = str(Path(TMP.name) / "uploads")

import server  # noqa: E402


class APIServer(server.ThreadingHTTPServer):
    daemon_threads = True


class TajAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["TAJ_DB_PATH"] = str(Path(TMP.name) / "test.sqlite3")
        os.environ["TAJ_UPLOAD_DIR"] = str(Path(TMP.name) / "uploads")
        server.ensure_schema()
        server.create_admin_account("owner@example.test", "Test-Only-Password-42!")
        cls.httpd = APIServer(("127.0.0.1", 0), server.TajHandler)
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

    def request(self, path, method="GET", body=None, headers=None, opener=None):
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        h = dict(headers or {})
        if body is not None and not isinstance(body, bytes):
            h.setdefault("Content-Type", "application/json")
        if self.csrf and method not in {"GET", "HEAD"}:
            h.setdefault("X-CSRF-Token", self.csrf)
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        use = opener or self.opener
        try:
            with use.open(req, timeout=8) as response:
                payload = response.read()
                content_type = response.headers.get_content_type()
                if content_type == "application/json":
                    return response.status, json.loads(payload.decode())
                return response.status, payload
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            try:
                data = json.loads(payload.decode())
            except Exception:
                data = payload.decode(errors="replace")
            return exc.code, data

    def admin_login(self):
        status, data = self.request("/api/admin/login", "POST", {"email": "owner@example.test", "password": "Test-Only-Password-42!"})
        self.assertEqual(status, 200, data)
        self.csrf = data["csrf_token"]
        return data

    def create_product(self, sku="TO-TEST-1", price="500"):
        return self.request("/api/admin/products", "POST", {
            "sku": sku,
            "name": "Test frame",
            "category_id": 1,
            "brand": "Test brand",
            "description": "Only a test record",
            "selling_price_inr": price,
            "original_price_inr": "",
            "stock_qty": 7,
            "status": "active",
            "featured": True,
            "specifications": {"frame_size": "medium"},
        })

    def test_public_home_data_and_exact_delivery_boundaries(self):
        status, health = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["ok"])
        status, store = self.request("/api/store")
        self.assertEqual(status, 200)
        self.assertEqual(store["delivery"]["free_delivery_threshold_paise"], 170000)
        self.assertEqual(store["delivery"]["standard_delivery_charge_paise"], 5000)
        self.assertEqual(server.calculate_delivery(50000)["total_paise"], 55000)
        self.assertEqual(server.calculate_delivery(150000)["delivery_charge_paise"], 5000)
        at_1699 = server.calculate_delivery(169900)
        self.assertEqual(at_1699["delivery_charge_paise"], 5000)
        self.assertEqual(at_1699["total_paise"], 174900)
        self.assertEqual(at_1699["remaining_for_free_delivery_paise"], 100)
        at_1700 = server.calculate_delivery(170000)
        self.assertEqual(at_1700["delivery_charge_paise"], 0)
        self.assertTrue(at_1700["free_delivery"])
        self.assertEqual(at_1700["total_paise"], 170000)
        self.assertEqual(server.calculate_delivery(250000)["total_paise"], 250000)

    def test_admin_login_is_required_and_product_persists_with_media(self):
        anonymous = urllib.request.build_opener()
        status, result = self.request("/api/admin/products", opener=anonymous)
        self.assertEqual(status, 401)
        self.admin_login()
        status, missing_csrf = self.request("/api/admin/products", "POST", {"name": "x"}, headers={"X-CSRF-Token": "bad"})
        self.assertEqual(status, 403)
        status, product = self.create_product()
        self.assertEqual(status, 201, product)
        self.assertEqual(product["sku"], "TO-TEST-1")
        status, public = self.request("/api/products/" + product["slug"])
        self.assertEqual(status, 200)
        self.assertEqual(public["selling_price_paise"], 50000)
        status, admin_list = self.request("/api/admin/products")
        self.assertEqual(status, 200)
        self.assertTrue(any(p["sku"] == "TO-TEST-1" for p in admin_list))

        image = (server.STATIC_DIR / "assets" / "category-eyeglasses.jpg").read_bytes()
        boundary = "----TajTestBoundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"kind\"\r\n\r\nimage\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"frame.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n"
        ).encode() + image + f"\r\n--{boundary}--\r\n".encode()
        status, media = self.request(f"/api/admin/products/{product['id']}/media", "POST", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        self.assertEqual(status, 201, media)
        self.assertEqual(media[0]["kind"], "image")
        status, public = self.request("/api/products/" + product["slug"])
        self.assertEqual(status, 200)
        self.assertEqual(len(public["media"]), 1)
        self.assertTrue(public["media"][0]["is_cover"])

        video = bytes.fromhex("000000186674797069736f6d0000020069736f6d69736f32")
        boundary = "----TajVideoBoundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"kind\"\r\n\r\nvideo\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"clip.mp4\"\r\nContent-Type: video/mp4\r\n\r\n"
        ).encode() + video + f"\r\n--{boundary}--\r\n".encode()
        status, video_media = self.request(f"/api/admin/products/{product['id']}/media", "POST", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        self.assertEqual(status, 201, video_media)
        self.assertEqual(video_media[0]["kind"], "video")
        status, served = self.request(video_media[0]["url"])
        self.assertEqual(status, 200)
        self.assertEqual(served[4:8], b"ftyp")

        status, updated = self.request(f"/api/admin/products/{product['id']}", "PUT", {"sku": product["sku"], "name": "Updated test frame", "category_id": 1, "brand": "Test brand", "selling_price_inr": "525.50", "stock_qty": 6, "status": "active", "specifications": {}})
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated["selling_price_paise"], 52550)
        self.request("/api/admin/logout", "POST", {})
        self.csrf = ""
        self.admin_login()
        status, persisted = self.request("/api/products/" + product["slug"])
        self.assertEqual(status, 200)
        self.assertEqual(persisted["name"], "Updated test frame")
        self.assertEqual(persisted["selling_price_paise"], 52550)

    def test_server_reprices_cart_and_admin_delivery_settings_apply(self):
        self.admin_login()
        status, p1 = self.create_product("TO-1699", "1699")
        self.assertEqual(status, 201, p1)
        status, quote = self.request("/api/quote", "POST", {"items": [{"product_id": p1["id"], "quantity": 1}]})
        self.assertEqual(status, 200, quote)
        self.assertEqual(quote["product_subtotal_paise"], 169900)
        self.assertEqual(quote["delivery_charge_paise"], 5000)
        self.assertEqual(quote["total_paise"], 174900)
        status, p2 = self.create_product("TO-1700", "1700")
        self.assertEqual(status, 201, p2)
        status, quote = self.request("/api/quote", "POST", {"items": [{"product_id": p2["id"], "quantity": 1}]})
        self.assertEqual(status, 200, quote)
        self.assertEqual(quote["delivery_charge_paise"], 0)
        self.assertEqual(quote["total_paise"], 170000)
        status, settings = self.request("/api/admin/settings", "PUT", {"free_delivery_threshold_inr": 1800, "standard_delivery_charge_inr": 65})
        self.assertEqual(status, 200, settings)
        status, quote = self.request("/api/quote", "POST", {"items": [{"product_id": p2["id"], "quantity": 1}]})
        self.assertEqual(status, 200)
        self.assertEqual(quote["delivery_charge_paise"], 6500)
        self.assertEqual(quote["remaining_for_free_delivery_paise"], 10000)

    def test_csv_preview_detects_duplicate_skus_and_imports_valid_rows(self):
        self.admin_login()
        status, sample = self.request("/api/admin/products/sample.csv")
        self.assertEqual(status, 200)
        self.assertIn(b"sku,name,category", sample)
        status, _ = self.create_product("TO-DUP", "250")
        self.assertEqual(status, 201)
        text = "sku,name,category,selling_price_inr,stock_qty,status\nTO-DUP,Duplicate,eyeglasses,300,4,active\nTO-CSV-2,Imported frame,eyeglasses,750.50,12,draft\n"
        status, preview = self.request("/api/admin/products/import/preview", "POST", {"csv": text})
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview["valid_count"], 1)
        self.assertEqual(preview["error_count"], 1)
        status, result = self.request("/api/admin/products/import", "POST", {"csv": text})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["failed"], 1)
        status, page = self.request("/api/products?q=Imported")
        self.assertEqual(status, 200)
        self.assertEqual(page["total"], 0, "Draft imports must remain unpublished by default when specified as draft.")
        status, admin = self.request("/api/admin/products?q=TO-CSV-2")
        self.assertEqual(status, 200)
        self.assertEqual(len(admin), 1)

    def test_whatsapp_requires_explicit_verification_and_map_is_confirmed(self):
        status, store = self.request("/api/store")
        self.assertEqual(status, 200)
        self.assertFalse(store["whatsapp_ready"])
        self.assertEqual(store["contact_phone"], "9597378385")
        self.assertEqual(store["maps_url"], "https://maps.google.com/?q=10.993682,76.964188")
        self.admin_login()
        status, settings = self.request("/api/admin/settings", "PUT", {"whatsapp_number": "9597378385", "whatsapp_verified": False})
        self.assertEqual(status, 200)
        status, store = self.request("/api/store")
        self.assertFalse(store["whatsapp_ready"])
        status, settings = self.request("/api/admin/settings", "PUT", {"whatsapp_number": "919597373835", "whatsapp_verified": True})
        self.assertEqual(status, 200)
        status, store = self.request("/api/store")
        self.assertTrue(store["whatsapp_ready"])
        self.assertEqual(store["whatsapp_number"], "919597373835")

    def test_ai_studio_reports_missing_provider_credentials_without_submitting(self):
        old_secret = os.environ.pop("RUNWAYML_API_SECRET", None)
        try:
            self.admin_login()
            status, cap = self.request("/api/admin/video-capabilities")
            self.assertEqual(status, 200)
            self.assertFalse(cap["configured"])
            status, result = self.request("/api/admin/video-jobs", "POST", {"confirm_paid_generation": True})
            self.assertEqual(status, 503)
            self.assertIn("No generation was submitted", result["error"])
        finally:
            if old_secret is not None:
                os.environ["RUNWAYML_API_SECRET"] = old_secret

    def test_product_delete_is_confirmed_by_admin_and_removes_record(self):
        self.admin_login()
        status, product = self.create_product("TO-DELETE", "450")
        self.assertEqual(status, 201)
        status, result = self.request(f"/api/admin/products/{product['id']}", "DELETE")
        self.assertEqual(status, 200, result)
        status, result = self.request("/api/products/" + product["slug"])
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
