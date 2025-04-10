import os
import re
import hashlib
import requests
from PIL import Image, ImageDraw, ImageFont
import boto3
from botocore.exceptions import ClientError
from io import BytesIO

# Shopify credentials (for optional lookups)
API_KEY = 'your_api_key'
PASSWORD = 'your_password'
STORE_URL = 'https://your-store.myshopify.com'

# R2 CONFIG
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")  # e.g. "https://<account>.r2.cloudflarestorage.com"

# Regex pattern to identify sizes
size_pattern = re.compile(r'\b(?:XS|S|M|L|XL|XXL|XXXL)\b|\d+')

# S3/R2 client
s3 = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY
)

def upload_image_to_r2(image: Image.Image, key: str):
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    buffer.seek(0)

    try:
        s3.upload_fileobj(
            buffer,
            R2_BUCKET,
            key,
            ExtraArgs={'ContentType': 'image/jpeg', 'ACL': 'public-read'}
        )
        return f"{R2_ENDPOINT}/{R2_BUCKET}/{key}"  # Public image URL
    except ClientError as e:
        print(f"❌ Upload failed: {e}")
        return None

# Utilities
def sanitize_directory_name(name):
    return re.sub(r'[<>:"/\\|?*]', '_', name)

def create_directory(path):
    if not os.path.exists(path):
        os.makedirs(path)

def add_price_to_image(image_path, price, size_option, folder_name, variant_id):
    try:
        img = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except IOError:
            font = ImageFont.load_default()

        price_text = f"{int(float(price))} DH"
        bbox = draw.textbbox((0, 0), price_text, font=font)
        text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x, y = img.width - text_width - 20, img.height - text_height - 20
        draw.rectangle([x - 10, y - 10, x + text_width + 10, y + text_height + 10], fill="#004AAD")
        draw.text((x, y), price_text, font=font, fill="white")

        # Upload to R2
        key = f"{size_option}/{folder_name}/{variant_id}.jpg"
        url = upload_image_to_r2(img, key)
        print(f"✅ Uploaded to {url}")

        # Optional: remove local file
        if os.path.exists(image_path):
            os.remove(image_path)
    except Exception as e:
        print(f"⚠️ Error processing image {image_path}: {e}")

def download_image_if_new(image_url, image_path):
    try:
        response = requests.get(image_url)
        if response.status_code != 200:
            print(f"❌ Failed to fetch image: {image_url}")
            return False
        image_data = response.content
        new_hash = hashlib.md5(image_data).hexdigest()
        if os.path.exists(image_path):
            with open(image_path, "rb") as f:
                existing_hash = hashlib.md5(f.read()).hexdigest()
            if existing_hash == new_hash:
                return False  # No change
        with open(image_path, "wb") as f:
            f.write(image_data)
        return True
    except Exception as e:
        print(f"⚠️ Error downloading image: {e}")
        return False

def handle_variant_update(payload):
    for product in payload.get("products", [payload]):  # support both batch and single
        product_tags = product.get("tags", "").lower()
        is_girls = "girls" in product_tags
        is_boys = "boys" in product_tags

        for variant in product.get("variants", []):
            variant_id = variant.get("id")
            image_id = variant.get("image_id")
            inventory = variant.get("inventory_quantity", 0)
            price = variant.get("price", "0")
            option_values = [
                variant.get('option1', ''),
                variant.get('option2', ''),
                variant.get('option3', '')
            ]
            size_option = next((sanitize_directory_name(v) for v in option_values if size_pattern.search(v)), "default")

            size_directory = os.path.join(os.getcwd(), size_option)
            girls_directory = os.path.join(size_directory, "girls") if is_girls else None
            boys_directory = os.path.join(size_directory, "boys") if is_boys else None
            for folder in [girls_directory, boys_directory]:
                if folder:
                    create_directory(folder)

            image_file_name = f"{variant_id}.jpg"
            image_url = None

            for image in product.get("images", []):
                if image["id"] == image_id:
                    image_url = image["src"]
                    break

            if inventory > 0 and image_url:
                for folder in filter(None, [girls_directory, boys_directory]):
                    image_path = os.path.join(folder, image_file_name)
                    changed = download_image_if_new(image_url, image_path)
                    if changed:
                        folder_name = "girls" if folder.endswith("girls") else "boys"
                        add_price_to_image(image_path, price, size_option, folder_name, variant_id)
                        print(f"✅ Updated image for variant {variant_id} at {image_path}")
            else:
                for folder in filter(None, [girls_directory, boys_directory]):
                    image_path = os.path.join(folder, image_file_name)
                    if os.path.exists(image_path):
                        os.remove(image_path)
                        print(f"❌ Deleted image for out-of-stock variant {variant_id} from {image_path}")
