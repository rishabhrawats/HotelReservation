from __future__ import annotations

import re

from bs4 import BeautifulSoup


QUOTE_MARKERS = [
    r"^\s*-----Original Message-----\s*$",
    r"^\s*Original Message\s*$",
    r"^\s*From:\s+.+$",
    r"^\s*Sent:\s+.+$",
    r"^\s*On .+ wrote:\s*$",
]


def _html_to_text(body: str) -> str:
    soup = BeautifulSoup(body or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text("\n")


def _truncate_quoted_chain(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    marker_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in QUOTE_MARKERS]
    for line in lines:
        if any(pattern.match(line.strip()) for pattern in marker_patterns):
            break
        kept.append(line)
    return "\n".join(kept)


def _squash_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_email_body(body: str) -> str:
    original = body or ""
    plain = _html_to_text(original)
    cleaned = _squash_whitespace(_truncate_quoted_chain(plain))
    if cleaned:
        return cleaned
    fallback = _squash_whitespace(_html_to_text(original))
    return fallback if fallback else original.strip()

