"""
Vercel Python serverless function replacing run_get.php.

Handles REDCap Data Entry Trigger (DET) webhooks (POST) and manual GET pings.
- Verifies secret (query param or POST body)
- Fetches the REDCap report as CSV
- Saves it to /tmp/redcap-data.csv  (writable on Vercel)
- Imports and runs generate_email_templ.main() in-process
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
import contextlib
import datetime
import hmac
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

# ── Allow sibling imports (_generate_email_templ lives in the same api/ dir) ──
# Underscore prefix tells Vercel NOT to deploy it as a standalone endpoint.
sys.path.insert(0, os.path.dirname(__file__))
import _generate_email_templ as generate_email_templ  # noqa: E402


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        self._handle(body=b"")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        self._handle(body=body)

    # ── Core logic ────────────────────────────────────────────────────────────

    def _handle(self, body: bytes):
        api_url = os.environ.get("REDCAP_API_URL", "https://redcap.tch.harvard.edu/redcap_edc/api/")
        token   = os.environ.get("REDCAP_TOKEN", "")
        secret  = os.environ.get("REDCAP_SECRET", "")

        if not secret:
            self._respond(500, {"status": "error", "message": "REDCAP_SECRET env var not set"})
            return

        # Merge query-string params and POST body params
        parsed      = urlparse(self.path)
        qs_params   = parse_qs(parsed.query)
        body_params = parse_qs(body.decode("utf-8", errors="replace")) if body else {}
        params      = {**body_params, **qs_params}  # query string wins on conflict

        provided_secret = params.get("secret", [""])[0]

        if not hmac.compare_digest(secret.encode(), provided_secret.encode()):
            self._respond(403, {"status": "error", "message": "Invalid secret"})
            return

        if not api_url or not token:
            self._respond(500, {"status": "error", "message": "Configuration missing"})
            return

        # Wait briefly so REDCap finishes writing auto-fields (e.g. timestamp)
        # before we fetch the report – the DET fires faster than REDCap commits.
        time.sleep(5)

        # ── Fetch REDCap report ───────────────────────────────────────────────
        payload = urlencode({
            "token":              token,
            "content":            "report",
            "format":             "csv",
            "report_id":          "18198",
            "csvDelimiter":       "",
            "rawOrLabel":         "raw",
            "rawOrLabelHeaders":  "raw",
            "exportCheckboxLabel": "false",
            "returnFormat":       "csv",
            "exportSurveyFields":    "true",
        }).encode()

        try:
            req = urllib.request.Request(api_url, data=payload, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status != 200:
                    self._respond(502, {"status": "error", "message": f"REDCap API returned {resp.status}"})
                    return
                csv_content = resp.read().decode("utf-8")
        except Exception as exc:
            self._respond(502, {"status": "error", "message": str(exc)})
            return

        # ── Save CSV to /tmp (the only writable path in Vercel serverless) ───
        output_path = "/tmp/redcap-data.csv"
        try:
            with open(output_path, "w", encoding="utf-8") as fh:
                fh.write(csv_content)
        except Exception as exc:
            self._respond(500, {"status": "error", "message": f"Could not write CSV: {exc}"})
            return

        # ── Run email script in-process ───────────────────────────────────────
        script_output = ""
        script_error  = None
        csv_rows = max(0, csv_content.count("\n") - 1)
        print(f"[run_get] csv_rows={csv_rows}, running generate_email_templ.main()")
        try:
            generate_email_templ.CSV_PATH = output_path
            det_record_id = params.get("record", [None])[0]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                generate_email_templ.main(det_record_id=det_record_id)
            script_output = buf.getvalue()
            print("[run_get] script_output:\n" + script_output)
        except Exception as exc:
            script_error = str(exc)
            print(f"[run_get] script_error: {script_error}")

        # ── Notify WordPress sync endpoint ──────────────────────────────────
        # Use /wp-json/ path (avoids ?rest_route= redirect issues) and set a
        # browser-like User-Agent so WP Engine's WAF doesn't block the request.
        wp_url    = os.environ.get(
            "WP_SYNC_URL",
            "https://dbsmatchmaker.com/wp-json/redcap/v1/update"
            "?secret=ca8318716dbf7cdc4682a6afebc6404c",
        )
        wp_status = None
        wp_error  = None
        record_param = params.get("record", [None])[0]
        try:
            wp_payload = urlencode({
                "record": record_param or "",
            }).encode()
            wp_req = urllib.request.Request(wp_url, data=wp_payload, method="POST")
            wp_req.add_header("Content-Type", "application/x-www-form-urlencoded")
            wp_req.add_header("User-Agent", "Mozilla/5.0 (compatible; REDCap-Sync/1.0)")
            with urllib.request.urlopen(wp_req, timeout=30) as wp_resp:
                wp_status = wp_resp.status
                wp_body   = wp_resp.read().decode("utf-8", errors="replace")[:800]
                print(f"[run_get] WP sync response: {wp_status} {wp_body}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1000]
            wp_error = f"HTTP {exc.code} {exc.reason}: {body}"
            print(f"[run_get] WP sync error: {wp_error}")
        except Exception as exc:
            wp_error = str(exc)
            print(f"[run_get] WP sync error: {wp_error}")

        # ── Respond ───────────────────────────────────────────────────────────
        record = params.get("record", [None])[0]
        self._respond(200, {
            "status":        "ok",
            "updated":       datetime.datetime.utcnow().isoformat() + "Z",
            "file":          output_path,
            "csv_rows":      csv_rows,
            "triggered_by":  record or "manual",
            "preview":       csv_content[:500],
            "email_script":  "generate_email_templ.py",
            "script_output": script_output,
            "script_error":  script_error,
            "wp_sync_status": wp_status,
            "wp_sync_error":  wp_error,
        })

    def _respond(self, code: int, body: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())
