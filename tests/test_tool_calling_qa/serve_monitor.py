"""Standalone monitor server — keeps running after tests finish.

Usage:
    cd insight-ai-agent
    python tests/test_tool_calling_qa/serve_monitor.py

Then open http://localhost:8888 in your browser.
The page auto-refreshes every 1.5s, so you can start/restart tests in another terminal.
"""

import shutil
import sys
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

DIR = Path(__file__).parent / "_live_output"
HTML_SRC = Path(__file__).parent / "monitor_dashboard.html"
PORT = 8888


class _Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def guess_type(self, path):
        t = super().guess_type(path)
        if isinstance(t, str) and t in ("text/html", "application/json"):
            return t + "; charset=utf-8"
        return t

    def log_message(self, fmt, *args):
        # One-line compact log
        sys.stderr.write(f"  {args[0]}\n")


def main():
    DIR.mkdir(exist_ok=True)

    # Always copy latest HTML
    if HTML_SRC.exists():
        shutil.copy2(HTML_SRC, DIR / "index.html")

    handler = partial(_Handler, directory=str(DIR))
    server = HTTPServer(("0.0.0.0", PORT), handler)

    print(f"  Monitor server running at http://localhost:{PORT}")
    print(f"  Serving from: {DIR}")
    print(f"  Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
