import pytest

from maps_scraper import IG_BLACKLIST, IG_RE, slugify, strip_icons


@pytest.mark.parametrize("html,esperado", [
    ('<a href="https://www.instagram.com/clinicasorriso/">', "clinicasorriso"),
    ("instagram.com/padaria.do.ze?hl=pt", "padaria.do.ze"),
])
def test_encontra_perfil_do_instagram(html, esperado):
    assert IG_RE.search(html).group(1) == esperado


def test_links_genericos_do_instagram_sao_ignorados():
    achados = IG_RE.findall("instagram.com/explore instagram.com/p/abc instagram.com/reels")
    assert all(h.lower() in IG_BLACKLIST for h in achados)


def test_remove_icones_do_texto():
    assert strip_icons(" (11) 4000-0000") == "(11) 4000-0000"


def test_nome_de_arquivo_da_busca():
    assert slugify("Clínicas Estética - Belo Horizonte") == "clínicas_estética_belo_horizonte"
