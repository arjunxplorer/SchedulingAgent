import type { CalendarEvent, Task, AuthStatus, SSEEvent } from "./types";

const API_BASE = "";

export async function fetchEvents(
  dateRange: string = "today",
  query: string = ""
): Promise<CalendarEvent[]> {
  const params = new URLSearchParams({ date_range: dateRange, query });
  const res = await fetch(`${API_BASE}/events?${params}`);
  if (!res.ok) throw new Error("Failed to fetch events");
  const data = await res.json();
  return data.events;
}

export async function fetchTasks(): Promise<Task[]> {
  const res = await fetch(`${API_BASE}/tasks`);
  if (!res.ok) throw new Error("Failed to fetch tasks");
  const data = await res.json();
  return data.tasks;
}

export async function fetchAuthStatus(): Promise<AuthStatus> {
  const res = await fetch(`${API_BASE}/auth/status`);
  if (!res.ok) return { authenticated: false };
  return res.json();
}

export async function startAuthLogin(): Promise<string> {
  const res = await fetch(`${API_BASE}/auth/login`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to start login");
  const data = await res.json();
  return data.auth_url;
}

export async function authLogout(): Promise<void> {
  await fetch(`${API_BASE}/auth/logout`, { method: "POST" });
}

export function streamChat(
  message: string,
  sessionId: string = "default",
  onEvent: (event: SSEEvent) => void,
  onDone: () => void,
  onError: (err: Error) => void
): () => void {
  const controller = new AbortController();

  fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok || !res.body) {
        throw new Error(`Chat request failed: ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const event = JSON.parse(line.slice(6)) as SSEEvent;
              onEvent(event);
            } catch {
              // Skip malformed JSON
            }
          }
        }
      }

      onDone();
    })
    .catch((err) => {
      if (err.name !== "AbortError") {
        onError(err);
      }
    });

  return () => controller.abort();
}
