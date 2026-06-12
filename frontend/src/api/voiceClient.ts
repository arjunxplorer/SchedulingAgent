/**
 * WebSocket client for the voice assistant.
 * Handles connection, audio streaming, and message routing.
 */

export interface VoiceMessage {
  type: string;
  text?: string;
  final?: boolean;
  message?: string;
  action?: string;
  title?: string;
  date?: string;
  tool?: string;
  args?: Record<string, unknown>;
  data?: string; // base64 audio
}

export type VoiceMessageHandler = (msg: VoiceMessage) => void;

export class VoiceClient {
  private ws: WebSocket | null = null;
  private handlers: VoiceMessageHandler[] = [];
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    this.ws = new WebSocket(`${protocol}//${host}/ws/voice`);

    this.ws.onopen = () => {
      this.notify({ type: "connected" });
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: VoiceMessage = JSON.parse(event.data);
        this.notify(msg);
      } catch {
        // ignore parse errors
      }
    };

    this.ws.onclose = () => {
      this.notify({ type: "disconnected" });
      // Auto-reconnect after 2s
      this.reconnectTimer = setTimeout(() => this.connect(), 2000);
    };

    this.ws.onerror = () => {
      this.notify({ type: "error", message: "WebSocket error" });
    };
  }

  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  sendAudio(pcm16Base64: string): void {
    this.send({ type: "audio", data: pcm16Base64 });
  }

  sendEndOfSpeech(): void {
    this.send({ type: "end_of_speech" });
  }

  sendInterrupt(): void {
    this.send({ type: "interrupt" });
  }

  onMessage(handler: VoiceMessageHandler): () => void {
    this.handlers.push(handler);
    return () => {
      this.handlers = this.handlers.filter((h) => h !== handler);
    };
  }

  private send(data: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  private notify(msg: VoiceMessage): void {
    for (const handler of this.handlers) {
      handler(msg);
    }
  }
}
