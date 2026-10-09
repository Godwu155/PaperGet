from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

import requests

from .errors import PaperGetError
from .http import HttpClient


def pdf_is_valid(path: Path) -> bool:
    try:
        if path.stat().st_size < 8:
            return False
        with path.open("rb") as file:
            return b"%PDF-" in file.read(1024)
    except OSError:
        return False


def filename_for_doi(doi: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", doi).strip("._")
    if len(safe) > 120:
        safe = safe[:100] + "_" + hashlib.sha256(doi.encode()).hexdigest()[:12]
    return safe + ".pdf"


class Downloader:
    def __init__(self, http: HttpClient, max_pdf_mb: int = 100):
        self.http = http
        self.max_bytes = max_pdf_mb * 1024 * 1024

    def download(self, url: str, destination: Path, *, force=False) -> str:
        if destination.exists() and not force and pdf_is_valid(destination):
            return self._hash(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
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
            if size < 8 or b"%PDF-" not in first:
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
                temp.unlink(missing_ok=True)

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
