import requests
import os

def test_final_upload():
    pk = "private_hbJQmvF1AwsXXfYT7T6VvFlTtPU="
    dummy_img = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    
    print("Testing Binary Upload...")
    try:
        ik_response = requests.post(
            "https://upload.imagekit.io/api/v1/files/upload",
            auth=(pk, ""),
            files={
                "file": ("test.png", dummy_img, "image/png"),
                "fileName": (None, "test.png"),
                "useUniqueFileName": (None, "true")
            }
        )
        print(f"Status: {ik_response.status_code}")
        print(f"Response: {ik_response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_final_upload()
