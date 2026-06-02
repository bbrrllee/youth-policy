"""
온통청년 API + 경기도 전용 포털 + 네이버 뉴스 RSS 자동 갱신
- 온통청년 API (중앙·광역 정책)
- 경기청년포털 youth.gg.go.kr (경기도 청년정책)
- 잡아바 apply.jobaba.net (경기도일자리재단 - 청년기본소득 등)
- 네이버 뉴스 RSS (경기도/31개 시군 청년정책 신규 공고 감지)
- 경기복지포털 gg24.gg.go.kr (고립은둔 등 복지사업)
매일 GitHub Actions에서 실행됩니다.
"""
import os, json, requests, xml.etree.ElementTree as ET, math, re
from datetime import datetime
from bs4 import BeautifulSoup

API_KEY  = os.environ.get("API_KEY", "c937731f-99f2-489c-a334-07bbfff0da0d")
BASE_URL = "https://www.youthcenter.go.kr/opi/youthPlcyList.do"
TODAY    = datetime.now()
CUR_M    = TODAY.month

FIELD_MAP = {
    "023010": "일자리", "023020": "주거",
    "023030": "교육ㆍ직업훈련", "023040": "금융ㆍ복지ㆍ문화", "023050": "참여권리",
}

# ── 상태 판별 ──────────────────────────────────────────
def get_status(text):
    if not text or not text.strip():
        return "미정"
    t = re.sub(r'\s+', ' ', text)
    if re.search(r'모집.?중|접수.?중|진행.?중', t): return "모집중"
    if re.search(r'마감|종료|완료', t):              return "마감"

    # 종료일 지난 경우
    m = re.search(r'~\s*(\d{4})[.\s]+(\d{1,2})[.\s]+(\d{1,2})', t)
    if m:
        try:
            end = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if end < TODAY: return "마감"
        except: pass

    # 정확한 날짜 있는 경우 (신뢰도 높음)
    m = re.search(r'(\d{4})[.\s]+(\d{1,2})[.\s]+(\d{1,2})', t)
    if m:
        try:
            start = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return "모집예정" if start > TODAY else "모집중"
        except: pass

    # 월 범위 (예: 3월~11월)
    m = re.search(r'(\d{1,2})월.*?~.*?(\d{1,2})월', t)
    if m:
        sm, em = int(m.group(1)), int(m.group(2))
        if CUR_M > em:  return "마감"
        if CUR_M < sm:  return "모집예정"
        return "확인필요"  # 해당 월 범위지만 공고 미확인

    if '상반기' in t: return "확인필요"
    if '하반기' in t: return "모집예정"

    m = re.search(r'(\d{1,2})월', t)
    if m:
        month = int(m.group(1))
        if month < CUR_M: return "마감"
        if month == CUR_M: return "확인필요"  # 해당 월 → 공고 확인 필요
        return "모집예정"

    return "미정"

# ── 온통청년 API 호출 ────────────────────────────────────
def fetch_api_page(page=1, per_page=100, keyword=""):
    params = {
        "openApiVlak": API_KEY, "pageIndex": page,
        "display": per_page, "srchCtpvCd": "41",
    }
    if keyword:
        params["query"] = keyword
    try:
        r = requests.get(BASE_URL, params=params, timeout=20)
        r.encoding = "utf-8"
        return ET.fromstring(r.text)
    except Exception as e:
        print(f"  API 오류: {e}")
        return None

def parse_item(item):
    ssg = item.findtext("ssgNm", "")
    ssg = ssg.replace("경기도", "").strip() if "경기도" in ssg else ssg
    field_code = item.findtext("polyBizSecd", "")
    return {
        "시군":     ssg or "경기도",
        "분야":     FIELD_MAP.get(field_code, item.findtext("polyBizSecdNm", "기타")),
        "사업명":   item.findtext("polyBizSjnm", ""),
        "주요내용": item.findtext("polyItcnCn", ""),
        "모집시기": item.findtext("rqutPrdCn", ""),
        "신청방법": item.findtext("rqutUrla", ""),
        "운영기관": item.findtext("cnsgNmor", ""),
        "문의처":   item.findtext("inqisCn", ""),
        "링크":     item.findtext("aplctnUrla", ""),
        "링크_모집":    item.findtext("aplctnUrla", ""),
        "링크_전년도":  "",
        "출처":     "온통청년API",
        "갱신일":   TODAY.strftime("%Y-%m-%d"),
    }

# ── 확인필요 항목 → API에서 실제 공고 검색 ─────────────────
def search_active_announcement(policy_name):
    """사업명 키워드로 온통청년 API 검색 → 실제 모집중 공고 찾기"""
    # 키워드 추출 (2~4글자 핵심어)
    keyword = policy_name.replace("경기", "").replace("청년", "").strip()
    keyword = re.sub(r'[^\w]', ' ', keyword).strip()
    if len(keyword) < 2:
        keyword = policy_name

    root = fetch_api_page(keyword=keyword)
    if root is None:
        return None

    for item in root.findall(".//youthPolicy"):
        name = item.findtext("polyBizSjnm", "")
        # 사업명 유사도 체크 (핵심 키워드 포함 여부)
        core_words = [w for w in keyword.split() if len(w) >= 2]
        if any(w in name for w in core_words):
            # 모집 기간 확인
            period = item.findtext("rqutPrdCn", "")
            status = get_status(period)
            if status == "모집중":
                link = item.findtext("aplctnUrla", "") or item.findtext("rqutUrla", "")
                print(f"    ✅ 공고 발견: {name} | {period}")
                return {"link": link, "period": period}

    print(f"    ❌ 공고 미발견: {policy_name}")
    return None

# ── 메인 ────────────────────────────────────────────────
def main():
    print(f"[{TODAY.strftime('%Y-%m-%d')}] 청년정책 데이터 갱신 시작...")

    # 기존 data.json 로드
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            existing = json.load(f)
        print(f"기존 데이터: {len(existing)}개")
    except:
        existing = []
        print("기존 data.json 없음")

    # 상태 재계산 + 링크 필드 보장
    updated = []
    check_list = []

    for d in existing:
        # 기존에 수동으로 모집중 처리된 것은 유지
        if d.get("링크_모집") and d.get("모집상태") == "모집중":
            updated.append(d)
            continue

        new_status = get_status(d.get("모집시기", ""))
        d["모집상태"] = new_status
        d.setdefault("링크_모집", "")
        d.setdefault("링크_전년도", "")
        d.setdefault("출처", "")

        if new_status == "확인필요":
            check_list.append(d)

        updated.append(d)

    print(f"\n확인필요 항목: {len(check_list)}개 → 온통청년 API 검색 시작")

    # 확인필요 항목 자동 검색
    confirmed_count = 0
    for d in check_list:
        print(f"  검색중: {d.get('시군')} | {d.get('사업명')}")
        result = search_active_announcement(d.get("사업명", ""))
        if result:
            d["모집상태"] = "모집중"
            d["링크_모집"] = result["link"]
            d["모집시기"]  = result["period"]  # 실제 공고 기간으로 업데이트
            confirmed_count += 1
        else:
            # 공고 못 찾으면 모집예정으로 유지 (자동 모집중 방지)
            d["모집상태"] = "모집예정"

    print(f"\nAPI 자동 확인: {confirmed_count}개 모집중 확인")

    # 온통청년 API 전체 수집
    print("\n온통청년 API 전체 수집...")
    first = fetch_api_page(1)
    if first is not None:
        total = int(first.findtext(".//totalCount", "0") or 0)
        api_items = [parse_item(i) for i in first.findall(".//youthPolicy")]
        for page in range(2, math.ceil(total / 100) + 1):
            root = fetch_api_page(page)
            if root:
                api_items.extend([parse_item(i) for i in root.findall(".//youthPolicy")])
        existing_names = {d.get("사업명", "") for d in updated}
        new_items = [i for i in api_items if i["사업명"] not in existing_names]
        for item in new_items:
            item["모집상태"] = get_status(item["모집시기"])
        updated.extend(new_items)
        print(f"온통청년 API 신규: {len(new_items)}개")

    # 31개 시군 공고 게시판 크롤링
    print("\n31개 시군 공고 게시판 크롤링...")
    sigungu_new = scrape_sigungu_boards(updated)
    updated.extend(sigungu_new)
    print(f"시군 공고 신규 발견: {len(sigungu_new)}개")

    # 경기도 전용 포털 크롤링 (청년기본소득, 고립은둔 등)
    print("\n경기도 전용 포털 크롤링...")
    existing_names = {d.get("사업명", "") for d in updated}

    portal_items = []
    portal_items.extend(scrape_jobaba())       # 잡아바 (청년기본소득 등)
    portal_items.extend(scrape_gg24())         # 경기복지포털 (고립은둔 등)
    portal_items.extend(scrape_gyeonggi_youth_portal())  # 경기청년포털

    added = 0
    for item in portal_items:
        if item["사업명"] not in existing_names and len(item["사업명"]) > 2:
            updated.append(item)
            existing_names.add(item["사업명"])
            added += 1
    print(f"경기도 포털 신규 추가: {added}개")

    # 네이버 뉴스 RSS 검색
    print("\n네이버 뉴스 RSS 청년정책 신규 공고 탐지...")
    news_items = search_naver_news(updated)
    news_added = 0
    existing_names_now = {d.get("사업명","") for d in updated}
    for item in news_items:
        if item["사업명"] not in existing_names_now and len(item["사업명"]) > 5:
            updated.append(item)
            existing_names_now.add(item["사업명"])
            news_added += 1
    print(f"뉴스 신규 추가: {news_added}개")

    # 최종 저장
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)

    # 요약
    from collections import Counter
    status_count = Counter(d.get("모집상태","미정") for d in updated)
    print(f"\n✅ 완료: 총 {len(updated)}개")
    for k, v in sorted(status_count.items()):
        print(f"  {k}: {v}개")

# ── 경기도 전용 포털 크롤링 ─────────────────────────────────
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def scrape_sigungu_boards(existing_data):
    """31개 시군 공고 게시판 크롤링 → 청년 관련 신규 공고 감지"""
    try:
        with open("sites.json", "r", encoding="utf-8") as f:
            sites = json.load(f)
    except:
        print("  sites.json 없음")
        return []

    # 기존 사업명 목록 (중복 방지)
    existing_names = {d.get("사업명","") for d in existing_data}
    # 기존 링크 목록 (같은 공고 중복 방지)
    existing_links = {d.get("링크","") for d in existing_data if d.get("링크")}

    YOUTH_KEYWORDS = ["청년", "청소년지원", "청년지원", "청년정책", "청년취업",
                      "청년주거", "청년창업", "청년인턴", "청년아르바이트"]
    results = []

    for site in sites:
        시군 = site.get("city") or site.get("시군", "")
        url  = site["url"]
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.encoding = r.apparent_encoding or "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")

            # 여러 셀렉터 시도
            rows = []
            for sel in site.get("selectors", ["table tr"]):
                rows = soup.select(sel)
                if len(rows) > 2:
                    break

            for row in rows:
                # 제목 텍스트와 링크 추출
                link_el = row.select_one("a")
                if not link_el:
                    continue
                title = link_el.get_text(strip=True)
                if not title or len(title) < 4:
                    continue

                # 청년 키워드 포함 여부 체크
                if not any(kw in title for kw in YOUTH_KEYWORDS):
                    continue

                href = link_el.get("href", "")
                full_link = href if href.startswith("http") else (
                    f"https://{url.split('/')[2]}{href}" if href.startswith("/") else url
                )

                # 중복 체크
                if full_link in existing_links:
                    continue
                if any(title in name or name in title for name in existing_names if len(name) > 4):
                    # 기존 사업명과 유사 → 모집중으로 상태만 업데이트
                    for d in existing_data:
                        if d.get("시군") == 시군 and (
                            title in d.get("사업명","") or d.get("사업명","") in title
                        ):
                            if d.get("모집상태") != "모집중":
                                d["모집상태"] = "모집중"
                                d["링크_모집"] = full_link
                                d["링크"] = full_link
                                print(f"  ✅ 상태 업데이트: [{시군}] {d['사업명']} → 모집중")
                    continue

                # 신규 공고 → 새 항목 추가
                results.append({
                    "시군": 시군, "분야": "기타",
                    "사업명": title, "주요내용": "",
                    "모집시기": "", "모집상태": "모집중",
                    "신청방법": "", "운영기관": "", "문의처": "",
                    "링크": full_link, "링크_모집": full_link, "링크_전년도": "",
                    "출처": f"{시군}공고게시판", "갱신일": TODAY.strftime("%Y-%m-%d"),
                })
                existing_links.add(full_link)
                print(f"  🆕 신규 공고: [{시군}] {title}")

        except Exception as e:
            print(f"  ⚠️ [{시군}] 크롤링 실패: {type(e).__name__}")

    return results


def scrape_gyeonggi_youth_portal():
    """경기청년포털 youth.gg.go.kr - 청년기본소득, 갭이어, 사다리 등"""
    results = []
    # 경기청년포털 정책 목록
    urls = [
        "https://youth.gg.go.kr/gg/intro/youth-policy-list.do",
        "https://youth.gg.go.kr/gg/archive-policy-search.do?mode=list&srSido=gyeonggi",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            # 정책 카드/리스트 항목 파싱 (사이트 구조에 따라 조정)
            items = soup.select(".policy-item, .list-item, article, .card")
            for item in items:
                title_el = item.select_one("h3, h4, .title, .tit, strong")
                link_el  = item.select_one("a")
                if title_el and title_el.get_text(strip=True):
                    name = title_el.get_text(strip=True)
                    link = ""
                    if link_el and link_el.get("href"):
                        href = link_el["href"]
                        link = href if href.startswith("http") else f"https://youth.gg.go.kr{href}"
                    results.append({
                        "시군": "경기도", "분야": "금융ㆍ복지ㆍ문화",
                        "사업명": name, "주요내용": "", "모집시기": "",
                        "모집상태": "확인필요", "신청방법": "", "운영기관": "경기도",
                        "문의처": "", "링크": link, "링크_모집": link, "링크_전년도": "",
                        "출처": "경기청년포털", "갱신일": TODAY.strftime("%Y-%m-%d"),
                    })
        except Exception as e:
            print(f"  경기청년포털 스크랩 오류: {e}")
    return results

def scrape_jobaba():
    """잡아바 apply.jobaba.net - 청년기본소득, 각종 경기도 사업"""
    results = []
    # 잡아바 경기도 사업 목록
    TARGET_PROGRAMS = [
        {"name": "경기도 청년기본소득", "url": "https://apply.jobaba.net/special/gibon/main.do",
         "분야": "금융ㆍ복지ㆍ문화", "모집상태": "모집중"},
    ]
    try:
        r = requests.get("https://apply.jobaba.net/bsns/bsnsListView.do", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        # 모집중 사업 파싱
        items = soup.select(".bsns-item, .list-bsns li, .program-item")
        for item in items:
            title_el = item.select_one(".bsns-nm, .tit, h3, strong")
            status_el = item.select_one(".status, .badge, .state")
            link_el   = item.select_one("a")
            if not title_el: continue
            name = title_el.get_text(strip=True)
            if not name: continue
            status_text = status_el.get_text(strip=True) if status_el else ""
            link = ""
            if link_el and link_el.get("href"):
                href = link_el["href"]
                link = href if href.startswith("http") else f"https://apply.jobaba.net{href}"
            status = "모집중" if "모집" in status_text else "모집예정" if "예정" in status_text else "확인필요"
            results.append({
                "시군": "경기도", "분야": "일자리",
                "사업명": name, "주요내용": "", "모집시기": "",
                "모집상태": status, "신청방법": "잡아바 온라인 신청",
                "운영기관": "경기도일자리재단", "문의처": "",
                "링크": link, "링크_모집": link, "링크_전년도": "",
                "출처": "잡아바", "갱신일": TODAY.strftime("%Y-%m-%d"),
            })
        # 고정 프로그램 추가 (잡아바 파싱 실패 대비)
        for p in TARGET_PROGRAMS:
            if not any(r["사업명"] == p["name"] for r in results):
                results.append({
                    "시군": "경기도", "분야": p["분야"], "사업명": p["name"],
                    "주요내용": "", "모집시기": "", "모집상태": p["모집상태"],
                    "신청방법": "잡아바 온라인 신청", "운영기관": "경기도일자리재단",
                    "문의처": "1877-0566", "링크": p["url"], "링크_모집": p["url"],
                    "링크_전년도": "", "출처": "잡아바", "갱신일": TODAY.strftime("%Y-%m-%d"),
                })
    except Exception as e:
        print(f"  잡아바 스크랩 오류: {e}")
        # 오류 시 고정 프로그램만 추가
        for p in TARGET_PROGRAMS:
            results.append({
                "시군": "경기도", "분야": p["분야"], "사업명": p["name"],
                "주요내용": "", "모집시기": "", "모집상태": p["모집상태"],
                "신청방법": "잡아바 온라인 신청", "운영기관": "경기도일자리재단",
                "문의처": "1877-0566", "링크": p["url"], "링크_모집": p["url"],
                "링크_전년도": "", "출처": "잡아바", "갱신일": TODAY.strftime("%Y-%m-%d"),
            })
    return results

def scrape_gg24():
    """경기복지포털 gg24.gg.go.kr - 고립은둔청년 등 복지사업"""
    results = []
    FIXED_PROGRAMS = [
        {"name": "경기 고립은둔청년 지원사업",
         "url": "https://gg24.gg.go.kr/svcreqst/selectSvcReqst.do?sch_tab_code=10&svc_seq=945",
         "분야": "금융ㆍ복지ㆍ문화", "모집상태": "모집중",
         "문의처": "경기복지재단 031-267-9100"},
    ]
    try:
        url = "https://gg24.gg.go.kr/svcreqst/selectSvcReqstList.do?sch_tab_code=10"
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select("li.item, .svc-item, .list-item")
        for item in items:
            title_el = item.select_one(".svc-nm, .tit, h3, strong, a")
            if not title_el: continue
            name = title_el.get_text(strip=True)
            if not name or "청년" not in name: continue
            link_el = item.select_one("a")
            link = ""
            if link_el and link_el.get("href"):
                href = link_el["href"]
                link = href if href.startswith("http") else f"https://gg24.gg.go.kr{href}"
            results.append({
                "시군": "경기도", "분야": "금융ㆍ복지ㆍ문화", "사업명": name,
                "주요내용": "", "모집시기": "", "모집상태": "확인필요",
                "신청방법": "경기복지포털 온라인 신청", "운영기관": "경기복지재단",
                "문의처": "031-267-9100", "링크": link, "링크_모집": link, "링크_전년도": "",
                "출처": "경기복지포털", "갱신일": TODAY.strftime("%Y-%m-%d"),
            })
    except Exception as e:
        print(f"  경기복지포털 스크랩 오류: {e}")

    # 고정 프로그램 추가
    for p in FIXED_PROGRAMS:
        if not any(r["사업명"] == p["name"] for r in results):
            results.append({
                "시군": "경기도", "분야": p["분야"], "사업명": p["name"],
                "주요내용": "", "모집시기": "", "모집상태": p["모집상태"],
                "신청방법": "경기복지포털 온라인 신청", "운영기관": "경기복지재단",
                "문의처": p["문의처"], "링크": p["url"], "링크_모집": p["url"], "링크_전년도": "",
                "출처": "경기복지포털", "갱신일": TODAY.strftime("%Y-%m-%d"),
            })
    return results


# ── 네이버 뉴스 RSS 검색 ─────────────────────────────────────
import urllib.parse
from xml.etree import ElementTree as ET2

NAVER_SEARCH_QUERIES = [
    "경기도 청년 모집 공고",
    "경기도 청년정책 신청",
    "경기 청년 지원 모집",
    "수원시 청년 모집",
    "성남시 청년 모집",
    "용인시 청년 모집",
    "고양시 청년 모집",
    "화성시 청년 모집",
    "경기청년 새소식",
]

YOUTH_KEYWORDS = ["청년", "청년정책", "청년지원", "청년모집", "청년공고"]
EXCLUDE_KEYWORDS = ["부동산", "주식", "투자", "광고", "대출금리"]

GYEONGGI_CITIES = ["수원","성남","의정부","안양","부천","광명","평택","동두천","안산",
                   "고양","과천","구리","남양주","오산","시흥","군포","의왕","하남",
                   "용인","파주","이천","안성","김포","화성","광주","양주","포천",
                   "여주","연천","가평","양평","경기"]

def search_naver_news(existing_data):
    """네이버 뉴스 RSS로 경기도 청년정책 신규 공고 탐지"""
    existing_names = {d.get("사업명","") for d in existing_data}
    existing_links = {d.get("링크","") for d in existing_data if d.get("링크")}
    results = []
    seen_links = set()

    for query in NAVER_SEARCH_QUERIES:
        try:
            encoded = urllib.parse.quote(query)
            rss_url = f"https://news.naver.com/main/rss/rss.naver?oid=&q={encoded}&sort=1&period=1"
            # 네이버 뉴스 검색 RSS (최근 1일)
            search_url = f"https://s.search.naver.com/p/newssearch/search.naver?query={encoded}&where=news&pd=4&ds=&de=&docid=&related=0&mynews=0&office_type=0&office_section_code=0&news_office_checked=&sort=1&field=0&service_area=0&start=1&display=10&format=rss"
            r = requests.get(search_url, headers={**HEADERS, "Referer": "https://search.naver.com"}, timeout=10)
            root = ET2.fromstring(r.content)

            for item in root.findall(".//item"):
                title_el = item.find("title")
                link_el  = item.find("link")
                desc_el  = item.find("description")
                if title_el is None: continue

                title = re.sub(r'<[^>]+>', '', title_el.text or "").strip()
                link  = link_el.text.strip() if link_el is not None and link_el.text else ""
                desc  = re.sub(r'<[^>]+>', '', desc_el.text or "").strip() if desc_el is not None else ""

                # 필터링
                if not any(kw in title for kw in YOUTH_KEYWORDS): continue
                if any(ex in title for ex in EXCLUDE_KEYWORDS): continue
                if not any(city in title+desc for city in GYEONGGI_CITIES): continue
                if link in seen_links or link in existing_links: continue
                if any(title[:10] in name for name in existing_names): continue

                seen_links.add(link)

                # 시군 추출
                시군 = "경기도"
                for city in GYEONGGI_CITIES:
                    if city in title and city != "경기":
                        시군 = city + ("시" if not city.endswith(("시","군")) else "")
                        break

                results.append({
                    "시군": 시군, "분야": "기타",
                    "사업명": title[:60],
                    "주요내용": desc[:200],
                    "모집시기": "", "모집상태": "확인필요",
                    "신청방법": "", "운영기관": "",
                    "문의처": "", "링크": link,
                    "링크_모집": link, "링크_전년도": "",
                    "출처": "네이버뉴스RSS",
                    "갱신일": TODAY.strftime("%Y-%m-%d"),
                    "메모": f"뉴스 자동감지 - 담당자 확인 필요: {link}"
                })
                print(f"  📰 뉴스 감지: {title[:40]}")

        except Exception as e:
            print(f"  네이버 RSS 오류 ({query[:10]}): {type(e).__name__}")
        time.sleep(0.5)

    print(f"네이버 뉴스 신규 감지: {len(results)}건")
    return results

import time


if __name__ == "__main__":
    main()
