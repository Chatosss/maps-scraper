# Maps Scraper

Coletor de empresas do Google Maps que fiz para montar listas de prospecção.
A partir de uma busca como "dentistas em Recife", ele junta nome, categoria,
nota, telefone, site, endereço e o Instagram da empresa, que ele procura
dentro do próprio site dela. Roda pela linha de comando ou por uma interface
gráfica, e exporta para CSV, JSON ou Excel.

A coleta mais completa, com qualificação e contato, está no
[LeadForge](https://github.com/Chatosss/leadforge).

*English version below.*

## O que ele faz

```
busca no Maps → rola a lista até o fim → abre cada empresa
        → extrai os dados → visita o site atrás do Instagram → CSV / JSON / Excel
```

- Coleta todos os resultados da busca, não só os primeiros: rola o painel de
  resultados até o Maps avisar que a lista acabou.
- Procura o Instagram no site de cada empresa, com até 5 sites abertos ao
  mesmo tempo, e ignora links genéricos como `/explore` ou `/p/`.
- Guarda tudo num banco SQLite. Numa busca repetida, empresas já coletadas
  vêm do banco em vez de serem raspadas de novo (dá para forçar a
  atualização).
- Interface em CustomTkinter com progresso por fase, tabela de resultados,
  histórico de buscas e exportação para Excel formatado.

## Partes que deram mais trabalho

- **Saber quando a lista acabou.** O Maps carrega os resultados aos poucos
  conforme a rolagem. O coletor rola com pausas levemente aleatórias e para
  quando aparece o aviso de fim de lista (em português ou inglês) ou quando
  passam 5 rolagens seguidas sem nenhum resultado novo.
- **Não perder dado bom numa coleta ruim.** Às vezes a página de uma empresa
  carrega pela metade e o telefone ou o site vêm vazios. O banco faz upsert
  pela URL do Maps e só sobrescreve telefone, site e Instagram quando o valor
  novo não está vazio.
- **Texto limpo.** O Maps mistura ícones da fonte Material Icons (caracteres
  da área de uso privado do Unicode) no texto de endereço e telefone. Eles são
  removidos antes de salvar.
- **Interface que não trava.** A raspagem roda com asyncio numa thread
  separada e conversa com a interface por uma fila, que a janela lê a cada
  80 ms.

## Tecnologias

Python 3, Playwright (async), SQLite, CustomTkinter, openpyxl, tqdm, pytest.

## Estrutura

| Caminho | O que tem |
|---|---|
| `maps_scraper.py` | coleta, extração e busca do Instagram; também é a versão de linha de comando |
| `app.py` | interface gráfica |
| `database.py` | banco SQLite com cache das empresas e histórico de buscas |
| `tests/` | testes do banco e da extração |

## Como rodar

Requisitos: Python 3.10+.

```bash
pip install -r requirements.txt
python -m playwright install chromium

python app.py                                          # interface gráfica
python maps_scraper.py "dentistas" -l "Recife, PE"     # linha de comando
python maps_scraper.py "academias" -l "Curitiba" --headless --no-instagram
```

Os arquivos saem na pasta `output/`. Para rodar os testes:
`pip install pytest` e `python -m pytest`.

## Uso responsável

Os termos de uso do Google não permitem coletar dados do Maps de forma
automatizada. Este projeto é um estudo de automação com Playwright. Se for
usar os dados para contato comercial, a LGPD também se aplica: só aborde
empresas pelos canais públicos delas e respeite quem pedir para não ser
contatado.

## Limitações

- Os seletores dependem do HTML atual do Google Maps e quebram quando ele
  muda.
- A coleta é sequencial na etapa de extração, então buscas grandes demoram.
- Só a busca do Instagram roda em paralelo.

---

## English

A Google Maps business scraper I built to create prospecting lists. Given a
search like "dentists in Recife", it collects name, category, rating, phone,
website, address and the business Instagram account, which it looks for on
the business website. It runs from the command line or a desktop GUI and
exports to CSV, JSON or Excel. A fuller version, with lead scoring and outreach, lives in
[LeadForge](https://github.com/Chatosss/leadforge).

**Highlights**

- **Knowing when the list ends**: it scrolls the results panel with slightly
  randomized pauses and stops at the end-of-list notice or after 5 scrolls
  with no new results.
- **Never losing good data to a bad scrape**: SQLite upsert keyed on the Maps
  URL that only overwrites phone, website and Instagram with non-empty values.
  Repeated searches reuse cached businesses.
- **Clean text**: strips Material Icons glyphs (Unicode private-use area)
  that Maps mixes into addresses and phone numbers.
- **Responsive GUI**: scraping runs with asyncio in a worker thread and talks
  to the CustomTkinter window through a queue.

**Stack**: Python 3, Playwright (async), SQLite, CustomTkinter, openpyxl.

**Note**: automated collection from Google Maps goes against Google's terms
of service. This is a study project in browser automation.

**Running it**: see *Como rodar* above. The commands are the same; the code
and the UI are in Portuguese.
