import time
import json
import re
import os
import sys
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ---------------- preprocessing 불러오기 ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(BASE_DIR, ".."))
from preprocessing.preprocessing import OliveYoungPreprocessor

# ---------------- 설정 ----------------
CAT_URL = "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100020006&rowsPerPage=48"
MAX_PRODUCTS = 48
MAX_TABS = 4

# ---------------- 유틸 함수 ----------------
def get_text_safe(driver, selectors):
    for sel in selectors:
        try:
            t = driver.find_element(By.CSS_SELECTOR, sel).text.strip()
            if t:
                return t
        except:
            pass
    return ""

def num_only(s: str) -> str:
    s = s.replace(",", "")
    m = re.findall(r"\d+", s)
    return "".join(m) if m else ""

def open_in_new_tab(driver, url):
    base = driver.current_window_handle
    driver.execute_script("window.open(arguments[0], '_blank');", url)
    WebDriverWait(driver, 5).until(lambda d: len(d.window_handles) > 1)
    new_handles = [h for h in driver.window_handles if h != base]
    detail = new_handles[-1]
    driver.switch_to.window(detail)
    return base, detail

# ---------------- 크롤링 ----------------
def crawl_olive_young():
    chrome_options = Options()
    chrome_options.add_argument("--window-size=1366,900")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    products_data = []
    OUTPUT_DIR = os.path.join(BASE_DIR, "..", "data")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    OUTPUT_PATH = os.path.join(OUTPUT_DIR, "oliveyoung_lip_makeup.json")

    # 전처리기 생성
    preprocessor = OliveYoungPreprocessor(input_path=None, output_path=None)

    try:
        # ---------------- 카테고리 페이지 접속 ----------------
        driver.get(CAT_URL)
        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located(
                (By.XPATH, "//a[contains(@href,'getGoodsDetail.do') and contains(@href,'goodsNo=')]")
            )
        )

        # 상품 링크 수집 (중복 제거)
        anchors = driver.find_elements(
            By.XPATH, "//a[contains(@href,'getGoodsDetail.do') and contains(@href,'goodsNo=')]"
        )
        hrefs, seen = [], set()
        for a in anchors:
            href = (a.get_attribute("href") or "").strip()
            if href and href not in seen:
                seen.add(href)
                hrefs.append(href)
        product_links = hrefs[:MAX_PRODUCTS]

        tab_queue = []

        # ---------------- 제품별 탭 처리 ----------------
        for i, link in enumerate(product_links, 1):
            base_handle, detail_handle = open_in_new_tab(driver, link)
            tab_queue.append((i, link, base_handle, detail_handle))

            if len(tab_queue) >= MAX_TABS or i == len(product_links):
                for idx, url, base, handle in tab_queue:
                    driver.switch_to.window(handle)

                    # -------- 기본 정보 --------
                    brand = get_text_safe(driver, ["p.prd_brand a", "p.prd_brand", ".brand_name a", ".brand_name"])
                    name = get_text_safe(driver, ["p.prd_name", "h2.prd_name", ".prd_info h2", "h2.goods_txt", "h1"])
                    price = ""
                    for sel in [".price-2", "span.price-1 span.num", ".total_price .num"]:
                        try:
                            txt = driver.find_element(By.CSS_SELECTOR, sel).text.strip()
                            digits = num_only(txt)
                            if digits:
                                price = digits
                                break
                        except:
                            pass

                    # -------- 메인 이미지 --------
                    main_img = ""
                    for sel in ["div.prd_thumb img", ".thumb img", ".prd_img img", ".left_area .img img", ".imgArea img"]:
                        try:
                            el = driver.find_element(By.CSS_SELECTOR, sel)
                            src = el.get_attribute("src") or el.get_attribute("data-src") or ""
                            if src:
                                main_img = src
                                break
                        except:
                            pass

                    # -------- 옵션 + thumb_color --------
                    variants = []
                    try:
                        sel_button = driver.find_element(By.CSS_SELECTOR, ".sel_option")
                        sel_button.click()
                        WebDriverWait(driver, 5).until(
                            lambda d: len(d.find_elements(By.CSS_SELECTOR, ".option_value")) > 0
                        )
                        time.sleep(1)
                        option_elements = driver.find_elements(By.CSS_SELECTOR, ".option_value")
                        thumb_elements = driver.find_elements(By.CSS_SELECTOR, ".thumb-color img")

                        for i_opt, option in enumerate(option_elements):
                            option_name = option.text.strip()
                            thumb_url = ""
                            if i_opt < len(thumb_elements):
                                thumb_url = thumb_elements[i_opt].get_attribute("src") or thumb_elements[i_opt].get_attribute("data-src") or ""
                            if option_name:
                                variants.append({"code_name": option_name, "thumb_color": thumb_url})
                    except:
                        variants = [{"code_name": "단품", "thumb_color": ""}]

                    # -------- 상세 이미지 수집 --------
                    product_images = []
                    try:
                        try:
                            btn = driver.find_element(By.CLASS_NAME, "btn-controller")
                            btn.click()
                            time.sleep(1)
                        except:
                            pass

                        speedy_imgs = driver.find_elements(By.CSS_SELECTOR, ".speedycat-container img")
                        for img in speedy_imgs:
                            try:
                                driver.execute_script("arguments[0].scrollIntoView(true);", img)
                                time.sleep(0.2)
                                src = img.get_attribute("data-src") or img.get_attribute("src")
                                if src and not src.startswith("data:image"):
                                    product_images.append(src)
                            except:
                                continue

                        speedy_divs = driver.find_elements(By.CSS_SELECTOR, ".speedycat-container div")
                        for div in speedy_divs:
                            try:
                                bg_url = div.value_of_css_property("background-image")
                                if bg_url.startswith("url("):
                                    bg_url = bg_url[4:-1].strip('"').strip("'")
                                    if bg_url and not bg_url.startswith("data:image") and bg_url not in product_images:
                                        product_images.append(bg_url)
                            except:
                                continue
                    except Exception as e:
                        print("[IMAGE COLLECT ERROR]", e)

                    # -------- 전처리 적용 및 데이터 저장 --------
                    for v in variants:
                        clean_name = preprocessor.clean_product_name(name)
                        clean_code = preprocessor.clean_code_name(v["code_name"])
                        products_data.append({
                            "brand_name": brand,
                            "product_name": clean_name,
                            "price": price,
                            "product_main_image": main_img,
                            "code_name": clean_code,
                            "thumb_color": v.get("thumb_color", ""),
                            "product_url": url,
                            "product_images": product_images
                        })

                    print(f"[{idx:02d}/{len(product_links)}] {name} - {len(variants)} variants, 이미지 {len(product_images)}장 수집")

                    # 탭 닫고 기본 탭으로 복귀
                    try: driver.close()
                    except: pass
                    try: driver.switch_to.window(base)
                    except:
                        handles = driver.window_handles
                        if handles:
                            driver.switch_to.window(handles[0])

                tab_queue = []

    finally:
        try:
            driver.quit()
        except:
            pass

        # ---------------- JSON 저장 ----------------
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(products_data, f, ensure_ascii=False, indent=2)
        print(f"{len(products_data)}건 저장 완료 -> {OUTPUT_PATH}")


if __name__ == "__main__":
    start_time = time.time()
    crawl_olive_young()
    end_time = time.time()
    print(f"[TIME] 총 소요 시간: {end_time - start_time:.2f}초")
