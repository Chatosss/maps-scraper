"""
SQLite database para o Maps Scraper.
Armazena empresas coletadas e histórico de buscas.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional

DB_PATH = Path("maps_data.db")

# ── Conexão ───────────────────────────────────────────────────────────────────

@contextmanager
def _conn():
    """Abre uma conexão isolada; faz commit ou rollback automaticamente."""
    con = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")   # suporta leituras concorrentes
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ── Inicialização ─────────────────────────────────────────────────────────────

def init_db():
    """Cria as tabelas se não existirem."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS businesses (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                maps_url         TEXT UNIQUE NOT NULL,
                nome             TEXT DEFAULT '',
                categoria        TEXT DEFAULT '',
                avaliacao        TEXT DEFAULT '',
                total_avaliacoes TEXT DEFAULT '',
                telefone         TEXT DEFAULT '',
                website          TEXT DEFAULT '',
                instagram        TEXT DEFAULT '',
                endereco         TEXT DEFAULT '',
                scraped_at       TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at       TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE INDEX IF NOT EXISTS idx_maps_url ON businesses(maps_url);

            CREATE TABLE IF NOT EXISTS searches (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                query          TEXT NOT NULL,
                location       TEXT DEFAULT '',
                total_urls     INTEGER DEFAULT 0,
                total_new      INTEGER DEFAULT 0,
                total_cached   INTEGER DEFAULT 0,
                searched_at    TEXT DEFAULT (datetime('now', 'localtime'))
            );
        """)


# ── Operações de negócio ──────────────────────────────────────────────────────

_FIELDS = [
    "maps_url", "nome", "categoria", "avaliacao", "total_avaliacoes",
    "telefone", "website", "instagram", "endereco",
]


def get_business(maps_url: str) -> Optional[Dict]:
    """Retorna empresa do banco pelo maps_url, ou None se não existir."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM businesses WHERE maps_url = ?", (maps_url,)
        ).fetchone()
    return dict(row) if row else None


def save_business(data: Dict):
    """Insere ou atualiza uma empresa. Nunca sobrescreve campos com string vazia."""
    row = {k: (data.get(k) or "") for k in _FIELDS}
    with _conn() as con:
        con.execute("""
            INSERT INTO businesses
                (maps_url, nome, categoria, avaliacao, total_avaliacoes,
                 telefone, website, instagram, endereco)
            VALUES
                (:maps_url, :nome, :categoria, :avaliacao, :total_avaliacoes,
                 :telefone, :website, :instagram, :endereco)
            ON CONFLICT(maps_url) DO UPDATE SET
                nome             = excluded.nome,
                categoria        = excluded.categoria,
                avaliacao        = excluded.avaliacao,
                total_avaliacoes = excluded.total_avaliacoes,
                telefone         = CASE WHEN excluded.telefone  != '' THEN excluded.telefone  ELSE telefone  END,
                website          = CASE WHEN excluded.website   != '' THEN excluded.website   ELSE website   END,
                instagram        = CASE WHEN excluded.instagram != '' THEN excluded.instagram ELSE instagram END,
                endereco         = excluded.endereco,
                updated_at       = datetime('now', 'localtime')
        """, row)


def update_instagram(maps_url: str, instagram: str):
    """Atualiza apenas o campo instagram de uma empresa."""
    with _conn() as con:
        con.execute(
            "UPDATE businesses SET instagram = ?, updated_at = datetime('now','localtime') "
            "WHERE maps_url = ?",
            (instagram, maps_url),
        )


def save_search(query: str, location: str, total_urls: int, total_new: int, total_cached: int):
    """Registra uma busca no histórico."""
    with _conn() as con:
        con.execute(
            "INSERT INTO searches (query, location, total_urls, total_new, total_cached) "
            "VALUES (?, ?, ?, ?, ?)",
            (query, location, total_urls, total_new, total_cached),
        )


def get_searches(limit: int = 50) -> List[Dict]:
    """Retorna as últimas buscas do histórico, mais recente primeiro."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM searches ORDER BY searched_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> Dict:
    """Retorna estatísticas gerais do banco."""
    with _conn() as con:
        total    = con.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
        with_ig  = con.execute("SELECT COUNT(*) FROM businesses WHERE instagram != ''").fetchone()[0]
        with_web = con.execute("SELECT COUNT(*) FROM businesses WHERE website   != ''").fetchone()[0]
        searches = con.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
    return {
        "total":          total,
        "with_instagram": with_ig,
        "with_website":   with_web,
        "searches":       searches,
    }


def delete_business(maps_url: str):
    """Remove uma empresa do banco."""
    with _conn() as con:
        con.execute("DELETE FROM businesses WHERE maps_url = ?", (maps_url,))


def clear_all():
    """Remove todos os registros (útil para reset)."""
    with _conn() as con:
        con.execute("DELETE FROM businesses")
        con.execute("DELETE FROM searches")
