import { hermesApi } from "@/lib/api";
import { format } from "date-fns";

interface Notification {
  id: string;
  channel: string;
  subject?: string;
  status: string;
  sent_at?: string;
  created_at: string;
}

export async function NotificationsPanel() {
  let notifications: Notification[] = [];
  let error = false;

  try {
    notifications = await hermesApi<Notification[]>("/api/v1/notifications?limit=8");
  } catch {
    error = true;
  }

  const channelIcon: Record<string, string> = {
    sms: "📱",
    email: "📧",
    dashboard: "🖥",
  };

  const statusColor: Record<string, string> = {
    sent: "text-jarvis-green",
    pending: "text-jarvis-yellow",
    failed: "text-jarvis-red",
  };

  return (
    <div className="bg-jarvis-surface border border-jarvis-border rounded-xl p-5">
      <h2 className="text-jarvis-text font-semibold text-sm uppercase tracking-wider mb-4">
        Notifications
      </h2>

      {error ? (
        <p className="text-jarvis-muted text-sm">Unavailable.</p>
      ) : notifications.length === 0 ? (
        <p className="text-jarvis-muted text-sm">No notifications yet.</p>
      ) : (
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {notifications.map((n) => (
            <div key={n.id} className="py-2 border-b border-jarvis-border/50 last:border-0">
              <div className="flex items-center gap-1.5 mb-0.5">
                <span className="text-xs">{channelIcon[n.channel] ?? "🔔"}</span>
                <span className="text-jarvis-text text-xs font-medium truncate">
                  {n.subject ?? n.channel}
                </span>
                <span className={`text-xs ml-auto shrink-0 ${statusColor[n.status] ?? "text-jarvis-muted"}`}>
                  {n.status}
                </span>
              </div>
              <div className="text-jarvis-muted text-xs font-mono">
                {format(new Date(n.created_at), "MM/dd HH:mm")}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
