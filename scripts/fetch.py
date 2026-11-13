#!/usr/bin/env python3
"""전국 공영도매시장 실시간 경매정보를 받아 data/*.json 으로 저장한다.

GitHub Actions 에서 정해진 시간마다 실행된다. 인증키는 환경변수 DATA_GO_KR_KEY 로 받는다.
표준 라이브러리만 사용한다.

저장하는 파일
  data/markets_discovered.json         API 에서 확인한 도매시장 코드와 이름 (처음 한 번 만든다)
  data/daily/<시장id>/<일자>.json       하루치 품목별 집계 (지난 날은 다시 받지 않는다)
  data/lots/<시장id>/<일자>/<법인코드>.json  그날 그 법인의 낙찰 내역 전체 (화면에서 누를 때 불러온다)
  data/<시장id>.json                   화면이 처음 읽는 시장별 시세 (품목, 최근 추세, 날짜별 법인 평균)
  data/index.json                      수집한 시장 목록과 요약
"""
import datetime
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://apis.data.go.kr/B552845/katRealTime2/trades2"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
KST = datetime.timezone(datetime.timedelta(hours=9))

WINDOW = 14         # 저장소(main)에 두는 최근 일수. 이보다 오래된 날은 archive 로 옮긴다.
GRAPH_DAYS = 7      # 그래프에 쓰는 최근 일수
REFRESH_DAYS = 2    # 항상 다시 받을 최근 며칠
ARCHIVE_DIR = os.environ.get("ARCHIVE_DIR", "").strip()   # archive 브랜치를 내려받은 폴더
PAGE_SIZE = 1000
MAX_CALLS = 2500    # 한 번 실행에서 부를 수 있는 최대 횟수
MAX_ITEMS = 500     # 시장 파일에 담을 최대 품목(규격) 수, 물량 많은 순
SCHEMA = 3          # 일별 파일 형식 번호. 바뀌면 지난 날도 다시 받는다.

KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
calls = 0


def log(*args):
    print(*args, flush=True)


def mask(text):
    if KEY:
        text = text.replace(KEY, "***").replace(urllib.parse.quote(KEY, safe=""), "***")
    return text


# ---------------------------------------------------------------- API 호출
def api(params):
    global calls
    q = dict(params)
    q["returnType"] = "json"
    key = KEY if "%" in KEY else urllib.parse.quote(KEY, safe="")
    url = BASE + "?serviceKey=" + key + "&" + urllib.parse.urlencode(q)
    last = "알 수 없음"
    for attempt in range(3):
        if calls >= MAX_CALLS:
            raise SystemExit("호출 횟수 한도(%d)에 도달해 중단합니다." % MAX_CALLS)
        calls += 1
        raw = ""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "marketprices/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode("utf-8", "replace")
            try:
                j = json.loads(raw)
            except ValueError:
                raise RuntimeError("JSON 이 아닌 응답: " + raw[:200].replace("\n", " "))
            head = j["response"]["header"]
            if str(head.get("resultCode")) != "0":
                raise RuntimeError("API 오류 %s %s" % (head.get("resultCode"), head.get("resultMsg")))
            return j["response"]["body"]
        except Exception as e:  # noqa: BLE001 - 재시도 대상
            last = mask(str(e))
            log("  재시도 %d/3: %s" % (attempt + 1, last[:200]))
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("API 호출 실패: " + last)


def rows_of(body):
    items = body.get("items")
    if not items:
        return []
    if isinstance(items, dict):
        items = items.get("item")
    if items is None:
        return []
    return items if isinstance(items, list) else [items]


def fetch_all(params, max_pages=200):
    out = []
    total = 0
    for page in range(1, max_pages + 1):
        body = api(dict(params, pageNo=page, numOfRows=PAGE_SIZE))
        rows = rows_of(body)
        total = int(body.get("totalCount") or 0)
        out.extend(rows)
        if page % 10 == 0:
            log("    %d쪽까지 받음: %d / %d행" % (page, len(out), total))
        if not rows or len(out) >= total:
            break
    return out, total


# ---------------------------------------------------------------- 파일 입출력
def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def strip_generated(obj):
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if k != "generated"}
    return obj


def write_json(path, obj):
    """내용이 같으면 쓰지 않는다. (generated 항목은 비교에서 뺀다)"""
    old = read_json(path)
    if old is not None and strip_generated(old) == strip_generated(obj):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    return True


# ---------------------------------------------------------------- 시장 찾기
def norm(s):
    return "".join((s or "").split())


def discover(today):
    """정산일자만 조건으로 걸어 그날 거래된 도매시장 코드와 이름을 모은다."""
    for back in range(0, 5):
        ds = (today - datetime.timedelta(days=back)).isoformat()
        log("시장 목록 찾기:", ds)
        params = {"cond[trd_clcln_ymd::EQ]": ds}
        try:
            rows, total = fetch_all(dict(params, selectable="whsl_mrkt_cd,whsl_mrkt_nm"), max_pages=150)
        except RuntimeError as e:
            log("  selectable 없이 다시 시도:", e)
            rows, total = fetch_all(params, max_pages=150)
        found = {}
        for r in rows:
            code = r.get("whsl_mrkt_cd")
            if not code:
                continue
            f = found.setdefault(code, {"code": code, "name": r.get("whsl_mrkt_nm") or "", "rows": 0})
            f["rows"] += 1
        log("  받은 행 %d / 전체 %d / 시장 %d곳" % (len(rows), total, len(found)))
        if found:
            out = {"date": ds, "markets": sorted(found.values(), key=lambda x: x["code"])}
            write_json(os.path.join(DATA, "markets_discovered.json"), out)
            return
    log("최근 5일 동안 시장 목록을 찾지 못했습니다.")


def resolve_code(m, discovered):
    if m.get("code"):
        known = [x["name"] for x in discovered if x["code"] == m["code"]]
        return m["code"], (known[0] if known else m.get("match") or m["id"])
    want = norm(m.get("match"))
    cands = [x for x in discovered if want and want in norm(x["name"])]
    if not cands:
        return None, None
    if len(cands) > 1:
        log("  이름이 여러 곳과 맞습니다:", [x["name"] for x in cands], "→ 가장 짧은 이름을 씁니다.")
    best = sorted(cands, key=lambda x: len(x["name"]))[0]
    return best["code"], best["name"]


# ---------------------------------------------------------------- 집계
def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def clean(x):
    """3.0 -> 3, 2.5 -> 2.5"""
    return int(x) if x == int(x) else round(x, 1)


def unit_label(r):
    uq = num(r.get("unit_qty"))
    un = (r.get("unit_nm") or "").strip()
    pk = (r.get("pkg_nm") or "").strip()
    head = ("%g" % uq if uq else "") + un
    return (head + " " + pk).strip()


def item_parts(r):
    n = (r.get("gds_mclsf_nm") or "").strip()
    v = (r.get("gds_sclsf_nm") or "").strip()
    if v == n:
        v = ""
    return n, v, unit_label(r)


def corp_code(r):
    return (r.get("corp_cd") or "").strip() or "none"


def agg(rows):
    """한 시장·하루치 행을 품목(규격)별로 묶는다. 가격은 규격 1단위 낙찰가의 물량 가중 평균.
    돌려주는 값: (품목별 집계, {법인코드: 법인이름})"""
    items, names = {}, {}
    for r in rows:
        q = num(r.get("qty"))
        p = num(r.get("scsbd_prc"))
        n, v, u = item_parts(r)
        if q <= 0 or p <= 0 or not n:
            continue
        it = items.setdefault("|".join([n, v, u]), {
            "n": n, "v": v, "u": u, "c": (r.get("gds_lclsf_nm") or "").strip() or "기타",
            "sp": 0.0, "q": 0.0, "corps": {}})
        it["sp"] += p * q
        it["q"] += q
        cc = corp_code(r)
        names.setdefault(cc, (r.get("corp_nm") or "").strip() or cc)
        c = it["corps"].setdefault(cc, [0.0, 0.0])
        c[0] += p * q
        c[1] += q
    return items, names


def lots_files(rows):
    """법인별 낙찰 내역 파일 내용을 만든다. {법인코드: 파일내용}
    rows 의 각 행: [품목번호, 시각, 산지번호, 수량, 낙찰가]. 최근 낙찰이 먼저 오도록 정렬한다."""
    byc = {}
    for r in rows:
        q = num(r.get("qty"))
        p = num(r.get("scsbd_prc"))
        n, v, u = item_parts(r)
        if q <= 0 or p <= 0 or not n:
            continue
        d = byc.setdefault(corp_code(r), {"name": (r.get("corp_nm") or "").strip(),
                                          "items": {}, "origins": {}, "raw": []})
        ii = d["items"].setdefault("|".join([n, v, u]), len(d["items"]))
        on = (r.get("plor_nm") or "").strip() or "미상"
        oi = d["origins"].setdefault(on, len(d["origins"]))
        dt = r.get("scsbd_dt") or ""
        d["raw"].append((dt, [ii, dt[11:19], oi, clean(q), clean(p)]))
    out = {}
    for cc, d in byc.items():
        d["raw"].sort(key=lambda x: x[0], reverse=True)
        out[cc] = {"corp": d["name"], "items": list(d["items"]), "origins": list(d["origins"]),
                   "rows": [x[1] for x in d["raw"]]}
    return out


def whole(x):
    return int(round(x))


def build_market(days_data):
    dates = sorted(d for d, v in days_data.items() if v.get("items"))[-WINDOW:]
    if not dates:
        return None
    latest = dates[-1]
    corp_names = {}
    for d in dates:
        corp_names.update(days_data[d].get("names") or {})
    graph = set(dates[-GRAPH_DAYS:])
    out = []
    for key, it in days_data[latest]["items"].items():
        week, wd, cd = [], [], {}
        for d in dates:
            x = days_data[d]["items"].get(key)
            if x and x["q"] > 0:
                if d in graph:
                    week.append(whole(x["sp"] / x["q"]))
                    wd.append(d)
                cd[d] = sorted(([c, whole(s / q), clean(q)] for c, (s, q) in x["corps"].items()),
                               key=lambda z: z[2], reverse=True)
        out.append({"n": it["n"], "v": it["v"], "u": it["u"], "c": it["c"],
                    "week": week, "wdays": wd, "vol": whole(it["q"]), "cd": cd})
    out.sort(key=lambda x: x["vol"], reverse=True)
    out = out[:MAX_ITEMS]
    used = {z[0] for it in out for lst in it["cd"].values() for z in lst}
    return {"date": latest, "dates": dates, "corps": {c: n for c, n in corp_names.items() if c in used},
            "items": out, "total_items": len(days_data[latest]["items"])}


def summarize(market):
    """오른/내린 품목 수와, 가장 많이 오른/내린 품목."""
    up = dn = 0
    best = worst = None
    for it in market["items"]:
        w = it["week"]
        if len(w) >= 2 and w[-2]:
            pct = (w[-1] - w[-2]) / w[-2] * 100
            if pct > 0.05:
                up += 1
            elif pct < -0.05:
                dn += 1
            rec = {"n": it["n"], "v": it.get("v", ""), "pct": round(pct, 1)}
            if best is None or pct > best["pct"]:
                best = rec
            if worst is None or pct < worst["pct"]:
                worst = rec
    return up, dn, best, worst


# ---------------------------------------------------------------- 메인
def collect_market(m, code, today):
    days_data = {}
    base = os.path.join(DATA, "daily", m["id"])
    lots_base = os.path.join(DATA, "lots", m["id"])
    for back in range(WINDOW):
        ds = (today - datetime.timedelta(days=back)).isoformat()
        path = os.path.join(base, ds + ".json")
        cached = read_json(path)
        if cached and cached.get("v") == SCHEMA and cached.get("items") and back >= REFRESH_DAYS:
            days_data[ds] = cached
            continue
        rows, total = fetch_all({"cond[whsl_mrkt_cd::EQ]": code, "cond[trd_clcln_ymd::EQ]": ds})
        items, names = agg(rows)
        day = {"v": SCHEMA, "date": ds, "rows": len(rows), "names": names, "items": items}
        files = lots_files(rows)
        for cc, content in files.items():
            write_json(os.path.join(lots_base, ds, cc + ".json"), content)
        log("  %s %s: 행 %d, 품목 %d, 법인 %d" % (m["id"], ds, len(rows), len(items), len(files)))
        write_json(path, day)
        days_data[ds] = day
    # 오래된 파일 정리: 일별 집계는 지우고, 낙찰 파일은 archive 로 옮긴다.
    recent = {(today - datetime.timedelta(days=i)).isoformat() for i in range(WINDOW)}
    if os.path.isdir(base):
        for f in os.listdir(base):
            if f[:-5] not in recent:
                os.remove(os.path.join(base, f))
    archive_old(m["id"], lots_base, recent)
    return days_data


def archive_old(mid, lots_base, recent):
    """보관 기간이 지난 날의 낙찰 파일을 archive 폴더로 옮기고, 날짜·법인 색인을 갱신한다."""
    if not os.path.isdir(lots_base):
        return
    old = sorted(d for d in os.listdir(lots_base) if d not in recent)
    if not old:
        return
    if not ARCHIVE_DIR:
        log("  ARCHIVE_DIR 가 없어 오래된 낙찰 파일 %d일치를 지우지 않고 둡니다." % len(old))
        return
    idx_path = os.path.join(ARCHIVE_DIR, "index", mid + ".json")
    idx = read_json(idx_path, {"dates": {}, "corps": {}})
    for d in old:
        src = os.path.join(lots_base, d)
        dst = os.path.join(ARCHIVE_DIR, "lots", mid, d)
        if not os.path.exists(dst):
            shutil.copytree(src, dst)
        codes = []
        for f in os.listdir(src):
            if f.endswith(".json"):
                code = f[:-5]
                codes.append(code)
                name = (read_json(os.path.join(src, f), {}) or {}).get("corp")
                if name:
                    idx["corps"][code] = name
        idx["dates"][d] = sorted(codes)
        shutil.rmtree(src, ignore_errors=True)
        log("  보관으로 이동: %s %s" % (mid, d))
    write_json(idx_path, idx)


def main():
    if not KEY:
        sys.exit("환경변수 DATA_GO_KR_KEY 가 없습니다. 저장소 Settings > Secrets 에 넣어주세요.")
    now = datetime.datetime.now(KST)
    today = now.date()
    cfg = read_json(os.path.join(ROOT, "scripts", "markets.json"), {})
    by_id = {m["id"]: m for m in cfg.get("markets", [])}

    disc_path = os.path.join(DATA, "markets_discovered.json")
    if not os.path.exists(disc_path) or os.environ.get("DISCOVER") == "1":
        discover(today)
    discovered = (read_json(disc_path, {}) or {}).get("markets", [])

    index, failed = [], 0
    for mid in cfg.get("active", []):
        m = by_id.get(mid)
        if not m:
            log("markets.json 에 없는 시장:", mid)
            continue
        code, name = resolve_code(m, discovered)
        if not code:
            log("건너뜀: %s 의 도매시장 코드를 찾지 못했습니다. data/markets_discovered.json 을 확인하세요." % mid)
            continue
        log("수집:", mid, code, name)
        try:
            market = build_market(collect_market(m, code, today))
        except (RuntimeError, urllib.error.URLError) as e:
            log("  실패:", mask(str(e)))
            failed += 1
            continue
        if not market:
            log("  데이터 없음")
            continue
        market.update({"id": mid, "name": m.get("label") or name, "code": code, "generated": now.isoformat(timespec="seconds")})
        write_json(os.path.join(DATA, mid + ".json"), market)
        up, dn, best, worst = summarize(market)
        index.append({"id": mid, "name": market["name"], "date": market["date"],
                      "items": len(market["items"]), "up": up, "dn": dn,
                      "top": best, "bot": worst})
        # 시장 하나가 끝날 때마다 저장해서, 중간에 멈춰도 끝낸 시장은 남게 한다.
        write_json(os.path.join(DATA, "index.json"),
                   {"generated": now.isoformat(timespec="seconds"), "markets": index})
    log("완료: 시장 %d곳, API 호출 %d회" % (len(index), calls))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
