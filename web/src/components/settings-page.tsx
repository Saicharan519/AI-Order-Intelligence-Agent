// Your account: change your name; change your email (your current password, then the code
// emailed to the new address); change your password (other devices are signed out).
"use client";

import { ArrowLeft, KeyRound, Loader2, Lock, Mail, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { httpApi, type Api } from "@/lib/api";
import { errorMessage } from "@/lib/format";
import type { UserInfo } from "@/lib/types";
import { CodeField, ConsoleNote, Field, INPUT, PasswordInput, ResendButton } from "./auth-forms";
import { Button, Callout, Card, Logo } from "./ui";

const MIN_PASSWORD = 10;

function Section({ icon, title, text, children }: { icon: ReactNode; title: string; text: string; children: ReactNode }) {
  return (
    <Card className="p-6">
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">{icon}</span>
        <div>
          <h2 className="text-base font-semibold text-zinc-900">{title}</h2>
          <p className="mt-0.5 text-sm text-zinc-600">{text}</p>
        </div>
      </div>
      <div className="mt-5">{children}</div>
    </Card>
  );
}

// A server message is shown only for a weak password (it says what to change).
const messageOf = (r: { code: string; message?: string }) =>
  r.code === "weak_password" && r.message ? r.message : errorMessage(r.code);

function ProfileForm({ api, me, onSaved }: { api: Api; me: UserInfo; onSaved: (u: UserInfo) => void }) {
  const [name, setName] = useState(me.name);
  const [email, setEmail] = useState(me.email ?? "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [pending, setPending] = useState<{ email: string; mode?: string } | null>(null);
  const [code, setCode] = useState("");

  const emailChanged = email.trim().toLowerCase() !== (me.email ?? "");
  const changed = emailChanged || name.trim() !== me.name;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    const r = await api.updateProfile(name.trim(), email.trim(), emailChanged ? password : "");
    setBusy(false);
    if (!r.ok) {
      setError(messageOf(r));
      return;
    }
    setPassword("");
    setName(r.data.name);
    onSaved({ id: r.data.id, email: r.data.email, name: r.data.name, role: r.data.role });
    if (r.data.pending_email) {
      setCode("");
      setPending({ email: r.data.pending_email, mode: r.data.mail_mode });
    } else {
      setEmail(r.data.email ?? "");
      setSaved(true);
    }
  };

  const confirm = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const r = await api.confirmEmail(code);
    setBusy(false);
    if (!r.ok) {
      setError(errorMessage(r.code));
      return;
    }
    setPending(null);
    setEmail(r.data.email ?? "");
    setSaved(true);
    onSaved(r.data);
  };

  if (pending) {
    return (
      <form onSubmit={confirm} className="space-y-4">
        <p className="text-sm text-zinc-700">
          We sent a 6-digit code to <b className="font-medium text-zinc-900">{pending.email}</b>. Enter it to start using
          this address; until then you keep signing in with {me.email}.
        </p>
        <ConsoleNote mode={pending.mode} />
        <CodeField value={code} onChange={setCode} label="Code from the new email" />
        {error && <Callout tone="error">{error}</Callout>}
        <div className="flex items-center gap-2">
          <Button type="submit" variant="primary" disabled={busy || code.length !== 6}>
            {busy && <Loader2 className="size-4 animate-spin" />} Confirm new email
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setPending(null);
              setError(null);
              setEmail(me.email ?? "");
            }}
          >
            Cancel
          </Button>
        </div>
        <ResendButton onResend={() => api.resendEmailCode()} />
      </form>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field id="name" label="Name" icon={<UserRound className="size-4" />}>
        <input id="name" required maxLength={80} autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} className={INPUT} />
      </Field>
      <Field id="email" label="Email" icon={<Mail className="size-4" />} hint="You sign in with this address.">
        <input id="email" type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} className={INPUT} />
      </Field>
      {emailChanged && (
        <div className="animate-fade-in">
          <Field id="profile-password" label="Current password" icon={<Lock className="size-4" />} hint="Needed to change the email you sign in with. We then email a code to the new address.">
            <PasswordInput id="profile-password" value={password} onChange={setPassword} autoComplete="current-password" />
          </Field>
        </div>
      )}
      {error && <Callout tone="error">{error}</Callout>}
      {saved && !changed && <Callout tone="success">Saved.</Callout>}
      <Button type="submit" variant="primary" disabled={busy || !changed || !name.trim() || !email.trim() || (emailChanged && !password)}>
        {busy && <Loader2 className="size-4 animate-spin" />} Save changes
      </Button>
    </form>
  );
}

function PasswordForm({ api }: { api: Api }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const tooShort = next.length > 0 && next.length < MIN_PASSWORD;
  const mismatch = repeat.length > 0 && repeat !== next;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (tooShort || mismatch) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    const r = await api.changePassword(current, next);
    setBusy(false);
    if (!r.ok) {
      setError(messageOf(r));
      return;
    }
    setCurrent("");
    setNext("");
    setRepeat("");
    setSaved(true);
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field id="current-password" label="Current password" icon={<Lock className="size-4" />}>
        <PasswordInput id="current-password" value={current} onChange={setCurrent} autoComplete="current-password" />
      </Field>
      <Field id="new-password" label="New password" icon={<Lock className="size-4" />} hint={`At least ${MIN_PASSWORD} characters. A short sentence works well.`}>
        <PasswordInput id="new-password" value={next} onChange={setNext} autoComplete="new-password" />
      </Field>
      <Field id="repeat-password" label="Repeat the new password" icon={<Lock className="size-4" />}>
        <PasswordInput id="repeat-password" value={repeat} onChange={setRepeat} autoComplete="new-password" />
      </Field>
      {tooShort && <p className="text-xs text-amber-700">The new password needs at least {MIN_PASSWORD} characters.</p>}
      {mismatch && <p className="text-xs text-amber-700">The two new passwords are different.</p>}
      {error && <Callout tone="error">{error}</Callout>}
      {saved && <Callout tone="success">Password changed. Your other devices were signed out; this one stays signed in.</Callout>}
      <Button type="submit" variant="primary" disabled={busy || !current || !next || !repeat || tooShort || mismatch}>
        {busy && <Loader2 className="size-4 animate-spin" />} Change password
      </Button>
    </form>
  );
}

export function SettingsPage({ api = httpApi }: { api?: Api }) {
  const router = useRouter();
  const [me, setMe] = useState<UserInfo | null>(null);
  const [operator, setOperator] = useState(false);

  useEffect(() => {
    let live = true;
    api.me().then((r) => {
      if (!live) return;
      if (!r.ok) router.replace("/login");
      else if (r.data.role === "operator") setOperator(true);
      else setMe(r.data);
    });
    return () => {
      live = false;
    };
  }, [api, router]);

  return (
    <div className="min-h-dvh bg-[#f7f7f8]">
      <header className="flex h-14 items-center gap-3 border-b border-zinc-200 bg-white px-6">
        <Logo className="size-6" />
        <span className="text-sm font-semibold text-zinc-900">Account settings</span>
        <Link href="/" className="ml-auto flex items-center gap-1.5 text-sm text-zinc-600 hover:text-zinc-900">
          <ArrowLeft className="size-4" /> Workspace
        </Link>
      </header>

      <main className="mx-auto max-w-xl space-y-6 px-6 py-8">
        {operator ? (
          <Callout tone="info">The operator key has no account to change. Sign in with your own account.</Callout>
        ) : me === null ? (
          <p className="flex items-center gap-2 text-sm text-zinc-500">
            <Loader2 className="size-4 animate-spin" /> Loading…
          </p>
        ) : (
          <>
            <Section icon={<UserRound className="size-4.5" />} title="Profile" text="Your name is shown in the sidebar and to the admin.">
              <ProfileForm api={api} me={me} onSaved={setMe} />
            </Section>
            <Section icon={<KeyRound className="size-4.5" />} title="Password" text="Only you know it: it is stored as a one-way hash, never in plain text.">
              <PasswordForm api={api} />
            </Section>
          </>
        )}
      </main>
    </div>
  );
}
