"""Copy installed runtime dependency notices into a standalone build."""

from __future__ import annotations

import importlib.metadata as metadata
import re
import shutil
import sys
from pathlib import Path


RUNTIME_PACKAGES = (
    "requests", "certifi", "charset-normalizer", "idna", "urllib3",
    "keyring", "jaraco.classes", "jaraco.context", "jaraco.functools",
    "more-itertools", "pywin32-ctypes", "PySide6", "PySide6_Addons",
    "PySide6_Essentials", "shiboken6",
)
QT_PACKAGES = {"PySide6", "PySide6_Addons", "PySide6_Essentials", "shiboken6"}


def write_notices(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    licenses = destination / "licenses"
    rows = []
    for name in RUNTIME_PACKAGES:
        dist = metadata.distribution(name)
        package_name = dist.metadata["Name"]
        license_name = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "See upstream"
        copied = []
        if name not in QT_PACKAGES:
            for file in dist.files or []:
                if ".dist-info/" not in str(file).replace("\\", "/"):
                    continue
                if not re.match(r"^(LICENSE|NOTICE|COPYING)(\.|$)", file.name, re.IGNORECASE):
                    continue
                source = Path(dist.locate_file(file))
                if not source.is_file():
                    continue
                package_dir = licenses / re.sub(r"[^A-Za-z0-9_.-]", "_", package_name)
                package_dir.mkdir(parents=True, exist_ok=True)
                target = package_dir / file.name
                shutil.copyfile(source, target)
                copied.append(f"licenses/{package_dir.name}/{target.name}")
        rows.append(f"| {package_name} | {dist.version} | {license_name} | {', '.join(copied) or 'See upstream'} |")

    content = "\n".join((
        "# Third-party components",
        "",
        "This manifest was generated from the Python environment used to build this Windows package.",
        "Package metadata is a starting point; review the exact Qt modules and distribution terms before a public release.",
        "",
        "| Component | Version | License metadata | Included text |",
        "| --- | --- | --- | --- |",
        *rows,
        "",
        "Qt for Python (PySide6 and Shiboken6) is offered under LGPLv3/GPLv3 or a commercial license:",
        "https://doc.qt.io/qtforpython-6/",
        "Qt module licensing and GPL-only module list:",
        "https://doc.qt.io/qt-6/licensing.html",
        "Qt PDF includes PDFium and other third-party code:",
        "https://doc.qt.io/qt-6/licenses-used-in-qt.html#qt-pdf",
        "Qt's explanation of open-source obligations:",
        "https://www.qt.io/development/open-source-lgpl-obligations",
        "",
    ))
    (destination / "THIRD_PARTY_NOTICES.md").write_text(content, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: make-notices.py <standalone-dist-directory>")
    write_notices(Path(sys.argv[1]))
