import json
import re

class OliveYoungPreprocessor:
    def __init__(self, input_file: str, output_file: str):
        self.input_file = input_file
        self.output_file = output_file
        self.data = []

    def load_json(self):
        with open(self.input_file, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    @staticmethod
    def clean_product_name(name: str) -> str:
        if not name:
            return name
        # [] 제거
        name = re.sub(r'\[.*?\]', '', name)
        # () 제거
        name = re.sub(r'\(.*?\)', '', name)
        return name.strip()

    @staticmethod
    def clean_code_name(code_name: str) -> str:
        if not code_name:
            return code_name
        if code_name.strip() == "단품":
            return code_name  # 단품은 그대로
        # [] 제거
        code_cleaned = re.sub(r'\[.*?\]', '', code_name)
        # (품절) 제거
        code_cleaned = re.sub(r'\(품절\)', '', code_cleaned)
        # \n 이후 내용 제거 (가격 정보 제거)
        code_cleaned = code_cleaned.split('\n')[0]
        return code_cleaned.strip() if code_cleaned.strip() else code_name

    def preprocess(self):
        for item in self.data:
            # product_name 전처리
            original_name = item.get("product_name", "")
            cleaned_name = self.clean_product_name(original_name)
            item["product_name"] = cleaned_name if cleaned_name else original_name

            # code_name 전처리
            original_code = item.get("code_name", "")
            cleaned_code = self.clean_code_name(original_code)
            item["code_name"] = cleaned_code if cleaned_code else original_code

    def save_json(self):
        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        print(f"{len(self.data)}건 저장 완료 -> {self.output_file}")


if __name__ == "__main__":
    processor = OliveYoungPreprocessor(
        input_file="oliveyoung_lip_makeup.json",
        output_file="oliveyoung_lip_makeup_preprocessed.json"
    )
    processor.load_json()
    processor.preprocess()
    processor.save_json()
