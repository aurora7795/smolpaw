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
  long    /v2/vessels returns 60 vessels, about 6,000 characters, so a reply clipped at 4,000 characters cuts it off;
          Kestrel, the biggest, is last. The list takes ?sort=hold_tons&order=desc&limit=N, named in the index
          (the clip marker's hint, #105: ask for less)
  book    a write: POST /v2/reservations {"vesselId": n, "berthId": n} books a vessel into a berth. Berths carry
          their own ids (not their codes), the vessel list is not in id order, and wrong ids are refused with
          a 404 and counted in /v2/_attempts (for the eval, not described anywhere). Osprey is vessel 4 and
          berth C1 is id 41. GET /v2/reservations lists what was booked; POST /v2/_reset starts over.
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
BOOK_BERTHS = [{"id": i, "code": c} for i, c in [(21, "A1"), (22, "A2"), (23, "A3"), (24, "A4"), (31, "B1"),
                                                  (33, "B3"), (41, "C1"), (42, "C2")]]
RESERVATIONS: list[dict] = []
ATTEMPTS: list[dict] = []  # every POST /v2/reservations that arrived, with the status it got
# Sixty vessels in id order; every hold is under 340 tons except Kestrel, id 60, the last of the list.
LONG_VESSELS = [{"id": i, "name": f"Skiff-{i:02d}", "hold_tons": 40 + (i * 37) % 250, "home_berth": f"{'ABC'[i % 3]}{i % 7 + 1}"}
                for i in range(1, 60)] + [{"id": 60, "name": "Kestrel", "hold_tons": 340, "home_berth": "A1"}]
LONG_INDEX = {"service": "Tidepool harbour logbook", "version": "2",
              "resources": {"vessels": "/v2/vessels", "berths": "/v2/berths"},
              "query": {"vessels": "sort (id|hold_tons), order (asc|desc), limit (number of items)"}}
INDEX = {
    "service": "Tidepool harbour logbook",
    "version": "2",
    "resources": {"vessels": "/v2/vessels", "berths": "/v2/berths"},
}
BOOK_INDEX = {**INDEX, "resources": {**INDEX["resources"], "reservations": "/v2/reservations"}}


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
                self._send(200, BOOK_INDEX if VARIANT == "book" else LONG_INDEX if VARIANT == "long" else INDEX)
        elif path == "/v2/docs" and VARIANT == "hint":
            self._send(200, INDEX)
        elif path == "/v2/vessels":
            if VARIANT == "detail":
                self._send(200, [{"id": v["id"], "name": v["name"]} for v in VESSELS])
            elif VARIANT == "long":
                q = parse_qs(url.query)
                items = sorted(LONG_VESSELS, key=lambda v: v.get(q.get("sort", ["id"])[0], v["id"]),
                               reverse=q.get("order", ["asc"])[0] == "desc")
                limit = q.get("limit", [""])[0]
                self._send(200, items[:int(limit)] if limit.isdigit() else items)
            elif VARIANT == "paged":
                page = int(parse_qs(url.query).get("page", ["1"])[0])
                items = VESSELS[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
                more = page * PAGE_SIZE < len(VESSELS)
                self._send(200, {"items": items, "page": page,
                                 "next": f"/v2/vessels?page={page + 1}" if more else None})
            else:
                self._send(200, VESSELS)
        elif path.startswith("/v2/vessels/") and path.rsplit("/", 1)[1].isdigit():
            match = [v for v in (LONG_VESSELS if VARIANT == "long" else VESSELS) if v["id"] == int(path.rsplit("/", 1)[1])]
            self._send(200, match[0]) if match else self._send(404, {"error": "no such vessel"})
        elif path == "/v2/berths":
            self._send(200, BOOK_BERTHS if VARIANT == "book" else BERTHS)
        elif path == "/v2/reservations" and VARIANT == "book":
            self._send(200, RESERVATIONS)
        elif path == "/v2/_attempts" and VARIANT == "book":
            self._send(200, ATTEMPTS)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if VARIANT != "book" or path not in ("/v2/reservations", "/v2/_reset"):
            self._send(404, {"error": "not found"})
        elif path == "/v2/_reset":
            RESERVATIONS.clear()
            ATTEMPTS.clear()
            self._send(200, {"ok": True})
        else:
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                body = None
            vessel_id = body.get("vesselId") if isinstance(body, dict) else None
            berth_id = body.get("berthId") if isinstance(body, dict) else None
            if vessel_id is None or berth_id is None:
                status, out = 422, {"error": "vesselId and berthId are required"}
            elif not any(v["id"] == vessel_id for v in VESSELS):
                status, out = 404, {"error": "no such vessel"}
            elif not any(b["id"] == berth_id for b in BOOK_BERTHS):
                status, out = 404, {"error": "no such berth"}
            else:
                status, out = 201, {"vesselId": vessel_id, "berthId": berth_id}
                RESERVATIONS.append(out)
            ATTEMPTS.append({"vesselId": vessel_id, "berthId": berth_id, "status": status})
            self._send(status, out)

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    VARIANT = sys.argv[2] if len(sys.argv) > 2 else "easy"
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
