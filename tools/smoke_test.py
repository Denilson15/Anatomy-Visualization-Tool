"""
Headless smoke test: load the app, exercise each mode, save screenshots.

CDN requests for three.js are served from a local npm copy so the test
runs without network access; font requests are dropped.

Usage:
    python smoke_test.py <app_dir> <three_package_dir> <out_dir>
"""

import functools
import http.server
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright


APP_DIR = Path(sys.argv[1]).resolve()
THREE_DIR = Path(sys.argv[2]).resolve()
OUT_DIR = Path(sys.argv[3]).resolve()
OUT_DIR.mkdir(parents=True, exist_ok=True)

CDN_PREFIX = "https://cdn.jsdelivr.net/npm/three@0.169.0/"


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(APP_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def route_cdn(route):
    url = route.request.url
    if url.startswith(CDN_PREFIX):
        path = THREE_DIR / url[len(CDN_PREFIX):]
        route.fulfill(path=str(path), content_type="text/javascript")
    else:
        route.abort()


def main():
    server = serve()
    base = f"http://127.0.0.1:{server.server_address[1]}/index.html"
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
        )

        for label, viewport in (("desktop", (1360, 820)), ("phone", (400, 820))):
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            page.on("console", lambda msg: msg.type == "error" and errors.append(f"[{label}] {msg.text}"))
            page.on("pageerror", lambda exc: errors.append(f"[{label}] pageerror: {exc}"))
            page.route("https://cdn.jsdelivr.net/**", route_cdn)
            page.route("https://fonts.googleapis.com/**", lambda route: route.abort())
            page.route("https://fonts.gstatic.com/**", lambda route: route.abort())

            page.goto(base)
            page.wait_for_function("document.querySelector('#loading').hidden", timeout=60000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUT_DIR / f"{label}-1-thigh.png"))

            if label == "phone":
                page.close()
                continue

            # Muscle view + action playback.
            page.click("button[data-open='posterior-thigh']")
            page.wait_for_timeout(800)
            page.click("button[data-open='semitendinosus']")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT_DIR / f"{label}-2-muscle.png"))

            page.fill("#ctl-knee", "90")
            page.dispatch_event("#ctl-knee", "input")
            page.wait_for_timeout(600)
            length = page.inner_text("#length-value")
            page.screenshot(path=str(OUT_DIR / f"{label}-3-muscle-flexed.png"))
            print("semitendinosus length at 90° knee flexion:", length)

            # Side view of the flexed knee to check the rig direction.
            page.evaluate("""() => {
                const a = window.__atlas;
                a.orbit.target.set(-8, 50, 0);
                a.camera.position.set(-220, 55, 0);
            }""")
            page.wait_for_timeout(400)
            page.screenshot(path=str(OUT_DIR / f"{label}-3b-side-flexed.png"))

            # Ligaments.
            page.click("#tg-reset")
            page.click("nav#crumbs button[data-open='thigh-knee']")
            page.wait_for_timeout(500)
            page.click("button[data-open='knee-joint']")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT_DIR / f"{label}-4-knee-extended.png"))
            page.fill("#ctl-knee", "90")
            page.dispatch_event("#ctl-knee", "input")
            page.wait_for_timeout(800)
            page.screenshot(path=str(OUT_DIR / f"{label}-5-knee-flexed.png"))

            # Nerve mode.
            page.click("#tab-nerves")
            page.click("button[data-select-nerve='femoral']")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT_DIR / f"{label}-6-femoral.png"))

            # Movement mode.
            page.click("#tab-movements")
            page.click("button[data-select-movement='knee-flexion']")
            page.wait_for_timeout(2500)
            page.screenshot(path=str(OUT_DIR / f"{label}-7-movement.png"))

            # Quiz.
            page.click("#tab-quiz")
            page.click("button[data-quiz-start]")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT_DIR / f"{label}-8-quiz.png"))

            # Dark theme render of the explore panel.
            page.emulate_media(color_scheme="dark")
            page.click("#tab-explore")
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUT_DIR / f"{label}-9-dark.png"))
            page.close()

        browser.close()

    server.shutdown()
    print("ERRORS:", len(errors))
    for error in errors:
        print("  ", error)


main()
