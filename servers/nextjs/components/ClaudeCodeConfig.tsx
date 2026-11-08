"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getApiErrorMessage, getApiUrl } from "@/utils/api";
import { DEFAULT_CLAUDE_CODE_MODEL } from "@/utils/claudeCode";

export default function ClaudeCodeConfig({ model, onModelChange, showModel = true }: {
  model: string;
  onModelChange: (model: string) => void;
  showModel?: boolean;
}) {
  const [linked, setLinked] = useState(false);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [session, setSession] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetch(getApiUrl("/api/v1/ppt/anthropic/auth/status"), { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(await getApiErrorMessage(response, "Could not check Claude Code connection."));
        const data = await response.json();
        if (active) setLinked(data.status === "authenticated");
      })
      .catch((failure) => { if (active) setError(failure.message); })
      .finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, []);

  const request = async (action: string, body?: object) => {
    const response = await fetch(getApiUrl(`/api/v1/ppt/anthropic/auth/${action}`), {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) throw new Error(await getApiErrorMessage(response, "Claude Code request failed. Start a new sign-in and try again."));
    return response.json();
  };

  const perform = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try { await action(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Please try again."); }
    finally { setBusy(false); }
  };

  return (
    <section className="space-y-4" aria-label="Claude Code connection" aria-busy={checking || busy}>
      <div>
        <h4 className="text-base font-medium text-gray-900">Claude Code</h4>
        <p className="mt-1 text-sm text-gray-600">Your connection belongs to your Presenton account. It is not shared with other users.</p>
      </div>
      {checking ? <p role="status" className="text-sm text-gray-600">Checking connection…</p> : linked ? (
        <div className="flex flex-wrap items-center gap-3">
          <p role="status" className="text-sm font-medium text-green-800">Account linked</p>
          <Button variant="outline" disabled={busy} onClick={() => perform(async () => {
            await request("logout"); setLinked(false); setCode(""); setSession(null);
          })}>Disconnect</Button>
        </div>
      ) : (
        <Button disabled={busy} onClick={() => perform(async () => {
          const data = await request("initiate");
          setSession(data.session_id); setUrl(data.url); setCode("");
          window.open(data.url, "_blank", "noopener,noreferrer");
        })}>{busy ? "Please wait…" : session ? "Start a new sign-in" : "Sign in with Claude Code"}</Button>
      )}
      {session && !linked && (
        <div className="space-y-2">
          <a href={url} target="_blank" rel="noopener noreferrer" className="text-sm text-violet-700 underline underline-offset-4">Open Claude sign-in page</a>
          <label className="block text-sm font-medium text-gray-900" htmlFor="claude-auth-code">Authentication code</label>
          <Input id="claude-auth-code" type="password" autoComplete="off" value={code} onChange={(event) => setCode(event.target.value)} />
          <p className="text-sm text-gray-600">Copy the complete code from Claude, including the part after #.</p>
          <Button disabled={busy || !code.trim()} onClick={() => perform(async () => {
            await request("exchange", { session_id: session, code: code.trim() });
            setLinked(true); setSession(null); setCode("");
            if (!model) onModelChange(DEFAULT_CLAUDE_CODE_MODEL);
          })}>{busy ? "Connecting…" : "Connect"}</Button>
        </div>
      )}
      {showModel && <div className="space-y-2">
        <label htmlFor="claude-code-model" className="block text-sm font-medium text-gray-900">Claude model ID</label>
        <Input id="claude-code-model" value={model} placeholder={DEFAULT_CLAUDE_CODE_MODEL} onChange={(event) => onModelChange(event.target.value)} />
        <p className="text-sm text-gray-600">Choose a model available to your Claude account. No Anthropic API key is required.</p>
      </div>}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    </section>
  );
}
