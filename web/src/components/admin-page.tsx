// Admin: invite people (one-time links), see accounts with their spend, disable or enable
// accounts, and revoke unused invites. Only admins get data from these endpoints; anyone
// else sees a short message.
"use client";

import clsx from "clsx";
import { ArrowLeft, Check, Copy, Link2, Loader2, Mail, ShieldAlert, UserPlus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { httpApi, type Api } from "@/lib/api";
import { errorMessage } from "@/lib/format";
import type { AdminInvite, AdminUser, UserInfo } from "@/lib/types";
import { Badge, Button, Callout, Card, Logo, SectionTitle } from "./ui";

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";

const STATUS_TONE = { pending: "brand", used: "good", revoked: "neutral", expired: "warn" } as const;

function CopyLink({ link }: { link: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      size="sm"
      variant="primary"
      onClick={async () => {
        await navigator.clipboard?.writeText(link);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />} {copied ? "Copied" : "Copy link"}
    </Button>
  );
}

export function AdminPage({ api = httpApi }: { api?: Api }) {
  const router = useRouter();
  const [me, setMe] = useState<UserInfo | null>(null);
  const [denied, setDenied] = useState(false);
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [cap, setCap] = useState<number | null>(null);
  const [invites, setInvites] = useState<AdminInvite[] | null>(null);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ email: string; link: string } | null>(null);

  const load = useCallback(async () => {
    const [u, i] = await Promise.all([api.adminUsers(), api.adminInvites()]);
    if (u.ok) {
      setUsers(u.data.users);
      setCap(u.data.user_daily_cap_usd);
    }
    if (i.ok) setInvites(i.data.invites);
  }, [api]);

  useEffect(() => {
    api.me().then((r) => {
      if (!r.ok) {
        if (r.status === 401) router.replace("/login");
        return;
      }
      setMe(r.data);
      if (r.data.role !== "admin") setDenied(true);
      else load();
    });
  }, [api, router, load]);

  const invite = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setCreated(null);
    const r = await api.createInvite(email);
    setBusy(false);
    if (!r.ok) {
      setError(errorMessage(r.code));
      return;
    }
    setCreated({ email: r.data.invite.email, link: `${window.location.origin}/signup?invite=${r.data.code}` });
    setEmail("");
    load();
  };

  const toggle = async (u: AdminUser) => {
    const r = await api.setUserDisabled(u.id, !u.disabled);
    if (!r.ok) setError(errorMessage(r.code));
    load();
  };

  const revoke = async (i: AdminInvite) => {
    await api.revokeInvite(i.id);
    load();
  };

  if (denied) {
    return (
      <div className="flex min-h-dvh items-center justify-center p-6">
        <Card className="max-w-sm p-7 text-center">
          <ShieldAlert className="mx-auto size-8 text-zinc-400" />
          <h1 className="mt-3 text-lg font-semibold text-zinc-900">Admins only</h1>
          <p className="mt-1 text-sm text-zinc-600">This page is for the workspace admin.</p>
          <Link href="/" className="mt-4 inline-block text-sm font-medium text-brand-600 hover:text-brand-700">
            Back to the workspace
          </Link>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-dvh bg-[#f7f7f8]">
      <header className="flex h-14 items-center gap-3 border-b border-zinc-200 bg-white px-6">
        <Logo className="size-6" />
        <span className="text-sm font-semibold text-zinc-900">Admin</span>
        <Link href="/" className="ml-auto flex items-center gap-1.5 text-sm text-zinc-600 hover:text-zinc-900">
          <ArrowLeft className="size-4" /> Workspace
        </Link>
      </header>

      <main className="mx-auto max-w-5xl space-y-8 px-6 py-8">
        {me === null ? (
          <p className="flex items-center gap-2 text-sm text-zinc-500">
            <Loader2 className="size-4 animate-spin" /> Loading…
          </p>
        ) : (
          <>
            <Card className="p-6">
              <div className="flex items-start gap-3">
                <span className="flex size-9 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                  <UserPlus className="size-4.5" />
                </span>
                <div>
                  <h2 className="text-base font-semibold text-zinc-900">Invite someone</h2>
                  <p className="mt-0.5 text-sm text-zinc-600">
                    You get a one-time link to send them yourself. They choose their own name and password. The link works once
                    and expires after 7 days.
                  </p>
                </div>
              </div>
              <form onSubmit={invite} className="mt-4 flex flex-wrap gap-2">
                <label htmlFor="invite-email" className="sr-only">Email to invite</label>
                <div className="relative min-w-64 flex-1">
                  <Mail className="pointer-events-none absolute top-2.5 left-3 size-4 text-zinc-400" />
                  <input
                    id="invite-email"
                    type="email"
                    required
                    placeholder="friend@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="h-10 w-full rounded-lg border border-zinc-300 pr-3 pl-9 text-sm outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100"
                  />
                </div>
                <Button type="submit" variant="primary" className="h-10" disabled={busy || !email}>
                  {busy ? <Loader2 className="size-4 animate-spin" /> : <Link2 className="size-4" />} Create invite link
                </Button>
              </form>
              {error && (
                <div className="mt-3">
                  <Callout tone="error">{error}</Callout>
                </div>
              )}
              {created && (
                <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-4">
                  <p className="text-sm font-medium text-emerald-900">Invite link for {created.email}</p>
                  <p className="mt-0.5 text-xs text-emerald-800">
                    Copy it now and send it to them: for safety it is shown only once.
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <code aria-label="Invite link" className="min-w-0 flex-1 truncate rounded-md bg-white px-2.5 py-1.5 font-mono text-xs text-zinc-800 ring-1 ring-emerald-200">
                      {created.link}
                    </code>
                    <CopyLink link={created.link} />
                  </div>
                </div>
              )}
            </Card>

            <section>
              <SectionTitle aside={cap !== null && <span className="text-xs text-zinc-500">Each user can spend ${cap.toFixed(2)} a day</span>}>
                Users
              </SectionTitle>
              <Card className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-zinc-50 text-xs text-zinc-600">
                    <tr>
                      <th className="px-4 py-2.5 text-left font-semibold">User</th>
                      <th className="px-4 py-2.5 text-left font-semibold">Role</th>
                      <th className="px-4 py-2.5 text-right font-semibold">Questions</th>
                      <th className="px-4 py-2.5 text-right font-semibold">Spent today</th>
                      <th className="px-4 py-2.5 text-right font-semibold">Spent in total</th>
                      <th className="px-4 py-2.5 text-left font-semibold">Last sign-in</th>
                      <th className="px-4 py-2.5" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100">
                    {(users ?? []).map((u) => (
                      <tr key={u.id} className={clsx(u.disabled && "opacity-60")}>
                        <td className="px-4 py-2.5">
                          <div className="font-medium text-zinc-900">{u.name}</div>
                          <div className="text-xs text-zinc-500">{u.email}</div>
                        </td>
                        <td className="px-4 py-2.5">
                          {u.disabled ? <Badge tone="bad">Disabled</Badge> : <Badge tone={u.role === "admin" ? "brand" : "neutral"}>{u.role === "admin" ? "Admin" : "User"}</Badge>}
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums">{u.questions}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums">${u.today_usd.toFixed(4)}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums">${u.total_usd.toFixed(4)}</td>
                        <td className="px-4 py-2.5 text-zinc-600">{when(u.last_login_at)}</td>
                        <td className="px-4 py-2.5 text-right">
                          {u.id !== me.id && (
                            <Button size="sm" variant={u.disabled ? "secondary" : "ghost"} onClick={() => toggle(u)}>
                              {u.disabled ? "Enable" : "Disable"}
                            </Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {users === null && <p className="px-4 py-3 text-sm text-zinc-500">Loading…</p>}
              </Card>
            </section>

            <section>
              <SectionTitle>Invites</SectionTitle>
              <Card className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-zinc-50 text-xs text-zinc-600">
                    <tr>
                      <th className="px-4 py-2.5 text-left font-semibold">Email</th>
                      <th className="px-4 py-2.5 text-left font-semibold">Status</th>
                      <th className="px-4 py-2.5 text-left font-semibold">Created</th>
                      <th className="px-4 py-2.5 text-left font-semibold">Expires</th>
                      <th className="px-4 py-2.5" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100">
                    {(invites ?? []).map((i) => (
                      <tr key={i.id}>
                        <td className="px-4 py-2.5 text-zinc-900">{i.email}</td>
                        <td className="px-4 py-2.5">
                          <Badge tone={STATUS_TONE[i.status]}>{i.status[0].toUpperCase() + i.status.slice(1)}</Badge>
                        </td>
                        <td className="px-4 py-2.5 text-zinc-600">{when(i.created_at)}</td>
                        <td className="px-4 py-2.5 text-zinc-600">{when(i.expires_at)}</td>
                        <td className="px-4 py-2.5 text-right">
                          {i.status === "pending" && (
                            <Button size="sm" variant="ghost" onClick={() => revoke(i)}>
                              Revoke
                            </Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {invites?.length === 0 && <p className="px-4 py-3 text-sm text-zinc-500">No invites yet.</p>}
              </Card>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
