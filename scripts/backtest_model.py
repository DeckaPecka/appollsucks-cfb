"""Walk-forward backtest for the opponent-adjusted point model.

For each historical regular-season week, fit ratings using only earlier games,
then predict the completed games in that week. No target-week scores are used
when producing that week's predictions.
"""
import json
import math
import os
import statistics
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://api.collegefootballdata.com"
FIRST_SEASON = 2015
LAST_SEASON = 2025
HOME_FIELD_ADVANTAGE = 2.5
MARGIN_CAP = 28.0


def norm(name):
    return " ".join(str(name or "").lower().replace("&", "and").replace("'", "").split())


def get(path, params):
    key = os.environ.get("CFBD_API_KEY")
    if not key:
        raise SystemExit("CFBD_API_KEY GitHub secret is missing.")
    url = API + path + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def get_optional(path, params):
    try:
        result = get(path, params)
        return result if isinstance(result, list) else []
    except Exception as error:
        print(f"Optional backtest input unavailable: {path}: {error}")
        return []


def first_number(item, keys):
    for key in keys:
        value = item.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def by_team(items):
    result = {}
    for item in items:
        name = item.get("team") or item.get("school")
        if name:
            result[norm(name)] = item
    return result


def standardized(values):
    usable = [float(v) for v in values.values() if v is not None and math.isfinite(float(v))]
    if len(usable) < 2:
        return {key: 0.0 for key in values}
    mean = statistics.mean(usable)
    stdev = statistics.pstdev(usable)
    if stdev == 0:
        return {key: 0.0 for key in values}
    return {
        key: (float(value) - mean) / stdev
        if value is not None and math.isfinite(float(value)) else 0.0
        for key, value in values.items()
    }


def solve_linear_system(matrix, vector):
    n = len(vector)
    a = [list(map(float, matrix[i])) + [float(vector[i])] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(a[row][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("Backtest rating system is singular.")
        a[col], a[pivot] = a[pivot], a[col]
        divisor = a[col][col]
        for j in range(col, n + 1):
            a[col][j] /= divisor
        for row in range(n):
            if row == col:
                continue
            factor = a[row][col]
            if factor:
                for j in range(col, n + 1):
                    a[row][j] -= factor * a[col][j]
    return [a[i][n] for i in range(n)]


def fit_ratings(team_names, training_games, prior_points, prior_equivalents):
    indexes = {norm(team): i for i, team in enumerate(team_names)}
    n = len(team_names)
    matrix = [[0.0] * n for _ in range(n)]
    vector = [0.0] * n
    for game in training_games:
        home_key, away_key = norm(game.get("homeTeam")), norm(game.get("awayTeam"))
        if home_key not in indexes or away_key not in indexes:
            continue
        home_i, away_i = indexes[home_key], indexes[away_key]
        if home_i == away_i:
            continue
        margin = float(game["homePoints"]) - float(game["awayPoints"])
        if not game.get("neutralSite", False):
            margin -= HOME_FIELD_ADVANTAGE
        margin = max(-MARGIN_CAP, min(MARGIN_CAP, margin))
        matrix[home_i][home_i] += 1.0
        matrix[away_i][away_i] += 1.0
        matrix[home_i][away_i] -= 1.0
        matrix[away_i][home_i] -= 1.0
        vector[home_i] += margin
        vector[away_i] -= margin

    for i, team in enumerate(team_names):
        strength = max(0.0, float(prior_equivalents))
        matrix[i][i] += strength + 0.05
        vector[i] += strength * float(prior_points.get(team, 0.0))

    ratings = solve_linear_system(matrix, vector)
    average = statistics.mean(ratings) if ratings else 0.0
    return {team: ratings[i] - average for i, team in enumerate(team_names)}


def metrics(predictions):
    if not predictions:
        return {"games": 0, "mae": None, "rmse": None, "winnerAccuracy": None, "baselineMae": None, "baselineRmse": None}
    errors = [p["predicted"] - p["actual"] for p in predictions]
    baseline_errors = [p["baseline"] - p["actual"] for p in predictions]
    correct = sum(
        1 for p in predictions
        if (p["predicted"] > 0 and p["actual"] > 0)
        or (p["predicted"] < 0 and p["actual"] < 0)
        or (p["predicted"] == 0 and p["actual"] == 0)
    )
    return {
        "games": len(predictions),
        "mae": round(statistics.mean(abs(error) for error in errors), 3),
        "rmse": round(math.sqrt(statistics.mean(error * error for error in errors)), 3),
        "winnerAccuracy": round(correct / len(predictions), 4),
        "baselineMae": round(statistics.mean(abs(error) for error in baseline_errors), 3),
        "baselineRmse": round(math.sqrt(statistics.mean(error * error for error in baseline_errors)), 3),
    }


all_predictions = []
season_results = []

for season in range(FIRST_SEASON, LAST_SEASON + 1):
    records = get("/records", {"year": season})
    team_names = [
        record["team"] for record in records
        if str(record.get("classification", "")).lower() == "fbs" and record.get("team")
    ]
    if len(team_names) < 100:
        print(f"Skipping {season}: only {len(team_names)} FBS teams found.")
        continue

    games = get("/games", {"year": season, "seasonType": "regular", "classification": "fbs"})
    games = [
        game for game in games
        if game.get("completed")
        and game.get("homePoints") is not None
        and game.get("awayPoints") is not None
        and game.get("homeTeam") and game.get("awayTeam")
        and norm(game.get("homeTeam")) in {norm(team) for team in team_names}
        and norm(game.get("awayTeam")) in {norm(team) for team in team_names}
    ]
    if not games:
        print(f"Skipping {season}: no completed FBS-vs-FBS games found.")
        continue

    talent = get_optional("/talent", {"year": season})
    if not talent:
        talent = get_optional("/recruiting/teams", {"year": season})
    talent_by_team = by_team(talent)
    raw_talent = {
        team: first_number(talent_by_team.get(norm(team), {}), ["talent", "talentComposite", "rating", "points"])
        for team in team_names
    }
    talent_z = standardized(raw_talent)
    prior_points = {team: max(-18.0, min(18.0, 6.0 * talent_z[team])) for team in team_names}

    season_predictions = []
    weeks = sorted({int(game.get("week") or 0) for game in games if int(game.get("week") or 0) > 0})
    for target_week in weeks:
        training = [game for game in games if int(game.get("week") or 0) < target_week]
        target_games = [game for game in games if int(game.get("week") or 0) == target_week]
        # Match the production model's early-season prior schedule.
        training_week = max(1, target_week - 1)
        prior_equivalents = max(0.0, 4.0 * (14.0 - min(training_week, 14)) / 13.0)
        if not any(value is not None for value in raw_talent.values()):
            prior_equivalents = 0.0
        ratings = fit_ratings(team_names, training, prior_points, prior_equivalents)

        for game in target_games:
            home, away = game["homeTeam"], game["awayTeam"]
            actual = float(game["homePoints"]) - float(game["awayPoints"])
            hfa = 0.0 if game.get("neutralSite", False) else HOME_FIELD_ADVANTAGE
            predicted = ratings[home] - ratings[away] + hfa
            baseline = hfa
            entry = {
                "season": season,
                "week": target_week,
                "homeTeam": home,
                "awayTeam": away,
                "actual": actual,
                "predicted": predicted,
                "baseline": baseline,
            }
            all_predictions.append(entry)
            season_predictions.append(entry)

    result = {"season": season, **metrics(season_predictions)}
    season_results.append(result)
    print(f"{season}: {result['games']} games, MAE {result['mae']}, baseline MAE {result['baselineMae']}")

overall = metrics(all_predictions)
improved = (
    overall["mae"] < overall["baselineMae"]
    if overall["mae"] is not None and overall["baselineMae"] is not None else None
)
output = {
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "modelVersion": 3,
    "seasons": [result["season"] for result in season_results],
    "overall": overall,
    "beatsHomeFieldOnlyBaseline": improved,
    "baselineDescription": "Predicts a 2.5-point home win for non-neutral games and 0 points at neutral sites.",
    "method": "Walk-forward by regular-season week: each prediction uses only completed games from earlier weeks in the same season.",
    "seasonResults": season_results,
    "notes": [
        "MAE and RMSE measure error in the predicted home-team scoring margin, in points; lower is better.",
        "Winner accuracy is the share of games where the predicted margin has the same sign as the actual margin.",
        "The baseline uses only home-field advantage and no team-strength information.",
        "The test covers regular-season FBS-vs-FBS games from historical seasons; it does not include bowl or playoff games.",
        "Historical talent inputs are used as the early-season prior when available; otherwise the model falls back to no talent prior."
    ]
}
os.makedirs("data", exist_ok=True)
with open("data/backtest.json", "w", encoding="utf-8") as output_file:
    json.dump(output, output_file, indent=2)
print(f"Backtest complete: {overall['games']} games, MAE {overall['mae']} points, baseline MAE {overall['baselineMae']} points.")
