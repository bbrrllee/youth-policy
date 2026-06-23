"""
경기도 청년정책 데이터 자동 갱신
매일 오전 9시 GitHub Actions에서 실행됩니다.

수집 경로:
1. 온통청년 API
2. 잡아바 (청년기본소득 등)
3. 경기복지포털 (고립은둔청년 등)
4. 경기청년포털
5. 31개 시군 공고 게시판
6. 네이버 뉴스 RSS
"""

# ── 전체 import (최상단에 모아서) ──────────────────────────
import os
import json
import re
import math
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from collections import Counter

import requests
try:
    from bs4 import BeautifulSoup
    BS4_OK = True
except ImportError:
    BS4_OK = False
    print("⚠️ beautifulsoup4 없음 - 크롤링 일부 스킵")

# ── 상수 ────────────────────────────────────────────────────
API_KEY      = os.environ.get("API_KEY", "c937731f-99f2-489c-a334-07bbfff0da0d")
JOBABA_KEY   = os.environ.get("JOBABA_KEY", "231944106408426fa30737e055d48493")
# 구 API URL이 다운된 경우를 대비해 복수 엔드포인트 시도
BASE_URLS = [
    "https://www.youthcenter.go.kr/opi/youthPlcyList.do",
    "https://youth.go.kr/opi/youthPlcyList.do",
]
BASE_URL = BASE_URLS[0]
TODAY    = datetime.now()
CUR_M    = TODAY.month
HEADERS  = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

FIELD_MAP = {
    "023010": "일자리",
    "023020": "주거",
    "023030": "교육ㆍ직업훈련",
    "023040": "금융ㆍ복지ㆍ문화",
    "023050": "참여권리",
}

GYEONGGI_CITIES = [
    "수원","성남","의정부","안양","부천","광명","평택","동두천","안산",
    "고양","과천","구리","남양주","오산","시흥","군포","의왕","하남",
    "용인","파주","이천","안성","김포","화성","광주","양주","포천",
    "여주","연천","가평","양평","경기"
]

# ── 모집상태 판별 ────────────────────────────────────────────
def get_status(text):
    if not text or not text.strip():
        return "미정"
    t = re.sub(r'\s+', ' ', text).strip()

    if re.search(r'모집.?중|접수.?중|진행.?중', t): return "모집중"
    if re.search(r'마감|종료|완료', t):              return "마감"
    if re.search(r'연중|상시|수시|예산.?소진|자금.?소진|분기별|소진시까지', t): return "모집중"
    if re.search(r'신규.?모집.?없음|모집.?계획.?없음|미시행|해당없음', t): return "미정"

    m = re.search(r'~\s*(\d{4})[.\s]*(\d{1,2})[.\s]*(\d{1,2})', t)
    if m:
        try:
            end = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if end < TODAY: return "마감"
        except: pass

    m = re.search(r'(\d{4})[.\s]*(\d{1,2})[.\s]*(\d{1,2})', t)
    if m:
        try:
            start = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return "모집예정" if start > TODAY else "모집중"
        except: pass

    m = re.search(r'(\d{1,2})월.*?~.*?(\d{1,2})월', t)
    if m:
        sm, em = int(m.group(1)), int(m.group(2))
        if CUR_M > em:  return "마감"
        if CUR_M < sm:  return "모집예정"
        return "확인필요"

    if '상반기' in t: return "확인필요"
    if '하반기' in t: return "모집예정"

    m = re.search(r'(\d{1,2})월', t)
    if m:
        month = int(m.group(1))
        if month < CUR_M: return "마감"
        if month == CUR_M: return "확인필요"
        return "모집예정"

    return "미정"

# ── 온통청년 API ─────────────────────────────────────────────
def fetch_api_page(page=1, per_page=100, keyword=""):
    params = {
        "openApiVlak": API_KEY,
        "pageIndex": page,
        "display": per_page,
        "srchCtpvCd": "41",
    }
    if keyword:
        params["query"] = keyword
    for url in BASE_URLS:
        try:
            r = requests.get(url, params=params, timeout=20, allow_redirects=False)
            if r.status_code in (301, 302, 303):
                print(f"  API 리다이렉트 ({r.status_code}): {url} → 다음 엔드포인트 시도")
                continue
            r.encoding = "utf-8"
            root = ET.fromstring(r.text)
            if root.find(".//youthPolicy") is not None or root.findtext(".//totalCount"):
                return root
        except Exception as e:
            print(f"  API 오류 ({url}): {e}")
    print("  ⚠️ 모든 API 엔드포인트 실패")
    return None

def parse_api_item(item):
    ssg = item.findtext("ssgNm", "")
    ssg = ssg.replace("경기도", "").strip() if "경기도" in ssg else ssg
    field_code = item.findtext("polyBizSecd", "")
    시기 = item.findtext("rqutPrdCn", "")
    return {
        "시군":     ssg or "경기도",
        "분야":     FIELD_MAP.get(field_code, item.findtext("polyBizSecdNm", "기타")),
        "사업명":   item.findtext("polyBizSjnm", ""),
        "주요내용": item.findtext("polyItcnCn", ""),
        "모집시기": 시기,
        "모집상태": get_status(시기),
        "신청방법": item.findtext("rqutUrla", ""),
        "운영기관": item.findtext("cnsgNmor", ""),
        "문의처":   item.findtext("inqisCn", ""),
        "링크":     item.findtext("aplctnUrla", ""),
        "링크_모집":   item.findtext("aplctnUrla", ""),
        "링크_전년도": "",
        "출처":     "온통청년API",
        "갱신일":   TODAY.strftime("%Y-%m-%d"),
    }

# ── 확인필요 항목 키워드 검색 ────────────────────────────────
def search_active(policy_name):
    keyword = re.sub(r'[^\w]', ' ', policy_name.replace("경기", "").replace("청년", "")).strip()
    if len(keyword) < 2:
        keyword = policy_name
    root = fetch_api_page(keyword=keyword)
    if root is None:
        return None
    for item in root.findall(".//youthPolicy"):
        name = item.findtext("polyBizSjnm", "")
        core = [w for w in keyword.split() if len(w) >= 2]
        if any(w in name for w in core):
            period = item.findtext("rqutPrdCn", "")
            if get_status(period) == "모집중":
                link = item.findtext("aplctnUrla", "") or item.findtext("rqutUrla", "")
                return {"link": link, "period": period}
    return None

# ── 경기도 일자리재단 OpenAPI (JobFndtnSportPolocy) ──────────
DIV_TO_FIELD = {
    "구직활동 지원": "일자리",
    "재직 지원":     "일자리",
    "기업 지원":     "일자리",
    "생활 지원":     "금융·복지·문화",
    "주거 지원":     "주거",
}

def fetch_jobfndtn_api():
    results = []
    url = "https://openapi.gg.go.kr/JobFndtnSportPolocy"
    page = 1
    total = None
    while True:
        try:
            r = requests.get(url, params={
                "KEY": JOBABA_KEY, "Type": "json",
                "pIndex": page, "pSize": 1000,
            }, timeout=20)
            data = r.json()
            body = data.get("JobFndtnSportPolocy", [{}])
            if len(body) < 2:
                break
            if total is None:
                total = int(body[0].get("list_total_count", 0))
            rows = body[1].get("row", [])
            for row in rows:
                begin = row.get("RECRUT_BEGIN_DE", "")
                end   = row.get("RECRUT_END_DE", "")
                if end:
                    try:
                        end_dt = datetime.strptime(end, "%Y%m%d")
                        status = "마감" if end_dt < TODAY else "모집중"
                    except:
                        status = "확인필요"
                elif begin:
                    status = "모집중"
                else:
                    status = "확인필요"

                시기 = ""
                if begin and end:
                    시기 = f"{begin[:4]}.{begin[4:6]}.{begin[6:]} ~ {end[:4]}.{end[4:6]}.{end[6:]}"
                elif begin:
                    시기 = f"{begin[:4]}.{begin[4:6]}.{begin[6:]} ~"

                div_nm = row.get("DIV_NM") or ""
                분야 = DIV_TO_FIELD.get(div_nm, "일자리")
                region = row.get("REGION_NM") or "경기도"

                results.append({
                    "시군":     region if region != "경기" else "경기도",
                    "분야":     분야,
                    "사업명":   row.get("PBLANC_TITLE", ""),
                    "주요내용": "",
                    "모집시기": 시기,
                    "모집상태": status,
                    "신청방법": "잡아바 온라인 신청",
                    "운영기관": row.get("INST_NM", ""),
                    "문의처":   "",
                    "링크":     row.get("DETAIL_PAGE_URL", ""),
                    "링크_모집":row.get("DETAIL_PAGE_URL", ""),
                    "링크_전년도": "",
                    "출처":     "경기일자리재단API",
                    "갱신일":   TODAY.strftime("%Y-%m-%d"),
                })
            if len(rows) < 1000:
                break
            page += 1
        except Exception as e:
            print(f"  경기일자리재단 API 오류: {e}")
            break
    print(f"  경기일자리재단 API: {len(results)}건 (전체 {total}건)")
    return results

# ── 잡아바 크롤링 ────────────────────────────────────────────
def scrape_jobaba():
    results = []
    FIXED = [
        {"사업명": "경기도 청년기본소득", "분야": "금융ㆍ복지ㆍ문화",
         "url": "https://apply.jobaba.net/special/gibon/main.do",
         "모집시기": "분기별 신청 (1분기:3월, 2분기:6월, 3분기:9월, 4분기:12월)",
         "문의처": "1877-0566"},
    ]
    if not BS4_OK:
        for p in FIXED:
            results.append(_make_gyeonggi_item(p))
        return results

    try:
        r = requests.get("https://apply.jobaba.net/bsns/bsnsListView.do",
                         headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select(".bsns-item, .list-bsns li, .program-item")
        for item in items:
            title_el = item.select_one(".bsns-nm, .tit, h3, strong")
            link_el  = item.select_one("a")
            if not title_el: continue
            name = title_el.get_text(strip=True)
            if not name or "청년" not in name: continue
            link = ""
            if link_el and link_el.get("href"):
                href = link_el["href"]
                link = href if href.startswith("http") else f"https://apply.jobaba.net{href}"
            results.append({
                "시군":"경기도","분야":"일자리","사업명":name,
                "주요내용":"","모집시기":"","모집상태":"확인필요",
                "신청방법":"잡아바 온라인 신청","운영기관":"경기도일자리재단",
                "문의처":"","링크":link,"링크_모집":link,"링크_전년도":"",
                "출처":"잡아바","갱신일":TODAY.strftime("%Y-%m-%d"),
            })
    except Exception as e:
        print(f"  잡아바 크롤링 오류: {e}")

    for p in FIXED:
        if not any(r["사업명"] == p["사업명"] for r in results):
            results.append(_make_gyeonggi_item(p))

    return results

def _make_gyeonggi_item(p):
    return {
        "시군":"경기도","분야":p.get("분야","금융ㆍ복지ㆍ문화"),
        "사업명":p["사업명"],"주요내용":"",
        "모집시기":p.get("모집시기",""),"모집상태":"모집중",
        "신청방법":"잡아바 온라인 신청","운영기관":"경기도일자리재단",
        "문의처":p.get("문의처",""),"링크":p["url"],
        "링크_모집":p["url"],"링크_전년도":"",
        "출처":"잡아바","갱신일":TODAY.strftime("%Y-%m-%d"),
    }

# ── 경기복지포털 ─────────────────────────────────────────────
def scrape_gg24():
    results = []
    FIXED = [
        {"사업명":"경기 고립은둔청년 지원사업","분야":"금융ㆍ복지ㆍ문화",
         "url":"https://gg24.gg.go.kr/svcreqst/selectSvcReqst.do?sch_tab_code=10&svc_seq=945",
         "모집상태":"모집중","문의처":"031-267-9100"},
    ]
    if not BS4_OK:
        for p in FIXED:
            results.append({**_make_gyeonggi_item(p), "운영기관":"경기복지재단","출처":"경기복지포털"})
        return results

    try:
        url = "https://gg24.gg.go.kr/svcreqst/selectSvcReqstList.do?sch_tab_code=10"
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select("li.item, .svc-item, .list-item"):
            title_el = item.select_one(".svc-nm, .tit, h3, a")
            if not title_el: continue
            name = title_el.get_text(strip=True)
            if not name or "청년" not in name: continue
            link_el = item.select_one("a")
            link = ""
            if link_el and link_el.get("href"):
                href = link_el["href"]
                link = href if href.startswith("http") else f"https://gg24.gg.go.kr{href}"
            results.append({
                "시군":"경기도","분야":"금융ㆍ복지ㆍ문화","사업명":name,
                "주요내용":"","모집시기":"","모집상태":"확인필요",
                "신청방법":"경기복지포털 온라인 신청","운영기관":"경기복지재단",
                "문의처":"031-267-9100","링크":link,"링크_모집":link,"링크_전년도":"",
                "출처":"경기복지포털","갱신일":TODAY.strftime("%Y-%m-%d"),
            })
    except Exception as e:
        print(f"  경기복지포털 오류: {e}")

    for p in FIXED:
        if not any(r["사업명"] == p["사업명"] for r in results):
            results.append({
                "시군":"경기도","분야":p["분야"],"사업명":p["사업명"],
                "주요내용":"","모집시기":"","모집상태":p["모집상태"],
                "신청방법":"경기복지포털 온라인 신청","운영기관":"경기복지재단",
                "문의처":p["문의처"],"링크":p["url"],"링크_모집":p["url"],"링크_전년도":"",
                "출처":"경기복지포털","갱신일":TODAY.strftime("%Y-%m-%d"),
            })
    return results

# ── 경기청년포털 ─────────────────────────────────────────────
def scrape_gyeonggi_youth():
    results = []
    if not BS4_OK:
        return results
    urls = [
        "https://youth.gg.go.kr/gg/intro/youth-policy-list.do",
        "https://youth.gg.go.kr/gg/archive-policy-search.do?mode=list&srSido=gyeonggi",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            for item in soup.select(".policy-item, .list-item, article, .card"):
                title_el = item.select_one("h3, h4, .title, .tit, strong")
                link_el  = item.select_one("a")
                if not title_el: continue
                name = title_el.get_text(strip=True)
                if not name: continue
                link = ""
                if link_el and link_el.get("href"):
                    href = link_el["href"]
                    link = href if href.startswith("http") else f"https://youth.gg.go.kr{href}"
                results.append({
                    "시군":"경기도","분야":"기타","사업명":name,
                    "주요내용":"","모집시기":"","모집상태":"확인필요",
                    "신청방법":"","운영기관":"경기도",
                    "문의처":"","링크":link,"링크_모집":link,"링크_전년도":"",
                    "출처":"경기청년포털","갱신일":TODAY.strftime("%Y-%m-%d"),
                })
        except Exception as e:
            print(f"  경기청년포털 오류: {e}")
    return results

# ── 31개 시군 공고게시판 ──────────────────────────────────────
def scrape_sigungu(existing_data):
    if not BS4_OK:
        print("  beautifulsoup4 없어 시군 크롤링 스킵")
        return []

    try:
        with open("sites.json", "r", encoding="utf-8") as f:
            sites = json.load(f)
    except Exception as e:
        print(f"  sites.json 읽기 오류: {e}")
        return []

    existing_links = {d.get("링크","") for d in existing_data if d.get("링크")}
    existing_names = {d.get("사업명","") for d in existing_data}
    YOUTH_KW = ["청년","청소년지원","청년지원","청년정책","청년취업","청년주거","청년창업"]
    results = []

    for site in sites:
        시군 = site.get("city") or site.get("시군", "")
        url  = site["url"]
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.encoding = r.apparent_encoding or "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            rows = []
            for sel in [".bdList li","table tr",".board-list tr",".list-item","li"]:
                rows = soup.select(sel)
                if len(rows) > 2: break

            for row in rows:
                link_el = row.select_one("a")
                if not link_el: continue
                title = link_el.get_text(strip=True)
                if not title or len(title) < 4: continue
                if not any(kw in title for kw in YOUTH_KW): continue
                href = link_el.get("href","")
                full_link = (href if href.startswith("http")
                             else f"https://{url.split('/')[2]}{href}" if href.startswith("/")
                             else url)
                if full_link in existing_links: continue
                if any(title[:8] in name for name in existing_names if len(name) > 4):
                    for d in existing_data:
                        if d.get("시군")==시군 and title[:8] in d.get("사업명",""):
                            if d.get("모집상태") != "모집중":
                                d["모집상태"] = "모집중"
                                d["링크_모집"] = full_link
                    continue
                results.append({
                    "시군":시군,"분야":"기타","사업명":title,
                    "주요내용":"","모집시기":"","모집상태":"모집중",
                    "신청방법":"","운영기관":"","문의처":"",
                    "링크":full_link,"링크_모집":full_link,"링크_전년도":"",
                    "출처":f"{시군}공고게시판","갱신일":TODAY.strftime("%Y-%m-%d"),
                })
                existing_links.add(full_link)
                print(f"  🆕 [{시군}] {title[:30]}")
        except Exception as e:
            print(f"  ⚠️ [{시군}] {type(e).__name__}")
        time.sleep(0.3)

    return results

# ── 네이버 뉴스 RSS ──────────────────────────────────────────
def search_naver_news(existing_data):
    existing_links = {d.get("링크","") for d in existing_data if d.get("링크")}
    existing_names = {d.get("사업명","") for d in existing_data}
    QUERIES = [
        "경기도 청년 모집 공고", "경기청년 지원사업 신청",
        "경기 청년정책 신규", "수원시 청년 모집",
        "성남시 청년 지원", "용인시 청년 모집",
    ]
    YOUTH_KW   = ["청년","청년정책","청년지원","청년모집"]
    EXCLUDE_KW = ["부동산","주식","투자","광고","대출금리","분양"]
    results = []
    seen   = set()

    for query in QUERIES:
        try:
            encoded = urllib.parse.quote(query)
            url = (f"https://s.search.naver.com/p/newssearch/search.naver"
                   f"?query={encoded}&where=news&pd=4&sort=1&field=0&start=1&display=10&format=rss")
            r = requests.get(url, headers={**HEADERS,"Referer":"https://search.naver.com"}, timeout=10)
            root = ET.fromstring(r.content)

            for item in root.findall(".//item"):
                title_el = item.find("title")
                link_el  = item.find("link")
                desc_el  = item.find("description")
                if title_el is None: continue
                title = re.sub(r'<[^>]+>','', title_el.text or "").strip()
                link  = link_el.text.strip() if link_el is not None and link_el.text else ""
                desc  = re.sub(r'<[^>]+>','', desc_el.text or "").strip() if desc_el is not None else ""

                if not any(kw in title for kw in YOUTH_KW): continue
                if any(ex in title for ex in EXCLUDE_KW): continue
                if not any(city in title+desc for city in GYEONGGI_CITIES): continue
                if link in seen or link in existing_links: continue
                if any(title[:8] in name for name in existing_names if len(name) > 4): continue

                seen.add(link)
                시군 = "경기도"
                for city in GYEONGGI_CITIES:
                    if city in title and city != "경기":
                        시군 = city + ("" if city.endswith(("시","군")) else "시")
                        break

                results.append({
                    "시군":시군,"분야":"기타","사업명":title[:60],
                    "주요내용":desc[:200],"모집시기":"","모집상태":"확인필요",
                    "신청방법":"","운영기관":"","문의처":"",
                    "링크":link,"링크_모집":link,"링크_전년도":"",
                    "출처":"네이버뉴스RSS","갱신일":TODAY.strftime("%Y-%m-%d"),
                    "메모":f"뉴스 자동감지 - 담당자 확인 필요",
                })
                print(f"  📰 [{시군}] {title[:35]}")
        except Exception as e:
            print(f"  뉴스RSS 오류: {type(e).__name__}")
        time.sleep(0.5)

    return results

# ── 메인 ────────────────────────────────────────────────────
def main():
    print(f"[{TODAY.strftime('%Y-%m-%d')}] 청년정책 데이터 갱신 시작")

    # 기존 데이터 로드
    try:
        with open("data.json","r",encoding="utf-8") as f:
            existing = json.load(f)
        print(f"기존: {len(existing)}개")
    except:
        existing = []
        print("기존 data.json 없음")

    updated = []
    check_list = []

    # 상태 재계산
    for d in existing:
        if d.get("링크_모집") and d.get("모집상태") == "모집중" and d.get("출처") == "수동추가":
            updated.append(d); continue
        new_status = get_status(d.get("모집시기",""))
        d["모집상태"] = new_status
        d.setdefault("링크_모집","")
        d.setdefault("링크_전년도","")
        if new_status == "확인필요":
            check_list.append(d)
        updated.append(d)

    # 확인필요 → API 검색
    print(f"\n확인필요 {len(check_list)}개 API 검색...")
    confirmed = 0
    for d in check_list:
        result = search_active(d.get("사업명",""))
        if result:
            d["모집상태"] = "모집중"
            d["링크_모집"] = result["link"]
            d["모집시기"]  = result["period"]
            confirmed += 1
        else:
            d["모집상태"] = "모집예정"
    print(f"확인 완료: {confirmed}개 모집중")

    existing_names = {d.get("사업명","") for d in updated}

    def add_new(items, label):
        added = 0
        for item in items:
            name = item.get("사업명","")
            if name and len(name) > 2 and name not in existing_names:
                item["모집상태"] = get_status(item.get("모집시기","")) or item.get("모집상태","미정")
                updated.append(item)
                existing_names.add(name)
                added += 1
        print(f"{label}: {added}개 추가")

    # 각 소스 수집
    print("\n온통청년 API...")
    first = fetch_api_page(1)
    if first is not None:
        total = int(first.findtext(".//totalCount","0") or 0)
        api_items = [parse_api_item(i) for i in first.findall(".//youthPolicy")]
        for page in range(2, math.ceil(total/100)+1):
            root = fetch_api_page(page)
            if root: api_items.extend([parse_api_item(i) for i in root.findall(".//youthPolicy")])
        add_new(api_items, "온통청년 API")

    print("\n경기일자리재단 API...")
    add_new(fetch_jobfndtn_api(), "경기일자리재단API")

    print("\n잡아바...")
    add_new(scrape_jobaba(), "잡아바")

    print("\n경기복지포털...")
    add_new(scrape_gg24(), "경기복지포털")

    print("\n경기청년포털...")
    add_new(scrape_gyeonggi_youth(), "경기청년포털")

    print("\n31개 시군 게시판...")
    sigungu_new = scrape_sigungu(updated)
    add_new(sigungu_new, "시군게시판")

    print("\n네이버 뉴스 RSS...")
    add_new(search_naver_news(updated), "네이버뉴스")

    # 안전 장치: 기존 데이터보다 현저히 적으면 저장 중단
    MIN_ITEMS = 10
    if len(existing) >= MIN_ITEMS and len(updated) < len(existing) * 0.5:
        print(f"\n⚠️ 안전 중단: 기존 {len(existing)}개 → 수집 {len(updated)}개 (50% 미만)")
        print("  data.json을 덮어쓰지 않습니다. API/스크래핑 오류를 확인하세요.")
        return

    # 저장
    with open("data.json","w",encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)

    status_count = Counter(d.get("모집상태","미정") for d in updated)
    print(f"\n✅ 완료: 총 {len(updated)}개")
    for k,v in sorted(status_count.items()):
        print(f"  {k}: {v}개")

if __name__ == "__main__":
    main()
