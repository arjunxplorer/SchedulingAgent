import { useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchAuthStatus, startAuthLogin, authLogout } from "../api/client";
import type { AuthStatus } from "../api/types";

export function useAuth() {
  const queryClient = useQueryClient();

  const status = useQuery<AuthStatus>({
    queryKey: ["auth"],
    queryFn: fetchAuthStatus,
    retry: false,
  });

  // Listen for auth success message from the popup window
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (event.data === "google-auth-success") {
        queryClient.invalidateQueries({ queryKey: ["auth"] });
        queryClient.invalidateQueries({ queryKey: ["events"] });
        queryClient.invalidateQueries({ queryKey: ["tasks"] });
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [queryClient]);

  const login = useMutation({
    mutationFn: startAuthLogin,
    onSuccess: (authUrl) => {
      window.open(authUrl, "_blank", "width=600,height=700");
    },
  });

  const logout = useMutation({
    mutationFn: authLogout,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["auth"] });
    },
  });

  return {
    isAuthenticated: status.data?.authenticated ?? false,
    reason: status.data?.reason,
    isLoading: status.isLoading,
    login,
    logout,
    refetch: status.refetch,
  };
}
