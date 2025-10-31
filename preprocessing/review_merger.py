import os
import json
import re
from natsort import natsorted

def merge_json_files(base_dir):
    input_dir = os.path.join(base_dir, "data", "review_number")
    output_dir = os.path.join(base_dir, "data", "review")

    if not os.path.exists(input_dir):
        print(f"[ERROR] 입력 디렉토리 없음: {input_dir}")
        return

    os.makedirs(output_dir, exist_ok=True)

    # ✅ 테스트용: 특정 폴더만 지정
    category_list = ["concealer"]   # ← 여기에 원하는 폴더 이름 입력 (예: ["blush"], ["concealer"] 등)

    for category in category_list:
        category_path = os.path.join(input_dir, category)
        if not os.path.isdir(category_path):
            print(f"[WARN] 폴더 없음: {category_path}")
            continue

        print(f"\n[INFO] '{category}' 폴더 처리 중...")

        # preprocessed / raw 두 가지 타입 처리
        for file_type in ["preprocessed", "raw"]:
            pattern = re.compile(rf"oliveyoung_{category}_(\d+)_reviews_{file_type}\.json$")
            json_files = [
                f for f in os.listdir(category_path) if pattern.match(f)
            ]

            if not json_files:
                print(f"  - '{file_type}' 파일 없음, 건너뜀.")
                continue

            # 숫자 순으로 정렬
            json_files = natsorted(json_files, key=lambda x: int(pattern.match(x).group(1)))

            merged_data = []
            for fname in json_files:
                fpath = os.path.join(category_path, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            merged_data.extend(data)
                        else:
                            merged_data.append(data)
                except Exception as e:
                    print(f"  [ERROR] 파일 읽기 실패: {fname} -> {e}")

            # 결과 파일명 (출력 위치는 review/)
            output_name = f"oliveyoung_{category}_reviews_{file_type}.json"
            output_path = os.path.join(output_dir, output_name)

            # 저장
            with open(output_path, "w", encoding="utf-8") as out_f:
                json.dump(merged_data, out_f, ensure_ascii=False, indent=2)

            print(f"  ✅ {len(merged_data)}개 항목 병합 완료 -> {output_path}")


if __name__ == "__main__":
    # 현재 파일 위치: cosmetic/preprocessing/review_merger.py
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    merge_json_files(BASE_DIR)
