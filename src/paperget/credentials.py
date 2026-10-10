"""Keep the GUI's OpenAlex key out of its ordinary settings file."""

from __future__ import annotations


_SERVICE = "PaperGet"
_ACCOUNT = "OpenAlex API Key"
_session_key: str | None = None
_UNSET = object()
_cached_key: str | None | object = _UNSET


def _backend():
    try:
        import keyring

        backend = keyring.get_keyring()
        # The Windows GUI uses the Windows Credential Manager backend. Never
        # silently fall back to a plaintext keyring implementation.
        if backend.__class__.__module__ != "keyring.backends.Windows":
            return None
        return keyring
    except Exception:
        return None


def get_openalex_key() -> str | None:
    global _cached_key
    if _session_key is not None:
        return _session_key
    if _cached_key is not _UNSET:
        return _cached_key
    backend = _backend()
    if backend is None:
        _cached_key = None
        return None
    try:
        _cached_key = backend.get_password(_SERVICE, _ACCOUNT) or None
    except Exception:
        _cached_key = None
    return _cached_key


def save_openalex_key(value: str) -> bool:
    """Return whether the key was saved persistently; otherwise keep it in memory."""
    global _session_key, _cached_key
    value = value.strip()
    if not value:
        raise ValueError("OpenAlex API Key cannot be empty")
    backend = _backend()
    if backend is not None:
        try:
            backend.set_password(_SERVICE, _ACCOUNT, value)
            _session_key = None
            _cached_key = value
            return True
        except Exception:
            pass
    _session_key = value
    return False


def clear_openalex_key() -> bool:
    """Return whether the persistent credential is absent after clearing."""
    global _session_key, _cached_key
    _session_key = None
    backend = _backend()
    if backend is None:
        return False
    try:
        if backend.get_password(_SERVICE, _ACCOUNT) is not None:
            backend.delete_password(_SERVICE, _ACCOUNT)
        _cached_key = None
        return True
    except Exception:
        return False
