// Sign-in, invite sign-up and admin pages, against a fake API (no network).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AdminPage } from "@/components/admin-page";
import { ForgotPasswordForm, SignInForm, SignUpForm } from "@/components/auth-forms";
import { SettingsPage } from "@/components/settings-page";
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
    deleteUser: vi.fn(no),
    updateProfile: vi.fn(no),
    changePassword: vi.fn(no),
    verifyCode: vi.fn(no),
    resendCode: vi.fn(no),
    forgotPassword: vi.fn(no),
    resendResetCode: vi.fn(no),
    resetPassword: vi.fn(no),
    confirmEmail: vi.fn(no),
    resendEmailCode: vi.fn(no),
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

  it("asks for the emailed code, can trust the device, then opens the workspace", async () => {
    const user = userEvent.setup();
    const a = api({
      signIn: vi.fn(async () => ok({ code_required: true, email_hint: "a***@example.test", mail_mode: "console" })),
      verifyCode: vi.fn(async () => ok({ user: ADMIN })),
    });
    render(<SignInForm api={a} />);
    await user.type(screen.getByLabelText("Email"), "admin@example.test");
    await user.type(screen.getByLabelText("Password"), PW);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Check your email")).toBeInTheDocument();
    expect(screen.getByText("a***@example.test")).toBeInTheDocument();
    expect(screen.getByText(/printed in the API's terminal/)).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled(); // the password alone is not enough
    expect(screen.getByRole("button", { name: /Send a new code in \d+s/ })).toBeDisabled();
    await user.type(screen.getByLabelText("6-digit code"), "654321");
    await user.click(screen.getByLabelText("Trust this device for 30 days"));
    await user.click(screen.getByRole("button", { name: "Verify and sign in" }));
    expect(a.verifyCode).toHaveBeenCalledWith("654321", true);
    expect(router.replace).toHaveBeenCalledWith("/");
  });

  it("explains a wrong code, and goes back to the password when the code expired", async () => {
    const user = userEvent.setup();
    const verify = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, code: "wrong_code", status: 400 })
      .mockResolvedValueOnce({ ok: false, code: "code_expired", status: 400 });
    const a = api({ signIn: vi.fn(async () => ok({ code_required: true, email_hint: "a***@example.test" })), verifyCode: verify });
    render(<SignInForm api={a} />);
    await user.type(screen.getByLabelText("Email"), "admin@example.test");
    await user.type(screen.getByLabelText("Password"), PW);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.type(await screen.findByLabelText("6-digit code"), "111111");
    await user.click(screen.getByRole("button", { name: "Verify and sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/wrong or has expired/);
    await user.click(screen.getByRole("button", { name: "Verify and sign in" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/expired. Please start again/);
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("links to the forgotten-password page", () => {
    render(<SignInForm api={api()} />);
    expect(screen.getByRole("link", { name: "Forgot password?" })).toHaveAttribute("href", "/forgot");
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

  it("emails the invite and still shows the one-time link to copy", async () => {
    const user = userEvent.setup();
    const a = adminApi({
      createInvite: vi.fn(async () =>
        ok({ code: CODE, invite: { ...INVITES[0], email: "new@example.test" }, mail: { sent: true, mode: "smtp" } }),
      ),
    });
    render(<AdminPage api={a} />);
    await user.type(await screen.findByLabelText("Email to invite"), "new@example.test");
    await user.click(screen.getByRole("button", { name: /Send invite/ }));
    expect(a.createInvite).toHaveBeenCalledWith("new@example.test");
    expect(await screen.findByText("Invite emailed to new@example.test")).toBeInTheDocument();
    expect(screen.getByLabelText("Invite link")).toHaveTextContent(`/signup?invite=${CODE}`);
    expect(screen.getByText(/shown only once/)).toBeInTheDocument();
  });

  it("says when the invite email failed or was only printed (development)", async () => {
    const user = userEvent.setup();
    const created = (mail: { sent: boolean; mode: string }) =>
      vi.fn(async () => ok({ code: CODE, invite: { ...INVITES[0], email: "new@example.test" }, mail }));
    const a = adminApi({ createInvite: created({ sent: false, mode: "smtp" }) });
    const { unmount } = render(<AdminPage api={a} />);
    await user.type(await screen.findByLabelText("Email to invite"), "new@example.test");
    await user.click(screen.getByRole("button", { name: /Send invite/ }));
    expect(await screen.findByText("The email to new@example.test could not be sent")).toBeInTheDocument();
    expect(screen.getByLabelText("Invite link")).toHaveTextContent(`/signup?invite=${CODE}`);
    unmount();

    render(<AdminPage api={adminApi({ createInvite: created({ sent: true, mode: "console" }) })} />);
    await user.type(await screen.findByLabelText("Email to invite"), "new@example.test");
    await user.click(screen.getByRole("button", { name: /Send invite/ }));
    expect(await screen.findByText(/printed in the API terminal/)).toBeInTheDocument();
  });

  it("lists users with their spend and lets the admin disable someone else, not themselves", async () => {
    const user = userEvent.setup();
    const a = adminApi({ setUserDisabled: vi.fn(async () => ok({ id: "u-2", disabled: true })) });
    render(<AdminPage api={a} />);
    const row = (await screen.findByText("friend@example.test", { selector: "div" })).closest("tr")!;
    expect(within(row).getAllByText("$0.0004")).toHaveLength(2); // spent today and in total
    await user.click(within(row).getByRole("button", { name: "Disable" }));
    expect(within(row).getByText("Block sign-in?")).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "No" }));
    expect(a.setUserDisabled).not.toHaveBeenCalled();
    await user.click(within(row).getByRole("button", { name: "Disable" }));
    await user.click(within(row).getByRole("button", { name: "Yes, disable" }));
    expect(a.setUserDisabled).toHaveBeenCalledWith("u-2", true);
    const mine = screen.getByText("admin@example.test", { selector: "div" }).closest("tr")!;
    expect(within(mine).queryByRole("button", { name: "Disable" })).not.toBeInTheDocument();
    expect(screen.getByText("Each user can spend $0.05 a day")).toBeInTheDocument();
  });

  it("deletes a normal user after a clear warning, never an admin", async () => {
    const user = userEvent.setup();
    const a = adminApi({ deleteUser: vi.fn(async () => ok({ id: "u-2", deleted: true, questions_removed: 2 })) });
    render(<AdminPage api={a} />);
    const row = (await screen.findByText("friend@example.test", { selector: "div" })).closest("tr")!;
    const mine = screen.getByText("admin@example.test", { selector: "div" }).closest("tr")!;
    expect(within(mine).queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "Delete" }));
    expect(within(row).getByText("Delete forever, with all their conversations?")).toBeInTheDocument();
    expect(a.deleteUser).not.toHaveBeenCalled();
    await user.click(within(row).getByRole("button", { name: "Yes, delete" }));
    expect(a.deleteUser).toHaveBeenCalledWith("u-2");
    expect(await screen.findByText(/Deleted Friend \(friend@example.test\) with 2 questions/)).toBeInTheDocument();
  });

  it("revokes a pending invite only", async () => {
    const user = userEvent.setup();
    const a = adminApi({ revokeInvite: vi.fn(async () => ok({ revoked: true })) });
    render(<AdminPage api={a} />);
    const buttons = await screen.findAllByRole("button", { name: "Revoke" });
    expect(buttons).toHaveLength(1);
    await user.click(buttons[0]);
    expect(a.revokeInvite).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Yes, revoke" }));
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

describe("Account settings", () => {
  it("changes the name without a password", async () => {
    const user = userEvent.setup();
    const a = api({ updateProfile: vi.fn(async () => ok({ ...ADMIN, name: "Sai Charan" })) });
    render(<SettingsPage api={a} />);
    const name = await screen.findByLabelText("Name");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled(); // nothing changed yet
    await user.clear(name);
    await user.type(name, "Sai Charan");
    expect(screen.queryByLabelText("Current password", { selector: "#profile-password" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(a.updateProfile).toHaveBeenCalledWith("Sai Charan", "admin@example.test", "");
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
  });

  it("changes the email only after the password and the code sent to the new address", async () => {
    const user = userEvent.setup();
    const a = api({
      updateProfile: vi.fn(async () => ok({ ...ADMIN, pending_email: "new@example.test" })),
      confirmEmail: vi.fn(async () => ok({ ...ADMIN, email: "new@example.test" })),
    });
    render(<SettingsPage api={a} />);
    const email = await screen.findByLabelText("Email");
    await user.clear(email);
    await user.type(email, "new@example.test");
    const save = screen.getByRole("button", { name: "Save changes" });
    expect(save).toBeDisabled();
    await user.type(document.getElementById("profile-password")!, PW);
    await user.click(save);
    expect(a.updateProfile).toHaveBeenCalledWith("Sai", "new@example.test", PW);
    expect(await screen.findByText(/until then you keep signing in with admin@example.test/)).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "Confirm new email" });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText("Code from the new email"), "12a34 56");
    expect(screen.getByLabelText("Code from the new email")).toHaveValue("123456"); // digits only
    await user.click(confirm);
    expect(a.confirmEmail).toHaveBeenCalledWith("123456");
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveValue("new@example.test");
  });

  it("explains a wrong current password", async () => {
    const user = userEvent.setup();
    const a = api({ changePassword: vi.fn(async () => ({ ok: false as const, code: "wrong_password", status: 400 })) });
    render(<SettingsPage api={a} />);
    await user.type(await screen.findByLabelText("Current password"), "not it");
    await user.type(screen.getByLabelText("New password"), PW);
    await user.type(screen.getByLabelText("Repeat the new password"), PW);
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(a.changePassword).toHaveBeenCalledWith("not it", PW);
    expect(await screen.findByRole("alert")).toHaveTextContent("Your current password is wrong.");
  });

  it("changes the password and says other devices were signed out", async () => {
    const user = userEvent.setup();
    const a = api({ changePassword: vi.fn(async () => ok({ ok: true })) });
    render(<SettingsPage api={a} />);
    await user.type(await screen.findByLabelText("Current password"), "old passphrase 1");
    await user.type(screen.getByLabelText("New password"), "short");
    expect(screen.getByText(/needs at least 10 characters/)).toBeInTheDocument();
    await user.clear(screen.getByLabelText("New password"));
    await user.type(screen.getByLabelText("New password"), PW);
    await user.type(screen.getByLabelText("Repeat the new password"), PW);
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText(/other devices were signed out/)).toBeInTheDocument();
    expect(screen.getByLabelText("Current password")).toHaveValue("");
  });

  it("sends visitors to sign in", async () => {
    render(<SettingsPage api={api({ me: vi.fn(async () => ({ ok: false as const, code: "unauthorized", status: 401 })) })} />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
  });
});

describe("Forgot password", () => {
  it("emails a code, then sets the new password with it", async () => {
    const user = userEvent.setup();
    const a = api({ forgotPassword: vi.fn(async () => ok({})), resetPassword: vi.fn(async () => ok({ ok: true })) });
    render(<ForgotPasswordForm api={a} />);
    await user.type(screen.getByLabelText("Email"), "admin@example.test");
    await user.click(screen.getByRole("button", { name: "Email me a code" }));
    expect(a.forgotPassword).toHaveBeenCalledWith("admin@example.test");
    expect(await screen.findByText(/If an account uses/)).toBeInTheDocument(); // never says whether it exists
    await user.type(screen.getByLabelText("6-digit code"), "123456");
    await user.type(screen.getByLabelText("New password"), PW);
    await user.type(screen.getByLabelText("Repeat the new password"), PW);
    await user.click(screen.getByRole("button", { name: "Set new password" }));
    expect(a.resetPassword).toHaveBeenCalledWith("123456", PW);
    expect(await screen.findByText("Password changed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });

  it("shows the server's reason for a weak password and a wrong code", async () => {
    const user = userEvent.setup();
    const reset = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, code: "weak_password", status: 400, message: "Use a less repetitive password." })
      .mockResolvedValueOnce({ ok: false, code: "wrong_code", status: 400 });
    render(<ForgotPasswordForm api={api({ forgotPassword: vi.fn(async () => ok({})), resetPassword: reset })} />);
    await user.type(screen.getByLabelText("Email"), "admin@example.test");
    await user.click(screen.getByRole("button", { name: "Email me a code" }));
    await user.type(await screen.findByLabelText("6-digit code"), "123456");
    await user.type(screen.getByLabelText("New password"), "aaaaaaaaaaaa");
    await user.type(screen.getByLabelText("Repeat the new password"), "aaaaaaaaaaaa");
    await user.click(screen.getByRole("button", { name: "Set new password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Use a less repetitive password.");
    await user.click(screen.getByRole("button", { name: "Set new password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/wrong or has expired/);
  });
});
