import time, json, re, os, html, unicodedata, string
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

CAT_URL = "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100020006&rowsPerPage=48"

# === 실행 설정 ===
MAX_TABS = 1                     # 테스트: 동시에 1탭 (전체 크롤링시 4 권장)
MAX_REVIEWS_PER_OPTION = 10      # 옵션별 리뷰 최대 개수
PRODUCT_LIMIT = 2                # 테스트: 첫 2개만 (전체는 48)

# ---------- utils ----------
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

def open_in_new_tab(driver, url):
    base = driver.current_window_handle
    driver.execute_script("window.open(arguments[0], '_blank');", url)
    WebDriverWait(driver, 5).until(lambda d: len(d.window_handles) > 1)
    new = [h for h in driver.window_handles if h != base][-1]
    driver.switch_to.window(new)
    return base, new

def click_if_present(driver, locator, by=By.CSS_SELECTOR, timeout=2):
    try:
        WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, locator))).click()
        return True
    except:
        return False

# 옵션 라벨 정규화(양쪽 표기가 달라도 맞춰주기)
def normalize_option_label(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("[옵션]", "")
    s = re.sub(r"\[[^\]]+\]", "", s)               # [단독], [기획] 등 제거
    s = s.replace("\n", " ")
    s = re.sub(r"\d{1,3}(?:,\d{3})*원", "", s)      # 가격 제거
    s = s.replace("_단품", " ").replace("단품", " ")  # '단품' 꼬리 제거
    s = re.sub(r"(기획|세트|증정|추가구성)", " ", s)   # 부가어 제거(필요시 추가)
    s = s.lower()
    # 공백/구두점/기호 제거
    s = re.sub(r"[\s" + re.escape(string.punctuation) + r"]+", "", s)
    return s.strip()

# ---------- review helpers ----------
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
    # 옵션 텍스트
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

    # 본문(.txt_inner) HTML → 텍스트
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

def select_review_option(driver, target_label_raw: str) -> bool:
    """리뷰의 '전체상품옵션'에서 target_label_raw(= code_name) 같은 옵션 선택"""
    target_norm = normalize_option_label(target_label_raw)

    # <select> 유형
    for sel in ["select#optGoodsSel","select[name='goodsSno']","select[name='goodsSnoCd']","select#reviewGoodsSelect"]:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            for o in el.find_elements(By.TAG_NAME, "option"):
                if normalize_option_label(o.text) == target_norm:
                    driver.execute_script(
                        "arguments[0].selected = true; arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", o)
                    time.sleep(0.5)
                    return True
        except: pass

    # 커스텀 드롭다운
    opened = False
    for btn in [".gdas_sort .sel_option",".gdas_sort .select_btn",".select_btn",".sel_option",".gdas_sort .selected"]:
        if click_if_present(driver, btn, timeout=2):
            opened = True; break
    if opened:
        for css in [".gdas_sort .select_list li a","ul.select_list li a",".select_list a"]:
            try:
                for a in driver.find_elements(By.CSS_SELECTOR, css):
                    if normalize_option_label(a.text) == target_norm:
                        driver.execute_script("arguments[0].click();", a)
                        time.sleep(0.5)
                        return True
            except: pass
    return False

def has_option_filter_ui(driver) -> bool:
    """리뷰 영역에 옵션 필터 UI가 존재하는지"""
    return bool(driver.find_elements(
        By.CSS_SELECTOR,
        "select#optGoodsSel, select[name='goodsSno'], select[name='goodsSnoCd'], "
        "select#reviewGoodsSelect, .gdas_sort .sel_option, .gdas_sort .select_btn"
    ))

def collect_review_texts_for_option(driver, code_name_raw: str, limit: int = 10):
    """현재 상세 페이지에서 code_name_raw 옵션의 리뷰 본문 텍스트만 최대 N개 수집 (멈춤 방지 강화)"""
    open_review_tab(driver)
    wait_review_container(driver, timeout=8)

    # 옵션 선택(실패해도 아래에서 라벨로 필터링)
    _ = select_review_option(driver, code_name_raw)
    want_norm = normalize_option_label(code_name_raw)
    lax = (want_norm in ("", "단품", "기본")) or (not has_option_filter_ui(driver))

    texts, seen = [], 0
    stagnate, MAX_STAGNATE = 0, 6  # 진전 없으면 그만

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
            # 더보기 펼치기
            try:
                more = it.find_element(By.XPATH, ".//button[contains(.,'더보기')]|.//a[contains(.,'더보기')]")
                if more.is_displayed():
                    driver.execute_script("arguments[0].click();", more)
                    time.sleep(0.1)
            except:
                pass

            opt_txt, body_txt = extract_option_and_body(it)
            # 옵션 라벨이 리뷰에 안 붙는 페이지(lax)면 필터 생략
            if not lax and normalize_option_label(opt_txt) != want_norm:
                continue

            texts.append(body_txt)
            if len(texts) >= limit:
                break

        stagnate = 0 if cur_len > seen else stagnate
        seen = cur_len

    # 백업: 한 건도 못 모았으면 옵션검사 없이 상위 N개
    if not texts:
        for it in find_review_items(driver):
            try:
                more = it.find_element(By.XPATH, ".//button[contains(.,'더보기')]|.//a[contains(.,'더보기')]")
                if more.is_displayed():
                    driver.execute_script("arguments[0].click();", more); time.sleep(0.1)
            except: pass
            texts.append(extract_option_and_body(it)[1])
            if len(texts) >= limit:
                break

    return texts

# ---------- main ----------
def crawl_oliveyoung_with_reviews_flat():
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
    OUT_PATH = os.path.join(OUTPUT_DIR, "oliveyoung_lip_makeup_with_reviews_flat.json")

    products = []

    try:
        driver.get(CAT_URL)
        WebDriverWait(driver, 12).until(
            EC.presence_of_all_elements_located(
                (By.XPATH, "//a[contains(@href,'getGoodsDetail.do') and contains(@href,'goodsNo=')]")
            )
        )
        anchors = driver.find_elements(By.XPATH, "//a[contains(@href,'getGoodsDetail.do') and contains(@href,'goodsNo=')]")
        hrefs, seen = [], set()
        for a in anchors:
            href = (a.get_attribute("href") or "").strip()
            if href and href not in seen:
                seen.add(href); hrefs.append(href)

        # ★ 테스트: 첫 N개만
        product_links = hrefs[:PRODUCT_LIMIT]
        print(f"[TEST] Processing first {PRODUCT_LIMIT} products")

        tab_queue = []
        for i, link in enumerate(product_links, 1):
            base, detail = open_in_new_tab(driver, link)
            try:
                driver.find_element(By.CSS_SELECTOR, ".sel_option").click()
            except: pass
            tab_queue.append((i, link, base, detail))

            if len(tab_queue) >= MAX_TABS or i == len(product_links):
                for idx, url, base_handle, handle in tab_queue:
                    driver.switch_to.window(handle)

                    brand = get_text_safe(driver, ["p.prd_brand a","p.prd_brand",".brand_name a",".brand_name"])
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

                    # 옵션 수집 (raw=저장용 문자열 그대로)
                    variants = []
                    try:
                        for opt in driver.find_elements(By.CSS_SELECTOR, ".option_value"):
                            raw = opt.text.strip()
                            if raw: variants.append(raw)
                    except: pass
                    if not variants: variants = ["단품"]

                    # 옵션별 리뷰 10개 수집 + 평평하게 저장(text1..text10)
                    for raw_label in variants:
                        try:
                            texts = collect_review_texts_for_option(driver, raw_label, limit=MAX_REVIEWS_PER_OPTION)
                        except Exception:
                            texts = []

                        rec = {
                            "brand_name": brand,
                            "product_name": name,
                            "price": price,
                            "product_main_image": main_img,
                            "code_name": raw_label,      # 줄바꿈/가격 포함한 원 문자열 그대로
                            "product_url": url
                        }
                        for j, txt in enumerate(texts[:MAX_REVIEWS_PER_OPTION], start=1):
                            rec[f"text{j}"] = txt

                        products.append(rec)

                    print(f"[{idx:02d}/{len(product_links)}] {name} | variants: {len(variants)}")

                    # 탭 정리
                    try: driver.close()
                    except: pass
                    try: driver.switch_to.window(base_handle)
                    except:
                        handles = driver.window_handles
                        if handles: driver.switch_to.window(handles[0])

                tab_queue = []

    finally:
        try:
            driver.quit()
        except: pass
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(products, f, ensure_ascii=False, indent=2)
        print(f"{len(products)}건 저장 완료 -> {OUT_PATH}")

if __name__ == "__main__":
    t0 = time.time()
    crawl_oliveyoung_with_reviews_flat()
    print(f"[TIME] {time.time()-t0:.2f}s")