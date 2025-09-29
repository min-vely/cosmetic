# file: image_merger.py
from PIL import Image
import requests
from io import BytesIO
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# preprocessing.py에서 클래스 임포트
from preprocessing import OliveYoungPreprocessor

class ImageMerger:
    def __init__(self, image_urls, brand_name, product_name, code_name):
        """
        :param image_urls: 합치고자 하는 이미지 URL 리스트
        :param brand_name: 브랜드명
        :param product_name: 제품명
        :param code_name: 저장할 파일명 기반 문자열
        """
        self.image_urls = image_urls
        self.brand_name = brand_name
        self.product_name = product_name
        self.code_name = code_name
        self.images = []

    def download_images(self, max_workers=8):
        """멀티스레딩으로 이미지 다운로드 및 RGBA 변환, 순서 유지"""
        self.images = [None] * len(self.image_urls)  # 순서 유지용 리스트

        def fetch(index, url):
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                return index, Image.open(BytesIO(response.content)).convert("RGBA")
            except Exception as e:
                print(f"이미지 다운로드 실패: {url} ({e})")
                return index, None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(fetch, i, url) for i, url in enumerate(self.image_urls)]
            for future in as_completed(futures):
                index, img = future.result()
                if img:
                    self.images[index] = img

        # None 제거
        self.images = [img for img in self.images if img is not None]

        if not self.images:
            print("다운로드된 이미지가 없습니다.")

    @staticmethod
    def sanitize_filename(name):
        """파일명에 사용할 수 없는 문자 제거"""
        sanitized = re.sub(r'[<>:"/\\|?*\n\r\t]', '', name)
        return sanitized.strip()

    def merge_vertical(self, save_dir="data/images/merged"):
        """이미지들을 세로로 합치기 (가장 긴 가로 기준, 가운데 정렬, 남는 공간 흰색)"""
        if not self.images:
            print("이미지가 없습니다. download_images() 먼저 실행하세요.")
            return

        os.makedirs(save_dir, exist_ok=True)

        max_width = max(img.width for img in self.images)
        total_height = sum(img.height for img in self.images)

        merged_image = Image.new("RGB", (max_width, total_height), (255, 255, 255))

        y_offset = 0
        for img in self.images:
            img_rgb = img.convert("RGB")
            x_offset = (max_width - img.width) // 2  # 가로 가운데 정렬
            merged_image.paste(img_rgb, (x_offset, y_offset))
            y_offset += img.height

        # 파일명 처리: brand_name + product_name + code_name
        clean_product_name = OliveYoungPreprocessor.clean_product_name(self.product_name)
        clean_code_name = OliveYoungPreprocessor.clean_code_name(self.code_name)
        file_name = f"{self.brand_name}_{clean_product_name}_{clean_code_name}"
        safe_name = self.sanitize_filename(file_name)

        save_path = os.path.join(save_dir, f"{safe_name}.png")
        merged_image.save(save_path)
        print(f"이미지 저장 완료: {save_path}")
        return save_path, merged_image


if __name__ == "__main__":
    # 테스트용 예시
    import json

    json_data = [
        {
            "brand_name": "헤라",
            "product_name": "[9월 올영픽] 헤라 센슈얼 누드 글로스 5g",
            "code_name": "[립컨실러+립트리트먼트 기획]란제리\n36,000원",
            "product_images": [
                "https://image.oliveyoung.co.kr/uploads/images/display/9000003/19/2626588043041346216.jpg",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop0/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/29/442_29105213.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop1/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/29/442_29105213.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop2/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/29/442_29105213.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop0/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/cde_27153736.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop1/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/cde_27153736.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop2/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/cde_27153736.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop0/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/be1_27153754.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop1/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/be1_27153754.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop2/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/be1_27153754.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop0/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/ee1_27153841.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop1/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/ee1_27153841.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop2/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/ee1_27153841.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop3/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/ee1_27153841.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop0/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/dde_27153850.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop1/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/dde_27153850.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop2/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/dde_27153850.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop0/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/de5_27153858.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop1/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/de5_27153858.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop2/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/de5_27153858.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop0/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/bb6_27153903.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop1/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/bb6_27153903.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop0/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/488_27153908.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop1/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/488_27153908.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop2/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/488_27153908.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop3/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/488_27153908.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop4/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/488_27153908.jpg?created=202509220737",
                "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/crop/A000000177984/202509220737/crop5/image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/html/attached/2025/08/27/488_27153908.jpg?created=202509220737"
            ]
        }
    ]

    data = json_data[0]
    merger = ImageMerger(
        data["product_images"],
        data["brand_name"],
        data["product_name"],
        data["code_name"]
    )
    merger.download_images()

    # 시간 측정
    start_time = time.time()
    merger.merge_vertical()
    end_time = time.time()
    print(f"이미지 세로 합치기 소요 시간: {end_time - start_time:.3f}초")
