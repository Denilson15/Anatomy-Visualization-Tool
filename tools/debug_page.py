"""
Open the app headlessly and run JavaScript snippets passed on the command line.

Usage:
    python debug_page.py <app_dir> <three_package_dir> "<js expression>" ...
"""

import functools
import http.server
import json
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright


APP_DIR = Path(sys.argv[1]).resolve()
THREE_DIR = Path(sys.argv[2]).resolve()
SNIPPETS = sys.argv[3:]
CDN_PREFIX = "https://cdn.jsdelivr.net/npm/three@0.169.0/"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


handler = functools.partial(QuietHandler, directory=str(APP_DIR))
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=server.serve_forever, daemon=True).start()


def route_cdn(route):
    url = route.request.url
    if url.startswith(CDN_PREFIX):
        route.fulfill(path=str(THREE_DIR / url[len(CDN_PREFIX):]), content_type="text/javascript")
    else:
        route.abort()


with sync_playwright() as p:
    browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
    page = browser.new_page(viewport={"width": 1200, "height": 800})
    page.on("pageerror", lambda exc: print("pageerror:", exc))
    page.route("https://cdn.jsdelivr.net/**", route_cdn)
    page.route("https://fonts.*/**", lambda route: route.abort())
    page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
    page.wait_for_function("window.__atlas !== undefined", timeout=120000)
    for snippet in SNIPPETS:
        if snippet.startswith("wait:"):
            page.wait_for_timeout(int(snippet[5:]))
            continue
        result = page.evaluate(snippet)
        print(json.dumps(result, indent=4)[:3000])
    browser.close()

server.shutdown()
