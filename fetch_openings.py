# 심평원 요양기관 개폐업정보조회 → "신규 개원(개업)" CSV 생성
# GitHub Actions에서 주기적으로 실행됩니다.
# 인증키는 코드에 넣지 않고, 깃헙 Secret(SERVICE_KEY)에서 읽습니다.
 
import os, csv, time, datetime, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
 
KEY = os.environ.get("SERVICE_KEY", "").strip()
if not KEY:
    raise SystemExit("SERVICE_KEY 가 없습니다. 깃헙 저장소 Settings > Secrets 에 SERVICE_KEY 를 등록하세요.")
 
BASE = "https://apis.data.go.kr/B551182/yadmOpCloInfoService2/getHospPharmacyOpCloList1"
 
# 시도코드 (법정동 시도코드 ×10000). 전국을 한 시도씩 돌며 수집.
SIDO = ["110000","260000","270000","280000","290000","300000","310000","360000",
        "410000","420000","430000","440000","450000","460000","470000","480000","500000"]
 
# 개설 데이터는 '기준년월(crtrYm)'로 들어옴 → 최근 14개월을 모두 조회해서 모음
# (도구에서 다시 3/6/12개월로 거름)
_t = datetime.date.today()
MONTHS = []
_y, _m = _t.year, _t.month
for _ in range(14):
    MONTHS.append(f"{_y}{_m:02d}")
    _m -= 1
    if _m == 0:
        _m = 12; _y -= 1
 
NUM = 1000  # 한 페이지 요청 수 (API가 더 적게 주더라도 아래 루프가 알아서 페이징)
 
def fetch(crtr, sido, page):
    params = {
        "serviceKey": KEY,
        "numOfRows": str(NUM),
        "pageNo": str(page),
        "crtrYm": crtr,      # 기준년월
        "yadmTp": "0",       # 0=전체(병의원+약국)
        "opCloTp": "1",      # 1=개업만
        "sidoCd": sido,
    }
    url = BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "gh-action"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()
 
def parse(xml_bytes, out):
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
        out.append({
            "요양기관명": g("yadmNm"),
            "요양종별": g("clCdNm"),
            "시도명": g("sidoCdNm"),
            "도로명주소": g("addr"),
            "표시과목명": g("shwSbjtCdNm"),
            "개설일자": date,
            "전화번호": g("telno"),
        })
    return total, len(items)
 
rows = []
for crtr in MONTHS:
    for sido in SIDO:
        try:
            page, collected = 1, 0
            while True:
                total, cnt = parse(fetch(crtr, sido, page), rows)
                collected += cnt
                if cnt == 0 or collected >= total:
                    break
                page += 1
                time.sleep(0.15)
            time.sleep(0.1)
        except Exception as ex:
            print(f"[경고] {crtr}/{sido} 오류, 건너뜀: {ex}")
    print(f"기준월 {crtr} 까지 누적 {len(rows)}건")
 
# 중복 제거 (기관명+주소+개설일자)
seen, uniq = set(), []
for r in rows:
    k = (r["요양기관명"], r["도로명주소"], r["개설일자"])
    if k in seen:
        continue
    seen.add(k); uniq.append(r)
 
cols = ["요양기관명","요양종별","시도명","도로명주소","표시과목명","개설일자","전화번호"]
with open("new-clinics.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    for r in uniq:
        w.writerow(r)
 
print(f"완료: {len(uniq)}건 저장 (최근 {len(MONTHS)}개월 기준년월, 전국 개업)")
 
