

import json
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

def crawl_olive_young():
    chrome_options = Options()
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    url = "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100020006"
    driver.get(url)
    
    print("페이지가 로드되었습니다. 크롤링을 시작합니다.")

    products_data = []
    
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "ul.prd_list.large-list a.prd_info"))
        )
        
        product_links = [elem.get_attribute('href') for elem in driver.find_elements(By.CSS_SELECTOR, "ul.prd_list.large-list a.prd_info")]
        
        for link in product_links:
            driver.get(link)
            
            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "p.prd_brand"))
                )
                
                brand_name = driver.find_element(By.CSS_SELECTOR, "p.prd_brand a").text
                product_name = driver.find_element(By.CSS_SELECTOR, "p.prd_name").text
                
                try:
                    price = driver.find_element(By.CSS_SELECTOR, "span.price-2 span.num").text
                except:
                    price = driver.find_element(By.CSS_SELECTOR, "span.price-1 span.num").text

                main_image_url = driver.find_element(By.CSS_SELECTOR, "div.prd_thumb img").get_attribute('src')

                try:
                    dropdown = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "div.prd_option_box a.select_btn"))
                    )
                    dropdown.click()
                    
                    options = WebDriverWait(driver, 10).until(
                        EC.visibility_of_all_elements_located((By.CSS_SELECTOR, "div.prd_option_box ul.select_list li a"))
                    )
                    
                    for option in options:
                        option_text = option.text
                        code_name = option_text.split('\n')[0]
                        code_price = price

                        product_info = {
                            "brand_name": brand_name,
                            "product_name": product_name,
                            "price": price,
                            "product_main_image": main_image_url,
                            "code_name": code_name,
                            "code_price": code_price
                        }
                        products_data.append(product_info)

                except Exception as e:
                    product_info = {
                        "brand_name": brand_name,
                        "product_name": product_name,
                        "price": price,
                        "product_main_image": main_image_url,
                        "code_name": "단품",
                        "code_price": price
                    }
                    products_data.append(product_info)
                    # print(f"No options for {product_name} or error: {e}")

            except Exception as e:
                print(f"Could not process product link {link}. Error: {e}")

    finally:
        driver.quit()
        with open('oliveyoung_lip_makeup.json', 'w', encoding='utf-8') as f:
            json.dump(products_data, f, ensure_ascii=False, indent=4)
        print("크롤링이 완료되어 'oliveyoung_lip_makeup.json' 파일에 저장했습니다.")

if __name__ == "__main__":
    crawl_olive_young()
