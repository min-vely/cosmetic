import os
import re
import json
import time
from enum import Enum
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# ---------------- 설정 ----------------
BASE_OUTPUT = "snapshots"
os.makedirs(BASE_OUTPUT, exist_ok=True)

CATEGORY_URLS = [
    "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=1000001000200010009&rowsPerPage=48",  # 쿠션
    "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=1000001000200010006&rowsPerPage=48",  # 블러셔
]

MAX_PAGES_PER_CATEGORY = 10
MAX_WAIT = 10  # 페이지 로드 최대 대기시간(초)
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

# ---------------- Enum 정의 ----------------
class CategoryEnum(Enum):
    CUSHION = "1000001000200010009"
    BLUSH = "1000001000200010006"

CATEGORY_NAME_MAP = {
    CategoryEnum.CUSHION.value: "cushion",
    CategoryEnum.BLUSH.value: "blush"
}

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
    """
    상품 요소가 나타날 때까지 최대 timeout 초 동안 polling하며 기다림.
    timeout 내에 나타나면 요소 리스트 반환, 아니면 빈 리스트
    """
    elapsed = 0
    while elapsed < timeout:
        anchors = driver.find_elements(By.XPATH, "//a[contains(@href,'getGoodsDetail.do') and contains(@href,'goodsNo=')]")
        if anchors:
            return anchors
        time.sleep(poll)
        elapsed += poll
    return []

def collect_product_urls_for_category(driver, category_url, max_pages=MAX_PAGES_PER_CATEGORY):
    collected, seen = [], set()

    for page in range(1, max_pages + 1):
        if "pageIdx=" in category_url:
            url = re.sub(r"pageIdx=\d+", f"pageIdx={page}", category_url)
        else:
            sep = "&" if "?" in category_url else "?"
            url = f"{category_url}{sep}pageIdx={page}"

        print(f"[PAGE] {page} → {url}")
        driver.get(url)

        anchors = wait_for_products_quick(driver)
        if not anchors:
            print(f"[INFO] page {page}: 상품 없음 → 조기 종료")
            break

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
    driver = setup_driver()
    try:
        result = {}
        for cat_url in category_urls:
            print(f"\n=== 카테고리 시작 ===\n{cat_url}")
            urls = collect_product_urls_for_category(driver, cat_url, max_pages)
            result[cat_url] = urls

            filename = get_category_filename(cat_url)
            out_path = os.path.join(out_dir, filename)

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(urls, f, ensure_ascii=False, indent=2)
            print(f"[SAVED] {len(urls)}개 URL → {out_path}")
        return result
    finally:
        driver.quit()

if __name__ == "__main__":
    snapshots = collect_all_categories(CATEGORY_URLS)
    print("\n=== 전체 완료 ===")
    for k, v in snapshots.items():
        print(f"{k}: {len(v)}개")
