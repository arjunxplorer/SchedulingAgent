import { useAuth } from "../hooks/useAuth";
import { LogIn, LogOut, Loader2 } from "lucide-react";

export function AuthStatus() {
  const { isAuthenticated, reason, isLoading, login, logout } = useAuth();

  if (isLoading) {
    return (
      <div className="auth-status">
        <Loader2 size={14} className="spin" />
        <span>Checking...</span>
      </div>
    );
  }

  if (isAuthenticated) {
    return (
      <div className="auth-status authenticated">
        <div className="auth-indicator" />
        <span>Connected</span>
        <button className="btn-icon" onClick={() => logout.mutate()} title="Logout">
          <LogOut size={14} />
        </button>
      </div>
    );
  }

  const reasonMessage =
    reason === "token_expired"
      ? "Session expired — please reconnect"
      : reason === "token_invalid"
        ? "Credentials invalid — please reconnect"
        : null;

  return (
    <div className="auth-status unauthenticated">
      {reasonMessage && <span className="auth-reason">{reasonMessage}</span>}
      <button className="btn-auth" onClick={() => login.mutate()} disabled={login.isPending}>
        <LogIn size={14} />
        {login.isPending ? "Connecting..." : "Connect Google Calendar"}
      </button>
    </div>
  );
}
