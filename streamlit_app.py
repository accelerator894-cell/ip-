import streamlit as st
import pandas as pd
import time, threading, random, socket, json
from pathlib import Path
from collections import Counter

# ------------------ 配置 ------------------
BASE = Path(".")
DB_FILE = BASE / "ip_db.json"
STATE_FILE = BASE / "state.json"
FAIL_FILE = BASE / "fail_db.json"

UUID = "填写你的UUID"
REALITY_PUB = "填写你的Reality公钥"
REALITY_SID = "填写你的shortid"
SNI = "www.cloudflare.com"

SCENES = ["normal", "gpt", "stream"]
FINGERPRINT = {"normal": "chrome", "gpt": "firefox", "stream": "safari"}
SEEDS = ["104.19.19.19", "104.18.20.126", "172.64.198.1", "172.67.1.1"]

# ------------------ 文件操作 ------------------
def load(path, default):
    if not path.exists(): return default
    return json.loads(path.read_text())

def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

# ------------------ IP 测试 ------------------
def test_ip(ip):
    try:
        s = socket.socket()
        s.settimeout(1)
        t0 = time.time()
        s.connect((ip, 443))
        latency = (time.time() - t0) * 1000
        s.close()
        colo = random.choice(["SFO","LAX","NYC","SG","HK"])
        return latency, colo
    except:
        return None, None

# ------------------ 健康度模型 ------------------
def colo_stability(colos):
    if not colos: return 0
    c = Counter(colos)
    return c.most_common(1)[0][1] / len(colos)

def health_score(h):
    return round(
        colo_stability(h["colo"])*0.4 +
        (1 - min(sum(h["latency"])/len(h["latency"])/200,1))*0.3 +
        min(h["success"]/max(h["success"]+h["fail"],1),1)*0.3,
        3
    )

def should_switch(cur, cand):
    if cur is None: return True
    if cur.get("health",0) >= 0.85: return False
    return cand["health"] - cur.get("health",0) >= 0.15

# ------------------ NekoBox JSON ------------------
def export_nekobox(scene, ip):
    profile = {
        "log": {"level": "warn"},
        "inbounds": [
            {"type":"socks","tag":"socks-in","listen":"127.0.0.1","listen_port":10808}
        ],
        "outbounds":[
            {
                "type":"vless",
                "tag":f"CF-{scene.upper()}",
                "server":ip,
                "server_port":443,
                "uuid":UUID,
                "tls":{
                    "enabled":True,
                    "server_name":SNI,
                    "utls":{"enabled":True,"fingerprint":FINGERPRINT[scene]},
                    "reality":{"enabled":True,"public_key":REALITY_PUB,"short_id":REALITY_SID}
                },
                "transport":{"type":"tcp"}
            }
        ],
        "route":{"auto_detect_interface":True}
    }
    file_path = BASE / f"nekobox_{scene}.json"
    save(file_path, profile)
    return file_path

# ------------------ 后台线程 ------------------
def scheduler():
    db = load(DB_FILE,{})
    state = load(STATE_FILE,{})
    fail = load(FAIL_FILE,{})

    while True:
        for ip in SEEDS:
            lat, colo = test_ip(ip)
            if lat is None:
                fail[ip] = fail.get(ip,0)+1
                continue

            h = db.get(ip,{"latency":[],"colo":[],"success":0,"fail":0})
            h["latency"].append(lat); h["latency"] = h["latency"][-10:]
            h["colo"].append(colo); h["colo"] = h["colo"][-10:]
            h["success"] += 1
            h["health"] = health_score(h)
            db[ip] = h

            for scene in SCENES:
                cur_ip = state.get(scene)
                cur = db.get(cur_ip) if cur_ip else None
                if should_switch(cur,h):
                    state[scene] = ip
                    export_nekobox(scene, ip)
        save(DB_FILE,db)
        save(STATE_FILE,state)
        save(FAIL_FILE,fail)
        time.sleep(10)

# ------------------ Streamlit 前端 ------------------
if "started" not in st.session_state:
    threading.Thread(target=scheduler,daemon=True).start()
    st.session_state.started = True

st.title("Cloudflare IP 猎手 · Streamlit版")

db = load(DB_FILE,{})
state = load(STATE_FILE,{})

# 构造 DataFrame，保证 score 列存在
rows = []
for ip, v in db.items():
    rows.append({
        "ip": ip,
        "score": v.get("health",0),
        "latency": v.get("latency")[-1] if v.get("latency") else 0,
        "colo": v.get("colo")[-1] if v.get("colo") else "UNK"
    })

if rows:
    df = pd.DataFrame(rows)
else:
    df = pd.DataFrame(columns=["ip","score","latency","colo"])

df = df.sort_values("score", ascending=False).head(10)
st.dataframe(df)

st.subheader("NekoBox 下载链接")
for scene in SCENES:
    ip = state.get(scene,"尚未选择")
    st.markdown(f"**{scene.upper()}** 当前节点: {ip}")
    file_path = BASE / f"nekobox_{scene}.json"
    if file_path.exists():
        st.download_button(f"下载 {scene.upper()}", data=file_path.read_text(), file_name=file_path.name)

st.caption("后台每10秒更新一次 IP 健康度和 NekoBox 配置")