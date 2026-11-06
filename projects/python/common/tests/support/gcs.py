"""tests/support/gcs: GCS's JSON API as the GCS driver speaks it — a bucket in a dict, behind a localhost server.

Enough of the API for every call `GCSBlobDriver` makes through gcloud-aio-storage: a simple upload (`uploadType=media`)
under `ifGenerationMatch` (412 when it does not hold), a download (`alt=media`), metadata, and a paged listing
(`prefix`, `maxResults`, `pageToken`). `fail` makes every request answer that status instead: a bucket that refuses.
It lets the blob contract run against the real driver with no emulator."""

import json
import re
from dataclasses import dataclass, field
from itertools import count
from typing import Final

from werkzeug import Request, Response

UPLOAD: Final[re.Pattern[str]] = re.compile(r"^/upload/storage/v1/b/(?P<bucket>[^/]+)/o$")
LISTING: Final[re.Pattern[str]] = re.compile(r"^/storage/v1/b/(?P<bucket>[^/]+)/o$")
OBJECT: Final[re.Pattern[str]] = re.compile(r"^/storage/v1/b/(?P<bucket>[^/]+)/o/(?P<name>.+)$")


@dataclass(slots=True)
class FakeGCS:
    """Objects by name, each its bytes and generation; generations only ever grow."""

    objects: dict[str, tuple[bytes, int]] = field(default_factory=dict)
    fail: int | None = None
    clock: count[int] = field(default_factory=lambda: count(1))

    def _item(self, name: str) -> dict[str, str]:
        data, generation = self.objects[name]
        return {"name": name, "generation": str(generation), "size": str(len(data))}

    @staticmethod
    def _json(payload: object, status: int = 200) -> Response:
        return Response(json.dumps(payload), status=status, content_type="application/json")

    def _missing(self) -> Response:
        return self._json({"error": {"code": 404, "message": "No such object"}}, 404)

    def _upload(self, request: Request) -> Response:
        name, wanted = request.args["name"], request.args.get("ifGenerationMatch")
        held = self.objects.get(name, (b"", 0))[1]
        match wanted is not None and int(wanted) != held:
            case True:
                return self._json({"error": {"code": 412, "message": "conditionNotMet"}}, 412)
        self.objects[name] = (request.get_data(), next(self.clock))
        return self._json(self._item(name))

    def _object(self, request: Request, name: str) -> Response:
        match (name in self.objects, request.args.get("alt")):
            case (False, _):
                return self._missing()
            case (True, "media"):
                return Response(self.objects[name][0], content_type="application/octet-stream")
            case _:
                return self._json(self._item(name))

    def _listing(self, request: Request) -> Response:
        names = sorted(name for name in self.objects if name.startswith(request.args.get("prefix", "")))
        start, size = int(request.args.get("pageToken") or 0), int(request.args.get("maxResults", 1000))
        page = {"items": [self._item(name) for name in names[start : start + size]]}
        more = {"nextPageToken": str(start + size)} if start + size < len(names) else {}
        return self._json({"kind": "storage#objects", **page, **more})

    def serve(self, request: Request) -> Response:
        """One request of the JSON API, answered from the dict — or with `fail`."""
        path = request.path
        match self.fail:
            case int() as status:
                return self._json({"error": {"code": status, "message": "refused"}}, status)
        match (request.method, UPLOAD.match(path), LISTING.match(path), OBJECT.match(path)):
            case ("POST", re.Match(), _, _):
                return self._upload(request)
            case ("GET", _, re.Match(), _):
                return self._listing(request)
            case ("GET", _, _, re.Match() as found):
                return self._object(request, found["name"])
            case _:
                return self._json({"error": {"code": 400, "message": f"unknown {request.method} {path}"}}, 400)
