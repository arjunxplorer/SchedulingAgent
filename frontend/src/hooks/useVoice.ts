/**
 * Voice hook — WebSocket + mic capture. No TTS.
 */
import { useState, useRef, useCallback, useEffect } from "react";
import { VoiceClient, type VoiceMessage } from "../api/voiceClient";

export interface TranscriptEntry {
  id: number;
  role: "user" | "assistant";
  text: string;
  timestamp: Date;
}

type ConnectionState = "disconnected" | "connecting" | "connected";

const SAMPLE_RATE = 16000;

export function useVoice() {
  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");
  const [isListening, setIsListening] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);

  const clientRef = useRef<VoiceClient | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const transcriptIdRef = useRef(0);

  useEffect(() => {
    if (clientRef.current) return;

    const client = new VoiceClient();
    clientRef.current = client;

    const unsub = client.onMessage((msg: VoiceMessage) => {
      switch (msg.type) {
        case "connected":
          setConnectionState("connected");
          break;
        case "disconnected":
          setConnectionState("disconnected");
          setIsListening(false);
          setIsProcessing(false);
          break;
        case "error":
          break;
        case "transcript":
          if (msg.text) {
            addEntry("user", msg.text);
            setIsProcessing(true);
          }
          break;
        case "response":
          if (msg.text) addEntry("assistant", msg.text);
          setIsProcessing(false);
          break;
      }
    });

    client.connect();
    setConnectionState("connecting");

    return () => {
      unsub();
      client.disconnect();
      clientRef.current = null;
    };
  }, []);

  const addEntry = useCallback((role: TranscriptEntry["role"], text: string) => {
    setTranscript((prev) => [
      ...prev,
      { id: ++transcriptIdRef.current, role, text, timestamp: new Date() },
    ]);
  }, []);

  const startListening = useCallback(async () => {
    if (isListening) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: SAMPLE_RATE, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      mediaStreamRef.current = stream;

      const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
      audioContextRef.current = ctx;

      const source = ctx.createMediaStreamSource(stream);
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      processorRef.current = proc;

      proc.onaudioprocess = (e) => {
        const input = e.inputBuffer.getChannelData(0);
        const ratio = ctx.sampleRate / SAMPLE_RATE;
        let samples: Float32Array;
        if (ratio !== 1) {
          const len = Math.floor(input.length / ratio);
          samples = new Float32Array(len);
          for (let i = 0; i < len; i++) samples[i] = input[Math.floor(i * ratio)];
        } else {
          samples = input;
        }
        const pcm = new Int16Array(samples.length);
        for (let i = 0; i < samples.length; i++) {
          const s = Math.max(-1, Math.min(1, samples[i]));
          pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        clientRef.current?.sendAudio(btoa(String.fromCharCode(...new Uint8Array(pcm.buffer))));
      };

      source.connect(proc);
      proc.connect(ctx.destination);
      setIsListening(true);
    } catch (err) {
      console.error("Mic error:", err);
    }
  }, [isListening]);

  const stopListening = useCallback(() => {
    if (!isListening) return;
    clientRef.current?.sendEndOfSpeech();
    if (processorRef.current) { processorRef.current.disconnect(); processorRef.current = null; }
    if (audioContextRef.current) { audioContextRef.current.close(); audioContextRef.current = null; }
    if (mediaStreamRef.current) { mediaStreamRef.current.getTracks().forEach((t) => t.stop()); mediaStreamRef.current = null; }
    setIsListening(false);
  }, [isListening]);

  const toggleListening = useCallback(() => {
    isListening ? stopListening() : startListening();
  }, [isListening, startListening, stopListening]);

  const clearTranscript = useCallback(() => { setTranscript([]); }, []);

  return {
    connectionState,
    isListening,
    isProcessing,
    transcript,
    toggleListening,
    clearTranscript,
  };
}
