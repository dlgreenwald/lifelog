import { useAuth } from '../auth/AuthContext';

export default function LandingPage() {
  const { login } = useAuth();

  return (
    <div className="landing-page">
      <div className="landing-content">
        <h1>LifeLog</h1>
        <p className="tagline">Your voice, remembered.</p>
        <p className="description">
          A voice-activated life journal. Wear a recorder, speak naturally,
          and LifeLog transcribes, diarizes, and summarizes your conversations
          — surfacing decisions, TODOs, and key moments.
        </p>
        <button className="login-button" onClick={login}>
          Sign in
        </button>
      </div>
    </div>
  );
}
