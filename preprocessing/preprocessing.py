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
        # 1+1, 1+2, 2+1기획 등 제거
        name = re.sub(r'\b\d+\s*\+\s*\d+(?:\s*기획)?\b', '', name)
        # 용량/종류/개/색상 관련 표현 제거, 앞뒤 언더바(_) 포함 (단위 뒤에 공백, 특수문자, 문자열 끝이 오는 경우만)
        name = re.sub(
            r'([_\s]*\d+(\.\d+)?\s*(g|ml|oz|종|개|colors?|컬러|칼라|입|개입|회분))(?=[\s/_+.,*&xX×]|$)',
            '',
            name,
            flags=re.IGNORECASE
        )
        # N회분 제거
        name = re.sub(r'\b\d+\s*회분\b', '', name)
        # '더블기획' 같은 복합형 표현 먼저 제거 (앞뒤가 공백, 시작/끝, 또는 특수문자인 경우만)
        name = re.sub(r'[_\s]*?(더블\s*기획|듀오\s*기획|더블\s*세트|기획\s*세트|듀오\s*세트)[_\s]*?', '', name)
        # 숫자+단위+기획, 기획 단독 제거
        name = re.sub(r'([_\s]*\d+(\.\d+)?\s*(g|ml|oz|종|개|colors|color|컬러|칼라|입|개입|회분)?[_\s]*)?기획\b', '', name, flags=re.IGNORECASE)
        # 단품/모음전/한정 기획 등 제거
        name = re.sub(r'\b(단품|모음전|한정\s*기획|꿀조합|특별한정|특별한정기획|듀오팩|기프트세트|대용량팩)\b', '', name)
        # '리필' 단독 제거 (앞뒤가 공백, 시작/끝, 또는 특수문자인 경우만)
        name = re.sub(r'(?<!\w)리필(?!\w)', '', name)
        # "중 택1", "중 택2", "택1", "택2", "택 1" 등 제거
        name = re.sub(r'\b중\s*택\s*\d+\b', '', name)
        name = re.sub(r'\b택\s*\d+\b', '', name)
        # X숫자 또는 *숫자 제거 (예: X3, *2)
        name = re.sub(r'\s*(\*|[xX×])\d+', '', name)
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
        code = re.sub(r'\*\s*\d+\s*개입', '', code)
        code = re.sub(r'\s+', ' ', code).strip()        

        # 6. 숫자+단위 제거 (문자와 섞여 있는 경우만)
        num_unit_pattern = r'\d+(\.\d+)?\s*(g|ml|oz|종|개|Color|color|colors|Colors|컬러|칼라|입|개입|회분)\b'
        if re.search(num_unit_pattern, code, flags=re.IGNORECASE) and not re.fullmatch(num_unit_pattern, code, flags=re.IGNORECASE):
            code = re.sub(num_unit_pattern, '', code, flags=re.IGNORECASE).strip()

        code = re.sub(r'[_\s]*?(더블\s*기획|듀오\s*기획|더블\s*세트|기획\s*세트)[_\s]*?', '', code)

        # 1) '세트', '기획' 등 제거
        code = re.sub(r'[\s_+/]?(세트|기획|듀오팩)', '', code)

        # 2) '단품' 단독인지 확인 후 제거 여부 결정
        if code.strip() not in ["단품"]:
            code = re.sub(r'[\s_+/]?단품', '', code)


        return code

    @classmethod
    def is_valid_code_name(cls, code: str, product_name: str = "") -> bool:
        """
        전처리 후의 code_name이 유효한 경우만 True 반환.
        예: '단독' 같은 불필요한 코드명은 False로 처리.
        """
        clean_code = cls.clean_code_name(code)
        if clean_code.strip() == "단독":
            print(f"[SKIP] code_name='단독' → {product_name}")
            return False
        return True

    @classmethod
    def extract_price_from_code_name(cls, code_name: str):
        """
        code_name이 '[키링기획] 03 브라운 1.5g\\n9,600원' 형태일 때
        ('[키링기획] 03 브라운 1.5g', '9600')을 반환.
        - '단품' 또는 None이면 가격은 빈 문자열로 반환.
        - 숫자만 추출하며, 콤마/원 단위 제거.
        """
        if not code_name or code_name.strip() == "단품":
            return code_name.strip() if code_name else "", ""

        # 줄바꿈 기준 분리
        parts = code_name.split("\n", 1)
        name = parts[0].strip()
        price = ""

        # 가격 부분 존재 시 숫자만 추출
        if len(parts) > 1:
            price_text = parts[1].strip()
            price = re.sub(r"[^\d]", "", price_text)  # "9,600원" → "9600"

        return name, price
    
    def preprocess(self):
        preprocessed = []
        seen = set()

        for p in self.products:
            new_product = p.copy()
            new_product['product_name'] = self.clean_product_name(p['product_name'])

            # code_name, review_name 모두 clean_code_name 적용
            if 'code_name' in p:
                # code_name에서 가격 분리
                raw_code = p['code_name']
                clean_code, extracted_price = self.extract_price_from_code_name(raw_code)
                new_product['code_name'] = self.clean_code_name(clean_code)

                # 기존 price가 없고, code_name에서 가격이 추출된 경우
                if not p.get('price') and extracted_price:
                    new_product['price'] = extracted_price
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
