print("Testing basic Python")
try:
    from flask import Flask
    print("Flask imported successfully")
except ImportError as e:
    print(f"Flask import error: {e}")

try:
    import requests
    print("Requests imported successfully")
except ImportError as e:
    print(f"Requests import error: {e}")

try:
    from authlib.integrations.flask_client import OAuth
    print("Authlib imported successfully")
except ImportError as e:
    print(f"Authlib import error: {e}")