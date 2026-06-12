export interface CalendarEvent {
  id: string;
  summary: string;
  start: string;
  end: string;
}

export interface Task {
  id: string;
  title: string;
  notes: string;
  due_date: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  intent?: {
    action: string;
    title?: string;
    date?: string;
  };
  timestamp: Date;
}

export interface SSEEvent {
  type: "status" | "intent" | "message" | "error" | "done";
  node?: string;
  message?: string;
  action?: string;
  title?: string;
  date?: string;
  content?: string;
}

export interface AuthStatus {
  authenticated: boolean;
  reason?: "no_credentials" | "token_expired" | "token_invalid";
}
