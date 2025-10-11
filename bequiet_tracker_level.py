import os, sys, json, time, re, random
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

# --------- Einstellungen ---------
GUILD_NAME   = "beQuiet"
RANKING_URL  = "https://pr-underworld.com/website/ranking/"
HOME_URL     = "https://pr-underworld.com/website/"
TIMEOUT      = 20

STATE_FILE   = Path("state.json")                 # speichert bekannte Level und Metadaten
MEMBERS_FILE = Path("bequiet_members.txt")        # eine Zeile pro Name
LEVELUP_TEXTS_FILE = Path("levelup_texts.txt")    # optionale Datei für Sprüche
WEBHOOK      = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
TZ           = ZoneInfo("Europe/Berlin")
FORCE_ANNOUNCE_FIRST_RUN = os.getenv("FORCE_ANNOUNCE_FIRST_RUN", "").strip().lower() in {"1", "true", "yes", "on"}

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

def _to_int_or_zero(x):
    try:
        if x is None:
            return 0
        if isinstance(x, bool):
            return int(x)
        if isinstance(x, (int,)):
            return int(x)
        s = str(x).strip()
        if re.fullmatch(r"\d+", s):
            return int(s)
    except Exception:
        pass
    return 0

def load_state():
    # Struktur
    state = {
        "levels": {},             # name -> int
        "baseline": {},           # name -> int  letzter Tages-Snapshot
        "last_post_date": "",     # "YYYY-MM-DD" Europe/Berlin
        "announced_members": {}   # name -> "YYYY-MM-DD"  verhindert Doppelposts
    }
    if STATE_FILE.exists():
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            # Hygiene: alles auf Integers trimmen, None entfernen
            for k in ("levels", "baseline"):
                d = {}
                for n, v in (raw.get(k) or {}).items():
                    n2 = str(n).strip()
                    if not n2:
                        continue
                    d[n2] = _to_int_or_zero(v)
                state[k] = d
            amd = {}
            for n, dt in (raw.get("announced_members") or {}).items():
                n2 = str(n).strip()
                if n2:
                    amd[n2] = str(dt).strip() or ""
            state["announced_members"] = amd
            state["last_post_date"] = str(raw.get("last_post_date") or "").strip()
        except Exception as e:
            print(f"State parse error: {e}", file=sys.stderr)
    return state

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
            lvl_i = _to_int_or_zero(lvl)
            if lvl_i <= 0:
                continue
            merged[n] = max(lvl_i, merged.get(n, 0))
    return merged

def diff_ups(baseline: dict[str, int], current: dict[str, int]):
    ups = []
    for name, new_lvl in current.items():
        old_lvl = _to_int_or_zero(baseline.get(name, 0))
        if new_lvl > old_lvl:
            ups.append((name, old_lvl, new_lvl))
    return ups

def main():
    state = load_state()
    known_levels: dict[str, int] = {n: _to_int_or_zero(v) for n, v in state.get("levels", {}).items()}
    baseline_levels: dict[str, int] = {n: _to_int_or_zero(v) for n, v in state.get("baseline", {}).items()}
    last_post_date: str = state.get("last_post_date", "") or ""
    announced_members: dict[str, str] = dict(state.get("announced_members", {}))

    # 1) Scrapen beider Quellen
    try:
        levels_ranking = scrape_ranking_bequiet()
    except Exception as e:
        print(f"Error scraping ranking: {e}", file=sys.stderr)
        levels_ranking = {}
    try:
        levels_home    = scrape_home_bequiet()
    except Exception as e:
        print(f"Error scraping home: {e}", file=sys.stderr)
        levels_home = {}

    current_levels = merge_levels(levels_ranking, levels_home)

    # 2) Mitgliederliste erweitern und Neuzugänge melden
    existing_members_list = load_members()
    existing_members = set(existing_members_list)
    existing_ci = {n.lower() for n in existing_members_list}

    found_now = set(current_levels.keys())
    # neu im Sinne der Datei
    file_new_members = sorted([n for n in found_now if n.lower() not in existing_ci], key=lambda s: s.lower())

    all_members = existing_members | found_now
    if all_members:
        save_members(all_members)

    # Nur Namen announcen, die noch nie angekündigt wurden
    today_local = datetime.now(TZ).date().isoformat()
    really_new_to_announce = [n for n in file_new_members if n not in announced_members]

    if really_new_to_announce:
        post_to_discord("🧭 Neue beQuiet Mitglieder aufgenommen " + ", ".join(really_new_to_announce))
        for n in really_new_to_announce:
            announced_members[n] = today_local
        print("New members announced " + ", ".join(really_new_to_announce))
    elif file_new_members:
        print("New members found but already announced earlier: " + ", ".join(file_new_members))

    # 3) Aktuellen Stand persistieren
    for name, lvl in current_levels.items():
        prev = _to_int_or_zero(known_levels.get(name, 0))
        if lvl > prev:
            known_levels[name] = lvl

    state["levels"] = known_levels
    state["announced_members"] = announced_members

    # 4) Tageslogik für Discord-Post einmal pro Tag nach Europa-Berlin-Datum
    if not baseline_levels:
        baseline_levels = dict(known_levels)
        state["baseline"] = baseline_levels
        state["last_post_date"] = "" if FORCE_ANNOUNCE_FIRST_RUN else today_local

    last_post_date = state.get("last_post_date", "") or ""
    should_post_today = last_post_date != today_local

    if should_post_today:
        ups_since_baseline = diff_ups(baseline_levels, known_levels)

        if ups_since_baseline:
            ups_since_baseline.sort(key=lambda x: (x[2] - x[1], x[2], x[0].lower()), reverse=True)
            spruch = pick_levelup_text()
            lines = [f"**beQuiet – Level-Ups** ({today_local})", f"_{spruch}_"]
            for name, old_lvl, new_lvl in ups_since_baseline:
                arrow = f"{old_lvl} → {new_lvl}" if old_lvl > 0 else f"neu erfasst: {new_lvl}"
                lines.append(f"• **{name}** — {arrow}")
            post_to_discord("\n".join(lines))
        else:
            print("No level-ups to post for today.")

        # Nach dem Tagespost Baseline und Datum aktualisieren
        state["baseline"] = dict(known_levels)
        state["last_post_date"] = today_local
    else:
        print("Daily post already sent today. Accumulating changes.")

    # 5) State speichern
    save_state(state)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
