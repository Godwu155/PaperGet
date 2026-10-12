"""Generate the PaperGet Windows icon from simple vector shapes."""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen


def draw_icon() -> QImage:
    image = QImage(256, 256, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#087E8B"))
    painter.drawRoundedRect(QRectF(8, 8, 240, 240), 46, 46)

    page = QPainterPath()
    page.moveTo(63, 42)
    page.lineTo(157, 42)
    page.lineTo(195, 80)
    page.lineTo(195, 204)
    page.quadTo(195, 216, 183, 216)
    page.lineTo(63, 216)
    page.quadTo(51, 216, 51, 204)
    page.lineTo(51, 54)
    page.quadTo(51, 42, 63, 42)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawPath(page)

    fold = QPainterPath()
    fold.moveTo(157, 42)
    fold.lineTo(157, 73)
    fold.quadTo(157, 80, 164, 80)
    fold.lineTo(195, 80)
    fold.closeSubpath()
    painter.setBrush(QColor("#C7E7EA"))
    painter.drawPath(fold)

    painter.setPen(QPen(QColor("#95BFC5"), 9, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(76, 104, 161, 104)
    painter.drawLine(76, 126, 147, 126)

    painter.setPen(QPen(QColor("#087E8B"), 14, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.drawLine(123, 147, 123, 185)
    painter.drawLine(106, 169, 123, 186)
    painter.drawLine(140, 169, 123, 186)
    painter.drawLine(99, 197, 147, 197)
    painter.end()
    return image


def to_png(image: QImage, size: int) -> bytes:
    scaled = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    if not scaled.save(buffer, "PNG"):
        raise RuntimeError("Cannot encode icon PNG")
    data = bytes(buffer.data())
    buffer.close()
    return data


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "src" / "paperget" / "assets" / "paperget.ico"
    target.parent.mkdir(parents=True, exist_ok=True)
    image = draw_icon()
    sizes = (16, 32, 48, 256)
    payloads = [to_png(image, size) for size in sizes]
    offset = 6 + 16 * len(sizes)
    entries = bytearray()
    for size, payload in zip(sizes, payloads):
        encoded_size = 0 if size == 256 else size
        entries.extend(struct.pack("<BBBBHHII", encoded_size, encoded_size, 0, 0,
                                   1, 32, len(payload), offset))
        offset += len(payload)
    target.write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + entries + b"".join(payloads))
    print(target)


if __name__ == "__main__":
    main()
