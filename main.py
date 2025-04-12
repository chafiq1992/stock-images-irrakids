import os
import re
import hashlib
import requests
import json
from fastapi import FastAPI, Request
from PIL import Image, ImageDraw, ImageFont
from requests.utils import parse_header_links
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import uvicorn

# Shopify credentials
API_KEY = os.getenv("SHOPIFY_API_KEY", "your_api_key")
PASSWORD = os.getenv("SHOPIFY_PASSWORD", "your_password")
STORE_URL = os.getenv("SHOPIFY_STORE_URL", "https://yourstore.myshopify.com")

# Google Drive folder ID to upload images to
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "your-folder-id")
SERVICE_ACCOUNT_FILE = os.getenv("GDRIVE_CREDENTIALS", "service_account.json")

# Local temporary directory for images
BASE_IMAGE_DIR = os.getenv("IRRAKIDS_IMAGE_DIR", "/tmp/irrakids-images")

app = FastAPI()

# Load Google Drive service
SCOPES = ['https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service = build('drive', 'v3', credentials=creds)

size_pattern = re.compile(r'\b(?:XS|S|M|L|XL|XXL|XXXL)\b|\d+')

# --- Utilities ---
def sanitize_directory_name(name):
    return re.sub(r'[<>:"/\\|?*]', '_', name)

def create_directory(path):
    if not os.path.exists(path):
        os.makedirs(path)

def add_price_to_image(image_path, price):
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
        img.save(image_path, "JPEG")
    except Exception as e:
        print(f"❌ Error adding price to image {image_path}: {e}")

def download_image_if_new(image_url, image_path):
    try:
        response = requests.get(image_url)
        image_data = response.content
        new_hash = hashlib.md5(image_data).hexdigest()
        if os.path.exists(image_path):
            with open(image_path, "rb") as f:
                existing_hash = hashlib.md5(f.read()).hexdigest()
            if existing_hash == new_hash:
                return False
        with open(image_path, "wb") as f:
            f.write(image_data)
        return True
    except:
        return False

def upload_to_drive(file_path, filename):
    try:
        file_metadata = {'name': filename, 'parents': [GOOGLE_DRIVE_FOLDER_ID]}
        media = MediaFileUpload(file_path, mimetype='image/jpeg')
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        print(f"☁️ Uploaded {filename} to Drive with ID {file.get('id')}")
    except Exception as e:
        print(f"⚠️ Upload failed for {filename}: {e}")

def process_product(product):
    product_tags = product.get("tags", "").lower()
    is_girls = "girls" in product_tags
    is_boys = "boys" in product_tags

    for variant in product.get("variants", []):
        variant_id = variant.get("id")
        image_id = variant.get("image_id")
        inventory = variant.get("inventory_quantity", 0)
        price = variant.get("price", "0")
        option_values = [variant.get('option1', ''), variant.get('option2', ''), variant.get('option3', '')]
        size_option = next((sanitize_directory_name(v) for v in option_values if size_pattern.search(v)), "default")

        size_dir = os.path.join(BASE_IMAGE_DIR, size_option)
        girls_dir = os.path.join(size_dir, "girls") if is_girls else None
        boys_dir = os.path.join(size_dir, "boys") if is_boys else None
        for folder in filter(None, [girls_dir, boys_dir]):
            create_directory(folder)

        image_name = f"{variant_id}.jpg"
        image_url = None
        for img in product.get("images", []):
            if img.get("id") == image_id:
                image_url = img.get("src")
                break

        if inventory > 0 and image_url:
            for folder in filter(None, [girls_dir, boys_dir]):
                image_path = os.path.join(folder, image_name)
                changed = download_image_if_new(image_url, image_path)
                if changed or not os.path.exists(image_path):
                    add_price_to_image(image_path, price)
                    upload_to_drive(image_path, f"{size_option}/{os.path.basename(folder)}/{image_name}")
                    print(f"✅ Updated variant {variant_id} at {image_path}")
        else:
            print(f"❌ Variant {variant_id} is out of stock or has no image.")

# --- Webhook ---
@app.post("/webhook")
async def webhook_listener(request: Request):
    payload = await request.json()
    print("🔔 Webhook received")
    if "products" in payload:
        for product in payload["products"]:
            process_product(product)
    elif "id" in payload:
        process_product(payload)
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
