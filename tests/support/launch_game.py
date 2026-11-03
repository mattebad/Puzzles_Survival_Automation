"""Fake launcher/game ADB payloads for development launch-game tests."""


def _frame(tag: bytes = b"frame") -> bytes:
    """Minimal native PNG header sufficient for the controller's bounds check."""

    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + (800).to_bytes(4, "big")
        + (1280).to_bytes(4, "big")
        + tag
    )


def _focus(package: str) -> str:
    return f"mCurrentFocus=Window{{1 u0 {package}/.MainActivity}}\n"
