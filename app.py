from flask import Flask, request, jsonify, render_template
import os
import json
from dotenv import load_dotenv
from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import Chroma
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

# -------------------------------
# 0. 초기 설정
# -------------------------------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data", "oliveyoung_lip_makeup_merged.json")
CHROMA_DIR = os.path.join(BASE_DIR, "chroma_db")

app = Flask(__name__)

# -------------------------------
# 1. Chroma 벡터스토어 캐싱
# -------------------------------
embedding = OpenAIEmbeddings(model="text-embedding-3-large", openai_api_key=OPENAI_API_KEY)

if not os.path.exists(CHROMA_DIR):
    print("[INFO] ChromaDB가 없어 새로 생성합니다...")

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    docs = []
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=50)

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
else:
    vectordb = Chroma(persist_directory=CHROMA_DIR, embedding_function=embedding)

retriever = vectordb.as_retriever(search_kwargs={"k": 8})

# -------------------------------
# 2. 리랭커
# -------------------------------
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
# 3. LLM
# -------------------------------
llm = ChatOpenAI(model="gpt-5-mini", temperature=0.2, openai_api_key=OPENAI_API_KEY)

def rag_pipeline(query):
    retrieved_docs = retriever.get_relevant_documents(query)
    reranked_docs = rerank(query, retrieved_docs)
    top_docs = reranked_docs[:5]

    context = "\n\n".join([d.page_content for d in top_docs])
    prompt = f"""
당신은 화장품 추천 챗봇입니다.
사용자의 질문: {query}

아래는 검색된 제품 정보와 리뷰입니다:
{context}

주의:
1. 사용자의 질문이 제품 추천 요청인지 먼저 판단하세요.
2. 추천 요청이라면:
   - 가장 적합한 제품의 product_name과 code_name을 명확히 제시하세요.
   - 추천 이유를 간단하고 설득력 있게 설명하세요.
   - 리뷰에서 실제 근거 문장을 요약해 포함하세요.
   - 요청 시 여러 개의 제품을 추천 가능합니다.
3. 추천 요청이 아닌 경우:
   - 제품 추천 없이 질문에 대한 전문가 의견만 간결히 답변하세요.
4. 답변은 한두 문장으로 간결하게 하고, 불필요한 일반 설명은 하지 마세요.
"""
    answer = llm.predict(prompt)
    return answer

# -------------------------------
# 4. Flask 라우팅
# -------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json["message"]
    answer = rag_pipeline(user_input)
    return jsonify({"response": answer})

if __name__ == "__main__":
    app.run(debug=True)