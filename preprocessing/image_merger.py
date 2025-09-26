import requests
from PIL import Image
from io import BytesIO
import base64

class ImageMerger:
    def __init__(self, image_urls):
        """
        image_urls: 크롤러에서 수집한 상세페이지 이미지 URL 리스트
        """
        self.image_urls = image_urls

    def download_images(self):
        images = []
        for url in self.image_urls:
            try:
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                img = Image.open(BytesIO(resp.content)).convert("RGB")
                images.append(img)
            except Exception as e:
                print(f"[IMAGE DOWNLOAD FAIL] {url} -> {e}")
        return images

    def merge_images(self, images):
        if not images:
            return None

        # 가장 큰 가로 폭 찾기
        max_width = max(img.width for img in images)
        resized_images = []

        for img in images:
            if img.width != max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.LANCZOS)
            resized_images.append(img)

        total_height = sum(img.height for img in resized_images)
        merged_img = Image.new("RGB", (max_width, total_height), (255, 255, 255))

        y_offset = 0
        for img in resized_images:
            merged_img.paste(img, (0, y_offset))
            y_offset += img.height

        return merged_img

    def merge_and_encode(self):
        images = self.download_images()
        merged_img = self.merge_images(images)
        if merged_img is None:
            return None

        buffered = BytesIO()
        merged_img.save(buffered, format="JPEG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return img_base64
