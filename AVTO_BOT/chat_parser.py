"""Helpers for extracting Telegram chat targets from pasted text."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_TELEGRAM_URL_RE = re.compile(
    r"(?i)(?<![\w@/.:\-])(?:https?://)?(?:www\.)?t\.me/[^\s<>\"',;!?(){}\[\]]+"
)
_USERNAME_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{5,32})(?![A-Za-z0-9_])")
_PEER_ID_RE = re.compile(r"(?<!\d)-100\d{5,15}(?!\d)")
_TRAILING_PUNCTUATION = ".,;:!?)]}>\"'"
_RESERVED_PATHS = {
    "addstickers",
    "addemoji",
    "addlist",
    "blog",
    "c",
    "iv",
    "joinchat",
    "login",
    "proxy",
    "s",
    "share",
    "setlanguage",
    "share/url",
}


def _canonical_tme_link(raw: str) -> str | None:
    """Return a canonical public username or invite target for a t.me URL."""
    candidate = raw.rstrip(_TRAILING_PUNCTUATION)
    if not candidate:
        return None
    if not candidate.lower().startswith(("http://", "https://")):
        candidate = "https://" + candidate
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if (parsed.hostname or "").lower() not in {"t.me", "www.t.me"}:
        return None

    segments = [part for part in parsed.path.split("/") if part]
    if not segments:
        return None
    first = segments[0]

    # Invite links are stored in an internal, explicit form. The bot only
    # resolves them for accounts that have already joined; it never joins a
    # group as a side effect of adding it.
    if first.startswith("+"):
        invite_hash = first[1:]
        if re.fullmatch(r"[A-Za-z0-9_-]{8,128}", invite_hash):
            return f"invite:{invite_hash}"
        return None
    if first.lower() == "joinchat" and len(segments) >= 2:
        invite_hash = segments[1]
        if re.fullmatch(r"[A-Za-z0-9_-]{8,128}", invite_hash):
            return f"invite:{invite_hash}"
        return None

    username = first
    if username.lower() in _RESERVED_PATHS:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        return None
    return "@" + username.lower()


def extract_invalid_telegram_links(text: str) -> list[str]:
    """Return malformed/unsupported t.me links for a useful user report."""
    if not text:
        return []
    invalid: list[str] = []
    seen: set[str] = set()
    for match in _TELEGRAM_URL_RE.finditer(text):
        raw = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        if raw and _canonical_tme_link(raw) is None and raw not in seen:
            seen.add(raw)
            invalid.append(raw)
    return invalid


def extract_chat_targets(text: str) -> list[str]:
    """Extract deduplicated Telegram usernames, invite links, and peer IDs.

    Non-link words, numbering, and surrounding punctuation are ignored.
    Only explicit @usernames, t.me links, and Telegram marked peer IDs are
    accepted, so ordinary numbers or unrelated URLs cannot become chats.
    """
    if not text:
        return []

    matches: list[tuple[int, int, str]] = []
    for match in _TELEGRAM_URL_RE.finditer(text):
        target = _canonical_tme_link(match.group(0))
        if target:
            matches.append((match.start(), match.end(), target))

    for match in _USERNAME_RE.finditer(text):
        matches.append((match.start(), match.end(), "@" + match.group(1).lower()))

    for match in _PEER_ID_RE.finditer(text):
        matches.append((match.start(), match.end(), match.group(0)))

    # Keep the order users pasted links in, and collapse aliases such as
    # @MyGroup and https://t.me/mygroup into one target.
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    targets: list[str] = []
    seen: set[str] = set()
    occupied_until = -1
    for start, end, target in matches:
        if start < occupied_until:
            continue
        occupied_until = end
        dedupe_key = target.lower() if target.startswith("@") else target
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        targets.append(target)
    return targets
