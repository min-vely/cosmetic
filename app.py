from flask import Flask, request, jsonify, render_template, session
import os
import json
import base64
import mimetypes
from dotenv import load_dotenv
from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
import requests
from google import genai
from google.genai import types
from io import BytesIO
from PIL import Image

# ------------------------------- 0. 초기 설정 -------------------------------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "change-me")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data", "oliveyoung_lip_makeup_merged.json")
CHROMA_DIR = os.path.join(BASE_DIR, "chroma_db")

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY  # 세션 사용

# ------------------------------- 1. Chroma 벡터스토어 캐싱 -------------------------------
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
                thumb = product.get("thumb_color", "")
                if isinstance(thumb, list):
                    thumb = thumb[-1] if thumb else ""
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
                        "product_name": product['product_name'],
                        "code_name": product.get('code_name', ''),
                        "product_url": product["product_url"],
                        "review_index": i,
                        "thumb_color": thumb
                    }
                ))
    vectordb = Chroma.from_documents(docs, embedding, persist_directory=CHROMA_DIR)
    vectordb.persist()
else:
    vectordb = Chroma(persist_directory=CHROMA_DIR, embedding_function=embedding)

retriever = vectordb.as_retriever(search_kwargs={"k": 8})

# ------------------------------- 2. 리랭커 -------------------------------
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

# ------------------------------- 3. LLM -------------------------------
llm = ChatOpenAI(model="gpt-5-mini", temperature=1, openai_api_key=OPENAI_API_KEY)

# ------------------------------- 4. 세션 캐시 -------------------------------
session_cache = {}

# ------------------------------- 5. 추천 처리 -------------------------------
def recommend_next(user_id="default"):
    if user_id not in session_cache:
        return {"response": "이전 추천이 없습니다. 먼저 질문해주세요.", "images": [], "product_names": [], "code_names": []}

    reranked_docs = session_cache[user_id]["docs"]
    already = session_cache[user_id]["already"]
    idx = session_cache[user_id].get("current_index", 0)
    query = session_cache[user_id]["last_query"]

    while idx < len(reranked_docs):
        d = reranked_docs[idx]
        key = (d.metadata.get("product_name", ""), d.metadata.get("code_name", ""))
        idx += 1
        if key in already:
            continue

        already.add(key)
        session_cache[user_id]["current_index"] = idx

        thumb = d.metadata.get("thumb_color", "")
        images = [thumb] if thumb else []

        prompt = f"""
당신은 화장품 추천 챗봇입니다.
사용자의 질문: {query}

아래는 검색된 제품 정보와 리뷰입니다:
{d.page_content}

추천할 제품명과 색상을 맨 앞에 표시하고, 그 뒤에 리뷰 기반으로 간결하게 추천 이유를 한두 문장으로 작성하세요.
"""
        raw_answer = llm.predict(prompt)
        answer = raw_answer.strip()

        # 세션에 현재 추천 제품 저장 (가상 화장용)
        session["last_swatch_url"] = images[0] if images else None
        session["last_product_info"] = {
            "product_name": d.metadata.get("product_name", ""),
            "code_name": d.metadata.get("code_name", ""),
        }

        return {
            "response": answer,
            "images": images,
            "product_names": [d.metadata.get("product_name", "")],
            "code_names": [d.metadata.get("code_name", "")]
        }

    return {"response": "더 이상 추천할 제품이 없습니다.", "images": [], "product_names": [], "code_names": []}

# ------------------------------- 6. 질의 분류 -------------------------------
def is_recommendation_query(user_id, user_input):
    history = session_cache.get(user_id, {}).get("history", [])
    context_text = ""
    for turn in history[-6:]:
        role = "사용자" if turn["role"]=="user" else "챗봇"
        context_text += f"{role}: {turn['text']}\n"
    context_text += f"사용자: {user_input}\n"

    prompt = f"""
이전 대화를 고려하여 마지막 사용자의 입력이 제품 추천 요청인지 판단하세요.
추천이면 "추천", 아니면 "일반"만 출력하세요.
{context_text}
"""
    answer = llm.predict(prompt).strip()
    return answer.lower() == "추천"

# ------------------------------- 7. RAG 파이프라인 -------------------------------
def rag_pipeline_first(query, user_id="default"):
    retrieved_docs = retriever.get_relevant_documents(query)
    reranked_docs = rerank(query, retrieved_docs)
    session_cache[user_id]["last_query"] = query
    session_cache[user_id]["docs"] = reranked_docs
    session_cache[user_id]["already"] = set()
    session_cache[user_id]["current_index"] = 0
    return recommend_next(user_id)

def rag_pipeline_next(user_id="default"):
    return recommend_next(user_id)

# ------------------------------- 8. Flask 라우팅 -------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    message = data.get("message", "")
    user_id = data.get("user_id", "default")

    if user_id not in session_cache:
        session_cache[user_id] = {"history": []}

    session_cache[user_id]["history"].append({"role": "user", "text": message})

    if is_recommendation_query(user_id, message):
        result = rag_pipeline_first(message, user_id)
    else:
        context_text = ""
        for turn in session_cache[user_id]["history"][-6:]:
            role = "사용자" if turn["role"]=="user" else "챗봇"
            context_text += f"{role}: {turn['text']}\n"
        prompt = f"""
당신은 뷰티 전문가입니다. 제품 추천은 하지 않고, 일반 대화만 3줄 이내로 답변하세요.
{context_text}
"""
        answer = llm.predict(prompt).strip()
        result = {"response": answer, "images": [], "product_names": [], "code_names": []}

    session_cache[user_id]["history"].append({"role": "bot", "text": result["response"]})
    return jsonify(result)

@app.route("/next", methods=["POST"])
def next_product():
    data = request.get_json()
    user_id = data.get("user_id", "default")
    result = recommend_next(user_id)
    if user_id in session_cache:
        session_cache[user_id]["history"].append({"role": "bot", "text": result["response"]})
    return jsonify(result)

# ------------------------------- 9. 가상 화장 (Gemini API) -------------------------------
def to_data_url(data: bytes, mime: str) -> str:
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:{mime};base64,{b64}"

@app.route("/apply_makeup", methods=["POST"])
def apply_makeup():
    if not GOOGLE_API_KEY:
        return jsonify({"error": "GOOGLE_API_KEY가 설정되지 않았습니다."}), 500

    data = request.get_json()
    img_data = data.get("image")
    if not img_data:
        return jsonify({"error": "image가 필요합니다."}), 400

    header, encoded = img_data.split(",", 1)
    img_bytes = base64.b64decode(encoded)

    swatch_url = data.get("swatch_url") or session.get("last_swatch_url")
    if not swatch_url:
        return jsonify({"error": "추천된 제품 이미지가 없습니다."}), 400

    # ------------------ swatch_bytes 세션 캐싱 ------------------
    swatch_bytes = session.get("last_swatch_bytes")
    if not swatch_bytes or session.get("last_swatch_url") != swatch_url:
        try:
            resp = requests.get(swatch_url, timeout=10)  # 최대 10초 대기
            resp.raise_for_status()
            swatch_bytes = resp.content
            session["last_swatch_bytes"] = swatch_bytes
            session["last_swatch_url"] = swatch_url
        except Exception as e:
            return jsonify({"error": f"이미지 로드 실패: {e}"}), 400
    # ------------------------------------------------------------

    client = genai.Client(api_key=GOOGLE_API_KEY)
    prompt = "사용자의 얼굴 사진에 아래 화장품의 색상을 입술에만 자연스럽게 적용하세요. 피부색이나 배경은 변경하지 마세요."

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(mime_type="image/png", data=img_bytes),
                types.Part.from_bytes(mime_type="image/png", data=swatch_bytes),
            ],
        ),
    ]
    cfg = types.GenerateContentConfig(response_modalities=["IMAGE"])

    try:
        out_bytes = None
        for chunk in client.models.generate_content_stream(
            model="gemini-2.5-flash-image",
            contents=contents,
            config=cfg,
        ):
            if (
                not chunk.candidates
                or not chunk.candidates[0].content
                or not chunk.candidates[0].content.parts
            ):
                continue
            part = chunk.candidates[0].content.parts[0]
            if getattr(part, "inline_data", None):
                out_bytes = part.inline_data.data
                break

        if not out_bytes:
            return jsonify({"error": "이미지를 생성하지 못했습니다."}), 500

        return jsonify({"result_image": base64.b64encode(out_bytes).decode("utf-8")})

    except Exception as e:
        return jsonify({"error": f"Gemini API 오류: {e}"}), 500


# ------------------------------- 10. 실행 -------------------------------
if __name__ == "__main__":
    app.run(debug=True)