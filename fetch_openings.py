# 심평원 요양기관 개폐업정보조회 → 신규 개원 CSV (좌표 포함)
# GitHub Actions에서 주기적으로 실행됩니다.
# 필요한 Secrets: SERVICE_KEY (심평원), KAKAO_REST (카카오 REST API 키)

import os, csv, time, datetime, json, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

SERVICE_KEY = os.environ.get("SERVICE_KEY", "").strip()
KAKAO_REST  = os.environ.get("KAKAO_REST", "").strip()
if not SERVICE_KEY:
    raise SystemExit("SERVICE_KEY 없음. 깃헙 Settings > Secrets 에 등록하세요.")
if not KAKAO_REST:
    raise SystemExit("KAKAO_REST 없음. 깃헙 Settings > Secrets 에 등록하세요.")

BASE = "https://apis.data.go.kr/B551182/yadmOpCloInfoService2/getHospPharmacyOpCloList1"
KAKAO_GEO = "https://dapi.kakao.com/v2/local/search/address.json"

SIDO = ["110000","260000","270000","280000","290000","300000","310000","360000",
        "410000","420000","430000","440000","450000","460000","470000","480000","500000"]

# 최근 12개월치만 수집 (1년 넘은 건 제외)
_t = datetime.date.today()
MONTHS, _y, _m = [], _t.year, _t.month
for _ in range(12):
    MONTHS.append(f"{_y}{_m:02d}")
    _m -= 1
    if _m == 0: _m = 12; _y -= 1

def fetch_hira(crtr, sido, page):
    params = {"serviceKey": SERVICE_KEY, "numOfRows": "1000", "pageNo": str(page),
              "crtrYm": crtr, "yadmTp": "0", "opCloTp": "1", "sidoCd": sido}
    req = urllib.request.Request(
        BASE + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "gh-action"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()

def parse_hira(xml_bytes, out):
    root = ET.fromstring(xml_bytes)
    code = root.findtext(".//resultCode")
    if code not in (None, "00"):
        raise RuntimeError(f"API 오류 {code}: {root.findtext('.//resultMsg')}")
    total = int(root.findtext(".//totalCount") or 0)
    items = root.findall(".//item")
    for it in items:
        g = lambda t: (it.findtext(t) or "").strip()
        e = g("estbDd")
        date = f"{e[0:4]}-{e[4:6]}-{e[6:8]}" if len(e) == 8 else e
        out.append({"요양기관명": g("yadmNm"), "요양종별": g("clCdNm"),
                    "시도명": g("sidoCdNm"), "도로명주소": g("addr"),
                    "표시과목명": g("shwSbjtCdNm"), "개설일자": date,
                    "전화번호": g("telno"), "lat": "", "lng": ""})
    return total, len(items)

def clean_addr(addr):
    """카카오 지오코딩 성공률을 높이기 위한 주소 정제"""
    import re
    a = addr
    # 괄호 제거
    a = re.sub(r'\([^)]*\)', '', a)
    # 물결표 범위 → 첫 번째 호수만 (101~108호, 701호~740호)
    a = re.sub(r'(\d+)\s*호?\s*[~～]\s*\d+\s*호', r'\1호', a)
    # 알파벳 호수 (A204, A205, ... → 제거)
    a = re.sub(r',?\s*[A-Za-z]\d+(?:,\s*[A-Za-z]\d+)*', '', a)
    # 지하 + 역명 제거 (발산역(5호선) 같은 표기)
    a = re.sub(r'[가-힣]+역\([^)]*\)', '', a)
    # 쉼표 뒤 층/호/건물명 제거
    a = re.sub(r',.*$', '', a)
    # 도로명+건물번호까지만 추출
    m = re.match(r'^(.*?(?:대로|로)(?:\s*\d+(?:가|번)?길)?\s*(?:지하)?\s*\d+(?:-\d+)?)', a)
    if m: a = m.group(1)
    a = re.sub(r'\s+', ' ', a).strip()
    return a if a else addr

def geocode_kakao(addr):
    """카카오 주소 검색 API → (lat, lng) 또는 None. 실패 시 정제 주소로 재시도."""
    import re
    def _fetch(query):
        try:
            req = urllib.request.Request(
                KAKAO_GEO + "?" + urllib.parse.urlencode({"query": query, "size": 1}),
                headers={"Authorization": f"KakaoAK {KAKAO_REST}", "User-Agent": "gh-action"})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read())
            docs = d.get("documents", [])
            if docs:
                return docs[0]["y"], docs[0]["x"]
        except Exception as e:
            print(f"  [좌표오류] {query[:30]}: {e}")
        return None, None

    # 1차: 원본 주소
    lat, lng = _fetch(addr)
    if lat: return lat, lng
    # 2차: 정제된 주소
    cleaned = clean_addr(addr)
    if cleaned != addr:
        lat, lng = _fetch(cleaned)
    return lat, lng

# ── 1단계: 개원 데이터 수집 ──────────────────────────────────
rows = []
for crtr in MONTHS:
    for sido in SIDO:
        try:
            page, collected = 1, 0
            while True:
                total, cnt = parse_hira(fetch_hira(crtr, sido, page), rows)
                collected += cnt
                if cnt == 0 or collected >= total: break
                page += 1
                time.sleep(0.15)
            time.sleep(0.1)
        except Exception as ex:
            print(f"[경고] {crtr}/{sido}: {ex}")
    print(f"기준월 {crtr} 누적 {len(rows)}건")

# 중복 제거
seen, uniq = set(), []
for r in rows:
    k = (r["요양기관명"], r["도로명주소"], r["개설일자"])
    if k not in seen: seen.add(k); uniq.append(r)
print(f"중복 제거 후: {len(uniq)}건")

# ── 2단계: 좌표 변환 (카카오) ────────────────────────────────
# 이전 실행에서 저장된 좌표 재사용 (새 기관만 변환)
prev_coords = {}
try:
    with open("new-clinics.csv", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("lat") and row.get("lng"):
                prev_coords[row["도로명주소"]] = (row["lat"], row["lng"])
    print(f"이전 좌표 {len(prev_coords)}건 재사용")
except FileNotFoundError:
    pass

need_geo, reused, failed = 0, 0, 0
for r in uniq:
    addr = r["도로명주소"]
    if addr in prev_coords:
        r["lat"], r["lng"] = prev_coords[addr]
        reused += 1
    elif addr:
        lat, lng = geocode_kakao(addr)
        if lat:
            r["lat"], r["lng"] = lat, lng
            need_geo += 1
        else:
            failed += 1
        time.sleep(0.05)  # 카카오 rate limit 방지

print(f"좌표: 신규변환 {need_geo}건 / 재사용 {reused}건 / 실패 {failed}건")

# ── 3단계: CSV 저장 ──────────────────────────────────────────
cols = ["요양기관명","요양종별","시도명","도로명주소","표시과목명","개설일자","전화번호","lat","lng"]
with open("new-clinics.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    for r in uniq: w.writerow(r)

print(f"완료: {len(uniq)}건 저장 (최근 12개월, 좌표 포함)")
