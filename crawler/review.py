import sys
import os
import time
import json
import re
import html
import unicodedata
import string
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import undetected_chromedriver as uc
import atexit

# ---------------- 경로 설정 ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(BASE_DIR, ".."))  # cosmetic 상위 폴더를 path에 추가

from preprocessing.preprocessing import OliveYoungPreprocessor  # ⚡ 여기서 import

CATEGORY_URL = "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100020006&rowsPerPage=48"
PRODUCT_URLS = []

def fetch_product_urls(driver):
    driver.get(CATEGORY_URL)
    WebDriverWait(driver, 10).until(
        EC.presence_of_all_elements_located(
            (By.XPATH, "//a[contains(@href,'getGoodsDetail.do') and contains(@href,'goodsNo=')]")
        )
    )
    anchors = driver.find_elements(
        By.XPATH, "//a[contains(@href,'getGoodsDetail.do') and contains(@href,'goodsNo=')]"
    )
    seen = set()
    urls = []
    for a in anchors:
        href = (a.get_attribute("href") or "").strip()
        if href and href not in seen:
            seen.add(href)
            urls.append(href)
    return urls[:48]  # 최대 48개

MAX_REVIEWS_PER_OPTION = 10

# ---------------- 기존 유틸 함수 그대로 ----------------
def sanitize_text(s: str) -> str:
    if not isinstance(s, str): return s
    return (s.replace("\u2028","\n").replace("\u2029","\n")
              .replace("\u00A0"," ").replace("\u202F"," ")
              .replace("\u200B","").replace("\ufeff","")
              .replace("\r\n","\n").replace("\r","\n")).strip()

def get_text_safe_wait(driver, selectors, timeout=8):
    for sel in selectors:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
            txt = el.text.strip()
            if txt: return txt
        except: 
            continue
    return ""

def num_only(s: str) -> str:
    s = s.replace(",", "")
    m = re.findall(r"\d+", s)
    return "".join(m) if m else ""

def click_if_present(driver, locator, by=By.CSS_SELECTOR, timeout=2):
    try:
        WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, locator))).click()
        return True
    except:
        return False

def normalize_option_label(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("[옵션]", "")
    s = re.sub(r"\[[^\]]+\]", "", s)
    s = s.replace("\n", " ")
    s = re.sub(r"\d{1,3}(?:,\d{3})*원", "", s)
    s = s.replace("_단품", " ").replace("단품", " ")
    s = re.sub(r"(기획|세트|증정|추가구성)", " ", s)
    s = s.lower()
    s = re.sub(r"[\s" + re.escape(string.punctuation) + r"]+", "", s)
    return s.strip()

# ---------------- 리뷰 관련 ----------------
def open_review_tab(driver):
    for by, loc in [
        (By.XPATH, "//a[contains(.,'리뷰')]"),
        (By.XPATH, "//button[contains(.,'리뷰')]"),
        (By.CSS_SELECTOR, ".prd_detail_tab a[href*='review']"),
        (By.CSS_SELECTOR, "a[href*='review']"),
        (By.CSS_SELECTOR, "button[data-tab*='review']"),
    ]:
        if click_if_present(driver, loc, by=by, timeout=3):
            time.sleep(0.3)
            break
    # 리뷰 영역 스크롤
    driver.execute_script("window.scrollBy(0, 400);")
    time.sleep(0.5)

def wait_review_container(driver, timeout=8):
    cands = ["ul#gdasList",".review_list","ul#reviewList","ul.gdas_list",
             "div.gdas_list ul",".review-list",".rv_list"]
    end = time.time()+timeout
    while time.time()<end:
        for css in cands:
            if driver.find_elements(By.CSS_SELECTOR, css): return css
        time.sleep(0.2)
    return None

def find_review_items(driver):
    for css in ["ul#gdasList > li",".review_list > li","ul#reviewList > li",
                "ul.gdas_list > li",".review-list > li",".rv_list > li","li[id^='gdas']"]:
        items = driver.find_elements(By.CSS_SELECTOR, css)
        if items: return items
    return []

def click_load_more_reviews(driver):
    for by, loc in [
        (By.XPATH, "//button[contains(.,'더보기')]"),
        (By.XPATH, "//a[contains(.,'더보기')]"),
        (By.CSS_SELECTOR, ".btn_review_more, .btn_more, .gdas_more, #reviewMore"),
        (By.XPATH, "//a[contains(.,'다음')]"),
        (By.CSS_SELECTOR, ".paging a.next"),
    ]:
        try:
            el = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((by, loc)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.2)
            el.click()
            return True
        except: 
            continue
    return False

def extract_option_and_body(it):
    opt = ""
    for sel in [".txt_option",".option",".rv_option",".gdas_option"]:
        try:
            opt = it.find_element(By.CSS_SELECTOR, sel).get_attribute("innerText").strip()
            if opt: break
        except: pass
    if not opt:
        try:
            el = it.find_element(By.XPATH, ".//*[contains(text(),'[옵션]')]")
            opt = el.get_attribute("innerText").strip()
        except:
            whole = (it.get_attribute("innerText") or it.text or "")
            m = re.search(r"\[옵션\]\s*[^\n\r]+", whole)
            if m: opt = m.group(0).strip()
    body = ""
    try:
        inner = it.find_element(By.CSS_SELECTOR, ".txt_inner").get_attribute("innerHTML")
        txt = re.sub(r"(?i)<br\s*/?>", "\n", inner)
        txt = re.sub(r"[\u2028\u2029]", "\n", txt)
        txt = re.sub(r"<[^>]+>", "", txt)
        body = html.unescape(txt).strip()
    except:
        for sel in [".txt_inner",".rv_txt",".review_txt",".gdas_txt",".cont",".content"]:
            try:
                body = it.find_element(By.CSS_SELECTOR, sel).text.strip()
                if body: break
            except: pass
        if not body:
            body = (it.text or "").strip()
            if opt: body = body.replace(opt,"").strip()
    return sanitize_text(opt), sanitize_text(body)

def collect_review_texts_for_option(driver, code_name_raw: str, limit: int = 10):
    # 현재 화면이 해당 옵션으로 필터된다고 가정하고 수집
    want_norm = normalize_option_label(code_name_raw)
    open_review_tab(driver)
    wait_review_container(driver, timeout=8)
    texts, seen = [], 0
    stagnate, MAX_STAGNATE = 0, 6
    while len(texts) < limit and stagnate < MAX_STAGNATE:
        items = find_review_items(driver)
        cur_len = len(items)
        if cur_len <= seen:
            stagnate += 1
            if not click_load_more_reviews(driver):
                break
            time.sleep(0.6)
            items = find_review_items(driver)
            cur_len = len(items)
        for it in items[seen:]:
            try:
                more = it.find_element(By.XPATH, ".//button[contains(.,'더보기')]|.//a[contains(.,'더보기')]")
                if more.is_displayed():
                    driver.execute_script("arguments[0].click();", more)
                    time.sleep(0.1)
            except: pass
            opt_txt, body_txt = extract_option_and_body(it)
            # UI 필터를 신뢰하지만, 기본/빈 라벨은 무조건 수집
            if want_norm in ("", "단품", "기본") or normalize_option_label(opt_txt) == want_norm or True:
                texts.append(body_txt)
            if len(texts) >= limit: break
        stagnate = 0 if cur_len > seen else stagnate
        seen = cur_len
    if not texts:
        for it in find_review_items(driver):
            texts.append(extract_option_and_body(it)[1])
            if len(texts) >= limit: break
    return texts

# -------- 라벨 추출(강화) --------
def get_radio_label_strong(driver, opt_radio) -> str:
    """
    옵션 라벨을 최대한 튼튼하게 얻는다.
    1) 형제 .txt/.text/.name
    2) 가장 가까운 상위 label의 텍스트
    3) aria-label / title / value / data-* 속성
    4) input[id] -> label[for=id]
    5) 가장 가까운 li 내부의 .txt/.text/.name
    """
    # 1) 형제 텍스트
    try:
        t = opt_radio.find_element(By.XPATH, "following-sibling::*[contains(@class,'txt') or contains(@class,'text') or contains(@class,'name')]").text.strip()
        if t: return t
    except: pass
    # 2) 상위 label
    try:
        t = opt_radio.find_element(By.XPATH, "ancestor::label[1]").text.strip()
        if t: return t
    except: pass
    # 3) 속성들
    for attr in ["aria-label", "title", "value", "data-name", "data-label", "data-opt-nm", "data-opt-name"]:
        try:
            v = (opt_radio.get_attribute(attr) or "").strip()
            if v: return v
        except: pass
    # 4) for=id
    try:
        _id = opt_radio.get_attribute("id")
        if _id:
            t = driver.find_element(By.CSS_SELECTOR, f"label[for='{_id}']").text.strip()
            if t: return t
    except: pass
    # 5) li 내부
    try:
        li = opt_radio.find_element(By.XPATH, "ancestor::li[1]")
        t = li.find_element(By.CSS_SELECTOR, ".txt, .text, .name").text.strip()
        if t: return t
    except: pass
    return ""

# -------- 옵션 순회 --------
def collect_reviews_per_radio_option(driver, max_reviews=10):
    open_review_tab(driver)
    wait_review_container(driver, timeout=8)
    option_recs = []

    # 드롭다운 펼치기(있으면)
    try:
        dropdown_btn = driver.find_element(By.CSS_SELECTOR, ".sel_option.item.all")
        driver.execute_script("arguments[0].click();", dropdown_btn)
        time.sleep(0.25)
    except: 
        pass

    # 옵션 목록
    try:
        radio_options = driver.find_elements(By.CSS_SELECTOR, ".opt-radio")
    except:
        radio_options = []

    if not radio_options:
        option_recs.append(("단품", collect_review_texts_for_option(driver, "단품", limit=max_reviews)))
        return option_recs

    for opt_radio in radio_options:
        try:
            # li 부모 요소 가져오기
            li_parent = opt_radio.find_element(By.XPATH, "ancestor::li[1]")

            # 비활성화(off) 옵션이면 건너뛰기
            li_class = li_parent.get_attribute("class") or ""
            if "off" in li_class.lower():
                continue  # 아예 수집하지 않음

            # 클릭 전 라벨 시도
            review_name = get_radio_label_strong(driver, opt_radio).strip()
            if review_name == "전체":
                continue

            # 클릭(스크롤 보정 포함)
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", opt_radio)
                time.sleep(0.05)
            except: pass
            driver.execute_script("arguments[0].click();", opt_radio)

            WebDriverWait(driver, 7).until(lambda d: len(find_review_items(d)) > 0)
            time.sleep(0.35)

            # 클릭 후 라벨 재시도(렌더 후 텍스트가 달라질 수 있음)
            if not review_name:
                review_name = get_radio_label_strong(driver, opt_radio).strip()

            # 그래도 없으면 첫 리뷰의 [옵션] 텍스트로 폴백
            if not review_name:
                items = find_review_items(driver)
                if items:
                    opt_txt, _ = extract_option_and_body(items[0])
                    if opt_txt.strip():
                        review_name = opt_txt.strip()

            # 마지막 폴백
            if not review_name:
                review_name = "미상옵션"

            texts = collect_review_texts_for_option(driver, review_name, limit=max_reviews)
            option_recs.append((review_name, texts))

        except Exception as e:
            print(f"Error processing option: {e}")
            # 실패해도 빈 라벨로는 저장하지 않음
            continue


    return option_recs

# ---------------- 메인 ----------------
def crawl_oliveyoung_reviews_and_preprocess():
    chrome_options = uc.ChromeOptions()
    chrome_options.add_argument("--window-size=1200,800")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--lang=ko-KR")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    driver = uc.Chrome(options=chrome_options)
    driver.set_page_load_timeout(30)
    driver.set_script_timeout(20)

    OUTPUT_DIR = os.path.join(BASE_DIR, "..", "data")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    OUT_PATH_RAW = os.path.join(OUTPUT_DIR, "oliveyoung_lip_makeup_reviews_raw.json")
    OUT_PATH_PRE = os.path.join(OUTPUT_DIR, "oliveyoung_lip_makeup_reviews_preprocessed.json")

    products = []
    try:
        # ---------------- 1. 카테고리에서 48개 상품 URL 수집 ----------------
        CATEGORY_URL = "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100020006&rowsPerPage=48"
        driver.get(CATEGORY_URL)
        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located(
                (By.XPATH, "//a[contains(@href,'getGoodsDetail.do') and contains(@href,'goodsNo=')]")
            )
        )
        anchors = driver.find_elements(
            By.XPATH, "//a[contains(@href,'getGoodsDetail.do') and contains(@href,'goodsNo=')]"
        )
        seen = set()
        PRODUCT_URLS = []
        for a in anchors:
            href = (a.get_attribute("href") or "").strip()
            if not href:
                continue
            # goodsNo만 추출
            m = re.search(r"goodsNo=(\w+)", href)
            if not m:
                continue
            goods_no = m.group(1)
            clean_url = f"https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo={goods_no}"
            if clean_url not in seen:
                seen.add(clean_url)
                PRODUCT_URLS.append(clean_url)

        PRODUCT_URLS = PRODUCT_URLS[:48]  # 최대 48개
        print(f"[INFO] {len(PRODUCT_URLS)}개 상품 링크 수집 완료")

        # ---------------- 2. 각 상품 페이지로 이동하여 리뷰 수집 ----------------
        for idx, url in enumerate(PRODUCT_URLS, 1):
            driver.get(url)
            time.sleep(1)
            
            brand = get_text_safe_wait(driver, ["p.prd_brand a",".brand_name a",".brand_name"])
            name  = get_text_safe_wait(driver, ["p.prd_name","h2.prd_name",".prd_info h2","h2.goods_txt","h1"])
            price = ""
            for sel in [".price-2","span.price-1 span.num",".total_price .num"]:
                txt = get_text_safe_wait(driver, [sel], timeout=3)
                digits = num_only(txt)
                if digits: price = digits; break
            main_img = ""
            for sel in ["div.prd_thumb img",".thumb img",".prd_img img",".left_area .img img",".imgArea img"]:
                try:
                    el = WebDriverWait(driver,3).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                    )
                    src = el.get_attribute("src") or el.get_attribute("data-src") or ""
                    if src: main_img = src; break
                except: pass

            option_reviews = collect_reviews_per_radio_option(driver, max_reviews=MAX_REVIEWS_PER_OPTION)
            for review_name, texts in option_reviews:
                rec = {
                    "brand_name": brand,
                    "product_name": name,
                    "price": price,
                    "product_main_image": main_img,
                    "review_name": review_name,
                    "product_url": url
                }
                for j, txt in enumerate(texts, start=1):
                    rec[f"text{j}"] = txt
                if not texts:
                    for j in range(1, MAX_REVIEWS_PER_OPTION+1):
                        rec[f"text{j}"] = ""
                products.append(rec)

            print(f"[{idx}/{len(PRODUCT_URLS)}] {name} | 옵션 {len(option_reviews)}개 완료")
    finally:
        try:
            driver.quit()
            atexit.unregister(driver.quit)
        except: pass
        finally: del driver

    # ---------------- 저장 (원본) ----------------
    with open(OUT_PATH_RAW, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    print(f"{len(products)}건 저장 완료 -> {OUT_PATH_RAW}")

    # ---------------- 전처리 적용 ----------------
    processor = OliveYoungPreprocessor(input_path=OUT_PATH_RAW, output_path=OUT_PATH_PRE)
    processor.load_json()
    processor.preprocess()
    processor.save_json()
    print(f"{len(processor.products)}건 전처리 후 저장 완료 -> {OUT_PATH_PRE}")


if __name__ == "__main__":
    t0 = time.time()
    crawl_oliveyoung_reviews_and_preprocess()
    print(f"[TIME] {time.time()-t0:.2f}s")