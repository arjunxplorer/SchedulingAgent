"""Voice WebSocket endpoint — FastWhisper STT → Agent (no TTS)."""

import asyncio
import json
import base64
import struct
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

voice_router = APIRouter()

_whisper_model = None


def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("base.en", device="cpu", compute_type="int8")
    return _whisper_model


SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 0.008
SILENCE_DURATION_MS = 1500
MIN_AUDIO_SAMPLES = SAMPLE_RATE
MIN_SPEECH_RATIO = 0.15

NOISE_PHRASES = {
    "you", "thank you", "thanks", "bye", "bye-bye", "the end",
    "subscribe", "like and subscribe", "you you", "the", "a", "so",
}


def pcm16_to_float32(pcm_bytes: bytes) -> np.ndarray:
    samples = struct.unpack(f"<{len(pcm_bytes) // 2}h", pcm_bytes)
    return np.array(samples, dtype=np.float32) / 32768.0


def is_silence(audio: np.ndarray) -> bool:
    if len(audio) == 0:
        return True
    return np.sqrt(np.mean(audio ** 2)) < SILENCE_THRESHOLD


def is_noise(text: str) -> bool:
    cleaned = text.strip().lower().rstrip(".!?")
    if len(cleaned) < 3:
        return True
    return cleaned in NOISE_PHRASES


@voice_router.websocket("/ws/voice")
async def voice_websocket(ws: WebSocket):
    await ws.accept()
    print("[VOICE] Client connected")

    audio_buffer = bytearray()
    silence_chunks = 0
    speech_chunks = 0
    is_processing = False
    msg_count = 0

    async def send_json(data: dict):
        try:
            await ws.send_text(json.dumps(data))
        except Exception:
            pass

    def run_stt(audio_np: np.ndarray) -> str:
        model = get_whisper()
        segments, _ = model.transcribe(
            audio_np, beam_size=3, language="en",
            no_speech_threshold=0.5, condition_on_previous_text=False, vad_filter=True,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    async def process_utterance(audio_np: np.ndarray):
        nonlocal is_processing
        if is_processing:
            return
        is_processing = True

        try:
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(None, run_stt, audio_np)
            if is_noise(text):
                return

            print(f"[VOICE] Transcribed: {text!r}")
            await send_json({"type": "transcript", "text": text})

            from src.graph_runner import create_default_model, build_graph, default_session_state
            from src.tools import get_current_time

            session = default_session_state()
            session["user_input"] = text
            session["current_time"] = get_current_time.invoke({})
            model = create_default_model()
            graph = build_graph(model)
            result = await loop.run_in_executor(None, lambda: graph.invoke(session))

            feedback = result.get("feedback", "")
            response_text = feedback

            if not feedback:
                try:
                    from langchain_core.messages import SystemMessage, HumanMessage
                    fallback = create_default_model()
                    resp = await loop.run_in_executor(
                        None, lambda: fallback.invoke([
                            SystemMessage("You are a concise voice scheduling assistant. Respond in 1-2 sentences."),
                            HumanMessage(text),
                        ]),
                    )
                    response_text = resp.content
                except Exception:
                    response_text = "Done."

            print(f"[VOICE] Response: {response_text!r}")
            await send_json({"type": "response", "text": response_text})

        except Exception as e:
            print(f"[VOICE] Error: {e}")
            await send_json({"type": "error", "message": str(e)})
        finally:
            is_processing = False

    chunks_per_sec = SAMPLE_RATE / 4096

    try:
        while True:
            msg = await ws.receive_text()
            data = json.loads(msg)
            msg_count += 1

            if data["type"] == "audio":
                chunk = base64.b64decode(data["data"])
                audio_chunk = pcm16_to_float32(chunk)
                audio_buffer.extend(chunk)

                silent = is_silence(audio_chunk)
                if silent:
                    silence_chunks += 1
                else:
                    silence_chunks = 0
                    speech_chunks += 1

                if msg_count % 50 == 0:
                    print(f"[VOICE] msg#{msg_count} buf={len(audio_buffer)} silence={silence_chunks} speech={speech_chunks}")

                silence_limit = int(chunks_per_sec * SILENCE_DURATION_MS / 1000)
                total_chunks = speech_chunks + silence_chunks
                speech_ratio = speech_chunks / total_chunks if total_chunks > 0 else 0

                if silence_chunks >= silence_limit and speech_chunks > 0:
                    audio_len = len(audio_buffer) / 2 / SAMPLE_RATE
                    if audio_len >= 1.0 and speech_ratio >= MIN_SPEECH_RATIO:
                        audio_np = pcm16_to_float32(bytes(audio_buffer))
                        print(f"[VOICE] End of speech, {audio_len:.1f}s, ratio={speech_ratio:.2f}")
                        audio_buffer.clear()
                        silence_chunks = 0
                        speech_chunks = 0
                        asyncio.create_task(process_utterance(audio_np))
                    else:
                        audio_buffer.clear()
                        silence_chunks = 0
                        speech_chunks = 0

            elif data["type"] == "end_of_speech":
                if len(audio_buffer) > MIN_AUDIO_SAMPLES * 2:
                    audio_np = pcm16_to_float32(bytes(audio_buffer))
                    audio_buffer.clear()
                    silence_chunks = 0
                    speech_chunks = 0
                    asyncio.create_task(process_utterance(audio_np))
                else:
                    audio_buffer.clear()
                    silence_chunks = 0
                    speech_chunks = 0

            elif data["type"] == "interrupt":
                audio_buffer.clear()
                silence_chunks = 0
                speech_chunks = 0

    except WebSocketDisconnect:
        print("[VOICE] Client disconnected")
    except Exception as e:
        print(f"[VOICE] Error: {e}")
