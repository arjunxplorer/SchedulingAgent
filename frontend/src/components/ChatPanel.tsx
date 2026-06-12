import { useState, useRef, useEffect, useCallback } from "react";
import { useChat } from "../hooks/useChat";
import { ChatMessage } from "./ChatMessage";
import { Send, Square, Trash2, Mic } from "lucide-react";

// Web Speech API types
interface SpeechRecognitionEvent {
  results: SpeechRecognitionResultList;
  resultIndex: number;
}

interface SpeechRecognitionErrorEvent {
  error: string;
}

export function ChatPanel() {
  const { messages, isStreaming, currentStatus, sendMessage, cancel, clearMessages } = useChat();
  const [input, setInput] = useState("");
  const [isListening, setIsListening] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<any>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, currentStatus]);

  // Initialize SpeechRecognition
  useEffect(() => {
    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let transcript = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        transcript += event.results[i][0].transcript;
      }
      setInput((prev) => {
        // On first result, replace; on subsequent, append
        if (event.resultIndex === 0) return transcript;
        return prev + transcript;
      });
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      console.error("Speech recognition error:", event.error);
      setIsListening(false);
    };

    recognition.onend = () => {
      setIsListening(false);
    };

    recognitionRef.current = recognition;
  }, []);

  const toggleListening = useCallback(() => {
    if (!recognitionRef.current) return;
    if (isListening) {
      recognitionRef.current.stop();
      setIsListening(false);
    } else {
      setInput(""); // Clear input before starting
      recognitionRef.current.start();
      setIsListening(true);
    }
  }, [isListening]);

  const handleSend = () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
    }
    setInput("");
    sendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const hasSpeechAPI =
    typeof window !== "undefined" &&
    ((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition);

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <h2>Scheduling Agent</h2>
        {messages.length > 0 && (
          <button className="btn-icon" onClick={clearMessages} title="Clear chat">
            <Trash2 size={16} />
          </button>
        )}
      </div>

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p>Try something like:</p>
            <div className="chat-suggestions">
              <button onClick={() => { setInput("What's on my calendar today?"); }}>What's on my calendar today?</button>
              <button onClick={() => { setInput("Schedule a meeting tomorrow at 2pm for 1 hour"); }}>Schedule a meeting tomorrow at 2pm</button>
              <button onClick={() => { setInput("Add review PR to my todo list"); }}>Add a task to my list</button>
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <ChatMessage key={i} message={msg} />
        ))}

        {isStreaming && currentStatus && (
          <div className="chat-status">
            <div className="status-spinner" />
            <span>{currentStatus}</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-area">
        <textarea
          className="chat-input"
          placeholder={isListening ? "Listening..." : "Type a message..."}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          disabled={isStreaming}
        />
        {hasSpeechAPI && !isStreaming && (
          <button
            className={`btn-mic ${isListening ? "listening" : ""}`}
            onClick={toggleListening}
            title={isListening ? "Stop listening" : "Speak"}
          >
            <Mic size={18} />
          </button>
        )}
        {isStreaming ? (
          <button className="btn-send btn-cancel" onClick={cancel} title="Stop">
            <Square size={18} />
          </button>
        ) : (
          <button
            className="btn-send"
            onClick={handleSend}
            disabled={!input.trim()}
            title="Send"
          >
            <Send size={18} />
          </button>
        )}
      </div>
    </div>
  );
}
