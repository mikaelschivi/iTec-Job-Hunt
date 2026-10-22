import re
from pathlib import Path

from watcher.scrape import parse_listings, split_status

FIXTURE = Path(__file__).parent / "fixtures" / "vagas_page.html"


def load():
    return FIXTURE.read_text(encoding="utf-8")


def by_id(listings):
    return {l.id: l for l in listings}


def test_fixture_counts_and_dedupe():
    listings = parse_listings(load())
    ids = [l.id for l in listings]
    assert len(listings) == 26
    assert len(set(ids)) == 26
    assert 2695 not in ids


def test_statuses():
    d = by_id(parse_listings(load()))
    assert d[13592].status == "closed"
    assert d[13249].status == "open"
    assert d[13470].status == "done"
    assert d[12997].status == "unknown"


def test_titles_clean():
    d = by_id(parse_listings(load()))
    assert d[13592].title == "Edital 039/2026 – Vagas para iniciação cientifica"
    assert d[13470].title.startswith("Edital 037/2026")
    for l in d.values():
        assert not re.match(r"[\U0001F7E6\U0001F7E9\U0001F7EA]", l.title)
        assert "&#8211;" not in l.title
        assert l.url == f"https://itecfurg.org/?p={l.id}"


def test_first_occurrence_wins():
    html = (
        '<article id="post-1"><h4 class="entry-title"><a href="x">🟩 First</a></h4></article>'
        '<article id="post-1"><h4 class="entry-title"><a href="x">🟦 Second</a></h4></article>'
    )
    (l,) = parse_listings(html)
    assert l.title == "First" and l.status == "open"


def test_href_fallback_without_articles():
    html = re.sub(r"</?article\b[^>]*>", "", load())
    listings = parse_listings(html)
    ids = {l.id for l in listings}
    assert len(listings) == 26
    assert ids == {l.id for l in parse_listings(load())}
    assert 2695 not in ids


def test_href_fallback_rejects_foreign():
    html = (
        '<a href="https://evil.tld/?p=5">x</a>'
        '<a href="https://itecfurg.org/?page_id=2695">nav</a>'
        '<a href="https://itecfurg.org/other/?p=7">y</a>'
        '<a href="javascript:alert(1)">z</a>'
        '<a href="https://www.itecfurg.org/?p=9">🟩 ok</a>'
    )
    listings = parse_listings(html)
    assert [l.id for l in listings] == [9]


def test_title_fallback_first_anchor():
    html = (
        '<article id="post-3"><a href="/a"><img src="t.png"></a>'
        '<a href="/b">🟩 Real title</a></article>'
    )
    (l,) = parse_listings(html)
    assert l.title == "Real title"


def test_article_without_title_skipped():
    html = '<article id="post-3"><a href="/a"><img src="t.png"></a></article>'
    assert parse_listings(html) == []


def test_non_post_articles_ignored():
    html = '<article id="other-3"><h4 class="entry-title"><a>t</a></h4></article>'
    assert parse_listings(html) == []


def test_split_status_variants():
    assert split_status("🟪Edital 037/2026") == ("done", "Edital 037/2026")
    assert split_status("🟩️ Edital") == ("open", "Edital")
    assert split_status("\xa0 🟦  Edital  x") == ("closed", "Edital x")
    assert split_status("Edital sem emoji") == ("unknown", "Edital sem emoji")
    assert split_status("") == ("unknown", "")


def test_fe0f_in_page():
    html = '<article id="post-8"><h4 class="entry-title"><a>🟩️Edital 8</a></h4></article>'
    (l,) = parse_listings(html)
    assert (l.status, l.title) == ("open", "Edital 8")
