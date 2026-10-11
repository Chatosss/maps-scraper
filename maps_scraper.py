#!/usr/bin/env python3
"""
Google Maps Business Scraper
Coleta: nome, categoria, avaliacao, telefone, website, Instagram, endereco

Uso:
  python maps_scraper.py "dentistas" -l "Sao Paulo, SP"
  python maps_scraper.py "academias" -l "Curitiba" --headless
  python maps_scraper.py "clinicas estetica" -l "BH" --no-instagram --format csv
"""

import asyncio
import csv
import json
import re
import argparse
import random
from pathlib import Path
from typing import Optional, List, Dict
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from tqdm import tqdm

# ── Configuracao ──────────────────────────────────────────────────────────────
SCROLL_PAUSE    = 1.5     # segundos entre scrolls
JITTER          = 0.4     # variacao aleatoria
MAPS_TIMEOUT    = 20_000  # ms por pagina de empresa
WEBSITE_TIMEOUT = 9_000   # ms por site (scan Instagram)
MAX_IG_WORKERS  = 5       # scans paralelos de Instagram
OUTPUT_DIR      = Path("output")

IG_RE = re.compile(
    r'(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9](?:[A-Za-z0-9._]{0,28}[A-Za-z0-9])?)',
    re.IGNORECASE,
)
IG_BLACKLIST = {
    'login', 'p', 'explore', 'reels', 'reel', 'stories', 'tv',
    'accounts', 'about', 'press', 'api', 'privacy', 'safety',
    'legal', 'help', 'blog', 'developer', 'directory', 'lite',
}

# Texto que aparece quando chegou ao fim da lista de resultados
END_OF_LIST = [
    "voce chegou ao fim da lista",
    "chegou ao fim da lista",
    "fim da lista",
    "you've reached the end",
    "reached the end of the list",
]

# Icones Material Icons (Private Use Area unicode) que aparecem no texto
ICON_RE = re.compile(r'[-​-‍]+')

CSV_FIELDS = [
    "nome", "categoria", "avaliacao", "total_avaliacoes",
    "telefone", "website", "instagram", "endereco", "maps_url",
]
# ─────────────────────────────────────────────────────────────────────────────


def jitter_sleep(extra: float = 0.0):
    return asyncio.sleep(SCROLL_PAUSE + random.uniform(0, JITTER) + extra)


def slugify(text: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s-]+", "_", clean)[:60]


def strip_icons(text: str) -> str:
    """Remove icones Material Icons (PUA unicode) do texto."""
    return ICON_RE.sub("", text).strip()


# ── Utilitarios de extracao ───────────────────────────────────────────────────

async def safe_text(locator, timeout: int = 3000) -> str:
    try:
        if await locator.count():
            raw = await locator.first.inner_text(timeout=timeout)
            return strip_icons(raw)
    except Exception:
        pass
    return ""


async def safe_attr(locator, attr: str, timeout: int = 3000) -> str:
    try:
        if await locator.count():
            val = await locator.first.get_attribute(attr, timeout=timeout)
            return (val or "").strip()
    except Exception:
        pass
    return ""


# ── Consent popup ─────────────────────────────────────────────────────────────

async def dismiss_consent(page):
    """Fechar dialogo de cookies/consentimento do Google se aparecer."""
    for sel in [
        'button[aria-label="Aceitar tudo"]',
        'button[aria-label="Accept all"]',
        'button[jsname="higCR"]',
        '#L2AGLb',
        'button:has-text("Aceitar tudo")',
        'button:has-text("Accept all")',
        'button:has-text("Concordar")',
        'button:has-text("Agree")',
        'form:nth-child(2) button',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click(timeout=3000)
                await asyncio.sleep(1.5)
                return
        except Exception:
            pass


# ── Fase 1: Coletar URLs ──────────────────────────────────────────────────────

async def collect_urls(page, query: str, on_update=None) -> List[str]:
    """Navega direto para busca do Maps e faz scroll coletando todas as URLs.
    on_update(added, total) — callback opcional; sem ele usa tqdm.
    """
    # Navegar direto para URL de busca — evita interagir com caixa de texto
    # que pode nao aparecer em modo headless
    search_url = f"https://www.google.com/maps/search/{quote_plus(query)}"
    await page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
    await asyncio.sleep(1.5)

    # Fechar popup de consentimento se aparecer
    await dismiss_consent(page)

    # Se redirecionado para pagina de consentimento, aguardar retorno
    if "google.com/maps" not in page.url:
        try:
            await page.wait_for_url("**/maps/**", timeout=12_000)
        except Exception:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=20_000)
            await asyncio.sleep(2)
            await dismiss_consent(page)

    # Aguardar painel de resultados
    feed = page.locator('div[role="feed"]')
    try:
        await feed.wait_for(state="visible", timeout=15_000)
    except PWTimeout:
        print("[!] Sem resultados ou timeout aguardando feed.")
        return []

    collected: Dict[str, bool] = {}
    stale = 0

    use_tqdm = on_update is None
    pbar = tqdm(desc="Coletando URLs", unit=" empresa", colour="cyan", ncols=70) if use_tqdm else None

    while True:
        links = await page.locator('a[href*="/maps/place/"]').all()
        added = 0

        for link in links:
            try:
                href = await link.get_attribute("href")
                if not href:
                    continue
                base = href.split("?")[0].split("#")[0]
                if base not in collected:
                    collected[base] = True
                    added += 1
            except Exception:
                pass

        if added:
            if use_tqdm:
                pbar.update(added)
            else:
                on_update(added, len(collected))
            stale = 0
        else:
            stale += 1

        # Verificar mensagem de fim da lista
        try:
            feed_text = (await feed.inner_text(timeout=3000)).lower()
            if any(msg in feed_text for msg in END_OF_LIST):
                break
        except Exception:
            pass

        if stale >= 5:
            break  # Sem novos resultados por 5 rounds consecutivos

        await feed.evaluate("el => { el.scrollTop += el.clientHeight * 0.85; }")
        await jitter_sleep()

    if use_tqdm:
        pbar.close()
    return list(collected.keys())


# ── Fase 2: Extrair dados de cada empresa ─────────────────────────────────────

async def extract_business(page, url: str) -> Optional[Dict]:
    """Visitar URL do Maps e extrair dados estruturados."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=MAPS_TIMEOUT)
        await asyncio.sleep(1.0)
    except Exception:
        return None

    data = {
        "nome": "",
        "categoria": "",
        "avaliacao": "",
        "total_avaliacoes": "",
        "telefone": "",
        "website": "",
        "instagram": "",
        "endereco": "",
        "maps_url": url,
    }

    try:
        # ── Nome ──────────────────────────────────────────────────────────
        data["nome"] = await safe_text(page.locator("h1").first)

        # ── Categoria ─────────────────────────────────────────────────────
        for sel in [
            'button[jsaction*="category"]',
            'button[jsaction*="pane.rating"]',
            'div.skqShb button',
            '[data-item-id*="category"] span',
        ]:
            cat = await safe_text(page.locator(sel).first)
            if cat and len(cat) < 80:
                data["categoria"] = cat
                break

        # ── Avaliacao ─────────────────────────────────────────────────────
        for sel in [
            'div.F7nice span[aria-hidden="true"]',
            'span.ceNzKf span[aria-hidden="true"]',
            'div.fontBodyMedium span[aria-hidden="true"]',
        ]:
            rating = await safe_text(page.locator(sel).first)
            if rating and re.match(r'[\d,.]', rating):
                data["avaliacao"] = rating
                break

        # Total de avaliacoes
        for sel in [
            'span[aria-label*="avaliações"]',
            'span[aria-label*="reviews"]',
            'span[aria-label*="comentários"]',
        ]:
            aria = await safe_attr(page.locator(sel).first, "aria-label")
            if aria:
                m = re.search(r"[\d.,]+", aria)
                if m:
                    data["total_avaliacoes"] = m.group(0)
                    break

        # ── Itens de informacao ───────────────────────────────────────────
        items = await page.locator("[data-item-id]").all()
        for item in items:
            try:
                item_id = (await item.get_attribute("data-item-id") or "").lower()

                # Endereco
                if "address" in item_id and not data["endereco"]:
                    raw = await item.inner_text(timeout=2000)
                    data["endereco"] = strip_icons(raw).replace("\n", " ").strip()

                # Telefone — extrair de item_id ou do texto limpo
                elif item_id.startswith("phone:"):
                    if not data["telefone"]:
                        # Tentar text do elemento (mais legivel ex: (82) 9999-9999)
                        raw = strip_icons(await item.inner_text(timeout=2000))
                        phone = raw.strip()
                        # Se ficou vazio, extrair do item_id (phone:tel:XXXX)
                        if not phone:
                            phone = item_id.replace("phone:", "").replace("tel:", "").strip()
                        data["telefone"] = phone

                # Website — eh um <a> tag com href
                elif item_id == "authority":
                    href = await item.get_attribute("href") or ""
                    if href and not data["website"]:
                        data["website"] = href

                # Instagram listado diretamente no Maps
                elif "instagram" in item_id:
                    href = await item.get_attribute("href") or ""
                    m = IG_RE.search(href)
                    if m and m.group(1).lower() not in IG_BLACKLIST:
                        data["instagram"] = f"instagram.com/{m.group(1)}"

            except Exception:
                continue

        # ── Fallbacks ─────────────────────────────────────────────────────

        # Website via selector direto (caso nao encontrado no loop)
        if not data["website"]:
            href = await safe_attr(page.locator('a[data-item-id="authority"]'), "href")
            if href:
                data["website"] = href

        # Telefone via link tel:
        if not data["telefone"]:
            tel_href = await safe_attr(page.locator('a[href^="tel:"]').first, "href")
            if tel_href:
                data["telefone"] = tel_href.replace("tel:", "").strip()

        # Instagram via links na pagina do Maps
        if not data["instagram"]:
            ig_links = await page.locator('a[href*="instagram.com"]').all()
            for lnk in ig_links:
                href = await safe_attr(lnk, "href")
                m = IG_RE.search(href)
                if m and m.group(1).lower() not in IG_BLACKLIST:
                    data["instagram"] = f"instagram.com/{m.group(1)}"
                    break

    except Exception:
        pass

    return data if data["nome"] else None


# ── Fase 3: Buscar Instagram nos sites ───────────────────────────────────────

async def find_instagram_on_site(context, website_url: str) -> str:
    """Visitar o site da empresa e procurar link do Instagram."""
    if not website_url:
        return ""

    if "instagram.com" in website_url:
        m = IG_RE.search(website_url)
        if m and m.group(1).lower() not in IG_BLACKLIST:
            return f"instagram.com/{m.group(1)}"

    page = await context.new_page()
    try:
        await page.route(
            re.compile(r"\.(png|jpe?g|gif|webp|svg|woff2?|ttf|eot|mp4|webm|css)(\?.*)?$", re.I),
            lambda r: r.abort(),
        )
        await page.goto(website_url, wait_until="domcontentloaded", timeout=WEBSITE_TIMEOUT)

        content = await page.content()
        matches = IG_RE.findall(content)
        for handle in matches:
            if handle.lower() not in IG_BLACKLIST and 1 <= len(handle) <= 30:
                return f"instagram.com/{handle}"

        links = await page.locator('a[href*="instagram.com"]').all()
        for lnk in links:
            href = await safe_attr(lnk, "href")
            m = IG_RE.search(href)
            if m and m.group(1).lower() not in IG_BLACKLIST:
                return f"instagram.com/{m.group(1)}"

    except Exception:
        pass
    finally:
        await page.close()

    return ""


# ── Orquestrador principal ───────────────────────────────────────────────────

async def run(query: str, location: str, headless: bool, scan_ig: bool, fmt: str):
    OUTPUT_DIR.mkdir(exist_ok=True)

    full_query = f"{query} {location}".strip() if location else query
    slug = slugify(full_query)
    out_csv  = OUTPUT_DIR / f"{slug}.csv"
    out_json = OUTPUT_DIR / f"{slug}.json"

    print(f"\n{'='*60}")
    print(f"  Google Maps Scraper")
    print(f"  Busca    : {full_query}")
    print(f"  Saida    : {OUTPUT_DIR.resolve()}")
    print(f"  Headless : {headless} | Instagram: {scan_ig}")
    print(f"{'='*60}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--lang=pt-BR,pt", "--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": 1366, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
        )

        print("Fase 1  ›  Coletando URLs...")
        search_page = await context.new_page()
        urls = await collect_urls(search_page, full_query)
        await search_page.close()
        print(f"         → {len(urls)} empresas encontradas\n")

        if not urls:
            print("[!] Nenhuma URL coletada. Encerrando.")
            await browser.close()
            return []

        print("Fase 2  ›  Extraindo dados...")
        results: List[Dict] = []

        csv_file = open(out_csv, "w", newline="", encoding="utf-8-sig")
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()

        detail_page = await context.new_page()
        for url in tqdm(urls, desc="Extraindo", unit=" empresa", colour="green", ncols=70):
            data = await extract_business(detail_page, url)
            if data:
                results.append(data)
                writer.writerow({k: data.get(k, "") for k in CSV_FIELDS})
                csv_file.flush()

        await detail_page.close()
        csv_file.close()

        if scan_ig:
            to_scan = [d for d in results if d["website"] and not d["instagram"]]
            print(f"\nFase 3  ›  Buscando Instagram em {len(to_scan)} sites...")

            sem = asyncio.Semaphore(MAX_IG_WORKERS)

            async def bounded_scan(d: Dict):
                async with sem:
                    d["instagram"] = await find_instagram_on_site(context, d["website"])

            tasks = [bounded_scan(d) for d in to_scan]
            for coro in tqdm(asyncio.as_completed(tasks), total=len(tasks),
                             desc="Instagram", unit=" site", colour="magenta", ncols=70):
                await coro

            with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
                w.writeheader()
                w.writerows({k: d.get(k, "") for k in CSV_FIELDS} for d in results)

        await context.close()
        await browser.close()

    print(f"\n{'─'*45}")
    if fmt in ("csv", "both"):
        print(f"  CSV   →  {out_csv}")
    if fmt in ("json", "both"):
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"  JSON  →  {out_json}")

    print(f"\n  Total     : {len(results)} empresas")
    print(f"  Site      : {sum(1 for d in results if d.get('website'))}")
    print(f"  Telefone  : {sum(1 for d in results if d.get('telefone'))}")
    print(f"  Instagram : {sum(1 for d in results if d.get('instagram'))}")
    print(f"{'─'*45}\n")
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Google Maps Business Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python maps_scraper.py "dentistas" -l "Sao Paulo, SP"
  python maps_scraper.py "academias" -l "Curitiba" --headless
  python maps_scraper.py "restaurantes" -l "Rio de Janeiro" --no-instagram
        """,
    )
    parser.add_argument("query", help='Nicho a buscar (ex: "dentistas")')
    parser.add_argument("--location", "-l", default="", metavar="LOCAL")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-instagram", action="store_true")
    parser.add_argument("--format", choices=["csv", "json", "both"], default="both")

    args = parser.parse_args()
    asyncio.run(run(
        query=args.query, location=args.location, headless=args.headless,
        scan_ig=not args.no_instagram, fmt=args.format,
    ))


if __name__ == "__main__":
    main()
