import type { ChatMessage as ChatMessageType } from "../api/types";
import { Calendar, CheckCircle, Trash2, Edit3, ListTodo } from "lucide-react";

interface Props {
  message: ChatMessageType;
}

const actionIcons: Record<string, typeof Calendar> = {
  create_event: Calendar,
  query: Calendar,
  modify: Edit3,
  delete: Trash2,
  create_task: ListTodo,
  add_task_to_calendar: ListTodo,
};

const actionLabels: Record<string, string> = {
  create_event: "Creating event",
  query: "Checking calendar",
  modify: "Modifying event",
  delete: "Deleting event",
  create_task: "Creating task",
  add_task_to_calendar: "Creating task + event",
};

export function ChatMessage({ message }: Props) {
  const isUser = message.role === "user";

  return (
    <div className={`chat-message ${isUser ? "user" : "assistant"}`}>
      <div className="chat-bubble">
        {message.intent && (
          <div className="chat-intent">
            {(() => {
              const Icon = actionIcons[message.intent.action] || CheckCircle;
              return <Icon size={14} />;
            })()}
            <span>
              {actionLabels[message.intent.action] || message.intent.action}
              {message.intent.title && `: ${message.intent.title}`}
              {message.intent.date && ` (${message.intent.date})`}
            </span>
          </div>
        )}
        <div className="chat-text">
          {message.content.split("\n").map((line, i) => (
            <span key={i}>
              {line}
              {i < message.content.split("\n").length - 1 && <br />}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
