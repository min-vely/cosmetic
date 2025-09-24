import json, time, re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

CAT_URL = "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100020006"

# -------------------- helpers --------------------
def wait_css(driver, css, timeout=15):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, css))
    )

def click_if_present(driver, locator, by=By.CSS_SELECTOR, timeout=3):
    try:
        WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((by, locator))
        ).click()
        return True
    except:
        return False

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
    """상품 상세를 새 탭으로 열고 (base, detail) 핸들 반환"""
    base = driver.current_window_handle
    driver.execute_script("window.open(arguments[0], '_blank');", url)
    WebDriverWait(driver, 5).until(lambda d: len(d.window_handles) > 1)
    new_handles = [h for h in driver.window_handles if h != base]
    detail = new_handles[-1]
    driver.switch_to.window(detail)
    return base, detail

def safe_get(driver, url, tries=2):
    """창/탭 유실 대비한 get() 래퍼"""
    for _ in range(tries):
        try:
            driver.get(url)
            return True
        except:
            try:
                handles = driver.window_handles
                if handles:
                    driver.switch_to.window(handles[0])
            except:
                pass
            time.sleep(0.3)
    return False
# -------------------------------------------------

def crawl_olive_young():
    chrome_options = Options()
    # 처음엔 headless 끄고 동작 확인 권장
    # chrome_options.add_argument("--headless=new")
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

        # 첫 방문 팝업/레이어 닫기(여러 패턴 시도)
        for loc, by in [
            ("//button[contains(.,'오늘 안 보기')]", By.XPATH),
            ("//a[contains(.,'오늘 안 보기')]", By.XPATH),
            ("button.btn_close_today", By.CSS_SELECTOR),
            (".oyAlertPop .btnClose", By.CSS_SELECTOR),
            (".pop_cont .btn_close", By.CSS_SELECTOR),
        ]:
            click_if_present(driver, loc, by=by, timeout=2)

        # 목록 섹션 로딩 대기 후 지연로딩 대비 스크롤
        try:
            wait_css(driver, "ul.prd_list, ul.cate_prd_list")
        except:
            pass

        last_h = 0
        for _ in range(6):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
            h = driver.execute_script("return document.body.scrollHeight")
            if h == last_h:
                break
            last_h = h

        # 상세 앵커 수집: href 패턴 기반 (클래스 의존 X)
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

        product_links = hrefs[:48]  # 1페이지 48개

        if not product_links:
            print("상품 링크를 찾지 못했습니다. 셀렉터/XPATH를 재확인하세요.")
            print(driver.title)
            print(driver.current_url)
            return

        print(f"[INFO] 상품 링크 {len(product_links)}개 수집")

        for i, link in enumerate(product_links, 1):
            # 상세는 새 탭으로 열기 → 작업 후 탭만 닫기
            base_handle, detail_handle = open_in_new_tab(driver, link)

            # 혹시 중간 팝업/새창이 끼면 정리
            if len(driver.window_handles) > 2:
                extras = [h for h in driver.window_handles if h not in (base_handle, detail_handle)]
                for h in extras:
                    try:
                        driver.switch_to.window(h)
                        driver.close()
                    except:
                        pass
                driver.switch_to.window(detail_handle)

            # 상세 핵심 블록 대기 (미로딩 시 한 번 재시도)
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "div.prd_detail, .prd_detail_area, .prd_detail_box, .goods-detail, .prd_view")
                    )
                )
            except:
                if not safe_get(driver, link, tries=2):
                    print(f"[SKIP] 상세 진입 실패: {link}")
                    driver.close()
                    driver.switch_to.window(base_handle)
                    continue

            # 브랜드
            brand = get_text_safe(driver, ["p.prd_brand a", "p.prd_brand", ".brand_name a", ".brand_name"])
            # 상품명
            name = get_text_safe(driver, ["p.prd_name", "h2.prd_name", ".prd_info h2", "h2.goods_txt", "h1"])
            # 가격
            price = ""
            for sel in [
                # User's suggestion is prioritized. This looks for the text within any element with class 'price-2'.
                ".price-2",
                # Fallback selectors from the original list
                "span.price-1 span.num",
                ".total_price .num",
                ".price_info .num",
                ".sale_price .num",
                ".price .num",
            ]:
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

            # 옵션(호수) 열기
            opened = False
            for sel in [
                "div.prd_option_box a.select_btn",
                ".prd_option_box .select_btn",
                ".opt_select .select_btn",
                ".options .select_btn",
                "button.select_btn",
            ]:
                if click_if_present(driver, sel, by=By.CSS_SELECTOR, timeout=3):
                    time.sleep(0.2)
                    opened = True
                    break

            variants = []
            if opened:
                opts = []
                for sel in [
                    "div.prd_option_box ul.select_list li a",
                    "div.prd_option_box ul.select_list li button",
                    ".select_list li a",
                    ".select_list li button",
                    ".option_list li a",
                    ".option_list li button",
                ]:
                    opts = driver.find_elements(By.CSS_SELECTOR, sel)
                    if opts:
                        break

                for o in opts:
                    txt = (o.text or "").strip()
                    if not txt:
                        continue
                    code_name = txt.split("\n")[0].strip()
                    code_price = num_only(txt) or price
                    variants.append({"code_name": code_name, "code_price": code_price})

            if not variants:
                variants = [{"code_name": "단품", "code_price": price}]

            for v in variants:
                products_data.append(
                    {
                        "brand_name": brand,
                        "product_name": name,
                        "price": price,  # 기본가
                        "product_main_image": main_img,
                        "code_name": v["code_name"],
                        "code_price": v["code_price"],
                        "product_url": link,
                    }
                )

            print(f"[{i:02d}/{len(product_links)}] {name} - {len(variants)} variants")

            # 상세 탭만 닫고 메인 탭 복귀
            try:
                driver.close()
            except:
                pass
            try:
                driver.switch_to.window(base_handle)
            except:
                # 창 유실 시 복구 시도
                handles = driver.window_handles
                if handles:
                    driver.switch_to.window(handles[0])
            time.sleep(0.2)  # 과도한 요청 방지

    finally:
        try:
            driver.quit()
        except:
            pass
        with open("oliveyoung_lip_makeup.json", "w", encoding="utf-8") as f:
            json.dump(products_data, f, ensure_ascii=False, indent=2)
        print(f"{len(products_data)}건 저장 완료 -> oliveyoung_lip_makeup.json")

if __name__ == "__main__":
    crawl_olive_young()
