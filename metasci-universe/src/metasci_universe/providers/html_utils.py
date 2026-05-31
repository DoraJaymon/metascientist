"""Small HTML helpers for lightweight conference spiders."""

from __future__ import annotations

from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Any


@dataclass
class Link:
    href: str
    text: str = ""
    attrs: dict[str, str] = field(default_factory=dict)


class LinkParser(HTMLParser):
    """Extract links and text snippets without adding an HTML parser dependency."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[Link] = []
        self.text_parts: list[str] = []
        self._current_link: Link | None = None
        self._link_text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {key.lower(): value or "" for key, value in attrs}
        href = attr_map.get("href")
        if href:
            self._current_link = Link(href=href, attrs=attr_map)
            self._link_text_parts = []

    def handle_data(self, data: str) -> None:
        text = _clean_text(data)
        if not text:
            return
        self.text_parts.append(text)
        if self._current_link is not None:
            self._link_text_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current_link is None:
            return
        self._current_link.text = _clean_text(" ".join(self._link_text_parts))
        self.links.append(self._current_link)
        self._current_link = None
        self._link_text_parts = []

    @property
    def text(self) -> str:
        return _clean_text(" ".join(self.text_parts))


def extract_links(html: str) -> list[Link]:
    parser = LinkParser()
    parser.feed(html)
    return parser.links


def html_text(html: str) -> str:
    parser = LinkParser()
    parser.feed(html)
    return parser.text


def _clean_text(value: Any) -> str:
    text = unescape(str(value or ""))
    return " ".join(text.split())
