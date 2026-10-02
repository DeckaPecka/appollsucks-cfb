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
ELO_INITIAL = 1500.0
ELO_HOME_ADVANTAGE = 55.0
ELO_K_FACTOR = 20.0


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


def elo_expected(home_elo, away_elo, neutral_site):
    home_advantage = 0.0 if neutral_site else ELO_HOME_ADVANTAGE
    return 1.0 / (1.0 + 10.0 ** (-(home_elo + home_advantage - away_elo) / 400.0))


def metrics(predictions):
    if not predictions:
        return {"games": 0, "mae": None, "rmse": None, "winnerAccuracy": None, "baselineMae": None, "baselineRmse": None, "eloWinnerAccuracy": None, "marketGames": 0, "modelMaeOnMarketGames": None, "marketSpreadMae": None, "modelCoverAccuracy": None}
    errors = [p["predicted"] - p["actual"] for p in predictions]
    baseline_errors = [p["baseline"] - p["actual"] for p in predictions]
    correct = sum(
        1 for p in predictions
        if (p["predicted"] > 0 and p["actual"] > 0)
        or (p["predicted"] < 0 and p["actual"] < 0)
        or (p["predicted"] == 0 and p["actual"] == 0)
    )
    elo_correct = sum(
        1 for p in predictions
        if (p["eloHomeWinProbability"] > 0.5 and p["actual"] > 0)
        or (p["eloHomeWinProbability"] < 0.5 and p["actual"] < 0)
        or (p["eloHomeWinProbability"] == 0.5 and p["actual"] == 0)
    )
    market_predictions = [p for p in predictions if p.get("marketHomeMargin") is not None]
    model_market_errors = [p["predicted"] - p["actual"] for p in market_predictions]
    market_errors = [p["marketHomeMargin"] - p["actual"] for p in market_predictions]
    # Against-the-spread (ATS): did the model correctly identify which side
    # would cover the closing spread? Exact pushes are excluded.
    ats_decisions = [
        p for p in market_predictions
        if abs(p["actual"] - p["marketHomeMargin"]) > 1e-9
        and abs(p["predicted"] - p["marketHomeMargin"]) > 1e-9
    ]
    ats_correct = sum(
        1 for p in ats_decisions
        if (p["predicted"] - p["marketHomeMargin"]) * (p["actual"] - p["marketHomeMargin"]) > 0
    )
    return {
        "games": len(predictions),
        "mae": round(statistics.mean(abs(error) for error in errors), 3),
        "rmse": round(math.sqrt(statistics.mean(error * error for error in errors)), 3),
        "winnerAccuracy": round(correct / len(predictions), 4),
        "baselineMae": round(statistics.mean(abs(error) for error in baseline_errors), 3),
        "baselineRmse": round(math.sqrt(statistics.mean(error * error for error in baseline_errors)), 3),
        "eloWinnerAccuracy": round(elo_correct / len(predictions), 4),
        "marketGames": len(market_predictions),
        "modelMaeOnMarketGames": round(statistics.mean(abs(error) for error in model_market_errors), 3) if model_market_errors else None,
        "marketSpreadMae": round(statistics.mean(abs(error) for error in market_errors), 3) if market_errors else None,
        "modelCoverAccuracy": round(ats_correct / len(ats_decisions), 4) if ats_decisions else None,
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
    lines_games = get_optional("/lines", {"year": season, "seasonType": "regular"})
    lines_by_game = {}
    lines_by_matchup = {}
    for line_game in lines_games:
        candidates = line_game.get("lines") or []
        valid = []
        for item in candidates:
            try:
                spread_value = float(item.get("spread"))
                if math.isfinite(spread_value):
                    valid.append({**item, "_spreadValue": spread_value})
            except (TypeError, ValueError):
                continue
        if not valid:
            continue
        # Prefer consensus closing spread; otherwise average available providers.
        consensus = [
            item for item in valid
            if "consensus" in str(
                (item.get("provider") or {}).get("name", "")
                if isinstance(item.get("provider"), dict)
                else item.get("provider") or ""
            ).lower()
        ]
        selected = consensus or valid
        spreads = [item["_spreadValue"] for item in selected]
        # CFBD's line records and game records do not always expose matching IDs.
        # Store both ID-based and matchup-based keys to avoid losing valid lines.
        market_home_margin = -statistics.mean(spreads)
        if line_game.get("id") is not None:
            lines_by_game[line_game.get("id")] = market_home_margin
        line_home = norm(line_game.get("homeTeam"))
        line_away = norm(line_game.get("awayTeam"))
        line_week = line_game.get("week")
        if line_home and line_away and line_week is not None:
            lines_by_matchup[(int(line_game.get("season") or season), int(line_week), line_home, line_away)] = market_home_margin
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
    elo_ratings = {team: ELO_INITIAL for team in team_names}
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
            elo_home_probability = elo_expected(
                elo_ratings[home], elo_ratings[away], bool(game.get("neutralSite", False))
            )
            entry = {
                "season": season,
                "week": target_week,
                "homeTeam": home,
                "awayTeam": away,
                "actual": actual,
                "predicted": predicted,
                "baseline": baseline,
                "eloHomeWinProbability": elo_home_probability,
                "marketHomeMargin": lines_by_game.get(game.get("id"), lines_by_matchup.get((
                    season, target_week, norm(home), norm(away)
                ))),
            }
            all_predictions.append(entry)
            season_predictions.append(entry)

        # Update Elo only after every game in this week has been predicted, so
        # another game's result from the same week cannot leak into a forecast.
        for game in target_games:
            home, away = game["homeTeam"], game["awayTeam"]
            actual_home_score = (
                1.0 if float(game["homePoints"]) > float(game["awayPoints"])
                else 0.0 if float(game["homePoints"]) < float(game["awayPoints"])
                else 0.5
            )
            expected_home_score = elo_expected(
                elo_ratings[home], elo_ratings[away], bool(game.get("neutralSite", False))
            )
            change = ELO_K_FACTOR * (actual_home_score - expected_home_score)
            elo_ratings[home] += change
            elo_ratings[away] -= change

    result = {"season": season, **metrics(season_predictions)}
    season_results.append(result)
    print(
        f"{season}: {result['games']} games, MAE {result['mae']}, "
        f"baseline MAE {result['baselineMae']}, spread games {result['marketGames']} "
        f"(line records fetched: {len(lines_games)})"
    )

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
    "eloBaselineDescription": "Simple Elo baseline: all teams start at 1500; 55 Elo points of home advantage; K-factor 20; ratings update only after all games in a week have been predicted.",
    "spreadBaselineDescription": "CollegeFootballData historical spread lines; market-implied home margin is the negative of the listed home-team spread. Prefer consensus when available, otherwise average providers. Games are matched by game ID, with season/week/home/away matchup fallback.",
    "spreadDataStatus": {
        "gamesWithLines": overall["marketGames"],
        "note": "If gamesWithLines is zero, the CFBD API returned no usable historical spread values for the requested seasons; check API access and line data availability."
    },
    "method": "Walk-forward by regular-season week: each prediction uses only completed games from earlier weeks in the same season. Model ratings and Elo predictions are frozen before each target week's results are used.",
    "seasonResults": season_results,
    "notes": [
        "MAE and RMSE measure error in the predicted home-team scoring margin, in points; lower is better.",
        "Winner accuracy is the share of games where the predicted margin has the same sign as the actual margin.",
        "The home-field-only baseline uses no team-strength information.",
        "The Elo baseline starts every team at 1500, uses a 55-point Elo home advantage and K-factor 20, and updates only after all games in a week have been predicted.",
        "Closing betting spreads are used only as a benchmark, never as an input to the model's ratings. Market comparison metrics use only games with a recorded spread; model MAE is recalculated on that same subset for a fair comparison.",
        "Against-the-spread accuracy measures whether the model correctly predicts which side covers the closing spread; pushes are excluded.",
        "Leakage check: target-week scores are used only to grade predictions and update Elo after that week's predictions; ratings for the target week use earlier weeks only.",
        "Historical talent/recruiting inputs are used only as a preseason prior; the script does not use season-final FPI, box-score statistics, or target-week results as model features.",
        "The test covers regular-season FBS-vs-FBS games from historical seasons; it does not include bowl or playoff games."
    ]
}
os.makedirs("data", exist_ok=True)
with open("data/backtest.json", "w", encoding="utf-8") as output_file:
    json.dump(output, output_file, indent=2)
print(f"Backtest complete: {overall['games']} games, MAE {overall['mae']} points, baseline MAE {overall['baselineMae']} points.")
