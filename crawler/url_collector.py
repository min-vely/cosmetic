import os
import re
import json
import time
from enum import Enum
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# ---------------- 설정 ----------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_OUTPUT = os.path.join(BASE_DIR, "snapshots")
os.makedirs(BASE_OUTPUT, exist_ok=True)

MAX_PAGES_PER_CATEGORY = 10
MAX_WAIT = 10  # 페이지 로드 최대 대기시간(초)
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

# ---------------- Enum 정의 ----------------
class CategoryEnum(Enum):
    # CUSHION = "1000001000200010009"
    # BLUSH = "1000001000200010006"
    # FOUNDATION = "1000001000200010002"
    # POWDER = "1000001000200010004"
    # CONCEALER = "1000001000200010005"
    # PRIMER = "1000001000200010003"
    # CONTOUR = "1000001000200010007"
    # HIGHLIGHTER = "1000001000200010008"
    # MAKEUP_FIXER = "1000001000200010010"
    # BBNCC = "1000001000200010001"
    # EYELINER = "1000001000200070002"
    # MASCARA = "1000001000200070001"
    # EYEBROW = "1000001000200070004"
    # EYESHADOW = "1000001000200070003"
    # EYELASHCARE = "1000001000200070007"
    # EYEFIXER = "1000001000200070008"
    # LIPLINER = "1000001000200060006"
    LIPTINT = "1000001000200060003"
    LIPSTICK = "1000001000200060004"
    LIPCARE = "1000001000200060001"
    LIPBALM = "1000001000200060007"
    LIPGLOSS = "1000001000200060002"


CATEGORY_NAME_MAP = {
    # CategoryEnum.CUSHION.value: "cushion",
    # CategoryEnum.BLUSH.value: "blush",
    # CategoryEnum.FOUNDATION.value: "foundation",
    # CategoryEnum.POWDER.value: "powder",
    # CategoryEnum.CONCEALER.value: "concealer",
    # CategoryEnum.PRIMER.value: "primer",
    # CategoryEnum.CONTOUR.value: "contour",
    # CategoryEnum.HIGHLIGHTER.value: "highlighter",
    # CategoryEnum.MAKEUP_FIXER.value: "makeupfixer",
    # CategoryEnum.BBNCC.value: "bbncc",
    # CategoryEnum.EYELINER.value: "eyeliner",
    # CategoryEnum.MASCARA.value: "mascara",
    # CategoryEnum.EYEBROW.value: "eyebrow",
    # CategoryEnum.EYESHADOW.value: "eyeshadow",
    # CategoryEnum.EYELASHCARE.value: "eyelashcare",
    # CategoryEnum.EYEFIXER.value: "eyefixer",
    # CategoryEnum.LIPLINER.value: "lipliner",
    CategoryEnum.LIPTINT.value: "liptint",
    CategoryEnum.LIPSTICK.value: "lipstick",
    CategoryEnum.LIPCARE.value: "lipcare",
    CategoryEnum.LIPBALM.value: "lipbalm",
    CategoryEnum.LIPGLOSS.value: "lipgloss",
}

CATEGORY_URLS = [
    f"https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo={cat.value}&rowsPerPage=48"
    for cat in CategoryEnum
]

# ---------------- 유틸 함수 ----------------
def normalize_goods_url(href: str) -> str:
    m = re.search(r"goodsNo=([A-Z0-9]+)", href or "")
    if m:
        goods_no = m.group(1)
        return f"https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo={goods_no}"
    return ""

def get_category_filename(url: str) -> str:
    m = re.search(r"dispCatNo=(\d+)", url)
    if m:
        disp_cat = m.group(1)
        cat_name = CATEGORY_NAME_MAP.get(disp_cat, disp_cat)
        return f"url_{cat_name}.json"
    else:
        safe_name = re.sub(r"[^\w\-]", "_", url)[:50]
        return f"url_{safe_name}.json"

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1366,900")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(f"user-agent={USER_AGENT}")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def wait_for_products_quick(driver, timeout=MAX_WAIT, poll=0.5):
    elapsed = 0
    anchors = []
    xpath = (
        "//a[contains(@href,'goodsNo=') or "
        "contains(@onclick,'goodsDetail') or "
        "contains(@href,'getGoodsDetail.do')]"
    )

    while elapsed < timeout:
        anchors = driver.find_elements(By.XPATH, xpath)
        if len(anchors) > 0:
            return anchors
        time.sleep(poll)
        elapsed += poll
    return anchors


def collect_product_urls_for_category(driver, category_url, max_pages=MAX_PAGES_PER_CATEGORY):
    collected, seen = [], set()

    for page in range(1, max_pages + 1):
        # 페이지 URL 구성
        if "pageIdx=" in category_url:
            url = re.sub(r"pageIdx=\d+", f"pageIdx={page}", category_url)
        else:
            sep = "&" if "?" in category_url else "?"
            url = f"{category_url}{sep}pageIdx={page}"

        print(f"[PAGE] {page} → {url}")
        driver.get(url)
        time.sleep(0.5)  # 페이지 로드 안정화용 짧은 대기

        # ✅ 카테고리 내 상품 개수 확인 (모든 카테고리 공통)
        try:
            info_elem = driver.find_element(By.CSS_SELECTOR, "p.cate_info_tx")
            info_text = info_elem.text.strip()

            # "0개의 상품이 등록되어 있습니다" 패턴에서 숫자 추출
            m = re.search(r"(\d+)\s*개의\s*상품이\s*등록되어\s*있습니다", info_text)
            if m:
                count = int(m.group(1))
                if count == 0:
                    print(f"[INFO] page {page}: 상품 개수 0 → 즉시 조기 종료")
                    break
        except NoSuchElementException:
            pass  # 페이지에 info 텍스트가 없을 경우 무시

        # ✅ 상품 로드 대기
        anchors = wait_for_products_quick(driver, timeout=MAX_WAIT)
        if not anchors:
            print(f"[INFO] page {page}: 상품 없음 (타임아웃) → 조기 종료")
            break

        # ✅ 상품 URL 수집
        new_count_before = len(collected)
        for a in anchors:
            href = a.get_attribute("href")
            norm = normalize_goods_url(href)
            if norm and norm not in seen:
                seen.add(norm)
                collected.append(norm)

        new_count_after = len(collected)
        new_items = new_count_after - new_count_before
        print(f"[INFO] page {page}: {new_items}개 → 누적 {new_count_after}개")

        if new_items == 0:
            print(f"[INFO] page {page}: 신규 상품 없음 → 조기 종료")
            break

    return collected

def collect_all_categories(category_urls, max_pages=MAX_PAGES_PER_CATEGORY, out_dir=BASE_OUTPUT):
    result = {}
    for cat_url in category_urls:
        driver = setup_driver()  # 카테고리 시작할 때 새 드라이버 생성
        try:
            cat_id = re.search(r"dispCatNo=(\d+)", cat_url).group(1)
            cat_name = next((c.name for c in CategoryEnum if c.value == cat_id), cat_id)
            print(f"\n=== 카테고리 시작: {cat_name} ({cat_id}) ===\n{cat_url}")

            urls = collect_product_urls_for_category(driver, cat_url, max_pages)
            result[cat_url] = urls

            filename = get_category_filename(cat_url)
            out_path = os.path.join(out_dir, filename)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(urls, f, ensure_ascii=False, indent=2)
            print(f"[SAVED] {len(urls)}개 URL → {out_path}")
        finally:
            driver.quit()  # 카테고리 끝나면 드라이버 종료
    return result


if __name__ == "__main__":
    snapshots = collect_all_categories(CATEGORY_URLS)
    print("\n=== 전체 완료 ===")
    for k, v in snapshots.items():
        print(f"{k}: {len(v)}개")
