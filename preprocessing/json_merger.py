import json
import os
import re
from collections import defaultdict

# ---------------- 폴더 경로 ----------------
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")
REVIEW_DIR = os.path.join(DATA_DIR, "review")
MERGED_DIR = os.path.join(DATA_DIR, "merged")

os.makedirs(MERGED_DIR, exist_ok=True)


# ---------------- 병합 함수 ----------------
def merge_product_and_review(product_path, review_path, output_path):
    # ---------------- JSON 불러오기 ----------------
    with open(product_path, "r", encoding="utf-8") as f:
        products = json.load(f)

    with open(review_path, "r", encoding="utf-8") as f:
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
                if code_name and review_name and code_name.strip() == review_name.strip():
                    matched_reviews.append(r)

            # 🎯 예외 케이스: product_name 내 code_name 1개, review_name 1개면 무조건 병합
            if not matched_reviews:
                unique_code_names = {pp.get("code_name", "").strip() for pp in product_list if pp.get("code_name")}
                unique_review_names = {rr.get("review_name", "").strip() for rr in review_list if rr.get("review_name")}

                if len(unique_code_names) == 1 and len(unique_review_names) == 1:
                    matched_reviews = review_list.copy()  # 전부 병합

            merged_item = p.copy()

            if matched_reviews:
                texts = []
                for mr in matched_reviews:
                    # '등록된 리뷰가 없습니다' 문구가 포함되어 있으면 스킵
                    if any("등록된 리뷰가 없습니다" in str(v) for v in mr.values()):
                        continue

                    text_keys = [k for k in mr.keys() if k.startswith("text")]
                    # text 뒤의 숫자 기준으로 정렬 (ex. text1, text2, ..., text100)
                    text_keys.sort(key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0)

                    for key in text_keys:
                        val = str(mr[key]).strip()
                        if val and "등록된 리뷰가 없습니다" not in val:
                            texts.append(val)

                merged_item["texts"] = texts if texts else []
            else:
                merged_item["texts"] = []

            merged_data.append(merged_item)

    # ---------------- thumb_color 병합 ----------------
    merged_data = merge_thumb_color(merged_data)

    # ---------------- 중복 제거 ----------------
    merged_data = deduplicate_by_code_name(merged_data)

    # ---------------- JSON 저장 ----------------
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged_data, f, ensure_ascii=False, indent=2)

    print(f"{len(merged_data)}건 병합 완료 -> {output_path}")


# ---------------- thumb_color 병합 ----------------
def merge_thumb_color(items):
    name_to_indices = defaultdict(list)
    for i, item in enumerate(items):
        code_name = item.get("code_name", "")
        if code_name:
            name_to_indices[code_name].append(i)

    for i, item in enumerate(items):
        code_name = item.get("code_name", "")
        combined_thumbs = set()

        current_thumbs = item.get("thumb_color", [])
        if isinstance(current_thumbs, str):
            current_thumbs = [current_thumbs]
        combined_thumbs.update(current_thumbs)

        for idx in name_to_indices.get(code_name, []):
            thumbs = items[idx].get("thumb_color", [])
            if isinstance(thumbs, str):
                thumbs = [thumbs]
            combined_thumbs.update(thumbs)

        item["thumb_color"] = list(combined_thumbs)

    return items


# ---------------- 중복 제거 ----------------
def deduplicate_by_code_name(items):
    grouped = defaultdict(list)
    for item in items:
        grouped[item.get("product_name", "")].append(item)

    unique_items = []
    for pname, group in grouped.items():
        seen = set()
        for item in group:
            code_name = item.get("code_name", "")
            if code_name in seen:
                continue
            seen.add(code_name)
            unique_items.append(item)

    return unique_items


# ---------------- 메인 실행 ----------------
if __name__ == "__main__":
    for fname in os.listdir(DATA_DIR):
        if not fname.startswith("oliveyoung_") or not fname.endswith(".json"):
            continue
        if "merged" in fname:
            continue  # 이미 병합된 파일은 스킵

        base_name = fname.replace("oliveyoung_", "").replace(".json", "")
        review_fname = f"oliveyoung_{base_name}_reviews_preprocessed.json"

        product_path = os.path.join(DATA_DIR, fname)
        review_path = os.path.join(REVIEW_DIR, review_fname)
        output_path = os.path.join(MERGED_DIR, f"oliveyoung_{base_name}_merged.json")

        if not os.path.exists(review_path):
            print(f"⚠️ 리뷰 파일 없음: {review_fname}")
            continue

        merge_product_and_review(product_path, review_path, output_path)