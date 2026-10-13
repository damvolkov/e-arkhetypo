"""cortexdb-mirror — CortexDB's graph projected into an Obsidian vault as markdown, read-only.

Every pass: facts, beliefs and their supporting events are read from the /v1 API; entities that differ
only in case or a hash suffix fold into one note; a literal that names another entity becomes a
[[link]]; each entity links the vault notes it was extracted from. One note per entity under
<mirror>/<source folder>/, one `## heading` per predicate (folders2graph draws folders and headings as
graph nodes). A file is written only when its text changes, atomically; only files listed in the
mirror's own manifest are ever removed. Stdlib only: the container mounts this file, nothing is built.
"""

import hashlib
import json
import logging
import os
import re
import signal
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

URL = os.environ.get("CORTEX_URL", "http://cortexdb:3141").rstrip("/")
KEY = os.environ["CORTEX_API_KEY"]
SCOPES = [s.strip() for s in os.environ.get("MIRROR_SCOPES", "app:tinymemory/source:files/app:documents").split(",") if s.strip()]
EVERY = int(os.environ.get("MIRROR_EVERY", "600"))
VAULT = Path(os.environ.get("MIRROR_VAULT", "/vault"))
OUT = Path(os.environ.get("MIRROR_DIR", "/mirror"))
SOURCES = dict(pair.split("=", 1) for pair in os.environ.get("MIRROR_SOURCES", "").split(",") if "=" in pair)
HEARTBEAT = Path("/tmp/mirror.ok")
MANIFEST = ".cortex-mirror.json"
UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]+')
HASH_SUFFIX = re.compile(r"-[0-9a-f]{12,}$")
ANONYMOUS = "ent_fact_subject_"
SKIP_DIRS = {".obsidian", ".stfolder", ".trash", ".git"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s cortexdb-mirror %(message)s")
log = logging.getLogger("cortexdb-mirror")


class CortexClient:
    """The /v1 read surface: paginated facts and beliefs, events cached for good (they never change)."""

    def __init__(self) -> None:
        self.events: dict[str, dict] = {}

    def _get(self, path: str, **query: str) -> dict:
        url = f"{URL}{path}" + (f"?{urllib.parse.urlencode(query)}" if query else "")
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {KEY}"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    def _pages(self, path: str, scope: str) -> list[dict]:
        items, cursor = [], None
        while True:
            page = self._get(path, scope=scope, **({"cursor": cursor} if cursor else {}))
            items += page.get("items", [])
            cursor = page.get("next_cursor")
            if not (page.get("has_more") and cursor):
                return items

    def facts(self, scope: str) -> list[dict]:
        return self._pages("/v1/facts", scope)

    def beliefs(self, scope: str) -> list[dict]:
        return self._pages("/v1/beliefs", scope)

    def origin(self, event_id: str) -> dict:
        """Where an event came from: {source, file_path, title} out of tinymemory's chunked envelope label."""
        if event_id not in self.events:
            try:
                labels = self._get(f"/v1/events/{event_id}").get("context", {}).get("labels", [])
            except urllib.error.HTTPError as error:
                ### A forgotten event (a source removed with its items) is no origin, never a failed pass.
                if error.code != 404:
                    raise
                labels = []
            chunks = sorted((label.split(":", 3)[2], label.split(":", 3)[3]) for label in labels if label.startswith("tm:e:"))
            try:
                meta = json.loads("".join(text for _, text in chunks)).get("meta", {})
            except json.JSONDecodeError:
                meta = {}
            self.events[event_id] = {
                "source": meta.get("source", {}).get("id", ""),
                "file_path": meta.get("file_path", ""),
                "title": meta.get("title", ""),
            }
        return self.events[event_id]


class Projection:
    """Facts and beliefs folded into entity notes, linked to each other and to the vault."""

    def __init__(self, client: CortexClient, vault_notes: dict[str, list[str]]) -> None:
        self.client = client
        self.vault_notes = vault_notes

    @staticmethod
    def _key(name: str) -> str:
        return re.sub(r"[^a-z0-9]", "", name.lower())

    @staticmethod
    def _display(entity_id: str, named: dict[str, str]) -> str:
        raw = named.get(entity_id) or HASH_SUFFIX.sub("", entity_id.removeprefix("ent_")).replace("_", " ")
        return " ".join(word.capitalize() if word.islower() else word for word in raw.split())

    @staticmethod
    def _filename(name: str) -> str:
        return re.sub(r"\s+", " ", UNSAFE.sub(" ", name)).strip()[:120] or "unnamed"

    def _note_of(self, origin: dict) -> str:
        """The vault note an event was read from, as a link target (path without .md), or ""."""
        stem = Path(origin["file_path"]).stem
        folder = SOURCES.get(origin["source"], "")
        candidates = self.vault_notes.get(self._key(stem), [])
        inside = [path for path in candidates if folder and path.startswith(f"{folder}/")]
        return (inside or candidates or [""])[0]

    @staticmethod
    def _ranked(names: list[str]) -> list[tuple[str, int]]:
        """Most frequent first; a tie goes to the alphabetically first, so every pass names a note alike."""
        return sorted(Counter(names).items(), key=lambda kv: (-kv[1], kv[0]))

    def notes(self, facts: list[dict], beliefs: list[dict]) -> dict[str, str]:
        facts = sorted(facts, key=lambda f: f["id"])
        beliefs = sorted(beliefs, key=lambda b: b["id"])
        named = {b["claim"]["subject"]["id"]: b["claim"]["subject"]["name"] for b in beliefs if b.get("claim", {}).get("subject", {}).get("name")}
        groups: dict[str, list[dict]] = defaultdict(list)
        for fact in facts:
            if not fact["subject"]["id"].startswith(ANONYMOUS):
                groups[self._key(self._display(fact["subject"]["id"], named))].append(fact)
        names = {key: self._ranked([self._display(f["subject"]["id"], named) for f in group]) for key, group in groups.items()}
        unattributed = []
        for fact in (f for f in facts if f["subject"]["id"].startswith(ANONYMOUS)):
            text = str(fact["object"].get("value", "")).lower()
            owners = [key for key, ranked in names.items() if len(ranked[0][0]) > 3 and ranked[0][0].lower() in text]
            for key in owners:
                groups[key].append(fact)
            unattributed += [] if owners else [fact]
        files = {key: self._filename(ranked[0][0]) + (" (cortex)" if key in self.vault_notes else "") for key, ranked in names.items()}
        claims = defaultdict(list)
        for belief in beliefs:
            claims[self._key(self._display(belief["claim"]["subject"]["id"], named))].append(belief)
        notes = {
            f"{self._folder(group)}/{files[key]}.md": self._render(key, group, names[key], files, claims[key])
            for key, group in groups.items()
        }
        if unattributed:
            notes["Statements.md"] = self._statements(unattributed, files)
        return notes

    def _origins(self, group: list[dict]) -> list[dict]:
        events = sorted({event for fact in group for event in fact.get("supports", []) if event.startswith("evt_")})
        return [self.client.origin(event) for event in events]

    def _folder(self, group: list[dict]) -> str:
        sources = self._ranked([origin["source"] for origin in self._origins(group) if origin["source"]])
        return SOURCES.get(sources[0][0], "other") if sources else "other"

    def _statements(self, facts: list[dict], files: dict[str, str]) -> str:
        """What the extractor stated without naming a subject, grouped under the note it came from."""
        by_note: dict[str, set[str]] = defaultdict(set)
        for fact in facts:
            notes = {self._note_of(o) for o in self._origins([fact])} or {""}
            for note in notes:
                by_note[note].add(f"- {self._value(fact['object'], files)}")
        lines = ["---", 'generated: "cortexdb-mirror"', "---", "", "# Statements", ""]
        for note in sorted(by_note):
            lines += [f"## [[{note}]]" if note else "## (no source note)", "", *sorted(by_note[note]), ""]
        return "\n".join(lines)

    def _value(self, obj: dict, files: dict[str, str]) -> str:
        value = str(obj.get("value", obj.get("id", "")))
        target = files.get(self._key(value))
        return f"[[{target}]]" if target else value

    def _render(self, key: str, group: list[dict], ranked: list, files: dict[str, str], claims: list[dict]) -> str:
        name = ranked[0][0]
        aliases = [alias for alias, _ in ranked[1:]]
        origins = self._origins(group)
        sources = sorted({SOURCES.get(o["source"], o["source"]) for o in origins if o["source"]})
        by_predicate: dict[str, list[dict]] = defaultdict(list)
        for fact in group:
            by_predicate[fact["predicate"]].append(fact)
        front = {
            "cortex_ids": sorted({f["subject"]["id"] for f in group if not f["subject"]["id"].startswith(ANONYMOUS)}),
            "aliases": aliases,
            "sources": sources,
            "facts": len(group),
            "generated": "cortexdb-mirror",
        }
        lines = ["---", *(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items()), "---", "", f"# {name}", ""]
        lines += [f"Same entity as [[{self.vault_notes[key][0]}]].", ""] if key in self.vault_notes else []
        for predicate in sorted(by_predicate):
            lines += [f"## {predicate}", ""]
            lines += sorted({f"- {self._value(f['object'], files)}" for f in by_predicate[predicate]})
            lines.append("")
        if claims:
            lines += ["## Beliefs", ""]
            lines += sorted(
                {
                    f"- {b['claim']['predicate']} → {self._value(b['claim']['object'], files)} · {b.get('stance', '')} {b.get('confidence', 0):.2f}"
                    for b in claims
                }
            )
            lines.append("")
        links = sorted({(self._note_of(o), o["title"]) for o in origins if self._note_of(o)})
        if links:
            lines += ["## Sources", ""]
            lines += [f"- [[{path}|{title or Path(path).name}]]" for path, title in links]
            lines.append("")
        return "\n".join(lines)


class Mirror:
    """One pass at a time: project, write what changed atomically, retire only what the manifest says is ours."""

    def __init__(self) -> None:
        self.client = CortexClient()

    def _vault_notes(self) -> dict[str, list[str]]:
        notes: dict[str, list[str]] = defaultdict(list)
        mirror = OUT.resolve()
        for root, dirs, files in os.walk(VAULT):
            ### The mirror usually sits inside the vault: its own notes are never vault notes, whatever the mounts.
            dirs[:] = [
                d for d in dirs
                if d not in SKIP_DIRS and (Path(root) / d).resolve() != mirror and not (Path(root) / d / MANIFEST).exists()
            ]
            for file in files:
                if file.endswith(".md"):
                    rel = (Path(root) / file).relative_to(VAULT).with_suffix("")
                    notes[Projection._key(rel.name)].append(str(rel))
        return {key: sorted(paths, key=len) for key, paths in notes.items()}

    @staticmethod
    def _write(path: Path, text: str) -> bool:
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        return True

    def once(self) -> None:
        started = time.monotonic()
        facts = [fact for scope in SCOPES for fact in self.client.facts(scope)]
        beliefs = [belief for scope in SCOPES for belief in self.client.beliefs(scope)]
        notes = Projection(self.client, self._vault_notes()).notes(facts, beliefs)
        notes["README.md"] = (
            "# CortexDB mirror\n\nGenerated by `cortexdb-mirror` from CortexDB's facts and beliefs — **read-only**: "
            "every pass rewrites these notes, edits here are lost. Write to `wiki/` or `notes/` instead.\n"
        )
        written = sum(self._write(OUT / rel, text) for rel, text in notes.items())
        manifest = OUT / MANIFEST
        previous = set(json.loads(manifest.read_text())) if manifest.is_file() else set()
        stale = sorted(previous - set(notes))
        for rel in stale:
            (OUT / rel).unlink(missing_ok=True)
        ### Folders a retired source left empty go too — only inside the mirror, never the mirror itself.
        for root, dirs, files in os.walk(OUT, topdown=False):
            if Path(root) != OUT and not dirs and not files:
                Path(root).rmdir()
        self._write(manifest, json.dumps(sorted(notes), indent=1) + "\n")
        HEARTBEAT.write_text(str(time.time()))
        log.info(
            "pass facts=%d beliefs=%d entities=%d written=%d removed=%d events_cached=%d seconds=%.1f",
            len(facts), len(beliefs), len(notes) - 1, written, len(stale), len(self.client.events), time.monotonic() - started,
        )


def main() -> None:
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    mirror = Mirror()
    log.info("start url=%s scopes=%s every=%ds vault=%s out=%s", URL, SCOPES, EVERY, VAULT, OUT)
    while not stop.is_set():
        try:
            mirror.once()
        except Exception as error:  # a pass that fails is retried at the next tick, never fatal
            log.warning("pass failed: %s", error)
        stop.wait(EVERY)
    log.info("stopped")


if __name__ == "__main__":
    main()
