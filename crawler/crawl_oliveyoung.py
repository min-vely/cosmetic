import os
import time
import json
import re
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
SNAPSHOTS_DIR = os.path.join(BASE_DIR, "..", "snapshots")
OUTPUT_DIR = os.path.join(BASE_DIR, "..", "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

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
    driver.execute_script(f"window.open('about:blank', '_blank');")
    WebDriverWait(driver, 5).until(lambda d: len(d.window_handles) > 1)

    new_handles = [h for h in driver.window_handles if h != base]
    detail = new_handles[-1]
    driver.switch_to.window(detail)
    driver.execute_script(f"window.location.href = '{url}';")

    try:
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except:
        pass

    return base, detail

# ---------------- 크롤링 함수 ----------------
def crawl_category_file(input_json):
    with open(input_json, "r", encoding="utf-8") as f:
        product_links = json.load(f)

    fname = os.path.basename(input_json)
    suffix = fname.replace("url_", "").replace(".json", "")
    output_path = os.path.join(OUTPUT_DIR, f"oliveyoung_{suffix}.json")

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

    preprocessor = OliveYoungPreprocessor(input_path=None, output_path=None)
    products_data = []
    tab_queue = []

    try:
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
                        thumb_divs = driver.find_elements(By.CSS_SELECTOR, ".thumb-color")

                        for i_opt, option in enumerate(option_elements):
                            option_name = option.text.strip()
                            thumb_url = ""
                            if i_opt < len(thumb_divs):
                                div = thumb_divs[i_opt]
                                try:
                                    path = div.find_element(By.CSS_SELECTOR, "input[name^='colrCmprImgPathNm_']").get_attribute("value")
                                    filename = div.find_element(By.CSS_SELECTOR, "input[name^='colrCmprImgNm_']").get_attribute("value")
                                    if path and filename:
                                        thumb_url = f"https://image.oliveyoung.co.kr/uploads/images/{path}/{filename}"
                                except:
                                    pass
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
                                if src and not src.startswith("data:image") and src not in product_images:
                                    product_images.append(src)
                            except:
                                continue

                        speedy_divs = driver.find_elements(By.CSS_SELECTOR, ".speedycat-container div")
                        for div in speedy_divs:
                            try:
                                bg_url = div.value_of_css_property("background-image")
                                if bg_url and bg_url.startswith("url("):
                                    bg_url = bg_url[4:-1].strip('"').strip("'")
                                    if bg_url and not bg_url.startswith("data:image") and bg_url not in product_images:
                                        product_images.append(bg_url)
                            except:
                                continue

                        temp_imgs = driver.find_elements(By.CSS_SELECTOR, "#tempHtml2 img, div#tempHtml2.contEditor img, #goodsDetailHtml.contEditor img, .contEditor#tempHtml2 img")
                        for img in temp_imgs:
                            try:
                                src = img.get_attribute("src") or img.get_attribute("data-src") or ""
                                if src and not src.startswith("data:image") and src not in product_images:
                                    product_images.append(src)
                            except:
                                continue

                        if not product_images:
                            fallback_imgs = driver.find_elements(By.CSS_SELECTOR, ".prd_detail_cont picture img, #new_detail_wrap picture img")
                            for img in fallback_imgs:
                                try:
                                    src = img.get_attribute("src")
                                    if src and "uploads/images/details" in src and src not in product_images:
                                        product_images.append(src)
                                except:
                                    continue

                        if not product_images:
                            alt_imgs = driver.find_elements(By.CSS_SELECTOR, "#goodsImgArea img, .prd_detail_area img")
                            for img in alt_imgs:
                                try:
                                    src = img.get_attribute("src")
                                    if src and "uploads/images" in src and not src.startswith("data:image") and src not in product_images:
                                        product_images.append(src)
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

                    print(f"[{idx:03d}/{len(product_links)}] {name} - {len(variants)} variants, 이미지 {len(product_images)}장 수집")

                    try: driver.close()
                    except: pass
                    try: driver.switch_to.window(base)
                    except:
                        handles = driver.window_handles
                        if handles:
                            driver.switch_to.window(handles[0])

                tab_queue = []

    finally:
        try: driver.quit()
        except: pass

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(products_data, f, ensure_ascii=False, indent=2)
        print(f"{len(products_data)}건 저장 완료 -> {output_path}")


if __name__ == "__main__":
    start_time = time.time()

    json_files = [os.path.join(SNAPSHOTS_DIR, f) for f in os.listdir(SNAPSHOTS_DIR) if f.endswith(".json")]
    for jf in json_files:
        print(f"=== 카테고리 파일 처리 === {jf}")
        crawl_category_file(jf)

    end_time = time.time()
    print(f"[TIME] 총 소요 시간: {end_time - start_time:.2f}초")
