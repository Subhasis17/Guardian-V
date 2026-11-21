import { ProfilePanel } from "./components/ProfilePanel";
import { AuthPages } from "./components/AuthPages";
import { PendingApprovals } from "./components/PendingApprovals";
import { useVoice } from "./hooks/useVoice";
import { useEffect, useRef, useState, type FormEvent } from "react";

import type { Action, Incident, Run, Context } from "./types";
const API = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

export default function App() {
  const [token, setToken] = useState("");
  const [showProfile, setShowProfile] = useState(true);
  const [google, setGoogle] = useState<{connected: boolean; trusted_contact_email: string} | null>(null);
  const [contactEmail, setContactEmail] = useState("");
  const [context, setContext] = useState<Context | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [summary, setSummary] = useState("");
  const [transactionType, setTransactionType] = useState("unknown");
  const [bankReceivedOn, setBankReceivedOn] = useState("");
  const [shadowDueOn, setShadowDueOn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const incidentRequest = useRef<{ summary: string; key: string } | null>(null);
  async function request<T>(
    path: string,
    options: RequestInit = {},
  ): Promise<T> {
    const destination = new URL(API, window.location.origin);
    if (destination.protocol !== 'https:' && !['localhost', '127.0.0.1', '[::1]'].includes(destination.hostname)) {
      throw new Error('Guardian requires an HTTPS API connection to protect your information.');
    }
    const response = await fetch(`${API}${path}`, {
      ...options,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": token,
        ...options.headers,
      },
    });
    if (!response.ok) {
      if (response.status === 401) { setToken(""); setContext(null); setRun(null); }
      const body = await response.text();
      let detail = `Request failed (${response.status})`;
      let code: string | undefined;
      try {
        const data = JSON.parse(body).detail;
        detail = typeof data === 'string' ? data : data?.message ?? detail;
        code = typeof data === 'object' ? data?.code : undefined;
      } catch { /* Proxies may return HTML or an empty body. */ }
      throw Object.assign(new Error(detail), {status: response.status, code});
    }
    return response.json();
  }

  const {
    voiceStatus,
    voiceConfig,
    voiceProfileId,
    setVoiceProfileId,
    voiceSession,
    startVoice,
    stopVoice,
  } = useVoice({ token, request, setBusy, setError });

  async function loadContext() {
    if (!token) return;
    try {
      setContext(await request<Context>("/api/context"));
      setError("");
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not load Guardian data.",
      );
    }
  }

  useEffect(() => {
    void loadContext();
  }, [token]);

  useEffect(() => {
    if (!token) { setGoogle(null); return; }
    void request<{connected: boolean; trusted_contact_email: string}>("/api/integrations/google/status")
      .then(status => { setGoogle(status); setContactEmail(status.trusted_contact_email); })
      .catch(e => setError(e instanceof Error ? e.message : "Could not load Google status."));
  }, [token]);

  async function saveContact() {
    try {
      await request("/api/integrations/google/contact", {method: "POST", body: JSON.stringify({email: contactEmail})});
      setGoogle(current => current ? {...current, trusted_contact_email: contactEmail} : current);
      setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save contact."); }
  }

  async function disconnectGoogle() {
    try {
      await request("/api/integrations/google/disconnect", {method: "POST"});
      setGoogle(current => current ? {...current, connected: false} : current);
      setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not disconnect Google."); }
  }

  useEffect(() => {
    if (!token) return;
    const timer = window.setInterval(() => void loadContext(), 5000);
    return () => window.clearInterval(timer);
  }, [token]);

  useEffect(() => {
    sessionStorage.removeItem("guardian-token");
    void request<{csrf_token: string}>("/api/auth/session").then(session => setToken(session.csrf_token)).catch(() => undefined);
  }, []);

  async function startIncident(event: FormEvent) {
    event.preventDefault();
    const facts = {summary, transaction_type: transactionType, bank_complaint_received_on: bankReceivedOn || null, bank_shadow_reversal_due_on: transactionType === "unauthorised" ? shadowDueOn || null : null};
    const fingerprint = JSON.stringify(facts);
    if (incidentRequest.current?.summary !== fingerprint) incidentRequest.current = { summary: fingerprint, key: crypto.randomUUID() };
    setBusy(true);
    setError("");
    try {
      setRun(
        await request<Run>("/api/incidents", {
          method: "POST",
          body: JSON.stringify({ ...facts, idempotency_key: incidentRequest.current.key }),
        }),
      );
      setSummary("");
      incidentRequest.current = null;
      await loadContext();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not start the incident.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function decide(action: Action, approved: boolean) {
    const incidentId = action.incident_id ?? run?.incident.id;
    if (!incidentId) return;
    setBusy(true);
    setError("");
    try {
      setRun(
        await request<Run>(
          `/api/incidents/${incidentId}/actions/${action.id}/approval`,
          { method: "POST", body: JSON.stringify({ approved }) },
        ),
      );
      await loadContext();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not record your decision.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function reopen(incident: Incident) {
    setBusy(true);
    setError("");
    try {
      setRun(await request<Run>(`/api/incidents/${incident.id}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not open incident.");
    } finally {
      setBusy(false);
    }
  }

  async function downloadReport() {
    if (!run) return;
    try {
      const report = await request<{ filename: string; content: string }>(
        `/api/incidents/${run.incident.id}/report`,
      );
      const link = document.createElement("a");
      link.href = URL.createObjectURL(
        new Blob([report.content], { type: "text/markdown" }),
      );
      link.download = report.filename;
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not generate the report.",
      );
    }
  }

  const money = (amount: number) =>
    new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amount);
  const when = (value: string) =>
    new Date(value).toLocaleString([], {
      dateStyle: "medium",
      timeStyle: "short",
    });

  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="#home">
          <span className="brand-mark">G</span> guardian
        </a>
        <span className="sandbox">
          <i /> DEMO SANDBOX
        </span>
        {token && <button className="profile" aria-label="Toggle profile" aria-expanded={showProfile} aria-controls="account-profile" onClick={() => setShowProfile(value => !value)}>Profile</button>}
      </header>
      <section className="welcome">
        <div>
          <p className="eyebrow">YOUR SAFETY, IN ONE PLACE</p>
          <h1>Let's take the next step together.</h1>
          <p className="subhead">
            If something feels wrong, we’ll work through it together.
          </p>
        </div>
        <span className="date">INCIDENT RESPONSE</span>
      </section>

      {!token && <AuthPages request={request} onSignedIn={csrf => {setToken(csrf); setError("");}} />}

      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}

      {token && Boolean(context?.pending_approvals?.length) && (
        <PendingApprovals
          approvals={context!.pending_approvals}
          busy={busy}
          decide={decide}
        />
      )}

      {token && (
        <>
          {showProfile && <ProfilePanel request={request} />}
          {context?.bank_available === false && <p role="status">Sandbox bank unavailable. Account state and transactions cannot be verified. Your saved incidents and approvals remain available.</p>}
          <section className="panel google-panel">
            <h2>Google email and calendar</h2>
            <p>{google?.connected ? "Connected to your Google account." : "Connect your Google account to send approved notifications and create follow-ups."}</p>
            {!google?.connected && <a className="google-connect" href={`${API}/api/integrations/google/connect`}><span className="google-mark" aria-hidden="true">G</span>Connect Google</a>}
            {google?.connected && <button className="secondary" type="button" onClick={() => void disconnectGoogle()}>Disconnect Google</button>}
            <div className="auth-row">
              <input type="email" aria-label="Trusted contact email" placeholder="Trusted contact email" value={contactEmail} onChange={e => setContactEmail(e.target.value)} />
              <button className="primary" type="button" onClick={() => void saveContact()} disabled={!contactEmail || contactEmail === google?.trusted_contact_email}>Save contact</button>
            </div>
            <small>Approved emails go to this contact. Follow-ups appear in your connected Google Calendar.</small>
          </section>
          <section className="voice-card">
            <div className="voice-copy">
              <span className="live-label">
                <i /> {voiceStatus.toUpperCase()}
              </span>
              <h2>Talk it through.</h2>
              <p>
                Speak with Guardian or write a short description below.
              </p>
              <div className="voice-controls">
                <label>
                  Conversation voice and language
                  <select
                    value={voiceProfileId}
                    disabled={
                      busy || Boolean(voiceSession.current) || !voiceConfig
                    }
                    onChange={(event) => setVoiceProfileId(event.target.value)}
                  >
                    {voiceConfig?.profiles.map((profile) => (
                      <option key={profile.id} value={profile.id}>
                        {profile.label}
                      </option>
                    ))}
                  </select>
                </label>
                {voiceSession.current ? (
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() => void stopVoice()}
                  >
                    End voice session
                  </button>
                ) : (
                  <button
                    className="start-button"
                    disabled={busy || !voiceConfig}
                    onClick={() => void startVoice()}
                  >
                    ◉ Start voice conversation
                  </button>
                )}
              </div>
              <p className="voice-caption">
                Guardian starts in English. Choose a voice and language before your call.
              </p>
              <form onSubmit={startIncident}>
                <fieldset className="followup-fields">
                  <legend>Bank complaint details for follow-up dates (optional)</legend>
                  <label>Transaction type<select value={transactionType} onChange={e => setTransactionType(e.target.value)}><option value="unknown">Not yet confirmed</option><option value="unauthorised">I did not authorise the transaction</option><option value="authorised">I authorised the transfer</option></select></label>
                  <label>Date the bank received your complaint<input type="date" value={bankReceivedOn} onChange={e => setBankReceivedOn(e.target.value)} /></label>
                  {transactionType === "unauthorised" && <label>Shadow reversal due date confirmed by bank<input type="date" value={shadowDueOn} onChange={e => setShadowDueOn(e.target.value)} /><small>Optional. Confirm the 10-working-day date with your bank; holidays vary.</small></label>}
                  <small>Report suspected fraud immediately. Guardian cannot report to a real bank or guarantee a refund. Without a receipt date, only general check-ins are scheduled.</small>
                </fieldset>
                <textarea
                  required
                  minLength={10}
                  maxLength={2000}
                  value={summary}
                  onChange={(e) => setSummary(e.target.value)}
                  placeholder="Example: Someone claiming to be a police officer threatened me and asked me to transfer ₹35,000. I may have shared banking details."
                />
                <button
                  className="start-button"
                  disabled={busy || summary.trim().length < 10}
                >
                  {busy ? "Working…" : "Review my situation →"}
                </button>
              </form>
              <small>
                No PINs or OTPs. Banking actions here are synthetic sandbox
                actions only.
              </small>
            </div>
            <div className="voice-art" aria-hidden="true">
              <div className="orbit orbit-one" />
              <div className="orbit orbit-two" />
              <div className="guardian-seal">G</div>
              <div className="wave">
                <b />
                <b />
                <b />
                <b />
                <b />
                <b />
                <b />
                <b />
                <b />
                <b />
                <b />
              </div>
            </div>
          </section>

          {run && (
            <section className="panel run-panel">
              <div className="run-heading">
                <div>
                  <p className="eyebrow">INCIDENT PLAN · SANDBOX</p>
                  <h2>Here’s what we can do.</h2>
                  <p className="run-summary">{run.incident.summary}</p>
                  {run.assessment && <p>Priority: {run.assessment.severity.replaceAll("_", " ")}. Confirm the transaction and exposed information with Guardian before deciding.</p>}
                  <button
                    className="report-button"
                    onClick={() => void downloadReport()}
                  >
                    Download incident report
                  </button>
                </div>
                <span className={`state ${run.incident.status}`}>
                  {run.incident.status.replaceAll("_", " ")}
                </span>
              </div>
              <div className="steps">
                {Boolean(run.followups?.length) && <section className="followup-series"><h3>Follow-up schedule</h3>{run.followups!.map(item => <article key={item.id}><h4>{item.title}</h4><p>{when(item.due_at)} · {item.status.replaceAll("_", " ")}</p><p>{item.guidance}</p>{item.source && <a href={item.source} target="_blank" rel="noreferrer">RBI source</a>}</article>)}</section>}
                {run.plan.map((action, index) => (
                  <article className="step" key={action.id}>
                    <span className={`step-number ${action.status}`}>
                      {action.status === "succeeded" ? "✓" : index + 1}
                    </span>
                    <div className="step-body">
                      <div className="step-title">
                        {action.title}
                        <span className={`mini-state ${action.status}`}>
                          {action.status.replaceAll("_", " ")}
                        </span>
                      </div>
                      {action.result && !action.result.startsWith('{"kind":') && (
                        <p>
                          {action.kind === "followup" && !Number.isNaN(Date.parse(action.result))
                            ? `Reminder set for ${when(action.result)}.`
                            : action.result}
                        </p>
                      )}
                      {action.reason && <p>{action.reason}</p>}
                      {action.status === "awaiting_approval" && (
                        <>
                          <p className="approval-copy">
                            {action.title.startsWith("Email ") || action.kind === "followup"
                              ? action.title + ". This uses your authorized Google account."
                              : action.kind === "freeze_card"
                              ? "This will mark the synthetic demo card as frozen in this local sandbox. No bank is contacted."
                              : "This will add a notice to the local demo outbox. No email or personal data will be sent."}
                          </p>
                          <div className="decision">
                            <button
                              className="primary"
                              disabled={busy}
                              onClick={() => void decide(action, true)}
                            >
                              Approve this action
                            </button>
                            <button
                              className="secondary"
                              disabled={busy}
                              onClick={() => void decide(action, false)}
                            >
                              Decline
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            </section>
          )}

          <section className="section-heading">
            <div>
              <p className="eyebrow">YOUR DEMO ACCOUNT</p>
              <h2>Recent activity.</h2>
            </div>
            <span>
              {context?.account.card_frozen
                ? "Demo card frozen"
                : "Synthetic transactions · no bank connection"}
            </span>
          </section>
          <section className="panel transactions">
            {context?.transactions.map((tx) => (
              <div className="transaction" key={tx.id}>
                <div>
                  <b>{tx.merchant}</b>
                  <small>
                    {when(tx.occurred_at)} · {tx.status}
                  </small>
                </div>
                <strong>{money(tx.amount)}</strong>
                {tx.suspicious ? <span className="flag">REVIEW</span> : null}
              </div>
            ))}
          </section>

          <section className="section-heading">
            <div>
              <p className="eyebrow">YOUR HISTORY</p>
              <h2>Incidents.</h2>
            </div>
            <span>Return to an existing response.</span>
          </section>
          <section className="panel transactions">
            {context?.incidents.length ? (
              context.incidents.map((incident) => (
                <button
                  className="incident-row"
                  key={incident.id}
                  onClick={() => void reopen(incident)}
                >
                  <span>
                    <b>{incident.summary}</b>
                    <small>{when(incident.created_at)}</small>
                  </span>
                  <span className="state">
                    {incident.status.replaceAll("_", " ")}
                  </span>
                </button>
              ))
            ) : (
              <p className="empty">No incidents yet.</p>
            )}
          </section>
          <button
            className="link-button"
            onClick={async () => {
              await stopVoice();
              await request("/api/auth/logout", {method: "POST"});
              setToken(""); setContext(null); setRun(null);
            }}
          >
            Sign out
          </button>
        </>
      )}
      <footer>
        <span>
          GUARDIAN <span className="footer-dot">•</span> HERE WITH YOU
        </span>
        <span>Demo environment · No real banking connections</span>
      </footer>
    </main>
  );
}
