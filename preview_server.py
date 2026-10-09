"""Build the site and serve dist/ at http://127.0.0.1:8000/.

Usage:
    python preview_server.py            # build, then serve
    python preview_server.py --no-build # serve the last build
    python preview_server.py --port 9000
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist'


class PreviewHandler(SimpleHTTPRequestHandler):
    """Serves dist/ and falls back to 404.html like a real static host."""

    def send_error(self, code, message=None, explain=None):
        page = DIST / '404.html'
        if code == 404 and page.exists():
            body = page.read_bytes()
            self.send_response(404)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)
            return
        super().send_error(code, message, explain)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description='Preview the STILLMRK site locally.')
    parser.add_argument('--no-build', action='store_true', help='Serve the existing dist/ without rebuilding.')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()

    if not args.no_build:
        result = subprocess.run([sys.executable, 'build_site.py'], cwd=ROOT)
        if result.returncode != 0:
            raise SystemExit(result.returncode)
    if not (DIST / 'index.html').exists():
        raise SystemExit('dist/ is empty. Run: python build_site.py')

    handler = partial(PreviewHandler, directory=str(DIST))
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    print(f'[STILLMRK preview] http://127.0.0.1:{args.port}/  (Ctrl+C to stop)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('[STILLMRK preview] Stopped.', flush=True)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
