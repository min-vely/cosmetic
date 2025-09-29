import os
import json
import re

class OliveYoungPreprocessor:
    def __init__(self, input_path, output_path):
        self.input_path = input_path
        self.output_path = output_path
        self.products = []

    def load_json(self):
        with open(self.input_path, "r", encoding="utf-8") as f:
            self.products = json.load(f)

    @classmethod
    def clean_product_name(self, name: str) -> str:
        # [] 안 내용 제거
        name = re.sub(r'\[.*?\]', '', name)
        # () 안 내용 제거
        name = re.sub(r'\(.*?\)', '', name)
        # 1+1, 1+2, 2+1 등 제거
        name = re.sub(r'\b\d+\s*\+\s*\d+\b', '', name)
        # 용량/종류/개/색상 관련 표현 제거
        name = re.sub(r'\b\d+(\.\d+)?\s*(g|ml|oz|종|개|COLOR|Colors|color|colors|Color)\b', '', name, flags=re.IGNORECASE)
        # 단품/기획/한정 기획 제거
        name = re.sub(r'\b(단품|기획|한정\s*기획)\b', '', name)
        # "중 택1", "중 택2", "택1", "택2" 제거
        name = re.sub(r'\b중\s*택\d+\b', '', name)
        name = re.sub(r'\b택\d+\b', '', name)
        # 불필요한 슬래시(/) 정리 (앞뒤 공백 포함)
        name = re.sub(r'\s*/\s*', ' ', name)
        # 중복 공백 제거 + 양쪽 공백 제거
        name = re.sub(r'\s+', ' ', name).strip()
        return name

    @classmethod
    def clean_code_name(self, code: str) -> str:
        code = code.strip()

        # 단독 "단품"이면 그대로 반환
        if code == "단품":
            return code

        # [] 안 내용 제거
        code = re.sub(r'\[.*?\]', '', code)
        # () 안 내용 제거 (대소문자 NEW 포함)
        code = re.sub(r'\(.*?\)', '', code)
        # (품절) 제거
        code = code.replace('(품절)', '')
        # \n 뒤 내용 제거
        code = re.sub(r'\n.*$', '', code)
        # 1+1, 1+2, 2+1 등 제거
        code = re.sub(r'\b\d+\s*\+\s*\d+\b', '', code)
        # NEW, New, new 등 단독 제거
        code = re.sub(r'\bNEW\b', '', code, flags=re.IGNORECASE)

        # 괄호 제거 후 남은 + 뒤 사은품 제거
        if '+' in code:
            code = code.split('+')[0].strip()

        # 앞 구분 문자(_, +, /, 공백)와 함께 '단품', '세트', '기획' 제거
        code = re.sub(r'[\s_+/]?(단품|세트|기획)', '', code)
        # 남은 공백 정리
        code = re.sub(r'\s+', ' ', code).strip()

        return code





    def preprocess(self):
        preprocessed = []
        seen = set()

        for p in self.products:
            new_product = p.copy()
            new_product['product_name'] = self.clean_product_name(p['product_name'])
            new_product['code_name'] = self.clean_code_name(p['code_name'])

            key = (
                new_product['brand_name'],
                new_product['product_name'],
                new_product['code_name']
            )
            if key not in seen:
                seen.add(key)
                preprocessed.append(new_product)
            else:
                # 🔍 디버깅: 중복된 항목 출력
                print(f"중복 제거됨 -> brand: {new_product['brand_name']}, "
                      f"product: {new_product['product_name']}, "
                      f"code: {new_product['code_name']}")

        self.products = preprocessed

    def save_json(self):
        with open(self.output_path, "w", encoding="utf-8") as f:
            json.dump(self.products, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    INPUT_PATH = os.path.join(BASE_DIR, "..", "data", "oliveyoung_lip_makeup.json")
    OUTPUT_PATH = os.path.join(BASE_DIR, "..", "data", "oliveyoung_lip_makeup_preprocessed.json")

    processor = OliveYoungPreprocessor(
        input_path=INPUT_PATH,
        output_path=OUTPUT_PATH
    )
    processor.load_json()
    processor.preprocess()
    processor.save_json()
    print(f"{len(processor.products)}건 저장 완료 -> {processor.output_path}")
