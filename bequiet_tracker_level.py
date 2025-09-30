import os, sys, json, time
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# --------- Einstellungen ---------
GUILD_NAME   = "beQuiet"
RANKING_URL  = "https://pr-underworld.com/website/ranking/"
HOME_URL     = "https://pr-underworld.com/website/"
TIMEOUT      = 20

STATE_FILE   = Path("state_levels.json")       # speichert bekannte Level
MEMBERS_FILE = Path("bequiet_members.txt")     # feste Mitgliedsliste (eine Zeile pro Name)

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
    # stabil sortieren, Groß/Kleinschreibung erhalten, Duplicates case-insensiv filtern
    seen_ci = set()
    out = []
    for n in sorted(names, key=lambda s: s.lower()):
        key = n.lower()
        if key in seen_ci:  # Duplikate vermeiden
            continue
        seen_ci.add(key)
        out.append(n)
    MEMBERS_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")

# --------- Parsen: gemeinsame Utilities ---------
def _is_bequiet(text: str) -> bool:
    return GUILD_NAME.lower() in text.lower()

def _find_netherworld_table(soup: BeautifulSoup):
    # Suche nach einer Überschrift mit "Netherworld" und nimm die nächste Tabelle
    for tag in soup.find_all(["h3", "h4", "h5", "h6"]):
        if "netherworld" in tag.get_text(strip=True).lower():
            tbl = tag.find_next("table")
            if tbl:
                return tbl
    # Fallback: letzte Tabelle nehmen
    tables = soup.find_all("table")
    if tables:
        return tables[-1]
    return None

# --------- Parsen: /ranking/ (Spalten: Name | Level | Job | Exp% | Guild) ---------
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
        if len(tds) < 5:
            continue
        name  = tds[0].get_text(strip=True)
        level = tds[1].get_text(strip=True)
        guild = tds[4].get_text(" ", strip=True)
        if not name:
            continue
        try:
            lvl = int(level)
        except Exception:
            continue
        if _is_bequiet(guild):
            res[name] = lvl
    return res

# --------- Parsen: / (Spalten: Online | Name | Level | Job | Exp% | Guild) ---------
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
        if len(tds) < 6:
            continue
        name  = tds[1].get_text(strip=True)
        level = tds[2].get_text(strip=True)
        guild = tds[5].get_text(" ", strip=True)
        if not name:
            continue
        try:
            lvl = int(level)
        except Exception:
            continue
        if _is_bequiet(guild):
            res[name] = lvl
    return res

# --------- Merge & Posting ---------
def merge_levels(*sources: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for src in sources:
        for n, lvl in src.items():
            merged[n] = max(lvl, merged.get(n, 0))
    return merged

def main():
    state = load_state()
    known_levels: dict[str, int] = state.get("levels", {})

    # 1) Scrapen beider Quellen
    levels_ranking = scrape_ranking_bequiet()
    levels_home    = scrape_home_bequiet()
    current_levels = merge_levels(levels_ranking, levels_home)

    # 2) Mitgliederliste laden/erweitern
    members = set(load_members())
    members |= set(current_levels.keys())
    if members:
        save_members(members)

    # 3) Level-Ups ermitteln
    ups = []
    for name, new_lvl in current_levels.items():
        old_lvl = int(known_levels.get(name, 0) or 0)
        if new_lvl > old_lvl:
            ups.append((name, old_lvl, new_lvl))
            known_levels[name] = new_lvl

    # 4) State speichern
    state["levels"] = known_levels
    save_state(state)

    # 5) Discord-Post nur bei Level-Ups
    if ups:
        ups.sort(key=lambda x: (x[2] - x[1], x[2], x[0].lower()), reverse=True)
        today = time.strftime("%Y-%m-%d")
        lines = [f"**beQuiet – Level-Ups** ({today})"]
        for name, old_lvl, new_lvl in ups:
            arrow = f"{old_lvl} → {new_lvl}" if old_lvl > 0 else f"neu erfasst: {new_lvl}"
            lines.append(f"• **{name}** — {arrow}")
        content = "\n".join(lines)
        post_to_discord(content)
    else:
        print("No level-ups today.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
