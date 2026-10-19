"""tools/stack_resolve.py: resolve every remote image in stack/ to the digest its tag points at today.

The stack doctrine is floating tags (``:latest`` unless a pin fixes a format); a floating tag is a
promise about *which* build runs, so the ledger ``stack/stack.versions.yml`` records what each tag
resolved to and when — the version truth of the stack without pinning the compose files. Registry
API v2 only (token challenge, manifest HEAD), no docker daemon, stdlib only. A vanished image is a
ledger line with ``vanished: true``, never a crash: the probe is the record, the reporting is
``repo_health.py``'s job. Exit is always 0."""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Final

TIMEOUT: Final = 30
USER_AGENT: Final = "e-stack-resolve"
MANIFEST_ACCEPT: Final = ", ".join(
    (
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.oci.image.index.v1+json",
    )
)
IMAGE_RE: Final = re.compile(r"^\s*image:\s*(\S+)\s*$", re.MULTILINE)
BUILD_RE: Final = re.compile(r"^\s*build:", re.MULTILINE)
PARKED_RE: Final = re.compile(r"stack\.parked:\s*\"?true\"?", re.MULTILINE)
CHALLENGE_KEY: Final = r'{key}="([^"]+)"'
SCHEMA: Final = 1


##### DISCOVERY #####


def refs(root: Path) -> list[tuple[str, str, str, bool, bool]]:
    """(service, category, image, local-build, parked) for every literal ``image:`` line under stack/.

    Compose files of scaffold folders (dot or underscore) are skipped, as management skips them; a
    service with a ``build:`` section owns images that live on this machine, not in a registry; a
    service labelled ``stack.parked: "true"`` is out of use and its upstream is never probed."""
    found: list[tuple[str, str, str, bool, bool]] = []
    for compose in sorted(root.rglob("compose.yml")):
        relative = compose.relative_to(root).parts
        if any(part.startswith((".", "_")) for part in relative):
            continue
        service, category = relative[1], relative[0]
        text = compose.read_text()
        local, parked = bool(BUILD_RE.search(text)), bool(PARKED_RE.search(text))
        found += [(service, category, ref, local, parked) for ref in IMAGE_RE.findall(text) if "${" not in ref]
    return sorted(set(found))


##### REGISTRY #####


def split(ref: str) -> tuple[str, str, str]:
    """(registry host, image name, tag) of a compose image ref, docker.io and ``latest`` filled in."""
    first, slash, remainder = ref.partition("/")
    registry = first if slash and ("." in first or ":" in first or first == "localhost") else "registry-1.docker.io"
    path = remainder if registry != "registry-1.docker.io" else ref
    name, sep, tag = path.rpartition(":")
    name, tag = (path, "latest") if not sep or "/" in tag else (name, tag)
    if registry == "registry-1.docker.io" and "/" not in name:
        name = f"library/{name}"
    return registry, name, tag


def _request(url: str, headers: dict[str, str]) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})


def _token(challenge: str, name: str) -> str:
    """A pull token from the registry's bearer realm; anonymous is enough for public images.

    Realm, service and scope arrive in any order and casing — quay says ``Realm``, github says
    ``service`` last — so each piece is plucked by key, not by position; a missing piece is a
    challenge this tool cannot answer, which surfaces as an unresolvable tag, never as a crash."""

    def piece(key: str) -> str:
        found = re.search(CHALLENGE_KEY.format(key=key), challenge, re.IGNORECASE)
        if not found:
            raise ValueError(f"no {key} in challenge")
        return found.group(1)

    url = f"{piece('realm')}?service={piece('service')}&scope={piece('scope').replace('*', name)}"
    with urllib.request.urlopen(_request(url, {}), timeout=TIMEOUT) as response:
        return str(json.load(response).get("token", ""))


def resolve(registry: str, name: str, tag: str) -> str | None:
    """The manifest digest the tag points at right now — None when the image or tag has vanished."""
    url = f"https://{registry}/v2/{name}/manifests/{tag}"
    headers = {"Accept": MANIFEST_ACCEPT}
    try:
        with urllib.request.urlopen(_request(url, headers), timeout=TIMEOUT) as response:
            return str(response.headers.get("Docker-Content-Digest", "")) or None
    except urllib.error.HTTPError as error:
        if error.code == 401 and (challenge := error.headers.get("WWW-Authenticate", "")):
            try:
                with urllib.request.urlopen(_request(url, {**headers, "Authorization": f"Bearer {_token(challenge, name)}"}), timeout=TIMEOUT) as retry:
                    return str(retry.headers.get("Docker-Content-Digest", "")) or None
            except Exception:  # noqa: BLE001 — an unreachable registry is an unresolvable tag, never a crash
                return None
        return None
    except Exception:  # noqa: BLE001 — same: the ledger records what could not be seen
        return None


##### LEDGER #####


def _scalar(value: Any) -> str:
    """One YAML scalar: bools bare, missing nulls bare, strings quoted."""
    return "true" if value is True else "false" if value is False else "null" if value is None else f"{value}" if isinstance(value, int) else f'"{value}"'


def ledger(entries: list[dict[str, Any]], resolved: str) -> str:
    """The YAML text of the version ledger — hand-emitted because the tool must run without any venv."""
    keys = ("category", "registry", "tag", "digest", "floating", "vanished", "build", "parked")
    lines = [f"schema: {SCHEMA}", f'resolved: "{resolved}"', "images:"]
    return "\n".join(
        [
            *lines,
            *(item for entry in entries for item in [f"- ref: {_scalar(entry['ref'])}", f"  service: {_scalar(entry['service'])}", *(f"  {key}: {_scalar(entry[key])}" for key in keys)]),
        ]
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("stack"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    entries = []
    for service, category, ref, local, parked in refs(args.root):
        registry, name, tag = split(ref) if not local else ("build", ref, ref.rpartition(":")[2] or "latest")
        digest = None if local or parked else resolve(registry, name, tag)
        entries.append(
            {
                "service": service,
                "category": category,
                "ref": ref,
                "registry": registry.removeprefix("registry-1."),
                "tag": tag,
                "digest": digest,
                "floating": local or parked or not re.match(r"^v?\d[\d.]*(-\w+)?$", tag),
                "vanished": not (local or parked) and digest is None,
                "build": local,
                "parked": parked,
            }
        )
        print(f"{ref}: {'BUILD' if local else 'PARKED' if parked else digest or 'VANISHED'}")
    args.output.write_text(ledger(entries, time.strftime("%Y-%m-%d", time.gmtime())))
    print(f"{len(entries)} images resolved -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
