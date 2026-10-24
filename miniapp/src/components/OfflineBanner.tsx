import { WifiOff } from "lucide-react";
import { useEffect, useState } from "react";

import { useI18n } from "../i18n";

function useOnline(): boolean {
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine !== false));
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  return online;
}

/**
 * A slim line while the phone has no connection (R2 T41). Done, ticks and comments wait and go
 * out when it's back (TanStack Query pauses mutations offline), so nothing typed is lost.
 */
export function OfflineBanner() {
  const { t } = useI18n();
  const online = useOnline();
  if (online) return null;
  return (
    <div className="offline-banner" role="status">
      <WifiOff size={15} strokeWidth={2.6} aria-hidden />
      <span>{t("offline.banner")}</span>
    </div>
  );
}
