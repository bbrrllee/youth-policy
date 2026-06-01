"""
온통청년 API → data.json 자동 갱신 + 확인필요 항목 공고 자동 검색
매일 GitHub Actions에서 실행됩니다.
"""
import os, json, requests, xml.etree.ElementTree as ET, math, re
from datetime import datetime

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

    # 온통청년 API 전체 수집 (신규 정책 추가)
    print("\n온통청년 API 전체 수집...")
    first = fetch_api_page(1)
    if first is not None:
        total = int(first.findtext(".//totalCount", "0") or 0)
        api_items = [parse_item(i) for i in first.findall(".//youthPolicy")]

        for page in range(2, math.ceil(total / 100) + 1):
            root = fetch_api_page(page)
            if root:
                api_items.extend([parse_item(i) for i in root.findall(".//youthPolicy")])

        # 기존에 없는 신규 정책만 추가
        existing_names = {d.get("사업명", "") for d in updated}
        new_items = [i for i in api_items if i["사업명"] not in existing_names]
        for item in new_items:
            item["모집상태"] = get_status(item["모집시기"])
        updated.extend(new_items)
        print(f"신규 정책 추가: {len(new_items)}개")

    # 최종 저장
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)

    # 요약
    from collections import Counter
    status_count = Counter(d.get("모집상태","미정") for d in updated)
    print(f"\n✅ 완료: 총 {len(updated)}개")
    for k, v in sorted(status_count.items()):
        print(f"  {k}: {v}개")

if __name__ == "__main__":
    main()
