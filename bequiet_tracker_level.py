# bequiet_tracker_level.py
import os, sys, json, time, re
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# --------- Einstellungen ---------
GUILD_NAME   = "beQuiet"
RANKING_URL  = "https://pr-underworld.com/website/ranking/"
HOME_URL     = "https://pr-underworld.com/website/"
TIMEOUT      = 20

STATE_FILE   = Path("state.json")                 # speichert bekannte Level
MEMBERS_FILE = Path("bequiet_members.txt")        # eine Zeile pro Name
WEBHOOK      = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

# --------- Helpers: IO / Discord ---------
def fetch_html(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": "beQuiet level tracker"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text

def post_to_discord(content: str):
    if not WEBHOOK:
        print("No DISCORD_WEBHOOK_URL set; skip posting", file=sys.stderr)
        return
    r = requests.post(WEBHOOK, json={"content": content}, timeout=15)
    try:
        r.raise_for_status()
    except Exception as e:
        print(f"Discord error: {e} {getattr(r, 'text', '')}", file=sys.stderr)

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"levels": {}}  # name -> last_known_level (int)

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def load_members() -> list[str]:
    if not MEMBERS_FILE.exists():
        return []
    names = []
    for line in MEMBERS_FILE.read_text(encoding="utf-8").splitlines():
        n = line.strip()
        if n:
            names.append(n)
    return names

def save_members(names: set[str]):
    seen_ci = set()
    out = []
    for n in sorted(names, key=lambda s: s.lower()):
        key = n.lower()
        if key in seen_ci:
            continue
        seen_ci.add(key)
        out.append(n)
    MEMBERS_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")

# --------- Parsen: Utilities ---------
def _is_bequiet(text: str) -> bool:
    return GUILD_NAME.lower() in text.lower()

def _digits_only(s: str) -> bool:
    return bool(re.fullmatch(r"\d+", s.strip()))

def _find_netherworld_table(soup: BeautifulSoup):
    # Suche nach Überschrift "Netherworld", nimm die nächste Tabelle
    for tag in soup.find_all(["h3", "h4", "h5", "h6"]):
        if "netherworld" in tag.get_text(strip=True).lower():
            tbl = tag.find_next("table")
            if tbl:
                return tbl
    # Fallback: letzte Tabelle (rechte Spalte)
    tables = soup.find_all("table")
    if tables:
        return tables[-1]
    return None

# --------- Parsen: /ranking/
# Layout laut Seite:
# th | [td Online] | [td Name] | [td Level] | [td Job] | [td Exp%] | [td Guild]
def scrape_ranking_bequiet() -> dict[str, int]:
    html = fetch_html(RANKING_URL)
    soup = BeautifulSoup(html, "html.parser")
    table = _find_netherworld_table(soup)
    if not table:
        print("Ranking: Netherworld table not found", file=sys.stderr)
        return {}
    res: dict[str, int] = {}
    tbody = table.find("tbody")
    if not tbody:
        return res

    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue

        name = level_text = guild_text = ""

        # Hauptlayout mit Online-Spalte (6 tds)
        if len(tds) >= 6:
            name = tds[1].get_text(strip=True)
            level_text = tds[2].get_text(strip=True)
            guild_text = tds[5].get_text(" ", strip=True)
        # Eventueller Alt/Fallback ohne Online-Spalte (5 tds)
        elif len(tds) >= 5:
            name = tds[0].get_text(strip=True)
            level_text = tds[1].get_text(strip=True)
            guild_text = tds[4].get_text(" ", strip=True)
        else:
            # letzter Fallback: nimm die erste ganzzahlige Zelle als Level,
            # und setze Name/Guild heuristisch
            lvl_idx = next((i for i, td in enumerate(tds) if _digits_only(td.get_text(strip=True))), None)
            if lvl_idx is None:
                continue
            level_text = tds[lvl_idx].get_text(strip=True)
            # Name typischerweise links daneben
            if lvl_idx - 1 >= 0:
                name = tds[lvl_idx - 1].get_text(strip=True)
            # Gilde meist ganz rechts
            guild_text = tds[-1].get_text(" ", strip=True)

        if not name or not _digits_only(level_text):
            continue
        if not _is_bequiet(guild_text):
            continue

        res[name] = int(level_text)

    return res

# --------- Parsen: Startseite /
# Layout laut Seite:
# th | [td Name] | [td Level] | [td Job] | [td Guild]
def scrape_home_bequiet() -> dict[str, int]:
    html = fetch_html(HOME_URL)
    soup = BeautifulSoup(html, "html.parser")
    table = _find_netherworld_table(soup)
    if not table:
        print("Home: Netherworld table not found", file=sys.stderr)
        return {}
    res: dict[str, int] = {}
    tbody = table.find("tbody")
    if not tbody:
        return res

    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue

        name = level_text = guild_text = ""

        # erwartetes Layout (4 tds)
        if len(tds) >= 4:
            name = tds[0].get_text(strip=True)
            level_text = tds[1].get_text(strip=True)
            guild_text = tds[3].get_text(" ", strip=True)
        else:
            # Fallback: finde Level-Zelle
            lvl_idx = next((i for i, td in enumerate(tds) if _digits_only(td.get_text(strip=True))), None)
            if lvl_idx is None:
                continue
            level_text = tds[lvl_idx].get_text(strip=True)
            if lvl_idx - 1 >= 0:
                name = tds[lvl_idx - 1].get_text(strip=True)
            guild_text = tds[-1].get_text(" ", strip=True)

        if not name
