"""processors/md: the MDProcessor — any file to Markdown, detected and rendered by the engine behind `MarkdownPort`.

Detection, every format's conversion, PDF reading and image description live behind one port (`MarkdownPort`);
this processor only guards the size, unpacks a ZIP and re-enters each member in parallel,
and records an engine's failure per file so one bad member never sinks a batch. It holds no state: `convert`
is a pure function of bytes that returns a typed list of rendered files."""

import io
import zipfile
from dataclasses import replace
from pathlib import PurePath
from typing import TYPE_CHECKING

import anyio

from e_infra.infra.logger import logger
from e_infra.infra.settings import settings as st
from e_infra.processors.models import MarkdownFile

if TYPE_CHECKING:
    from pathlib import Path

    from e_infra.infra.config.md import MDSettings
    from e_infra.ports.markdown import MarkdownPort


##### ERRORS #####
class MDError(RuntimeError):
    """The processor refused the input before any conversion: not a format it knows, or too big."""


class UnsupportedFormatError(MDError):
    """No format was detected from the bytes and name: outside the spectrum, so it is not guessed."""


class InputTooLargeError(MDError):
    """The file crosses MD_MAX_INPUT_BYTES: rejected before the engine is invoked."""


class ZipBombError(MDError):
    """The archive crosses MD_ZIP_MAX_ENTRIES or MD_ZIP_MAX_BYTES: its members are never read."""


class MDProcessor:
    """Renders any file to Markdown through one engine; a ZIP is unpacked and each member re-entered."""

    __slots__ = ("_conf", "_md")

    def __init__(self, markdown: MarkdownPort, settings: MDSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.md if settings is None else settings
        self._md = markdown

    ##### PRIVATE — rendering #####

    def _file(
        self,
        name: str,
        markdown: str,
        source: str,
        *,
        warnings: tuple[str, ...] = (),
        path: str = "",
        error: str = "",
    ) -> MarkdownFile:
        """One rendered file, named after its source and traced to the format it was read as."""
        return MarkdownFile(
            name=PurePath(name or "document").stem + ".md",
            markdown=markdown,
            source=source,
            warnings=warnings,
            path=path,
            error=error,
        )

    async def _render(self, data: bytes, name: str, source: str) -> MarkdownFile:
        """Run the engine on one file; a failure becomes a file that carries the reason, never a raised abort.

        The detected `source` labels the file, but the engine wants its concrete extension — the name's own
        suffix when it has one (`code` is a category, `py` is the format), else the source itself."""
        extension = PurePath(name).suffix.lstrip(".").lower() or source
        try:
            conversion = await self._md.convert(data, extension=extension)
        except Exception as error:  # noqa: BLE001 — a leaf engine: its reason rides on the file, the run continues
            return self._file(name, "", source, error=f"{type(error).__name__}: {error}")
        return self._file(name, conversion.markdown, source, warnings=conversion.warnings)

    @staticmethod
    def _read_zip(data: bytes, entries: int, total: int) -> list[tuple[str, bytes]]:
        """A ZIP's members as (path, bytes), bounded before any byte is read: too many or too big is a bomb."""
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = [info for info in archive.infolist() if not info.is_dir()]
            if len(members) > entries or sum(info.file_size for info in members) > total:
                msg = f"archive of {len(members)} entries, {sum(info.file_size for info in members)} bytes, over limit"
                raise ZipBombError(msg)
            return [(info.filename, archive.read(info)) for info in members]

    async def _fan_out(self, data: bytes) -> list[MarkdownFile]:
        """Unpack a ZIP and re-enter every member through `convert` — nested archives recurse — bounded and in order."""
        members = await anyio.to_thread.run_sync(
            self._read_zip, data, self._conf.md_zip_max_entries, self._conf.md_zip_max_bytes
        )
        gate = anyio.Semaphore(self._conf.md_concurrency)
        rendered: list[list[MarkdownFile]] = [[] for _ in members]

        async def convert_one(index: int, path: str, raw: bytes) -> None:
            async with gate:
                children = await self.convert(raw, name=path)
                rendered[index] = [
                    replace(child, path=path if not child.path else f"{path}/{child.path}") for child in children
                ]

        async with anyio.create_task_group() as group:
            for index, (path, raw) in enumerate(members):
                group.start_soon(convert_one, index, path, raw)
        return [child for files in rendered for child in files]

    ############################################################

    ##### PUBLIC #####

    async def convert(self, source: bytes | Path, *, name: str = "") -> list[MarkdownFile]:
        """Render one file — any supported format, or a ZIP of them — to a list of typed Markdown files."""
        raw = source if isinstance(source, bytes) else await anyio.Path(source).read_bytes()
        label = name or getattr(source, "name", "") or "document"
        if len(raw) > self._conf.md_max_input_bytes:
            msg = f"{label!r} is {len(raw)} bytes, over MD_MAX_INPUT_BYTES"
            raise InputTooLargeError(msg)
        match self._md.detect(label, raw):
            case None:
                msg = f"{label!r} is not a format the processor converts"
                raise UnsupportedFormatError(msg)
            case "zip":
                files = await self._fan_out(raw)
            case fmt:
                files = [await self._render(raw, label, fmt)]
        logger.info(
            "markdown rendered", name=label, source=files[0].source if files else "", files=len(files), step="MD"
        )
        return files
