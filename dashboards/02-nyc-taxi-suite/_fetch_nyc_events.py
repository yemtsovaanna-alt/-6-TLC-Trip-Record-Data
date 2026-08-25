"""Download NYC-area sports schedules, concerts, street closures → events/nyc_events.csv"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "events" / "nyc_events.csv"
CURATED_CONCERTS = ROOT / "events" / "curated_concerts.csv"
VENUES = pd.read_csv(ROOT / "events" / "venues.csv")
ET = ZoneInfo("America/New_York")

DEFAULT_START = {
    "NFL": 13, "NBA": 19, "MLB": 19, "MLS": 19, "Tennis": 11, "Marathon": 8,
    "Concert": 20, "StreetClosure": 9, "Super Bowl": 18,
}

MLB_TEAMS = {147: "yankee", 121: "citi"}  # NYY, NYM

MLS_LOCATION_VENUE = {
    "Yankee Stadium": "yankee",
    "Citi Field": "citi",
    "Red Bull Arena": "red_bulls",
}
MLS_HOME_TEAMS = {"New York City", "New York"}  # NYCFC, Red Bulls
MLS_FEED_YEARS = range(2023, 2026)  # fixturedownload.com JSON feeds

# setlist.fm venue IDs (optional API key: SETLIST_FM_API_KEY)
SETLIST_VENUES = {
    "bd6aee8a": "msg",
    "73d1ae6d": "barclays",
    "63d477c7": "citi",
    "3bd6e4c4": "yankee",
}

BILLY_JOEL_MSG_DATES = [
    "2019-01-24", "2019-03-21", "2019-05-09", "2019-06-02", "2019-07-11",
    "2019-08-28", "2019-09-27", "2019-10-25",
    "2020-01-25", "2020-02-20",
    "2021-11-05", "2021-12-20",
    "2022-02-12", "2022-03-24", "2022-05-14", "2022-06-10", "2022-07-20",
    "2022-08-24", "2022-10-09", "2022-11-23",
    "2023-01-13", "2023-02-14", "2023-03-26", "2023-06-02", "2023-07-24",
    "2023-08-29", "2023-10-20", "2023-11-22", "2023-12-19",
    "2024-01-11", "2024-02-09", "2024-03-28", "2024-04-26", "2024-05-09",
    "2024-06-08", "2024-07-25",
]


def _http_json(url: str, headers: dict | None = None, timeout: int = 45) -> dict:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "nyc-taxi-events/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _nfl_home_games() -> pd.DataFrame:
    url = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
    try:
        games = pd.read_csv(url)
    except Exception as e:
        print(f"  NFL fetch failed: {e}")
        return pd.DataFrame()
    games = games[games["home_team"].isin(["NYG", "NYJ"])].copy()
    games["date"] = pd.to_datetime(games["gameday"])
    games = games[(games["date"].dt.year >= 2019) & (games["date"].dt.year <= 2025)]
    games = games[games["game_type"].isin(["REG", "POST"])]
    hr = games["gametime"].fillna("13:00").str.split(":").str[0].astype(int)
    games["start_hour"] = hr.where(hr.notna(), DEFAULT_START["NFL"])
    out = pd.DataFrame({
        "date": games["date"].dt.date,
        "start_hour": games["start_hour"].astype(int),
        "venue_id": "metlife",
        "event_type": "NFL",
        "title": games["away_team"] + " @ " + games["home_team"],
        "tags": "sports,nfl",
    })
    print(f"  NFL home games: {len(out)}")
    return out


def _mlb_home_games() -> pd.DataFrame:
    """MLB Stats API (pybaseball/Baseball-Reference often break for recent seasons)."""
    rows = []
    for year in range(2019, 2026):
        for team_id, venue_id in MLB_TEAMS.items():
            url = (
                f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team_id}"
                f"&season={year}&gameTypes=R,P&hydrate=team"
            )
            try:
                data = _http_json(url)
            except Exception as e:
                print(f"  MLB {venue_id} {year}: {e}")
                continue
            for day in data.get("dates", []):
                for g in day.get("games", []):
                    if g["teams"]["home"]["team"]["id"] != team_id:
                        continue
                    gd = g["gameDate"].replace("Z", "+00:00")
                    local = dt.datetime.fromisoformat(gd).astimezone(ET)
                    away = g["teams"]["away"]["team"]["name"]
                    home = g["teams"]["home"]["team"]["name"]
                    gtype = "POST" if g.get("gameType") != "R" else "REG"
                    rows.append({
                        "date": local.date(),
                        "start_hour": local.hour,
                        "venue_id": venue_id,
                        "event_type": "MLB",
                        "title": f"{away} @ {home}" + (f" ({gtype})" if gtype == "POST" else ""),
                        "tags": "sports,mlb",
                    })
    out = pd.DataFrame(rows)
    print(f"  MLB home games (Stats API): {len(out)}")
    return out


def _mls_home_games() -> pd.DataFrame:
    """MLS home fixtures for NYCFC + Red Bulls via fixturedownload.com (2023+)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://fixturedownload.com/",
    }
    rows = []
    for year in MLS_FEED_YEARS:
        url = f"https://fixturedownload.com/feed/json/mls-{year}"
        try:
            data = _http_json(url, headers=headers)
        except Exception as e:
            print(f"  MLS {year}: {e}")
            continue
        if not isinstance(data, list):
            print(f"  MLS {year}: unexpected payload")
            continue
        for m in data:
            if m.get("HomeTeam") not in MLS_HOME_TEAMS:
                continue
            loc = (m.get("Location") or "").strip()
            venue_id = MLS_LOCATION_VENUE.get(loc)
            if not venue_id:
                continue
            try:
                utc = dt.datetime.strptime(m["DateUtc"], "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
            except (KeyError, ValueError):
                continue
            local = utc.astimezone(ET)
            home = m["HomeTeam"]
            away = m.get("AwayTeam", "?")
            club = "NYCFC" if home == "New York City" else "Red Bulls"
            rows.append({
                "date": local.date(),
                "start_hour": local.hour,
                "venue_id": venue_id,
                "event_type": "MLS",
                "title": f"{away} @ {club}",
                "tags": "sports,mls,soccer",
            })
    out = pd.DataFrame(rows)
    print(f"  MLS home games (fixturedownload {MLS_FEED_YEARS.start}-{MLS_FEED_YEARS.stop - 1}): {len(out)}")
    return out


def _nba_from_nba_api() -> pd.DataFrame:
    try:
        from nba_api.stats.endpoints import scheduleleaguev2
    except ImportError:
        print("  NBA: nba_api not installed, using curated playoffs only")
        return _nba_curated()
    rows = []
    for season in ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25"]:
        try:
            sched = scheduleleaguev2.ScheduleLeagueV2(season=season).get_data_frames()[0]
        except Exception as e:
            print(f"  NBA {season}: {e}")
            continue
        home = sched[sched["homeTeam_teamTricode"].isin(["NYK", "BKN"])].copy()
        home["date"] = pd.to_datetime(home["gameDate"]).dt.date
        for _, r in home.iterrows():
            vid = "msg" if r["homeTeam_teamTricode"] == "NYK" else "barclays"
            rows.append({
                "date": r["date"],
                "start_hour": DEFAULT_START["NBA"],
                "venue_id": vid,
                "event_type": "NBA",
                "title": f"{r['awayTeam_teamTricode']} @ {r['homeTeam_teamTricode']}",
                "tags": "sports,nba",
            })
    out = pd.DataFrame(rows)
    print(f"  NBA (nba_api): {len(out)}")
    return out


def _nba_curated() -> pd.DataFrame:
    dates = [
        ("2021-05-22", "msg", "Knicks home playoff"),
        ("2021-05-26", "msg", "Knicks home playoff"),
        ("2021-05-28", "msg", "Knicks home playoff"),
        ("2023-04-15", "msg", "Knicks play-in"),
        ("2023-04-23", "msg", "Knicks playoff"),
        ("2024-05-06", "msg", "Knicks playoff"),
        ("2022-04-12", "barclays", "Nets play-in"),
    ]
    return pd.DataFrame([{
        "date": dt.date.fromisoformat(d),
        "start_hour": DEFAULT_START["NBA"],
        "venue_id": v,
        "event_type": "NBA",
        "title": title,
        "tags": "sports,nba",
    } for d, v, title in dates])


def _billy_joel_msg() -> pd.DataFrame:
    rows = [{
        "date": dt.date.fromisoformat(d),
        "start_hour": 20,
        "venue_id": "msg",
        "event_type": "Concert",
        "title": "Billy Joel MSG residency",
        "tags": "concerts,rock,residency",
    } for d in BILLY_JOEL_MSG_DATES]
    out = pd.DataFrame(rows)
    print(f"  Billy Joel MSG residency: {len(out)}")
    return out


def _curated_concerts() -> pd.DataFrame:
    if not CURATED_CONCERTS.exists():
        return pd.DataFrame()
    df = pd.read_csv(CURATED_CONCERTS)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["start_hour"] = df.get("start_hour", DEFAULT_START["Concert"]).fillna(DEFAULT_START["Concert"]).astype(int)
    df["tags"] = df.get("tags", "concerts").fillna("concerts")
    print(f"  Curated concerts CSV: {len(df)}")
    return df[["date", "start_hour", "venue_id", "event_type", "title", "tags"]]


def _setlist_concerts() -> pd.DataFrame:
    api_key = os.environ.get("SETLIST_FM_API_KEY", "").strip()
    if not api_key:
        print("  setlist.fm: no SETLIST_FM_API_KEY, skipping")
        return pd.DataFrame()
    headers = {"Accept": "application/json", "x-api-key": api_key}
    rows = []
    for venue_id, vid in SETLIST_VENUES.items():
        page = 1
        while page <= 20:
            url = f"https://api.setlist.fm/rest/1.0/venue/{venue_id}/setlists?p={page}"
            try:
                data = _http_json(url, headers=headers)
            except urllib.error.HTTPError as e:
                print(f"  setlist.fm {vid} p{page}: HTTP {e.code}")
                break
            except Exception as e:
                print(f"  setlist.fm {vid}: {e}")
                break
            sets = data.get("setlist") or []
            if not sets:
                break
            for s in sets:
                try:
                    d = dt.datetime.strptime(s["eventDate"], "%d-%m-%Y").date()
                except (KeyError, ValueError):
                    continue
                if d.year < 2019 or d.year > 2025:
                    continue
                artist = (s.get("artist") or {}).get("name") or "Concert"
                rows.append({
                    "date": d,
                    "start_hour": DEFAULT_START["Concert"],
                    "venue_id": vid,
                    "event_type": "Concert",
                    "title": f"{artist} (setlist.fm)",
                    "tags": "concerts,setlistfm",
                })
            if len(sets) < 20:
                break
            page += 1
    out = pd.DataFrame(rows)
    print(f"  setlist.fm concerts: {len(out)}")
    return out


def _thanksgiving_date(year: int) -> dt.date:
    d = dt.date(year, 11, 1)
    offset = (3 - d.weekday()) % 7
    first_thu = d + dt.timedelta(days=offset)
    return first_thu + dt.timedelta(days=21)


def _last_sunday_june(year: int) -> dt.date:
    d = dt.date(year, 6, 30)
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def _street_closure_events() -> pd.DataFrame:
    """Recurring parades / mass street closures (Thanksgiving, St Patrick's, NYE, Pride)."""
    rows = []
    for year in range(2019, 2026):
        tg = _thanksgiving_date(year)
        rows.extend([
            {
                "date": tg,
                "start_hour": 9,
                "venue_id": "macys_parade",
                "event_type": "StreetClosure",
                "title": f"Macy's Thanksgiving Day Parade {year}",
                "tags": "street_closure,parade,thanksgiving",
            },
            {
                "date": tg - dt.timedelta(days=1),
                "start_hour": 18,
                "venue_id": "macys_parade",
                "event_type": "StreetClosure",
                "title": f"Macy's Balloon Inflation {year}",
                "tags": "street_closure,parade,thanksgiving,inflation",
            },
            {
                "date": dt.date(year, 3, 17),
                "start_hour": 11,
                "venue_id": "st_patricks",
                "event_type": "StreetClosure",
                "title": f"NYC St. Patrick's Day Parade {year}",
                "tags": "street_closure,parade,st_patricks",
            },
            {
                "date": dt.date(year, 12, 31),
                "start_hour": 18,
                "venue_id": "times_sq",
                "event_type": "StreetClosure",
                "title": f"Times Square NYE {year}",
                "tags": "street_closure,nye,times_square",
            },
            {
                "date": _last_sunday_june(year),
                "start_hour": 12,
                "venue_id": "times_sq",
                "event_type": "StreetClosure",
                "title": f"NYC Pride March {year}",
                "tags": "street_closure,parade,pride",
            },
        ])
        nov1 = dt.date(year, 11, 1)
        sunday = nov1 + dt.timedelta(days=(6 - nov1.weekday()) % 7)
        rows.append({
            "date": sunday, "start_hour": 8, "venue_id": "marathon",
            "event_type": "Marathon", "title": f"NYC Marathon {year}",
            "tags": "sports,marathon,street_closure",
        })
        us_open_start = dt.date(year, 8, 28)
        for i in range(14):
            d = us_open_start + dt.timedelta(days=i)
            rows.append({
                "date": d, "start_hour": 11, "venue_id": "us_open",
                "event_type": "Tennis", "title": f"US Open {year}",
                "tags": "sports,tennis",
            })
    rows.append({
        "date": dt.date(2020, 2, 2), "start_hour": 18, "venue_id": "times_sq",
        "event_type": "Super Bowl", "title": "Super Bowl LIV watch parties NYC",
        "tags": "sports,superbowl",
    })
    out = pd.DataFrame(rows)
    print(f"  Street closures / parades / fixed: {len(out)}")
    return out


def main():
    OUT.parent.mkdir(exist_ok=True)
    parts = [
        _nfl_home_games(),
        _mlb_home_games(),
        _mls_home_games(),
        _nba_from_nba_api(),
        _billy_joel_msg(),
        _curated_concerts(),
        _setlist_concerts(),
        _street_closure_events(),
    ]
    parts = [p for p in parts if not p.empty]
    if not parts:
        raise SystemExit("No events fetched")
    df = pd.concat(parts, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.drop_duplicates(subset=["date", "venue_id", "title"])
    df = df.sort_values(["date", "venue_id"]).reset_index(drop=True)
    df.to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(df)} events)")
    print(df["event_type"].value_counts().to_string())


if __name__ == "__main__":
    main()
