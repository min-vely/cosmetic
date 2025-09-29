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
sys.path.append(os.path.join(BASE_DIR, ".."))  # cosmetic 상위 폴더를 path에 추가

from preprocessing.preprocessing import OliveYoungPreprocessor  # ⚡ 여기서 import


# ---------------- 단일 상품 URL ----------------
PRODUCT_URLS = [
    "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000161007"
]

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

# ---------------- 크롤링 ----------------
def crawl_single_product():
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

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_DIR = os.path.join(BASE_DIR, "..", "data")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    OUTPUT_PATH = os.path.join(OUTPUT_DIR, "oliveyoung_lip_makeup.json")

    # 전처리기 생성
    preprocessor = OliveYoungPreprocessor(input_path=None, output_path=None)


    try:
        for idx, link in enumerate(PRODUCT_URLS, 1):
            driver.get(link)
            time.sleep(2)  # 페이지 로딩 대기

            # 기본 정보
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

            # 메인 이미지
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

            # 옵션 수집
            variants = []
            try:
                sel_button = driver.find_element(By.CSS_SELECTOR, ".sel_option")
                sel_button.click()
                WebDriverWait(driver, 5).until(
                    lambda d: len(d.find_elements(By.CSS_SELECTOR, ".option_value")) > 0
                )
                time.sleep(1)
                option_elements = driver.find_elements(By.CSS_SELECTOR, ".option_value")
                for option in option_elements:
                    option_name = option.text.strip()
                    if option_name:
                        variants.append({"code_name": option_name})
            except:
                variants = [{"code_name": "단품"}]

            # 상세 이미지 수집
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

            # ---------------- 전처리 적용 ----------------
            for v in variants:
                clean_name = preprocessor.clean_product_name(name)
                clean_code = preprocessor.clean_code_name(v["code_name"])

                products_data.append({
                    "brand_name": brand,
                    "product_name": clean_name,
                    "price": price,
                    "product_main_image": main_img,
                    "code_name": clean_code,
                    "product_url": link,
                    "product_images": product_images
                })

            print(f"[{idx}/{len(PRODUCT_URLS)}] {name} - {len(variants)} variants, 이미지 {len(product_images)}장 수집")

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
    crawl_single_product()
    end_time = time.time()
    print(f"[TIME] 총 소요 시간: {end_time - start_time:.2f}초")
