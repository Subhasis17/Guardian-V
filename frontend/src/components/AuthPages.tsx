import { useEffect, useState, type FormEvent } from 'react';

type Props = {
  request: <T>(path: string, options?: RequestInit) => Promise<T>;
  onSignedIn: (csrf: string) => void;
};

export function AuthPages({request, onSignedIn}: Props) {
  const [page, setPage] = useState<'register' | 'login' | 'consent'>('register');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [age, setAge] = useState('');
  const [address, setAddress] = useState('');
  const [accepted, setAccepted] = useState(false);
  const [notice, setNotice] = useState<{version: string; text: string} | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    request<{version: string; text: string}>('/api/auth/consent').then(setNotice).catch(() => setError('Privacy notice unavailable. Please try again.'));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError('');
    if (page === 'register') { setPage('consent'); return; }
    setBusy(true);
    try {
      if (page === 'consent') {
        if (!accepted || !notice) return;
        await request('/api/auth/register', {method: 'POST', body: JSON.stringify({username, password, age: Number(age), address, consent: accepted, consent_version: notice.version})});
      }
      const session = await request<{csrf_token: string}>('/api/auth/login', {method: 'POST', body: JSON.stringify({username, password})});
      setPassword(''); setAddress(''); setAge('');
      onSignedIn(session.csrf_token);
    } catch (e) {
      if (page === 'login') {
        setPage('register'); setPassword('');
        setError('Sign-in was unsuccessful. New here? Complete registration below. Already registered? Choose Sign in to retry.');
      } else {
        setAccepted(false);
        setError(e instanceof Error ? e.message : 'Could not create your account.');
      }
    } finally { setBusy(false); }
  }

  return <section className="auth-layout">
    <aside className="auth-intro"><p className="eyebrow">GUARDIAN · YOUR NEXT SAFE STEP</p><h2>A calm place to begin.</h2><p>Talk through what happened, review a plan, and stay in control of every action.</p><ul><li>Private account access</li><li>Approval before sensitive actions</li><li>Protected profile details</li></ul></aside>
    <form className="panel auth-form" onSubmit={submit}>
      <p className="eyebrow">{page === 'consent' ? 'STEP 2 OF 2' : page === 'register' ? 'STEP 1 OF 2' : 'WELCOME BACK'}</p>
      <h2>{page === 'consent' ? 'Your information, your choice' : page === 'register' ? 'Create your account' : 'Sign in'}</h2>
      {page === 'consent' ? <>
        <p>{notice?.text || 'Loading privacy notice…'}</p>
        <p>Username: {username.slice(0,1)}*** · Age: *** · Address: [hidden]</p>
        <label className="consent-check"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} required />I agree to the collection and protected storage of these profile details as described above.</label>
        <small>Notice version: {notice?.version}</small>
        <button type="button" className="link-button" disabled={busy} onClick={() => {setPage('register'); setAccepted(false);}}>Back to edit or decline</button>
      </> : <>
        <label>Username<input autoComplete="username" value={username} required minLength={3} maxLength={100} onChange={e => setUsername(e.target.value)} placeholder="Choose your username" /></label>
        <label>Password<input type="password" autoComplete={page === 'register' ? 'new-password' : 'current-password'} value={password} required minLength={page === 'register' ? 12 : 1} maxLength={256} onChange={e => setPassword(e.target.value)} placeholder={page === 'register' ? 'At least 12 characters' : 'Your password'} /></label>
        {page === 'register' && <><label>Age<input type="number" min={1} max={120} step={1} required value={age} onChange={e => setAge(e.target.value)} /></label><label>Address<textarea autoComplete="street-address" minLength={5} maxLength={500} required value={address} onChange={e => setAddress(e.target.value)} placeholder="Your address" /></label><p className="auth-note">Review the privacy notice before submitting your details. Never enter an OTP, PIN or banking password.</p></>}
      </>}
      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary" disabled={busy || (page === 'consent' && (!accepted || !notice))}>{busy ? 'Please wait…' : page === 'register' ? 'Review privacy & consent' : page === 'consent' ? 'Agree & create account' : 'Sign in'}</button>
      {page !== 'consent' && <button type="button" className="link-button" disabled={busy} onClick={() => {setPage(page === 'login' ? 'register' : 'login'); setPassword(''); setAccepted(false); setError('');}}>{page === 'login' ? 'New here? Create an account' : 'Already registered? Sign in'}</button>}
    </form>
  </section>;
}
