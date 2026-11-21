import { useEffect, useRef, useState } from "react";
import type { IAgoraRTCClient, IMicrophoneAudioTrack } from "agora-rtc-sdk-ng";
import type { RTMClient as RTMClientType } from "agora-rtm";
import type { VoiceConfig, VoiceSession, Transcript } from "../types";

type VoiceOptions = {
  token: string;
  request: <T>(path: string, options?: RequestInit) => Promise<T>;
  setBusy: (busy: boolean) => void;
  setError: (error: string) => void;
};

export function useVoice({ token, request, setBusy, setError }: VoiceOptions) {
  const [voiceStatus, setVoiceStatus] = useState("Voice is ready");
  const [voiceConfig, setVoiceConfig] = useState<VoiceConfig | null>(null);
  const [voiceProfileId, setVoiceProfileId] = useState("default");
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const [diagnosticId, setDiagnosticId] = useState("");
  const [diagnostics, setDiagnostics] = useState<{
    session: { status: string };
    events: { event: string; created_at: string }[];
  } | null>(null);
  const [diagnosticError, setDiagnosticError] = useState("");
  const voiceSession = useRef<VoiceSession | null>(null);
  const rtcClient = useRef<IAgoraRTCClient | null>(null);
  const micTrack = useRef<IMicrophoneAudioTrack | null>(null);
  const rtmClient = useRef<RTMClientType | null>(null);

  function logVoice(event: string, id = voiceSession.current?.session_id) {
    if (id)
      void request(`/api/voice/sessions/${id}/events`, {
        method: "POST",
        body: JSON.stringify({ event }),
      }).catch(() =>
        setDiagnosticError("Some diagnostic events could not be saved."),
      );
  }

  useEffect(() => {
    if (!diagnosticId || !token) return;
    let cancelled = false;
    async function refresh() {
      try {
        const data = await request<any>(
          `/api/voice/sessions/${diagnosticId}/diagnostics`,
        );
        if (!cancelled) setDiagnostics(data);
        if (voiceSession.current?.session_id === diagnosticId) {
          const state = await request<{status: string}>(`/api/voice/sessions/${diagnosticId}`);
          if (!cancelled && ["stopped", "failed", "ended", "terminated", "completed"].includes(state.status.toLowerCase())) {
            micTrack.current?.stop();
            micTrack.current?.close();
            micTrack.current = null;
            await rtcClient.current?.leave().catch(() => undefined);
            rtcClient.current = null;
            await rtmClient.current?.logout().catch(() => undefined);
            rtmClient.current = null;
            voiceSession.current = null;
            setVoiceStatus(`Voice session ${state.status}`);
          }
        }
      } catch {
        if (!cancelled)
          setDiagnosticError(
            "Session status or diagnostics unavailable. Voice may still be connected.",
          );
      }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [diagnosticId, token]);

  useEffect(() => {
    if (!token) return;
    request<VoiceConfig>("/api/voice/config")
      .then((config) => {
        setVoiceConfig(config);
        setVoiceProfileId(config.default_profile_id);
      })
      .catch((e) =>
        setError(
          e instanceof Error
            ? e.message
            : "Could not load voice configuration.",
        ),
      );
  }, [token]);

  async function startVoice() {
    setBusy(true);
    setError("");
    setTranscripts([]);
    setVoiceStatus("Connecting to Agora…");
    let prepared: VoiceSession | null = null;
    try {
      const [{ default: AgoraRTC }, { default: AgoraRTM }] = await Promise.all([
        import("agora-rtc-sdk-ng"),
        import("agora-rtm"),
      ]);
      prepared = await request<VoiceSession>("/api/voice/session", {
        method: "POST",
        body: JSON.stringify({ profile_id: voiceProfileId }),
      });
      voiceSession.current = prepared;
      setDiagnosticId(prepared.session_id);
      setDiagnostics(null);
      setDiagnosticError("");
      const rtc = AgoraRTC.createClient({ mode: "rtc", codec: "vp8" });
      rtc.on("connection-state-change", (state) => {
        if (state === "DISCONNECTED")
          logVoice("rtc_disconnected", prepared?.session_id);
      });
      rtc.on("user-published", async (user, mediaType) => {
        try {
          await rtc.subscribe(user, mediaType);
          if (mediaType === "audio" && user.audioTrack) {
            user.audioTrack.play();
            logVoice("remote_audio_play_requested", prepared?.session_id);
          }
        } catch {
          logVoice("remote_audio_failed", prepared?.session_id);
        }
      });
      await rtc.join(
        prepared.app_id,
        prepared.channel,
        prepared.rtc_rtm_token,
        prepared.uid,
      );
      rtcClient.current = rtc;
      logVoice("rtc_joined");
      const mic = await AgoraRTC.createMicrophoneAudioTrack();
      micTrack.current = mic;
      await rtc.publish(mic);
      logVoice("mic_published");
      const rtm = new AgoraRTM.RTM(prepared.app_id, String(prepared.uid));
      await rtm.login({ token: prepared.rtc_rtm_token });
      await rtm.subscribe(prepared.channel);
      logVoice("rtm_connected");
      rtm.addEventListener("message", (event) => {
        if (event.channelName !== prepared?.channel) return;
        logVoice("message_received", prepared?.session_id);
        try {
          const raw =
            typeof event.message === "string"
              ? event.message
              : new TextDecoder().decode(event.message);
          const data = JSON.parse(raw);
          const candidates = [
            data,
            data.payload,
            data.data,
            data.transcript,
            data.payload?.transcript,
            data.data?.transcript,
          ].flatMap((value: any) =>
            Array.isArray(value) ? value : value ? [value] : [],
          );
          const next = candidates
            .filter(
              (item: any) =>
                typeof item?.text === "string" ||
                typeof item?.content === "string",
            )
            .map((item: any) => ({
              role:
                item.role ??
                (String(item.uid) === String(prepared?.uid) ||
                String(item.uid) === "0"
                  ? "user"
                  : "assistant"),
              content: item.text ?? item.content,
            }))
            .filter((item: Transcript) => item.content.trim());
          if (next.length) {
            setTranscripts((current) => [...current, ...next]);
            logVoice("transcript_received", prepared?.session_id);
          } else logVoice("transcript_unrecognized", prepared?.session_id);
        } catch {
          /* Ignore non-transcript RTM events. */
        }
      });
      rtmClient.current = rtm;
      await request(`/api/voice/sessions/${prepared.session_id}/start`, {
        method: "POST",
        body: "{}",
      });
      setVoiceStatus(`Connected · ${prepared.profile_label} · Murf Falcon`);
    } catch (e) {
      logVoice("agent_start_failed", prepared?.session_id);
      if (prepared)
        void request(`/api/voice/sessions/${prepared.session_id}/stop`, {
          method: "POST",
          body: "{}",
        }).catch(() => undefined);
      micTrack.current?.stop();
      micTrack.current?.close();
      micTrack.current = null;
      await rtcClient.current?.leave().catch(() => undefined);
      rtcClient.current = null;
      await rtmClient.current?.logout().catch(() => undefined);
      rtmClient.current = null;
      voiceSession.current = null;
      setVoiceStatus("Not connected");
      setError(
        e instanceof Error
          ? e.message
          : "Could not start the Agora voice session.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function stopVoice() {
    const active = voiceSession.current;
    let stopped = !active;
    setBusy(true);
    try {
      if (active)
        await request(`/api/voice/sessions/${active.session_id}/stop`, {
          method: "POST",
          body: "{}",
        });
      stopped = true;
    } catch (e) {
      logVoice("stop_failed", active?.session_id);
      setError(
        e instanceof Error ? e.message : "Could not stop the voice session.",
      );
    } finally {
      micTrack.current?.stop();
      micTrack.current?.close();
      micTrack.current = null;
      await rtcClient.current?.leave().catch(() => undefined);
      rtcClient.current = null;
      await rtmClient.current?.logout().catch(() => undefined);
      rtmClient.current = null;
      if (stopped) voiceSession.current = null;
      setVoiceStatus(stopped ? "Voice session ended" : "Microphone off; server stop unconfirmed. Retry End voice session.");
      setBusy(false);
    }
  }

  return {
    voiceStatus,
    voiceConfig,
    voiceProfileId,
    setVoiceProfileId,
    transcripts,
    diagnosticId,
    diagnostics,
    diagnosticError,
    voiceSession,
    startVoice,
    stopVoice,
  };
}
