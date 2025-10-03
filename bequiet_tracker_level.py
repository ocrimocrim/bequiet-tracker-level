import os, sys, json, time, re, random
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
LEVELUP_TEXTS_FILE = Path("levelup_texts.txt")    # neue Datei für Sprüche
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

# --------- Levelup Sprüche ---------
def pick_levelup_text() -> str:
    if LEVELUP_TEXTS_FILE.exists():
        lines = [ln.strip() for ln in LEVELUP_TEXTS_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if lines:
            return random.choice(lines)
    # Fallback falls Datei fehlt oder leer
    return "hat ein neues Level erreicht!"

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
    # Fallback: letzte Tabelle
    tables = soup.find_all("table")
    if tables:
        return tables[-1]
    return None

# --------- Parsen: /ranking/
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

        # Hauptlayout mit Online-Spalte
        if len(tds) >= 6:
            name = tds[1].get_text(strip=True)
            level_text = tds[2].get_text(strip=True)
            guild_text = tds[5].get_text(" ", strip=True)
        elif len(tds) >= 5:
            name = tds[0].get_text(strip=True)
            level_text = tds[1].get_text(strip=True)
            guild_text = tds[4].get_text(" ", strip=True)
        else:
            lvl_idx = next((i for i, td in enumerate(tds) if _digits_only(td.get_text(strip=True))), None)
            if lvl_idx is None:
                continue
            level_text = tds[lvl_idx].get_text(strip=True)
            if lvl_idx - 1 >= 0:
                name = tds[lvl_idx - 1].get_text(strip=True)
            guild_text = tds[-1].get_text(" ", strip=True)

        if not name or not _digits_only(level_text):
            continue
        if not _is_bequiet(guild_text):
            continue

        res[name] = int(level_text)

    return res

# --------- Parsen: Startseite /
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

        if len(tds) >= 4:
            name = tds[0].get_text(strip=True)
            level_text = tds[1].get_text(strip=True)
            guild_text = tds[3].get_text(" ", strip=True)
        else:
            lvl_idx = next((i for i, td in enumerate(tds) if _digits_only(td.get_text(strip=True))), None)
            if lvl_idx is None:
                continue
            level_text = tds[lvl_idx].get_text(strip=True)
            if lvl_idx - 1 >= 0:
                name = tds[lvl_idx - 1].get_text(strip=True)
            guild_text = tds[-1].get_text(" ", strip=True)

        if not name or not _digits_only(level_text):
            continue
        if not _is_bequiet(guild_text):
            continue

        res[name] = int(level_text)

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

    # 2) Mitgliederliste erweitern und Neuzugänge melden
    existing_members_list = load_members()
    existing_members = set(existing_members_list)
    existing_ci = {n.lower() for n in existing_members_list}

    found_now = set(current_levels.keys())
    new_members = sorted([n for n in found_now if n.lower() not in existing_ci], key=lambda s: s.lower())

    all_members = existing_members | found_now
    if all_members:
        save_members(all_members)

    if new_members:
        post_to_discord("🧭 Neue beQuiet Mitglieder aufgenommen " + ", ".join(new_members))
        print("New members detected " + ", ".join(new_members))

    # 3) Level-Ups ermitteln
    ups = []
    for name, new_lvl in current_levels.items():
        old_raw = known_levels.get(name, 0)
        try:
            old_lvl = int(old_raw or 0)
        except Exception:
            old_lvl = 0
        if new_lvl > old_lvl:
            ups.append((name, old_lvl, new_lvl))
            known_levels[name] = new_lvl

    # 4) State speichern
    state["levels"] = known_levels
    save_state(state)

    # 5) Discord-Post bei Level-Ups
    if ups:
        ups.sort(key=lambda x: (x[2] - x[1], x[2], x[0].lower()), reverse=True)
        today = time.strftime("%Y-%m-%d")
        spruch = pick_levelup_text()
        lines = [f"**beQuiet – Level-Ups** ({today})", f"_{spruch}_"]
        for name, old_lvl, new_lvl in ups:
            arrow = f"{old_lvl} → {new_lvl}" if old_lvl > 0 else f"neu erfasst: {new_lvl}"
            lines.append(f"• **{name}** — {arrow}")
        post_to_discord("\n".join(lines))
    else:
        print("No level-ups today.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
