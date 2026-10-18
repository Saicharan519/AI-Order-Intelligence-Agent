// Sign-in (password, then the emailed 6-digit code unless the device is trusted), forgot
// password, and create-account forms. Everything goes to this app's own server, which
// keeps the session, the code challenge and the trusted-device token in httpOnly cookies.
"use client";

import { ArrowLeft, Eye, EyeOff, KeyRound, Loader2, Lock, Mail, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { httpApi, type Api, type ApiResult } from "@/lib/api";
import { errorMessage } from "@/lib/format";
import { Button, Callout, Logo } from "./ui";

const MIN_PASSWORD = 10;

export function AuthShell({ title, subtitle, children }: { title: string; subtitle: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-[radial-gradient(ellipse_at_top,_#eef2ff,_#f7f7f8_60%)] p-6">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <Logo className="size-9" />
          <div className="leading-tight">
            <div className="text-sm font-semibold text-zinc-900">Order Intelligence</div>
            <div className="text-[11px] text-zinc-500">Analytics agent · Olist</div>
          </div>
        </div>
        <div className="rounded-2xl border border-zinc-200 bg-white p-7 shadow-xl shadow-zinc-200/60">
          <h1 className="text-xl font-semibold text-zinc-900">{title}</h1>
          <p className="mt-1.5 text-sm leading-relaxed text-zinc-600">{subtitle}</p>
          <div className="mt-6">{children}</div>
        </div>
        <p className="mt-4 text-center text-xs text-zinc-500">Access is by invitation only.</p>
      </div>
    </div>
  );
}

export function Field({
  id,
  label,
  icon,
  children,
  hint,
  aside,
}: {
  id: string;
  label: string;
  icon: ReactNode;
  children: ReactNode;
  hint?: string;
  aside?: ReactNode;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <label htmlFor={id} className="block text-sm font-medium text-zinc-800">
          {label}
        </label>
        {aside}
      </div>
      <div className="relative">
        <span className="pointer-events-none absolute top-2.5 left-3 text-zinc-400">{icon}</span>
        {children}
      </div>
      {hint && <p className="mt-1 text-xs text-zinc-500">{hint}</p>}
    </div>
  );
}

export const INPUT =
  "h-10 w-full rounded-lg border border-zinc-300 pr-3 pl-9 text-sm outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100 disabled:bg-zinc-50 disabled:text-zinc-500";

export function PasswordInput({
  id,
  value,
  onChange,
  autoComplete,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <>
      <input
        id={id}
        type={show ? "text" : "password"}
        autoComplete={autoComplete}
        required
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={INPUT + " pr-10"}
      />
      <button
        type="button"
        onClick={() => setShow(!show)}
        aria-label={show ? "Hide password" : "Show password"}
        className="absolute top-2 right-2 rounded p-1 text-zinc-400 hover:text-zinc-700"
      >
        {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </>
  );
}

/** The 6-digit emailed code: digits only, the phone's number pad, one-time-code autofill. */
export function CodeField({ value, onChange, label = "6-digit code" }: { value: string; onChange: (v: string) => void; label?: string }) {
  return (
    <Field id="code" label={label} icon={<KeyRound className="size-4" />}>
      <input
        id="code"
        inputMode="numeric"
        autoComplete="one-time-code"
        autoFocus
        required
        maxLength={6}
        placeholder="000000"
        value={value}
        onChange={(e) => onChange(e.target.value.replace(/\D/g, "").slice(0, 6))}
        className={INPUT + " font-mono text-base tracking-[0.4em] placeholder:text-zinc-300"}
      />
    </Field>
  );
}

const RESEND_WAIT_S = 60;

/** "Send a new code", available a minute after the last one (the API enforces the same). */
export function ResendButton({ onResend }: { onResend: () => Promise<ApiResult<unknown>> }) {
  const [left, setLeft] = useState(RESEND_WAIT_S);
  const [note, setNote] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  useEffect(() => {
    if (left <= 0) return;
    const t = setTimeout(() => setLeft((n) => n - 1), 1000);
    return () => clearTimeout(t);
  }, [left]);
  const resend = async () => {
    setNote(null);
    const r = await onResend();
    if (r.ok) {
      setLeft(RESEND_WAIT_S);
      setNote({ tone: "ok", text: "A new code was sent. Use the newest email." });
    } else {
      setNote({ tone: "error", text: errorMessage(r.code) });
    }
  };
  return (
    <div className="text-center text-xs">
      <button
        type="button"
        onClick={resend}
        disabled={left > 0}
        className="font-medium text-brand-600 hover:text-brand-700 disabled:cursor-default disabled:text-zinc-400"
      >
        {left > 0 ? `Send a new code in ${left}s` : "Send a new code"}
      </button>
      {note && <p className={note.tone === "ok" ? "mt-1 text-emerald-700" : "mt-1 text-rose-700"}>{note.text}</p>}
    </div>
  );
}

/** In development (MAIL_MODE=console) the API prints emails in its terminal instead of sending. */
export function ConsoleNote({ mode }: { mode?: string }) {
  if (mode !== "console") return null;
  return (
    <Callout tone="info">
      Development mode: no email was sent. The code is printed in the API&apos;s terminal window.
    </Callout>
  );
}

export function SignInForm({ api = httpApi }: { api?: Api }) {
  const router = useRouter();
  const [step, setStep] = useState<"password" | "code">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [trust, setTrust] = useState(false);
  const [sent, setSent] = useState<{ hint: string; mode?: string }>({ hint: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submitPassword = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const r = await api.signIn(email, password);
    setBusy(false);
    if (!r.ok) return setError(errorMessage(r.code));
    if (r.data.code_required) {
      setSent({ hint: r.data.email_hint ?? "your email", mode: r.data.mail_mode });
      setCode("");
      setStep("code");
    } else {
      router.replace("/");
    }
  };

  const submitCode = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const r = await api.verifyCode(code, trust);
    setBusy(false);
    if (r.ok) return router.replace("/");
    if (r.code === "code_expired") {
      setStep("password");
      setPassword("");
    }
    setError(errorMessage(r.code));
  };

  if (step === "code") {
    return (
      <AuthShell title="Check your email" subtitle={<>We sent a 6-digit code to <b className="font-medium text-zinc-800">{sent.hint}</b>. It expires in 10 minutes.</>}>
        <form onSubmit={submitCode} className="space-y-4">
          <ConsoleNote mode={sent.mode} />
          <CodeField value={code} onChange={setCode} />
          <label className="flex items-center gap-2 text-sm text-zinc-700">
            <input type="checkbox" checked={trust} onChange={(e) => setTrust(e.target.checked)} className="size-4 rounded border-zinc-300 accent-brand-600" />
            Trust this device for 30 days
          </label>
          {error && <Callout tone="error">{error}</Callout>}
          <Button type="submit" variant="primary" className="w-full" disabled={busy || code.length !== 6}>
            {busy && <Loader2 className="size-4 animate-spin" />} Verify and sign in
          </Button>
          <ResendButton onResend={() => api.resendCode()} />
        </form>
        <button
          type="button"
          onClick={() => {
            setStep("password");
            setError(null);
            setPassword("");
          }}
          className="mt-5 flex w-full items-center justify-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-800"
        >
          <ArrowLeft className="size-3.5" /> Use a different account
        </button>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Sign in" subtitle="Welcome back. Sign in to ask questions about the order data.">
      <form onSubmit={submitPassword} className="space-y-4">
        <Field id="email" label="Email" icon={<Mail className="size-4" />}>
          <input id="email" type="email" autoComplete="username" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} className={INPUT} />
        </Field>
        <Field
          id="password"
          label="Password"
          icon={<Lock className="size-4" />}
          aside={
            <Link href="/forgot" className="text-xs font-medium text-brand-600 hover:text-brand-700">
              Forgot password?
            </Link>
          }
        >
          <PasswordInput id="password" value={password} onChange={setPassword} autoComplete="current-password" />
        </Field>
        {error && <Callout tone="error">{error}</Callout>}
        <Button type="submit" variant="primary" className="w-full" disabled={busy || !email || !password}>
          {busy && <Loader2 className="size-4 animate-spin" />} Sign in
        </Button>
      </form>
      <p className="mt-5 text-center text-xs text-zinc-500">No account? Ask the admin for an invite link.</p>
    </AuthShell>
  );
}

export function SignUpForm({ api = httpApi }: { api?: Api }) {
  const router = useRouter();
  const invite = useSearchParams().get("invite") ?? "";
  const [email, setEmail] = useState<string | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const check = invite ? api.inviteInfo(invite) : Promise.resolve({ ok: false as const, code: "invalid_invite", status: 404 });
    check.then((r) => {
      if (!live) return;
      if (r.ok) setEmail(r.data.email);
      else setInviteError(errorMessage(r.code));
    });
    return () => {
      live = false;
    };
  }, [api, invite]);

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD;
  const mismatch = repeat.length > 0 && repeat !== password;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (tooShort || mismatch) return;
    setBusy(true);
    setError(null);
    const r = await api.signUp(invite, name, password);
    setBusy(false);
    if (r.ok) router.replace("/");
    else setError(r.code === "weak_password" && r.message ? r.message : errorMessage(r.code));
  };

  if (inviteError) {
    return (
      <AuthShell title="Invite not valid" subtitle="This link cannot be used to create an account.">
        <Callout tone="error">{inviteError}</Callout>
        <p className="mt-4 text-sm text-zinc-600">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-brand-600 hover:text-brand-700">
            Sign in
          </Link>
        </p>
      </AuthShell>
    );
  }
  if (email === null) {
    return (
      <AuthShell title="Create your account" subtitle="Checking your invite…">
        <p className="flex items-center gap-2 text-sm text-zinc-500">
          <Loader2 className="size-4 animate-spin" /> One moment…
        </p>
      </AuthShell>
    );
  }
  return (
    <AuthShell title="Create your account" subtitle="You were invited. Choose your name and a password; only you will know it.">
      <form onSubmit={submit} className="space-y-4">
        <Field id="email" label="Email" icon={<Mail className="size-4" />} hint="Fixed by the invite.">
          <input id="email" type="email" autoComplete="username" value={email} disabled className={INPUT} />
        </Field>
        <Field id="name" label="Your name" icon={<UserRound className="size-4" />}>
          <input id="name" required maxLength={80} autoFocus autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} className={INPUT} />
        </Field>
        <Field id="password" label="Password" icon={<Lock className="size-4" />} hint={`At least ${MIN_PASSWORD} characters. A short sentence works well.`}>
          <PasswordInput id="password" value={password} onChange={setPassword} autoComplete="new-password" />
        </Field>
        <Field id="repeat" label="Repeat the password" icon={<Lock className="size-4" />}>
          <PasswordInput id="repeat" value={repeat} onChange={setRepeat} autoComplete="new-password" />
        </Field>
        {tooShort && <p className="text-xs text-amber-700">The password needs at least {MIN_PASSWORD} characters.</p>}
        {mismatch && <p className="text-xs text-amber-700">The two passwords are different.</p>}
        {error && <Callout tone="error">{error}</Callout>}
        <Button type="submit" variant="primary" className="w-full" disabled={busy || !name.trim() || !password || tooShort || mismatch || !repeat}>
          {busy && <Loader2 className="size-4 animate-spin" />} Create account
        </Button>
      </form>
    </AuthShell>
  );
}

export function ForgotPasswordForm({ api = httpApi }: { api?: Api }) {
  const [step, setStep] = useState<"email" | "code" | "done">("email");
  const [email, setEmail] = useState("");
  const [mode, setMode] = useState<string | undefined>();
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD;
  const mismatch = repeat.length > 0 && repeat !== password;

  const submitEmail = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const r = await api.forgotPassword(email);
    setBusy(false);
    if (!r.ok) return setError(errorMessage(r.code));
    setMode(r.data.mail_mode);
    setStep("code");
  };

  const submitReset = async (e: FormEvent) => {
    e.preventDefault();
    if (tooShort || mismatch) return;
    setBusy(true);
    setError(null);
    const r = await api.resetPassword(code, password);
    setBusy(false);
    if (r.ok) return setStep("done");
    if (r.code === "code_expired") setStep("email");
    setError(r.code === "weak_password" && r.message ? r.message : errorMessage(r.code));
  };

  const back = (
    <p className="mt-5 text-center text-xs text-zinc-500">
      <Link href="/login" className="inline-flex items-center gap-1.5 hover:text-zinc-800">
        <ArrowLeft className="size-3.5" /> Back to sign in
      </Link>
    </p>
  );

  if (step === "done") {
    return (
      <AuthShell title="Password changed" subtitle="Your new password is set. For safety, every device was signed out.">
        <Link
          href="/login"
          className="flex h-9 w-full items-center justify-center rounded-lg bg-brand-600 text-sm font-medium text-white shadow-sm hover:bg-brand-700"
        >
          Sign in
        </Link>
      </AuthShell>
    );
  }

  if (step === "code") {
    return (
      <AuthShell title="Check your email" subtitle={<>If an account uses <b className="font-medium text-zinc-800">{email}</b>, we sent it a 6-digit code. It expires in 10 minutes.</>}>
        <form onSubmit={submitReset} className="space-y-4">
          <ConsoleNote mode={mode} />
          <CodeField value={code} onChange={setCode} />
          <Field id="new-password" label="New password" icon={<Lock className="size-4" />} hint={`At least ${MIN_PASSWORD} characters. A short sentence works well.`}>
            <PasswordInput id="new-password" value={password} onChange={setPassword} autoComplete="new-password" />
          </Field>
          <Field id="repeat-password" label="Repeat the new password" icon={<Lock className="size-4" />}>
            <PasswordInput id="repeat-password" value={repeat} onChange={setRepeat} autoComplete="new-password" />
          </Field>
          {tooShort && <p className="text-xs text-amber-700">The password needs at least {MIN_PASSWORD} characters.</p>}
          {mismatch && <p className="text-xs text-amber-700">The two passwords are different.</p>}
          {error && <Callout tone="error">{error}</Callout>}
          <Button type="submit" variant="primary" className="w-full" disabled={busy || code.length !== 6 || !password || !repeat || tooShort || mismatch}>
            {busy && <Loader2 className="size-4 animate-spin" />} Set new password
          </Button>
          <ResendButton onResend={() => api.resendResetCode()} />
        </form>
        {back}
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Forgot your password?" subtitle="Enter the email you sign in with. We will email you a 6-digit code to set a new password.">
      <form onSubmit={submitEmail} className="space-y-4">
        <Field id="email" label="Email" icon={<Mail className="size-4" />}>
          <input id="email" type="email" autoComplete="username" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} className={INPUT} />
        </Field>
        {error && <Callout tone="error">{error}</Callout>}
        <Button type="submit" variant="primary" className="w-full" disabled={busy || !email}>
          {busy && <Loader2 className="size-4 animate-spin" />} Email me a code
        </Button>
      </form>
      {back}
    </AuthShell>
  );
}
