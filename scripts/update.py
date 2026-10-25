#!/usr/bin/env python3
"""
pl-watch データ更新スクリプト（ネタバレ防止版）

ESPN の非公式 API から 日程 / スタメン / フォーメーション / ベンチ を、
プレミアリーグ公式サイトから 選手写真 を取得して data/ 以下に JSON を書き出す。

【絶対のルール】
  スコア・得点者・勝敗・カード・交代時間・順位は一切保存しない。
  出力は「ホワイトリスト方式」で必要な項目だけを手で詰め直し、
  最後に禁止ワードが出力に含まれていないかを検査する。

依存ライブラリなし（標準ライブラリのみ）。Python 3.10+。
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer"
PL_API = "https://footballapi.pulselive.com/football"
PL_PHOTO = "https://resources.premierleague.com/premierleague/photos/players/250x250/{opta}.png"
ESPN_LOGO = "https://a.espncdn.com/i/teamlogos/soccer/500/{id}.png"

# 出力 JSON に紛れ込んではいけない語（キー名・値の両方を検査）
FORBIDDEN = re.compile(
    r'"(score|scores|winner|goals?|goalScorers?|assists?|result|points|record|'
    r'standing|standings|rank|yellowCards?|redCards?|subbedIn|subbedOut|'
    r'keyEvents|commentary|leaders|headlines?|plays|scoringPlays|penalt\w*)"',
    re.IGNORECASE,
)

NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------- utils
def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def get_json(url: str, headers: dict | None = None, retries: int = 3) -> dict | None:
    h = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            log(f"  HTTP {e.code} {url}")
            if e.code in (403, 404):
                return None
        except Exception as e:  # noqa: BLE001
            log(f"  error {e} {url}")
        time.sleep(1.5 * (attempt + 1))
    return None


def norm_name(s: str | None) -> str:
    """アクセント除去・小文字化・記号除去した比較用の名前"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=1)
    m = FORBIDDEN.search(text)
    if m:
        raise RuntimeError(f"禁止項目 {m.group(0)} が出力に含まれています: {path}")
    path.write_text(text + "\n", encoding="utf-8")


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_espn_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- 写真 (PL公式)
_pl_season_cache: int | None = None


def pl_current_season() -> int | None:
    global _pl_season_cache
    if _pl_season_cache:
        return _pl_season_cache
    d = get_json(f"{PL_API}/competitions/1/compseasons?page=0&pageSize=1",
                 {"Origin": "https://www.premierleague.com", "Referer": "https://www.premierleague.com/"})
    try:
        _pl_season_cache = int(d["content"][0]["id"])
    except Exception:  # noqa: BLE001
        _pl_season_cache = None
    return _pl_season_cache


def pl_squad(pl_team_id: int) -> list[dict]:
    """PL公式の選手一覧 → [{name, first, last, jersey, pos, photo}]"""
    sid = pl_current_season()
    if not sid:
        return []
    url = (f"{PL_API}/teams/{pl_team_id}/compseasons/{sid}/staff"
           f"?pageSize=100&compSeasons={sid}&altIds=true&page=0&type=player")
    d = get_json(url, {"Origin": "https://www.premierleague.com", "Referer": "https://www.premierleague.com/"})
    out = []
    for p in (d or {}).get("players", []):
        info = p.get("info", {}) or {}
        opta = (p.get("altIds") or {}).get("opta")
        birth = p.get("birth") or {}
        nat = p.get("nationalTeam") or birth.get("country") or {}
        dob_ms = (birth.get("date") or {}).get("millis")
        join_ms = (p.get("joinDate") or {}).get("millis")
        out.append({
            "name": (p.get("name") or {}).get("display"),
            "first": (p.get("name") or {}).get("first"),
            "last": (p.get("name") or {}).get("last"),
            "jersey": info.get("shirtNum"),
            "pos": info.get("position"),
            "posInfo": info.get("positionInfo"),
            "photo": PL_PHOTO.format(opta=opta) if opta else None,
            # --- 選手詳細用（成績系は入れない）
            "dob": datetime.fromtimestamp(dob_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if dob_ms else None,
            "nat": nat.get("country"),
            "natCode": nat.get("isoCode"),
            "height": p.get("height"),
            "joined": datetime.fromtimestamp(join_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if join_ms else None,
            "birthPlace": birth.get("place"),
        })
    return out


BIO_KEYS = ("photo", "dob", "nat", "natCode", "height", "joined", "birthPlace", "posInfo")


def bio_of(q: dict) -> dict:
    return {k: q.get(k) for k in BIO_KEYS}


def pl_all_teams_index() -> dict[str, dict]:
    """リーグ全チームの 正規化名 → {name, team, 写真, 生年月日, 国籍, 身長...}（相手チームの選手用）"""
    sid = pl_current_season()
    if not sid:
        return {}
    d = get_json(f"{PL_API}/teams?pageSize=40&compSeasons={sid}&altIds=true&page=0",
                 {"Origin": "https://www.premierleague.com", "Referer": "https://www.premierleague.com/"})
    index: dict[str, dict] = {}
    for t in (d or {}).get("content", []):
        tid = t.get("id")
        if tid is None:
            continue
        tname = t.get("name") or (t.get("club") or {}).get("name")
        for p in pl_squad(int(tid)):
            if not p["name"]:
                continue
            rec = {"name": p["name"], "team": tname, "jersey": p["jersey"], **bio_of(p)}
            index[norm_name(p["name"])] = rec
            # 姓だけのキーも（衝突したら先勝ち）
            ln = norm_name(p["last"])
            if ln and ln not in index:
                index[ln] = rec
        time.sleep(0.3)
    return index


def find_in_index(name: str, index: dict[str, dict]) -> dict | None:
    n = norm_name(name)
    if n in index:
        return index[n]
    parts = n.split()
    if parts and parts[-1] in index:
        return index[parts[-1]]
    return None


def find_photo(name: str, index: dict[str, dict]) -> str | None:
    rec = find_in_index(name, index)
    return rec.get("photo") if rec else None


# ---------------------------------------------------------------- 配置 (フォーメーション図)
def pos_depth(abbr: str | None) -> float:
    a = (abbr or "").upper()
    base = a.split("-")[0]
    table = {
        "G": 0, "GK": 0,
        "LB": 1, "RB": 1, "CB": 1, "CD": 1, "D": 1, "SW": 0.8,
        "LWB": 1.5, "RWB": 1.5,
        "DM": 2, "CDM": 2,
        "CM": 3, "M": 3,
        "LM": 3.5, "RM": 3.5,
        "AM": 4, "CAM": 4,
        "LW": 4.5, "RW": 4.5,
        "SS": 5, "CF": 5,
        "ST": 6, "F": 6, "FW": 6,
    }
    return table.get(base, 3)


def pos_side(abbr: str | None) -> int:
    """左→右の並び順。L=0, C-L=1, C=2, C-R=3, R=4"""
    a = (abbr or "").upper()
    if a.startswith("L"):
        return 0
    if a.endswith("-L"):
        return 1
    if a.startswith("R"):
        return 4
    if a.endswith("-R"):
        return 3
    return 2


def arrange_rows(starters: list[dict], formation: str | None) -> list[list[dict]]:
    """フォーメーション文字列(例 4-2-3-1)とポジション略号から行ごとの並びを作る。GKは別行。"""
    gk = [p for p in starters if pos_depth(p["pos"]) == 0]
    field = [p for p in starters if pos_depth(p["pos"]) != 0]
    field.sort(key=lambda p: (pos_depth(p["pos"]), pos_side(p["pos"]), p.get("place") or 99))
    sizes: list[int] = []
    if formation:
        try:
            sizes = [int(x) for x in formation.split("-")]
        except ValueError:
            sizes = []
    if not sizes or sum(sizes) != len(field):
        # フォーメーション不明 → 深さで自動グループ化
        sizes = []
        groups: dict[float, int] = {}
        for p in field:
            groups[pos_depth(p["pos"])] = groups.get(pos_depth(p["pos"]), 0) + 1
        sizes = [groups[k] for k in sorted(groups)]
    rows: list[list[dict]] = [gk] if gk else []
    i = 0
    for n in sizes:
        rows.append(field[i:i + n])
        i += n
    if i < len(field):
        rows.append(field[i:])
    return rows


# ---------------------------------------------------------------- ESPN
def espn_roster(league: str, team_id: str) -> list[dict]:
    d = get_json(f"{ESPN}/{league}/teams/{team_id}/roster")
    out = []
    for a in (d or {}).get("athletes", []):
        inj = []
        for i in a.get("injuries", []) or []:
            # 負傷情報があれば種類と状態だけ（詳細文は入れない）
            inj.append({
                "status": i.get("status"),
                "type": ((i.get("details") or {}).get("type")),
                "date": i.get("date"),
            })
        out.append({
            "id": str(a.get("id")),
            "name": a.get("displayName") or a.get("fullName"),
            "jersey": a.get("jersey"),
            "pos": (a.get("position") or {}).get("abbreviation"),
            "photo": (a.get("headshot") or {}).get("href"),
            "injuries": inj,
        })
    return out


def espn_schedule(league: str, team_id: str) -> list[dict]:
    events: dict[str, dict] = {}
    for suffix in ("", "?fixture=true"):
        d = get_json(f"{ESPN}/{league}/teams/{team_id}/schedule{suffix}")
        for e in (d or {}).get("events", []):
            events[str(e["id"])] = e
    return list(events.values())


def fixture_from_event(e: dict, team_id: str, league_name: str) -> dict | None:
    """ESPN event → ホワイトリストした fixture 情報。スコア等は一切触らない。"""
    try:
        comp = e["competitions"][0]
    except (KeyError, IndexError):
        return None
    comps = comp.get("competitors", [])
    ours = next((c for c in comps if str(c.get("id")) == team_id or str((c.get("team") or {}).get("id")) == team_id), None)
    theirs = next((c for c in comps if c is not ours), None)
    if not ours or not theirs:
        return None
    state = ((comp.get("status") or {}).get("type") or {})
    sname = state.get("name", "")
    if sname in ("STATUS_SCHEDULED", "STATUS_DELAYED"):
        status = "scheduled"
    elif sname in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED"):
        status = "postponed"
    else:
        status = "played"  # 開始後は全部 played 扱い（進行中かどうかも出さない）
    tt = theirs.get("team") or {}
    week = (e.get("week") or comp.get("week") or {})
    return {
        "eventId": str(e["id"]),
        "date": iso(parse_espn_date(e["date"])),
        "competition": league_name,
        "matchday": week.get("number") if isinstance(week, dict) else None,
        "isHome": ours.get("homeAway") == "home",
        "opponent": {
            "id": str(tt.get("id")),
            "name": tt.get("displayName") or tt.get("name"),
            "abbr": tt.get("abbreviation"),
            "logo": ESPN_LOGO.format(id=tt.get("id")),
        },
        "venue": ((comp.get("venue") or {}).get("fullName")),
        "status": status,
        "final": bool(state.get("completed")),
    }


def espn_lineups(league: str, event_id: str) -> dict[str, dict] | None:
    """summary → {teamId: {formation, players:[{id,name,jersey,pos,starter,place}]}}"""
    d = get_json(f"{ESPN}/{league}/summary?event={event_id}")
    if not d:
        return None
    out: dict[str, dict] = {}
    for r in d.get("rosters", []) or []:
        tid = str((r.get("team") or {}).get("id"))
        players = []
        for p in r.get("roster", []) or []:
            a = p.get("athlete") or {}
            players.append({
                "id": str(a.get("id")),
                "name": a.get("displayName") or a.get("fullName"),
                "jersey": p.get("jersey"),
                "pos": (p.get("position") or {}).get("abbreviation"),
                "starter": bool(p.get("starter")),
                "place": p.get("formationPlace"),
            })
        out[tid] = {"formation": r.get("formation"), "players": players}
    return out


# ---------------------------------------------------------------- 欠場理由（手入力）
def load_manual_absences(team_key: str) -> list[dict]:
    p = ROOT / "absences.json"
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log(f"absences.json が読めません: {e}")
        return []
    return d.get(team_key, []) or []


def manual_reason(name: str, match_date: datetime, entries: list[dict]) -> dict | None:
    n = norm_name(name)
    for e in entries:
        en = norm_name(e.get("name"))
        if not en:
            continue
        if en == n or en in n.split() or n.endswith(" " + en) or en == n.split()[-1]:
            f = e.get("from")
            u = e.get("until")
            if f and match_date.date() < datetime.strptime(f, "%Y-%m-%d").date():
                continue
            if u and match_date.date() > datetime.strptime(u, "%Y-%m-%d").date():
                continue
            return {"type": e.get("type") or "欠場", "reason": e.get("reason") or "", "source": "manual"}
    return None


# ---------------------------------------------------------------- main per team
def build_team(team: dict, photo_index: dict[str, dict]) -> None:
    tid = team["id"]
    league = team["league"]
    espn_id = str(team["espnTeamId"])
    tdir = DATA / tid
    log(f"== {team['name']}")

    # --- 選手名鑑（ESPN + PL公式の写真・プロフィール）
    roster = espn_roster(league, espn_id)
    plsq = pl_squad(int(team["plTeamId"])) if team.get("plTeamId") else []
    own_index = {norm_name(q["name"]): q for q in plsq if q["name"]}
    for q in plsq:
        ln = norm_name(q["last"])
        if ln and ln not in own_index:
            own_index[ln] = q
    for p in roster:
        q = find_in_index(p["name"], own_index)
        if not q and p["jersey"]:
            q = next((q for q in plsq if str(q["jersey"]) == str(p["jersey"])), None)
        if not q:
            q = find_in_index(p["name"], photo_index)
        bio = bio_of(q) if q else {}
        espn_photo = p.get("photo")
        p.update(bio)
        p["photo"] = bio.get("photo") or espn_photo
    write_json(tdir / "roster.json", {"updatedAt": iso(NOW), "players": roster})
    log(f"  roster: {len(roster)} 人（写真あり {sum(1 for p in roster if p['photo'])} 人、"
        f"プロフィールあり {sum(1 for p in roster if p.get('dob'))} 人）")

    # --- 日程
    events = espn_schedule(league, espn_id)
    fixtures = [f for f in (fixture_from_event(e, espn_id, team.get("leagueName", league)) for e in events) if f]
    fixtures.sort(key=lambda f: f["date"])

    # --- スタメン取得対象
    mdir = tdir / "matches"
    mdir.mkdir(parents=True, exist_ok=True)
    manual = load_manual_absences(tid)
    roster_by_id = {p["id"]: p for p in roster}

    for f in fixtures:
        mpath = mdir / f"{f['eventId']}.json"
        existing = None
        if mpath.exists():
            try:
                existing = json.loads(mpath.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                existing = None
        if existing and existing.get("final"):
            f["hasLineup"] = True
            continue
        kickoff = datetime.strptime(f["date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        want = f["status"] == "played" or (f["status"] == "scheduled" and kickoff - NOW <= timedelta(hours=3))
        if not want:
            f["hasLineup"] = bool(existing)
            continue
        lineups = espn_lineups(league, f["eventId"])
        time.sleep(0.5)
        ours = (lineups or {}).get(espn_id)
        if not ours or not ours["players"]:
            f["hasLineup"] = bool(existing)
            continue
        theirs = next((v for k, v in lineups.items() if k != espn_id), None)

        def pack(side: dict | None, use_roster_photos: bool) -> dict | None:
            if not side:
                return None
            players = []
            for p in side["players"]:
                rp = roster_by_id.get(p["id"]) if use_roster_photos else None
                photo = (rp or {}).get("photo") or find_photo(p["name"], photo_index)
                players.append({**p, "photo": photo})
            starters = [p for p in players if p["starter"]]
            bench = [p for p in players if not p["starter"]]
            rows = arrange_rows(starters, side.get("formation"))
            return {
                "formation": side.get("formation"),
                "rows": [[p["id"] for p in row] for row in rows],
                "starters": starters,
                "bench": bench,
            }

        ours_p = pack(ours, True)
        theirs_p = pack(theirs, False)

        # 欠場・メンバー外 = 名鑑 − 当日メンバー
        squad_ids = {p["id"] for p in ours["players"]}
        absentees = []
        for p in roster:
            if p["id"] in squad_ids:
                continue
            info = {"id": p["id"], "name": p["name"], "jersey": p["jersey"], "pos": p["pos"], "photo": p["photo"]}
            mr = manual_reason(p["name"], kickoff, manual)
            if mr:
                info.update(mr)
            elif p.get("injuries"):
                i = p["injuries"][0]
                info.update({"type": "負傷" if (i.get("type") or "").lower() != "suspension" else "出場停止",
                             "reason": i.get("status") or "", "source": "espn"})
            else:
                info.update({"type": "理由不明", "reason": "", "source": "none"})
            absentees.append(info)
        absentees.sort(key=lambda a: (a["type"] == "理由不明", a["jersey"] is None, int(a["jersey"]) if (a["jersey"] or "").isdigit() else 999))

        write_json(mpath, {
            "eventId": f["eventId"],
            "date": f["date"],
            "final": f["final"],
            "updatedAt": iso(NOW),
            "team": ours_p,
            "opponent": {"id": f["opponent"]["id"], "name": f["opponent"]["name"], **(theirs_p or {})} if theirs_p else None,
            "absentees": absentees,
        })
        f["hasLineup"] = True
        log(f"  lineup: {f['date'][:10]} vs {f['opponent']['name']} ({ours.get('formation')}) final={f['final']}")

    for f in fixtures:
        f.pop("final", None)
    write_json(tdir / "fixtures.json", {"updatedAt": iso(NOW), "fixtures": fixtures})

    # --- 今季メンバー入り回数（ユース選手などを欠場者一覧で分けるため）
    counts: dict[str, int] = {}
    for mp in sorted(mdir.glob("*.json")):
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for p in (m.get("team") or {}).get("starters", []) + (m.get("team") or {}).get("bench", []):
            counts[p["id"]] = counts.get(p["id"], 0) + 1
    write_json(tdir / "squad-history.json", {"updatedAt": iso(NOW), "appearancesInSquad": counts})
    log(f"  fixtures: {len(fixtures)} 試合（スタメンあり {sum(1 for f in fixtures if f.get('hasLineup'))}）")


def main() -> int:
    cfg = json.loads((ROOT / "teams.json").read_text(encoding="utf-8"))
    teams = cfg.get("teams", [])
    log("PL公式から全チームの選手インデックスを作成中...")
    photo_index = pl_all_teams_index()
    log(f"  選手 {len(photo_index)} 件")
    if photo_index:
        # フルネームのキーだけを書き出す（相手チーム選手の詳細ポップアップ用）
        full_only = {k: v for k, v in photo_index.items() if " " in k or norm_name(v["name"]) == k}
        write_json(DATA / "pl-players.json", {"updatedAt": iso(NOW), "players": full_only})
    ok = True
    for team in teams:
        try:
            build_team(team, photo_index)
        except Exception as e:  # noqa: BLE001
            ok = False
            log(f"!! {team.get('id')} の更新に失敗: {e!r}")
    write_json(DATA / "meta.json", {"updatedAt": iso(NOW), "teams": [t["id"] for t in teams]})
    log("done")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
