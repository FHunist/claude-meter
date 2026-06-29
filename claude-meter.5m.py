#!/usr/bin/env python3
"""claude-meter: Claude Code usage in your menu bar (Claude Pro/Max).

The two % gauges (5-hour + weekly) come straight from Anthropic's
`anthropic-ratelimit-unified-*` response headers, so they are ACCOUNT-WIDE:
they reflect every machine signed into your account, not just this one.
The dollar figures and the "heavy sessions" list are a LOCAL cost proxy
parsed from this machine's ~/.claude/projects logs.

Cross-platform core with thin per-OS shims (token / notify / clipboard).
macOS today, via SwiftBar; the shims carry Linux branches for the
waybar/Argos port. No third-party Python packages.
"""
import json, glob, os, sys, time, shlex, base64, subprocess, getpass, platform
from collections import defaultdict
from datetime import datetime, timezone, timedelta

SELF   = os.path.abspath(__file__)
CFG    = os.path.expanduser("~/.config/claude-meter")
CACHE  = os.path.join(CFG, "real.json")
ALERTS = os.path.join(CFG, "alerts.json")
TREND  = os.path.join(CFG, "trend.json")
CONFIG = os.path.join(CFG, "config.json")
NAMES  = os.path.join(CFG, "names.json")   # user-set session labels {sid: name}
REPO_URL = "https://github.com/FHunist/claude-meter"
TTL    = 240                      # s; scheduled runs re-ping, rapid clicks reuse cache
IS_MAC = (platform.system() == "Darwin")
ALERT_LEVELS = [50, 80, 95]       # notify when a window crosses these %
ACTIVE_MIN   = 30                 # a session is "active" if it logged within this many minutes
L5, L7 = 5 * 3600, 7 * 86400      # window lengths (s), for projection
WARMUP = 45 * 60                  # s; floor on elapsed so the projection doesn't spike early

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
    r=rate(model); cc=u.get("cache_creation"); cc=cc if isinstance(cc,dict) else {}
    cw1=cc.get("ephemeral_1h_input_tokens") or 0
    cw5=cc.get("ephemeral_5m_input_tokens")
    if cw5 is None: cw5=(u.get("cache_creation_input_tokens") or 0)-cw1
    return ((u.get("input_tokens") or 0)*r["in"]+(u.get("output_tokens") or 0)*r["out"]
            +(u.get("cache_read_input_tokens") or 0)*r["cr"]+max(cw5 or 0,0)*r["cw5"]+cw1*r["cw1"])/1_000_000

# ---- platform shims ------------------------------------------------------
def get_token():
    """Claude Code OAuth access token, or None. macOS=Keychain, Linux=file/libsecret."""
    try:
        if IS_MAC:
            raw=subprocess.run(["security","find-generic-password","-s","Claude Code-credentials",
                "-a",getpass.getuser(),"-w"],capture_output=True,text=True,timeout=8).stdout.strip()
        else:  # Linux (best effort, verified on the waybar/Argos port)
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
    def esc(t): return str(t).replace("\\","\\\\").replace('"','\\"')
    try:
        if IS_MAC:
            subprocess.run(["osascript","-e",
                f'display notification "{esc(msg)}" with title "{esc(title)}"'],
                timeout=6,capture_output=True)
        else:
            subprocess.run(["notify-send",str(title),str(msg)],timeout=6,capture_output=True)
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

def open_session(sid,cwd,cfg):
    """Open the session in a terminal and run `claude --resume`. Falls back to copying."""
    if not sid: return
    cmd=(f"cd {shlex.quote(cwd)} && " if cwd else "")+f"claude --resume {shlex.quote(sid)}"
    term=(cfg.get("terminal") or "Terminal")
    esc=cmd.replace("\\","\\\\").replace('"','\\"')   # escape for an AppleScript string
    try:
        if term=="iTerm":
            script=('tell application "iTerm"\nactivate\n'
                    'set w to (create window with default profile)\n'
                    'tell current session of w to write text "'+esc+'"\nend tell')
            osa=["osascript","-e",script]
        elif term=="Warp":                            # no `do script`, simulate keystrokes
            script=('tell application "Warp" to activate\ndelay 0.4\n'
                    'tell application "System Events"\n'
                    'keystroke "n" using command down\ndelay 0.5\n'
                    'keystroke "'+esc+'"\nkey code 36\nend tell')
            osa=["osascript","-e",script]
        else:                                          # Terminal.app (default, reliable)
            osa=["osascript","-e",'tell application "Terminal" to do script "'+esc+'"',
                 "-e",'tell application "Terminal" to activate']
        r=subprocess.run(osa,timeout=15,capture_output=True,text=True)
        if r.returncode!=0: raise RuntimeError(r.stderr or "osascript failed")
    except Exception:
        clipboard(cmd); notify("claude-meter","Couldn't open terminal, resume command copied instead")

# ---- session display names + rename dialog -------------------------------
def _osa_esc(t): return str(t).replace("\\","\\\\").replace('"','\\"')
def prompt_name(default=""):
    """macOS text dialog returning the new label (None if cancelled; "" means reset to auto)."""
    if not IS_MAC: return None
    try:
        r=subprocess.run(["osascript",
            "-e",'display dialog "Rename this session in claude-meter (blank resets to auto):" '
                 'default answer "'+_osa_esc(default)+'" with title "claude-meter" '
                 'buttons {"Cancel","Save"} default button "Save"',
            "-e",'text returned of result'],capture_output=True,text=True,timeout=120)
        return r.stdout.rstrip("\n") if r.returncode==0 else None
    except Exception: return None
def load_names():
    try: d=json.load(open(NAMES)); return d if isinstance(d,dict) else {}
    except Exception: return {}
def save_names(d):
    try: os.makedirs(CFG,exist_ok=True); json.dump(d,open(NAMES,"w"))
    except Exception: pass

# ---- live rate-limit headers ---------------------------------------------
def fetch_real():
    tok=get_token()
    if not tok: return None
    try:
        body=json.dumps({"model":"claude-haiku-4-5-20251001","max_tokens":1,
            "system":"You are Claude Code, Anthropic's official CLI for Claude.",
            "messages":[{"role":"user","content":"hi"}]})
        p=subprocess.run(["curl","-sS","-D","-","-o","/dev/null","-K","-",
            "https://api.anthropic.com/v1/messages",
            "-H","anthropic-beta: oauth-2025-04-20",
            "-H","anthropic-version: 2023-06-01",
            "-H","content-type: application/json","--data",body],
            input=f'header = "authorization: Bearer {tok}"\n',   # token via stdin config, not argv (ps-safe)
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
    try:
        cache=json.load(open(CACHE))
        if not isinstance(cache,dict): cache=None
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
    frac=max(0.0,min(pct/100.0,1.0)); total=round(frac*width*8); full,rem=divmod(total,8)
    return "▕"+("█"*full+(EIGHTHS[rem-1] if rem else "")).ljust(width,"░")+"▏"
def clr(pct):
    return "#34c759" if pct<50 else ("#ff9f0a" if pct<80 else "#ff3b30")
def cd(epoch):
    s=epoch-time.time()
    if s<=0: return "now"
    m=int(s//60)
    return f"{m//60}h{m%60:02d}m" if m<1440 else f"{m//1440}d {(m%1440)//60}h"
def when(epoch):
    if not epoch: return ""
    return datetime.fromtimestamp(epoch).astimezone().strftime("%a %I:%M %p").replace(" 0"," ").replace(":00","")
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
def sftint(name,hexcolor):
    """Full SF Symbol spec: image + color. sfcolor alone doesn't tint in older
    SwiftBar, so also emit a Palette sfconfig (base64 JSON), which does."""
    cfg=base64.b64encode(json.dumps({"renderingMode":"Palette","colors":[hexcolor],
        "scale":"medium","weight":"semibold"}).encode()).decode()
    return f"sfimage={name} sfcolor={hexcolor} sfconfig={cfg}"

def dur(secs):
    m=int(max(secs,0)//60)
    if m<60: return f"{m}m"
    if m<1440: return f"{m//60}h{m%60:02d}m"
    return f"{m//1440}d{(m%1440)//60}h"

def proj_color(proj,reset,L):
    """Color the projection by how much of the window you'd be locked out for."""
    frac=(reset-proj)/L
    if frac>0.33: return "#d70015,#ff453a"   # red   : long lockout ahead
    if frac>0.10: return "#b25000,#ff9f0a"   # amber : moderate
    return "#9a7d0a,#ffd60a"                  # yellow : marginal overshoot

def forecast(util,reset,L):
    """Projected end-of-window state at the current average rate. (text,color) or None."""
    now=time.time()
    if util is None or not reset: return None
    remaining=reset-now
    if remaining<=0: return None              # window already reset / stale headers
    elapsed=L-remaining
    if elapsed<=300 or util<=0.001: return None
    rate=util/max(elapsed,WARMUP)            # warmup floor damps the early-window spike
    end=util+rate*remaining                   # projected utilization at reset
    if end>=1.0:
        proj=now+(1.0-util)/rate
        return (f"→ caps {when(proj)} · ~{dur(reset-proj)} locked", proj_color(proj,reset,L))
    return (f"→ ~{end*100:.0f}% at reset", "#6e6e73,#aeaeb2")

def load_config():
    cfg={"alert_levels":list(ALERT_LEVELS),"active_min":ACTIVE_MIN,"dual_title":False,"title_window":"5h","terminal":"Terminal",
         "show":{"forecast":True,"burn":True,"trend":True,"sessions":True,"insight":True,"cost":True,"links":True}}
    try:
        u=json.load(open(CONFIG))
        if isinstance(u,dict):
            for k in cfg:
                if k not in u: continue
                if k=="show":
                    if isinstance(u[k],dict): cfg["show"].update(u[k])  # merge partial
                elif type(u[k])==type(cfg[k]): cfg[k]=u[k]              # ignore wrong-typed values
    except Exception: pass
    al=cfg["alert_levels"]
    if not (isinstance(al,list) and al and all(isinstance(x,(int,float)) for x in al)):
        cfg["alert_levels"]=list(ALERT_LEVELS)
    return cfg

def status_banner(status):
    s=(status or "").lower()
    if not s or s=="allowed": return None
    if "reject" in s: return ("⛔ Rate-limited: requests are being rejected","#ff3b30")
    if "queue"  in s: return ("⏳ Requests are being queued (throttled)","#ff9f0a")
    if "warn"   in s: return ("⚠︎ Approaching your limit","#ff9f0a")
    return (f"status: {status}","#ff9f0a")

def status_dot(status):
    """Tiny menu-bar indicator (colored emoji) shown when usage is throttled."""
    s=(status or "").lower()
    if not s or s=="allowed": return ""
    if "reject" in s: return "⛔ "
    if "queue"  in s: return "⏳ "
    return "⚠️ "

def record_trend(real):
    """Append the account-wide u5/u7 sample (deduped by ts); keep ~24h. Returns the series."""
    try:
        data=json.load(open(TREND))
        if not isinstance(data,list): data=[]
        data=[d for d in data if isinstance(d,list) and len(d)==3]
    except Exception: data=[]
    if real and real.get("u5") is not None:
        ts=int(real["ts"])
        if not data or int(data[-1][0])!=ts:
            data.append([ts,round(real["u5"],4),round(real.get("u7") or 0,4)])
            cutoff=time.time()-24*3600
            data=[d for d in data if d[0]>=cutoff][-400:]
            try: os.makedirs(CFG,exist_ok=True); json.dump(data,open(TREND,"w"))
            except Exception: pass
    return data

def sparkline(data,hours=24,width=24):
    if not data: return None
    now=time.time(); span=hours*3600.0; start=now-span
    bins=[None]*width
    for ts,u5,_ in data:
        if ts<start: continue
        i=min(int((ts-start)/span*width),width-1)
        bins[i]=u5 if bins[i] is None else max(bins[i],u5)
    if all(b is None for b in bins): return None
    BL="▁▂▃▄▅▆▇█"
    return "".join("·" if b is None else BL[min(int(b*7.999),7)] for b in bins)

def burn_rate(data,mins=45):
    """Recent 5h-utilization slope as %/hour (0 on reset/idle, None if too few samples)."""
    if not data: return None
    now=time.time(); pts=[(ts,u5) for ts,u5,_ in data if ts>=now-mins*60]
    if len(pts)<2: return None
    dt=pts[-1][0]-pts[0][0]
    if dt<300: return None
    return max((pts[-1][1]-pts[0][1])/dt*3600*100, 0.0)

def insight(tw,by_model):
    total=tw["in"]+tw["cr"]+tw["cw"]
    if total<100_000: return None
    cr=tw["cr"]/max(1,total)
    opus=sum(v for m,v in by_model.items() if "opus" in m.lower()); tot=sum(by_model.values()) or 1.0
    if cr>0.85:
        return f"💡 {round(cr*100)}% cached context, /compact more often"
    if opus/tot>0.9:
        return "💡 Mostly Opus, try Sonnet for routine work"
    return f"💡 cache {round(cr*100)}% · Opus {round(opus/tot*100)}% of spend"

# ---- alerts (background desktop notifications) ----------------------------
def check_alerts(real, levels):
    if not real: return
    try:
        st=json.load(open(ALERTS))
        if not isinstance(st,dict): st={}
    except Exception: st={}
    changed=False
    for key,util,reset,label in (("5h",real.get("u5"),real.get("r5"),"5-hour"),
                                  ("7d",real.get("u7"),real.get("r7"),"weekly")):
        if util is None or not reset: continue
        pct=util*100; s=st.get(key) or {}
        if s.get("reset")!=reset:                                    # window rolled over
            if s.get("reset") is not None and s.get("notified",0)>0: # only if we'd warned last window
                notify("claude-meter", f"{label} window reset, full capacity again")
            s={"reset":reset,"notified":0}; changed=True
        crossed=max([t for t in levels if pct>=t] or [0])
        if crossed>s.get("notified",0):
            notify("claude-meter", f"{label} usage at {pct:.0f}%, resets in {cd(reset)}")
            s["notified"]=crossed; changed=True
        st[key]=s
    if changed:
        os.makedirs(CFG,exist_ok=True); json.dump(st,open(ALERTS,"w"))

# ---- main ----------------------------------------------------------------
def main():
    args=sys.argv[1:]
    cfg=load_config()
    if args and args[0]=="--resume":                                 # row-click action
        open_session(args[1] if len(args)>1 else "", args[2] if len(args)>2 else "", cfg)
        return
    if args and args[0]=="--rename":                                 # opt-click action
        sid=args[1] if len(args)>1 else ""
        if sid:
            names=load_names(); new=prompt_name(names.get(sid,""))
            if new is not None:
                new=new.strip()
                if new: names[sid]=new
                else: names.pop(sid,None)                             # blank input resets to auto title
                save_names(names)
        return
    force="--force" in args
    names=load_names()

    now=datetime.now(timezone.utc).astimezone()
    start_today=now.replace(hour=0,minute=0,second=0,microsecond=0)
    d7=now-timedelta(days=7); d30=now-timedelta(days=30)
    wstart=now.replace(hour=23,minute=0,second=0,microsecond=0)
    while wstart.weekday()!=1 or wstart>now: wstart-=timedelta(days=1)

    by_model=defaultdict(float); win=defaultdict(float); daily=defaultdict(float); tw=defaultdict(int)
    events=[]; earliest=None; today=now.date(); sessions={}
    for fp in glob.glob(os.path.expanduser("~/.claude/projects/**/*.jsonl"),recursive=True):
        s=sessions.setdefault(fp,{"sid":os.path.basename(fp)[:-6],"cwd":None,"title":None,
                                  "cost":0.0,"ctx":0,"subagents":0,"last":None})
        with open(fp,errors="ignore") as f:
            for line in f:
                try: o=json.loads(line)
                except: continue
                if not isinstance(o,dict): continue
                if s["cwd"] is None and o.get("cwd"): s["cwd"]=o["cwd"]
                if o.get("aiTitle"): s["title"]=o["aiTitle"]
                msg=o.get("message")
                if not isinstance(msg,dict): continue
                if msg.get("role")=="assistant" and isinstance(msg.get("content"),list):
                    for it in msg["content"]:
                        if isinstance(it,dict) and it.get("type")=="tool_use" and it.get("name")=="Task":
                            s["subagents"]+=1
                u=msg.get("usage"); model=msg.get("model")
                if not isinstance(u,dict) or model=="<synthetic>": continue
                try: t=datetime.fromisoformat(o["timestamp"].replace("Z","+00:00")).astimezone()
                except: continue
                c=cost(u,model); events.append((t,c)); by_model[model]+=c
                earliest=t if earliest is None or t<earliest else earliest
                win["all"]+=c; daily[t.date()]+=c
                if t>=start_today: win["today"]+=c
                if t>=d30: win["30d"]+=c
                if t>=wstart:
                    win["week"]+=c
                    tw["in"]+=u.get("input_tokens") or 0; tw["out"]+=u.get("output_tokens") or 0
                    tw["cr"]+=u.get("cache_read_input_tokens") or 0; tw["cw"]+=u.get("cache_creation_input_tokens") or 0
                s["cost"]+=c
                ctx=(u.get("input_tokens") or 0)+(u.get("cache_read_input_tokens") or 0)+(u.get("cache_creation_input_tokens") or 0)
                if s["last"] is None or t>=s["last"]:   # live context = the LATEST request's prompt, not the session peak (stale after /compact)
                    s["last"]=t; s["ctx"]=ctx

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
    trend_data=record_trend(real)
    check_alerts(real if src in ("live","cached","stale") else None, cfg["alert_levels"])

    if real and real.get("u5") is not None:
        b_pct=real["u5"]*100; w_pct=(real.get("u7") or 0)*100
        b_reset=f"resets {when(real['r5'])} · in {cd(real['r5'])}" if real.get("r5") else ""
        w_reset=f"resets {when(real['r7'])} · in {cd(real['r7'])}" if real.get("r7") else ""
        srcline=(f"● live · {ago(real['ts'])}" if src in ("live","cached")
                 else f"◐ stale · {ago(real['ts'])}")
        accountwide=True
    else:
        blimit=override("claude_limit.txt") or max((b["cost"] for b in blocks),default=0.0) or 1.0
        wlimit=override("claude_weekly_limit.txt") or (win["week"] or 1.0)
        b_pct=min(bcost/blimit*100,999); w_pct=min(win["week"]/wlimit*100,999)
        b_reset=("resets in "+cd((active["start"]+B).timestamp())) if active else "idle"
        w_reset="resets "+when((wstart+timedelta(days=7)).timestamp())
        srcline="○ proxy · API offline"
        accountwide=False

    active_cut=now-timedelta(minutes=cfg["active_min"])
    heavy=[s for s in sessions.values() if s["last"] and s["last"]>=active_cut and s["cost"]>0.005
           and not s["sid"].startswith("agent-")]  # active only; agent-* aren't resumable
    heavy.sort(key=lambda s:-s["cost"]); heavy=heavy[:5]

    last7=[(today-timedelta(days=i)) for i in range(6,-1,-1)]
    last7=[(d,daily.get(d,0.0)) for d in last7]
    dmax=max((c for _,c in last7),default=0) or 1.0
    since=earliest.strftime("%b %d") if earliest else "?"
    MONO="font=Menlo size=13"; BIG="font=Menlo size=15"; SM="font=Menlo size=12"
    TXT="color=#1d1d1f,#f5f5f7"   # primary text, high contrast in light & dark
    DIM="color=#6e6e73,#aeaeb2"   # secondary captions, readable, not faint
    # SF Symbols ignore color=; each row tints its icon via its own sfcolor=light,dark
    SH=cfg["show"]; OUT=[]; p=OUT.append   # buffer so hidden sections leave no orphan separators

    dot=status_dot(real.get("status") if real else None)
    if cfg["dual_title"]:
        p(f"{dot}{gauge(b_pct)} {b_pct:.0f}  {gauge(w_pct)} {w_pct:.0f} | color={clr(max(b_pct,w_pct))}")
    else:
        tp = w_pct if cfg.get("title_window")=="weekly" else b_pct
        p(f"{dot}{gauge(tp)} {tp:.0f}% | color={clr(tp)}")
    p("---")
    sb=status_banner(real.get("status") if real else None)
    if sb:
        p(f"{sb[0]} | size=13 color={sb[1]}")
        p("---")
    # two windows: one bold bar line + one small meta line each
    for label,pct,resettext,util,reset,L in (
            ("5h  ",b_pct,b_reset,(real or {}).get("u5"),(real or {}).get("r5"),L5),
            ("week",w_pct,w_reset,(real or {}).get("u7"),(real or {}).get("r7"),L7)):
        p(f"{label} {pbar(pct)} {pct:>3.0f}% | {BIG} color={clr(pct)}")
        p(f"  {resettext} | font=Menlo size=11 {DIM}")
        fc=forecast(util,reset,L) if SH["forecast"] else None
        if fc:
            p(f"  {fc[0]} | font=Menlo size=11 color={fc[1]}")
    br=burn_rate(trend_data)                                  # recent slope (best when active)
    if (br is None or br<0.5) and real and real.get("r5"):        # idle/sparse → window-average rate
        el=L5-(real["r5"]-time.time())
        if el>300: br=real["u5"]/max(el,WARMUP)*3600*100
    if SH["burn"] and br and br>=1:
        p(f"burn ~{br:.0f}%/hr | {SM} {TXT} {sftint('flame.fill','#ff6a00')}")
    if SH["trend"]:
        spark=sparkline(trend_data,width=16) if accountwide else None
        if spark:
            p(f"5h 24h ▕{spark}▏ {b_pct:.0f}% | {SM} {TXT} {sftint('chart.line.uptrend.xyaxis','#0a84ff')}")
    p("---")
    p(f"{srcline} · ↻ refresh | {SM} {TXT} bash={SELF} param1=--force terminal=false refresh=true")
    if SH["sessions"]:
        p("---")
        p(f"Active sessions · this machine | size=11 {DIM} {sftint('bolt.fill','#ff9500')}")
        if heavy:
            p(f"click → resume · ⌥click → rename | size=10 {DIM}")
            for s in heavy:
                lbl=sanitize(names.get(s["sid"]) or s["title"] or (os.path.basename(s["cwd"]) if s["cwd"] else s["sid"][:8]))[:18]
                ctx=f"{s['ctx']/1000:.0f}k" if s["ctx"] else "-"
                p(f"{lbl}  ${s['cost']:.0f} · {ctx} · {ago(s['last'].timestamp())} | {SM} {TXT} bash={SELF} "
                  f"param1=--resume param2={pq(s['sid'])} param3={pq(s['cwd'] or '')} terminal=false")
                p(f"✎ rename {lbl} | alternate=true {SM} {DIM} bash={SELF} "
                  f"param1=--rename param2={pq(s['sid'])} terminal=false refresh=true")
        else:
            p(f"no active sessions in the last {cfg['active_min']}m | {SM} {DIM}")
    if SH["insight"]:
        ins=insight(tw,by_model)
        if ins:
            p("---")
            p(f"{ins.replace('💡 ','')} | size=11 {TXT} {sftint('lightbulb.fill','#e6a700')}")
    if SH["cost"]:
        p("---")
        p(f"Cost & history (local $ proxy) | {SM} {TXT} {sftint('dollarsign.circle','#30a14e')}")
        p(f"--Per day (last 7) | size=11 {DIM}")
        for d,c in last7:
            tag=" ←today" if d==today else ""
            p(f"--{d.strftime('%a')} ▕{hbar(c/dmax)}▏ ${c:>4.0f}{tag} | {SM} {TXT}")
        p(f"--Today ${win['today']:,.0f}  ·  week ${win['week']:,.0f}  ·  30d ${win['30d']:,.0f} | {MONO} {TXT}")
        p(f"--All-time ${win['all']:,.0f}  (since {since}) | {MONO} {TXT}")
        p(f"--By model | size=11 {DIM}")
        for m,v in sorted(by_model.items(),key=lambda x:-x[1]):
            p(f"--{sanitize(m).replace('claude-',''):20} ${v:>8,.2f} | {SM} {TXT}")
        p(f"--$ = equivalent API cost · local proxy, not billed on Pro/Max | size=10 {DIM}")
    if SH["links"]:
        p("---")
        p(f"Links | {SM} {TXT} {sftint('link','#0a84ff')}")
        p(f"--claude-meter on GitHub | href={REPO_URL} {sftint('chevron.left.forwardslash.chevron.right','#af52de')}")
        p(f"--Open ~/.claude | bash=/usr/bin/open param1={pq(os.path.expanduser('~/.claude'))} terminal=false {sftint('folder','#0a84ff')}")
        p(f"--Anthropic status | href=https://status.anthropic.com {sftint('antenna.radiowaves.left.and.right','#30a14e')}")

    out=[]                                  # collapse duplicate / leading / trailing separators
    for ln in OUT:
        if ln=="---" and (not out or out[-1]=="---"): continue
        out.append(ln)
    while out and out[-1]=="---": out.pop()
    print("\n".join(out))

if __name__=="__main__":
    try:
        main()
    except Exception as e:                       # a plugin must never show a broken menu
        print("◌ | color=#8e8e93")
        print("---")
        print(f"claude-meter hiccup ({type(e).__name__}) · ↻ retry | size=11 color=#8e8e93 "
              f"bash={SELF} param1=--force terminal=false refresh=true")   # type only, no message/paths
