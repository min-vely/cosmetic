import os
import time
import json
from tqdm import tqdm
from openai import OpenAI
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma


load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMA_DIR = os.path.join(BASE_DIR, "chroma_db")
MERGED_DIR = os.path.join(BASE_DIR, "data", "merged")
LOG_PATH = os.path.join(BASE_DIR, "chromadblog.txt")

BATCH_SIZE = 500

# ------------------ 로깅 함수 ------------------
def log_message(msg):
    print(msg)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {msg}\n")

# ------------------ 임베딩 객체 ------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    log_message("[ERROR] OPENAI_API_KEY가 .env에서 로드되지 않았습니다. .env 파일을 확인하세요.")
    exit(1)

try:
    client = OpenAI(api_key=OPENAI_API_KEY)
    client.models.list()  # ✅ 실제 호출 테스트
    log_message("[INFO] ✅ OpenAI API 연결 성공")
except Exception as e:
    log_message(f"[ERROR] ❌ OpenAI API 연결 실패: {e}")
    exit(1)

embedding = OpenAIEmbeddings(model="text-embedding-3-large", openai_api_key=OPENAI_API_KEY)

# ------------------ Chroma 로드 ------------------
if os.path.exists(CHROMA_DIR):
    vectordb = Chroma(persist_directory=CHROMA_DIR, embedding_function=embedding)
    log_message("[INFO] 기존 ChromaDB를 로드합니다...")
else:
    vectordb = Chroma(persist_directory=CHROMA_DIR, embedding_function=embedding)
    log_message("[INFO] ChromaDB가 없어 새로 생성합니다...")

# ------------------ 데이터 로드 ------------------
data = []
for fname in os.listdir(MERGED_DIR):
    if fname.endswith(".json"):
        fpath = os.path.join(MERGED_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, list):
                    data.extend(content)
                else:
                    data.append(content)
        except Exception as e:
            log_message(f"[WARN] 파일 읽기 실패: {fname} -> {e}")

# ------------------ 문서 생성 ------------------
docs = []
text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)

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

# ------------------ 진행 상태 확인 ------------------
start_batch = 0
if os.path.exists(LOG_PATH):
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if "✅ 진행 완료 배치" in line:
                try:
                    start_batch = int(line.strip().split(":")[-1]) + 1
                except:
                    pass

total_batches = len(range(0, len(docs), BATCH_SIZE))
log_message(f"[INFO] 총 배치 수: {total_batches}, 시작 배치 인덱스: {start_batch}")

# ------------------ 임베딩 실행 ------------------
for i in tqdm(range(start_batch, total_batches), desc="Embedding in batches"):
    ####################### 테스트용 로그 메시지
    log_message(f"[DEBUG] 현재 배치 진행 중: {i}/{total_batches}")
    batch_start = i * BATCH_SIZE
    batch = docs[batch_start:batch_start + BATCH_SIZE]
    if not batch:
        continue

    try:
        vectordb.add_documents(batch)
        vectordb.persist()
        log_message(f"✅ 진행 완료 배치: {i}")
    except Exception as e:
        log_message(f"[WARN] 임베딩 중 오류 발생: {e}")
        if "quota" in str(e).lower() or "rate" in str(e).lower():
            log_message("[ERROR] API 한도 또는 요금 초과로 중단됩니다. 진행 상태가 저장되었습니다.")
            break
        time.sleep(15)
        continue

    time.sleep(10)

log_message("[INFO] 임베딩 완료")