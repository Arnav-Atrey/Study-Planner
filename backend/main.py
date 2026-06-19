import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

from auth import create_access_token, get_current_user, get_user_from_token
from database import close_db, init_db
from gemini_client import GeminiClient
from models import ChatMessage, Conversation, User, validate_password_strength
from voice_agent import VoiceSession

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


# ---- Voice (Gemini Live) ----


@app.websocket("/ws/voice")
async def voice_ws(
    websocket: WebSocket,
    token: str = Query(...),
    conversation_id: Optional[str] = Query(None),
):
    """Real-time voice assistant over WebSocket.

    Client -> server binary frames: raw 16kHz PCM16 mic audio.
    Client -> server text frame "stop": end the session cleanly.

    Server -> client binary frames: raw 24kHz PCM16 audio to play back.
    Server -> client JSON frames: {"type": "input_transcript"|"output_transcript"
        |"turn_complete"|"interrupted"|"error"|"ready", ...}
    """
    user = await get_user_from_token(token)
    if user is None:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        await websocket.close(code=1011, reason="Voice service not configured")
        return

    await websocket.accept()

    conv: Optional[Conversation] = None
    if conversation_id:
        conv = await Conversation.get(conversation_id)
        if not conv or conv.user_id != str(user.id):
            conv = None
    if conv is None:
        conv = Conversation(user_id=str(user.id), title="Voice chat")
        await conv.insert()
    conv_id = str(conv.id)

    await websocket.send_json({"type": "ready", "conversation_id": conv_id})

    session = VoiceSession(api_key=api_key)

    # Buffers for the transcript text of the turn currently in progress.
    # Gemini streams transcription incrementally; we accumulate and only
    # persist to Mongo once a turn completes.
    input_buffer = {"text": ""}
    output_buffer = {"text": ""}

    async def persist_turn() -> None:
        user_text = input_buffer["text"].strip()
        assistant_text = output_buffer["text"].strip()
        input_buffer["text"] = ""
        output_buffer["text"] = ""

        if not user_text and not assistant_text:
            return

        if user_text:
            await ChatMessage(
                user_id=str(user.id),
                conversation_id=conv_id,
                role="user",
                content=user_text,
            ).insert()
        if assistant_text:
            await ChatMessage(
                user_id=str(user.id),
                conversation_id=conv_id,
                role="assistant",
                content=assistant_text,
            ).insert()

        if conv.title in ("New chat", "Voice chat") and user_text:
            conv.title = (user_text[:50] + "…") if len(user_text) > 50 else user_text
        conv.updated_at = datetime.utcnow()
        await conv.save()

    async def on_audio_chunk(chunk: bytes) -> None:
        await websocket.send_bytes(chunk)

    async def on_input_transcript(text: str) -> None:
        input_buffer["text"] += text
        await websocket.send_json({"type": "input_transcript", "text": text})

    async def on_output_transcript(text: str) -> None:
        output_buffer["text"] += text
        await websocket.send_json({"type": "output_transcript", "text": text})

    async def on_turn_complete() -> None:
        await websocket.send_json({"type": "turn_complete"})
        await persist_turn()

    async def on_interrupted() -> None:
        await websocket.send_json({"type": "interrupted"})

    async def receive_loop() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                session.stop()
                return
            if "bytes" in message and message["bytes"] is not None:
                session.push_audio(message["bytes"])
            elif "text" in message and message["text"] is not None:
                if message["text"] == "stop":
                    session.stop()
                    return

    try:
        recv_task_handle = asyncio.create_task(receive_loop())
        run_task_handle = asyncio.create_task(
            session.run(
                on_audio_chunk=on_audio_chunk,
                on_input_transcript=on_input_transcript,
                on_output_transcript=on_output_transcript,
                on_turn_complete=on_turn_complete,
                on_interrupted=on_interrupted,
            )
        )

        done, pending = await asyncio.wait(
            {recv_task_handle, run_task_handle},
            return_when=asyncio.FIRST_COMPLETED,
        )
        session.stop()
        for task in pending:
            task.cancel()
        for task in done:
            if not task.cancelled() and task.exception():
                raise task.exception()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        await persist_turn()
        try:
            await websocket.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)