/**
 * Sign-in endpoints (plan §4.3, §7.1). Anonymous calls: no Bearer token and no refresh dance. The
 * poll token is the browser's secret and travels only in the `X-Login-Poll` header; the deep link
 * (QR) carries the public code.
 */
import { request } from "@/api/http";
import type { AccessResponse } from "@/api/types";

export type LoginLinkStatus = "pending" | "approved" | "denied" | "expired" | "consumed";

/** `POST /owner/auth/login-links/` → 201 */
export interface LoginLink {
  id: string;
  poll_token: string;
  /** `https://t.me/<bot>?start=login_<code>`: shown as the QR and behind "Open in Telegram". */
  deep_link: string;
  bot_username: string;
  /** The 2-digit number the person taps in Telegram. */
  match_code: string;
  expires_at: string;
}

const AUTH = "/owner/auth/login-links/";

export function createLoginLink(): Promise<LoginLink> {
  return request<LoginLink>(AUTH, { method: "POST", json: {}, anonymous: true, toast: false });
}

/** `{status}` only; never a token. */
export function pollLoginLink(link: Pick<LoginLink, "id" | "poll_token">, signal?: AbortSignal): Promise<{ status: LoginLinkStatus }> {
  return request<{ status: LoginLinkStatus }>(`${AUTH}${link.id}/`, {
    anonymous: true,
    toast: false,
    signal,
    headers: { "X-Login-Poll": link.poll_token },
  });
}

/** Once, when approved: `{access}` plus the httpOnly refresh cookie. */
export function claimLoginLink(link: Pick<LoginLink, "id" | "poll_token">): Promise<AccessResponse> {
  return request<AccessResponse>(`${AUTH}${link.id}/claim/`, {
    method: "POST",
    json: {},
    anonymous: true,
    toast: false,
    headers: { "X-Login-Poll": link.poll_token },
  });
}
