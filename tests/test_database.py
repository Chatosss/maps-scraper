import pytest

import database


@pytest.fixture(autouse=True)
def banco_temporario(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "teste.db")
    database.init_db()


def empresa(**kw):
    base = {"maps_url": "https://maps.google.com/x", "nome": "Clinica Sorriso",
            "telefone": "(11) 4000-0000", "website": "https://exemplo.com.br"}
    base.update(kw)
    return base


def test_salva_e_le_empresa():
    database.save_business(empresa())
    e = database.get_business("https://maps.google.com/x")
    assert e["nome"] == "Clinica Sorriso"


def test_nova_coleta_vazia_nao_apaga_contato_ja_salvo():
    database.save_business(empresa(instagram="instagram.com/clinicasorriso"))
    database.save_business(empresa(telefone="", website="", instagram=""))
    e = database.get_business("https://maps.google.com/x")
    assert e["telefone"] == "(11) 4000-0000"
    assert e["instagram"] == "instagram.com/clinicasorriso"


def test_estatisticas():
    database.save_business(empresa())
    database.save_business(empresa(maps_url="https://maps.google.com/y", website=""))
    database.save_search("dentistas", "Recife", 2, 2, 0)
    s = database.get_stats()
    assert s == {"total": 2, "with_instagram": 0, "with_website": 1, "searches": 1}
