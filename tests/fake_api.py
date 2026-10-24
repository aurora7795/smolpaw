"""
"Tidepool": a small invented harbour-logbook API, used to test whether a model can discover
an API no model has memorised. Run: .venv/bin/python tests/fake_api.py [port] [variant]

  GET /                 index of resources
  GET /v2/vessels       list of vessels
  GET /v2/vessels/<id>  one vessel
  GET /v2/berths        list of berths

Variants (harder discovery; the answer to "biggest cargo capacity" is always Kestrel, 340):
  easy    the default described above
  hint    "/" is a 404 whose body points at /v2/docs, which holds the index
  detail  the vessel list has only id and name; hold_tons is only on /v2/vessels/<id>
  paged   /v2/vessels returns 2 items per page with a "next" link; Kestrel is on page 2
"""

import json
import sys
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, HTTPServer

VARIANT = "easy"
PAGE_SIZE = 2
VESSELS = [
    {"id": 1, "name": "Marigold", "hold_tons": 120, "home_berth": "B3"},
    {"id": 3, "name": "Lantern", "hold_tons": 85, "home_berth": "C2"},
    {"id": 4, "name": "Osprey", "hold_tons": 210, "home_berth": "A4"},
    {"id": 2, "name": "Kestrel", "hold_tons": 340, "home_berth": "A1"},
    {"id": 5, "name": "Halcyon", "hold_tons": 275, "home_berth": "B1"},
]
BERTHS = [{"code": v["home_berth"], "occupied_by": v["name"]} for v in VESSELS]
INDEX = {
    "service": "Tidepool harbour logbook",
    "version": "2",
    "resources": {"vessels": "/v2/vessels", "berths": "/v2/berths"},
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: object) -> None:
        data = json.dumps(body, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        path = url.path.rstrip("/") or "/"
        if path == "/":
            if VARIANT == "hint":
                self._send(404, {"error": "not found", "docs": "/v2/docs"})
            else:
                self._send(200, INDEX)
        elif path == "/v2/docs" and VARIANT == "hint":
            self._send(200, INDEX)
        elif path == "/v2/vessels":
            if VARIANT == "detail":
                self._send(200, [{"id": v["id"], "name": v["name"]} for v in VESSELS])
            elif VARIANT == "paged":
                page = int(parse_qs(url.query).get("page", ["1"])[0])
                items = VESSELS[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
                more = page * PAGE_SIZE < len(VESSELS)
                self._send(200, {"items": items, "page": page,
                                 "next": f"/v2/vessels?page={page + 1}" if more else None})
            else:
                self._send(200, VESSELS)
        elif path.startswith("/v2/vessels/") and path.rsplit("/", 1)[1].isdigit():
            match = [v for v in VESSELS if v["id"] == int(path.rsplit("/", 1)[1])]
            self._send(200, match[0]) if match else self._send(404, {"error": "no such vessel"})
        elif path == "/v2/berths":
            self._send(200, BERTHS)
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    VARIANT = sys.argv[2] if len(sys.argv) > 2 else "easy"
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
