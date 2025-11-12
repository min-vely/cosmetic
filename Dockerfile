# Python 3.11 베이스 이미지
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 패키지 업데이트 및 필수 패키지 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# requirements-prod.txt 복사 및 패키지 설치
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

# gunicorn 설치 (프로덕션 서버)
RUN pip install --no-cache-dir gunicorn

# 애플리케이션 파일 복사
COPY . .

# 필요한 디렉토리 생성
RUN mkdir -p /tmp/flask_session

# 포트 노출 (Cloud Run은 환경 변수 PORT 사용)
EXPOSE 8080

# Cloud Run은 PORT 환경 변수를 제공하므로 기본값 설정
ENV PORT=8080
ENV FLASK_ENV=production

# gunicorn으로 Flask 앱 실행
# --bind 0.0.0.0:$PORT: Cloud Run의 PORT 환경 변수 사용
# --workers 2: 워커 프로세스 수
# --threads 4: 각 워커당 스레드 수
# --timeout 300: 타임아웃 5분 (임베딩 작업이 오래 걸릴 수 있음)
# --worker-class gthread: 스레드 기반 워커
CMD exec gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 300 --worker-class gthread app:app
