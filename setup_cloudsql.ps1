# Cloud SQL 자동 설정 스크립트 (Windows PowerShell)
# 사용법: .\setup_cloudsql.ps1

$ErrorActionPreference = "Stop"  # 에러 발생 시 스크립트 중단

Write-Host "🐘 Cloud SQL (PostgreSQL) 설정 시작..." -ForegroundColor Cyan

# 프로젝트 ID 확인
try {
    $PROJECT_ID = (gcloud config get-value project 2>$null)
} catch {
    $PROJECT_ID = $null
}

if ([string]::IsNullOrEmpty($PROJECT_ID)) {
    Write-Host "❌ Google Cloud 프로젝트가 설정되지 않았습니다." -ForegroundColor Red
    Write-Host "다음 명령어로 프로젝트를 설정하세요:"
    Write-Host "  gcloud config set project YOUR_PROJECT_ID"
    exit 1
}

Write-Host "✅ 프로젝트: $PROJECT_ID" -ForegroundColor Green

# 변수 설정
$INSTANCE_NAME = "cosmetic-chatbot-db"
$DB_NAME = "cosmetic_db"
$DB_USER = "cosmetic_user"
$REGION = "asia-northeast3"  # 서울

# 1. Cloud SQL Admin API 활성화
Write-Host ""
Write-Host "1️⃣  Cloud SQL Admin API 활성화 중..." -ForegroundColor Yellow
gcloud services enable sqladmin.googleapis.com
Write-Host "   ✅ API 활성화 완료" -ForegroundColor Green

# 2. Cloud SQL 인스턴스 생성 여부 확인
Write-Host ""
Write-Host "2️⃣  Cloud SQL 인스턴스 확인 중..." -ForegroundColor Yellow
try {
    gcloud sql instances describe $INSTANCE_NAME 2>&1 | Out-Null
    Write-Host "   ✅ 인스턴스가 이미 존재합니다: $INSTANCE_NAME" -ForegroundColor Green
} catch {
    Write-Host "   📦 새 인스턴스 생성 중... (5-10분 소요)" -ForegroundColor Blue
    gcloud sql instances create $INSTANCE_NAME `
      --database-version=POSTGRES_15 `
      --tier=db-f1-micro `
      --region=$REGION `
      --storage-type=SSD `
      --storage-size=10GB `
      --backup-start-time=03:00 `
      --maintenance-window-day=SUN `
      --maintenance-window-hour=4 `
      --availability-type=zonal
    Write-Host "   ✅ 인스턴스 생성 완료" -ForegroundColor Green
}

# 연결 이름 가져오기
$CONNECTION_NAME = (gcloud sql instances describe $INSTANCE_NAME --format="value(connectionName)")
Write-Host "   📝 연결 이름: $CONNECTION_NAME" -ForegroundColor Green

# 3. 루트 비밀번호 설정
Write-Host ""
Write-Host "3️⃣  루트 사용자 비밀번호 설정" -ForegroundColor Yellow
$ROOT_PASSWORD_SECURE = Read-Host "   루트(postgres) 비밀번호 입력" -AsSecureString
$ROOT_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($ROOT_PASSWORD_SECURE)
)

if ([string]::IsNullOrEmpty($ROOT_PASSWORD)) {
    Write-Host "   ❌ 비밀번호가 비어있습니다." -ForegroundColor Red
    exit 1
}

gcloud sql users set-password postgres `
  --instance=$INSTANCE_NAME `
  --password=$ROOT_PASSWORD
Write-Host "   ✅ 루트 비밀번호 설정 완료" -ForegroundColor Green

# 4. 애플리케이션 데이터베이스 생성
Write-Host ""
Write-Host "4️⃣  애플리케이션 데이터베이스 생성 중..." -ForegroundColor Yellow
try {
    gcloud sql databases describe $DB_NAME --instance=$INSTANCE_NAME 2>&1 | Out-Null
    Write-Host "   ✅ 데이터베이스가 이미 존재합니다: $DB_NAME" -ForegroundColor Green
} catch {
    gcloud sql databases create $DB_NAME --instance=$INSTANCE_NAME
    Write-Host "   ✅ 데이터베이스 생성 완료: $DB_NAME" -ForegroundColor Green
}

# 5. 애플리케이션 사용자 생성
Write-Host ""
Write-Host "5️⃣  애플리케이션 사용자 생성" -ForegroundColor Yellow
$APP_PASSWORD_SECURE = Read-Host "   앱 사용자($DB_USER) 비밀번호 입력" -AsSecureString
$APP_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($APP_PASSWORD_SECURE)
)

if ([string]::IsNullOrEmpty($APP_PASSWORD)) {
    Write-Host "   ❌ 비밀번호가 비어있습니다." -ForegroundColor Red
    exit 1
}

# 사용자 존재 여부 확인
try {
    gcloud sql users describe $DB_USER --instance=$INSTANCE_NAME 2>&1 | Out-Null
    Write-Host "   ℹ️  사용자가 이미 존재합니다. 비밀번호를 업데이트합니다." -ForegroundColor Blue
    gcloud sql users set-password $DB_USER `
      --instance=$INSTANCE_NAME `
      --password=$APP_PASSWORD
} catch {
    gcloud sql users create $DB_USER `
      --instance=$INSTANCE_NAME `
      --password=$APP_PASSWORD
}
Write-Host "   ✅ 사용자 설정 완료: $DB_USER" -ForegroundColor Green

# 6. DATABASE_URL 생성 및 Secret Manager에 저장
Write-Host ""
Write-Host "6️⃣  DATABASE_URL 생성 및 Secret Manager에 저장 중..." -ForegroundColor Yellow

# Cloud Run용 DATABASE_URL (Unix 소켓 사용)
$DATABASE_URL = "postgresql://${DB_USER}:${APP_PASSWORD}@/${DB_NAME}?host=/cloudsql/${CONNECTION_NAME}"

# Secret 존재 여부 확인
try {
    gcloud secrets describe DATABASE_URL 2>&1 | Out-Null
    Write-Host "   ℹ️  DATABASE_URL Secret이 이미 존재합니다. 새 버전을 추가합니다." -ForegroundColor Blue
    $DATABASE_URL | gcloud secrets versions add DATABASE_URL --data-file=-
} catch {
    $DATABASE_URL | gcloud secrets create DATABASE_URL --data-file=-
}
Write-Host "   ✅ DATABASE_URL Secret 저장 완료" -ForegroundColor Green

# 7. Cloud Run 서비스 계정에 권한 부여
Write-Host ""
Write-Host "7️⃣  Cloud Run 서비스 계정에 Cloud SQL 권한 부여 중..." -ForegroundColor Yellow
$PROJECT_NUMBER = (gcloud projects describe $PROJECT_ID --format="value(projectNumber)")

gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" `
  --role="roles/cloudsql.client" `
  --condition=None
Write-Host "   ✅ 권한 부여 완료" -ForegroundColor Green

# 8. 로컬 개발용 DATABASE_URL 출력
Write-Host ""
Write-Host "8️⃣  로컬 개발 설정" -ForegroundColor Yellow
$LOCAL_DATABASE_URL = "postgresql://${DB_USER}:${APP_PASSWORD}@localhost:5432/${DB_NAME}"
Write-Host "   .env 파일에 다음 내용을 추가하세요:" -ForegroundColor Blue
Write-Host ""
Write-Host "DATABASE_URL=$LOCAL_DATABASE_URL" -ForegroundColor Green
Write-Host ""

# 9. Cloud SQL Proxy 다운로드 안내
Write-Host "9️⃣  로컬에서 Cloud SQL 연결하려면 Cloud SQL Proxy 필요" -ForegroundColor Yellow
Write-Host "   다운로드: https://cloud.google.com/sql/docs/postgres/sql-proxy"
Write-Host ""
Write-Host "   Windows용 다운로드:"
Write-Host "   https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.8.2/cloud-sql-proxy.x64.exe" -ForegroundColor Cyan
Write-Host ""
Write-Host "   실행 명령어:"
Write-Host "   cloud-sql-proxy.exe $CONNECTION_NAME" -ForegroundColor Green
Write-Host ""

# 완료 메시지
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host "✅ Cloud SQL 설정 완료!" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host ""
Write-Host "📋 설정 정보:" -ForegroundColor Blue
Write-Host "   인스턴스: $INSTANCE_NAME"
Write-Host "   데이터베이스: $DB_NAME"
Write-Host "   사용자: $DB_USER"
Write-Host "   리전: $REGION"
Write-Host "   연결 이름: $CONNECTION_NAME"
Write-Host ""
Write-Host "📝 다음 단계:" -ForegroundColor Yellow
Write-Host "   1. .env 파일에 DATABASE_URL 추가"
Write-Host "   2. Cloud SQL Proxy 다운로드 및 실행"
Write-Host "   3. 앱 실행: python app.py (테이블 자동 생성)"
Write-Host "   4. 데이터 마이그레이션 (선택): python migrate_sqlite_to_postgresql.py"
Write-Host "   5. Cloud Run 배포: .\deploy.ps1"
Write-Host ""
