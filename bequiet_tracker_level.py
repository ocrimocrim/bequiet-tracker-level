#!/usr/bin/env python3
import os, json, time, sys, re, random
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# ---------- Konfiguration ----------
URL = "https://pr-underworld.com/website/ranking/"   # Level-Ranking-Seite (zeigt Top 100)
GUILD_NAME = "beQuiet"

STATE_FILE   = Path("state.json")
MEMBERS_FILE = Path("bequiet_members.txt")
TIMEOUT = 20
WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

LEVEL_MESSAGES = [
    "Gz on leveling up, bro! Even the panther in Horizon tavern is buying drinks tonight!",
    "Big gz! From Laksy harbor to Katan rooftops, every Blue Pixie is dancing for your ding!",
    "Congrats, mate! Even Cube dungeon mobs stopped KS’ing for a sec to clap for your level up.",
    "Sweet ding! The Yeti in Crystal Valley whispered me: 'that guy deserves +10 cards now'.",
    "Gz, hero! The White Dragon in Lost Mines just ragequit because you outleveled his ego.",
    "Level up hype! Even Admin InkDevil paused banning cheaters on the private server war to salute you.",
    "Massive gz! Horizon guards told me your level up just became the new main quest.",
    "Yo, gz! The Tortus and the Wolf from your pet bag started a moshpit in front of Laksy fountain.",
    "Congrats! Even the boss in Temple of the Ancients is begging to be in your party now.",
    "Gz for the ding! The Rondo marketplace doubled the price of Soul Stones after hearing your name.",
    "Поздравляю с апом, брат! Даже скелеты из Temple of Lost Souls начали спорить, кто будет тебе носить сумку, а пантера из Хорайзона уже заказала водку на весь сервер!"
]

# ---------- Helpers: State ----------
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"levels": {}, "last_run_ts": 0}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------- Helpers: Mitgliederliste ----------
def load_members() -> list[str]:
    if not MEMBERS_FILE.exists():
        return []
    names = [line.strip() for line in MEMBERS_FILE.read_text(encoding="utf-8").splitlines()]
    names = [n for n in names if n]
    # Duplikate entfernen, Reihenfolge stabil halten
    seen, uniq = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq

def save_members(names: list[str]) -> None:
    uniq_sorted = sorted(set(n.strip() for n in names if n.strip()), key=str.lower)
    MEMBERS_FILE.write_text("\n".join(uniq_sorted) + ("\n" if uniq_sorted else ""), encoding="utf-8")

# ---------- Discord ----------
def post_to_discord(player, level):
    if not WEBHOOK:
        print("Webhook fehlt. Setze Secret DISCORD_WEBHOOK_URL", file=sys.stderr)
        return
    msg = random.choice(LEVEL_MESSAGES)
    payload = {"content": f"Gratulations {player}. You reached level {level}.\n{msg}"}
    r = requests.post(WEBHOOK, json=payload, timeout=10)
    r.raise_for_status()

# ---------- Parsing ----------
def find_netherworld_table(soup):
    # Überschrift "Netherworld" -> nächste Tabelle
    for h in soup.find_all(["h1","h2","h3","h4","h5","h6"]):
        if h.get_text(strip=True).lower().startswith("netherworld"):
            return h.find_next("table")
    return None

def extract_rows(table):
    """
    Ranking-Spalten (Netherworld):
      # | Online | Name | Level | Job | Exp % | Guild
    -> Name = tds[2], Level = tds[3], Guild = tds[6]
    """
    rows = []
    tbody = table.find("tbody")
    if not tbody:
        return rows
    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue
        name = tds[2].get_text(strip=True)
        level_txt = tds[3].get_text(strip=True)
        guild_txt = tds[6].get_text(" ", strip=True)
        try:
            level = int(re.sub(r"[^\d]", "", level_txt))
        except ValueError:
            continue
        rows.append({"name": name, "level": level, "guild": guild_txt})
    return rows

# ---------- Main ----------
def main():
    state = load_state()
    members = load_members()
    member_set = set(members)

    r = requests.get(URL, timeout=TIMEOUT, headers={"User-Agent": "beQuiet level tracker"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    table = find_netherworld_table(soup)
    if not table:
        print("Netherworld Tabelle nicht gefunden", file=sys.stderr)
        return

    # Alle beQuiet-Spieler auf der Ranking-Seite (Top 100) auslesen
    current_seen = {}
    newly_found_for_list = []
    for row in extract_rows(table):
        if GUILD_NAME.lower() not in row["guild"].lower():
            continue
        name = row["name"]
        level = row["level"]
        current_seen[name] = level
        # Falls nicht in Liste -> zur Liste ergänzen
        if name not in member_set:
            member_set.add(name)
            newly_found_for_list.append(name)

        # Level-Änderungen prüfen
        prev = state["levels"].get(name)
        force_first = os.getenv("FORCE_ANNOUNCE_FIRST_RUN", "").lower() == "true"
        if prev is None:
            if force_first:
                post_to_discord(name, level)
            state["levels"][name] = level
        elif level > prev:
            post_to_discord(name, level)
            state["levels"][name] = level

    # Wichtig: NICHT mehr alles löschen, was heute nicht im Ranking war.
    # Die Top-100 filtert; Mitglieder außerhalb der Top-100 sollen im State bleiben.
    # Optional: wer gar kein beQuiet mehr ist, könntest du künftig via members.txt steuern.

    # Alle Namen aus der Mitgliederliste sicher im State anlegen
    for n in member_set:
        state["levels"].setdefault(n, None)

    # Neue Mitglieder-Namen ins File schreiben (sortiert, dedupliziert)
    if newly_found_for_list or (set(members) != member_set):
        save_members(list(member_set))
        if newly_found_for_list:
            print("Zur Mitgliederliste hinzugefügt: " + ", ".join(sorted(newly_found_for_list, key=str.lower)))

    state["last_run_ts"] = int(time.time())
    save_state(state)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Fehler: {e}", file=sys.stderr)
        sys.exit(1)
