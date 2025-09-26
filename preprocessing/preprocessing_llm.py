import os
import json
from dotenv import load_dotenv
from tqdm import tqdm

from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

# ✅ .env 불러오기
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ✅ Pydantic 모델 정의
class Product(BaseModel):
    brand_name: str = Field(..., description="브랜드 이름")
    product_name: str = Field(..., description="전처리된 상품 이름")
    code_name: str = Field(..., description="전처리된 코드 이름")

class Products(BaseModel):
    items: list[Product]

# ✅ LLM 설정
llm = ChatOpenAI(
    model_name="gpt-4o",
    temperature=0,
    openai_api_key=OPENAI_API_KEY,
)

parser = PydanticOutputParser(pydantic_object=Products)

prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "너는 화장품 데이터를 전처리하는 도우미야. "
            "입력 JSON 데이터를 받아 불필요한 기호나 단어를 제거한 뒤, "
            "brand_name, product_name, code_name을 깔끔하게 반환해."
        ),
        (
            "human",
            "다음 데이터를 전처리해줘:\n\n{data}\n\n"
            "출력은 반드시 {format_instructions} 형식으로."
        ),
    ]
).partial(format_instructions=parser.get_format_instructions())


def preprocess_with_pydantic(data, batch_size=20):
    """배치 단위로 LLM 호출하여 전처리"""
    results = []
    seen = set()

    for i in tqdm(range(0, len(data), batch_size), desc="Preprocessing"):
        batch = data[i : i + batch_size]

        chain = prompt | llm | parser
        parsed = chain.invoke({"data": json.dumps(batch, ensure_ascii=False)})

        for item in parsed.items:
            key = (item.brand_name, item.product_name, item.code_name)
            if key not in seen:
                seen.add(key)
                results.append(item.dict())
            else:
                tqdm.write(f"중복 제거됨 -> brand: {item.brand_name}, "
                           f"product: {item.product_name}, "
                           f"code: {item.code_name}")

    return results


if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    INPUT_PATH = os.path.join(BASE_DIR, "..", "data", "oliveyoung_lip_makeup.json")
    OUTPUT_PATH = os.path.join(BASE_DIR, "..", "data", "oliveyoung_lip_makeup_pydantic.json")

    # ✅ 데이터 로드
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # ✅ 전처리 실행
    preprocessed = preprocess_with_pydantic(data, batch_size=20)

    # ✅ 저장
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(preprocessed, f, ensure_ascii=False, indent=2)

    print(f"{len(preprocessed)}건 저장 완료 -> {OUTPUT_PATH}")
