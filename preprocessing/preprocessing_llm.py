import os
import json
from tqdm import tqdm
from llm_preprocessing import LLMProductNameCleaner  # llm_cleaner.py에서 LLM 처리 클래스

class LLMPreprocessor:
    def __init__(self, input_path, output_path):
        self.input_path = input_path
        self.output_path = output_path
        self.products = []

    def load_json(self):
        with open(self.input_path, "r", encoding="utf-8") as f:
            self.products = json.load(f)

    def preprocess(self):
        cleaner = LLMProductNameCleaner()
        preprocessed = []
        seen = set()  # 중복 제거

        for idx, p in enumerate(tqdm(self.products, desc="전처리 진행", unit="건"), 1):
            new_product = p.copy()
            # product_name과 code_name만 LLM으로 전처리
            new_product['product_name'] = cleaner.clean_product_name(p['product_name'])
            new_product['code_name'] = cleaner.clean_code_name(p['code_name'])

            # 중복 제거: brand_name + product_name + code_name + price
            key = (new_product['brand_name'], new_product['product_name'], new_product['code_name'], new_product['price'])
            if key not in seen:
                seen.add(key)
                preprocessed.append(new_product)
            else:
                # tqdm.write() 사용 -> 진행바 깨지지 않고 출력
                tqdm.write(f"[{idx}/{len(self.products)} 중복 제거] {new_product['brand_name']} - {new_product['product_name']} - {new_product['code_name']}")

        self.products = preprocessed

    def save_json(self):
        with open(self.output_path, "w", encoding="utf-8") as f:
            json.dump(self.products, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    INPUT_PATH = os.path.join(BASE_DIR, "..", "data", "oliveyoung_lip_makeup.json")
    OUTPUT_PATH = os.path.join(BASE_DIR, "..", "data", "oliveyoung_lip_makeup_llm.json")

    processor = LLMPreprocessor(
        input_path=INPUT_PATH,
        output_path=OUTPUT_PATH
    )
    processor.load_json()
    processor.preprocess()
    processor.save_json()
    print(f"{len(processor.products)}건 저장 완료 -> {processor.output_path}")
