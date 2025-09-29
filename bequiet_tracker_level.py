import os, json, time, sys, re, random
from pathlib import Path
import requests
from bs4 import BeautifulSoup

URL = "https://pr-underworld.com/website/ranking/"
GUILD_NAME = "beQuiet"
STATE_FILE = Path("state.json")
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

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"levels": {}, "last_run_ts": 0}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def post_to_discord(player, level):
    if not WEBHOOK:
        print("Webhook fehlt. Setze Secret DISCORD_WEBHOOK_URL", file=sys.stderr)
        return
    msg = random.choice(LEVEL_MESSAGES)
    payload = {"content": f"Gratulations {player}. You reached level {level}.\n{msg}"}
    r = requests.post(WEBHOOK, json=payload, timeout=10)
    r.raise_for_status()

def find_netherworld_table(soup):
    for h in soup.find_all(["h1","h2","h3","h4","h5","h6"]):
        if h.get_text(strip=True).lower().startswith("netherworld"):
            return h.find_next("table")
    return None

def extract_rows(table):
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

def main():
    state = load_state()
    r = requests.get(URL, timeout=TIMEOUT, headers={"User-Agent": "beQuiet level tracker"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    table = find_netherworld_table(soup)
    if not table:
        print("Netherworld Tabelle nicht gefunden", file=sys.stderr)
        return

    current = {}
    for row in extract_rows(table):
        if GUILD_NAME.lower() not in row["guild"].lower():
            continue
        name = row["name"]
        level = row["level"]
        current[name] = level

        prev = state["levels"].get(name)
        force_first = os.getenv("FORCE_ANNOUNCE_FIRST_RUN", "").lower() == "true"

        if prev is None:
            if force_first:
                post_to_discord(name, level)
            state["levels"][name] = level
            continue

        if level > prev:
            post_to_discord(name, level)
            state["levels"][name] = level

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
