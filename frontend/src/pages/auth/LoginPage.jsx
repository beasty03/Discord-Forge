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
.auth-err{background:rgba(240,90,90,.1);border:1px solid rgba(240,90,90,.25);border-radius:var(--r);padding:10px 14px;font-size:12px;color:var(--red);margin-bottom:14px;font-family:var(--mono)}
.auth-links{display:flex;justify-content:space-between;margin-top:18px;font-size:12px;color:var(--t2)}
.auth-link{color:var(--accent2);cursor:pointer;text-decoration:none}
.auth-link:hover{text-decoration:underline}
`;

export default function LoginPage({ onLogin, goRegister, goForgot }) {
  const [form, setForm] = useState({ username:"", password:"" });
  const [busy, setBusy] = useState(false);
  const [err,  setErr]  = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!form.username || !form.password) { setErr("Enter username and password."); return; }
    setBusy(true); setErr(null);
    try {
      const r = await api.login(form.username, form.password);
      if (!r) { setErr("Login failed. Check your credentials."); }
      else if (r.ok) { onLogin(); }
      else { setErr(r.error || "Login failed."); }
    } catch(e) { setErr(e.message || "Network error."); }
    setBusy(false);
  };

  return (
    <>
      <style>{AUTH_CSS}</style>
      <div className="auth-wrap">
        <div className="auth-card">
          <div className="auth-logo">⚡</div>
          <div className="auth-title">DiscordForge</div>
          <div className="auth-sub">Sign in to your account</div>
          {err && <div className="auth-err">{err}</div>}
          <form onSubmit={submit}>
            <div className="auth-field">
              <div className="auth-label">Username</div>
              <input className="auth-input" autoFocus value={form.username} onChange={e=>setForm(f=>({...f,username:e.target.value}))} autoComplete="username"/>
            </div>
            <div className="auth-field">
              <div className="auth-label">Password</div>
              <input className="auth-input" type="password" value={form.password} onChange={e=>setForm(f=>({...f,password:e.target.value}))} autoComplete="current-password"/>
            </div>
            <button className="auth-btn" type="submit" disabled={busy}>{busy?"Signing in…":"Sign In"}</button>
          </form>
          <div className="auth-links">
            <span className="auth-link" onClick={goRegister}>Create account</span>
            <span className="auth-link" onClick={goForgot}>Forgot password?</span>
          </div>
        </div>
      </div>
    </>
  );
}
