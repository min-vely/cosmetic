import os
import json
from dotenv import load_dotenv
from typing import List
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

# ✅ .env 파일에서 OPENAI_API_KEY 불러오기
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# -----------------------------
# Pydantic 모델 정의
# -----------------------------
class Product(BaseModel):
    brand_name: str = Field(..., description="브랜드명")
    product_name: str = Field(..., description="전처리된 제품명")
    code_name: str = Field(..., description="전처리된 코드명")
    price: str = Field(..., description="가격 (문자열)")
    product_main_image: str = Field(..., description="대표 이미지 URL")
    product_url: str = Field(..., description="상품 상세 페이지 URL")

class Products(BaseModel):
    products: List[Product]

# -----------------------------
# LLM + Parser 설정
# -----------------------------
parser = PydanticOutputParser(pydantic_object=Products)

prompt_template = ChatPromptTemplate.from_messages([
    ("system", 
     "너는 화장품 쇼핑몰 크롤링 데이터를 전처리하는 도우미야. "
     "제품명과 코드명에서 브랜드명, 순수 제품명만 남기고, "
     "용량, 색상, 단품/세트/기획, (품절) 등 불필요한 단어는 제거해."),
    ("human", 
     "다음 데이터를 전처리해서 JSON 형식으로 출력해줘:\n\n{input}\n\n"
     "{format_instructions}")
])

llm = ChatOpenAI(
    temperature=0,
    model_name="gpt-4o",  # 필요 시 gpt-4o, gpt-4o-mini 등 변경 가능
    openai_api_key=OPENAI_API_KEY,
)

# -----------------------------
# 데이터 불러오기
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_PATH = os.path.join(BASE_DIR, "..", "data", "oliveyoung_lip_makeup.json")
OUTPUT_PATH = os.path.join(BASE_DIR, "..", "data", "oliveyoung_lip_makeup_pydantic.json")

with open(INPUT_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

# -----------------------------
# 배치 처리
# -----------------------------
BATCH_SIZE = 20  # 입력 크기 제한 때문에 배치 단위로 실행
results = []

for i in range(0, len(data), BATCH_SIZE):
    batch = data[i:i+BATCH_SIZE]
    input_str = json.dumps(batch, ensure_ascii=False, indent=2)

    prompt = prompt_template.format_messages(
        input=input_str,
        format_instructions=parser.get_format_instructions()
    )

    response = llm.invoke(prompt)
    parsed = parser.parse(response.content)

    results.extend(parsed.products)
    print(f"✅ {i+len(batch)}개 처리 완료")

# -----------------------------
# 결과 저장
# -----------------------------
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump({"products": [p.dict() for p in results]}, f, ensure_ascii=False, indent=2)

print(f"🎉 전체 {len(results)}건 저장 완료 -> {OUTPUT_PATH}")
