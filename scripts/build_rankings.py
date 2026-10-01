import json
import os
import urllib.parse
import urllib.request
from collections import defaultdict

API = "https://api.collegefootballdata.com"
YEAR = 2026
KEY = os.environ.get("CFBD_API_KEY")
if not KEY:
    raise SystemExit("CFBD_API_KEY GitHub secret is missing.")

def get(path, params):
    url = API + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

records = get("/records", {"year": YEAR})
teams = [r for r in records if str(r.get("classification", "")).lower() == "fbs"]

# Keep team logos local to the site. CFBD returns current team logo URLs,
# and GitHub Pages serves the generated map without a browser-side API call.
team_details = get("/teams", {"year": YEAR})
fbs_names = {r["team"] for r in teams}
logo_map = {}
for team in team_details:
    name = team.get("school") or team.get("team")
    logos = team.get("logos") or []
    if name in fbs_names and logos:
        logo_map[name] = logos[0]

games = []
for week in range(1, 17):
    try:
        games.extend(get("/games", {"year": YEAR, "week": week, "classification": "fbs"}))
    except Exception:
        pass

games = [g for g in games if g.get("homePoints") is not None and g.get("awayPoints") is not None]

stats = defaultdict(lambda: {"games": 0, "wins": 0, "losses": 0, "pf": 0, "pa": 0})
opponents = defaultdict(list)

for g in games:
    home, away = g.get("homeTeam"), g.get("awayTeam")
    hp, ap = g.get("homePoints"), g.get("awayPoints")
    if not home or not away or hp is None or ap is None:
        continue
    stats[home]["games"] += 1; stats[away]["games"] += 1
    stats[home]["pf"] += hp; stats[home]["pa"] += ap
    stats[away]["pf"] += ap; stats[away]["pa"] += hp
    opponents[home].append(away); opponents[away].append(home)
    if hp > ap:
        stats[home]["wins"] += 1; stats[away]["losses"] += 1
    elif ap > hp:
        stats[away]["wins"] += 1; stats[home]["losses"] += 1

rows = []
for r in teams:
    name = r["team"]
    s = stats[name]
    gp = max(s["games"], 1)
    win_pct = s["wins"] / gp
    margin = (s["pf"] - s["pa"]) / gp
    score = 70 + (win_pct * 25) + max(-10, min(10, margin / 4))
    rows.append({
        "team": name,
        "conference": r.get("conference"),
        "wins": s["wins"],
        "losses": s["losses"],
        "rating": round(score, 3),
        "gamesPlayed": s["games"],
        "pointsFor": s["pf"],
        "pointsAgainst": s["pa"]
    })

rows.sort(key=lambda x: (-x["rating"], -x["wins"], x["losses"], x["team"]))
for i, row in enumerate(rows, 1):
    row["rank"] = i

output = {
    "season": YEAR,
    "teamCount": len(rows),
    "generatedAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    "dataProvider": "CollegeFootballData.com",
    "rankings": rows
}

os.makedirs("data", exist_ok=True)
with open("data/rankings.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2)

with open("data/team_logos.json", "w", encoding="utf-8") as f:
    json.dump(logo_map, f, indent=2)

print(f"Generated {len(rows)} FBS rankings and {len(logo_map)} team logos.")
