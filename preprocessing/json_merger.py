import json
import os
from collections import defaultdict

# ---------------- 파일 경로 ----------------
PRODUCT_JSON_PATH = "../data/oliveyoung_lip_makeup.json"
REVIEW_JSON_PATH = "../data/oliveyoung_lip_makeup_reviews_preprocessed.json"
OUTPUT_JSON_PATH = "../data/oliveyoung_lip_makeup_merged.json"

# ---------------- JSON 불러오기 ----------------
with open(PRODUCT_JSON_PATH, "r", encoding="utf-8") as f:
    products = json.load(f)

with open(REVIEW_JSON_PATH, "r", encoding="utf-8") as f:
    reviews = json.load(f)

# ---------------- 해시맵으로 그룹화 ----------------
product_map = defaultdict(list)
for p in products:
    product_map[p["product_name"]].append(p)

review_map = defaultdict(list)
for r in reviews:
    review_map[r["product_name"]].append(r)

merged_data = []

# ---------------- 리뷰 병합 ----------------
for pname, product_list in product_map.items():
    review_list = review_map.get(pname, [])

    for p in product_list:
        code_name = p.get("code_name", "")
        matched_reviews = []

        # code_name과 review_name 부분 매칭
        for r in review_list:
            review_name = r.get("review_name", "")
            if code_name and review_name and (code_name in review_name or review_name in code_name):
                matched_reviews.append(r)

        merged_item = p.copy()

        if matched_reviews:
            texts = []
            for mr in matched_reviews:
                for key in sorted(mr.keys()):
                    if key.startswith("text"):
                        texts.append(mr[key])
            merged_item["texts"] = texts
        else:
            merged_item["texts"] = []

        merged_data.append(merged_item)

# ---------------- thumb_color 병합 ----------------
def merge_thumb_color(items):
    """
    code_name 단어 기준으로 thumb_color 합치기
    """
    name_to_indices = defaultdict(list)
    for i, item in enumerate(items):
        words = item["code_name"].split()
        for word in words:
            name_to_indices[word].append(i)

    for i, item in enumerate(items):
        combined_thumbs = set()
        # 기존 thumb_color를 리스트로 변환 (혹시 str로 되어있다면)
        current_thumbs = item.get("thumb_color", [])
        if isinstance(current_thumbs, str):
            current_thumbs = [current_thumbs]
        combined_thumbs.update(current_thumbs)

        words = item["code_name"].split()
        for word in words:
            for idx in name_to_indices[word]:
                thumbs = items[idx].get("thumb_color", [])
                if isinstance(thumbs, str):
                    thumbs = [thumbs]
                combined_thumbs.update(thumbs)

        item["thumb_color"] = list(combined_thumbs)

    return items

merged_data = merge_thumb_color(merged_data)

# ---------------- 중복 제거 ----------------
def deduplicate_by_code_name(items):
    """
    code_name 부분 문자열 기준으로 동일 제품 그룹 중 첫 번째만 남기기
    """
    seen = set()
    unique_items = []

    for item in items:
        code_name = item.get("code_name", "")
        if any(code_name in s or s in code_name for s in seen):
            continue
        seen.add(code_name)
        unique_items.append(item)

    return unique_items

merged_data = deduplicate_by_code_name(merged_data)

# ---------------- JSON 저장 ----------------
with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(merged_data, f, ensure_ascii=False, indent=2)

print(f"{len(merged_data)}건 병합 완료 -> {OUTPUT_JSON_PATH}")
