from __future__ import annotations

import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 8000


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)


def run_build() -> None:
    result = subprocess.run([sys.executable, 'build_site.py'], cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    run_build()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), PreviewHandler)
    print(f"[STILLMRK preview] http://127.0.0.1:{PORT}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[STILLMRK preview] Stopped.", flush=True)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
