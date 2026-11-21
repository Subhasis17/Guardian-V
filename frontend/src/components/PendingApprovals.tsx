import type { Action } from "../types";

type Props = {
  approvals: Action[];
  busy: boolean;
  decide: (action: Action, approved: boolean) => Promise<void>;
};

export function PendingApprovals({ approvals, busy, decide }: Props) {
  return (
    <section className="panel approvals-panel" aria-live="polite">
      <div className="approval-heading">
        <div>
          <p className="eyebrow">NEEDS YOUR DECISION</p>
          <h2>Pending approvals</h2>
        </div>
        <span className="approval-count">{approvals.length}</span>
      </div>
      {approvals.map((action) => (
        <article className="approval-notice" key={action.id}>
          <div>
            <b>{action.title}</b>
            <p>{action.incident_summary}</p>
            <small>
              {action.title.startsWith("Email ") || action.kind === "followup"
                ? action.title + ". This uses your authorized Google account."
                : action.kind === "freeze_card"
                ? "Freezes the synthetic demo card in this sandbox."
                : "Adds a notice to the local sandbox outbox; no email is sent."}
            </small>
          </div>
          <div className="decision">
            <button
              className="primary"
              disabled={busy}
              onClick={() => void decide(action, true)}
            >
              Approve
            </button>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => void decide(action, false)}
            >
              Decline
            </button>
          </div>
        </article>
      ))}
    </section>
  );
}
