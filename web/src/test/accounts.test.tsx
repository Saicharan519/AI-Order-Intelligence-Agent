// Sign-in, invite sign-up and admin pages, against a fake API (no network).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AdminPage } from "@/components/admin-page";
import { SignInForm, SignUpForm } from "@/components/auth-forms";
import type { Api, ApiResult } from "@/lib/api";
import type { AdminInvite, AdminUser, UserInfo } from "@/lib/types";
import { router, setQuery } from "./navigation-mock";

const ADMIN: UserInfo = { id: "a-1", email: "admin@example.test", name: "Sai", role: "admin" };
const PW = "a good passphrase 1";
const CODE = "Zq3x".repeat(10);

function api(overrides: Partial<Api> = {}): Api {
  const no = async () => ({ ok: false as const, code: "not_found", status: 404 });
  const base = {
    me: vi.fn(async () => ({ ok: true as const, data: ADMIN })),
    signIn: vi.fn(no),
    signUp: vi.fn(no),
    signOut: vi.fn(no),
    inviteInfo: vi.fn(no),
    health: vi.fn(no),
    budget: vi.fn(no),
    ask: vi.fn(no),
    trace: vi.fn(no),
    clearScope: vi.fn(no),
    sessions: vi.fn(no),
    session: vi.fn(no),
    catalog: vi.fn(no),
    adminUsers: vi.fn(no),
    adminInvites: vi.fn(no),
    createInvite: vi.fn(no),
    revokeInvite: vi.fn(no),
    setUserDisabled: vi.fn(no),
  };
  return { ...base, ...overrides } as Api;
}

const ok = <T,>(data: T): ApiResult<T> => ({ ok: true, data });

describe("Sign in", () => {
  it("signs in and opens the workspace", async () => {
    const user = userEvent.setup();
    const a = api({ signIn: vi.fn(async () => ok({ user: ADMIN })) });
    render(<SignInForm api={a} />);
    await user.type(screen.getByLabelText("Email"), "admin@example.test");
    await user.type(screen.getByLabelText("Password"), PW);
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(a.signIn).toHaveBeenCalledWith("admin@example.test", PW);
    expect(router.replace).toHaveBeenCalledWith("/");
  });

  it("shows one plain message for a wrong email or password", async () => {
    const user = userEvent.setup();
    const a = api({ signIn: vi.fn(async () => ({ ok: false as const, code: "invalid_credentials", status: 401 })) });
    render(<SignInForm api={a} />);
    await user.type(screen.getByLabelText("Email"), "x@example.test");
    await user.type(screen.getByLabelText("Password"), "wrong passphrase");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Email or password is wrong.");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("lets you show the password while typing", async () => {
    const user = userEvent.setup();
    render(<SignInForm api={api()} />);
    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "text");
  });
});

describe("Create your account from an invite", () => {
  it("shows the invited email and creates the account with the user's own password", async () => {
    const user = userEvent.setup();
    setQuery(`invite=${CODE}`);
    const a = api({
      inviteInfo: vi.fn(async () => ok({ email: "friend@example.test", expires_at: "2026-10-25T00:00:00Z" })),
      signUp: vi.fn(async () => ok({ user: { ...ADMIN, role: "user" as const } })),
    });
    render(<SignUpForm api={a} />);
    const email = await screen.findByLabelText("Email");
    expect(email).toHaveValue("friend@example.test");
    expect(email).toBeDisabled();
    await user.type(screen.getByLabelText("Your name"), "Friend");
    await user.type(screen.getByLabelText("Password"), PW);
    await user.type(screen.getByLabelText("Repeat the password"), PW);
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(a.inviteInfo).toHaveBeenCalledWith(CODE);
    expect(a.signUp).toHaveBeenCalledWith(CODE, "Friend", PW);
    expect(router.replace).toHaveBeenCalledWith("/");
  });

  it("will not submit a short or mismatched password", async () => {
    const user = userEvent.setup();
    setQuery(`invite=${CODE}`);
    const a = api({ inviteInfo: vi.fn(async () => ok({ email: "f@example.test", expires_at: "x" })) });
    render(<SignUpForm api={a} />);
    await user.type(await screen.findByLabelText("Your name"), "F");
    await user.type(screen.getByLabelText("Password"), "short");
    expect(screen.getByText(/needs at least 10 characters/)).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Password"));
    await user.type(screen.getByLabelText("Password"), PW);
    await user.type(screen.getByLabelText("Repeat the password"), PW + "x");
    expect(screen.getByText("The two passwords are different.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create account" })).toBeDisabled();
    expect(a.signUp).not.toHaveBeenCalled();
  });

  it("explains a used or expired invite, and a link without one", async () => {
    setQuery(`invite=${CODE}`);
    const a = api({ inviteInfo: vi.fn(async () => ({ ok: false as const, code: "invalid_invite", status: 404 })) });
    const { unmount } = render(<SignUpForm api={a} />);
    expect(await screen.findByText("Invite not valid")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/may be used or expired/);
    unmount();
    setQuery("");
    const b = api();
    render(<SignUpForm api={b} />);
    expect(await screen.findByText("Invite not valid")).toBeInTheDocument();
    expect(b.inviteInfo).not.toHaveBeenCalled();
  });
});

describe("Admin", () => {
  const USERS: AdminUser[] = [
    { id: "a-1", email: "admin@example.test", name: "Sai", role: "admin", disabled: false, created_at: "2026-10-18T10:00:00Z", last_login_at: "2026-10-18T12:00:00Z", total_usd: 0.0931, today_usd: 0.002, questions: 40 },
    { id: "u-2", email: "friend@example.test", name: "Friend", role: "user", disabled: false, created_at: "2026-10-18T11:00:00Z", last_login_at: null, total_usd: 0.0004, today_usd: 0.0004, questions: 2 },
  ];
  const INVITES: AdminInvite[] = [
    { id: "i-1", email: "pending@example.test", created_at: "2026-10-18T10:00:00Z", expires_at: "2026-10-25T10:00:00Z", status: "pending" },
    { id: "i-2", email: "friend@example.test", created_at: "2026-10-18T10:00:00Z", expires_at: "2026-10-25T10:00:00Z", status: "used" },
  ];

  function adminApi(extra: Partial<Api> = {}) {
    return api({
      adminUsers: vi.fn(async () => ok({ users: USERS, user_daily_cap_usd: 0.05 })),
      adminInvites: vi.fn(async () => ok({ invites: INVITES })),
      ...extra,
    });
  }

  it("creates an invite and shows the one-time link to copy", async () => {
    const user = userEvent.setup();
    const a = adminApi({
      createInvite: vi.fn(async () => ok({ code: CODE, invite: { ...INVITES[0], email: "new@example.test" } })),
    });
    render(<AdminPage api={a} />);
    await user.type(await screen.findByLabelText("Email to invite"), "new@example.test");
    await user.click(screen.getByRole("button", { name: /Create invite link/ }));
    expect(a.createInvite).toHaveBeenCalledWith("new@example.test");
    expect(await screen.findByLabelText("Invite link")).toHaveTextContent(`/signup?invite=${CODE}`);
    expect(screen.getByText(/shown only once/)).toBeInTheDocument();
  });

  it("lists users with their spend and lets the admin disable someone else, not themselves", async () => {
    const user = userEvent.setup();
    const a = adminApi({ setUserDisabled: vi.fn(async () => ok({ id: "u-2", disabled: true })) });
    render(<AdminPage api={a} />);
    const row = (await screen.findByText("friend@example.test", { selector: "div" })).closest("tr")!;
    expect(within(row).getAllByText("$0.0004")).toHaveLength(2); // spent today and in total
    await user.click(within(row).getByRole("button", { name: "Disable" }));
    expect(a.setUserDisabled).toHaveBeenCalledWith("u-2", true);
    const mine = screen.getByText("admin@example.test", { selector: "div" }).closest("tr")!;
    expect(within(mine).queryByRole("button", { name: "Disable" })).not.toBeInTheDocument();
    expect(screen.getByText("Each user can spend $0.05 a day")).toBeInTheDocument();
  });

  it("revokes a pending invite only", async () => {
    const user = userEvent.setup();
    const a = adminApi({ revokeInvite: vi.fn(async () => ok({ revoked: true })) });
    render(<AdminPage api={a} />);
    const buttons = await screen.findAllByRole("button", { name: "Revoke" });
    expect(buttons).toHaveLength(1);
    await user.click(buttons[0]);
    expect(a.revokeInvite).toHaveBeenCalledWith("i-1");
  });

  it("tells a normal user the page is for admins, and sends visitors to sign in", async () => {
    const a = api({ me: vi.fn(async () => ok({ ...ADMIN, role: "user" as const })) });
    const { unmount } = render(<AdminPage api={a} />);
    expect(await screen.findByText("Admins only")).toBeInTheDocument();
    expect(a.adminUsers).not.toHaveBeenCalled();
    unmount();
    render(<AdminPage api={api({ me: vi.fn(async () => ({ ok: false as const, code: "unauthorized", status: 401 })) })} />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
  });
});
