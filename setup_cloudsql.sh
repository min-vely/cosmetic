#!/bin/bash

# Cloud SQL 자동 설정 스크립트
# 사용법: ./setup_cloudsql.sh

set -e  # 에러 발생 시 스크립트 중단

echo "🐘 Cloud SQL (PostgreSQL) 설정 시작..."

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 프로젝트 ID 확인
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)

if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}❌ Google Cloud 프로젝트가 설정되지 않았습니다.${NC}"
    echo "다음 명령어로 프로젝트를 설정하세요:"
    echo "  gcloud config set project YOUR_PROJECT_ID"
    exit 1
fi

echo -e "${GREEN}✅ 프로젝트: $PROJECT_ID${NC}"

# 변수 설정
INSTANCE_NAME="cosmetic-chatbot-db"
DB_NAME="cosmetic_db"
DB_USER="cosmetic_user"
REGION="asia-northeast3"  # 서울

# 1. Cloud SQL Admin API 활성화
echo ""
echo -e "${YELLOW}1️⃣  Cloud SQL Admin API 활성화 중...${NC}"
gcloud services enable sqladmin.googleapis.com
echo -e "${GREEN}   ✅ API 활성화 완료${NC}"

# 2. Cloud SQL 인스턴스 생성 여부 확인
echo ""
echo -e "${YELLOW}2️⃣  Cloud SQL 인스턴스 확인 중...${NC}"
if gcloud sql instances describe $INSTANCE_NAME &>/dev/null; then
    echo -e "${GREEN}   ✅ 인스턴스가 이미 존재합니다: $INSTANCE_NAME${NC}"
else
    echo -e "${BLUE}   📦 새 인스턴스 생성 중... (5-10분 소요)${NC}"
    gcloud sql instances create $INSTANCE_NAME \
      --database-version=POSTGRES_15 \
      --tier=db-f1-micro \
      --region=$REGION \
      --storage-type=SSD \
      --storage-size=10GB \
      --backup-start-time=03:00 \
      --maintenance-window-day=SUN \
      --maintenance-window-hour=4 \
      --availability-type=zonal
    echo -e "${GREEN}   ✅ 인스턴스 생성 완료${NC}"
fi

# 연결 이름 가져오기
CONNECTION_NAME=$(gcloud sql instances describe $INSTANCE_NAME --format="value(connectionName)")
echo -e "${GREEN}   📝 연결 이름: $CONNECTION_NAME${NC}"

# 3. 루트 비밀번호 설정
echo ""
echo -e "${YELLOW}3️⃣  루트 사용자 비밀번호 설정${NC}"
echo -n "   루트(postgres) 비밀번호 입력: "
read -s ROOT_PASSWORD
echo ""

if [ -z "$ROOT_PASSWORD" ]; then
    echo -e "${RED}   ❌ 비밀번호가 비어있습니다.${NC}"
    exit 1
fi

gcloud sql users set-password postgres \
  --instance=$INSTANCE_NAME \
  --password=$ROOT_PASSWORD
echo -e "${GREEN}   ✅ 루트 비밀번호 설정 완료${NC}"

# 4. 애플리케이션 데이터베이스 생성
echo ""
echo -e "${YELLOW}4️⃣  애플리케이션 데이터베이스 생성 중...${NC}"
if gcloud sql databases describe $DB_NAME --instance=$INSTANCE_NAME &>/dev/null; then
    echo -e "${GREEN}   ✅ 데이터베이스가 이미 존재합니다: $DB_NAME${NC}"
else
    gcloud sql databases create $DB_NAME --instance=$INSTANCE_NAME
    echo -e "${GREEN}   ✅ 데이터베이스 생성 완료: $DB_NAME${NC}"
fi

# 5. 애플리케이션 사용자 생성
echo ""
echo -e "${YELLOW}5️⃣  애플리케이션 사용자 생성${NC}"
echo -n "   앱 사용자($DB_USER) 비밀번호 입력: "
read -s APP_PASSWORD
echo ""

if [ -z "$APP_PASSWORD" ]; then
    echo -e "${RED}   ❌ 비밀번호가 비어있습니다.${NC}"
    exit 1
fi

# 사용자 존재 여부 확인 (에러 무시)
if gcloud sql users describe $DB_USER --instance=$INSTANCE_NAME &>/dev/null; then
    echo -e "${BLUE}   ℹ️  사용자가 이미 존재합니다. 비밀번호를 업데이트합니다.${NC}"
    gcloud sql users set-password $DB_USER \
      --instance=$INSTANCE_NAME \
      --password=$APP_PASSWORD
else
    gcloud sql users create $DB_USER \
      --instance=$INSTANCE_NAME \
      --password=$APP_PASSWORD
fi
echo -e "${GREEN}   ✅ 사용자 설정 완료: $DB_USER${NC}"

# 6. DATABASE_URL 생성 및 Secret Manager에 저장
echo ""
echo -e "${YELLOW}6️⃣  DATABASE_URL 생성 및 Secret Manager에 저장 중...${NC}"

# Cloud Run용 DATABASE_URL (Unix 소켓 사용)
DATABASE_URL="postgresql://${DB_USER}:${APP_PASSWORD}@/${DB_NAME}?host=/cloudsql/${CONNECTION_NAME}"

# Secret 존재 여부 확인
if gcloud secrets describe DATABASE_URL &>/dev/null; then
    echo -e "${BLUE}   ℹ️  DATABASE_URL Secret이 이미 존재합니다. 새 버전을 추가합니다.${NC}"
    echo -n "$DATABASE_URL" | gcloud secrets versions add DATABASE_URL --data-file=-
else
    echo -n "$DATABASE_URL" | gcloud secrets create DATABASE_URL --data-file=-
fi
echo -e "${GREEN}   ✅ DATABASE_URL Secret 저장 완료${NC}"

# 7. Cloud Run 서비스 계정에 권한 부여
echo ""
echo -e "${YELLOW}7️⃣  Cloud Run 서비스 계정에 Cloud SQL 권한 부여 중...${NC}"
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/cloudsql.client" \
  --condition=None
echo -e "${GREEN}   ✅ 권한 부여 완료${NC}"

# 8. 로컬 개발용 DATABASE_URL 출력
echo ""
echo -e "${YELLOW}8️⃣  로컬 개발 설정${NC}"
LOCAL_DATABASE_URL="postgresql://${DB_USER}:${APP_PASSWORD}@localhost:5432/${DB_NAME}"
echo -e "${BLUE}   .env 파일에 다음 내용을 추가하세요:${NC}"
echo ""
echo -e "${GREEN}DATABASE_URL=${LOCAL_DATABASE_URL}${NC}"
echo ""

# 9. Cloud SQL Proxy 다운로드 안내
echo -e "${YELLOW}9️⃣  로컬에서 Cloud SQL 연결하려면 Cloud SQL Proxy 필요${NC}"
echo "   다운로드: https://cloud.google.com/sql/docs/postgres/sql-proxy"
echo ""
echo "   실행 명령어:"
echo -e "${GREEN}   cloud-sql-proxy ${CONNECTION_NAME}${NC}"
echo ""

# 완료 메시지
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Cloud SQL 설정 완료!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BLUE}📋 설정 정보:${NC}"
echo "   인스턴스: $INSTANCE_NAME"
echo "   데이터베이스: $DB_NAME"
echo "   사용자: $DB_USER"
echo "   리전: $REGION"
echo "   연결 이름: $CONNECTION_NAME"
echo ""
echo -e "${YELLOW}📝 다음 단계:${NC}"
echo "   1. .env 파일에 DATABASE_URL 추가"
echo "   2. Cloud SQL Proxy 실행: cloud-sql-proxy ${CONNECTION_NAME}"
echo "   3. 앱 실행: python app.py (테이블 자동 생성)"
echo "   4. 데이터 마이그레이션 (선택): python migrate_sqlite_to_postgresql.py"
echo "   5. Cloud Run 배포: ./deploy.sh"
echo ""
