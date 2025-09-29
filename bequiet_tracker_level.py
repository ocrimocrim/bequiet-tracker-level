import os
import json
import time
import sys
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# --- Einstellungen ---
URL = "https://pr-underworld.com/website/ranking/"
GUILD_NAME = "beQuiet"                   # nur diese Gilde beobachten
STATE_FILE = Path("state.json")          # Datei, in der wir die letzten Level speichern
TIMEOUT = 20
WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

# Schalter:
FORCE_FIRST = os.getenv("FORCE_ANNOUNCE_FIRST_RUN", "").lower() == "true"
SEND_TEST_MESSAGE = os.getenv("SEND_TEST_MESSAGE", "").lower() == "true"


# ---------- Hilfsfunktionen ----------
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"levels": {}, "last_run_ts": 0}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def post_text(content: str):
    """Beliebigen Text via Webhook posten."""
    if not WEBHOOK:
        print("Webhook fehlt. Setze Secret DISCORD_WEBHOOK_URL", file=sys.stderr)
        return
    r = requests.post(WEBHOOK, json={"content": content}, timeout=10)
    r.raise_for_status()


def post_level_up(player: str, level: int):
    post_text(f"Gratulations {player}. You reached level {level}")


def find_netherworld_table(soup: BeautifulSoup):
    """
    Sucht die Tabelle direkt UNTERHALB der Überschrift 'Netherworld'
    (Underworld wird ignoriert – so wie du es wolltest).
    """
    for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if h.get_text(strip=True).lower().startswith("netherworld"):
            return h.find_next("table")
    return None


def extract_rows(table) -> list[dict]:
    """
    Extrahiert Zeilen aus der Ranking-Tabelle.
    Erwartete Struktur pro Zeile (Beispiel aus deiner Beschreibung):
      <td> Name </td>
      <td> 180 </td>
      ...
      <td> ... beQuiet</td>
    Wir lesen: name (td[2]), level (td[3]), guild (td[6]).
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


# ---------- Hauptlogik ----------
def main():
    state = load_state()

    # Optional: reine Testmeldung – unabhängig von Spielern
    if SEND_TEST_MESSAGE:
        post_text("✅ Testlauf erfolgreich: Das Tracker-Script läuft und kann in diesen Kanal posten.")

    # Seite abrufen
    r = requests.get(URL, timeout=TIMEOUT, headers={"User-Agent": "beQuiet level tracker"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Nur NETherworld-Tabelle beachten
    table = find_netherworld_table(soup)
    if not table:
        print("Netherworld Tabelle nicht gefunden", file=sys.stderr)
        return

    current: dict[str, int] = {}

    # Zeilen verarbeiten
    for row in extract_rows(table):
        # nur unsere Gilde
        if GUILD_NAME.lower() not in row["guild"].lower():
            continue

        name = row["name"]
        level = row["level"]
        current[name] = level

        prev = state["levels"].get(name)

        # erster bekannter Stand? => speichern (und optional announcen)
        if prev is None:
            if FORCE_FIRST:
                post_level_up(name, level)  # nur einmalig beim ersten Lauf, wenn gewünscht
            state["levels"][name] = level
            continue

        # Level-Up?
        if level > prev:
            post_level_up(name, level)
            state["levels"][name] = level

    # Spieler, die nicht mehr in der aktuellen Tabelle sind, aus dem State entfernen
    for missing in list(state["levels"].keys()):
        if missing not in current:
            del state["levels"][missing]

    state["last_run_ts"] = int(time.time())
    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Fehler: {e}", file=sys.stderr)
        sys.exit(1)
