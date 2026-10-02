import json
import math
import os
import statistics
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

API = "https://api.collegefootballdata.com"
YEAR = 2026
KEY = os.environ.get("CFBD_API_KEY")
if not KEY:
    raise SystemExit("CFBD_API_KEY GitHub secret is missing.")


def get(path, params):
    url = API + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def get_optional(path, params):
    try:
        result = get(path, params)
        return result if isinstance(result, list) else []
    except Exception as error:
        print(f"Optional endpoint unavailable: {path}: {error}")
        return []


def norm(name):
    return " ".join(str(name or "").lower().replace("&", "and").replace("'", "").split())


def first_number(item, keys):
    for key in keys:
        value = item.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def by_team(items, team_keys=("team", "school")):
    result = {}
    for item in items:
        name = next((item.get(key) for key in team_keys if item.get(key)), None)
        if name:
            result[norm(name)] = item
    return result


def z_scores(values, neutral=50.0):
    usable = [float(v) for v in values.values() if v is not None and math.isfinite(float(v))]
    if len(usable) < 2:
        return {key: neutral for key in values}
    mean = statistics.mean(usable)
    stdev = statistics.pstdev(usable)
    if stdev == 0:
        return {key: neutral for key in values}
    return {
        key: round(max(0.0, min(100.0, 50.0 + 15.0 * ((float(value) - mean) / stdev))), 3)
        if value is not None and math.isfinite(float(value)) else neutral
        for key, value in values.items()
    }



def standardized(values):
    """Return unclipped z-scores, using zero for missing or unavailable inputs."""
    usable = [float(v) for v in values.values() if v is not None and math.isfinite(float(v))]
    if len(usable) < 2:
        return {key: 0.0 for key in values}
    mean = statistics.mean(usable)
    stdev = statistics.pstdev(usable)
    if stdev == 0:
        return {key: 0.0 for key in values}
    return {
        key: ((float(value) - mean) / stdev)
        if value is not None and math.isfinite(float(value)) else 0.0
        for key, value in values.items()
    }


def solve_linear_system(matrix, vector):
    """Solve Ax=b using Gaussian elimination with partial pivoting."""
    n = len(vector)
    a = [list(map(float, matrix[i])) + [float(vector[i])] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(a[row][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("Power-rating system is singular.")
        a[col], a[pivot] = a[pivot], a[col]
        pivot_value = a[col][col]
        for j in range(col, n + 1):
            a[col][j] /= pivot_value
        for row in range(n):
            if row == col:
                continue
            factor = a[row][col]
            if factor == 0:
                continue
            for j in range(col, n + 1):
                a[row][j] -= factor * a[col][j]
    return [a[i][n] for i in range(n)]


def fit_power_ratings(team_names, completed_games, prior_points, prior_game_equivalents):
    """Fit neutral-field team ratings in points above/below the average FBS team."""
    index = {norm(team): i for i, team in enumerate(team_names)}
    n = len(team_names)
    matrix = [[0.0] * n for _ in range(n)]
    vector = [0.0] * n
    usable_games = 0
    home_field_advantage = 2.5
    for game in completed_games:
        home_key, away_key = norm(game.get("homeTeam")), norm(game.get("awayTeam"))
        if home_key not in index or away_key not in index:
            continue
        home_i, away_i = index[home_key], index[away_key]
        if home_i == away_i:
            continue
        margin = float(game["homePoints"]) - float(game["awayPoints"])
        if not game.get("neutralSite", False):
            margin -= home_field_advantage
        margin = max(-28.0, min(28.0, margin))
        matrix[home_i][home_i] += 1.0
        matrix[away_i][away_i] += 1.0
        matrix[home_i][away_i] -= 1.0
        matrix[away_i][home_i] -= 1.0
        vector[home_i] += margin
        vector[away_i] -= margin
        usable_games += 1

    for i, team in enumerate(team_names):
        strength = max(0.0, float(prior_game_equivalents))
        matrix[i][i] += strength + 0.05
        vector[i] += strength * float(prior_points.get(team, 0.0))

    ratings = solve_linear_system(matrix, vector)
    league_mean = statistics.mean(ratings) if ratings else 0.0
    ratings = [value - league_mean for value in ratings]
    return {team: round(ratings[i], 3) for i, team in enumerate(team_names)}, usable_games


records = get("/records", {"year": YEAR})
teams = [r for r in records if str(r.get("classification", "")).lower() == "fbs"]
team_names = [r["team"] for r in teams]
team_name_lookup = {norm(name): name for name in team_names}

# Keep logo entries restricted to the teams displayed in the rankings.
team_details = get_optional("/teams", {"year": YEAR})
fbs_names = set(team_names)
logo_map = {}
for team in team_details:
    name = team.get("school") or team.get("team")
    logos = team.get("logos") or []
    if name in fbs_names and logos:
        logo_map[name] = logos[0]

# Pull completed FBS games. Each game is used once for records, schedule,
# scoring margin and recent form.
games = []
for week in range(1, 17):
    games.extend(get_optional("/games", {"year": YEAR, "week": week, "seasonType": "regular", "classification": "fbs"}))
games = [
    game for game in games
    if game.get("homePoints") is not None and game.get("awayPoints") is not None
    and game.get("homeTeam") and game.get("awayTeam")
]
season_week = max(1, max((int(game.get("week") or 0) for game in games), default=1))

stats = defaultdict(lambda: {"games": 0, "wins": 0, "losses": 0, "pf": 0, "pa": 0})
opponents = defaultdict(list)
game_margins = defaultdict(list)
for game in games:
    home, away = game["homeTeam"], game["awayTeam"]
    hp, ap = float(game["homePoints"]), float(game["awayPoints"])
    week = int(game.get("week") or 0)
    stats[home]["games"] += 1
    stats[away]["games"] += 1
    stats[home]["pf"] += hp
    stats[home]["pa"] += ap
    stats[away]["pf"] += ap
    stats[away]["pa"] += hp
    opponents[home].append(away)
    opponents[away].append(home)
    game_margins[home].append((week, hp - ap, away))
    game_margins[away].append((week, ap - hp, home))
    if hp > ap:
        stats[home]["wins"] += 1
        stats[away]["losses"] += 1
    elif ap > hp:
        stats[away]["wins"] += 1
        stats[home]["losses"] += 1

# Supplemental model inputs. Missing endpoints degrade gracefully to neutral
# component values rather than breaking the scheduled rankings build.
talent_data = get_optional("/talent", {"year": YEAR})
if not talent_data:
    talent_data = get_optional("/recruiting/teams", {"year": YEAR})
returning_data = get_optional("/player/returning", {"year": YEAR})
ppa_data = get_optional("/ppa/teams", {"year": YEAR})
fpi_data = get_optional("/ratings/fpi", {"year": YEAR})

talent_by_team = by_team(talent_data)
returning_by_team = by_team(returning_data)
ppa_by_team = by_team(ppa_data)
fpi_by_team = by_team(fpi_data)

# Map CFBD's field variations into stable model inputs.
talent_raw, returning_raw, performance_raw, schedule_raw, recent_raw = {}, {}, {}, {}, {}
base = {}
for team in team_names:
    key = norm(team)
    s = stats[team]
    played = s["games"]
    win_pct = s["wins"] / played if played else 0.5
    margin_per_game = (s["pf"] - s["pa"]) / played if played else 0.0
    base[team] = {"gamesPlayed": played, "wins": s["wins"], "losses": s["losses"],
                  "pointsFor": int(s["pf"]), "pointsAgainst": int(s["pa"]),
                  "winPct": round(win_pct, 4), "scoringMarginPerGame": round(margin_per_game, 3)}

    t = talent_by_team.get(key, {})
    talent_raw[team] = first_number(t, ["talent", "talentComposite", "rating", "points"])
    ret = returning_by_team.get(key, {})
    returning_raw[team] = first_number(ret, ["total", "percent", "percentReturning", "returningProduction"])
    ppa = ppa_by_team.get(key, {})
    ppa_overall = first_number(ppa, ["overall", "ppa", "total"])
    offense = first_number(ppa, ["offense", "offensePPA"])
    defense = first_number(ppa, ["defense", "defensePPA"])
    # Prefer overall PPA; otherwise use scoring margin and win rate.
    performance_raw[team] = (0.55 * ppa_overall + 0.25 * margin_per_game + 20 * win_pct) if ppa_overall is not None else (margin_per_game + 20 * win_pct)
    if offense is not None and defense is not None and ppa_overall is None:
        performance_raw[team] = offense - defense

    opp_win_pcts = []
    for opponent in opponents[team]:
        opponent_stats = stats[opponent]
        opponent_games = opponent_stats["games"]
        if opponent_games:
            opp_win_pcts.append(opponent_stats["wins"] / opponent_games)
    schedule_raw[team] = statistics.mean(opp_win_pcts) if opp_win_pcts else None

    ordered = sorted(game_margins[team], key=lambda item: item[0])
    recent_games = ordered[-4:]
    if recent_games:
        # Latest game receives the largest weight; margin is capped to reduce
        # blowout distortion. Opponent record adjusts the margin modestly.
        weighted_total = weight_total = 0.0
        for index, (_, margin, opponent) in enumerate(recent_games, start=1):
            opponent_stats = stats[opponent]
            opponent_gp = opponent_stats["games"]
            opponent_strength = (opponent_stats["wins"] / opponent_gp - 0.5) if opponent_gp else 0.0
            weight = float(index)
            adjusted_margin = max(-28.0, min(28.0, margin)) + 10.0 * opponent_strength
            weighted_total += weight * adjusted_margin
            weight_total += weight
        recent_raw[team] = weighted_total / weight_total
    else:
        recent_raw[team] = None

# Convert roster inputs into a modest preseason prior measured in points.
# The prior fades to zero by week 14, so game results increasingly drive ratings.
talent_z = standardized(talent_raw)
returning_z = standardized(returning_raw)
prior_raw = {
    team: (0.75 * talent_z[team] + 0.25 * returning_z[team])
    if returning_raw[team] is not None else talent_z[team]
    for team in team_names
}
prior_z = standardized(prior_raw)
prior_points = {team: max(-18.0, min(18.0, 6.0 * prior_z[team])) for team in team_names}
prior_game_equivalents = max(0.0, 4.0 * (14.0 - min(season_week, 14)) / 13.0)
if not any(value is not None for value in talent_raw.values()):
    prior_game_equivalents = 0.0

ratings, fbs_games_used = fit_power_ratings(
    team_names, games, prior_points, prior_game_equivalents
)

rows = []
for team_record in teams:
    team = team_record["team"]
    key = norm(team)
    s = base[team]
    fpi = first_number(fpi_by_team.get(key, {}), ["fpi"])
    rows.append({
        "team": team,
        "conference": team_record.get("conference"),
        **s,
        "rating": ratings[team],
        "priorRating": round(prior_points[team], 3),
        "fpiRating": round(fpi, 3) if fpi is not None else None,
    })

rows.sort(key=lambda row: (-row["rating"], -row["wins"], row["losses"], row["team"]))
for rank, row in enumerate(rows, start=1):
    row["rank"] = rank

fpi_rows = sorted(
    [row for row in rows if row["fpiRating"] is not None],
    key=lambda row: (-row["fpiRating"], row["team"])
)
fpi_rank = {row["team"]: rank for rank, row in enumerate(fpi_rows, start=1)}
for row in rows:
    row["fpiRank"] = fpi_rank.get(row["team"])
    row["rankDifferenceVsFPI"] = (row["fpiRank"] - row["rank"]) if row["fpiRank"] is not None else None

# Rank correlation is calculated only when at least two teams have FPI values.
matched = [row for row in rows if row["fpiRank"] is not None]
if len(matched) >= 2:
    n = len(matched)
    d2 = sum((row["rank"] - row["fpiRank"]) ** 2 for row in matched)
    spearman = 1 - (6 * d2) / (n * (n * n - 1))
    mean_abs_rank_diff = statistics.mean(abs(row["rank"] - row["fpiRank"]) for row in matched)
    fpi_comparison = {
        "matchedTeams": n,
        "spearmanRankCorrelation": round(spearman, 4),
        "meanAbsoluteRankDifference": round(mean_abs_rank_diff, 2),
        "note": "Comparison is against CFBD's FPI endpoint for the same season; ties and missing teams may affect interpretation."
    }
else:
    fpi_comparison = {
        "matchedTeams": len(matched),
        "spearmanRankCorrelation": None,
        "meanAbsoluteRankDifference": None,
        "note": "FPI data is not currently available for enough teams to calculate a meaningful comparison."
    }

output = {
    "season": YEAR,
    "seasonWeek": season_week,
    "teamCount": len(rows),
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "dataProvider": "CollegeFootballData.com",
    "model": {
        "name": "AP Poll Sucks Opponent-Adjusted Point Model",
        "version": 3,
        "ratingUnit": "points",
        "ratingMeaning": "Expected scoring margin versus an average FBS team on a neutral field",
        "homeFieldAdvantage": 2.5,
        "marginCap": 28,
        "fbsGamesUsed": fbs_games_used,
        "preseasonPriorGameEquivalents": round(prior_game_equivalents, 3),
        "notes": [
            "Ratings are point estimates relative to an average FBS team; the difference between two ratings is the projected neutral-field margin.",
            "Each completed game contributes an opponent-adjusted scoring-margin equation, so schedule strength is accounted for through the full network of opponents rather than a separate win-percentage bonus.",
            "Home-field advantage of 2.5 points is removed from non-neutral games before fitting the model.",
            "Game margins are capped at plus or minus 28 points to limit the influence of extreme blowouts.",
            "Roster talent is used only as a modest preseason prior, worth at most 18 points per standard deviation and fading to zero by week 14.",
            "CFBD FPI is used only for comparison and never enters the rating calculation.",
            "A small regularization term keeps ratings stable for teams with few or no completed FBS games."
        ]
    },
    "fpiComparison": fpi_comparison,
    "rankings": rows
}

os.makedirs("data", exist_ok=True)
with open("data/rankings.json", "w", encoding="utf-8") as file:
    json.dump(output, file, indent=2)

with open("data/team_logos.json", "w", encoding="utf-8") as file:
    json.dump(logo_map, file, indent=2)

print(f"Generated {len(rows)} FBS rankings, {len(logo_map)} team logos, and matched {len(matched)} teams to FPI.")
