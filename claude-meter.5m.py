#!/usr/bin/env python3
"""claude-meter — Claude Code usage in your menu bar.

The two % gauges (5-hour + weekly) come straight from Anthropic's
`anthropic-ratelimit-unified-*` response headers, so they are ACCOUNT-WIDE —
they reflect every machine signed into your account, not just this one.
The dollar figures and the "heavy sessions" list are a LOCAL cost proxy
parsed from this machine's ~/.claude/projects logs.

Cross-platform core with thin per-OS shims (token / notify / clipboard).
macOS today, via SwiftBar; the shims carry Linux branches for the
waybar/Argos port. No third-party Python packages.
"""
import json, glob, os, sys, time, shlex, subprocess, getpass, platform
from collections import defaultdict
from datetime import datetime, timezone, timedelta

SELF   = os.path.abspath(__file__)
CFG    = os.path.expanduser("~/.config/claude-meter")
CACHE  = os.path.join(CFG, "real.json")
ALERTS = os.path.join(CFG, "alerts.json")
TTL    = 240                      # s; scheduled runs re-ping, rapid clicks reuse cache
IS_MAC = (platform.system() == "Darwin")
ALERT_LEVELS = [80, 95]           # notify when a window crosses these %
L5, L7 = 5 * 3600, 7 * 86400      # window lengths (s), for projection

# ---- cost proxy (local $ only) -------------------------------------------
PRICES = {
    "opus":   {"in":15.0,"out":75.0,"cr":1.50,"cw5":18.75,"cw1":30.0},
    "sonnet": {"in":3.0, "out":15.0,"cr":0.30,"cw5":3.75, "cw1":6.0},
    "haiku":  {"in":1.0, "out":5.0, "cr":0.10,"cw5":1.25, "cw1":2.0},
}
def rate(m):
    m=(m or "").lower()
    return PRICES["haiku"] if "haiku" in m else PRICES["sonnet"] if "sonnet" in m else PRICES["opus"]
def cost(u,model):
    r=rate(model); cc=u.get("cache_creation") or {}
    cw1=cc.get("ephemeral_1h_input_tokens",0)
    cw5=cc.get("ephemeral_5m_input_tokens",u.get("cache_creation_input_tokens",0)-cw1)
    return (u.get("input_tokens",0)*r["in"]+u.get("output_tokens",0)*r["out"]
            +u.get("cache_read_input_tokens",0)*r["cr"]+max(cw5,0)*r["cw5"]+cw1*r["cw1"])/1_000_000

# ---- platform shims ------------------------------------------------------
def get_token():
    """Claude Code OAuth access token, or None. macOS=Keychain, Linux=file/libsecret."""
    try:
        if IS_MAC:
            raw=subprocess.run(["security","find-generic-password","-s","Claude Code-credentials",
                "-a",getpass.getuser(),"-w"],capture_output=True,text=True,timeout=8).stdout.strip()
        else:  # Linux (best effort — verified on the waybar/Argos port)
            fp=os.path.expanduser("~/.claude/.credentials.json")
            raw=open(fp).read().strip() if os.path.exists(fp) else ""
            if not raw:
                raw=subprocess.run(["secret-tool","lookup","service","Claude Code-credentials"],
                    capture_output=True,text=True,timeout=8).stdout.strip()
        if not raw: return None
        o=json.loads(raw); o=o.get("claudeAiOauth",o)
        tok=o.get("accessToken"); exp=o.get("expiresAt",0) or 0
        if not tok or (exp and exp/1000 < time.time()): return None
        return tok
    except Exception:
        return None

def notify(title,msg):
    try:
        if IS_MAC:
            subprocess.run(["osascript","-e",f'display notification "{msg}" with title "{title}"'],
                           timeout=6,capture_output=True)
        else:
            subprocess.run(["notify-send",title,msg],timeout=6,capture_output=True)
    except Exception:
        pass

def clipboard(text):
    try:
        if IS_MAC:
            subprocess.run(["pbcopy"],input=text,text=True,timeout=6); return True
        for cmd in (["wl-copy"],["xclip","-selection","clipboard"]):
            try: subprocess.run(cmd,input=text,text=True,timeout=6); return True
            except Exception: continue
    except Exception:
        pass
    return False

# ---- live rate-limit headers ---------------------------------------------
def fetch_real():
    tok=get_token()
    if not tok: return None
    try:
        body=json.dumps({"model":"claude-haiku-4-5-20251001","max_tokens":1,
            "system":"You are Claude Code, Anthropic's official CLI for Claude.",
            "messages":[{"role":"user","content":"hi"}]})
        p=subprocess.run(["curl","-sS","-D","-","-o","/dev/null",
            "https://api.anthropic.com/v1/messages",
            "-H",f"authorization: Bearer {tok}",
            "-H","anthropic-beta: oauth-2025-04-20",
            "-H","anthropic-version: 2023-06-01",
            "-H","content-type: application/json","--data",body],
            capture_output=True,text=True,timeout=12)
        h={}
        for line in p.stdout.splitlines():
            if line.lower().startswith("anthropic-ratelimit") and ":" in line:
                k,v=line.split(":",1); h[k.strip().lower()]=v.strip()
        def g(k):
            try: return float(h[k])
            except: return None
        u5=g("anthropic-ratelimit-unified-5h-utilization")
        u7=g("anthropic-ratelimit-unified-7d-utilization")
        if u5 is None and u7 is None: return None
        d={"ts":time.time(),"u5":u5,"u7":u7,
           "r5":int(float(h.get("anthropic-ratelimit-unified-5h-reset",0) or 0)),
           "r7":int(float(h.get("anthropic-ratelimit-unified-7d-reset",0) or 0)),
           "status":h.get("anthropic-ratelimit-unified-status","")}
        os.makedirs(CFG,exist_ok=True); json.dump(d,open(CACHE,"w"))
        return d
    except Exception:
        return None

def get_real(force=False):
    cache=None
    try: cache=json.load(open(CACHE))
    except Exception: pass
    if cache and not force and time.time()-cache.get("ts",0) < TTL:
        return cache,"cached"
    fresh=fetch_real()
    if fresh: return fresh,"live"
    return (cache,"stale") if cache else (None,"none")

# ---- formatting ----------------------------------------------------------
def gauge(pct):
    if pct<12.5: return "◯"
    if pct<37.5: return "◔"
    if pct<62.5: return "◑"
    if pct<87.5: return "◕"
    return "●"
EIGHTHS="▏▎▍▌▋▊▉█"
def hbar(frac,width=10):
    frac=max(0.0,min(frac,1.0)); total=round(frac*width*8); full,rem=divmod(total,8)
    return ("█"*full+(EIGHTHS[rem-1] if rem else "")).ljust(width)
def pbar(pct,width=14):
    fill=int(round(min(pct,100)/100*width)); return "▕"+"█"*fill+"░"*(width-fill)+"▏"
def clr(pct):
    return "#34c759" if pct<50 else ("#ff9f0a" if pct<80 else "#ff3b30")
def cd(epoch):
    s=epoch-time.time()
    if s<=0: return "now"
    m=int(s//60)
    return f"{m//60}h{m%60:02d}m" if m<1440 else f"{m//1440}d {(m%1440)//60}h"
def when(epoch):
    if not epoch: return ""
    return datetime.fromtimestamp(epoch).astimezone().strftime("%a %I:%M %p").replace(" 0"," ")
def ago(ts):
    a=time.time()-ts
    return "just now" if a<60 else (f"{int(a//60)}m ago" if a<3600 else f"{int(a//3600)}h ago")
def override(name):
    fp=os.path.join(CFG,name)
    try: return float(open(fp).read().strip())
    except Exception: return None
def sanitize(s):  # SwiftBar treats | and newlines as control chars
    return (s or "").replace("|","/").replace("\n"," ").strip()
def pq(v):        # quote a SwiftBar param value only if it contains spaces
    return f'"{v}"' if (" " in v) else v

def project(util,reset,L):
    """Projected exhaustion epoch if on pace to hit the cap before reset, else None."""
    if util is None or not reset: return None
    now=time.time(); elapsed=L-(reset-now)
    if elapsed<=300 or util<=0.001: return None
    proj=now+elapsed*(1.0-util)/util
    return proj if proj<reset else None

# ---- alerts (background desktop notifications) ----------------------------
def check_alerts(real):
    if not real: return
    try: st=json.load(open(ALERTS))
    except Exception: st={}
    changed=False
    for key,util,reset,label in (("5h",real.get("u5"),real.get("r5"),"5-hour"),
                                  ("7d",real.get("u7"),real.get("r7"),"weekly")):
        if util is None or not reset: continue
        pct=util*100; s=st.get(key) or {}
        if s.get("reset")!=reset: s={"reset":reset,"notified":0}     # window rolled over
        crossed=max([t for t in ALERT_LEVELS if pct>=t] or [0])
        if crossed>s.get("notified",0):
            notify("claude-meter", f"{label} usage at {pct:.0f}% — resets in {cd(reset)}")
            s["notified"]=crossed; changed=True
        st[key]=s
    if changed:
        os.makedirs(CFG,exist_ok=True); json.dump(st,open(ALERTS,"w"))

# ---- main ----------------------------------------------------------------
def main():
    args=sys.argv[1:]
    if args and args[0]=="--copy":                                   # row-click action
        sid=args[1] if len(args)>1 else ""
        cwd=args[2] if len(args)>2 else ""
        cmd=(f"cd {shlex.quote(cwd)} && " if cwd else "")+f"claude --resume {sid}"
        clipboard(cmd); notify("claude-meter","Resume command copied to clipboard")
        return
    force="--force" in args

    now=datetime.now(timezone.utc).astimezone()
    start_today=now.replace(hour=0,minute=0,second=0,microsecond=0)
    d7=now-timedelta(days=7); d30=now-timedelta(days=30)
    wstart=now.replace(hour=23,minute=0,second=0,microsecond=0)
    while wstart.weekday()!=1 or wstart>now: wstart-=timedelta(days=1)

    by_model=defaultdict(float); win=defaultdict(float); daily=defaultdict(float)
    events=[]; earliest=None; today=now.date(); sessions={}
    for fp in glob.glob(os.path.expanduser("~/.claude/projects/**/*.jsonl"),recursive=True):
        s=sessions.setdefault(fp,{"sid":os.path.basename(fp)[:-6],"cwd":None,"title":None,
                                  "cost":0.0,"ctx":0,"subagents":0,"last":None})
        with open(fp,errors="ignore") as f:
            for line in f:
                try: o=json.loads(line)
                except: continue
                if s["cwd"] is None and o.get("cwd"): s["cwd"]=o["cwd"]
                if o.get("aiTitle"): s["title"]=o["aiTitle"]
                msg=o.get("message") or {}
                if msg.get("role")=="assistant" and isinstance(msg.get("content"),list):
                    for it in msg["content"]:
                        if isinstance(it,dict) and it.get("type")=="tool_use" and it.get("name")=="Task":
                            s["subagents"]+=1
                u=msg.get("usage"); model=msg.get("model")
                if not u or model=="<synthetic>": continue
                try: t=datetime.fromisoformat(o["timestamp"].replace("Z","+00:00")).astimezone()
                except: continue
                c=cost(u,model); events.append((t,c)); by_model[model]+=c
                earliest=t if earliest is None or t<earliest else earliest
                win["all"]+=c; daily[t.date()]+=c
                if t>=start_today: win["today"]+=c
                if t>=d30: win["30d"]+=c
                if t>=wstart: win["week"]+=c
                s["cost"]+=c
                ctx=u.get("input_tokens",0)+u.get("cache_read_input_tokens",0)
                if ctx>s["ctx"]: s["ctx"]=ctx
                s["last"]=t if s["last"] is None or t>s["last"] else s["last"]

    # active 5h proxy block (fallback only)
    events.sort(); blocks=[]; cur=None; B=timedelta(hours=5)
    for t,c in events:
        if cur and (t>=cur["start"]+B or t-cur["last"]>=B): blocks.append(cur); cur=None
        if cur is None: cur={"start":t.replace(minute=0,second=0,microsecond=0),"cost":0.0,"last":t}
        cur["cost"]+=c; cur["last"]=t
    if cur: blocks.append(cur)
    active=blocks[-1] if blocks and now<blocks[-1]["start"]+B else None
    bcost=active["cost"] if active else 0.0

    real,src=get_real(force=force)
    check_alerts(real if src in ("live","cached","stale") else None)

    proj5=proj7=None
    if real and real.get("u5") is not None:
        b_pct=real["u5"]*100; w_pct=(real.get("u7") or 0)*100
        b_reset=f"resets {when(real['r5'])} · in {cd(real['r5'])}" if real.get("r5") else ""
        w_reset=f"resets {when(real['r7'])} · in {cd(real['r7'])}" if real.get("r7") else ""
        proj5=project(real.get("u5"),real.get("r5"),L5)
        proj7=project(real.get("u7"),real.get("r7"),L7)
        srcline=(f"● live — Anthropic headers · updated {ago(real['ts'])}" if src in ("live","cached")
                 else f"◐ stale — last good {ago(real['ts'])}")
        accountwide=True
    else:
        blimit=override("claude_limit.txt") or max((b["cost"] for b in blocks),default=0.0) or 1.0
        wlimit=override("claude_weekly_limit.txt") or (win["week"] or 1.0)
        b_pct=min(bcost/blimit*100,999); w_pct=min(win["week"]/wlimit*100,999)
        b_reset=("resets in "+cd((active["start"]+B).timestamp())) if active else "idle"
        w_reset="resets "+when((wstart+timedelta(days=7)).timestamp())
        srcline="○ proxy (no API — token expired/offline; local estimate)"
        accountwide=False

    heavy=[s for s in sessions.values() if s["last"] and s["last"]>=d7 and s["cost"]>0.005
           and not s["sid"].startswith("agent-")]  # agent-* are subagent transcripts, not resumable
    heavy.sort(key=lambda s:-s["cost"]); heavy=heavy[:5]

    last7=[(today-timedelta(days=i)) for i in range(6,-1,-1)]
    last7=[(d,daily.get(d,0.0)) for d in last7]
    dmax=max((c for _,c in last7),default=0) or 1.0
    since=earliest.strftime("%b %d") if earliest else "?"
    MONO="font=Menlo size=13"; BIG="font=Menlo size=15"; SM="font=Menlo size=12"; GRAY="color=#8e8e93"
    p=print

    p(f"{gauge(b_pct)} {b_pct:.0f}% | color={clr(b_pct)}")
    p("---")
    p(f"Usage · {'account-wide (all machines)' if accountwide else 'local estimate'} | size=11 {GRAY}")
    p("---")
    p(f"5-hour window   ·  {b_reset} | size=11")
    p(f"{pbar(b_pct)} {b_pct:.0f}% | {BIG} color={clr(b_pct)}")
    if proj5: p(f"↗ on pace to hit the 5h cap ~{when(proj5)} | size=11 color=#ff3b30")
    p("---")
    p(f"Weekly window (all models)  ·  {w_reset} | size=11")
    p(f"{pbar(w_pct)} {w_pct:.0f}% | {BIG} color={clr(w_pct)}")
    if proj7: p(f"↗ on pace to hit the weekly cap ~{when(proj7)} | size=11 color=#ff3b30")
    elif accountwide: p(f"↗ on pace — clears the week before reset ✓ | size=11 {GRAY}")
    p("---")
    p(f"{srcline} | size=11")
    p(f"↻ Refresh now (live API) | bash={SELF} param1=--force terminal=false refresh=true")
    p("---")
    p(f"Heavy sessions · 7d · this machine | size=11 {GRAY}")
    if heavy:
        p(f"click a row to copy its claude --resume cmd | size=10 {GRAY}")
        for s in heavy:
            lbl=sanitize(s["title"] or (os.path.basename(s["cwd"]) if s["cwd"] else s["sid"][:8]))[:24]
            sub=f" · {s['subagents']} subagents" if s["subagents"] else ""
            ctx=f"{s['ctx']/1000:.0f}k" if s["ctx"] else "—"
            p(f"{lbl}  ${s['cost']:.2f} · ctx {ctx}{sub} | {SM} bash={SELF} "
              f"param1=--copy param2={s['sid']} param3={pq(s['cwd'] or '')} terminal=false")
    else:
        p(f"none in the last 7 days | {SM} {GRAY}")
    p("---")
    p(f"Per day (last 7) — local $ proxy | size=11 {GRAY}")
    for d,c in last7:
        tag=" ←today" if d==today else ""
        p(f"{d.strftime('%a')} ▕{hbar(c/dmax)}▏ ${c:>4.0f}{tag} | {SM}")
    p("---")
    p(f"Today ${win['today']:,.0f}  ·  this week ${win['week']:,.0f}  ·  30d ${win['30d']:,.0f} | {MONO}")
    p(f"All-time ${win['all']:,.0f}   (since {since}) | {MONO}")
    p(f"$ = equivalent API cost (local proxy, not billed on Pro/Max) | size=10 {GRAY}")
    p("By model | size=11")
    for m,v in sorted(by_model.items(),key=lambda x:-x[1]):
        p(f"{sanitize(m).replace('claude-',''):20} ${v:>8,.2f} | {SM}")

if __name__=="__main__":
    main()
