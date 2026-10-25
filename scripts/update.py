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

import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
import urllib.error
import urllib.parse
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


def write_json_unchecked(path: Path, obj) -> None:
    """結果ファイル（data/<team>/results/）専用。スコアを含むので禁止ワード検査を通さない。
    画面側は「結果を表示」ボタンが押された時だけこのファイルを読む。"""
    assert path.parent.name == "results", "write_json_unchecked は results/ 以外に使わない"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


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


# ---------------------------------------------------------------- 経歴 (Wikidata)
WD_SPARQL = "https://query.wikidata.org/sparql"
# Wikimedia の UA ポリシーに合わせる（連絡先URL入り。形式が違うと 429 で弾かれる）
WD_UA = "Mozilla/5.0 (compatible; pl-watch/0.1; +https://github.com/uraura868-del/pl-watch)"
CAREER_TTL_DAYS = 30


def sparql(query: str) -> list[dict]:
    url = WD_SPARQL + "?format=json&query=" + urllib.parse.quote(query)
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": WD_UA, "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8")).get("results", {}).get("bindings", [])
        except urllib.error.HTTPError as e:
            log(f"  wikidata HTTP {e.code}")
            if e.code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            return []
        except Exception as e:  # noqa: BLE001
            log(f"  wikidata error {e}")
            time.sleep(3)
    return []


def _v(b: dict, k: str):
    return (b.get(k) or {}).get("value")


def wd_find_player(name: str, dob: str) -> str | None:
    """生年月日が一致するサッカー選手の中から、名前が合う人物の QID を返す"""
    q = f'''
    SELECT ?p ?pLabel (GROUP_CONCAT(DISTINCT ?alias; separator="|") AS ?aliases) WHERE {{
      ?p wdt:P569 "{dob}T00:00:00Z"^^xsd:dateTime .
      ?p wdt:P106 wd:Q937857 .
      OPTIONAL {{ ?p skos:altLabel ?alias FILTER(lang(?alias) IN ("en", "mul")) }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
    }} GROUP BY ?p ?pLabel'''
    rows = sparql(q)
    if not rows:
        return None
    n_tokens = set(norm_name(name).split())
    last = norm_name(name).split()[-1] if n_tokens else ""
    best, best_score = None, 0
    for b in rows:
        labels = [_v(b, "pLabel") or ""] + (_v(b, "aliases") or "").split("|")
        score = 0
        for lab in labels:
            toks = set(norm_name(lab).split())
            if not toks:
                continue
            if norm_name(lab) == norm_name(name):
                score = max(score, 3)
            elif last and last in toks:
                score = max(score, 2)
            elif toks & n_tokens:
                score = max(score, 1)
        if score > best_score:
            best, best_score = _v(b, "p"), score
    if best_score == 0 and len(rows) == 1:
        # 同じ生年月日のサッカー選手が1人しかいなければ、その人物とみなす
        best = _v(rows[0], "p")
    return best.rsplit("/", 1)[-1] if best else None


def wd_career(qid: str) -> list[dict]:
    q = f'''
    SELECT ?club ?clubEn ?clubJa ?start ?end ?apps ?acqLabel ?isNat WHERE {{
      wd:{qid} p:P54 ?s . ?s ps:P54 ?club .
      OPTIONAL {{ ?s pq:P580 ?start }}
      OPTIONAL {{ ?s pq:P582 ?end }}
      OPTIONAL {{ ?s pq:P1350 ?apps }}
      OPTIONAL {{ ?s pq:P1642 ?acq . ?acq rdfs:label ?acqLabel FILTER(lang(?acqLabel) = "en") }}
      OPTIONAL {{ ?club rdfs:label ?clubJa FILTER(lang(?clubJa) = "ja") }}
      OPTIONAL {{ ?club rdfs:label ?clubEn FILTER(lang(?clubEn) = "en") }}
      OPTIONAL {{ ?club rdfs:label ?clubMul FILTER(lang(?clubMul) = "mul") }}
      BIND(EXISTS {{ ?club wdt:P31/wdt:P279* wd:Q6979593 }} AS ?isNat)
    }}'''
    out: dict[tuple, dict] = {}
    for b in sparql(q):
        en = _v(b, "clubEn") or _v(b, "clubMul") or ""
        ja = _v(b, "clubJa") or ""
        def year(v: str | None) -> str | None:
            # 「不明な値」は genid の URL で返ってくるので捨てる
            if not v or v.startswith("http"):
                return None
            return v[:4]
        start = year(_v(b, "start"))
        end = year(_v(b, "end"))
        key = (en, start, end)
        if key in out:
            continue
        apps = _v(b, "apps")
        try:
            apps_n = int(float(apps)) if apps not in (None, "") else None
        except (TypeError, ValueError):
            apps_n = None  # 「不明な値」(genid URL) など
        acq = (_v(b, "acqLabel") or "").lower()
        youth = bool(re.search(r"\b(u-?\d{2}|under-?\d{2}|youth|juniors?|academy|reserves?|b team|ii)\b", en.lower()))
        out[key] = {
            "club": ja or en,
            "clubEn": en,
            "start": start,
            "end": end,
            "apps": apps_n,
            "national": _v(b, "isNat") == "true",
            "youth": youth,
            "loan": "loan" in acq,
        }
    rows = list(out.values())
    rows.sort(key=lambda r: (r["start"] or "0000", r["end"] or "9999"))
    return rows


# ---------------------------------------------------------------- クラブのエンブレム (ESPN 検索)
ESPN_SEARCH = "https://site.web.api.espn.com/apis/common/v3/search?limit=6&type=team&sport=soccer&query="
LOGO_CACHE = DATA / "club-logos.json"
NAT_WORDS = re.compile(r"\b(men's|women's|national|association|football|soccer|team|olympic|under-?\d{1,2}|u-?\d{1,2})\b", re.IGNORECASE)
# 正規化後のトークンから落とす語（クラブ略号・一般語）。2文字以下と数字だけのトークンも落とす
CLUB_NOISE_TOKENS = {"fc", "afc", "cf", "sc", "ac", "as", "us", "ss", "bc", "kv", "cp", "ssd", "asd", "calcio", "club", "clube",
                     "de", "da", "do", "futebol", "voetbal", "sport", "sporting", "football", "association", "athletic", "the"}


def club_tokens(name: str) -> list[str]:
    out = []
    for t in norm_name(name).split():
        if t in CLUB_NOISE_TOKENS or t.isdigit() or len(t) <= 2:
            continue
        out.append(t)
    return out


def logo_query_name(row: dict) -> str:
    """経歴の1行から ESPN 検索に使う名前を作る（代表は国名、クラブは略号を落とした名前）"""
    en = row.get("clubEn") or row.get("club") or ""
    if row.get("national"):
        # "Portugal national under-19 football team" → "Portugal"
        s = NAT_WORDS.sub(" ", en)
        return re.sub(r"\s+", " ", s).strip(" -")
    toks = club_tokens(en)
    return " ".join(toks) if toks else en


def espn_team_logo(name: str, cache: dict[str, str | None], national: bool = False) -> str | None:
    key = ("nat:" if national else "club:") + norm_name(name)
    if key in cache:
        return cache[key]
    d = get_json(ESPN_SEARCH + urllib.parse.quote(name))
    items = [i for i in (d or {}).get("items", []) if i.get("type") == "team"]
    want = set(club_tokens(name)) or set(norm_name(name).split())
    best, best_score = None, 0
    for it in items:
        cand = club_tokens(it.get("displayName") or "") or norm_name(it.get("displayName") or "").split()
        cand_set = set(cand)
        if not cand_set or not want:
            continue
        overlap = len(want & cand_set)
        score = overlap * 2 - abs(len(cand_set) - len(want))
        if national and norm_name(it.get("displayName") or "") == norm_name(name):
            score += 5
        if overlap and score > best_score:
            best, best_score = it, score
    logo = None
    if best:
        logos = best.get("logos") or []
        logo = next((l.get("href") for l in logos if "default" in (l.get("rel") or [])), None) or (logos[0].get("href") if logos else None)
        if not logo and best.get("id"):
            logo = ESPN_LOGO.format(id=best["id"])
    cache[key] = logo
    time.sleep(0.3)
    return logo


def attach_logos(cache_players: dict) -> int:
    """careers.json の各行に logo を付ける（未処理の行だけ）。結果は data/club-logos.json に共有キャッシュ"""
    logo_cache: dict[str, str | None] = {}
    if LOGO_CACHE.exists():
        try:
            logo_cache = json.loads(LOGO_CACHE.read_text(encoding="utf-8")).get("logos", {})
        except Exception:  # noqa: BLE001
            logo_cache = {}
    n = 0
    for entry in cache_players.values():
        for row in entry.get("career", []):
            if "logo" in row:
                continue
            q = logo_query_name(row)
            row["logo"] = espn_team_logo(q, logo_cache, national=row.get("national", False)) if q else None
            n += 1
    write_json(LOGO_CACHE, {"updatedAt": iso(NOW), "logos": logo_cache})
    return n


def update_careers(path: Path, roster: list[dict]) -> None:
    """選手の経歴を Wikidata から取得し path にキャッシュ（自チーム: data/<team>/careers.json、相手: data/opponents/careers.json）"""
    cache: dict = {}
    if path.exists():
        try:
            cache = json.loads(path.read_text(encoding="utf-8")).get("players", {})
        except Exception:  # noqa: BLE001
            cache = {}
    fetched = 0
    for p in roster:
        pid = p["id"]
        old = cache.get(pid)
        if old and old.get("fetchedAt"):
            age = NOW - datetime.strptime(old["fetchedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            # 見つかった人は30日、見つからなかった人は1日でリトライ（429 等の一時失敗に備える）
            if age < timedelta(days=CAREER_TTL_DAYS if old.get("qid") else 1):
                continue
        if not p.get("dob"):
            cache[pid] = {"name": p["name"], "qid": None, "career": [], "fetchedAt": iso(NOW)}
            continue
        try:
            qid = (old or {}).get("qid") or wd_find_player(p["name"], p["dob"])
            career = wd_career(qid) if qid else []
        except Exception as e:  # noqa: BLE001
            log(f"  経歴取得に失敗 ({p['name']}): {e!r}")
            continue
        cache[pid] = {"name": p["name"], "qid": qid, "career": career, "fetchedAt": iso(NOW)}
        fetched += 1
        if fetched % 10 == 0:
            write_json(path, {"updatedAt": iso(NOW), "players": cache})  # 途中経過を保存
        time.sleep(2.0)
    try:
        n_logo = attach_logos(cache)
    except Exception as e:  # noqa: BLE001
        n_logo = 0
        log(f"  エンブレム取得に失敗（スキップ）: {e!r}")
    write_json(path, {"updatedAt": iso(NOW), "players": cache})
    found = sum(1 for v in cache.values() if v.get("qid"))
    with_logo = sum(1 for v in cache.values() for r in v.get("career", []) if r.get("logo"))
    total_rows = sum(len(v.get("career", [])) for v in cache.values())
    log(f"  careers: {found}/{len(cache)} 人分（今回取得 {fetched} 人）、エンブレム {with_logo}/{total_rows} 行（今回検索 {n_logo} 行）")


# ---------------------------------------------------------------- 欠場理由 (Transfermarkt)
REASON_JA = [  # 部分一致。上から順に評価
    ("cruciate", "十字靭帯損傷"), ("achilles", "アキレス腱の負傷"), ("hamstring", "ハムストリング負傷"),
    ("groin", "鼠径部の負傷"), ("calf", "ふくらはぎの負傷"), ("thigh", "太ももの負傷"), ("adductor", "内転筋の負傷"),
    ("knee", "膝の負傷"), ("ankle", "足首の負傷"), ("foot", "足の負傷"), ("toe", "つま先の負傷"), ("hip", "股関節の負傷"),
    ("back", "背中の負傷"), ("shoulder", "肩の負傷"), ("arm", "腕の負傷"), ("hand", "手の負傷"), ("wrist", "手首の負傷"),
    ("rib", "肋骨の負傷"), ("head", "頭部の負傷"), ("concussion", "脳震盪"), ("facial", "顔面の負傷"),
    ("muscle", "筋肉系の負傷"), ("muscular", "筋肉系の負傷"), ("ligament", "靭帯損傷"), ("tendon", "腱の負傷"), ("fracture", "骨折"),
    ("bruise", "打撲"), ("knock", "打撲"), ("strain", "肉離れ"), ("tear", "断裂"),
    ("illness", "体調不良"), ("ill", "体調不良"), ("virus", "体調不良"), ("fever", "体調不良"), ("flu", "体調不良"),
    ("yellow card", "累積警告"), ("red card", "退場による出場停止"), ("suspen", "出場停止"), ("ban", "出場停止"),
    ("surgery", "手術"), ("fitness", "コンディション不良"), ("rest", "休養"), ("unknown", "負傷（詳細不明）"),
]


def reason_ja(s: str) -> str:
    low = (s or "").lower()
    for k, v in REASON_JA:
        if k in low:
            return v
    return s or ""


def tm_fetch(url: str) -> str | None:
    """Transfermarkt のページを取る（空白をまとめた HTML）。失敗なら None"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9",
                                                   "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return re.sub(r"\s+", " ", r.read().decode("utf-8", "ignore"))
    except Exception as e:  # noqa: BLE001
        log(f"  transfermarkt 取得失敗: {e} ({url[:60]})")
        return None


# ---------------------------------------------------------------- 選手写真 (Transfermarkt)
TM_PHOTOS = DATA / "tm-photos.json"
TM_PHOTO_TTL_DAYS = 7
TM_MAX_NEW_CLUBS_PER_RUN = 6  # 1回の更新で新しく読みに行くクラブ数の上限（負荷を抑える）
_tm_cache: dict = {}


def tm_cache_load() -> None:
    global _tm_cache
    _tm_cache = {}
    if TM_PHOTOS.exists():
        try:
            _tm_cache = json.loads(TM_PHOTOS.read_text(encoding="utf-8")).get("clubs", {})
        except Exception:  # noqa: BLE001
            _tm_cache = {}
    # ID が引けなかったクラブは次回また試す（キャッシュしない）
    _tm_cache = {k: v for k, v in _tm_cache.items() if v.get("id")}


def wd_tm_club(name: str) -> dict | None:
    """Wikidata でクラブを検索し、Transfermarkt のクラブID (P7223) を引く。GitHub からでも安定して使える"""
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(
            "https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&language=en&type=item&limit=7&search=" + urllib.parse.quote(name),
            headers={"User-Agent": WD_UA}), timeout=30).read())
    except Exception as e:  # noqa: BLE001
        log(f"  wikidata search error {e}")
        return None
    ids = [s["id"] for s in d.get("search", [])]
    if not ids:
        return None
    rows = sparql("SELECT ?c ?cLabel ?tm WHERE { VALUES ?c { " + " ".join(f"wd:{i}" for i in ids) +
                  " } ?c wdt:P7223 ?tm . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en,mul\". } }")
    found = {(_v(b, "c") or "").rsplit("/", 1)[-1]: (_v(b, "cLabel"), _v(b, "tm")) for b in rows}
    for i in ids:  # 検索の並び（関連度順）で最初に TM ID を持つもの
        if i in found and (found[i][1] or "").isdigit():
            return {"id": int(found[i][1]), "slug": "club", "name": found[i][0] or name}
    return None


def tm_cache_save() -> None:
    write_json(TM_PHOTOS, {"updatedAt": iso(NOW), "clubs": _tm_cache})


def tm_search_club(name: str) -> dict | None:
    """クイック検索の「Clubs」欄から、名前が最も近いクラブを選ぶ"""
    h = tm_fetch("https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche?query=" + urllib.parse.quote(name))
    if not h:
        return None
    want = set(club_tokens(name)) or set(norm_name(name).split())
    best, best_score = None, 0
    for box in re.split(r'<div class="box">', h):
        if "Clubs" not in box[:600]:
            continue
        for title, href, cid in re.findall(r'<td class="hauptlink">\s*<a title="([^"]+)" href="(/[^"]+/startseite/verein/(\d+))', box):
            cand = set(club_tokens(html.unescape(title))) or set(norm_name(title).split())
            overlap = len(want & cand)
            score = overlap * 2 - abs(len(cand) - len(want))
            if overlap and score > best_score:
                slug = href.split("/")[1]
                best, best_score = {"id": int(cid), "slug": slug, "name": html.unescape(title)}, score
        break
    return best


def tm_squad_photos(slug: str, tm_id: int) -> dict[str, str] | None:
    """クラブの選手一覧から 正規化名 → 顔写真URL"""
    h = tm_fetch(f"https://www.transfermarkt.com/{slug}/kader/verein/{tm_id}/plus/1")
    if not h:
        return None
    out: dict[str, str] = {}
    for url, title in re.findall(r'data-src="(https://img\.a\.transfermarkt\.technology/portrait/[^"]+)" title="([^"]+)"', h):
        if "default" in url:
            continue
        name = html.unescape(title)
        url = url.replace("/portrait/medium/", "/portrait/header/")  # medium は 100px で粗いので一回り大きいものを使う
        out[norm_name(name)] = url
        ln = norm_name(name).split()[-1] if norm_name(name) else ""
        if ln and ln not in out:
            out[ln] = url
    return out


_tm_new_clubs = 0


def tm_club_photos(club_name: str, cfg: dict | None = None) -> dict[str, str]:
    """クラブ名（ESPN 表記）から写真辞書を返す。7日キャッシュ。cfg に tmTeamId があれば検索しない"""
    global _tm_new_clubs
    key = norm_name(club_name)
    entry = _tm_cache.get(key)
    if entry and entry.get("fetchedAt"):
        age = NOW - datetime.strptime(entry["fetchedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if age < timedelta(days=TM_PHOTO_TTL_DAYS) or _tm_new_clubs >= TM_MAX_NEW_CLUBS_PER_RUN:
            return entry.get("players", {})
    if _tm_new_clubs >= TM_MAX_NEW_CLUBS_PER_RUN:
        return (entry or {}).get("players", {})
    ident = None
    if cfg and cfg.get("tmTeamId") and cfg.get("tmSlug"):
        ident = {"id": int(cfg["tmTeamId"]), "slug": cfg["tmSlug"], "name": cfg.get("name")}
    elif entry and entry.get("id"):
        ident = {"id": entry["id"], "slug": entry["slug"], "name": entry.get("name")}
    else:
        ident = wd_tm_club(club_name)  # まず Wikidata（GitHub からも安定）、だめなら Transfermarkt 検索
        if not ident:
            ident = tm_search_club(club_name)
        time.sleep(1.0)
    _tm_new_clubs += 1
    if not ident:
        _tm_cache[key] = {"id": None, "slug": None, "name": None, "fetchedAt": iso(NOW), "players": {}}
        log(f"  tm-photos: クラブが見つからず ({club_name})")
        return {}
    players = tm_squad_photos(ident["slug"], ident["id"])
    time.sleep(1.0)
    if players is None:
        return (entry or {}).get("players", {})
    _tm_cache[key] = {**ident, "fetchedAt": iso(NOW), "players": players}
    log(f"  tm-photos: {ident['name']} {len([k for k in players if ' ' in k])} 人")
    return players


def tm_photo_for(name: str, players: dict[str, str]) -> str | None:
    n = norm_name(name)
    if n in players:
        return players[n]
    parts = n.split()
    return players.get(parts[-1]) if parts else None


def tm_injuries(slug: str, tm_id: int) -> list[dict] | None:
    """Transfermarkt の「負傷者・出場停止」ページを読む。取得できなければ None"""
    h = tm_fetch(f"https://www.transfermarkt.com/{slug}/sperrenundverletzungen/verein/{tm_id}")
    if h is None:
        return None
    out = []
    chunks = re.split(r'<tr class="(?:odd|even)">', h)[1:]
    for ch in chunks:
        name_m = re.search(r'<a [^>]*title="([^"]+)"[^>]*href="/[^"]*/profil/spieler/\d+"', ch)
        if not name_m:
            continue
        outer = re.sub(r'<table class="inline-table">.*?</table>', "", ch, count=1, flags=re.S)
        row = outer.split("</tr>")[0]
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 4:
            continue
        reason = cells[2]
        since = _tm_date(cells[3])
        until = _tm_date(cells[4]) if len(cells) > 4 else None
        low = reason.lower()
        kind = "出場停止" if any(w in low for w in ("suspen", "ban", "card")) else "負傷"
        out.append({"name": html.unescape(name_m.group(1)), "reason": reason, "reasonJa": reason_ja(reason),
                    "type": kind, "since": since, "until": until})
    return out


def _tm_date(s: str) -> str | None:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def update_injuries(tdir: Path, team: dict) -> None:
    """負傷・出場停止の履歴を data/<team>/injuries.json に溜める（消えた項目は復帰扱いで閉じる）"""
    if not team.get("tmTeamId") or not team.get("tmSlug"):
        return
    path = tdir / "injuries.json"
    hist: list[dict] = []
    if path.exists():
        try:
            hist = json.loads(path.read_text(encoding="utf-8")).get("players", [])
        except Exception:  # noqa: BLE001
            hist = []
    current = tm_injuries(team["tmSlug"], int(team["tmTeamId"]))
    today = NOW.strftime("%Y-%m-%d")
    if current is None:
        log("  injuries: 取得できず（前回の履歴を維持）")
        write_json(path, {"updatedAt": iso(NOW), "fetchedOk": False, "players": hist})
        return
    by_key = {(norm_name(h["name"]), h.get("since")): h for h in hist}
    cur_keys = set()
    for c in current:
        k = (norm_name(c["name"]), c.get("since"))
        cur_keys.add(k)
        if k in by_key:
            e = by_key[k]
            e.update({"reason": c["reason"], "reasonJa": c["reasonJa"], "type": c["type"], "until": c["until"], "lastSeen": today, "active": True})
        else:
            hist.append({**c, "firstSeen": today, "lastSeen": today, "active": True})
    for h in hist:
        k = (norm_name(h["name"]), h.get("since"))
        if k not in cur_keys and h.get("active", True):
            # ページから消えた＝復帰したとみなし、最後に見た日で閉じる
            h["active"] = False
            if not h.get("until") or h["until"] > today:
                h["until"] = h.get("lastSeen") or today
    hist.sort(key=lambda h: (h.get("since") or "", h["name"]))
    write_json(path, {"updatedAt": iso(NOW), "fetchedOk": True, "players": hist})
    log(f"  injuries: 現在 {len(current)} 件（{', '.join(c['name'] + '=' + c['reasonJa'] for c in current[:4])}）、履歴 {len(hist)} 件")


# ---------------------------------------------------------------- カレンダー (.ics)
def write_ics(tdir: Path, team: dict, fixtures: list[dict]) -> None:
    """Google カレンダー等で購読できる日程ファイル。キックオフ時刻だけで、結果は含めない"""
    def esc_ics(s: str) -> str:
        return (s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//pl-watch//JP", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{esc_ics(team.get('shortName') or team['name'])} 日程（PL Watch）", "X-WR-TIMEZONE:Asia/Tokyo"]
    for f in fixtures:
        if f.get("status") == "postponed":
            continue
        dt = datetime.strptime(f["date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        start = dt.strftime("%Y%m%dT%H%M%SZ")
        end = (dt + timedelta(hours=2)).strftime("%Y%m%dT%H%M%SZ")
        ha = "H" if f.get("isHome") else "A"
        title = f"{team.get('shortName') or team['name']} vs {f['opponent']['name']} ({f.get('compShort') or f.get('competition', '')}, {ha})"
        lines += ["BEGIN:VEVENT", f"UID:{f['eventId']}@pl-watch", f"DTSTAMP:{NOW.strftime('%Y%m%dT%H%M%SZ')}",
                  f"DTSTART:{start}", f"DTEND:{end}", f"SUMMARY:{esc_ics(title)}",
                  f"DESCRIPTION:{esc_ics((f.get('competition') or '') + '。スタメンはキックオフ約1時間前から PL Watch で確認できます。')}",
                  f"LOCATION:{esc_ics(f.get('venue') or '')}",
                  "BEGIN:VALARM", "TRIGGER:-PT60M", "ACTION:DISPLAY", "DESCRIPTION:スタメン公開のころです", "END:VALARM",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    (tdir / "fixtures.ics").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")


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


def espn_summary(league: str, event_id: str) -> dict | None:
    return get_json(f"{ESPN}/{league}/summary?event={event_id}")


SHOT_TYPES = {"Shot On Target": "onTarget", "Shot Off Target": "offTarget", "Shot Blocked": "blocked"}
BOX_STATS = {  # 試合終了時のみ（ESPN boxscore）。得点やセーブ数に関わる項目は入れない
    "possessionPct": "possession", "totalPasses": "passes", "accuratePasses": "passesAccurate", "passPct": "passAcc",
    "totalTackles": "tackles", "effectiveTackles": "tacklesWon", "interceptions": "interceptions",
    "totalClearance": "clearances", "totalCrosses": "crosses", "accurateCrosses": "crossesAccurate",
}
COUNT_KEYS = ("shots", "onTarget", "offTarget", "blocked", "corners", "fouls", "offsides", "yellow", "red")


def stats_from_summary(d: dict, our_id: str, f: dict) -> dict | None:
    """実況(commentary)を前半/全体で集計し、boxscore の集計値を試合終了分に足す。得点・PK・セーブは一切含めない。"""
    teams = (d.get("boxscore") or {}).get("teams") or []
    if not teams:
        return None
    name_to_side: dict[str, str] = {}
    for t in teams:
        tt = t.get("team") or {}
        name_to_side[tt.get("displayName") or ""] = "us" if str(tt.get("id")) == our_id else "opp"

    def empty() -> dict:
        return {k: 0 for k in COUNT_KEYS}

    ht = {"us": empty(), "opp": empty()}
    ft = {"us": empty(), "opp": empty()}
    com = d.get("commentary") or []
    got_ht = False
    for c in com:
        p = c.get("play") or {}
        ttxt = ((p.get("type") or {}).get("text") or "")
        low = ttxt.lower()
        period_no = ((p.get("period") or {}).get("number")) or 0
        if ttxt == "Halftime" or period_no >= 2:
            got_ht = True  # 後半の実況があれば前半は完結している
        if not ttxt or "goal" in low or "penalty" in low:
            continue
        side = name_to_side.get(((p.get("team") or {}).get("displayName") or ""))
        if not side:
            continue
        period = ((p.get("period") or {}).get("number")) or 0
        key = SHOT_TYPES.get(ttxt)
        if not key:
            if ttxt == "Corner Awarded":
                key = "corners"
            elif ttxt == "Foul":
                key = "fouls"
            elif ttxt == "Offside":
                key = "offsides"
            elif "yellow" in low:
                key = "yellow"
            elif "red" in low:
                key = "red"
        if not key:
            continue
        for bucket in ([ft, ht] if period == 1 else [ft]):
            bucket[side][key] += 1
            if key in ("onTarget", "offTarget", "blocked"):
                bucket[side]["shots"] += 1
    if not com:
        for side in ("us", "opp"):
            for k in COUNT_KEYS:
                ft[side][k] = None
    for t in teams:
        side = "us" if str((t.get("team") or {}).get("id")) == our_id else "opp"
        for s in t.get("statistics") or []:
            k = BOX_STATS.get(s.get("name"))
            if k:
                ft[side][k] = s.get("displayValue")
    return {
        "eventId": f["eventId"],
        "date": f["date"],
        "opponent": {"name": f["opponent"]["name"], "abbr": f["opponent"]["abbr"]},
        "ht": ht if (com and got_ht) else None,
        "ft": ft,
        "source": "ESPN",
        "note": "得点・PK・セーブ数は含めていません。シュート数はゴールになったものを除いた数です。",
    }


def result_from_summary(d: dict, our_id: str, f: dict) -> dict | None:
    """スコア・得点者・退場者。results/ にだけ書く（ボタンを押した時だけ読まれる）"""
    comps = (((d.get("header") or {}).get("competitions") or [{}])[0].get("competitors")) or []
    us = next((c for c in comps if str((c.get("team") or {}).get("id")) == our_id), None)
    opp = next((c for c in comps if c is not us), None)
    if not us or not opp or us.get("score") in (None, "") or opp.get("score") in (None, ""):
        return None
    goals, reds = [], []
    for e in d.get("keyEvents") or []:
        t = ((e.get("type") or {}).get("text") or "")
        low = t.lower()
        side = "us" if str((e.get("team") or {}).get("id")) == our_id else "opp"
        minute = ((e.get("clock") or {}).get("displayValue") or "")
        names = [((p.get("athlete") or {}).get("displayName")) for p in (e.get("participants") or [])]
        if e.get("scoringPlay") or "goal" in low:
            if e.get("shootout") or "shootout" in low or "missed" in low or "saved" in low:
                continue
            kind = "og" if ("own" in low or e.get("ownGoal")) else ("pen" if ("penalty" in low or e.get("penaltyKick")) else "goal")
            goals.append({"side": side, "scorer": names[0] if names else None,
                          "assist": names[1] if (len(names) > 1 and kind == "goal") else None,
                          "minute": minute, "kind": kind})
        elif "red" in low:
            reds.append({"side": side, "name": names[0] if names else None, "minute": minute})
    return {
        "eventId": f["eventId"], "date": f["date"],
        "opponent": {"name": f["opponent"]["name"], "abbr": f["opponent"]["abbr"]},
        "isHome": f["isHome"],
        "score": {"us": int(us["score"]), "opp": int(opp["score"])},
        "goals": goals, "redCards": reds, "source": "ESPN",
    }


# ---------------------------------------------------------------- プレー動画 (YouTube Data API)
YT_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
VIDEO_TTL_DAYS = 30
VIDEOS_PER_PLAYER = 3
# ネタバレになりそうなタイトルを除外する（完全ではない）
SPOILER_TITLE = re.compile(
    r"\bvs\.?\b|\bv\b|\d\s*[-–:]\s*\d|goal|highlight|ハイライト|ゴール|\bwin\b|\bwon\b|defeat|\bloss\b|\blose\b|\bdraw\b|derby|"
    r"\bmatch\b|result|reaction|press|interview|injur|red card|penalt|hat-?trick|final|cup|vs\b|試合|得点|勝|負|速報",
    re.IGNORECASE,
)


def yt_search(query: str) -> list[dict] | None:
    url = ("https://www.googleapis.com/youtube/v3/search?part=snippet&type=video&videoEmbeddable=true&maxResults=12"
           f"&safeSearch=strict&q={urllib.parse.quote(query)}&key={YT_KEY}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:200]
        log(f"  youtube HTTP {e.code}: {body}")
        return None if e.code in (403, 429) else []
    except Exception as e:  # noqa: BLE001
        log(f"  youtube error {e}")
        return []
    out = []
    for it in d.get("items", []):
        vid = (it.get("id") or {}).get("videoId")
        sn = it.get("snippet") or {}
        title = html.unescape(sn.get("title") or "")
        if not vid or SPOILER_TITLE.search(title):
            continue
        out.append({"id": vid, "title": title, "channel": sn.get("channelTitle"), "publishedAt": (sn.get("publishedAt") or "")[:10]})
        if len(out) >= VIDEOS_PER_PLAYER:
            break
    return out


def update_videos(path: Path, roster: list[dict]) -> None:
    cache: dict = {}
    if path.exists():
        try:
            cache = json.loads(path.read_text(encoding="utf-8")).get("players", {})
        except Exception:  # noqa: BLE001
            cache = {}
    if not YT_KEY:
        log("  videos: YOUTUBE_API_KEY が未設定のためスキップ（YouTube 検索リンクのみ表示されます）")
        # キーの無い環境（ローカル）で走っても、GitHub 側で取得済みのキャッシュは消さない
        write_json(path, {"updatedAt": iso(NOW), "enabled": bool(cache), "players": cache})
        return
    fetched = 0
    for p in roster:
        old = cache.get(p["id"])
        if old and old.get("fetchedAt"):
            age = NOW - datetime.strptime(old["fetchedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if age < timedelta(days=VIDEO_TTL_DAYS):
                continue
        q = f'{p["name"]} skills'
        vids = yt_search(q)
        if vids is None:  # クォータ超過など → 今回はここで打ち切り
            log("  videos: クォータ超過または拒否。次回に持ち越し")
            break
        cache[p["id"]] = {"name": p["name"], "query": q, "videos": vids, "fetchedAt": iso(NOW)}
        fetched += 1
        time.sleep(0.5)
    write_json(path, {"updatedAt": iso(NOW), "enabled": True, "players": cache})
    log(f"  videos: {sum(1 for v in cache.values() if v.get('videos'))}/{len(roster)} 人分（今回検索 {fetched} 人）")


def lineups_from_summary(d: dict | None) -> dict[str, dict] | None:
    """summary → {teamId: {formation, players:[{id,name,jersey,pos,starter,place}]}}"""
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
    own_tm = tm_club_photos(team["name"], team)  # Transfermarkt の写真（現所属のもの）を優先
    for p in roster:
        q = find_in_index(p["name"], own_index)
        if not q and p["jersey"]:
            q = next((q for q in plsq if str(q["jersey"]) == str(p["jersey"])), None)
        if not q:
            q = find_in_index(p["name"], photo_index)
        bio = bio_of(q) if q else {}
        espn_photo = p.get("photo")
        p.update(bio)
        p["photo"] = tm_photo_for(p["name"], own_tm) or bio.get("photo") or espn_photo
    write_json(tdir / "roster.json", {"updatedAt": iso(NOW), "players": roster})
    log(f"  roster: {len(roster)} 人（写真あり {sum(1 for p in roster if p['photo'])} 人、"
        f"プロフィールあり {sum(1 for p in roster if p.get('dob'))} 人）")
    try:
        update_careers(tdir / "careers.json", roster)
    except Exception as e:  # noqa: BLE001
        log(f"  careers の更新に失敗（スキップ）: {e!r}")
    try:
        update_videos(tdir / "videos.json", roster)
    except Exception as e:  # noqa: BLE001
        log(f"  videos の更新に失敗（スキップ）: {e!r}")

    # --- 欠場理由（Transfermarkt）
    try:
        update_injuries(tdir, team)
    except Exception as e:  # noqa: BLE001
        log(f"  injuries の更新に失敗（スキップ）: {e!r}")

    # --- 日程（リーグ戦＋カップ戦）
    comps = team.get("competitions") or [{"league": league, "name": team.get("leagueName", league), "short": ""}]
    fixtures: list[dict] = []
    seen_ids: set[str] = set()
    for comp in comps:
        for e in espn_schedule(comp["league"], espn_id):
            f = fixture_from_event(e, espn_id, comp.get("name") or comp["league"])
            if not f or f["eventId"] in seen_ids:
                continue
            f["league"] = comp["league"]
            f["compShort"] = comp.get("short") or ""
            seen_ids.add(f["eventId"])
            fixtures.append(f)
        time.sleep(0.3)
    fixtures.sort(key=lambda f: f["date"])

    # --- スタメン取得対象
    mdir = tdir / "matches"
    mdir.mkdir(parents=True, exist_ok=True)
    manual = load_manual_absences(tid)
    roster_by_id = {p["id"]: p for p in roster}

    sdir = tdir / "stats"
    sdir.mkdir(parents=True, exist_ok=True)
    rdir = tdir / "results"
    rdir.mkdir(parents=True, exist_ok=True)
    for f in fixtures:
        mpath = mdir / f"{f['eventId']}.json"
        spath = sdir / f"{f['eventId']}.json"
        rpath = rdir / f"{f['eventId']}.json"
        existing = None
        if mpath.exists():
            try:
                existing = json.loads(mpath.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                existing = None
        f["hasStats"] = spath.exists()
        f["hasResult"] = rpath.exists()
        kickoff = datetime.strptime(f["date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        need_lineup = not (existing and existing.get("final")) and (
            f["status"] == "played" or (f["status"] == "scheduled" and kickoff - NOW <= timedelta(hours=3)))
        is_final = f["status"] == "played" and bool(f.get("final"))
        need_stats = is_final and not spath.exists()
        need_result = is_final and not rpath.exists()
        if not need_lineup and not need_stats and not need_result:
            f["hasLineup"] = bool(existing)
            continue
        summary = espn_summary(f.get("league") or league, f["eventId"])
        time.sleep(0.5)
        if need_result and summary:
            try:
                res = result_from_summary(summary, espn_id, f)
            except Exception as e:  # noqa: BLE001
                res = None
                log(f"  result の抽出に失敗: {e!r}")
            if res:
                write_json_unchecked(rpath, res)
                f["hasResult"] = True
                log(f"  result: {f['date'][:10]} vs {f['opponent']['name']} を results/ に保存")
        if need_stats and summary:
            try:
                st = stats_from_summary(summary, espn_id, f)
            except Exception as e:  # noqa: BLE001
                st = None
                log(f"  stats の集計に失敗: {e!r}")
            if st:
                write_json(spath, st)
                f["hasStats"] = True
                log(f"  stats: {f['date'][:10]} vs {f['opponent']['name']}（HT {'あり' if st['ht'] else 'なし'}）")
        if not need_lineup:
            f["hasLineup"] = bool(existing)
            continue
        lineups = lineups_from_summary(summary)
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

    # --- 写真の更新（自チームは名鑑から、相手チームは Transfermarkt から）を保存済みの試合ファイルに反映
    try:
        refresh_match_photos(mdir, fixtures, roster_by_id, photo_index)
    except Exception as e:  # noqa: BLE001
        log(f"  写真の反映に失敗（スキップ）: {e!r}")

    for f in fixtures:
        f.pop("final", None)
    write_json(tdir / "fixtures.json", {"updatedAt": iso(NOW), "fixtures": fixtures})
    try:
        write_ics(tdir, team, fixtures)
    except Exception as e:  # noqa: BLE001
        log(f"  ics の生成に失敗（スキップ）: {e!r}")

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


def refresh_match_photos(mdir: Path, fixtures: list[dict], roster_by_id: dict, photo_index: dict) -> None:
    """試合ファイル内の選手写真を最新に置き換える（自チーム: 名鑑、相手: Transfermarkt → PL公式 の順）"""
    # 直近の試合から順に相手クラブの写真を用意（1回の更新で読むクラブ数には上限あり）
    ordered = sorted((f for f in fixtures if f.get("hasLineup")), key=lambda f: abs((datetime.strptime(f["date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) - NOW).total_seconds()))
    changed = 0
    for f in ordered:
        mp = mdir / f"{f['eventId']}.json"
        if not mp.exists():
            continue
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        before = json.dumps(m, ensure_ascii=False, sort_keys=True)
        for p in ((m.get("team") or {}).get("starters") or []) + ((m.get("team") or {}).get("bench") or []) + (m.get("absentees") or []):
            rp = roster_by_id.get(p.get("id"))
            if rp and rp.get("photo"):
                p["photo"] = rp["photo"]
        opp = m.get("opponent") or {}
        if opp.get("starters"):
            tm = tm_club_photos(opp.get("name") or f["opponent"]["name"])
            for p in (opp.get("starters") or []) + (opp.get("bench") or []):
                photo = tm_photo_for(p.get("name") or "", tm) or find_photo(p.get("name") or "", photo_index) or p.get("photo")
                if photo:
                    p["photo"] = photo
        if json.dumps(m, ensure_ascii=False, sort_keys=True) != before:
            write_json(mp, m)
            changed += 1
    if changed:
        log(f"  写真を更新した試合ファイル: {changed}")


def collect_opponent_players(teams: list[dict], photo_index: dict[str, dict]) -> list[dict]:
    """保存済みの試合ファイルから、相手チームのスタメン・ベンチに入った選手を集める（チーム横断で共有）"""
    players: dict[str, dict] = {}
    for team in teams:
        mdir = DATA / team["id"] / "matches"
        if not mdir.exists():
            continue
        for mp in sorted(mdir.glob("*.json")):
            try:
                m = json.loads(mp.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            o = m.get("opponent") or {}
            # 今日からの近さ（日数）。直近の試合の相手を先に取る
            try:
                mdate = datetime.strptime(m["date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                dist = abs((mdate - NOW).total_seconds()) / 86400
            except Exception:  # noqa: BLE001
                dist = 9999
            for p in (o.get("starters") or []) + (o.get("bench") or []):
                if p.get("id") in players:
                    players[p["id"]]["dist"] = min(players[p["id"]]["dist"], dist)
                    continue
                rec = find_in_index(p.get("name") or "", photo_index)
                players[p["id"]] = {"id": p["id"], "name": p.get("name"), "dob": (rec or {}).get("dob"), "dist": dist}
    return sorted(players.values(), key=lambda p: (p["dist"], p["name"] or ""))


def main() -> int:
    cfg = json.loads((ROOT / "teams.json").read_text(encoding="utf-8"))
    teams = cfg.get("teams", [])
    tm_cache_load()
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
    # --- 相手チームの選手（観る試合のスタメン・ベンチ）の経歴と動画。チーム横断で共有キャッシュ
    try:
        opp = collect_opponent_players(teams, photo_index)
        log(f"== 相手チームの選手 {len(opp)} 人")
        update_careers(DATA / "opponents" / "careers.json", opp)
        update_videos(DATA / "opponents" / "videos.json", opp)
    except Exception as e:  # noqa: BLE001
        log(f"!! 相手チーム選手の更新に失敗: {e!r}")
    try:
        tm_cache_save()
    except Exception as e:  # noqa: BLE001
        log(f"!! tm-photos の保存に失敗: {e!r}")
    write_json(DATA / "meta.json", {"updatedAt": iso(NOW), "teams": [t["id"] for t in teams]})
    log("done")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
