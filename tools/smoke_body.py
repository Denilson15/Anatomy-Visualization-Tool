"""
Headless smoke test for the full-body app: exercise region scoping and
each tab, save screenshots, report console errors and timings.

Usage:
    python smoke_body.py <app_dir> <three_package_dir> <out_dir>
"""

import functools
import http.server
import sys
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


APP_DIR = Path(sys.argv[1]).resolve()
THREE_DIR = Path(sys.argv[2]).resolve()
OUT_DIR = Path(sys.argv[3]).resolve()
OUT_DIR.mkdir(parents=True, exist_ok=True)

CDN_PREFIX = "https://cdn.jsdelivr.net/npm/three@0.169.0/"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve():
    handler = functools.partial(QuietHandler, directory=str(APP_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def route_cdn(route):
    url = route.request.url
    if url.startswith(CDN_PREFIX):
        route.fulfill(path=str(THREE_DIR / url[len(CDN_PREFIX):]), content_type="text/javascript")
    else:
        route.abort()


def open_page(browser, base, viewport, errors, label):
    page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
    page.on("console", lambda msg: msg.type == "error" and "ERR_FAILED" not in msg.text and errors.append(f"[{label}] {msg.text}"))
    page.on("pageerror", lambda exc: errors.append(f"[{label}] pageerror: {exc}"))
    page.route("https://cdn.jsdelivr.net/**", route_cdn)
    page.route("https://fonts.googleapis.com/**", lambda route: route.abort())
    page.route("https://fonts.gstatic.com/**", lambda route: route.abort())
    start = time.time()
    page.goto(base)
    page.wait_for_function("document.querySelector('#loading').hidden", timeout=90000)
    skeleton = time.time() - start
    page.wait_for_function("window.__atlas !== undefined", timeout=120000)
    print(f"[{label}] skeleton {skeleton:.1f}s, all muscles {time.time() - start:.1f}s")
    page.wait_for_timeout(1500)
    return page


def shot(page, name):
    page.wait_for_timeout(1500)
    # The software renderer used in tests is slow with the full body on screen.
    page.screenshot(path=str(OUT_DIR / f"{name}.png"), timeout=180000)


def main():
    server = serve()
    base = f"http://127.0.0.1:{server.server_address[1]}/index.html"
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])

        page = open_page(browser, base, (1360, 820), errors, "desktop")
        shot(page, "01-body")

        page.click("#pane-explore button[data-open='lower-limb']")
        shot(page, "02-lower-limb")
        page.click("#pane-explore button[data-open='thigh-knee']")
        shot(page, "03-thigh-knee")
        page.click("#pane-explore button[data-open='thigh-knee--hamstrings']")
        page.wait_for_timeout(600)
        page.click("#pane-explore button[data-open='semitendinosus']")
        page.fill("#ctl-knee", "80")
        page.dispatch_event("#ctl-knee", "input")
        shot(page, "04-semitendinosus-flexed")
        print("semitendinosus length:", page.inner_text("#length-value"))

        page.evaluate("window.__atlas.openEntity('body')")
        page.click("#tg-reset")
        page.click("#pane-explore button[data-open='upper-limb']")
        page.wait_for_timeout(600)
        page.click("#pane-explore button[data-open='shoulder']")
        shot(page, "05-shoulder")
        page.click("#pane-explore button[data-open='shoulder--deltoid']")
        page.wait_for_timeout(600)
        page.click("#pane-explore button[data-open='acromial-part-of-deltoid']")
        shot(page, "06-deltoid")

        page.click("#tab-movements")
        page.click("button[data-select-movement='shoulderAbd:+']")
        page.wait_for_timeout(3000)
        shot(page, "07-shoulder-abduction")
        print("abduction estimate:", page.inner_text("#pane-movements")[-400:].replace("\n", " | "))

        page.click("#tab-nerves")
        page.click("button[data-select-nerve='axillary']")
        shot(page, "08-axillary")

        page.click("#tab-movements")
        page.click("button[data-select-movement='scapular-upward-rotation']")
        shot(page, "08b-scapular-upward-rotation")

        page.evaluate("window.__atlas.openEntity('abdomen')")
        shot(page, "08c-abdomen")
        page.evaluate("window.__atlas.openEntity('abdomen--pelvic-floor')")
        shot(page, "08d-pelvic-floor")
        page.evaluate("window.__atlas.openEntity('rectus-abdominis')")
        shot(page, "08e-rectus-abdominis")

        page.evaluate("window.__atlas.openEntity('trunk')")
        page.click("#tab-movements")
        page.click("button[data-select-movement='trunkFlex:+']")
        page.wait_for_timeout(3000)
        shot(page, "09-trunk-flexion")

        page.evaluate("window.__atlas.openEntity('forearm')")
        page.click("#tab-movements")
        page.click("button[data-select-movement='forearmPro:+']")
        page.wait_for_timeout(3000)
        shot(page, "10-pronation")

        page.evaluate("window.__atlas.openEntity('thigh-knee')")
        page.click("#tab-quiz")
        page.click("button[data-quiz-start]")
        shot(page, "11-quiz")

        page.emulate_media(color_scheme="dark")
        page.evaluate("window.__atlas.openEntity('head-neck')")
        shot(page, "12-head-neck-dark")
        page.close()

        phone = open_page(browser, base, (400, 820), errors, "phone")
        shot(phone, "13-phone-body")
        phone.click("#pane-explore button[data-open='upper-limb']")
        shot(phone, "14-phone-upper-limb")
        phone.close()

        browser.close()

    server.shutdown()
    print("ERRORS:", len(errors))
    for error in errors[:30]:
        print("  ", error)


main()
