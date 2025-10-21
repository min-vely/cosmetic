import os
import json
from dotenv import load_dotenv
from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import Chroma

# -------------------------------
# 0. .env 로드 (OpenAI API 키)
# -------------------------------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY is None:
    raise ValueError("OPENAI_API_KEY가 .env에 설정되어 있지 않습니다!")
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# -------------------------------
# 1. 경로 설정
# -------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data", "oliveyoung_lip_makeup_merged.json")
CHROMA_DIR = os.path.join(BASE_DIR, "chroma_db")

# -------------------------------
# 2. 벡터스토어 초기화 (캐싱)
# -------------------------------
embedding = OpenAIEmbeddings(model="text-embedding-3-large", openai_api_key=OPENAI_API_KEY)

if not os.path.exists(CHROMA_DIR):
    print("[INFO] ChromaDB가 없어 새로 생성합니다...")

    # JSON 로드 & chunk 생성
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    docs = []
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=700,
        chunk_overlap=50
    )

    for product in data:
        for review in product.get("texts", []):
            chunks = text_splitter.split_text(review)
            for i, chunk in enumerate(chunks):
                content = f"""
브랜드: {product['brand_name']}
제품명: {product['product_name']}
색상명: {product.get('code_name', '')}
가격: {product.get('price', '')}
리뷰:
{chunk}
"""
                docs.append(Document(
                    page_content=content,
                    metadata={
                        "product_url": product["product_url"],
                        "review_index": i
                    }
                ))

    vectordb = Chroma.from_documents(docs, embedding, persist_directory=CHROMA_DIR)
    vectordb.persist()
    print("[INFO] ChromaDB 생성 완료")

else:
    print("[INFO] 기존 ChromaDB 로드 중...")
    vectordb = Chroma(persist_directory=CHROMA_DIR, embedding_function=embedding)
    print("[INFO] 로드 완료")

retriever = vectordb.as_retriever(search_kwargs={"k": 8})

# -------------------------------
# 3. 리랭커 (bge-reranker-large)
# -------------------------------
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

reranker_model = "BAAI/bge-reranker-large"
tokenizer = AutoTokenizer.from_pretrained(reranker_model)
model = AutoModelForSequenceClassification.from_pretrained(reranker_model)
device = "cuda" if torch.cuda.is_available() else "cpu"
model.to(device)

def rerank(query, docs):
    pairs = [[query, d.page_content] for d in docs]
    inputs = tokenizer(pairs, padding=True, truncation=True, return_tensors="pt", max_length=512)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        scores = model(**inputs).logits.squeeze(-1).cpu().tolist()
    scored = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
    return [d for d, s in scored]

# -------------------------------
# 4. LLM (GPT-5-Mini) + QA
# -------------------------------
llm = ChatOpenAI(model="gpt-5-mini", temperature=0.2, openai_api_key=OPENAI_API_KEY)

def rag_pipeline(query):
    print("[1] 검색 시작")
    retrieved_docs = retriever.get_relevant_documents(query)

    print("[2] 리랭킹 시작")
    reranked_docs = rerank(query, retrieved_docs)
    top_docs = reranked_docs[:5]

    print("[3] LLM 호출 시작")
    context = "\n\n".join([d.page_content for d in top_docs])
    prompt = f"""
당신은 화장품 추천 챗봇입니다.
사용자의 질문: {query}

아래는 검색된 제품 정보와 리뷰입니다:
{context}

위 정보를 근거로:
1. 가장 적합한 제품의 product_name과 code_name을 명확히 제시하세요.
2. 추천 이유를 간단하고 설득력 있게 설명하세요.
3. 리뷰에서 실제 근거 문장을 요약해 포함하세요.
4. 불필요한 일반 설명은 하지 마세요.
5. 가능하다면 한두 문장으로 간결하게 답하세요.
"""
    answer = llm.predict(prompt)
    return answer

# -------------------------------
# 5. 실행 예시
# -------------------------------
# if __name__ == "__main__":
#     query = "촉촉하고 쿨톤에게 어울리는 핑크색 틴트 추천해줘."
#     print(rag_pipeline(query))

# if __name__ == "__main__":
#     query = "헤라 브랜드의 틴트 중 여쿨라에게 잘 어울리는 틴트 추천해줘."
#     print(rag_pipeline(query))

if __name__ == "__main__":
    query = "딸기우유색 틴트 추천해줘."
    print(rag_pipeline(query))