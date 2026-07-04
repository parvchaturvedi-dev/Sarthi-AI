"use client";
import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, setSession } from "@/lib/api";
import GoogleButton from "../components/GoogleButton";

export default function Register() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      const d = await api("/api/auth/register", { method: "POST", body: JSON.stringify({ name, email, password: pw }) });
      setSession(d.token, d.user);
      router.push("/");
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  const google = useCallback(async (credential) => {
    setErr("");
    try {
      const d = await api("/api/auth/google", { method: "POST", body: JSON.stringify({ credential }) });
      setSession(d.token, d.user);
      router.push("/");
    } catch (e) { setErr(e.message); }
  }, [router]);

  return (
    <div className="min-h-screen grid place-items-center bg-gradient-to-b from-[#fafcff] to-white px-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-3 justify-center mb-6">
          <img src="/logo.png" alt="Sarthi" className="w-9 h-9 rounded-lg object-contain" />
          <span className="text-2xl font-extrabold tracking-tight">Sarthi</span>
        </div>
        <div className="bg-white border border-line rounded-2xl shadow-soft p-7">
          <h1 className="text-xl font-extrabold mb-1">Create your account</h1>
          <p className="text-sm text-muted mb-6">Get started with Sarthi</p>

          <GoogleButton onCredential={google} />

          <div className="flex items-center gap-3 my-5 text-xs text-muted">
            <div className="h-px bg-line flex-1" /> or <div className="h-px bg-line flex-1" />
          </div>

          <form onSubmit={submit} className="space-y-3">
            <input required placeholder="Full name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)}
              className="w-full px-4 py-3 rounded-xl border border-line bg-[#f6f7fa] outline-none focus:border-accent text-[15px]" />
            <input type="email" required placeholder="Email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)}
              className="w-full px-4 py-3 rounded-xl border border-line bg-[#f6f7fa] outline-none focus:border-accent text-[15px]" />
            <input type="password" required minLength={6} placeholder="Password (min 6 chars)" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)}
              className="w-full px-4 py-3 rounded-xl border border-line bg-[#f6f7fa] outline-none focus:border-accent text-[15px]" />
            {err && <div className="text-sm text-red-500">{err}</div>}
            <button disabled={busy}
              className="w-full py-3 rounded-xl font-bold text-white bg-gradient-to-br from-accent to-[#2a6fd0] shadow-soft disabled:opacity-60">
              {busy ? "Creating…" : "Create account"}
            </button>
          </form>

          <p className="text-sm text-muted text-center mt-5">
            Already have an account? <Link href="/login" className="text-accent font-semibold">Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
