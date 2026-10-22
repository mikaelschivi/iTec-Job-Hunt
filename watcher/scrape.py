import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from watcher import config

log = logging.getLogger(__name__)

ARTICLE_ID_RE = re.compile(r"^post-(\d+)$")
QUERY_ID_RE = re.compile(r"^p=(\d+)$")
VS16 = "️"
EMOJI_TO_STATUS = {emoji: status for status, (emoji, _) in config.STATUS.items()}


@dataclass(frozen=True)
class Listing:
    id: int
    title: str
    status: str
    url: str


def split_status(title):
    text = title.strip()
    status = "unknown"
    if text and text[0] in EMOJI_TO_STATUS:
        status = EMOJI_TO_STATUS[text[0]]
        text = text[1:]
        if text.startswith(VS16):
            text = text[1:]
        text = text.strip()
    text = text.replace(VS16, "").strip()
    return status, re.sub(r"\s+", " ", text)


def make_listing(post_id, raw_title):
    status, title = split_status(raw_title)
    return Listing(
        id=post_id,
        title=title,
        status=status,
        url=config.LISTING_URL_TEMPLATE.format(id=post_id),
    )


def _article_title(article):
    link = article.select_one(".entry-title a")
    if link is not None:
        text = link.get_text(" ", strip=True)
        if text:
            return text
    for link in article.find_all("a"):
        text = link.get_text(" ", strip=True)
        if text:
            return text
    return None


def _from_articles(soup):
    found = {}
    for article in soup.find_all("article"):
        match = ARTICLE_ID_RE.match(article.get("id") or "")
        if not match:
            continue
        post_id = int(match.group(1))
        if post_id in found:
            continue
        title = _article_title(article)
        if title is None:
            log.warning("article post-%d has no title, skipped", post_id)
            continue
        found[post_id] = make_listing(post_id, title)
    return found


def _href_id(href):
    try:
        parsed = urlparse(href)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.hostname not in config.SITE_HOSTS:
        return None
    if parsed.path not in ("", "/"):
        return None
    match = QUERY_ID_RE.match(parsed.query)
    if not match:
        return None
    return int(match.group(1))


def _from_anchors(soup):
    found = {}
    for anchor in soup.find_all("a", href=True):
        post_id = _href_id(anchor["href"])
        if post_id is None or post_id in found:
            continue
        text = anchor.get_text(" ", strip=True)
        if not text:
            continue
        found[post_id] = make_listing(post_id, text)
    return found


def parse_listings(html):
    soup = BeautifulSoup(html, "html.parser")
    found = _from_articles(soup)
    if not found:
        found = _from_anchors(soup)
    return list(found.values())
