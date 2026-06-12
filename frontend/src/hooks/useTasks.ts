import { useQuery } from "@tanstack/react-query";
import { fetchTasks } from "../api/client";
import type { Task } from "../api/types";

export function useTasks() {
  return useQuery<Task[]>({
    queryKey: ["tasks"],
    queryFn: fetchTasks,
    refetchInterval: 60000, // Refresh every 60s
  });
}
