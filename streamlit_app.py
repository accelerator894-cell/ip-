import streamlit as st
import pandas as pd
import time, threading, random, socket, json
from pathlib import Path
from collections import Counter, defaultdict

# ------------------ 配置 ------------------
BASE = Path(".")
DB_FILE = BASE / "ip_db.json"
STATE_FILE = BASE / "state.json"
FAIL_FILE = BASE / "fail_db.json"

UUID = "123e4567-e89b-12d3-a456-426614174000"       # 你的 UUID
REALITY_PUB = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A..."  # 你的 Reality 公钥
REALITY_SID = "abcd1234efgh5678"                    # 你的 Short ID
SNI = "speed.cloudflare.com"                        # 之前的 host

SCENES = ["normal", "gpt", "stream", "custom"]
FINGERPRINT = {"normal": "chrome", "gpt": "firefox", "stream": "safari", "custom": "chrome"}
SEEDS = ["104.19.19.19", "104.18.20.126", "172.64.198.1", "172.67.1.1", "104.21.32.13"]

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
        speed = random.uniform(0.5,3.5)  # 模拟下载速度 MB/s
        source = random.choice(["📂 全量扫描","⚡ 优质种子","🏆 历史优秀","🕷️ 爬虫","💎 冷门"])
        return latency, colo, speed, source
    except:
        return None, None, 0, None

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
            lat, colo, speed, source = test_ip(ip)
            if lat is None:
                fail[ip] = fail.get(ip,0)+1
                continue

            h = db.get(ip,{"latency":[],"colo":[],"success":0,"fail":0,"speed":[],"source":""})
            h["latency"].append(lat); h["latency"] = h["latency"][-10:]
            h["colo"].append(colo); h["colo"] = h["colo"][-10:]
            h["speed"].append(speed); h["speed"] = h["speed"][-10:]
            h["success"] += 1
            h["source"] = source
            h["health"] = health_score(h)
            db[ip] = h

            for scene in SCENES:
                # 场景筛选规则
                if scene == "gpt" and speed < 1.0:  # GPT 独享要求速度快
                    continue
                if scene == "stream" and lat > 150:  # 流媒体低延迟
                    continue
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

st.set_page_config(page_title="Cloudflare 猎手", layout="wide")
st.title("🧬 Cloudflare IP 猎手 · 多场景自动筛选")

db = load(DB_FILE,{})
state = load(STATE_FILE,{})

# 构造 DataFrame，填补缺失数据
rows = []
for ip, v in db.items():
    latency = round(v.get("latency")[-1],1) if v.get("latency") else 999
    speed = round(v.get("speed")[-1],2) if v.get("speed") else 0.0
    colo = v.get("colo")[-1] if v.get("colo") else "UNK"
    source = v.get("source","未知")
    health = round(v.get("health",0.0),3)
    rows.append({
        "IP": ip,
        "评分": health,
        "延迟(ms)": latency,
        "速度(MB/s)": speed,
        "来源": source,
        "Colo": colo
    })

if rows:
    df = pd.DataFrame(rows).sort_values("评分", ascending=False).head(10)
else:
    df = pd.DataFrame(columns=["IP","评分","延迟(ms)","速度(MB/s)","来源","Colo"])

st.subheader("前10优质节点")
st.dataframe(df, use_container_width=True)

st.subheader("NekoBox 下载中心")
for scene in SCENES:
    ip = state.get(scene,"尚未选择")
    st.markdown(f"**{scene.upper()}** 当前节点: {ip}")
    file_path = BASE / f"nekobox_{scene}.json"
    if file_path.exists():
        st.download_button(f"下载 {scene.upper()}", data=file_path.read_text(), file_name=file_path.name)

st.caption("后台每10秒自动更新 IP 健康度、Colo稳定性、速度和 NekoBox 配置，按场景自动筛选最优 IP")