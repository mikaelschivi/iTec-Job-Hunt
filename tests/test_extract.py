import json
from datetime import datetime, timezone
from pathlib import Path

from watcher.extract import extract, html_to_lines, safe_url
from watcher.scrape import Listing

FIX = Path(__file__).parent / "fixtures"


def fixture(post_id):
    post = json.loads((FIX / f"post_{post_id}.json").read_text(encoding="utf-8"))
    listing = Listing(post_id, "t", "open", f"https://itecfurg.org/?p={post_id}")
    return extract(post, listing)


def synth(html):
    post = {"content": {"rendered": html}, "date_gmt": "2026-10-01T00:00:00"}
    return extract(post, Listing(1, "t", "open", "u"))


def test_13592_structured():
    s = fixture(13592)
    assert s.vacancies == "03 Vagas para Iniciação Científica"
    assert s.deadline == "12/10/2026"
    assert s.stipend == "R$1300,00"
    assert s.workload == "15h (semanais)"
    assert s.requirements == ["Experiência com Python", "Disponibilidade de horários"]
    assert len(s.desirable) == 4
    assert s.apply_link == "https://forms.gle/QJJiKXhwGcV19VY47"
    assert s.doc_link.endswith("/Edital-039_2026-IC-1-1.pdf")
    assert s.intro is None
    assert s.published == datetime(2026, 10, 2, 21, 29, 47, tzinfo=timezone.utc)


def test_12997_errata_not_picked():
    s = fixture(12997)
    assert s.stipend == "R$1.300,00"
    assert s.deadline == "01/06/2026"
    assert s.vacancies == "01 vaga para Apoio Administrativo"
    assert s.doc_link.endswith("Edital-030_2026-4.pdf")
    assert s.apply_link.startswith("https://forms.gle/")


def test_13249_unstructured_intro():
    s = fixture(13249)
    assert s.vacancies is None and s.deadline is None and s.stipend is None
    assert s.intro is not None and len(s.intro) <= 301
    assert s.intro.endswith("…")
    assert s.doc_link == "https://faurg.org.br/editais-para-credenciamento/"


def test_e20_inline_tag_splits():
    s = synth(
        "<p><strong>Requisitos</strong> (Obrigatórios):<br>Item A;<br>Item B</p>"
        "<p>Outros:</p><p>Bolsa <strong>R$</strong>1300,00</p>"
    )
    assert s.requirements == ["Item A", "Item B"]
    assert s.stipend == "R$1300,00"


def test_e21_requirement_broken_across_br():
    s = synth("<p>Requisitos:<br>Experiência com<br>python avançado;<br>Outro item.</p>")
    assert s.requirements == ["Experiência com python avançado", "Outro item"]


def test_e22_link_rejection():
    s = synth(
        '<p><a href="https://evil.tld/?forms.gle">x</a>'
        '<a href="javascript:alert(1)">y</a>'
        '<a href="http://forms.gle/abc">z</a></p>'
    )
    assert s.apply_link is None
    s = synth(
        '<p>Acesse o documento <a href="javascript:alert(1)">x</a></p>'
    )
    assert s.doc_link is None
    s = synth('<a href="https://docs.google.com/forms/d/1">f</a>')
    assert s.apply_link == "https://docs.google.com/forms/d/1"
    s = synth('<a href="https://docs.google.com/document/d/1">f</a>')
    assert s.apply_link is None


def test_e27_lowercase_items_kept():
    s = synth("<p>Requisitos:<br>python básico;<br>git;<br>docker</p>")
    assert s.requirements == ["python básico", "git", "docker"]


def test_pdf_fallback_for_doc_link():
    s = synth(
        '<p><a href="https://evil.tld/a.pdf">no</a>'
        '<a href="https://itecfurg.org/up/e.pdf">yes</a></p>'
    )
    assert s.doc_link == "https://itecfurg.org/up/e.pdf"


def test_deadline_second_pattern():
    s = synth("<p>Inscrições abertas, prazo: até 05/11/2026</p>")
    assert s.deadline == "05/11/2026"


def test_vacancies_cut_and_none():
    s = synth("<p>2 vagas - Inscrições até 01/01/2027</p>")
    assert s.vacancies == "2 vagas"
    assert synth("<p>nada</p>").vacancies is None


def test_list_cap_six():
    items = "".join(f"<li>Item {i}</li>" for i in range(10))
    s = synth(f"<p>Requisitos:</p><ul>{items}</ul>")
    assert len(s.requirements) == 6


def test_empty_content_never_raises():
    s = synth("")
    assert s.intro is None and s.requirements == []


def test_html_to_lines_block_aware():
    assert html_to_lines("<p>a<b>b</b></p><div>C</div>X<br>Y") == ["ab", "C", "X", "Y"]


def test_safe_url():
    assert safe_url("https://a.com/x") == "https://a.com/x"
    for bad in ["http://a.com", "javascript:alert(1)", "https://", "https://a.com/ x",
                "https://a.com/\x00", "", None, "//a.com"]:
        assert safe_url(bad) is None
