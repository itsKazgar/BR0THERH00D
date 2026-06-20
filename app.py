#!/usr/bin/env python3
import os, sqlite3, secrets, datetime, requests
from flask import (Flask, request, session, redirect, render_template_string,
                   jsonify, abort)
from werkzeug.security import generate_password_hash, check_password_hash

APP_DIR  = os.path.dirname(os.path.abspath(__file__))
DB       = os.path.join(APP_DIR, "hood.db")
FEE      = os.environ.get("HOOD_FEE", "5.00")
PP_ID    = os.environ.get("PAYPAL_CLIENT_ID", "")
PP_SECRET= os.environ.get("PAYPAL_SECRET", "")
PP_ENV   = os.environ.get("PAYPAL_ENV", "sandbox")
PP_BASE  = "https://api-m.paypal.com" if PP_ENV == "live" else "https://api-m.sandbox.paypal.com"

app = Flask(__name__)
# Session key MUST be stable + shared across gunicorn workers, or logins break
# and sessions are forgeable per-restart. Use HOOD_SECRET in production.
app.secret_key = os.environ.get("HOOD_SECRET", "")
if not app.secret_key:
    import sys as _sys
    app.secret_key = secrets.token_hex(32)
    print("WARNING: HOOD_SECRET not set — using a random per-process key. "
          "Set HOOD_SECRET in production so sessions persist across workers/restarts.",
          file=_sys.stderr)

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

def init():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY, username TEXT UNIQUE, pw_hash TEXT NOT NULL,
      status TEXT DEFAULT 'pending', created TEXT);
    CREATE TABLE IF NOT EXISTS posts(
      uid INTEGER PRIMARY KEY, body TEXT, updated TEXT);
    CREATE TABLE IF NOT EXISTS dms(
      id INTEGER PRIMARY KEY, sender TEXT, recipient TEXT, body TEXT, ts TEXT);
    """)
    c.commit(); c.close()
init()

def me():
    uid = session.get("uid")
    if not uid: return None
    c = db(); u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone(); c.close()
    return u

STYLE = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Ubuntu+Mono:wght@400;700&display=swap');
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#1a0f1a;color:#e8d5c4;font-family:'Ubuntu Mono',monospace;
       font-size:15px;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
  .scr{width:100%;max-width:560px}
  .bar{color:#b99bb9;font-size:13px;margin-bottom:18px}
  a{color:#8fae4a;text-decoration:none} a:hover{text-decoration:underline}
  .row{display:flex;margin:8px 0} .row label{color:#8fae4a;width:90px}
  input{background:#0e060e;border:1px solid #3a2a3a;color:#e8d5c4;
        font-family:'Ubuntu Mono',monospace;font-size:14px;padding:7px 9px;flex:1;outline:none}
  input:focus{border-color:#d98e5a}
  .btn{display:inline-block;background:transparent;border:1px solid #8fae4a;color:#8fae4a;
       font-family:'Ubuntu Mono',monospace;font-size:14px;padding:8px 22px;cursor:pointer;margin-top:14px}
  .btn:hover{background:rgba(143,174,74,.1)}
  .enter{font-size:18px;padding:12px 40px;border-color:#d98e5a;color:#d98e5a}
  .enter:hover{background:rgba(217,142,90,.1)}
  .center{min-height:100vh;display:flex;align-items:center;justify-content:center}
  .err{color:#ff6b6b;margin:10px 0} .ok{color:#8fae4a;margin:10px 0} .dim{color:#7a6a72}
  .post{border-top:1px solid #2a1a2a;padding:12px 0}
  .post .u{color:#d98e5a} .post .t{color:#5a4a52;font-size:12px}
  .post .b{color:#e8d5c4;margin-top:4px;white-space:pre-wrap;word-break:break-word}
  textarea{background:#0e060e;border:1px solid #3a2a3a;color:#e8d5c4;width:100%;
           font-family:'Ubuntu Mono',monospace;font-size:14px;padding:9px;outline:none;resize:vertical;min-height:70px}
  textarea:focus{border-color:#d98e5a}
  .nav{color:#7a6a72;font-size:13px;margin-bottom:16px} .nav a{margin-right:14px}
</style>
"""

@app.route("/")
def home():
    return render_template_string(STYLE + """
    <form action="/gate" method="get" style="text-align:center">
      <button class="btn enter" type="submit">[ enter ]</button>
    </form>""")

@app.route("/gate")
def gate():
    if me() and me()["status"] == "active": return redirect("/board")
    return render_template_string(STYLE + """
    <div class="scr">
      <form action="/login" method="post">
        <div class="row"><label>login as</label><input name="username" autofocus></div>
        <div class="row"><label>password</label><input name="password" type="password"></div>
        <button class="btn" type="submit">log in</button>
      </form>
      <div style="margin-top:24px"><a href="/create">create account →</a></div>
    </div>""")

@app.route("/login", methods=["POST"])
def login():
    u = request.form.get("username","").strip(); p = request.form.get("password","")
    c = db(); row = c.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone(); c.close()
    if not row or not check_password_hash(row["pw_hash"], p):
        return render_template_string(STYLE + """
        <div class="scr"><div class="err">x wrong username or password</div><a href="/gate">< back</a></div>""")
    session["uid"] = row["id"]
    return redirect("/board") if row["status"] == "active" else redirect("/pay")

@app.route("/create")
def create():
    return render_template_string(STYLE + """
    <div class="scr">
      <form action="/create" method="post">
        <div class="row"><label>username</label><input name="username" autofocus></div>
        <div class="row"><label>password</label><input name="password" type="password"></div>
        <button class="btn" type="submit">continue →</button>
      </form>
      <div style="margin-top:20px"><a href="/gate">log in</a></div>
    </div>""")

@app.route("/create", methods=["POST"])
def create_post():
    u = request.form.get("username","").strip(); p = request.form.get("password","")
    if not u or not p or len(u) > 24 or " " in u:
        return render_template_string(STYLE + """
        <div class="scr"><div class="err">x pick a handle (no spaces, max 24) and a password</div>
        <a href="/create">< back</a></div>""")
    c = db()
    if c.execute("SELECT 1 FROM users WHERE username=?", (u,)).fetchone():
        c.close()
        return render_template_string(STYLE + """
        <div class="scr"><div class="err">x that handle is taken</div><a href="/create">< back</a></div>""")
    cur = c.execute("INSERT INTO users(username,pw_hash,status,created) VALUES(?,?,?,?)",
                    (u, generate_password_hash(p), "pending", datetime.datetime.utcnow().isoformat()))
    c.commit(); session["uid"] = cur.lastrowid; c.close()
    return redirect("/pay")

@app.route("/pay")
def pay():
    u = me()
    if not u: return redirect("/gate")
    if u["status"] == "active": return redirect("/board")
    configured = bool(PP_ID and PP_SECRET)
    return render_template_string(STYLE + """
    <div class="scr">
      <div class="dim">&gt; handle <span style="color:#d98e5a">{{u}}</span> reserved, pending payment.</div>
      <div class="dim" style="margin-top:6px">&gt; fee: ${{fee}} — one time. paid = approved.</div>
      {% if configured %}
        <div id="paypal-button-container" style="margin-top:20px;max-width:300px"></div>
        <div id="msg" class="dim" style="margin-top:10px"></div>
        <script src="https://www.paypal.com/sdk/js?client-id={{ppid}}&currency=USD"></script>
        <script>
          paypal.Buttons({
            style:{layout:'horizontal',color:'gold',shape:'rect',label:'pay'},
            createOrder:function(){return fetch('/pp/create',{method:'POST'}).then(r=>r.json()).then(d=>d.id);},
            onApprove:function(data){
              document.getElementById('msg').textContent='confirming...';
              return fetch('/pp/capture',{method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({orderID:data.orderID})}).then(r=>r.json()).then(d=>{
                  if(d.ok){window.location='/board';}
                  else{document.getElementById('msg').innerHTML='<span style="color:#ff6b6b">x '+(d.error||'failed')+'</span>';}
                });}
          }).render('#paypal-button-container');
        </script>
      {% else %}
        <div class="err" style="margin-top:18px">payments not configured yet.</div>
        <div class="dim">set PAYPAL_CLIENT_ID and PAYPAL_SECRET to go live.</div>
        <div class="dim" style="margin-top:14px">&gt; dev only:</div>
        <form action="/pay/dev-approve" method="post"><button class="btn" type="submit">[dev] mark paid</button></form>
      {% endif %}
      <div style="margin-top:22px"><a href="/logout">< cancel</a></div>
    </div>""", u=u["username"], fee=FEE, configured=configured, ppid=PP_ID)

def pp_token():
    r = requests.post(PP_BASE + "/v1/oauth2/token", auth=(PP_ID, PP_SECRET),
                      data={"grant_type": "client_credentials"},
                      headers={"Accept": "application/json"}, timeout=20)
    r.raise_for_status(); return r.json()["access_token"]

@app.route("/pp/create", methods=["POST"])
def pp_create():
    if not me(): abort(401)
    if not (PP_ID and PP_SECRET): return jsonify(error="not configured"), 400
    try:
        tok = pp_token()
        r = requests.post(PP_BASE + "/v2/checkout/orders",
            headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
            json={"intent": "CAPTURE", "purchase_units": [{"amount": {"currency_code": "USD", "value": FEE},
                  "description": "the h00d — handle approval"}]}, timeout=20)
        r.raise_for_status(); return jsonify(id=r.json()["id"])
    except Exception as e: return jsonify(error=str(e)), 500

@app.route("/pp/capture", methods=["POST"])
def pp_capture():
    u = me()
    if not u: abort(401)
    if not (PP_ID and PP_SECRET): return jsonify(error="not configured"), 400
    order = (request.json or {}).get("orderID")
    if not order: return jsonify(error="no order"), 400
    try:
        tok = pp_token()
        r = requests.post(PP_BASE + f"/v2/checkout/orders/{order}/capture",
            headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"}, timeout=20)
        r.raise_for_status(); data = r.json()
        if data.get("status") == "COMPLETED":
            c = db(); c.execute("UPDATE users SET status='active' WHERE id=?", (u["id"],)); c.commit(); c.close()
            return jsonify(ok=True)
        return jsonify(error="payment not completed"), 400
    except Exception as e: return jsonify(error=str(e)), 500

@app.route("/pay/dev-approve", methods=["POST"])
def dev_approve():
    if PP_ID and PP_SECRET: abort(403)
    u = me()
    if not u: return redirect("/gate")
    c = db(); c.execute("UPDATE users SET status='active' WHERE id=?", (u["id"],)); c.commit(); c.close()
    return redirect("/board")

def require_active():
    u = me()
    if not u: return None, redirect("/gate")
    if u["status"] != "active": return None, redirect("/pay")
    return u, None

@app.route("/board")
def board():
    u, r = require_active()
    if r: return r
    c = db()
    mine = c.execute("SELECT body FROM posts WHERE uid=?", (u["id"],)).fetchone()
    posts = c.execute("""SELECT users.username AS u, posts.body AS b, posts.updated AS t
                         FROM posts JOIN users ON users.id=posts.uid ORDER BY posts.updated DESC""").fetchall()
    c.close()
    rows = "".join(
        f'<div class="post"><span class="u">{_esc(p["u"])}</span> '
        f'<span class="t">{(p["t"] or "")[:16].replace("T"," ")}</span>'
        f'<div class="b">{_esc(p["b"])}</div></div>' for p in posts) \
        or '<div class="dim" style="margin-top:14px">no words yet.</div>'
    return render_template_string(STYLE + """
    <div class="scr">
      <div class="nav"><a href="/dm">messages</a><a href="/logout">log out</a></div>
      <form action="/board" method="post">
        <textarea name="body" placeholder="share your words (one post per brother — posting replaces yours)">{{mine}}</textarea>
        <button class="btn" type="submit">post →</button>
      </form>
      <div style="margin-top:22px">{{rows|safe}}</div>
    </div>""", mine=(mine["body"] if mine else ""), rows=rows)

@app.route("/board", methods=["POST"])
def board_post():
    u, r = require_active()
    if r: return r
    body = (request.form.get("body","") or "").strip()[:2000]
    c = db()
    if body:
        c.execute("INSERT INTO posts(uid,body,updated) VALUES(?,?,?) "
                  "ON CONFLICT(uid) DO UPDATE SET body=excluded.body, updated=excluded.updated",
                  (u["id"], body, datetime.datetime.utcnow().isoformat()))
        c.commit()
    c.close(); return redirect("/board")

@app.route("/dm")
def dm():
    u, r = require_active()
    if r: return r
    c = db()
    inbox = c.execute("SELECT sender,body,ts FROM dms WHERE recipient=? ORDER BY id DESC LIMIT 50",
                      (u["username"],)).fetchall()
    names = [x["username"] for x in
             c.execute("SELECT username FROM users WHERE status='active' AND id!=? ORDER BY username",
                       (u["id"],)).fetchall()]
    c.close()
    msgs = "".join(
        f'<div class="post"><span class="u">{_esc(m["sender"])}</span> '
        f'<span class="t">{(m["ts"] or "")[:16].replace("T"," ")}</span>'
        f'<div class="b">{_esc(m["body"])}</div></div>' for m in inbox) \
        or '<div class="dim" style="margin-top:14px">no messages.</div>'
    opts = "".join(f'<option value="{_esc(n)}">{_esc(n)}</option>' for n in names)
    return render_template_string(STYLE + """
    <div class="scr">
      <div class="nav"><a href="/board">board</a><a href="/logout">log out</a></div>
      <form action="/dm" method="post">
        <div class="row"><label>to</label>
          <select name="to" style="flex:1;background:#0e060e;border:1px solid #3a2a3a;color:#e8d5c4;font-family:'Ubuntu Mono',monospace;padding:7px">{{opts|safe}}</select></div>
        <textarea name="body" placeholder="message..."></textarea>
        <button class="btn" type="submit">send →</button>
      </form>
      <div class="dim" style="margin:20px 0 4px">&gt; inbox</div>
      {{msgs|safe}}
    </div>""", opts=opts, msgs=msgs)

@app.route("/dm", methods=["POST"])
def dm_post():
    u, r = require_active()
    if r: return r
    to = (request.form.get("to","") or "").strip()
    body = (request.form.get("body","") or "").strip()[:2000]
    c = db()
    ok = c.execute("SELECT 1 FROM users WHERE username=? AND status='active'", (to,)).fetchone()
    if ok and body:
        c.execute("INSERT INTO dms(sender,recipient,body,ts) VALUES(?,?,?,?)",
                  (u["username"], to, body, datetime.datetime.utcnow().isoformat()))
        c.commit()
    c.close(); return redirect("/dm")

@app.route("/logout")
def logout():
    session.clear(); return redirect("/")

def _esc(s):
    return ((s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            .replace('"',"&quot;").replace("'","&#39;"))

if __name__ == "__main__":
    print("the h00d -> http://localhost:8080  (payments:",
          "LIVE" if (PP_ID and PP_SECRET) else "not configured - dev approve enabled", ")")
    app.run(host="0.0.0.0", port=8080, debug=False)
