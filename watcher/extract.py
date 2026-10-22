import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from watcher import config
from watcher.scrape import Listing

BLOCK_TAGS = ["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "tr"]
MAX_ITEMS = 6
INTRO_MIN = 80

VACANCIES_RE = re.compile(r"(?i)\b\d+\s+vagas?\b")
VACANCIES_CUT_RE = re.compile(r"\s+[–-]\s+|–")
DEADLINE_RE = re.compile(r"(?i)inscri[çc][õo]es\s+at[ée]\s+(\d{1,2}/\d{1,2}/\d{4})")
DEADLINE_LINE_RE = re.compile(r"(?i)\bat[ée]\s+(\d{1,2}/\d{1,2}/\d{4})")
STIPEND_RE = re.compile(r"R\$\s?\d[\d.]*,\d{2}")
WORKLOAD_RE = re.compile(r"(?i)\bCH:\s*(.+)")
REQUIREMENTS_RE = re.compile(r"(?i)^requisitos")
DESIRABLE_RE = re.compile(r"(?i)^conhecimentos\s+desej[áa]veis")
DOC_PHRASE_RE = re.compile(r"(?i)acesse o documento")


@dataclass
class Summary:
    listing: Listing
    vacancies: str | None = None
    deadline: str | None = None
    stipend: str | None = None
    workload: str | None = None
    requirements: list[str] = field(default_factory=list)
    desirable: list[str] = field(default_factory=list)
    apply_link: str | None = None
    doc_link: str | None = None
    intro: str | None = None
    published: datetime | None = None


def safe_url(url):
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url:
        return None
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return None
    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except ValueError:
        return None
    if parsed.scheme != "https" or not host:
        return None
    return url


def _join_continuations(lines):
    out = []
    for line in lines:
        if out:
            prev = out[-1]
            joins = prev.endswith(",") or (
                line[0].islower() and not prev.endswith((".", ";", ":"))
            )
            if joins:
                out[-1] = prev + " " + line
                continue
        out.append(line)
    return out


def html_to_lines(html):
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(BLOCK_TAGS):
        tag.append("\n")
    text = unicodedata.normalize("NFC", soup.get_text(""))
    lines = [line.strip() for line in text.split("\n")]
    return _join_continuations([line for line in lines if line])


def cap(text, limit):
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + "…"


def _vacancies(lines):
    for line in lines:
        if VACANCIES_RE.search(line):
            head = VACANCIES_CUT_RE.split(line)[0].strip()
            return head or None
    return None


def _deadline(lines):
    m = DEADLINE_RE.search("\n".join(lines))
    if m:
        return m.group(1)
    for line in lines:
        if "inscri" in line.lower():
            m = DEADLINE_LINE_RE.search(line)
            if m:
                return m.group(1)
    return None


def _section(lines, start_re):
    for i, line in enumerate(lines):
        if start_re.match(line):
            items = []
            for item in lines[i + 1 :]:
                if item.endswith(":") or len(items) >= MAX_ITEMS:
                    break
                items.append(item.rstrip(";,. ").strip())
            return [item for item in items if item]
    return []


def _host(url):
    try:
        return urlparse(url).hostname
    except ValueError:
        return None


def _path(url):
    try:
        return urlparse(url).path
    except ValueError:
        return ""


def _apply_link(soup):
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        host = _host(href)
        if host == "forms.gle" or (
            host == "docs.google.com" and _path(href).startswith("/forms")
        ):
            return safe_url(href)
    return None


def _doc_link(soup):
    node = soup.find(string=DOC_PHRASE_RE)
    if node is not None:
        parent = node.find_parent(["p", "div", "li"])
        if parent is not None:
            a = parent.find("a", href=True)
            if a is not None:
                return safe_url(a["href"])
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if _host(href) in config.SITE_HOSTS and _path(href).lower().endswith(".pdf"):
            return safe_url(href)
    return None


def _published(post):
    raw = post.get("date_gmt")
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def extract(post, listing):
    html = post["content"]["rendered"]
    lines = html_to_lines(html)
    text = "\n".join(lines)
    soup = BeautifulSoup(html, "html.parser")

    stipend = STIPEND_RE.search(text)
    workload = WORKLOAD_RE.search(text)
    summary = Summary(
        listing=listing,
        vacancies=_vacancies(lines),
        deadline=_deadline(lines),
        stipend=stipend.group(0) if stipend else None,
        workload=workload.group(1).strip() if workload else None,
        requirements=_section(lines, REQUIREMENTS_RE),
        desirable=_section(lines, DESIRABLE_RE),
        apply_link=_apply_link(soup),
        doc_link=_doc_link(soup),
        published=_published(post),
    )
    if not (summary.vacancies or summary.deadline or summary.stipend):
        for line in lines:
            if len(line) >= INTRO_MIN:
                summary.intro = cap(line, config.CAP_INTRO)
                break
    return summary
