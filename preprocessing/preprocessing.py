import os
import json
import re
import unicodedata

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
        # 용량/종류/개/색상 관련 표현 제거, 앞뒤 언더바(_) 포함
        name = re.sub(r'([_\s]*\d+(\.\d+)?\s*(g|ml|oz|종|개|colors|color|컬러|칼라|입|개입))+', '', name, flags=re.IGNORECASE)
        # N회분 제거
        name = re.sub(r'\b\d+\s*회분\b', '', name)
        # '더블기획' 같은 복합형 표현 먼저 제거 (앞뒤가 공백, 시작/끝, 또는 특수문자인 경우만)
        name = re.sub(r'[_\s]*?(더블\s*기획|듀오\s*기획|더블\s*세트|기획\s*세트)[_\s]*?', '', name)
        # 단품/기획/모음전/한정 기획 제거
        name = re.sub(r'\b(단품|기획|모음전|한정\s*기획)\b', '', name)
        # '리필' 단독 제거 (앞뒤가 공백, 시작/끝, 또는 특수문자인 경우만)
        name = re.sub(r'(?<!\w)리필(?!\w)', '', name)
        # "중 택1", "중 택2", "택1", "택2", "택 1" 등 제거
        name = re.sub(r'\b중\s*택\s*\d+\b', '', name)
        name = re.sub(r'\b택\s*\d+\b', '', name)
        # 불필요한 슬래시(/) 정리 (앞뒤 공백 포함)
        name = re.sub(r'\s*/\s*', ' ', name)
        # 중복 공백 제거 + 양쪽 공백 제거
        name = re.sub(r'\s+', ' ', name).strip()
        return name

    @classmethod
    def clean_code_name(cls, code: str) -> str:
        if not code:
            return ""

        # 1. 특수 공백 문자 제거 (\u3000, \xa0, \u200b 등)
        code = code.replace("\u3000", " ").replace("\xa0", " ").replace("\u200b", " ")
        code = code.strip()

        # 2. 줄바꿈 이후 내용 제거 (가격 등 불필요한 텍스트)
        code = re.sub(r'\n.*$', '', code).strip()

        # 3. 전각 문자 → 반각 문자 변환
        code = unicodedata.normalize("NFKC", code)

        if code == "단품":
            return code

        # 4. 괄호 감싸짐 확인 → 양쪽 괄호와 공백만 제거 (내부 괄호가 없는 경우만)
        if re.fullmatch(r'^\[\s*[^\[\]]+\s*\]$', code):
            code = re.sub(r'^\[\s*(.*?)\s*\]$', r'\1', code).strip()
            wrapped = True
        elif re.fullmatch(r'^\(\s*[^\(\)]+\s*\)$', code):
            code = re.sub(r'^\(\s*(.*?)\s*\)$', r'\1', code).strip()
            wrapped = True
        else:
            wrapped = False


        # 5. 기존 전처리 적용 (괄호 안 내용 제거 등, 전체 괄호 감싸짐이 아닌 경우만)
        if not wrapped:
            code = re.sub(r'\[.*?\]', '', code)

        code = re.sub(r'\(품절\)', '', code)
        code = re.sub(r'\(.*?\)', '', code)
        code = re.sub(r'\b\d+\s*\+\s*\d+\b', '', code)
        code = re.sub(r'\bNEW\b', '', code, flags=re.IGNORECASE)
        code = re.sub(r'[\s_+/]?(단품|세트|기획)', '', code)
        code = re.sub(r'\*\s*\d+\s*개입', '', code)
        code = re.sub(r'\s+', ' ', code).strip()

        # 6. 숫자+단위 제거 (문자와 섞여 있는 경우만)
        num_unit_pattern = r'\d+(\.\d+)?\s*(g|ml|oz|종|개|Color|color|colors|Colors)\b'
        if re.search(num_unit_pattern, code, flags=re.IGNORECASE) and not re.fullmatch(num_unit_pattern, code, flags=re.IGNORECASE):
            code = re.sub(num_unit_pattern, '', code, flags=re.IGNORECASE).strip()

        return code


    
    def preprocess(self):
        preprocessed = []
        seen = set()

        for p in self.products:
            new_product = p.copy()
            new_product['product_name'] = self.clean_product_name(p['product_name'])
            
            # code_name, review_name 모두 clean_code_name 적용
            if 'code_name' in p:
                new_product['code_name'] = self.clean_code_name(p['code_name'])
            if 'review_name' in p:
                new_product['review_name'] = self.clean_code_name(p['review_name'])

            key = (
                new_product['brand_name'],
                new_product['product_name'],
                new_product.get('code_name', ''),
                new_product.get('review_name', '')
            )
            if key not in seen:
                seen.add(key)
                preprocessed.append(new_product)
            else:
                print(f"중복 제거됨 -> brand: {new_product['brand_name']}, "
                    f"product: {new_product['product_name']}, "
                    f"code: {new_product.get('code_name', '')}, "
                    f"review: {new_product.get('review_name', '')}")

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
