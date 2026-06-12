/**
 * VoicePanel — Jarvis-style voice interface. You speak, it responds as text.
 */
import { useRef, useEffect } from "react";
import { useVoice } from "../hooks/useVoice";
import { Mic, MicOff, Trash2, Wifi, WifiOff } from "lucide-react";

export function VoicePanel() {
  const {
    connectionState,
    isListening,
    isProcessing,
    transcript,
    toggleListening,
    clearTranscript,
  } = useVoice();

  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [transcript]);

  const statusLabel = () => {
    if (connectionState !== "connected") return "Connecting...";
    if (isProcessing) return "Processing...";
    if (isListening) return "Listening";
    return "Ready";
  };

  return (
    <div className="voice-panel">
      <div className="voice-header">
        <div className="voice-title">
          <span className="voice-logo">⚡</span>
          <span>JARVIS</span>
        </div>
        <div className="voice-header-right">
          {transcript.length > 0 && (
            <button className="btn-icon" onClick={clearTranscript} title="Clear">
              <Trash2 size={14} />
            </button>
          )}
          <div className={`voice-conn ${connectionState}`}>
            {connectionState === "connected" ? <Wifi size={13} /> : <WifiOff size={13} />}
          </div>
        </div>
      </div>

      <div className="voice-transcript">
        {transcript.length === 0 && (
          <div className="voice-empty">
            <div className="voice-empty-icon">🎙️</div>
            <p className="voice-empty-title">Press to speak</p>
            <p className="voice-empty-hint">"What's on my calendar tomorrow?"</p>
          </div>
        )}

        {transcript.map((entry) => (
          <div key={entry.id} className={`voice-row voice-${entry.role}`}>
            <span className="voice-role">{entry.role === "user" ? "You" : "Jarvis"}</span>
            <span className="voice-text">{entry.text}</span>
          </div>
        ))}

        {isProcessing && (
          <div className="voice-row voice-thinking">
            <span className="voice-role">Jarvis</span>
            <span className="voice-dots"><span>.</span><span>.</span><span>.</span></span>
          </div>
        )}

        <div ref={endRef} />
      </div>

      <div className="voice-bar">
        <span className={`voice-status ${isListening ? "active" : ""}`}>{statusLabel()}</span>
        <button
          className={`voice-mic ${isListening ? "on" : ""} ${isProcessing ? "busy" : ""}`}
          onClick={toggleListening}
          disabled={connectionState !== "connected" || isProcessing}
        >
          {isListening ? <MicOff size={22} /> : <Mic size={22} />}
        </button>
      </div>
    </div>
  );
}
