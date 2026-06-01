"""
온통청년 API → data.json 자동 갱신 스크립트
GitHub Actions에서 매일 실행됩니다.
"""
import os
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

API_KEY = os.environ.get("API_KEY", "c937731f-99f2-489c-a334-07bbfff0da0d")
BASE_URL = "https://www.youthcenter.go.kr/opi/youthPlcyList.do"

FIELD_MAP = {
    "023010": "일자리",
    "023020": "주거",
    "023030": "교육ㆍ직업훈련",
    "023040": "금융ㆍ복지ㆍ문화",
    "023050": "참여권리",
}

def fetch_page(page, per_page=100):
    params = {
        "openApiVlak": API_KEY,
        "pageIndex": page,
        "display": per_page,
        "srchCtpvCd": "41",  # 경기도
    }
    try:
        resp = requests.get(BASE_URL, params=params, timeout=30)
        resp.encoding = "utf-8"
        root = ET.fromstring(resp.text)
        return root
    except Exception as e:
        print(f"API 호출 오류 (page {page}): {e}")
        return None

def parse_policies(root):
    policies = []
    for item in root.findall(".//youthPolicy"):
        field_code = item.findtext("polyBizSecd", "")
        field_name = FIELD_MAP.get(field_code, item.findtext("polyBizSecdNm", "기타"))

        # 시군구 파싱 (경기도 수원시 → 수원시)
        ssg = item.findtext("ssgNm", "")
        if "경기도" in ssg:
            ssg = ssg.replace("경기도", "").strip()

        policies.append({
            "시군": ssg if ssg else "경기도",
            "분야": field_name,
            "사업명": item.findtext("polyBizSjnm", ""),
            "주요내용": item.findtext("polyItcnCn", ""),
            "모집시기": item.findtext("rqutPrdCn", ""),
            "신청방법": item.findtext("rqutUrla", ""),
            "운영기관": item.findtext("cnsgNmor", ""),
            "문의처": item.findtext("inqisCn", ""),
            "링크": item.findtext("aplctnUrla", ""),
            "출처": "온통청년API",
            "갱신일": datetime.now().strftime("%Y-%m-%d"),
        })
    return policies

def get_total_count(root):
    try:
        return int(root.findtext(".//totalCount", "0"))
    except:
        return 0

def main():
    print("온통청년 API 데이터 수집 시작...")

    # 기존 data.json 로드 (수동 입력 데이터 보존)
    existing = []
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            existing = json.load(f)
        print(f"기존 데이터: {len(existing)}개")
    except:
        print("기존 data.json 없음 - 새로 생성")

    # 수동 입력 데이터 분리 (출처가 없거나 '수동'인 것)
    manual_data = [d for d in existing if d.get("출처", "수동") in ("수동", "")]

    # API 데이터 수집
    first_page = fetch_page(1)
    if first_page is None:
        print("API 연결 실패. 기존 data.json 유지.")
        return

    total = get_total_count(first_page)
    print(f"경기도 정책 총 {total}개")

    api_policies = parse_policies(first_page)

    # 나머지 페이지
    import math
    total_pages = math.ceil(total / 100)
    for page in range(2, total_pages + 1):
        root = fetch_page(page)
        if root:
            api_policies.extend(parse_policies(root))
        print(f"  페이지 {page}/{total_pages} 완료")

    print(f"API 수집 완료: {len(api_policies)}개")

    # 합치기: 수동 데이터 + API 데이터
    merged = manual_data + api_policies
    print(f"최종 데이터: {len(merged)}개 (수동 {len(manual_data)}개 + API {len(api_policies)}개)")

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print("data.json 저장 완료!")

if __name__ == "__main__":
    main()
