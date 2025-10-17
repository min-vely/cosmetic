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

CATEGORY_URL = "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=1000001000200010009&rowsPerPage=48"
PRODUCT_URLS = []
MAX_REVIEWS_PER_OPTION = 10

# ---------------- 유틸 함수 ----------------
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
    if not s: return ""
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

# ---------------- 팝업 원천 차단 + 즉시 제거 ----------------
def inject_popup_killer(driver):
    """
    옵션 클릭/더보기 시 뜨는 '큐레이션/추천상품' 레이어를 최대한 예방 + 즉시 제거.
    - curation.popClose() 호출, 닫기 버튼(.layer_close.type4) 클릭, recoGoodsYn=N
    - 딤(.dim/.dimmed 등) 클릭 + 숨김
    - 네트워크 요청 차단(추천/curation 관련), 스크롤 락 해제
    """
    js = r"""
    (function(){
      try {
        // 0) 추천 팝업 여는 전역 함수가 있으면 무력화
        try {
          if (window.curation) {
            ['popOpen','open','openRecommend','show','showPop','recoOpen'].forEach(fn=>{
              try{ if (typeof window.curation[fn]==='function'){ window.curation[fn]=function(){}; } }catch(e){}
            });
          }
        } catch(e){}

        // 1) 추천/큐레이션 관련 네트워크 차단
        const BLOCK_PATTERNS = [/recommend/i, /recom/i, /curation/i, /popup/i, /gdasRecommend/i];
        const origFetch = window.fetch;
        window.fetch = function(input, init){
          try {
            const url = (typeof input === 'string') ? input : (input && input.url ? input.url : '');
            if (url && BLOCK_PATTERNS.some(p=>p.test(url))) {
              return Promise.resolve(new Response(JSON.stringify({}), {status: 204}));
            }
          } catch(e){}
          return origFetch.apply(this, arguments);
        };
        const origOpen = window.XMLHttpRequest && window.XMLHttpRequest.prototype.open;
        if (origOpen) {
          XMLHttpRequest.prototype.open = function(method, url){
            try { if (url && BLOCK_PATTERNS.some(p=>p.test(url))) { this.send = function(){}; } } catch(e){}
            return origOpen.apply(this, arguments);
          };
        }

        // 2) DOM 붙자마자 닫기/숨김
        const POPUP_SEL = [
          '.popup_layer','.ly_popup','.modal','.layer_pop',
          '.recommend-popup','.recommend_layer','.layer_recommend',
          '.prd_recommend','.prd-recommend','.curation','.curation_wrap',
          '.curation-area','#recomPop','[role="dialog"]','.layer_cont4.w900'
        ];
        const CLOSE_SEL = [
          '.btn_close','.popup_close','.ly_close','.modal-close','.btnClose','.btn_layer_close',
          'button.layer_close.type4','.oy-sp-gnb .btn-close',
          'button[aria-label="닫기"]','button[title="닫기"]',
          'button[class*="close"]','a[class*="close"]'
        ];
        const DIM_SEL = ['.dim','.dimmed','.overlay','.modal-backdrop','.oyDimmed'];

        function killScrollLock(){
          try {
            document.body.style.overflow = 'auto';
            document.documentElement.style.overflow = 'auto';
            document.body.classList.remove('no-scroll','fixed','overflow-hidden');
          } catch(e){}
        }

        function clickXTextual(el){
          try{
            const cand = el.querySelectorAll('button, a');
            for (const b of cand){
              const t = (b.innerText||'').trim();
              if (t === '×' || t === '✕') { b.click(); return true; }
            }
          }catch(e){}
          return false;
        }

        function directClose(){
          try{ if (window.curation && typeof curation.popClose==='function') curation.popClose(); }catch(e){}
          try{ var r=document.getElementById('recoGoodsYn'); if(r) r.value='N'; }catch(e){}
          try{ var b=document.querySelector('button.layer_close.type4'); if(b){ b.click(); } }catch(e){}
        }

        function hideOrRemove(node){
          try {
            if (!node || !node.querySelector) return false;
            let matched = false;

            directClose();

            for (const s of POPUP_SEL) {
              const el = node.matches && node.matches(s) ? node : node.querySelector(s);
              if (!el) continue;

              let closed = false;
              for (const cs of CLOSE_SEL) {
                const btn = el.querySelector(cs);
                if (btn && getComputedStyle(btn).display !== 'none' && getComputedStyle(btn).visibility !== 'hidden') {
                  btn.click(); closed = true; matched = true; break;
                }
              }
              if (!closed) { closed = clickXTextual(el); if (closed) matched = true; }

              if (!closed){
                el.style.setProperty('display','none','important');
                el.style.setProperty('visibility','hidden','important');
                el.style.setProperty('z-index','-1','important');
                matched = true;
              }
            }

            // 딤 클릭 + 숨김
            for (const ds of DIM_SEL){
              document.querySelectorAll(ds).forEach(d=>{
                try{ d.click(); }catch(e){}
                d.style.display='none'; d.style.visibility='hidden'; d.style.zIndex='-1';
              });
            }

            if (matched) killScrollLock();
            return matched;
          } catch(e){ return false; }
        }

        hideOrRemove(document);
        const mo = new MutationObserver(muts=>{
          for (const m of muts) { m.addedNodes && m.addedNodes.forEach(n=>hideOrRemove(n)); }
        });
        mo.observe(document.documentElement || document.body, {childList:true, subtree:true});
        setInterval(()=>hideOrRemove(document), 400);

        window.addEventListener('keydown', (e)=>{ if (e.key === 'Escape') hideOrRemove(document); }, true);
        window.open = function(){ return null; };
      } catch(e) {}
    })();
    """
    try:
        driver.execute_script(js)
    except Exception:
        pass

# ---------------- 강제 닫기 (Selenium 측) ----------------
def close_interfering_popup_strong(driver, max_attempts=2):
    popup_selectors = [
        ".popup_layer",".ly_popup",".modal",".layer_pop",
        ".recommend-popup",".recommend_layer",".layer_recommend",
        ".prd_recommend",".prd-recommend",".curation",".curation_wrap",
        ".curation-area","#recomPop","[role='dialog']", ".layer_cont4.w900"
    ]
    close_btn_selectors = [
        ".btn_close",".popup_close",".ly_close",".modal-close",".btnClose",".btn_layer_close",
        "button.layer_close.type4",".oy-sp-gnb .btn-close",
        "button[aria-label='닫기']","button[title='닫기']",
        "button[class*='close']","a[class*='close']"
    ]
    dim_selectors = [".dim",".dimmed",".overlay",".modal-backdrop",".oyDimmed"]

    def _kill_scroll_lock():
        try:
            driver.execute_script("""
                document.body.style.overflow='auto';
                document.documentElement.style.overflow='auto';
                document.body.classList.remove('no-scroll','fixed','overflow-hidden');
            """)
        except: pass

    def _direct_close_js():
        try:
            driver.execute_script("""
              try{ if (window.curation && typeof curation.popClose==='function') curation.popClose(); }catch(e){}
              try{ var r=document.getElementById('recoGoodsYn'); if(r) r.value='N'; }catch(e){}
              try{ var b=document.querySelector('button.layer_close.type4'); if(b){ b.click(); } }catch(e){}
            """)
        except: pass

    for _ in range(max_attempts):
        closed = False

        # ESC
        try:
            driver.switch_to.default_content()
            driver.execute_script("document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape'}));")
        except: pass

        _direct_close_js()

        # 일반 팝업
        for sel in popup_selectors:
            try:
                for p in driver.find_elements(By.CSS_SELECTOR, sel):
                    if not p.is_displayed(): continue
                    btn_clicked = False
                    for bsel in close_btn_selectors:
                        try:
                            for btn in p.find_elements(By.CSS_SELECTOR, bsel):
                                if btn.is_displayed():
                                    driver.execute_script("arguments[0].click();", btn)
                                    time.sleep(0.02)
                                    btn_clicked = True; closed = True; break
                        except: continue
                        if btn_clicked: break
                    if not btn_clicked:
                        try:
                            driver.execute_script(
                                "arguments[0].style.display='none';"
                                "arguments[0].style.visibility='hidden';"
                                "arguments[0].style.zIndex='-1';", p)
                            closed = True
                        except: pass
            except: pass

        # iframe 내부
        try:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for f in iframes:
                try:
                    driver.switch_to.frame(f)
                    _direct_close_js()
                    for sel in popup_selectors:
                        try:
                            for p in driver.find_elements(By.CSS_SELECTOR, sel):
                                if not p.is_displayed(): continue
                                btn_clicked = False
                                for bsel in close_btn_selectors:
                                    try:
                                        for btn in p.find_elements(By.CSS_SELECTOR, bsel):
                                            if btn.is_displayed():
                                                driver.execute_script("arguments[0].click();", btn)
                                                time.sleep(0.02)
                                                btn_clicked = True; closed = True; break
                                    except: continue
                                    if btn_clicked: break
                                if not btn_clicked:
                                    try:
                                        driver.execute_script(
                                            "arguments[0].style.display='none';"
                                            "arguments[0].style.visibility='hidden';"
                                            "arguments[0].style.zIndex='-1';", p)
                                        closed = True
                                    except: pass
                        except: pass
                except: pass
                finally:
                    try: driver.switch_to.default_content()
                    except: pass
        except: pass

        # 딤 클릭 + 숨김
        try:
            for ds in dim_selectors:
                for d in driver.find_elements(By.CSS_SELECTOR, ds):
                    try: driver.execute_script("arguments[0].click();", d)
                    except: pass
                    try:
                        driver.execute_script(
                            "arguments[0].style.display='none';"
                            "arguments[0].style.visibility='hidden';"
                            "arguments[0].style.zIndex='-1';", d)
                        closed = True
                    except: pass
        except: pass

        _kill_scroll_lock()
        if not closed: break
        time.sleep(0.05)

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

            # 클릭 직후 초고속 스윕
            driver.execute_script("document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape'}));")
            close_interfering_popup_strong(driver, max_attempts=1)
            driver.execute_script("""
              try{ if (window.curation && typeof curation.popClose==='function') curation.popClose(); }catch(e){}
              try{ var r=document.getElementById('recoGoodsYn'); if(r) r.value='N'; }catch(e){}
              try{ var b=document.querySelector('button.layer_close.type4'); if(b){ b.click(); } }catch(e){}
              document.querySelectorAll('.dim,.dimmed,.overlay,.modal-backdrop,.oyDimmed').forEach(d=>{try{d.click()}catch(e){} d.style.display='none'; d.style.visibility='hidden'; d.style.zIndex='-1';});
            """)
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
                    # 클릭 직후 초고속 스윕
                    driver.execute_script("document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape'}));")
                    close_interfering_popup_strong(driver, max_attempts=1)
                    driver.execute_script("""
                      try{ if (window.curation && typeof curation.popClose==='function') curation.popClose(); }catch(e){}
                      try{ var r=document.getElementById('recoGoodsYn'); if(r) r.value='N'; }catch(e){}
                      try{ var b=document.querySelector('button.layer_close.type4'); if(b){ b.click(); } }catch(e){}
                      document.querySelectorAll('.dim,.dimmed,.overlay,.modal-backdrop,.oyDimmed').forEach(d=>{try{d.click()}catch(e){} d.style.display='none'; d.style.visibility='hidden'; d.style.zIndex='-1';});
                    """)
                    time.sleep(0.1)
            except: pass

            opt_txt, body_txt = extract_option_and_body(it)
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
    try:
        t = opt_radio.find_element(By.XPATH, "following-sibling::*[contains(@class,'txt') or contains(@class,'text') or contains(@class,'name')]").text.strip()
        if t: return t
    except: pass
    try:
        t = opt_radio.find_element(By.XPATH, "ancestor::label[1]").text.strip()
        if t: return t
    except: pass
    for attr in ["aria-label", "title", "value", "data-name", "data-label", "data-opt-nm", "data-opt-name"]:
        try:
            v = (opt_radio.get_attribute(attr) or "").strip()
            if v: return v
        except: pass
    try:
        _id = opt_radio.get_attribute("id")
        if _id:
            t = driver.find_element(By.CSS_SELECTOR, f"label[for='{_id}']").text.strip()
            if t: return t
    except: pass
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

    try:
        dropdown_btn = driver.find_element(By.CSS_SELECTOR, ".sel_option.item.all")
        driver.execute_script("arguments[0].click();", dropdown_btn)
        time.sleep(0.25)
    except:
        pass

    try:
        radio_options = driver.find_elements(By.CSS_SELECTOR, ".opt-radio")
    except:
        radio_options = []

    if not radio_options:
        option_recs.append(("단품", collect_review_texts_for_option(driver, "단품", limit=max_reviews)))
        return option_recs

    for opt_radio in radio_options:
        try:
            li_parent = opt_radio.find_element(By.XPATH, "ancestor::li[1]")
            li_class = li_parent.get_attribute("class") or ""
            if "off" in li_class.lower():
                continue

            review_name = get_radio_label_strong(driver, opt_radio).strip()
            if review_name == "전체":
                continue

            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", opt_radio)
            time.sleep(0.05)
            driver.execute_script("arguments[0].click();", opt_radio)

            # 클릭 직후 초고속 스윕
            driver.execute_script("document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape'}));")
            close_interfering_popup_strong(driver, max_attempts=1)
            driver.execute_script("""
              try{ if (window.curation && typeof curation.popClose==='function') curation.popClose(); }catch(e){}
              try{ var r=document.getElementById('recoGoodsYn'); if(r) r.value='N'; }catch(e){}
              try{ var b=document.querySelector('button.layer_close.type4'); if(b){ b.click(); } }catch(e){}
              document.querySelectorAll('.dim,.dimmed,.overlay,.modal-backdrop,.oyDimmed').forEach(d=>{try{d.click()}catch(e){} d.style.display='none'; d.style.visibility='hidden'; d.style.zIndex='-1';});
            """)
            time.sleep(0.2)

            WebDriverWait(driver, 7).until(lambda d: len(find_review_items(d)) > 0)
            time.sleep(0.35)

            if not review_name:
                review_name = get_radio_label_strong(driver, opt_radio).strip()
            if not review_name:
                items = find_review_items(driver)
                if items:
                    opt_txt, _ = extract_option_and_body(items[0])
                    if opt_txt.strip():
                        review_name = opt_txt.strip()
            if not review_name:
                review_name = "미상옵션"

            texts = collect_review_texts_for_option(driver, review_name, limit=max_reviews)
            option_recs.append((review_name, texts))

        except Exception as e:
            print(f"Error processing option: {e}")
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

    # ★ 드라이버 생성 직후 주입
    inject_popup_killer(driver)

    OUTPUT_DIR = os.path.join(BASE_DIR, "..", "data")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    OUT_PATH_RAW = os.path.join(OUTPUT_DIR, "oliveyoung_cushion_reviews_raw.json")
    OUT_PATH_PRE = os.path.join(OUTPUT_DIR, "oliveyoung_cushion_reviews_preprocessed.json")

    products = []
    try:
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
            if not href: continue
            m = re.search(r"goodsNo=(\w+)", href)
            if not m: continue
            goods_no = m.group(1)
            clean_url = f"https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo={goods_no}"
            if clean_url not in seen:
                seen.add(clean_url)
                PRODUCT_URLS.append(clean_url)

        PRODUCT_URLS = PRODUCT_URLS[:48]
        print(f"[INFO] {len(PRODUCT_URLS)}개 상품 링크 수집 완료")

        for idx, url in enumerate(PRODUCT_URLS, 1):
            driver.get(url)
            time.sleep(1)

            # 진입 직후 혹시 레이어 뜨면 정리
            close_interfering_popup_strong(driver, max_attempts=1)

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
        try:
            del driver
        except: pass

    with open(OUT_PATH_RAW, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    print(f"{len(products)}건 저장 완료 -> {OUT_PATH_RAW}")

    processor = OliveYoungPreprocessor(input_path=OUT_PATH_RAW, output_path=OUT_PATH_PRE)
    processor.load_json()
    processor.preprocess()
    processor.save_json()
    print(f"{len(processor.products)}건 전처리 후 저장 완료 -> {OUT_PATH_PRE}")

if __name__ == "__main__":
    t0 = time.time()
    crawl_oliveyoung_reviews_and_preprocess()
    print(f"[TIME] {time.time()-t0:.2f}s")