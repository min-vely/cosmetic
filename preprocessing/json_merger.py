import json
import os
from collections import defaultdict

# ---------------- 파일 경로 ----------------
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# PRODUCT_JSON_PATH = os.path.join(BASE_DIR, "oliveyoung_lip_makeup.json")
# REVIEW_JSON_PATH = os.path.join(BASE_DIR, "oliveyoung_lip_makeup_reviews_preprocessed.json")
# OUTPUT_JSON_PATH = os.path.join(BASE_DIR, "oliveyoung_lip_makeup_merged.json")

PRODUCT_JSON_PATH = "../data/oliveyoung_lip_makeup.json"
REVIEW_JSON_PATH = "../data/oliveyoung_lip_makeup_reviews_preprocessed.json"
OUTPUT_JSON_PATH = "../data/oliveyoung_lip_makeup_merged.json"


# ---------------- JSON 불러오기 ----------------
with open(PRODUCT_JSON_PATH, "r", encoding="utf-8") as f:
    products = json.load(f)

with open(REVIEW_JSON_PATH, "r", encoding="utf-8") as f:
    reviews = json.load(f)

# ---------------- 해시맵으로 그룹화 ----------------
# product_name -> list of products
product_map = defaultdict(list)
for p in products:
    product_map[p["product_name"]].append(p)

# product_name -> list of reviews
review_map = defaultdict(list)
for r in reviews:
    review_map[r["product_name"]].append(r)

merged_data = []

# ---------------- 병합 ----------------
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
            # 리뷰가 있으면 texts 리스트로 추가
            texts = []
            for mr in matched_reviews:
                for key in sorted(mr.keys()):
                    if key.startswith("text"):
                        texts.append(mr[key])
            merged_item["texts"] = texts
        else:
            # 리뷰가 없으면 texts를 빈 리스트로
            merged_item["texts"] = []

        merged_data.append(merged_item)



# ---------------- JSON 저장 ----------------
with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(merged_data, f, ensure_ascii=False, indent=2)

print(f"{len(merged_data)}건 병합 완료 -> {OUTPUT_JSON_PATH}")
