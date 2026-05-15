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
import urllib.request

# ── Allow sibling imports (generate_email_templ lives in the same api/ dir) ──
sys.path.insert(0, os.path.dirname(__file__))
import generate_email_templ  # noqa: E402


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
        try:
            generate_email_templ.CSV_PATH = output_path
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                generate_email_templ.main()
            script_output = buf.getvalue()
        except Exception as exc:
            script_error = str(exc)

        # ── Respond ───────────────────────────────────────────────────────────
        record = params.get("record", [None])[0]
        csv_rows = max(0, csv_content.count("\n") - 1)  # subtract header row
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
        })

    def _respond(self, code: int, body: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())
