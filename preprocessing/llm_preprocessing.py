import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate

load_dotenv()  # .env에서 OPENAI_API_KEY 읽기

class LLMProductNameCleaner:
    def __init__(self, temperature=0, model_name="gpt-4o"):
        self.llm = ChatOpenAI(
            temperature=temperature,
            model_name=model_name
        )

    def clean_product_name(self, name: str) -> str:
        """
        제품명에서 브랜드명과 순수 제품명만 남기고,
        용량, 색상, 단품/기획/한정기획 등 불필요한 꼬리표 제거
        """
        prompt = f"""
        다음 제품명에서 브랜드명과 순수 제품명만 남기고,
        다음 꼬리표와 문구는 모두 제거해주세요:
        - 단품, 기획, 한정 기획
        - 용량 표시 (예: g, ml, oz)
        - 색상, 개수, 호수 표시 (예: 10종, 15종, 14 Colors, 18 COLOR, 4colors 등)
        - '중 택1'과 같이 선택 문구
        - 괄호를 포함한 []나 () 안의 내용
        - 주의: 절대 새로운 문구를 추가하지 마세요. '원문:', '브랜드명과 순수 제품명:'처럼 덧붙이지 마세요.
        원문: "{name}"
        """

        response = self.llm.invoke(prompt)
        # AIMessage 객체의 content 사용
        return response.content.strip()

    def clean_code_name(self, code: str) -> str:
        """
        code_name 전처리:
        - [] 안 내용 제거
        - (품절) 제거
        - \n 뒤 가격 제거
        - 중복 공백 제거
        """
        import re
        code = re.sub(r'\[.*?\]', '', code)
        code = code.replace('(품절)', '')
        code = re.sub(r'\n.*$', '', code)
        code = re.sub(r'\s+', ' ', code).strip()
        return code

    def clean_product(self, product: dict) -> dict:
        """
        단일 상품 데이터 전처리
        """
        cleaned = product.copy()
        cleaned["product_name"] = self.clean_product_name(product["product_name"])
        cleaned["code_name"] = self.clean_code_name(product["code_name"])
        return cleaned
