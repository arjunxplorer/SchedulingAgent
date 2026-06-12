import { useQuery } from "@tanstack/react-query";
import { fetchEvents } from "../api/client";
import type { CalendarEvent } from "../api/types";

export function useEvents(dateRange: string = "today") {
  return useQuery<CalendarEvent[]>({
    queryKey: ["events", dateRange],
    queryFn: () => fetchEvents(dateRange),
    refetchInterval: 30000, // Refresh every 30s
  });
}
