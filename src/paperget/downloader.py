from __future__ import annotations

import hashlib
import os
import re
import tempfile
import unicodedata
from pathlib import Path

import requests

from .errors import PaperGetError
from .http import HttpClient


def pdf_is_valid(path: Path) -> bool:
    try:
        if path.stat().st_size < 8:
            return False
        with path.open("rb") as file:
            return file.read(5) == b"%PDF-"
    except OSError:
        return False


def filename_for_doi(doi: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", doi).strip("._")
    if len(safe) > 120:
        safe = safe[:100] + "_" + hashlib.sha256(doi.encode()).hexdigest()[:12]
    return safe + ".pdf"


def filename_for_paper(title: str, doi: str) -> str:
    """Use a readable, Windows-safe title with a stable DOI collision suffix."""
    clean = "".join(
        " " if char in '<>:"/\\|?*' or unicodedata.category(char).startswith("C") else char
        for char in unicodedata.normalize("NFC", title)
    )
    clean = re.sub(r"\s+", " ", clean).strip(" .")
    if not clean:
        return filename_for_doi(doi)
    suffix = hashlib.sha256(doi.casefold().encode("utf-8")).hexdigest()[:12]
    # Leave space for the suffix and extension in a Windows path component.
    units = 0
    end = 0
    for char in clean:
        units += len(char.encode("utf-16-le")) // 2
        if units > 120:
            break
        end += 1
    clean = clean[:end].rstrip(" .")
    if not clean:
        return filename_for_doi(doi)
    return f"{clean} [{suffix}].pdf"


class Downloader:
    def __init__(self, http: HttpClient, max_pdf_mb: int = 100):
        self.http = http
        self.max_bytes = max_pdf_mb * 1024 * 1024

    def download(self, url: str, destination: Path, *, force=False) -> str:
        if destination.exists() and not force and pdf_is_valid(destination):
            return self._hash(destination)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PaperGetError("disk_error", str(exc)) from exc
        response = self.http.get(url, stream=True)
        temp: Path | None = None
        try:
            if response.status_code == 404:
                raise PaperGetError("not_found", "PDF URL returned HTTP 404")
            length = response.headers.get("Content-Length")
            if length:
                try:
                    if int(length) > self.max_bytes:
                        raise PaperGetError("too_large", "PDF exceeds configured size limit")
                except ValueError:
                    pass

            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=destination.stem + "_", suffix=".part",
                dir=destination.parent, delete=False,
            ) as file:
                temp = Path(file.name)
                digest = hashlib.sha256()
                size = 0
                first = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise PaperGetError("too_large", "PDF exceeds configured size limit")
                    if len(first) < 1024:
                        first.extend(chunk[: 1024 - len(first)])
                    digest.update(chunk)
                    file.write(chunk)
            if size < 8 or not first.startswith(b"%PDF-"):
                raise PaperGetError("invalid_pdf", "Response was not a PDF")
            os.replace(temp, destination)
            temp = None
            return digest.hexdigest()
        except requests.RequestException as exc:
            raise PaperGetError("connection_error", str(exc)) from exc
        except OSError as exc:
            raise PaperGetError("disk_error", str(exc)) from exc
        finally:
            response.close()
            if temp is not None:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass

    def import_file(self, source: Path, destination: Path) -> str:
        """Copy a user-provided PDF through the same size and header checks."""
        try:
            if not source.is_file():
                raise PaperGetError("invalid_input", "Selected PDF file does not exist")
            size = source.stat().st_size
        except OSError as exc:
            raise PaperGetError("disk_error", str(exc)) from exc
        if size > self.max_bytes:
            raise PaperGetError("too_large", "PDF exceeds configured size limit")
        if not pdf_is_valid(source):
            raise PaperGetError("invalid_pdf", "Selected file is not a valid PDF")
        if destination.exists() and pdf_is_valid(destination):
            return self._hash(destination)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PaperGetError("disk_error", str(exc)) from exc
        temp: Path | None = None
        try:
            with source.open("rb") as input_file, tempfile.NamedTemporaryFile(
                mode="wb", prefix=destination.stem + "_", suffix=".part",
                dir=destination.parent, delete=False,
            ) as output_file:
                temp = Path(output_file.name)
                digest = hashlib.sha256()
                size = 0
                for chunk in iter(lambda: input_file.read(65536), b""):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise PaperGetError("too_large", "PDF exceeds configured size limit")
                    digest.update(chunk)
                    output_file.write(chunk)
            os.replace(temp, destination)
            temp = None
            return digest.hexdigest()
        except OSError as exc:
            raise PaperGetError("disk_error", str(exc)) from exc
        finally:
            if temp is not None:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
