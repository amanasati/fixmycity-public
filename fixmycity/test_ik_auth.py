import base64
from imagekitio import ImageKit

# Use the exact keys from app.py
IMAGEKIT_PUBLIC_KEY = "public_ruMYJkoKgxzzt+0QEoVxh5UkKgc="
IMAGEKIT_URL_ENDPOINT = "https://ik.imagekit.io/iw7nsdrvo"
PRIVATE_KEY = "private_hbJQmvF1AwsXXfYT7T6VvFlTtPU="

ik = ImageKit(private_key=PRIVATE_KEY)

try:
    print("Testing ImageKit auth...")
    # Just list 1 file to see if it works
    files = ik.files.list(limit=1)
    print("✅ Auth successful!")
    print(f"Files: {files}")
except Exception as e:
    print(f"❌ Auth failed: {e}")
