# ================= Cloudflare Hunter Scheduler =================
# 工程级 IP 调度 + 进化系统

import streamlit as st
import requests, time, json, random, re, socket, threading, subprocess
import pandas as pd
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
import concurrent.futures
import ipaddress

# ================= 基础 =================
BASE = Path(__file__).parent
FILES = {
    "db": BASE / "ip_db.json",
    "state": BASE / "runtime_state.json",
    "config": BASE / "config.json",
}

def load(p, d):
    if not p.exists(): return d
    try: return json.loads(p.read_text())
    except: return d

def save(p, d):
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False))

# ================= 配置 =================
CONFIG = load(FILES["config"], {
    "mode": "normal",
    "switch_threshold": 70,
    "hold_threshold": 85,
    "max_workers": 50
})

# ================= 稳定 EMA =================
def ema(old, new, a=0.3):
    return new if old is None else old * (1 - a) + new * a

# ================= TLS / Reality 探测 =================
def tls_capable(ip):
    try:
        p = subprocess.run(
            ["openssl", "s_client", "-connect", f"{ip}:443",
             "-servername", "www.cloudflare.com", "-alpn", "h2"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=3
        )
        out = p.stdout.decode(errors="ignore")
        return "TLSv1.3" in out and "ALPN protocol: h2" in out
    except:
        return False

# ================= IP 测试 =================
def test_ip(ip):
    t0 = time.time()
    try:
        s = socket.create_connection((ip, 443), timeout=1)
        latency = (time.time() - t0) * 1000
        s.close()

        r = requests.get(
            f"http://{ip}/__down?bytes=150000",
            headers={"Host": "speed.cloudflare.com"},
            timeout=4, stream=True
        )
        size = sum(len(c) for c in r.iter_content(65536))
        speed = size / 1024 / 1024 / 4

        score = round(100 - latency / 4 + min(speed * 6, 50), 1)
        return latency, speed, score
    except:
        return None, None, 0

# ================= 调度核心 =================
def scheduler_loop():
    db = load(FILES["db"], {})
    state = load(FILES["state"], {"current_ip": None})

    while True:
        current = state.get("current_ip")

        # 判断是否需要换 IP
        if current:
            stable = db[current]["stable"]
            if stable >= CONFIG["hold_threshold"]:
                time.sleep(5)
                continue

        # 选择候选
        candidates = sorted(
            db.items(),
            key=lambda x: x[1]["stable"],
            reverse=True
        )

        for ip, meta in candidates:
            if meta["stable"] < CONFIG["switch_threshold"]:
                continue
            state["current_ip"] = ip
            save(FILES["state"], state)
            break

        time.sleep(5)

# ================= 主引擎 =================
def engine():
    db = load(FILES["db"], {})

    while True:
        ips = list(db.keys())
        with concurrent.futures.ThreadPoolExecutor(40) as ex:
            for ip, (lat, spd, score) in zip(ips, ex.map(test_ip, ips)):
                if score <= 0: continue

                meta = db.setdefault(ip, {})
                meta["score"] = score
                meta["stable"] = ema(meta.get("stable"), score)
                meta["last"] = datetime.now().strftime("%H:%M:%S")

                if meta.get("tls") is None:
                    meta["tls"] = tls_capable(ip)

                meta["tags"] = {
                    "gpt": meta["tls"] and meta["stable"] > 80,
                    "stream": spd > 3
                }

        save(FILES["db"], db)
        time.sleep(10)

# ================= UI =================
if "run" not in st.session_state:
    threading.Thread(target=engine, daemon=True).start()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    st.session_state.run = True

st.title("🧬 Cloudflare Hunter · 调度器")

db = load(FILES["db"], {})
state = load(FILES["state"], {})

st.metric("当前使用 IP", state.get("current_ip", "无"))

df = pd.DataFrame([
    {"ip": ip, **meta} for ip, meta in db.items()
])

st.dataframe(df, use_container_width=True)