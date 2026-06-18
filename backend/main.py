import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

from auth import create_access_token, get_current_user
from database import close_db, init_db
from gemini_client import GeminiClient
from models import ChatMessage, Conversation, User, validate_password_strength

gemini_client = GeminiClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(title="AI Study Planner API", lifespan=lifespan)

frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin, "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Request / response schemas ----


class AuthRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    success: bool = True
    username: str
    token: str


class MeResponse(BaseModel):
    authenticated: bool = True
    username: str
    id: str


class ConversationCreate(BaseModel):
    title: str = "New chat"


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


# ---- Auth routes ----


@app.post("/api/auth/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: AuthRequest):
    username = payload.username.strip()
    password = payload.password

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")
    if len(username) < 2:
        raise HTTPException(status_code=400, detail="Username must be at least 2 characters")

    ok, err = validate_password_strength(password)
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    existing = await User.find_one(User.username == username)
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")

    user = User(username=username)
    user.set_password(password)
    await user.insert()

    token = create_access_token(str(user.id))
    return AuthResponse(username=user.username, token=token)


@app.post("/api/auth/login", response_model=AuthResponse)
async def login(payload: AuthRequest):
    username = payload.username.strip()
    password = payload.password

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    user = await User.find_one(User.username == username)
    if not user or not user.check_password(password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(str(user.id))
    return AuthResponse(username=user.username, token=token)


@app.get("/api/me", response_model=MeResponse)
async def me(current_user: User = Depends(get_current_user)):
    return MeResponse(username=current_user.username, id=str(current_user.id))


# ---- Conversations ----


@app.get("/api/conversations")
async def list_conversations(current_user: User = Depends(get_current_user)):
    convos = (
        await Conversation.find(Conversation.user_id == str(current_user.id))
        .sort(-Conversation.updated_at)
        .to_list()
    )
    return {"conversations": [c.to_dict() for c in convos]}


@app.post("/api/conversations", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
):
    title = (payload.title or "New chat").strip() or "New chat"
    conv = Conversation(user_id=str(current_user.id), title=title)
    await conv.insert()
    return conv.to_dict()


# ---- Chat ----


@app.get("/api/chat/history")
async def chat_history(
    conversation_id: str = Query(...),
    limit: int = Query(500, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
):
    conv = await Conversation.get(conversation_id)
    if not conv or conv.user_id != str(current_user.id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = (
        await ChatMessage.find(
            ChatMessage.user_id == str(current_user.id),
            ChatMessage.conversation_id == conversation_id,
        )
        .sort(+ChatMessage.created_at)
        .limit(limit)
        .to_list()
    )
    return {"messages": [m.to_dict() for m in messages]}


@app.post("/api/chat")
async def chat(payload: ChatRequest, current_user: User = Depends(get_current_user)):
    user_message = (payload.message or "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="No message provided")

    conv: Conversation | None = None
    if payload.conversation_id:
        conv = await Conversation.get(payload.conversation_id)
        if not conv or conv.user_id != str(current_user.id):
            raise HTTPException(status_code=404, detail="Conversation not found")

    if conv is None:
        conv = Conversation(user_id=str(current_user.id), title="New chat")
        await conv.insert()

    conv_id = str(conv.id)

    try:
        recent = (
            await ChatMessage.find(ChatMessage.conversation_id == conv_id)
            .sort(-ChatMessage.created_at)
            .limit(50)
            .to_list()
        )
        history = [(m.role, m.content) for m in reversed(recent)]
        response_text = gemini_client.generate_response(user_message, history=history)

        user_msg = ChatMessage(
            user_id=str(current_user.id),
            conversation_id=conv_id,
            role="user",
            content=user_message,
        )
        assistant_msg = ChatMessage(
            user_id=str(current_user.id),
            conversation_id=conv_id,
            role="assistant",
            content=response_text,
        )
        await user_msg.insert()
        await assistant_msg.insert()

        if conv.title == "New chat":
            conv.title = (user_message[:50] + "…") if len(user_message) > 50 else user_message
        conv.updated_at = datetime.utcnow()
        await conv.save()

        return {"response": response_text, "conversation_id": conv_id}
    except Exception:
        raise HTTPException(status_code=500, detail="Error generating response")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
