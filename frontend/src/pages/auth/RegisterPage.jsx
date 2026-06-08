import { useState, useEffect } from "react";
import { api } from "../../api.js";

const AUTH_CSS = `
.auth-wrap{min-height:100vh;background:var(--bg0);display:flex;align-items:center;justify-content:center;padding:24px}
.auth-card{background:var(--bg1);border:1px solid var(--border);border-radius:var(--rl);padding:36px 40px;width:100%;max-width:420px}
.auth-logo{font-size:32px;text-align:center;margin-bottom:8px}
.auth-title{font-size:22px;font-weight:800;letter-spacing:-.5px;text-align:center;margin-bottom:4px}
.auth-sub{font-size:12px;color:var(--t2);text-align:center;font-family:var(--mono);margin-bottom:28px}
.auth-label{font-size:11px;font-weight:700;color:var(--t2);letter-spacing:.8px;text-transform:uppercase;margin-bottom:6px}
.auth-input{width:100%;background:var(--bg2);border:1px solid var(--border2);border-radius:var(--r);color:var(--t0);font-family:var(--mono);font-size:13px;padding:10px 14px;outline:none;transition:border-color .15s;box-sizing:border-box}
.auth-input:focus{border-color:var(--accent)}
.auth-field{margin-bottom:14px}
.auth-btn{width:100%;padding:11px;border-radius:var(--r);background:var(--accent);border:none;color:#fff;font-size:14px;font-weight:700;cursor:pointer;transition:background .15s;margin-top:4px}
.auth-btn:hover{background:var(--accent2)}
.auth-btn:disabled{opacity:.5;cursor:not-allowed}
.auth-err{background:rgba(240,90,90,.1);border:1px solid rgba(240,90,90,.25);border-radius:var(--r);padding:10px 14px;font-size:12px;color:var(--red);margin-bottom:14px;font-family:var(--mono)}
.auth-ok{background:rgba(35,209,139,.1);border:1px solid rgba(35,209,139,.25);border-radius:var(--r);padding:10px 14px;font-size:12px;color:var(--green);margin-bottom:14px}
.auth-links{margin-top:18px;font-size:12px;color:var(--t2);text-align:center}
.auth-link{color:var(--accent2);cursor:pointer}
.auth-link:hover{text-decoration:underline}
`;

export default function RegisterPage({ onDone, goLogin }) {
  const [form,   setForm]   = useState({ username:"", email:"", password:"", confirm_password:"" });
  const [busy,   setBusy]   = useState(false);
  const [err,    setErr]    = useState(null);
  const [ok,     setOk]     = useState(null);
  const [config, setConfig] = useState(null);

  useEffect(() => { api.publicConfig().catch(()=>null).then(r=>{ if(r) setConfig(r); }); }, []);

  const submit = async (e) => {
    e.preventDefault();
    if (form.password !== form.confirm_password) { setErr("Passwords do not match."); return; }
    if (form.password.length < 6) { setErr("Password must be at least 6 characters."); return; }
    setBusy(true); setErr(null);
    try {
      const r = await api.register(form.username, form.email, form.password, form.confirm_password);
      if (!r) { setErr("Registration failed."); }
      else if (r.ok) {
        setOk(r.verify_email
          ? "Account created! Check your inbox to verify your email before logging in."
          : "Account created! You can now sign in.");
      } else { setErr(r.error || "Registration failed."); }
    } catch(e) { setErr(e.message || "Network error."); }
    setBusy(false);
  };

  return (
    <>
      <style>{AUTH_CSS}</style>
      <div className="auth-wrap">
        <div className="auth-card">
          <div className="auth-logo">⚡</div>
          <div className="auth-title">Create Account</div>
          <div className="auth-sub">Join DiscordForge</div>
          {err && <div className="auth-err">{err}</div>}
          {ok  && <div className="auth-ok">{ok} <span className="auth-link" onClick={goLogin}>Sign in →</span></div>}
          {!ok && (
            <form onSubmit={submit}>
              <div className="auth-field">
                <div className="auth-label">Username</div>
                <input className="auth-input" autoFocus value={form.username} onChange={e=>setForm(f=>({...f,username:e.target.value}))} autoComplete="username"/>
              </div>
              <div className="auth-field">
                <div className="auth-label">Email</div>
                <input className="auth-input" type="email" value={form.email} onChange={e=>setForm(f=>({...f,email:e.target.value}))} autoComplete="email"/>
              </div>
              <div className="auth-field">
                <div className="auth-label">Password</div>
                <input className="auth-input" type="password" value={form.password} onChange={e=>setForm(f=>({...f,password:e.target.value}))} autoComplete="new-password"/>
              </div>
              <div className="auth-field">
                <div className="auth-label">Confirm Password</div>
                <input className="auth-input" type="password" value={form.confirm_password} onChange={e=>setForm(f=>({...f,confirm_password:e.target.value}))} autoComplete="new-password"/>
              </div>
              <button className="auth-btn" type="submit" disabled={busy}>{busy?"Creating…":"Create Account"}</button>
            </form>
          )}
          <div className="auth-links">
            Already have an account? <span className="auth-link" onClick={goLogin}>Sign in</span>
          </div>
        </div>
      </div>
    </>
  );
}
