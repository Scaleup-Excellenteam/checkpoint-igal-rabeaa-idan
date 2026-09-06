import httpx

response = httpx.get("http://127.0.0.1:8000")
data = response.json()
print("Message:", data["message"])
print("Page Content Loaded Successfully!")
