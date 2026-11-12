"""REST API and WebSocket tests."""

from __future__ import annotations

import json

from tornado.httpclient import HTTPRequest
from tornado.testing import gen_test
from tornado.websocket import websocket_connect

from .helpers import PNG, WebTestCase


class ApiTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.install()
        self.login()
        self.create_entity("temps", "Temperatures", is_sensor="1", read_interval_ms="1500")
        self.add_field("temps", "sensor", "text", required="1")
        self.add_field("temps", "celsius", "float")
        self.add_field("temps", "note", "longtext")
        self.add_field("temps", "photo", "image")
        self.create_entity("hidden", "Hidden")
        self.token = self.create_api_key("sensor-1")

    def api(self, method, path, body=None, token=None, ctype="application/json", raw: bytes | None = None):
        headers = {"Authorization": f"Bearer {token or self.token}"}
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if data is not None:
            headers["Content-Type"] = ctype
        r = self.fetch(path, method=method, body=data, headers=headers, allow_nonstandard_methods=True)
        try:
            payload = json.loads(r.body) if r.body else None
        except ValueError:
            payload = r.body
        return r.code, payload

    def test_authentication(self):
        code, body = self.api("GET", "/api/v1/ping", token="erp_bad_token")
        self.assertEqual(code, 401)
        self.assertEqual(body["error"], "unauthorized")
        r = self.fetch("/api/v1/ping")
        self.assertEqual(r.code, 401)
        code, body = self.api("GET", "/api/v1/ping")
        self.assertEqual(code, 200)
        self.assertEqual(body["key"], "sensor-1")
        r = self.fetch("/api/v1/ping", headers={"X-API-Key": self.token})
        self.assertEqual(r.code, 200)

    def test_schema_and_config(self):
        code, body = self.api("GET", "/api/v1/entities")
        self.assertEqual(code, 200)
        names = [e["name"] for e in body["entities"]]
        self.assertEqual(names, ["hidden", "temps"] if names[0] == "hidden" else ["temps", "hidden"])
        code, body = self.api("GET", "/api/v1/entities/temps/config")
        self.assertEqual(body["read_interval_ms"], 1500)
        # changing the reading interval centrally is visible to sensors
        r = self.post("/admin/entities/temps/edit", {"label": "Temperatures", "perm_user": "write", "perm_dealer": "none",
                                                     "is_sensor": "1", "read_interval_ms": "250", "sort_order": "0"})
        self.assertEqual(r.code, 302, self.text(r))
        code, body = self.api("GET", "/api/v1/entities/temps/config")
        self.assertEqual(body["read_interval_ms"], 250)

    def test_create_read_update_delete(self):
        code, body = self.api("POST", "/api/v1/entities/temps/records", {"sensor": "hall", "celsius": 21.5})
        self.assertEqual(code, 201, body)
        rid = body["id"]
        code, body = self.api("GET", f"/api/v1/entities/temps/records/{rid}")
        self.assertEqual(body["celsius"], 21.5)
        self.assertEqual(body["sensor"], "hall")
        self.assertTrue(body["created_at"].endswith("Z"))
        code, body = self.api("PATCH", f"/api/v1/entities/temps/records/{rid}", {"celsius": 22})
        self.assertEqual(code, 200, body)
        self.assertEqual(body["celsius"], 22.0)
        self.assertEqual(body["sensor"], "hall")
        code, body = self.api("PUT", f"/api/v1/entities/temps/records/{rid}", {"celsius": 1})
        self.assertEqual(code, 422)
        self.assertEqual(body["details"]["sensor"], "required")
        code, body = self.api("DELETE", f"/api/v1/entities/temps/records/{rid}")
        self.assertEqual(code, 204)
        code, body = self.api("DELETE", f"/api/v1/entities/temps/records/{rid}")
        self.assertEqual(code, 404)

    def test_batch_list_filters_and_latest(self):
        items = [{"sensor": "a" if i % 2 else "b", "celsius": i} for i in range(10)]
        code, body = self.api("POST", "/api/v1/entities/temps/records", items)
        self.assertEqual(code, 201, body)
        self.assertEqual(body["count"], 10)
        ids = body["ids"]
        code, body = self.api("GET", f"/api/v1/entities/temps/records?since_id={ids[4]}")
        self.assertEqual([r["id"] for r in body["records"]], ids[5:])
        code, body = self.api("GET", "/api/v1/entities/temps/records?sensor=a&limit=2")
        self.assertEqual(len(body["records"]), 2)
        self.assertTrue(all(r["sensor"] == "a" for r in body["records"]))
        code, body = self.api("GET", "/api/v1/entities/temps/latest?n=3")
        self.assertEqual([r["id"] for r in body["records"]], list(reversed(ids[-3:])))
        self.assertEqual(body["read_interval_ms"], 1500)

    def test_validation_and_unknown(self):
        code, body = self.api("POST", "/api/v1/entities/temps/records", {"sensor": "x", "celsius": "warm"})
        self.assertEqual(code, 422)
        self.assertEqual(body["details"]["celsius"], "invalid_number")
        code, body = self.api("POST", "/api/v1/entities/temps/records", {"sensor": "x", "bogus": 1})
        self.assertEqual(body["details"]["bogus"], "unknown_field")
        code, body = self.api("POST", "/api/v1/entities/temps/records", raw=b"{not json")
        self.assertEqual(code, 400)
        code, body = self.api("GET", "/api/v1/entities/nothing/records")
        self.assertEqual(code, 404)
        code, body = self.api("GET", "/api/v1/nothing")
        self.assertEqual(code, 404)

    def test_charset_of_request(self):
        raw = json.dumps({"sensor": "Şube-İç", "note": "ğüşıöç"}, ensure_ascii=False).encode("cp857")
        code, body = self.api("POST", "/api/v1/entities/temps/records", raw=raw,
                              ctype="application/json; charset=cp857")
        self.assertEqual(code, 201, body)
        code, body = self.api("GET", f"/api/v1/entities/temps/records/{body['id']}")
        self.assertEqual(body["sensor"], "Şube-İç")
        self.assertEqual(body["note"], "ğüşıöç")

    def test_restricted_key(self):
        token = self.create_api_key("reader", entities="temps", can_write="", allowed_ips="")
        code, body = self.api("POST", "/api/v1/entities/temps/records", {"sensor": "x"}, token=token)
        self.assertEqual(code, 403)
        code, body = self.api("GET", "/api/v1/entities/hidden/records", token=token)
        self.assertEqual(code, 404)
        code, body = self.api("GET", "/api/v1/entities/temps/records", token=token)
        self.assertEqual(code, 200)
        token = self.create_api_key("remote", allowed_ips="10.0.0.0/8")
        code, body = self.api("GET", "/api/v1/ping", token=token)
        self.assertEqual(code, 401)

    def test_rate_limit(self):
        token = self.create_api_key("slow", min_interval_ms="60000")
        code, _ = self.api("POST", "/api/v1/entities/temps/records", {"sensor": "x"}, token=token)
        self.assertEqual(code, 201)
        r = self.fetch("/api/v1/entities/temps/records", method="POST", body=b'{"sensor": "y"}',
                       headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        self.assertEqual(r.code, 429)
        self.assertIn("Retry-After", r.headers)

    def test_api_disabled(self):
        self.post("/admin/settings", {"company_name": "T", "default_language": "en-US", "default_charset": "utf-8",
                                      "timezone": "UTC", "default_currency": "TRY", "page_size": "25",
                                      "session_hours": "12"})
        code, body = self.api("GET", "/api/v1/ping")
        self.assertEqual(code, 503)

    def test_file_upload(self):
        from .helpers import multipart

        body, ctype = multipart({}, {"file": ("t.png", PNG, "image/png")})
        r = self.fetch("/api/v1/files?kind=image&entity=temps", method="POST", body=body,
                       headers={"Authorization": f"Bearer {self.token}", "Content-Type": ctype})
        self.assertEqual(r.code, 201, r.body)
        file_id = json.loads(r.body)["id"]
        code, body = self.api("POST", "/api/v1/entities/temps/records", {"sensor": "cam", "photo": file_id})
        self.assertEqual(code, 201, body)
        r = self.fetch(f"/api/v1/files/{file_id}", headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(r.body, PNG)
        code, body = self.api("POST", "/api/v1/entities/temps/records", {"sensor": "cam", "photo": 9999})
        self.assertEqual(body["details"]["photo"], "file_missing")

    def test_xsrf_not_required_for_api(self):
        code, _ = self.api("POST", "/api/v1/entities/temps/records", {"sensor": "x"})
        self.assertEqual(code, 201)

    @gen_test
    async def test_websocket_stream(self):
        url = f"ws://127.0.0.1:{self.get_http_port()}/api/v1/stream/temps"
        bad = HTTPRequest(url, headers={"Authorization": "Bearer nope"})
        with self.assertRaises(Exception):
            await websocket_connect(bad)
        sensor = await websocket_connect(HTTPRequest(url, headers={"Authorization": f"Bearer {self.token}"}))
        watcher = await websocket_connect(url + f"?token={self.token}")
        hello = json.loads(await sensor.read_message())
        self.assertEqual(hello["event"], "hello")
        self.assertEqual(hello["read_interval_ms"], 1500)
        json.loads(await watcher.read_message())
        await sensor.write_message(json.dumps({"sensor": "ws", "celsius": 3.25}))
        messages = [json.loads(await sensor.read_message()) for _ in range(2)]
        events = {m["event"] for m in messages}
        self.assertEqual(events, {"stored", "created"})
        pushed = json.loads(await watcher.read_message())
        self.assertEqual(pushed["event"], "created")
        self.assertEqual(pushed["records"][0]["celsius"], 3.25)
        await sensor.write_message(json.dumps({"celsius": 1}))
        error = json.loads(await sensor.read_message())
        self.assertEqual(error["event"], "error")
        await sensor.write_message(json.dumps({"event": "config"}))
        self.assertEqual(json.loads(await sensor.read_message())["read_interval_ms"], 1500)
        sensor.close()
        watcher.close()
