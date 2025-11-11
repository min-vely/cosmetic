from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_session import Session   # ✅ 추가
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from zoneinfo import ZoneInfo
from authlib.integrations.flask_client import OAuth
import os
import uuid
import time
import json
import base64
import requests
import mimetypes
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
import requests
from google import genai
from google.genai import types
from io import BytesIO
from tqdm import tqdm
from flask import request, jsonify, session

# ------------------------------- 0. 초기 설정 -------------------------------
# 한국 시간대 헬퍼 함수
def get_kst_now():
    """현재 한국 시간(KST) 반환 (timezone 정보 없이)"""
    return datetime.now(ZoneInfo("Asia/Seoul")).replace(tzinfo=None)

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "change-me")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMA_DIR_1536 = os.path.join(BASE_DIR, "chroma_db_1536")
CHROMA_DIR_3072 = os.path.join(BASE_DIR, "chroma_db_3072")
LOG_PATH = os.path.join(BASE_DIR, "chromadblog.txt")  # ✅ 추가: 로그 파일 경로
MERGED_DIR = os.path.join(BASE_DIR, "data", "merged")
PROCESSED_FILES_1536 = os.path.join(BASE_DIR, "processed_files_1536.json")
PROCESSED_FILES_3072 = os.path.join(BASE_DIR, "processed_files_3072.json")

# ------------------------------- 로그 함수 (초기 설정) -------------------------------
def log_message(msg):
    """로그 메시지를 파일과 콘솔에 출력"""
    print(msg)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {msg}\n")

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY  # 세션 키 설정

# ✅ 서버 세션 설정 (파일 기반)
app.config["SESSION_TYPE"] = "filesystem"  # 세션을 서버 파일에 저장
app.config["SESSION_FILE_DIR"] = "/tmp/flask_session"  # 세션 저장 디렉토리
app.config["SESSION_PERMANENT"] = False  # 브라우저 종료 시 세션 만료
app.config["SESSION_USE_SIGNER"] = True  # 서명된 쿠키 사용
Session(app)  # ✅ 서버 세션 활성화

# ------------------------------- 데이터베이스 설정 -------------------------------
# 환경 변수에서 DATABASE_URL 읽기 (Cloud SQL 사용 시)
# 없으면 SQLite 사용 (로컬 개발용)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///cosmetic.db")

# PostgreSQL URL이 postgres://로 시작하면 postgresql://로 변경 (Heroku 호환성)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,  # 연결 유효성 검사
    "pool_recycle": 300,    # 5분마다 연결 재사용
}
db = SQLAlchemy(app)

# 데이터베이스 타입 로깅
db_type = "PostgreSQL (Cloud SQL)" if "postgresql" in DATABASE_URL else "SQLite (로컬)"
log_message(f"[Database] 사용 중인 데이터베이스: {db_type}")

# ------------------------------- 로그인 매니저 설정 -------------------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# ------------------------------- 데이터베이스 모델 -------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=get_kst_now)

    # 관계: 한 유저는 여러 검색 기록을 가짐
    search_histories = db.relationship("SearchHistory", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class SearchHistory(db.Model):
    __tablename__ = "search_histories"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    query = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=True)
    dimension = db.Column(db.Integer, default=1536)  # 1536 or 3072
    is_recommendation = db.Column(db.Boolean, default=True)  # 추천 쿼리인지 일반 대화인지
    created_at = db.Column(db.DateTime, default=get_kst_now)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# 앱 컨텍스트 내에서 테이블 생성
with app.app_context():
    db.create_all()

# ------------------------------- OAuth 설정 (Google Login) -------------------------------
oauth = OAuth(app)

# OAuth 설정 검증
if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    log_message("[WARN] GOOGLE_CLIENT_ID 또는 GOOGLE_CLIENT_SECRET이 설정되지 않았습니다. 구글 로그인이 비활성화됩니다.")
    google = None
else:
    google = oauth.register(
        name='google',
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
    )

# ------------------------------- 1. Chroma 벡터스토어 캐싱 -------------------------------
# Gemini Embedding 설정 (공식 genai SDK 사용)
from google import genai
from google.genai import types
from langchain_core.embeddings import Embeddings
from typing import List

# Gemini Client 초기화
genai_client = genai.Client(api_key=GOOGLE_API_KEY)
MODEL_ID = "gemini-embedding-001"

# LangChain과 호환되는 커스텀 임베딩 클래스
class GeminiEmbeddings(Embeddings):
    def __init__(self, client, model_id: str, output_dimensionality: int = None):
        self.client = client
        self.model_id = model_id
        self.output_dimensionality = output_dimensionality

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """여러 문서를 임베딩 (Gemini API는 한 번에 최대 100개 제한)"""
        config = None
        if self.output_dimensionality:
            config = types.EmbedContentConfig(output_dimensionality=self.output_dimensionality)

        # Gemini API 배치 제한: 최대 100개씩 처리
        GEMINI_BATCH_LIMIT = 100
        all_embeddings = []

        for i in range(0, len(texts), GEMINI_BATCH_LIMIT):
            batch = texts[i:i + GEMINI_BATCH_LIMIT]
            result = self.client.models.embed_content(
                model=self.model_id,
                contents=batch,
                config=config
            )
            all_embeddings.extend([embedding.values for embedding in result.embeddings])

        return all_embeddings

    def embed_query(self, text: str) -> List[float]:
        """단일 쿼리를 임베딩"""
        config = None
        if self.output_dimensionality:
            config = types.EmbedContentConfig(output_dimensionality=self.output_dimensionality)

        result = self.client.models.embed_content(
            model=self.model_id,
            contents=[text],
            config=config
        )
        return result.embeddings[0].values

# 1536차원과 3072차원 2개의 임베딩 모델 생성
embedding_1536 = GeminiEmbeddings(
    client=genai_client,
    model_id=MODEL_ID,
    output_dimensionality=1536  # 1536차원으로 축소
)

embedding_3072 = GeminiEmbeddings(
    client=genai_client,
    model_id=MODEL_ID,
    output_dimensionality=3072  # 기본 3072차원 명시
)

# 기본 임베딩 (호환성 유지)
embedding = embedding_1536

def get_processed_files(processed_file_path):
    """처리된 파일 목록 로드"""
    if os.path.exists(processed_file_path):
        with open(processed_file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_processed_files(processed_file_path, files):
    """처리된 파일 목록 저장"""
    with open(processed_file_path, "w", encoding="utf-8") as f:
        json.dump(files, f, ensure_ascii=False, indent=2)

def get_current_json_files():
    """현재 data/merged 폴더의 JSON 파일 목록 가져오기"""
    if not os.path.exists(MERGED_DIR):
        return []
    return [fname for fname in os.listdir(MERGED_DIR) if fname.endswith(".json")]

def get_category_from_filename(filename):
    """파일명에서 카테고리 추출
    예: oliveyoung_lipstick_merged.json -> lipstick
    """
    parts = filename.replace("_merged.json", "").split("_")
    if len(parts) >= 2:
        return parts[1]  # oliveyoung_lipstick -> lipstick
    return "unknown"

def load_json_files(file_list):
    """지정된 JSON 파일들을 로드하여 데이터와 카테고리 정보 반환"""
    data_with_category = []
    for fname in file_list:
        fpath = os.path.join(MERGED_DIR, fname)
        category = get_category_from_filename(fname)

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, list):
                    # 각 제품에 카테고리 정보 추가
                    for item in content:
                        item['_category'] = category
                        data_with_category.append(item)
                else:
                    content['_category'] = category
                    data_with_category.append(content)
        except Exception as e:
            log_message(f"[WARN] 파일 읽기 실패: {fname} -> {e}")
    return data_with_category

def create_vectordb(chroma_dir, embedding_func, dimension_name, processed_file_path):
    """벡터 DB 생성 또는 증분 업데이트"""

    # 현재 merged 폴더의 파일 목록
    current_files = get_current_json_files()

    # 처리된 파일 목록 로드
    processed_files = get_processed_files(processed_file_path)

    # 새로 추가된 파일 찾기
    new_files = [f for f in current_files if f not in processed_files]

    # VectorDB 로드 또는 생성
    if os.path.exists(chroma_dir):
        log_message(f"[INFO] {dimension_name} ChromaDB가 이미 존재합니다. 로드합니다.")
        vectordb = Chroma(persist_directory=chroma_dir, embedding_function=embedding_func)

        # 새 파일이 있으면 증분 업데이트
        if new_files:
            log_message(f"[INFO] {dimension_name} 새로운 파일 감지: {new_files}")
            log_message(f"[INFO] {dimension_name} 증분 업데이트를 시작합니다...")
            data = load_json_files(new_files)
        else:
            log_message(f"[INFO] {dimension_name} 새로운 파일이 없습니다. 기존 DB를 사용합니다.")
            return vectordb
    else:
        # DB가 없으면 전체 파일 처리
        log_message(f"[INFO] {dimension_name} ChromaDB가 없어 새로 생성합니다...")
        data = load_json_files(current_files)

    # 데이터가 없으면 조기 반환
    if not data:
        log_message(f"[INFO] {dimension_name} 처리할 데이터가 없습니다.")
        return vectordb

    # ---------------- 나머지 기존 코드 그대로 유지 ----------------
    docs = []
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    for product in data:
        # 리뷰 샘플링: 제품당 최대 50개
        reviews = product.get("texts", [])
        if len(reviews) > 50:
            import random
            reviews = random.sample(reviews, 50)
        for review in reviews:
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
                        "thumb_color": thumb,
                        "category": product.get('_category', 'unknown'),  # 카테고리 추가
                        "brand_name": product.get('brand_name', '')  # 브랜드도 필터링용으로 추가
                    }
                ))

    # docs가 비어있으면 조기 반환
    if not docs:
        log_message(f"[INFO] {dimension_name} 생성된 문서가 없습니다.")
        return vectordb

    # vectordb가 없으면 새로 생성
    if not os.path.exists(chroma_dir):
        vectordb = Chroma(persist_directory=chroma_dir, embedding_function=embedding_func)

    BATCH_SIZE = 2000  # 한 번에 2000개씩 임베딩
    total_batches = len(range(0, len(docs), BATCH_SIZE))

    # ✅ 추가: 이전 진행 상태 복원
    start_batch = 0
    log_file = os.path.join(BASE_DIR, f"chromadblog_{dimension_name}.txt")
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                if "✅ 진행 완료 배치" in line:
                    try:
                        start_batch = int(line.strip().split(":")[-1])
                    except:
                        pass
    # 증분 업데이트인지 전체 생성인지 로깅
    if new_files:
        log_message(f"[INFO] {dimension_name} 증분 업데이트 - 새 파일 수: {len(new_files)}, 문서 수: {len(docs)}")
    else:
        log_message(f"[INFO] {dimension_name} 전체 생성 - 파일 수: {len(current_files)}, 문서 수: {len(docs)}")

    log_message(f"[INFO] {dimension_name} 총 배치 수: {total_batches}, 시작 배치 인덱스: {start_batch}")

    for i in tqdm(range(start_batch, len(docs) // BATCH_SIZE + 1), desc=f"Embedding {dimension_name}"):
        batch_start = i * BATCH_SIZE
        batch = docs[batch_start:batch_start + BATCH_SIZE]
        if not batch:
            continue
        try:
            vectordb.add_documents(batch)
            vectordb.persist()
            log_message(f"✅ {dimension_name} 진행 완료 배치: {i}")
        except Exception as e:
            log_message(f"[WARN] {dimension_name} 임베딩 중 오류 발생: {e}")
            if "quota" in str(e).lower() or "rate" in str(e).lower():
                log_message(f"[ERROR] {dimension_name} API 한도 또는 요금 초과로 중단됩니다. 진행 상태가 저장되었습니다.")
                break
            #time.sleep(2)
            continue

        #time.sleep(1)

    vectordb.persist()

    # 처리된 파일 목록 업데이트 및 저장
    if new_files:
        # 증분 업데이트: 새 파일 추가
        updated_files = processed_files + new_files
    else:
        # 전체 생성: 현재 모든 파일
        updated_files = current_files

    save_processed_files(processed_file_path, updated_files)
    log_message(f"[INFO] {dimension_name} 처리 완료. 총 파일 수: {len(updated_files)}")

    return vectordb

# 2개의 벡터 DB 생성
vectordb_1536 = create_vectordb(CHROMA_DIR_1536, embedding_1536, "1536차원", PROCESSED_FILES_1536)

# ⚠️ 임시 비활성화: 3072차원 테스트 후 다시 활성화 예정
# vectordb_3072 = create_vectordb(CHROMA_DIR_3072, embedding_3072, "3072차원", PROCESSED_FILES_3072)
vectordb_3072 = None  # 임시 비활성화

# 기본 설정 (호환성 유지)
vectordb = vectordb_1536
retriever = vectordb.as_retriever(search_kwargs={"k": 5})
retriever_1536 = vectordb_1536.as_retriever(search_kwargs={"k": 5})
# retriever_3072 = vectordb_3072.as_retriever(search_kwargs={"k": 5})  # 임시 비활성화
retriever_3072 = None  # 임시 비활성화

# ------------------------------- 2. 리랭커 -------------------------------
reranker_model = "BAAI/bge-reranker-large"
tokenizer = AutoTokenizer.from_pretrained(reranker_model)
model = AutoModelForSequenceClassification.from_pretrained(reranker_model)
device = "cuda" if torch.cuda.is_available() else "cpu"
model.to(device)

def rerank(query, docs):
    if not docs:  # ✅ 빈 리스트 방어
        return []

    pairs = [[query, d.page_content] for d in docs if d.page_content.strip()]
    if not pairs:  # ✅ 문서 내용이 비어 있는 경우 방어
        return []

    inputs = tokenizer(
        pairs,
        padding=True,
        truncation=True,
        return_tensors="pt",
        max_length=512
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        scores = model(**inputs).logits.squeeze(-1).cpu().tolist()

    scored = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
    return [d for d, s in scored]

# ------------------------------- 3. LLM -------------------------------
llm = ChatOpenAI(model="gpt-5-mini", temperature=1, openai_api_key=OPENAI_API_KEY)

# ------------------------------- 4. 세션 캐시 -------------------------------
session_cache = {}

# ------------------------------- 4-1. Retriever 캐시 (의미론적 유사도 기반) -------------------------------
# 차원별로 캐시 분리
retriever_cache_1536 = {}  # {query: {"embedding": [...], "results": [...]}}
# retriever_cache_3072 = {}  # 임시 비활성화
retriever_cache_3072 = {}  # 빈 캐시로 유지 (코드 호환성)
MAX_CACHE_SIZE = 100
SIMILARITY_THRESHOLD = 0.95  # 유사도 임계값 (0.95 이상이면 같은 쿼리로 간주)

# ------------------------------- 4-2. LLM 응답 캐시 (의미론적 유사도 기반) -------------------------------
llm_cache = {}  # {cache_key: {"embedding": [...], "response": str}}
MAX_LLM_CACHE_SIZE = 200
LLM_SIMILARITY_THRESHOLD = 0.93  # LLM은 약간 낮은 임계값 사용 (더 많은 캐시 히트)

def cosine_similarity(vec1, vec2):
    """두 벡터 간의 코사인 유사도 계산"""
    import numpy as np
    vec1 = np.array(vec1)
    vec2 = np.array(vec2)
    return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

def semantic_cached_retrieve(query, retriever, embedding_func, retriever_cache, dimension_name="default", max_cache_size=MAX_CACHE_SIZE, threshold=SIMILARITY_THRESHOLD):
    """의미론적 유사도 기반 캐싱 - '라벤더 색상'과 '라벤더색상'을 같은 쿼리로 인식"""

    # 쿼리를 임베딩으로 변환
    query_embedding = embedding_func.embed_query(query)

    # 캐시에서 유사한 쿼리 찾기
    for cached_query, cache_data in retriever_cache.items():
        cached_embedding = cache_data["embedding"]
        similarity = cosine_similarity(query_embedding, cached_embedding)

        if similarity >= threshold:
            log_message(f"[{dimension_name} Semantic Cache Hit] 원본: '{query}' -> 캐시: '{cached_query}' (유사도: {similarity:.4f})")
            return cache_data["results"]

    # 캐시 미스 - 새로 검색 수행
    log_message(f"[{dimension_name} Cache Miss] {query}")
    results = retriever.invoke(query)

    # 캐시 크기 제한 (FIFO 방식으로 가장 오래된 항목 삭제)
    if len(retriever_cache) >= max_cache_size:
        oldest_key = next(iter(retriever_cache))
        del retriever_cache[oldest_key]
        log_message(f"[{dimension_name} Cache] 최대 크기 도달, 가장 오래된 항목 삭제: {oldest_key}")

    # 캐시에 저장 (쿼리 임베딩과 결과 함께 저장)
    retriever_cache[query] = {
        "embedding": query_embedding,
        "results": results
    }

    return results

def cached_llm_invoke(prompt, cache_key_base="", use_cache=True):
    """
    LLM 호출을 캐싱하여 동일/유사한 프롬프트에 대해 재사용

    Args:
        prompt: LLM에 전달할 프롬프트
        cache_key_base: 캐시 키의 기본값 (예: "제품명_색상명")
        use_cache: 캐싱 사용 여부

    Returns:
        LLM 응답 문자열
    """
    if not use_cache:
        return llm.invoke(prompt).content.strip()

    # 프롬프트를 임베딩으로 변환 (1536차원 사용)
    prompt_embedding = embedding_1536.embed_query(prompt)

    # 캐시에서 유사한 프롬프트 찾기
    for cached_key, cache_data in llm_cache.items():
        cached_embedding = cache_data["embedding"]
        similarity = cosine_similarity(prompt_embedding, cached_embedding)

        if similarity >= LLM_SIMILARITY_THRESHOLD:
            log_message(f"[LLM Cache Hit] 키: '{cache_key_base}' (유사도: {similarity:.4f})")
            return cache_data["response"]

    # 캐시 미스 - 새로 LLM 호출
    log_message(f"[LLM Cache Miss] 키: '{cache_key_base}'")
    response = llm.invoke(prompt).content.strip()

    # 캐시 크기 제한 (FIFO 방식)
    if len(llm_cache) >= MAX_LLM_CACHE_SIZE:
        oldest_key = next(iter(llm_cache))
        del llm_cache[oldest_key]
        log_message(f"[LLM Cache] 최대 크기 도달, 가장 오래된 항목 삭제: {oldest_key}")

    # 캐시에 저장
    cache_key = cache_key_base or f"prompt_{len(llm_cache)}"
    llm_cache[cache_key] = {
        "embedding": prompt_embedding,
        "response": response
    }

    return response

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

        # LLM 캐싱을 위한 키 생성 (제품명_색상명_쿼리해시)
        product_name = d.metadata.get("product_name", "")
        code_name = d.metadata.get("code_name", "")
        cache_key_base = f"{product_name}_{code_name}_{hash(query) % 10000}"

        prompt = f"""
당신은 화장품 추천 챗봇입니다.
사용자의 질문: {query}

아래는 검색된 제품 정보와 리뷰입니다:
{d.page_content}

추천할 제품명과 색상을 맨 앞에 표시하고, 그 뒤에 리뷰 기반으로 간결하게 추천 이유를 한두 문장으로 작성하세요.
"""
        answer = cached_llm_invoke(prompt, cache_key_base=cache_key_base)

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

    # LLM 캐싱을 위한 키 생성
    cache_key_base = f"classify_{hash(user_input) % 10000}"

    prompt = f"""
이전 대화를 고려하여 마지막 사용자의 입력이 제품 추천 요청인지 판단하세요.
추천이면 "추천", 아니면 "일반"만 출력하세요.
{context_text}
"""
    answer = cached_llm_invoke(prompt, cache_key_base=cache_key_base)
    return answer.lower() == "추천"

# ------------------------------- 6-1. 카테고리 추론 -------------------------------
def infer_category_from_query(query):
    """쿼리에서 카테고리 추론"""
    category_keywords = {
        "lipstick": ["립스틱", "립스틱추천"],
        "liptint": ["틴트", "립틴트", "물틴트", "벨벳틴트"],
        "lipliner": ["립라이너", "립 라이너", "립펜슬"],
        "makeupfixer": ["픽서", "메이크업 픽서", "세팅", "세팅스프레이"],
        "lipgloss": ["글로스", "립글로스"],
        "lipbalm": ["립밤", "립 밤", "립케어밤"],
        "lipcare": ["립케어", "입술케어", "립스크럽"],
        "cushion": ["쿠션", "쿠션팩트", "쿠션파운데이션"],
        "foundation": ["파운데이션", "파데", "리퀴드파운데이션"],
        "concealer": ["컨실러", "커버컨실러"],
        "powder": ["파우더", "팩트", "피니쉬파우더"],
        "primer": ["프라이머", "메이크업베이스", "톤업크림", "메베"],
        "bbncc": [
            r"\b[bB]{2}\b",           # "BB", "bb" 독립 단어
            r"\b[cC]{2}\b",           # "CC", "cc" 독립 단어
            r"[bB]{2}\s*크림",        # "BB크림", "BB 크림"
            r"[cC]{2}\s*크림",        # "CC크림", "CC 크림"
            r"비비\s*크림?",          # 한글 "비비", "비비크림"
            r"씨씨\s*크림?",          # 한글 "씨씨", "씨씨크림"
        ],
        "blush": ["블러셔", "치크", "볼터치"],
        "contour": ["컨투어", "쉐딩", "쉐이딩", "컨투어링"],
        "highlighter": ["하이라이터"],
        "eyeshadow": ["아이섀도", "섀도우", "아이섀도우", "팔레트"],
        "eyeliner": ["아이라이너", "라이너", "젤라이너", "펜슬라이너"],
        "eyebrow": ["아이브로우", "눈썹", "브로우", "눈썹펜슬", "브로우카라", "브로우펜슬"],
        "mascara": ["마스카라", "컬링마스카라"],
        "eyefixer": ["아이 픽서", "아이픽서", "아이메이크업픽서"],
        "eyelashcare": ["속눈썹영양제", "래쉬케어", "래쉬세럼"],
    }

    query_lower = query.lower()
    for category, keywords in category_keywords.items():
        for keyword in keywords:
            if keyword in query_lower:
                log_message(f"[Category Filter] 쿼리에서 카테고리 감지: {category} (키워드: {keyword})")
                return category
    return None  # 카테고리를 찾지 못하면 전체 검색

# ------------------------------- 7. RAG 파이프라인 -------------------------------
def rag_pipeline_first(query, user_id="default", dimension=1536):
    """
    dimension: 1536 또는 3072 중 선택
    """
    timing_info = {}

    # 0. 카테고리 추론 및 필터링 설정
    category = infer_category_from_query(query)
    search_kwargs = {"k": 5}

    if category:
        search_kwargs["filter"] = {"category": category}
        log_message(f"[Filter] 카테고리 필터 적용: {category}")

    # 1. Retriever 시간 측정
    retriever_start = time.time()

    # 필터가 적용된 retriever 생성
    # ⚠️ 3072차원 임시 비활성화: 1536차원으로 폴백
    if dimension == 3072:
        if vectordb_3072 is None:
            log_message(f"[WARN] 3072차원이 비활성화되어 1536차원으로 폴백합니다.")
            dimension = 1536  # 폴백
        else:
            filtered_retriever = vectordb_3072.as_retriever(search_kwargs=search_kwargs)
            retrieved_docs = semantic_cached_retrieve(
                query, filtered_retriever, embedding_3072, retriever_cache_3072, "3072차원"
            )

    if dimension == 1536:
        filtered_retriever = vectordb_1536.as_retriever(search_kwargs=search_kwargs)
        retrieved_docs = semantic_cached_retrieve(
            query, filtered_retriever, embedding_1536, retriever_cache_1536, "1536차원"
        )

    timing_info["retriever"] = time.time() - retriever_start

    if not retrieved_docs:  # ✅ 검색 결과가 없을 경우
        return {
            "response": "관련된 제품을 찾지 못했습니다.",
            "images": [],
            "product_names": [],
            "code_names": [],
            "timing": timing_info
        }

    # 2. Reranker 시간 측정
    reranker_start = time.time()
    reranked_docs = rerank(query, retrieved_docs)
    timing_info["reranker"] = time.time() - reranker_start

    if not reranked_docs:  # ✅ 리랭크 결과가 없을 경우
        return {
            "response": "적합한 제품을 찾지 못했습니다.",
            "images": [],
            "product_names": [],
            "code_names": [],
            "timing": timing_info
        }

    session_cache[user_id]["last_query"] = query
    session_cache[user_id]["docs"] = reranked_docs
    session_cache[user_id]["already"] = set()
    session_cache[user_id]["current_index"] = 0

    # 3. LLM 시간 측정
    llm_start = time.time()
    result = recommend_next(user_id)
    timing_info["llm"] = time.time() - llm_start

    # timing 정보 추가
    result["timing"] = timing_info
    return result

def rag_pipeline_next(user_id="default"):
    return recommend_next(user_id)

# ------------------------------- 8. Flask 라우팅 -------------------------------
# ------------------------------- 8-1. 인증 라우트 -------------------------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        data = request.get_json()
        username = data.get("username", "").strip()
        email = data.get("email", "").strip()
        password = data.get("password", "").strip()

        # 유효성 검사
        if not username or not email or not password:
            return jsonify({"error": "모든 필드를 입력해주세요."}), 400

        # 중복 확인
        if User.query.filter_by(username=username).first():
            return jsonify({"error": "이미 존재하는 사용자명입니다."}), 400
        if User.query.filter_by(email=email).first():
            return jsonify({"error": "이미 존재하는 이메일입니다."}), 400

        # 새 사용자 생성
        new_user = User(username=username, email=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        # 자동 로그인
        login_user(new_user)
        return jsonify({"message": "회원가입 성공!", "username": username}), 201

    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        data = request.get_json()
        email = data.get("email", "").strip()
        password = data.get("password", "").strip()

        if not email or not password:
            return jsonify({"error": "이메일과 비밀번호를 입력해주세요."}), 400

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            return jsonify({"error": "이메일 또는 비밀번호가 올바르지 않습니다."}), 401

        login_user(user)
        return jsonify({"message": "로그인 성공!", "username": user.username}), 200

    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return jsonify({"message": "로그아웃 성공!"}), 200

@app.route("/user/me")
def get_current_user():
    """현재 로그인한 사용자 정보 조회"""
    if current_user.is_authenticated:
        return jsonify({
            "authenticated": True,
            "id": current_user.id,
            "username": current_user.username,
            "email": current_user.email
        }), 200
    else:
        return jsonify({"authenticated": False}), 200

# ------------------------------- 8-2. 구글 OAuth 로그인 -------------------------------
@app.route("/login/google")
def google_login():
    """구글 로그인 리다이렉트"""
    if not google:
        log_message("[ERROR] 구글 OAuth가 설정되지 않았습니다.")
        return jsonify({"error": "구글 로그인이 설정되지 않았습니다. GOOGLE_CLIENT_ID와 GOOGLE_CLIENT_SECRET을 확인하세요."}), 500

    redirect_uri = url_for("google_callback", _external=True)
    log_message(f"[Google OAuth] 리다이렉트 URI: {redirect_uri}")
    return google.authorize_redirect(redirect_uri)

@app.route("/login/google/callback")
def google_callback():
    """구글 로그인 콜백"""
    if not google:
        log_message("[ERROR] 구글 OAuth가 설정되지 않았습니다.")
        return jsonify({"error": "구글 로그인이 설정되지 않았습니다."}), 500

    try:
        log_message("[Google OAuth] 토큰 교환 시작")
        token = google.authorize_access_token()
        log_message(f"[Google OAuth] 토큰 교환 성공: {token.keys()}")

        user_info = token.get('userinfo')
        if not user_info:
            log_message("[ERROR] userinfo가 토큰에 없습니다.")
            return jsonify({"error": "구글 사용자 정보를 가져올 수 없습니다."}), 400

        email = user_info.get('email')
        username = user_info.get('name') or email.split('@')[0]
        log_message(f"[Google OAuth] 사용자 정보: email={email}, username={username}")

        # 이미 가입된 사용자인지 확인
        user = User.query.filter_by(email=email).first()

        if not user:
            # 새 사용자 생성 (구글 로그인은 비밀번호 없음)
            log_message(f"[Google OAuth] 새 사용자 생성: {email}")
            user = User(username=username, email=email)
            user.set_password(str(uuid.uuid4()))  # 임의의 비밀번호 설정
            db.session.add(user)
            db.session.commit()
        else:
            log_message(f"[Google OAuth] 기존 사용자 로그인: {email}")

        login_user(user)
        log_message(f"[Google OAuth] 로그인 성공: {email}")
        return redirect(url_for('index'))

    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        log_message(f"[Google Login Error] {e}\n{error_detail}")
        return jsonify({"error": f"구글 로그인 오류: {str(e)}"}), 500

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    # 전체 시간 측정 시작
    total_start = time.time()

    data = request.get_json()
    message = data.get("message", "")
    user_id = data.get("user_id", "default")
    dimension = data.get("dimension", 1536)  # 기본값 1536차원

    if user_id not in session_cache:
        session_cache[user_id] = {"history": [], "dimension": dimension}

    # 현재 사용자가 선택한 차원 저장
    session_cache[user_id]["dimension"] = dimension
    session_cache[user_id]["history"].append({"role": "user", "text": message})

    # 추천 쿼리인지 판단
    is_recommendation = is_recommendation_query(user_id, message)

    if is_recommendation:
        result = rag_pipeline_first(message, user_id, dimension)
    else:
        # 일반 대화 시간 측정
        llm_start = time.time()
        context_text = ""
        for turn in session_cache[user_id]["history"][-6:]:
            role = "사용자" if turn["role"]=="user" else "챗봇"
            context_text += f"{role}: {turn['text']}\n"

        # LLM 캐싱을 위한 키 생성 (마지막 사용자 메시지 해시)
        cache_key_base = f"general_chat_{hash(message) % 10000}"

        prompt = f"""
당신은 뷰티 전문가입니다. 제품 추천은 하지 않고, 일반 대화만 3줄 이내로 답변하세요.
{context_text}
"""
        answer = cached_llm_invoke(prompt, cache_key_base=cache_key_base)
        llm_time = time.time() - llm_start
        result = {
            "response": answer,
            "images": [],
            "product_names": [],
            "code_names": [],
            "timing": {"llm": llm_time}
        }

    # 전체 소요 시간 계산
    total_time = time.time() - total_start
    if "timing" not in result:
        result["timing"] = {}
    result["timing"]["total"] = total_time

    session_cache[user_id]["history"].append({"role": "bot", "text": result["response"]})

    # ✅ 로그인한 사용자의 경우 검색 쿼리를 데이터베이스에 저장
    if current_user.is_authenticated:
        try:
            search_history = SearchHistory(
                user_id=current_user.id,
                query=message,
                response=result["response"],
                dimension=dimension,
                is_recommendation=is_recommendation
            )
            db.session.add(search_history)
            db.session.commit()
        except Exception as e:
            log_message(f"[DB Error] 검색 기록 저장 실패: {e}")
            db.session.rollback()

    return jsonify(result)

# ------------------------------- 8-3. 검색 기록 조회 -------------------------------
@app.route("/history", methods=["GET"])
@login_required
def get_search_history():
    """로그인한 사용자의 검색 기록 조회"""
    try:
        # 쿼리 파라미터로 페이지네이션 지원
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)

        # 사용자의 검색 기록을 최신순으로 조회 (SQLAlchemy 2.0 스타일)
        histories = db.session.query(SearchHistory)\
            .filter_by(user_id=current_user.id)\
            .order_by(SearchHistory.created_at.desc())\
            .paginate(page=page, per_page=per_page, error_out=False)

        result = {
            "total": histories.total,
            "page": page,
            "per_page": per_page,
            "histories": [
                {
                    "id": h.id,
                    "query": h.query,
                    "response": h.response,
                    "dimension": h.dimension,
                    "is_recommendation": h.is_recommendation,
                    "created_at": h.created_at.isoformat()
                }
                for h in histories.items
            ]
        }

        return jsonify(result), 200

    except Exception as e:
        log_message(f"[DB Error] 검색 기록 조회 실패: {e}")
        return jsonify({"error": "검색 기록 조회 실패"}), 500

@app.route("/history/<int:history_id>", methods=["DELETE"])
@login_required
def delete_search_history(history_id):
    """특정 검색 기록 삭제"""
    try:
        history = db.session.query(SearchHistory).filter_by(id=history_id, user_id=current_user.id).first()

        if not history:
            return jsonify({"error": "검색 기록을 찾을 수 없습니다."}), 404

        db.session.delete(history)
        db.session.commit()

        return jsonify({"message": "검색 기록이 삭제되었습니다."}), 200

    except Exception as e:
        log_message(f"[DB Error] 검색 기록 삭제 실패: {e}")
        db.session.rollback()
        return jsonify({"error": "검색 기록 삭제 실패"}), 500

@app.route("/next", methods=["POST"])
def next_product():
    # 시간 측정 시작
    total_start = time.time()

    data = request.get_json()
    user_id = data.get("user_id", "default")
    # 저장된 dimension 사용 (없으면 기본값 1536)
    dimension = session_cache.get(user_id, {}).get("dimension", 1536)

    llm_start = time.time()
    result = recommend_next(user_id)
    llm_time = time.time() - llm_start

    # 시간 정보 추가
    total_time = time.time() - total_start
    result["timing"] = {
        "llm": llm_time,
        "total": total_time
    }

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

    # ------------------ swatch_bytes 캐싱 수정 ------------------
    swatch_path = session.get("last_swatch_path")
    cached_url = session.get("last_swatch_url")

    # 캐시된 파일이 없거나 URL이 바뀌었거나 파일이 삭제된 경우 새로 다운로드
    if not swatch_path or cached_url != swatch_url or not os.path.exists(swatch_path):
        try:
            resp = requests.get(swatch_url, timeout=10)
            resp.raise_for_status()

            # /tmp 디렉토리에 임시 파일 저장
            os.makedirs("/tmp", exist_ok=True)
            swatch_path = f"/tmp/swatch_{uuid.uuid4().hex}.png"
            with open(swatch_path, "wb") as f:
                f.write(resp.content)

            # 세션에는 파일 경로와 URL만 저장
            session["last_swatch_path"] = swatch_path
            session["last_swatch_url"] = swatch_url

        except Exception as e:
            return jsonify({"error": f"이미지 로드 실패: {e}"}), 400

    # 임시 파일에서 swatch_bytes 읽기
    with open(swatch_path, "rb") as f:
        swatch_bytes = f.read()
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
    # Cloud Run에서는 PORT 환경 변수를 사용
    port = int(os.getenv("PORT", 5000))
    # 프로덕션 환경에서는 debug=False 사용
    debug = os.getenv("FLASK_ENV") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)