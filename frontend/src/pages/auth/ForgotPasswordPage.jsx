import { useState } from "react";
import { api } from "../../api.js";

const AUTH_CSS = `
.auth-wrap{min-height:100vh;background:var(--bg0);display:flex;align-items:center;justify-content:center;padding:24px}
.auth-card{background:var(--bg1);border:1px solid var(--border);border-radius:var(--rl);padding:36px 40px;width:100%;max-width:400px}
.auth-logo{font-size:32px;text-align:center;margin-bottom:8px}
.auth-title{font-size:22px;font-weight:800;letter-spacing:-.5px;text-align:center;margin-bottom:4px}
.auth-sub{font-size:12px;color:var(--t2);text-align:center;font-family:var(--mono);margin-bottom:28px}
.auth-label{font-size:11px;font-weight:700;color:var(--t2);letter-spacing:.8px;text-transform:uppercase;margin-bottom:6px}
.auth-input{width:100%;background:var(--bg2);border:1px solid var(--border2);border-radius:var(--r);color:var(--t0);font-family:var(--mono);font-size:13px;padding:10px 14px;outline:none;transition:border-color .15s;box-sizing:border-box}
.auth-input:focus{border-color:var(--accent)}
.auth-field{margin-bottom:16px}
.auth-btn{width:100%;padding:11px;border-radius:var(--r);background:var(--accent);border:none;color:#fff;font-size:14px;font-weight:700;cursor:pointer;transition:background .15s;margin-top:4px}
.auth-btn:hover{background:var(--accent2)}
.auth-btn:disabled{opacity:.5;cursor:not-allowed}
.auth-ok{background:rgba(35,209,139,.1);border:1px solid rgba(35,209,139,.25);border-radius:var(--r);padding:12px 14px;font-size:12px;color:var(--green);margin-bottom:14px;line-height:1.6}
.auth-links{margin-top:18px;font-size:12px;color:var(--t2);text-align:center}
.auth-link{color:var(--accent2);cursor:pointer}
.auth-link:hover{text-decoration:underline}
`;

export default function ForgotPasswordPage({ onDone, goLogin }) {
  const [form, setForm] = useState({ username:"", email:"" });
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try { await api.forgotPassword(form.username, form.email); } catch {}
    setSent(true); setBusy(false);
  };

  return (
    <>
      <style>{AUTH_CSS}</style>
      <div className="auth-wrap">
        <div className="auth-card">
          <div className="auth-logo">🔑</div>
          <div className="auth-title">Reset Password</div>
          <div className="auth-sub">We'll email you a reset link</div>
          {sent ? (
            <div className="auth-ok">
              Check your mailbox — if the details matched, a reset link is on its way.
              The link expires in 1 hour.
            </div>
          ) : (
            <form onSubmit={submit}>
              <div className="auth-field">
                <div className="auth-label">Username</div>
                <input className="auth-input" autoFocus value={form.username} onChange={e=>setForm(f=>({...f,username:e.target.value}))}/>
              </div>
              <div className="auth-field">
                <div className="auth-label">Email Address</div>
                <input className="auth-input" type="email" value={form.email} onChange={e=>setForm(f=>({...f,email:e.target.value}))}/>
              </div>
              <button className="auth-btn" type="submit" disabled={busy}>{busy?"Sending…":"Send Reset Link"}</button>
            </form>
          )}
          <div className="auth-links">
            <span className="auth-link" onClick={goLogin}>← Back to sign in</span>
          </div>
        </div>
      </div>
    </>
  );
}
