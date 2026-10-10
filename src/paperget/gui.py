"""PaperGet desktop entry point. Qt is imported only for the optional GUI."""

from __future__ import annotations


def main() -> int:
    try:
        from .gui_window import run
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            raise SystemExit("GUI dependency missing. Install with: pip install 'paperget[gui]'") from exc
        raise
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
