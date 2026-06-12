import { useState } from "react";
import { useEvents } from "../hooks/useEvents";
import { Calendar, ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";

const DATE_RANGES = [
  { value: "today", label: "Today" },
  { value: "tomorrow", label: "Tomorrow" },
  { value: "this_week", label: "This Week" },
  { value: "next_week", label: "Next Week" },
] as const;

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
  } catch {
    return "";
  }
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

export function CalendarView() {
  const [dateRange, setDateRange] = useState("today");
  const { data: events, isLoading, refetch, isFetching } = useEvents(dateRange);

  return (
    <div className="calendar-view">
      <div className="calendar-header">
        <div className="calendar-header-left">
          <Calendar size={18} />
          <h3>Calendar</h3>
        </div>
        <button
          className="btn-icon"
          onClick={() => refetch()}
          disabled={isFetching}
          title="Refresh"
        >
          <RefreshCw size={14} className={isFetching ? "spin" : ""} />
        </button>
      </div>

      <div className="calendar-range-tabs">
        {DATE_RANGES.map((r) => (
          <button
            key={r.value}
            className={`tab ${dateRange === r.value ? "active" : ""}`}
            onClick={() => setDateRange(r.value)}
          >
            {r.label}
          </button>
        ))}
      </div>

      <div className="calendar-events">
        {isLoading ? (
          <div className="calendar-loading">Loading...</div>
        ) : events && events.length > 0 ? (
          events.map((ev) => (
            <div key={ev.id} className="event-card">
              <div className="event-time">
                {formatTime(ev.start)} — {formatTime(ev.end)}
              </div>
              <div className="event-title">{ev.summary}</div>
              {dateRange === "this_week" || dateRange === "next_week" ? (
                <div className="event-date">{formatDate(ev.start)}</div>
              ) : null}
            </div>
          ))
        ) : (
          <div className="calendar-empty">No events {dateRange.replace("_", " ")}.</div>
        )}
      </div>
    </div>
  );
}
