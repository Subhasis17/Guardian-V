export type Action = {
  id: string;
  incident_id?: string;
  incident_summary?: string;
  kind: string;
  title: string;
  status: string;
  result: string | null;
  depends_on?: string[];
  reason?: string;
};
export type Incident = {
  id: string;
  summary: string;
  status: string;
  created_at: string;
};
export type Run = {
  followups?: {id: string; title: string; due_at: string; status: string; guidance: string; source: string | null}[];
  assessment?: { severity: string; basis: string[]; missing_facts: string[] };
  sandbox: boolean;
  incident: Incident;
  plan: Action[];
  audit: { action: string; detail: string; created_at: string }[];
};
export type Context = {
  bank_available?: boolean;
  bank_warming?: boolean;
  bank_error?: string | null;
  profile: { name: string; trusted_contact: string };
  account: { card_frozen: boolean | null };
  transactions: {
    id: string;
    merchant: string;
    amount: number;
    occurred_at: string;
    status: string;
    suspicious: number;
  }[];
  incidents: Incident[];
  pending_approvals: Action[];
};
export type VoiceProfile = {
  id: string;
  label: string;
  asr_language: string;
  tts_locale: string;
  reply_language: string;
  greeting: string;
  auto_detect_input: boolean;
};
export type VoiceConfig = {
  default_profile_id: string;
  profiles: VoiceProfile[];
};
export type VoiceSession = {
  session_id: string;
  app_id: string;
  channel: string;
  uid: number;
  rtc_rtm_token: string;
  profile_id: string;
  profile_label: string;
};
export type Transcript = { role: string; content: string };
