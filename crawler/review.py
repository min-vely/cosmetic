import time, json, re, os, html, unicodedata, string
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

PRODUCT_URLS = [
    "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000177984&dispCatNo=100000100020006",
    "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000213153&dispCatNo=100000100020006"
]
MAX_REVIEWS_PER_OPTION = 10

# ---------------- utils ----------------
def sanitize_text(s: str) -> str:
    if not isinstance(s, str): return s
    return (s.replace("\u2028","\n").replace("\u2029","\n")
              .replace("\u00A0"," ").replace("\u202F"," ")
              .replace("\u200B","").replace("\ufeff","")
              .replace("\r\n","\n").replace("\r","\n")).strip()

def get_text_safe(scope, selectors):
    for sel in selectors:
        try:
            t = scope.find_element(By.CSS_SELECTOR, sel).text.strip()
            if t: return t
        except: pass
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
            time.sleep(0.2); break
    # 리뷰 영역으로 스크롤
    for css in ["#gdasList","#gdasReview",".review_list",".gdas_area",
                "#goodsEvaluation",".review_wrap","#review","#gdas"]:
        try:
            driver.execute_script(
                "var el=document.querySelector(arguments[0]); if(el){el.scrollIntoView({block:'center'});}", css)
            time.sleep(0.2); break
        except: pass

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
            time.sleep(0.1); el.click(); return True
        except: continue
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
            if normalize_option_label(opt_txt) != want_norm and want_norm not in ("", "단품", "기본"):
                continue
            texts.append(body_txt)
            if len(texts) >= limit: break
        stagnate = 0 if cur_len > seen else stagnate
        seen = cur_len
    if not texts:
        for it in find_review_items(driver):
            texts.append(extract_option_and_body(it)[1])
            if len(texts) >= limit: break
    return texts

def collect_reviews_per_radio_option(driver, max_reviews=10):
    """
    '전체 상품 옵션' 클릭 후, 두 번째 라디오 옵션부터 리뷰 수집
    """
    open_review_tab(driver)
    wait_review_container(driver, timeout=8)

    option_recs = []

    # 전체 옵션 버튼 클릭
    try:
        dropdown_btn = driver.find_element(By.CSS_SELECTOR, ".sel_option.item.all")
        driver.execute_script("arguments[0].click();", dropdown_btn)
        time.sleep(0.3)
    except:
        pass

    # 라디오 옵션 가져오기 (.opt-radio)
    try:
        radio_options = driver.find_elements(By.CSS_SELECTOR, ".opt-radio")
    except:
        radio_options = []

    if not radio_options or len(radio_options) < 2:
        # 라디오 옵션 없거나 1개만 있으면 단품 처리
        option_recs.append(("단품", collect_review_texts_for_option(driver, "단품", limit=max_reviews)))
        return option_recs

    # 두 번째 옵션부터 순회
    for opt in radio_options[1:]:
        try:
            label = opt.text.strip() or "옵션"
            driver.execute_script("arguments[0].click();", opt)
            
            # 리뷰 영역 로딩 대기
            WebDriverWait(driver, 5).until(lambda d: len(find_review_items(d)) >= 0)
            time.sleep(0.5)

            texts = collect_review_texts_for_option(driver, label, limit=max_reviews)
            option_recs.append((label, texts))
        except:
            option_recs.append((label, []))

    return option_recs


# ---------------- 메인 ----------------
def crawl_oliveyoung_reviews_radio_debug():
    chrome_options = Options()
    chrome_options.add_argument("--window-size=1366,900")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--lang=ko-KR")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.set_page_load_timeout(30)
    driver.set_script_timeout(20)

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_DIR = os.path.join(BASE_DIR, "..", "data")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    OUT_PATH = os.path.join(OUTPUT_DIR, "oliveyoung_lip_makeup_reviews_radio_debug.json")

    products = []
    try:
        for idx, url in enumerate(PRODUCT_URLS, 1):
            driver.get(url)
            time.sleep(1)
            brand = get_text_safe(driver, ["p.prd_brand a",".brand_name a",".brand_name"])
            name  = get_text_safe(driver, ["p.prd_name","h2.prd_name",".prd_info h2","h2.goods_txt","h1"])
            price = ""
            for sel in [".price-2","span.price-1 span.num",".total_price .num"]:
                try:
                    txt = driver.find_element(By.CSS_SELECTOR, sel).text.strip()
                    digits = num_only(txt)
                    if digits: price = digits; break
                except: pass
            main_img = ""
            for sel in ["div.prd_thumb img",".thumb img",".prd_img img",".left_area .img img",".imgArea img"]:
                try:
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                    src = el.get_attribute("src") or el.get_attribute("data-src") or ""
                    if src: main_img = src; break
                except: pass

            option_reviews = collect_reviews_per_radio_option(driver, max_reviews=MAX_REVIEWS_PER_OPTION)
            for code_name, texts in option_reviews:
                rec = {
                    "brand_name": brand,
                    "product_name": name,
                    "price": price,
                    "product_main_image": main_img,
                    "code_name": code_name,
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
        try: driver.quit()
        except: pass
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(products, f, ensure_ascii=False, indent=2)
        print(f"{len(products)}건 저장 완료 -> {OUT_PATH}")

if __name__ == "__main__":
    t0 = time.time()
    crawl_oliveyoung_reviews_radio_debug()
    print(f"[TIME] {time.time()-t0:.2f}s")
