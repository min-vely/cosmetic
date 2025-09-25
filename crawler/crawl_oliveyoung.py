import time
import json
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# 48개 상품 페이지
CAT_URL = "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100020006&rowsPerPage=48"

MAX_TABS = 4  # 동시에 열고 처리할 탭 개수

def wait_css(driver, css, timeout=15):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, css))
    )

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

def crawl_olive_young_parallel():
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

    try:
        driver.get(CAT_URL)
        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located(
                (By.XPATH, "//a[contains(@href,'getGoodsDetail.do') and contains(@href,'goodsNo=')]")
            )
        )

        anchors = driver.find_elements(
            By.XPATH, "//a[contains(@href,'getGoodsDetail.do') and contains(@href,'goodsNo=')]"
        )
        hrefs, seen = [], set()
        for a in anchors:
            href = (a.get_attribute("href") or "").strip()
            if href and href not in seen:
                seen.add(href)
                hrefs.append(href)

        product_links = hrefs[:48]  # 48개 상품

        tab_queue = []

        for i, link in enumerate(product_links, 1):
            # goodsNo 추출
            match = re.search(r"goodsNo=([A-Z0-9]+)", link)
            if not match:
                print(f"[SKIP] goodsNo를 찾을 수 없음: {link}")
                continue
            base_handle, detail_handle = open_in_new_tab(driver, link)
            tab_queue.append((i, link, base_handle, detail_handle))

            if len(tab_queue) >= MAX_TABS or i == len(product_links):
                for idx, url, base, handle in tab_queue:
                    driver.switch_to.window(handle)

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

                    # 옵션 드롭다운 클릭
                    try:
                        sel_button = driver.find_element(By.CSS_SELECTOR, ".sel_option")
                        sel_button.click()
                        time.sleep(0.5)
                    except:
                        pass

                    # 옵션 수집
                    variants = []
                    try:
                        option_elements = driver.find_elements(By.CSS_SELECTOR, ".option_value")
                        for option in option_elements:
                            option_name = option.text.strip()
                            if option_name:
                                variants.append({"code_name": option_name})
                    except:
                        pass

                    if not variants:
                        variants = [{"code_name": "단품"}]

                    for v in variants:
                        products_data.append({
                            "brand_name": brand,
                            "product_name": name,
                            "price": price,
                            "product_main_image": main_img,
                            "code_name": v["code_name"],
                            "product_url": link,
                        })

                    print(f"[{idx:02d}/{len(product_links)}] {name} - {len(variants)} variants")

                    # 탭 닫기
                    try:
                        driver.close()
                    except:
                        pass
                    try:
                        driver.switch_to.window(base)
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
        with open("../data/oliveyoung_lip_makeup.json", "w", encoding="utf-8") as f:
            json.dump(products_data, f, ensure_ascii=False, indent=2)
        print(f"{len(products_data)}건 저장 완료 -> oliveyoung_lip_makeup.json")

if __name__ == "__main__":
    start_time = time.time()
    crawl_olive_young_parallel()
    end_time = time.time()
    print(f"[TIME] 총 소요 시간: {end_time - start_time:.2f}초")
