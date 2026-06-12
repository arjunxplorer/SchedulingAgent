import { useState, useCallback, useRef } from "react";
import { streamChat } from "../api/client";
import type { ChatMessage, SSEEvent } from "../api/types";

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentStatus, setCurrentStatus] = useState<string | null>(null);
  const abortRef = useRef<(() => void) | null>(null);

  const sendMessage = useCallback((text: string) => {
    if (isStreaming) return;

    // Add user message
    const userMsg: ChatMessage = {
      role: "user",
      content: text,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);
    setCurrentStatus("Thinking...");

    // Prepare assistant message placeholder
    let assistantContent = "";
    let assistantIntent: ChatMessage["intent"] = undefined;

    const cleanup = streamChat(
      text,
      "default",
      (event: SSEEvent) => {
        switch (event.type) {
          case "status":
            setCurrentStatus(event.message || null);
            break;
          case "intent":
            assistantIntent = {
              action: event.action || "",
              title: event.title,
              date: event.date,
            };
            break;
          case "message":
            assistantContent = event.content || "";
            break;
          case "error":
            assistantContent = `Error: ${event.message || event.content || "Something went wrong"}`;
            break;
          case "done":
            break;
        }
      },
      () => {
        // Done — add the assistant message
        const assistantMsg: ChatMessage = {
          role: "assistant",
          content: assistantContent || "(No response)",
          intent: assistantIntent,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
        setIsStreaming(false);
        setCurrentStatus(null);
      },
      (err) => {
        const errorMsg: ChatMessage = {
          role: "assistant",
          content: `Error: ${err.message}`,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, errorMsg]);
        setIsStreaming(false);
        setCurrentStatus(null);
      }
    );

    abortRef.current = cleanup;
  }, [isStreaming]);

  const cancel = useCallback(() => {
    abortRef.current?.();
    setIsStreaming(false);
    setCurrentStatus(null);
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  return { messages, isStreaming, currentStatus, sendMessage, cancel, clearMessages };
}
