// Sign-in and create-account forms. The password goes to this app's own server, which
// passes it to the API once and keeps only the returned session in an httpOnly cookie.
"use client";

import { Eye, EyeOff, Loader2, Lock, Mail, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { httpApi, type Api } from "@/lib/api";
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

function Field({
  id,
  label,
  icon,
  children,
  hint,
}: {
  id: string;
  label: string;
  icon: ReactNode;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-zinc-800">
        {label}
      </label>
      <div className="relative">
        <span className="pointer-events-none absolute top-2.5 left-3 text-zinc-400">{icon}</span>
        {children}
      </div>
      {hint && <p className="mt-1 text-xs text-zinc-500">{hint}</p>}
    </div>
  );
}

const INPUT =
  "h-10 w-full rounded-lg border border-zinc-300 pr-3 pl-9 text-sm outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100 disabled:bg-zinc-50 disabled:text-zinc-500";

function PasswordInput({
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

export function SignInForm({ api = httpApi }: { api?: Api }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const r = await api.signIn(email, password);
    setBusy(false);
    if (r.ok) router.replace("/");
    else setError(errorMessage(r.code));
  };

  return (
    <AuthShell title="Sign in" subtitle="Welcome back. Sign in to ask questions about the order data.">
      <form onSubmit={submit} className="space-y-4">
        <Field id="email" label="Email" icon={<Mail className="size-4" />}>
          <input id="email" type="email" autoComplete="username" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} className={INPUT} />
        </Field>
        <Field id="password" label="Password" icon={<Lock className="size-4" />}>
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
