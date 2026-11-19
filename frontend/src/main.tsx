import { useEffect, useRef, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import type { IAgoraRTCClient, IMicrophoneAudioTrack } from "agora-rtc-sdk-ng";
import type { RTMClient as RTMClientType } from "agora-rtm";
import "./style.css";

type Action = { id: string; kind: string; title: string; status: string; result: string | null };
type Incident = { id: string; summary: string; status: string; created_at: string };
type Run = { sandbox: boolean; incident: Incident; plan: Action[]; audit: { action: string; detail: string; created_at: string }[] };
type Context = { profile: { name: string; trusted_contact: string }; account: { card_frozen: boolean }; transactions: { merchant: string; amount: number; occurred_at: string; status: string; suspicious: number }[]; incidents: Incident[] };
type VoiceProfile = { id: string; label: string; asr_language: string; tts_locale: string; reply_language: string; greeting: string; auto_detect_input: boolean };
type VoiceConfig = { default_profile_id: string; profiles: VoiceProfile[] };
type VoiceSession = { session_id: string; app_id: string; channel: string; uid: number; rtc_rtm_token: string; profile_id: string; profile_label: string };
type Transcript = { role: string; content: string };
const API = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

function App() {
  const [token, setToken] = useState(sessionStorage.getItem("guardian-token") ?? "");
  const [tokenInput, setTokenInput] = useState(token);
  const [context, setContext] = useState<Context | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [summary, setSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [voiceStatus, setVoiceStatus] = useState("Voice is ready");
  const [voiceConfig, setVoiceConfig] = useState<VoiceConfig | null>(null);
  const [voiceProfileId, setVoiceProfileId] = useState("default");
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const [diagnosticId, setDiagnosticId] = useState("");
  const [diagnostics, setDiagnostics] = useState<{session: {status: string}; events: {event: string; created_at: string}[]} | null>(null);
  const [diagnosticError, setDiagnosticError] = useState("");
  const voiceSession = useRef<VoiceSession | null>(null);
  const rtcClient = useRef<IAgoraRTCClient | null>(null);
  const micTrack = useRef<IMicrophoneAudioTrack | null>(null);
  const rtmClient = useRef<RTMClientType | null>(null);

  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch(`${API}${path}`, { ...options, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...options.headers } });
    if (!response.ok) throw new Error((await response.json()).detail ?? `Request failed (${response.status})`);
    return response.json();
  }

  function logVoice(event: string, id = voiceSession.current?.session_id) {
    if (id) void request(`/api/voice/sessions/${id}/events`, {method: "POST", body: JSON.stringify({event})}).catch(() => setDiagnosticError("Some diagnostic events could not be saved."));
  }

  useEffect(() => {
    if (!diagnosticId || !token) return;
    let cancelled = false;
    async function refresh() {
      try {
        const data = await request<any>(`/api/voice/sessions/${diagnosticId}/diagnostics`);
        if (!cancelled) setDiagnostics(data);
        if (voiceSession.current?.session_id === diagnosticId) {
          await request(`/api/voice/sessions/${diagnosticId}`);
        }
      } catch { if (!cancelled) setDiagnosticError("Session status or diagnostics unavailable. Voice may still be connected."); }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [diagnosticId, token]);

  async function loadContext() {
    if (!token) return;
    try { setContext(await request<Context>("/api/context")); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load Guardian data."); }
  }

  useEffect(() => { void loadContext(); }, [token]);

  useEffect(() => {
    if (!token) return;
    request<VoiceConfig>("/api/voice/config")
      .then(config => { setVoiceConfig(config); setVoiceProfileId(config.default_profile_id); })
      .catch(e => setError(e instanceof Error ? e.message : "Could not load voice configuration."));
  }, [token]);

  async function connect() {
    setToken(tokenInput.trim());
    sessionStorage.setItem("guardian-token", tokenInput.trim());
  }

  async function startIncident(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { setRun(await request<Run>("/api/incidents", { method: "POST", body: JSON.stringify({ summary }) })); setSummary(""); await loadContext(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not start the incident."); }
    finally { setBusy(false); }
  }

  async function decide(action: Action, approved: boolean) {
    if (!run) return;
    setBusy(true); setError("");
    try { setRun(await request<Run>(`/api/incidents/${run.incident.id}/actions/${action.id}/approval`, { method: "POST", body: JSON.stringify({ approved }) })); await loadContext(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not record your decision."); }
    finally { setBusy(false); }
  }

  async function reopen(incident: Incident) {
    setBusy(true); setError("");
    try { setRun(await request<Run>(`/api/incidents/${incident.id}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not open incident."); }
    finally { setBusy(false); }
  }

  async function downloadReport() {
    if (!run) return;
    try {
      const report = await request<{ filename: string; content: string }>(`/api/incidents/${run.incident.id}/report`);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([report.content], { type: "text/markdown" }));
      link.download = report.filename; link.click(); URL.revokeObjectURL(link.href);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not generate the report."); }
  }

  async function startVoice() {
    setBusy(true); setError(""); setTranscripts([]); setVoiceStatus("Connecting to Agora…");
    let prepared: VoiceSession | null = null;
    try {
      const [{ default: AgoraRTC }, { default: AgoraRTM }] = await Promise.all([import("agora-rtc-sdk-ng"), import("agora-rtm")]);
      prepared = await request<VoiceSession>("/api/voice/session", { method: "POST", body: JSON.stringify({ profile_id: voiceProfileId }) });
      voiceSession.current = prepared;
      setDiagnosticId(prepared.session_id); setDiagnostics(null); setDiagnosticError("");
      const rtc = AgoraRTC.createClient({ mode: "rtc", codec: "vp8" });
      rtc.on("connection-state-change", state => { if (state === "DISCONNECTED") logVoice("rtc_disconnected", prepared?.session_id); });
      rtc.on("user-published", async (user, mediaType) => {
        try {
          await rtc.subscribe(user, mediaType);
          if (mediaType === "audio" && user.audioTrack) { user.audioTrack.play(); logVoice("remote_audio_play_requested", prepared?.session_id); }
        } catch { logVoice("remote_audio_failed", prepared?.session_id); }
      });
      await rtc.join(prepared.app_id, prepared.channel, prepared.rtc_rtm_token, prepared.uid);
      rtcClient.current = rtc; logVoice("rtc_joined");
      const mic = await AgoraRTC.createMicrophoneAudioTrack();
      micTrack.current = mic;
      await rtc.publish(mic); logVoice("mic_published");
      const rtm = new AgoraRTM.RTM(prepared.app_id, String(prepared.uid));
      await rtm.login({ token: prepared.rtc_rtm_token });
      await rtm.subscribe(prepared.channel); logVoice("rtm_connected");
      rtm.addEventListener("message", (event) => {
        if (event.channelName !== prepared?.channel) return;
        logVoice("message_received", prepared?.session_id);
        try {
          const raw = typeof event.message === "string" ? event.message : new TextDecoder().decode(event.message);
          const data = JSON.parse(raw);
          const candidates = [data, data.payload, data.data, data.transcript, data.payload?.transcript, data.data?.transcript].flatMap((value: any) => Array.isArray(value) ? value : value ? [value] : []);
          const next = candidates.filter((item: any) => typeof item?.text === "string" || typeof item?.content === "string").map((item: any) => ({ role: item.role ?? (String(item.uid) === String(prepared?.uid) || String(item.uid) === "0" ? "user" : "assistant"), content: item.text ?? item.content })).filter((item: Transcript) => item.content.trim());
          if (next.length) { setTranscripts(current => [...current, ...next]); logVoice("transcript_received", prepared?.session_id); }
          else logVoice("transcript_unrecognized", prepared?.session_id);
        } catch { /* Ignore non-transcript RTM events. */ }
      });
      rtmClient.current = rtm;
      await request(`/api/voice/sessions/${prepared.session_id}/start`, { method: "POST", body: "{}" });
      setVoiceStatus(`Connected · ${prepared.profile_label} · Murf Falcon`);
    } catch (e) {
      logVoice("agent_start_failed", prepared?.session_id);
      if (prepared) void request(`/api/voice/sessions/${prepared.session_id}/stop`, { method: "POST", body: "{}" }).catch(() => undefined);
      micTrack.current?.stop(); micTrack.current?.close(); micTrack.current = null;
      await rtcClient.current?.leave().catch(() => undefined); rtcClient.current = null;
      await rtmClient.current?.logout().catch(() => undefined); rtmClient.current = null;
      voiceSession.current = null; setVoiceStatus("Not connected");
      setError(e instanceof Error ? e.message : "Could not start the Agora voice session.");
    } finally { setBusy(false); }
  }

  async function stopVoice() {
    const active = voiceSession.current;
    setBusy(true);
    try { if (active) await request(`/api/voice/sessions/${active.session_id}/stop`, { method: "POST", body: "{}" }); }
    catch (e) { logVoice("stop_failed", active?.session_id); setError(e instanceof Error ? e.message : "Could not stop the voice session."); }
    finally {
      micTrack.current?.stop(); micTrack.current?.close(); micTrack.current = null;
      await rtcClient.current?.leave().catch(() => undefined); rtcClient.current = null;
      await rtmClient.current?.logout().catch(() => undefined); rtmClient.current = null;
      voiceSession.current = null; setVoiceStatus("Voice session ended"); setBusy(false);
    }
  }

  const money = (amount: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(amount);
  const when = (value: string) => new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });

  return <main className="shell">
    <header className="topbar"><a className="brand" href="#home"><span className="brand-mark">G</span> guardian</a><span className="sandbox"><i /> DEMO SANDBOX</span><button className="profile" aria-label="Profile">A</button></header>
    <section className="welcome"><div><p className="eyebrow">YOUR SAFETY, IN ONE PLACE</p><h1>Good evening, Alex.</h1><p className="subhead">If something feels wrong, we’ll work through it together.</p></div><span className="date">INCIDENT RESPONSE</span></section>

    {!token && <section className="panel auth-panel"><div><p className="eyebrow">LOCAL DEMO ACCESS</p><h2>Connect to Guardian</h2><p>Enter the demo API token configured on the backend. It stays in this browser tab only.</p></div><div className="auth-row"><input aria-label="Demo API token" type="password" value={tokenInput} onChange={e => setTokenInput(e.target.value)} placeholder="DEMO_API_TOKEN" /><button className="primary" onClick={() => void connect()} disabled={!tokenInput.trim()}>Connect</button></div></section>}

    {error && <div className="error" role="alert">{error}</div>}

    {token && <>
      <section className="voice-card"><div className="voice-copy"><span className="live-label"><i /> {voiceStatus.toUpperCase()}</span><h2>Talk it through.</h2><p>Use the live Agora voice session, or describe what happened below to create an incident plan.</p>
        <div className="voice-controls"><label>Conversation language<select value={voiceProfileId} disabled={busy || Boolean(voiceSession.current) || !voiceConfig} onChange={event => setVoiceProfileId(event.target.value)}>{voiceConfig?.profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.label}</option>)}</select></label>{voiceSession.current ? <button className="secondary" disabled={busy} onClick={() => void stopVoice()}>End voice session</button> : <button className="start-button" disabled={busy || !voiceConfig} onClick={() => void startVoice()}>◉ Start voice conversation</button>}</div>
        {diagnosticId && <details className="voice-diagnostics"><summary>Voice session diagnostics</summary><p>Session: <code>{diagnosticId}</code></p><p>Provider status: {diagnostics?.session.status ?? "Checking?"}. Updates every 10 seconds.</p><p>Audio events indicate playback was requested, not that speech was heard. Client events are self reported.</p>{diagnosticError && <p role="status">{diagnosticError}</p>}<ol>{diagnostics?.events.map((event, i) => <li key={i}><time>{new Date(event.created_at).toLocaleTimeString()}</time> {event.event.replaceAll("_", " ")}</li>)}</ol><p>Credentials and conversation text are excluded from diagnostics.</p></details>}
        {transcripts.length > 0 && <div className="transcript" aria-live="polite">{transcripts.map((item, index) => <p key={`${index}-${item.role}`}><b>{item.role === "assistant" ? "Guardian" : "You"}:</b> {item.content}</p>)}</div>}
        <p className="voice-caption">Voice sessions use Agora RTC and Murf Falcon. Auto-detect recognizes multilingual input but replies with the configured default voice; choose a language profile for matching speech output.</p>
        <form onSubmit={startIncident}><textarea required minLength={10} maxLength={2000} value={summary} onChange={e => setSummary(e.target.value)} placeholder="Example: Someone claiming to be a police officer threatened me and asked me to transfer ₹35,000. I may have shared banking details." /><button className="start-button" disabled={busy || summary.trim().length < 10}>{busy ? "Working…" : "Review my situation →"}</button></form>
        <small>No PINs or OTPs. Banking actions here are synthetic sandbox actions only.</small></div><div className="voice-art" aria-hidden="true"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="guardian-seal">G</div><div className="wave"><b/><b/><b/><b/><b/><b/><b/><b/><b/><b/><b/></div></div></section>

      {run && <section className="panel run-panel"><div className="run-heading"><div><p className="eyebrow">INCIDENT PLAN · SANDBOX</p><h2>Here’s what we can do.</h2><p className="run-summary">{run.incident.summary}</p><button className="report-button" onClick={() => void downloadReport()}>Download incident report</button></div><span className={`state ${run.incident.status}`}>{run.incident.status.replaceAll("_", " ")}</span></div>
        <div className="steps">{run.plan.map((action, index) => <article className="step" key={action.id}><span className={`step-number ${action.status}`}>{action.status === "succeeded" ? "✓" : index + 1}</span><div className="step-body"><div className="step-title">{action.title}<span className={`mini-state ${action.status}`}>{action.status.replaceAll("_", " ")}</span></div>{action.result && <p>{action.kind === "followup" ? `Reminder set for ${when(action.result)}.` : action.result}</p>}
          {action.status === "awaiting_approval" && <><p className="approval-copy">{action.kind === "freeze_card" ? "This will mark the synthetic demo card as frozen in this local sandbox. No bank is contacted." : "This will add a notice to the local demo outbox. No email or personal data will be sent."}</p><div className="decision"><button className="primary" disabled={busy} onClick={() => void decide(action, true)}>Approve this action</button><button className="secondary" disabled={busy} onClick={() => void decide(action, false)}>Decline</button></div></>}</div></article>)}</div>
        <details className="audit"><summary>Execution history</summary>{run.audit.map((event, i) => <p key={`${event.action}-${i}`}><b>{event.action.replaceAll("_", " ")}</b> · {event.detail} <time>{when(event.created_at)}</time></p>)}</details>
      </section>}

      <section className="section-heading"><div><p className="eyebrow">YOUR DEMO ACCOUNT</p><h2>Recent activity.</h2></div><span>{context?.account.card_frozen ? "Demo card frozen" : "Synthetic transactions · no bank connection"}</span></section>
      <section className="panel transactions">{context?.transactions.map(tx => <div className="transaction" key={tx.merchant}><div><b>{tx.merchant}</b><small>{when(tx.occurred_at)} · {tx.status}</small></div><strong>{money(tx.amount)}</strong>{tx.suspicious ? <span className="flag">REVIEW</span> : null}</div>)}</section>

      <section className="section-heading"><div><p className="eyebrow">YOUR HISTORY</p><h2>Incidents.</h2></div><span>Return to an existing response.</span></section>
      <section className="panel transactions">{context?.incidents.length ? context.incidents.map(incident => <button className="incident-row" key={incident.id} onClick={() => void reopen(incident)}><span><b>{incident.summary}</b><small>{when(incident.created_at)}</small></span><span className="state">{incident.status.replaceAll("_", " ")}</span></button>) : <p className="empty">No incidents yet.</p>}</section>
      <button className="link-button" onClick={() => { sessionStorage.removeItem("guardian-token"); setToken(""); }}>Disconnect demo session</button>
    </>}
    <footer><span>GUARDIAN <span className="footer-dot">•</span> HERE WITH YOU</span><span>Demo environment · No real banking connections</span></footer>
  </main>;
}

createRoot(document.getElementById("root")!).render(<App/>);
