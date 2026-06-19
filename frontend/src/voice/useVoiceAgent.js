import { useCallback, useEffect, useRef, useState } from 'react';
import { getToken } from '../api/client';
import { AudioPlayback } from './audioPlayback';
import { MicCapture } from './micCapture';

const WS_BASE =
  import.meta.env.VITE_WS_URL ||
  (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host;

/**
 * Manages a single voice session: opens the WebSocket + mic + speaker,
 * streams transcript text up as it arrives, and reports finished turns so
 * the caller can append them as chat messages.
 *
 * Usage in Chat.jsx:
 *   const voice = useVoiceAgent({ conversationId, onTurn: (turn) => ... });
 *   voice.start() / voice.stop()
 *   voice.listening, voice.liveUserText, voice.liveAssistantText
 */
export function useVoiceAgent({ conversationId, onTurn, onConversationId }) {
  const [listening, setListening] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState(null);
  const [liveUserText, setLiveUserText] = useState('');
  const [liveAssistantText, setLiveAssistantText] = useState('');

  const wsRef = useRef(null);
  const micRef = useRef(null);
  const playbackRef = useRef(null);
  const turnBufferRef = useRef({ user: '', assistant: '' });

  const cleanup = useCallback(() => {
    if (micRef.current) {
      micRef.current.stop();
      micRef.current = null;
    }
    if (playbackRef.current) {
      playbackRef.current.stop();
      playbackRef.current = null;
    }
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch {
        // socket may already be closed
      }
      wsRef.current = null;
    }
    setListening(false);
    setConnecting(false);
  }, []);

  const stop = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      try {
        wsRef.current.send('stop');
      } catch {
        // ignore
      }
    }
    cleanup();
  }, [cleanup]);

  const start = useCallback(async () => {
    if (listening || connecting) return;
    setError(null);
    setConnecting(true);
    turnBufferRef.current = { user: '', assistant: '' };
    setLiveUserText('');
    setLiveAssistantText('');

    const token = getToken();
    if (!token) {
      setError('Not authenticated.');
      setConnecting(false);
      return;
    }

    const params = new URLSearchParams({ token });
    if (conversationId) params.set('conversation_id', conversationId);
    const ws = new WebSocket(`${WS_BASE}/ws/voice?${params.toString()}`);
    ws.binaryType = 'arraybuffer';
    wsRef.current = ws;

    const playback = new AudioPlayback();
    playbackRef.current = playback;

    ws.onopen = () => {
      // Wait for the server's "ready" message before starting the mic, so
      // we know the conversation_id and that the Live session is live.
    };

    ws.onmessage = (event) => {
      if (typeof event.data === 'string') {
        let msg;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }

        switch (msg.type) {
          case 'ready': {
            playback.start();
            if (onConversationId) onConversationId(msg.conversation_id);
            const mic = new MicCapture({
              onChunk: (buf) => {
                if (ws.readyState === WebSocket.OPEN) ws.send(buf);
              },
            });
            micRef.current = mic;
            mic
              .start()
              .then(() => {
                setConnecting(false);
                setListening(true);
              })
              .catch((err) => {
                setError(err.message || 'Microphone access failed.');
                cleanup();
              });
            break;
          }
          case 'input_transcript': {
            turnBufferRef.current.user += msg.text;
            setLiveUserText(turnBufferRef.current.user);
            break;
          }
          case 'output_transcript': {
            turnBufferRef.current.assistant += msg.text;
            setLiveAssistantText(turnBufferRef.current.assistant);
            break;
          }
          case 'interrupted': {
            playback.flush();
            break;
          }
          case 'turn_complete': {
            const { user, assistant } = turnBufferRef.current;
            turnBufferRef.current = { user: '', assistant: '' };
            setLiveUserText('');
            setLiveAssistantText('');
            if (onTurn && (user.trim() || assistant.trim())) {
              onTurn({ user: user.trim(), assistant: assistant.trim() });
            }
            break;
          }
          case 'error': {
            setError(msg.message || 'Voice session error.');
            break;
          }
          default:
            break;
        }
        return;
      }

      // Binary frame: 24kHz PCM16 audio to play back.
      playback.enqueueChunk(event.data);
    };

    ws.onerror = () => {
      setError('Voice connection error.');
    };

    ws.onclose = () => {
      cleanup();
    };
  }, [listening, connecting, conversationId, onTurn, onConversationId, cleanup]);

  useEffect(() => stop, [stop]);

  return {
    start,
    stop,
    listening,
    connecting,
    error,
    liveUserText,
    liveAssistantText,
  };
}