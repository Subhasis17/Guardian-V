import { useEffect, useState } from 'react';

type Profile = {username: string; age: string; address: string};
type Props = {request: <T>(path: string, options?: RequestInit) => Promise<T>};

export function ProfilePanel({request}: Props) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setError('');
    request<Profile>('/api/auth/profile')
      .then(value => {if (!cancelled) setProfile(value);})
      .catch(() => {if (!cancelled) setError('Could not load your profile. Please try again.');});
    return () => {cancelled = true;};
  }, [attempt]);
  return <section id="account-profile" className="panel account-profile" aria-labelledby="profile-heading">
    <div><h2 id="profile-heading">Your profile</h2><p>Your personal details are masked for privacy.</p></div>
    {error ? <p role="alert">{error} <button className="link-button" type="button" onClick={() => setAttempt(value => value + 1)}>Retry</button></p> : profile ? <dl>
      <div><dt>Username</dt><dd>{profile.username}</dd></div>
      <div><dt>Age</dt><dd>{profile.age}</dd></div>
      <div><dt>Address</dt><dd>{profile.address}</dd></div>
    </dl> : <p role="status">Loading profile?</p>}
  </section>;
}
