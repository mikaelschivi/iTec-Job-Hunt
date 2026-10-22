import re

from watcher import config
from watcher.extract import Summary
from watcher.format import minimal, new_listing, status_change
from watcher.scrape import Listing


def listing(title="Edital 1 – Vaga", status="open"):
    return Listing(7, title, status, "https://itecfurg.org/?p=7")


def full_summary(**over):
    s = Summary(
        listing=listing(),
        vacancies="03 Vagas para IC",
        deadline="12/10/2026",
        stipend="R$1300,00",
        workload="15h (semanais)",
        requirements=["Python", "Horários"],
        desirable=["NLP"],
        apply_link="https://forms.gle/abc",
        doc_link="https://itecfurg.org/x.pdf",
        intro=None,
    )
    for k, v in over.items():
        setattr(s, k, v)
    return s


def assert_valid_html(text):
    assert text.count("<b>") == text.count("</b>")
    assert not re.search(r"&(?!(amp|lt|gt|quot|#\d+|#x[0-9a-f]+);)", text)
    stripped = re.sub(r"</?b>", "", text)
    assert "<" not in stripped and ">" not in stripped


def test_new_listing_layout():
    t = new_listing(full_summary())
    lines = t.split("\n")
    assert lines[0] == "🆕 <b>Nova vaga — iTEC FURG</b>"
    assert lines[1] == "<b>Edital 1 – Vaga</b>"
    assert "Status: 🟩 Inscrições abertas" in lines
    assert "Bolsa: R$1300,00 · CH: 15h (semanais)" in lines
    assert "• Python" in lines
    assert "📝 Inscrição: https://forms.gle/abc" in lines
    assert lines[-1] == "🔗 https://itecfurg.org/?p=7"
    assert_valid_html(t)


def test_e8_escaping():
    s = full_summary(
        listing=listing(title='A <b>&</b> "q"'),
        requirements=["x < y & z"],
        apply_link="https://forms.gle/a?x=1&y=\"2\"",
    )
    t = new_listing(s)
    assert "&lt;b&gt;&amp;&lt;/b&gt;" in t
    assert "x &lt; y &amp; z" in t
    assert "&amp;y=&quot;2&quot;" in t
    assert_valid_html(t)


def test_e9_long_message_drops_sections():
    s = full_summary(
        requirements=["r" * 300] * 10,
        desirable=["d" * 300] * 10,
        intro="i" * 5000,
        apply_link="https://forms.gle/" + "a" * 3000,
        doc_link="https://itecfurg.org/" + "b" * 3000,
    )
    t = new_listing(s)
    assert len(t) <= 4000
    assert_valid_html(t)
    assert t.startswith("🆕 <b>")
    assert t.endswith("🔗 https://itecfurg.org/?p=7")


def test_e9_amp_heavy_title_still_fits():
    s = full_summary(listing=listing(title="&" * 500), requirements=["&" * 120] * 6,
                     desirable=["<" * 120] * 6)
    t = new_listing(s)
    assert len(t) <= 4000
    assert_valid_html(t)


def test_field_caps():
    s = full_summary(vacancies="v" * 500, requirements=["x"] * 20)
    t = new_listing(s)
    assert "v" * 121 not in t
    assert t.count("• x") == 6


def test_plain_variant_no_tags_no_escape():
    s = full_summary(listing=listing(title="A & B <x>"))
    t = new_listing(s, html=False)
    assert "<b>" not in t
    assert "A & B <x>" in t
    assert "&amp;" not in t


def test_unknown_status_omits_status_line():
    t = new_listing(full_summary(listing=listing(status="unknown")))
    assert "Status:" not in t


def test_intro_only():
    s = Summary(listing=listing(), intro="Texto longo da introdução")
    t = new_listing(s)
    assert "Texto longo da introdução" in t
    assert "Bolsa" not in t and "Requisitos" not in t


def test_status_change():
    t = status_change(listing(title="Ed <1>"), "open", "closed")
    assert t == (
        "🔄 <b>Ed &lt;1&gt;</b>\n"
        "🟩 Inscrições abertas → 🟦 Inscrições finalizadas / em andamento\n"
        "🔗 https://itecfurg.org/?p=7"
    )
    p = status_change(listing(title="Ed <1>"), "closed", "done", html=False)
    assert "<b>" not in p and "Ed <1>" in p


def test_minimal():
    t = minimal(listing())
    assert "(detalhes indisponíveis)" in t
    assert "Inscrições abertas" in t
    assert_valid_html(t)
    assert "<b>" not in minimal(listing(), html=False)
    assert "Status" not in minimal(listing(status="unknown"))


def test_status_table_shared():
    for status, (emoji, label) in config.STATUS.items():
        assert label.startswith(emoji)
