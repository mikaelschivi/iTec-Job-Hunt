import html as htmllib

from watcher import config
from watcher.extract import cap

DROP_ORDER = [
    "desirable",
    "requirements",
    "intro",
    "workload",
    "doc_link",
    "apply_link",
    "deadline",
    "stipend",
    "vacancies",
]


def status_label(status):
    entry = config.STATUS.get(status)
    return entry[1] if entry else config.UNKNOWN_LABEL


def _esc(text, use_html):
    if not use_html:
        return text
    return htmllib.escape(text, quote=True)


def _bold(text, use_html):
    return f"<b>{_esc(text, True)}</b>" if use_html else text


def _items(items):
    return [cap(item, config.CAP_ITEM) for item in items[: config.CAP_ITEMS]]


def _build(summary, parts, use_html):
    e = lambda s: _esc(s, use_html)
    lines = [
        "🆕 " + _bold("Nova vaga — iTEC FURG", use_html),
        _bold(cap(summary.listing.title, config.CAP_TITLE), use_html),
    ]
    if summary.listing.status in config.STATUS:
        lines.append("Status: " + e(status_label(summary.listing.status)))
    if "intro" in parts:
        lines.append(e(cap(summary.intro, config.CAP_INTRO)))
    if "vacancies" in parts:
        lines.append(e(cap(summary.vacancies, config.CAP_FIELD)))
    if "deadline" in parts:
        lines.append("Inscrições até: " + e(cap(summary.deadline, config.CAP_FIELD)))
    money = []
    if "stipend" in parts:
        money.append("Bolsa: " + e(cap(summary.stipend, config.CAP_FIELD)))
    if "workload" in parts:
        money.append("CH: " + e(cap(summary.workload, config.CAP_FIELD)))
    if money:
        lines.append(" · ".join(money))
    if "requirements" in parts:
        lines.append("Requisitos:")
        lines.extend("• " + e(item) for item in _items(summary.requirements))
    if "desirable" in parts:
        lines.append("Desejáveis:")
        lines.extend("• " + e(item) for item in _items(summary.desirable))
    if "apply_link" in parts:
        lines.append("📝 Inscrição: " + e(summary.apply_link))
    if "doc_link" in parts:
        lines.append("📄 Edital: " + e(summary.doc_link))
    lines.append("🔗 " + e(summary.listing.url))
    return "\n".join(lines)


def new_listing(summary, html=True):
    parts = {
        name
        for name in DROP_ORDER
        if getattr(summary, name)
    }
    text = _build(summary, parts, html)
    for name in DROP_ORDER:
        if len(text) <= config.TELEGRAM_MAX_CHARS:
            break
        parts.discard(name)
        text = _build(summary, parts, html)
    return text


def status_change(listing, old_status, new_status, html=True):
    title = cap(listing.title, config.CAP_TITLE)
    return "\n".join(
        [
            "🔄 " + _bold(title, html),
            f"{_esc(status_label(old_status), html)} → {_esc(status_label(new_status), html)}",
            "🔗 " + _esc(listing.url, html),
        ]
    )


def minimal(listing, html=True):
    lines = [_bold(cap(listing.title, config.CAP_TITLE), html)]
    if listing.status in config.STATUS:
        lines.append(_esc(status_label(listing.status), html))
    lines.append("(detalhes indisponíveis)")
    lines.append("🔗 " + _esc(listing.url, html))
    return "\n".join(lines)
