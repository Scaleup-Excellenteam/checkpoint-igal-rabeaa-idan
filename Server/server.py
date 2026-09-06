from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

app = FastAPI()

class LoginRequest(BaseModel):
    username: str
    password: str

FAKE_USERS_DB = {
    "idan": "idan123",
    "user": "user123",
    "admin": "admin123"
}

class UserSignup(BaseModel):
    username: str
    password: str

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.post("/login", status_code=status.HTTP_200_OK)
async def login(credentials: LoginRequest):
    stored_password = FAKE_USERS_DB.get(credentials.username)
    if not stored_password or stored_password != credentials.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
    return {
        "status": "success",
        "message": f"Welcome back, {credentials.username}!"
    }

@app.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(user: UserSignup):
    if user.username in FAKE_USERS_DB:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    FAKE_USERS_DB[user.username] = user.password
    return {
        "message": f"User '{user.username}' created successfully!"
    }