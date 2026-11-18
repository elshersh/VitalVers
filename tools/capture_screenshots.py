"""
tools/capture_screenshots.py — Deterministic Playwright screenshot runner for Before/After checks.

Serves a target directory over ephemeral localhost HTTP and captures 1440x900 (desktop)
and 390x844 (mobile) full-page PNGs.
"""
import argparse
import functools
import http.server
import os
import socketserver
import sys
import threading
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def _serve_dir(directory: str):
    handler = functools.partial(_QuietHandler, directory=directory)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port


def _parse_page_entry(entry: str) -> tuple[str, str]:
    if "=" in entry:
        slug, url_path = entry.split("=", 1)
        return slug.strip(), url_path.strip()
    clean = entry.split("?", 1)[0].split("#", 1)[0]
    return os.path.splitext(clean)[0], entry


def capture(
    root_dir: str,
    out_dir: str,
    pages: list[str],
    allow_api_404: bool = False,
    fail_on_errors: bool = False,
) -> int:
    os.makedirs(out_dir, exist_ok=True)
    httpd, port = _serve_dir(root_dir)
    base_url = f"http://127.0.0.1:{port}"
    fatal_errors: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for vp_name, width, height, mobile in (
                ("1440", 1440, 900, False),
                ("390", 390, 844, True),
            ):
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    is_mobile=mobile,
                    has_touch=mobile,
                    device_scale_factor=1,
                )
                for entry in pages:
                    slug, page_path = _parse_page_entry(entry)
                    page = context.new_page()
                    page_errors: list[str] = []
                    console_errors: list[str] = []
                    bad_assets: list[str] = []
                    external_requests: list[str] = []
                    page.on("pageerror", lambda err, errs=page_errors: errs.append(str(err)))
                    page.on(
                        "console",
                        lambda msg, cerrs=console_errors: cerrs.append(f"{msg.text} ({msg.location.get('url', '')})")
                        if msg.type == "error"
                        else None,
                    )

                    def _on_request(req, ext=external_requests):
                        parsed = urlparse(req.url)
                        if parsed.scheme in ("data", "blob"):
                            return
                        if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
                            ext.append(req.url)

                    def _on_response(resp, b_assets=bad_assets):
                        if resp.status >= 400 and resp.url.startswith(base_url):
                            rel = resp.url[len(base_url):]
                            if allow_api_404 and rel.startswith("/api/"):
                                return
                            b_assets.append(f"{resp.status} {rel}")

                    page.on("request", _on_request)
                    page.on("response", _on_response)
                    url = f"{base_url}/{page_path.lstrip('/')}"
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    page.evaluate("""() => Promise.race([
                        Promise.all(Array.from(document.images).map(i => i.complete ? Promise.resolve() : new Promise(r => { i.onload = r; i.onerror = r; }))),
                        new Promise(r => setTimeout(r, 3000))
                    ])""")
                    page.evaluate("""() => Promise.race([
                        document.fonts ? document.fonts.ready : Promise.resolve(),
                        new Promise(r => setTimeout(r, 1500))
                    ])""")
                    if "dashboard" in page_path or "mental" in page_path:
                        page.wait_for_timeout(1800)
                    else:
                        page.wait_for_timeout(700)
                    out_path = os.path.join(out_dir, f"{slug}_{vp_name}.png")
                    page.screenshot(path=out_path, full_page=True)
                    print(f"[ok] {out_path}")

                    for err in page_errors:
                        msg = f"[{slug} {vp_name}] pageerror: {err}"
                        print(f"[ERR] {msg}", file=sys.stderr)
                        fatal_errors.append(msg)
                    for asset in bad_assets:
                        msg = f"[{slug} {vp_name}] HTTP {asset}"
                        print(f"[ERR] {msg}", file=sys.stderr)
                        fatal_errors.append(msg)
                    for ext_url in external_requests:
                        msg = f"[{slug} {vp_name}] external request: {ext_url}"
                        print(f"[ERR] {msg}", file=sys.stderr)
                        fatal_errors.append(msg)
                    for cerr in console_errors:
                        if allow_api_404 and "/api/" in cerr and "404" in cerr:
                            continue
                        msg = f"[{slug} {vp_name}] console.error: {cerr}"
                        print(f"[ERR] {msg}", file=sys.stderr)
                        fatal_errors.append(msg)

                    page.close()
                context.close()
            browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()

    if fail_on_errors and fatal_errors:
        print(f"[FAIL] {len(fatal_errors)} runtime/asset errors encountered.", file=sys.stderr)
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--pages", nargs="+", required=True)
    parser.add_argument("--allow-api-404", action="store_true")
    parser.add_argument("--fail-on-errors", action="store_true")
    args = parser.parse_args()
    rc = capture(
        os.path.abspath(args.root),
        os.path.abspath(args.out),
        args.pages,
        allow_api_404=args.allow_api_404,
        fail_on_errors=args.fail_on_errors,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
