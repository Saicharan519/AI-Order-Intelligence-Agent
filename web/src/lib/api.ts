// Browser-side calls to this app's /api proxy. Sign-in state is an httpOnly cookie the
// browser sends automatically; no token or code is handled here. Errors come back as codes
// from ERROR_MESSAGES, never as thrown exceptions, so every caller handles them the same way.

import type {
  AdminInvite,
  AdminUser,
  AskResponse,
  Budget,
  Catalog,
  Health,
  SessionDetail,
  SessionSummary,
  Trace,
  UserInfo,
} from "./types";

/** After the password: either signed in ({user}) or an emailed code is needed. */
export type SignInStep = {
  user?: UserInfo;
  code_required?: boolean;
  email_hint?: string;
  mail_mode?: string; // "console": the email was printed in the API terminal, not sent
};

export type ApiResult<T> = { ok: true; data: T } | { ok: false; code: string; status: number; message?: string };

export interface Api {
  me(): Promise<ApiResult<UserInfo>>;
  signIn(email: string, password: string): Promise<ApiResult<SignInStep>>;
  verifyCode(code: string, trustDevice: boolean): Promise<ApiResult<{ user: UserInfo }>>;
  resendCode(): Promise<ApiResult<{ ok: boolean }>>;
  forgotPassword(email: string): Promise<ApiResult<{ mail_mode?: string }>>;
  resendResetCode(): Promise<ApiResult<{ ok: boolean }>>;
  resetPassword(code: string, newPassword: string): Promise<ApiResult<{ ok: boolean }>>;
  signUp(invite: string, name: string, password: string): Promise<ApiResult<{ user: UserInfo }>>;
  signOut(): Promise<ApiResult<{ ok: boolean }>>;
  inviteInfo(code: string): Promise<ApiResult<{ email: string; expires_at: string }>>;
  updateProfile(
    name: string,
    email: string,
    currentPassword: string,
  ): Promise<ApiResult<UserInfo & { pending_email?: string; mail_mode?: string }>>;
  confirmEmail(code: string): Promise<ApiResult<UserInfo>>;
  resendEmailCode(): Promise<ApiResult<{ ok: boolean }>>;
  changePassword(currentPassword: string, newPassword: string): Promise<ApiResult<{ ok: boolean }>>;
  health(): Promise<ApiResult<Health>>;
  budget(): Promise<ApiResult<Budget>>;
  ask(question: string, sessionId: string): Promise<ApiResult<AskResponse>>;
  trace(requestId: string): Promise<ApiResult<Trace>>;
  clearScope(sessionId: string): Promise<ApiResult<{ cleared: boolean }>>;
  sessions(): Promise<ApiResult<{ sessions: SessionSummary[] }>>;
  session(sessionId: string): Promise<ApiResult<SessionDetail>>;
  catalog(): Promise<ApiResult<Catalog>>;
  adminUsers(): Promise<ApiResult<{ users: AdminUser[]; user_daily_cap_usd: number }>>;
  adminInvites(): Promise<ApiResult<{ invites: AdminInvite[] }>>;
  createInvite(email: string): Promise<ApiResult<{ code: string; invite: AdminInvite; mail?: { sent: boolean; mode: string } }>>;
  revokeInvite(id: string): Promise<ApiResult<{ revoked: boolean }>>;
  setUserDisabled(id: string, disabled: boolean): Promise<ApiResult<{ id: string; disabled: boolean }>>;
  deleteUser(id: string): Promise<ApiResult<{ id: string; deleted: boolean; questions_removed: number }>>;
}

async function call<T>(method: string, path: string, body?: unknown): Promise<ApiResult<T>> {
  let r: Response;
  try {
    r = await fetch(`/api/${path}`, {
      method,
      headers: body !== undefined ? { "content-type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
      credentials: "same-origin",
    });
  } catch {
    return { ok: false, code: "connection_error", status: 0 };
  }
  let data: unknown;
  try {
    data = await r.json();
  } catch {
    return { ok: false, code: "internal_error", status: r.status };
  }
  if (!r.ok) {
    const e = (data as { error?: { code?: string; message?: string } })?.error;
    return { ok: false, code: e?.code ?? "internal_error", status: r.status, message: e?.message };
  }
  return { ok: true, data: data as T };
}

const enc = encodeURIComponent;

export const httpApi: Api = {
  me: () => call("GET", "v1/auth/me"),
  signIn: (email, password) => call("POST", "auth/login", { email, password }),
  verifyCode: (code, trustDevice) => call("POST", "auth/verify", { code, trust_device: trustDevice }),
  resendCode: () => call("POST", "auth/resend", {}),
  forgotPassword: (email) => call("POST", "auth/forgot", { email }),
  resendResetCode: () => call("POST", "auth/forgot-resend", {}),
  resetPassword: (code, newPassword) => call("POST", "auth/reset", { code, new_password: newPassword }),
  signUp: (invite, name, password) => call("POST", "auth/signup", { invite, name, password }),
  signOut: () => call("POST", "auth/logout", {}),
  inviteInfo: (code) => call("GET", `v1/auth/invites/${enc(code)}`),
  updateProfile: (name, email, currentPassword) =>
    call("POST", "v1/account/profile", { name, email, current_password: currentPassword }),
  confirmEmail: (code) => call("POST", "v1/account/email/confirm", { code }),
  resendEmailCode: () => call("POST", "v1/account/email/resend", {}),
  changePassword: (currentPassword, newPassword) =>
    call("POST", "v1/account/password", { current_password: currentPassword, new_password: newPassword }),
  health: () => call("GET", "v1/health"),
  budget: () => call("GET", "v1/budget"),
  ask: (question, sessionId) => call("POST", "v1/ask", { question, session_id: sessionId }),
  trace: (id) => call("GET", `v1/requests/${enc(id)}`),
  clearScope: (sessionId) => call("POST", `v1/sessions/${enc(sessionId)}/scope/clear`, {}),
  sessions: () => call("GET", "v1/sessions"),
  session: (sessionId) => call("GET", `v1/sessions/${enc(sessionId)}`),
  catalog: () => call("GET", "v1/catalog"),
  adminUsers: () => call("GET", "v1/admin/users"),
  adminInvites: () => call("GET", "v1/admin/invites"),
  createInvite: (email) => call("POST", "v1/admin/invites", { email }),
  revokeInvite: (id) => call("POST", `v1/admin/invites/${enc(id)}/revoke`, {}),
  setUserDisabled: (id, disabled) => call("POST", `v1/admin/users/${enc(id)}/${disabled ? "disable" : "enable"}`, {}),
  deleteUser: (id) => call("POST", `v1/admin/users/${enc(id)}/delete`, {}),
};
