import json
import os
from http.server import BaseHTTPRequestHandler

from src.college_lead_scraper import CollegeLeadScraper, ScrapeConfig


def _cors(handler: BaseHTTPRequestHandler):
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        _cors(self)
        self.end_headers()

    def do_GET(self):
        # Health + docs
        self.send_response(200)
        _cors(self)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        payload = {
            "ok": True,
            "endpoint": "/api/scrape",
            "usage": {
                "method": "POST",
                "body": {
                    "college_name": "AIIMS Delhi",
                    "max_faculty_pages": 2,
                    "max_faculty_per_page": 8,
                    "include_linkedin": False,
                    "polite_delay_s": 0.0,
                    "request_timeout_s": 10,
                },
            },
        }
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self.send_response(400)
            _cors(self)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": "invalid_json"}).encode("utf-8"))
            return

        college_name = (data.get("college_name") or "").strip()
        if not college_name:
            self.send_response(400)
            _cors(self)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": "college_name_required"}).encode("utf-8"))
            return

        # Hard limits to keep serverless predictable
        max_faculty_pages = min(int(data.get("max_faculty_pages", 2)), 5)
        max_faculty_per_page = min(int(data.get("max_faculty_per_page", 8)), 25)
        include_linkedin = bool(data.get("include_linkedin", False))

        # If you enable LinkedIn search, force stricter limits (DDG can be flaky)
        if include_linkedin:
            max_faculty_pages = min(max_faculty_pages, 2)
            max_faculty_per_page = min(max_faculty_per_page, 5)

        request_timeout_s = min(int(data.get("request_timeout_s", 10)), 15)
        polite_delay_s = float(data.get("polite_delay_s", 0.0))

        config = ScrapeConfig(
            request_timeout_s=request_timeout_s,
            max_faculty_pages=max_faculty_pages,
            max_faculty_per_page=max_faculty_per_page,
            include_linkedin=include_linkedin,
            polite_delay_s=polite_delay_s,
        )

        scraper = CollegeLeadScraper(config=config)
        results = scraper.run_workflow(college_name)

        self.send_response(200)
        _cors(self)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "data": results}).encode("utf-8"))
