"""Gemini Live session management for the real-time voice assistant.

This module bridges a browser WebSocket (raw 16kHz PCM in, 24kHz PCM out)
with a Gemini Live session. It mirrors the structure of a local
sounddevice-based script, but every audio queue is fed by / drained into
the browser's WebSocket instead of a physical mic/speaker.

One VoiceSession is created per browser WebSocket connection and torn down
when the socket closes.
"""
import asyncio
import os
from typing import Awaitable, Callable, Optional

from google import genai
from google.genai import types as genai_types

from gemini_client import perform_web_search

MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")
INPUT_SAMPLE_RATE = 16_000
OUTPUT_SAMPLE_RATE = 24_000

SYSTEM_INSTRUCTIONS = """You are a helpful, encouraging AI study planner assistant, speaking with the user out loud in real time.

Style:
- Conversational, warm, and concise — 2 short sentences per turn unless the user asks for more detail or a list.
- Avoid long monologues; you're having a spoken conversation, not writing an essay.
- Confirm tool use briefly, e.g. "Let me look that up" rather than describing the function call.

Tools:
- web_search(query) — search the web for current information. Use it when the user asks about something you would not know reliably (current events, specific facts, schedules, etc).

Behaviour:
- If the user interrupts you mid-sentence, stop immediately and listen.
- If a tool returns an error or no results, say so in plain English and offer to try a different query.
- You are helping the user study and plan their learning, so feel free to suggest study techniques, summarize topics, quiz the user, or help them build a study schedule when relevant.
"""

WEB_SEARCH_TOOL_DECLARATION = {
    "function_declarations": [
        {
            "name": "web_search",
            "description": "Search the web for current information and return a list of results with titles, links, and snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    }
                },
                "required": ["query"],
            },
        }
    ]
}


def _build_live_config() -> genai_types.LiveConnectConfig:
    """LiveConnectConfig with audio responses, server-side VAD, transcription, and the web_search tool."""
    return genai_types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=SYSTEM_INSTRUCTIONS,
        tools=[WEB_SEARCH_TOOL_DECLARATION],
        realtime_input_config=genai_types.RealtimeInputConfig(
            automatic_activity_detection=genai_types.AutomaticActivityDetection(
                disabled=False,
            ),
        ),
        input_audio_transcription=genai_types.AudioTranscriptionConfig(),
        output_audio_transcription=genai_types.AudioTranscriptionConfig(),
    )


async def _run_web_search_tool(query: str) -> dict:
    """Run the (blocking) DuckDuckGo search helper in a thread so it doesn't block the event loop."""
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(None, perform_web_search, query, 5)
    if not results:
        return {"results": [], "note": "No results found."}
    return {
        "results": [
            {"title": r["title"], "url": r["href"], "snippet": r["body"]}
            for r in results
        ]
    }


class VoiceSession:
    """Owns one Gemini Live connection and the queues that feed/drain it.

    Usage: create, call run(), which blocks until the session ends (socket
    closed, error, or stop() called). Feed mic audio via push_audio() from
    your WebSocket receive loop; consume transcript/audio events by passing
    callbacks into run().
    """

    def __init__(self, api_key: str):
        self._client = genai.Client(api_key=api_key)
        self._mic_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=200)
        self._stop_event = asyncio.Event()

    def push_audio(self, pcm_chunk: bytes) -> None:
        """Called from the WebSocket receive loop with raw 16kHz PCM16 bytes from the browser."""
        try:
            self._mic_queue.put_nowait(pcm_chunk)
        except asyncio.QueueFull:
            # Drop oldest-style backpressure: if the model/network can't keep up,
            # prefer dropping audio over blocking the receive loop.
            pass

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self._mic_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    async def run(
        self,
        on_audio_chunk: Callable[[bytes], Awaitable[None]],
        on_input_transcript: Callable[[str], Awaitable[None]],
        on_output_transcript: Callable[[str], Awaitable[None]],
        on_turn_complete: Callable[[], Awaitable[None]],
        on_interrupted: Callable[[], Awaitable[None]],
    ) -> None:
        """Run the Live session until stop() is called or the connection errors out.

        on_audio_chunk: raw 24kHz PCM16 bytes to play back to the browser.
        on_input_transcript / on_output_transcript: incremental transcript text
            for what the user said / what the assistant is saying.
        on_turn_complete: assistant finished a full turn (flush transcript buffer).
        on_interrupted: user started talking over the assistant; caller should
            stop playback of anything already queued client-side.
        """
        config = _build_live_config()

        async with self._client.aio.live.connect(model=MODEL, config=config) as session:
            send_task = asyncio.create_task(self._send_audio_loop(session))
            recv_task = asyncio.create_task(
                self._receive_loop(
                    session,
                    on_audio_chunk,
                    on_input_transcript,
                    on_output_transcript,
                    on_turn_complete,
                    on_interrupted,
                )
            )
            stop_waiter = asyncio.create_task(self._stop_event.wait())

            tasks = {send_task, recv_task, stop_waiter}
            try:
                done, pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                # Always cancel and await every task we created, even on the
                # happy path, so no task's result/exception is ever left
                # unretrieved (that's what produced the dangling
                # "Task exception was never retrieved" log before).
                for task in tasks:
                    if not task.done():
                        task.cancel()
                results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, BaseException) and not isinstance(
                    result, asyncio.CancelledError
                ):
                    raise result

    async def _send_audio_loop(self, session) -> None:
        while not self._stop_event.is_set():
            chunk = await self._mic_queue.get()
            if chunk is None:
                break
            await session.send_realtime_input(
                audio=genai_types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
            )

    async def _handle_tool_call(self, session, tool_call) -> None:
        responses = []
        for fc in tool_call.function_calls or []:
            if fc.name == "web_search":
                query = (fc.args or {}).get("query", "")
                try:
                    result = await _run_web_search_tool(query)
                except Exception as exc:  # noqa: BLE001
                    result = {"error": str(exc)}
            else:
                result = {"error": f"Unknown tool: {fc.name}"}
            responses.append({"id": fc.id, "name": fc.name, "response": result})
        await session.send_tool_response(function_responses=responses)

    async def _receive_loop(
        self,
        session,
        on_audio_chunk,
        on_input_transcript,
        on_output_transcript,
        on_turn_complete,
        on_interrupted,
    ) -> None:
        from google.genai import errors as genai_errors
        from websockets.exceptions import ConnectionClosedOK

        try:
            async for response in session.receive():
                if self._stop_event.is_set():
                    return

                if response.tool_call:
                    await self._handle_tool_call(session, response.tool_call)
                    continue

                sc = response.server_content
                if sc is None:
                    continue

                if sc.interrupted:
                    await on_interrupted()
                    continue

                if sc.model_turn:
                    for part in sc.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            await on_audio_chunk(part.inline_data.data)

                if sc.input_transcription and sc.input_transcription.text:
                    await on_input_transcript(sc.input_transcription.text)

                if sc.output_transcription and sc.output_transcription.text:
                    await on_output_transcript(sc.output_transcription.text)

                if sc.turn_complete:
                    await on_turn_complete()
        except ConnectionClosedOK:
            # The Live session closed cleanly (code 1000). This can be a
            # normal end-of-session, but if it happens immediately after
            # connecting with no prior activity, it usually means the
            # server rejected the session (e.g. no access to this model on
            # the current API key/project) rather than us hanging up.
            return
        except genai_errors.APIError as exc:
            # The SDK sometimes wraps a clean WebSocket close (1000) in an
            # APIError instead of letting it surface as ConnectionClosedOK.
            # Treat a bare "1000" code the same way; re-raise anything else
            # so it reaches the browser as a real error.
            if str(exc).strip().startswith("1000"):
                return
            raise