import streamlit as st
import requests
import time
import re
import random
import os
import json
import pandas as pd
import concurrent.futures
import statistics
import socket
from datetime import datetime, timedelta
import urllib3

# 禁用 HTTPS 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 页面配置与持久化路径
# ===========================
st.set_page_config(page_title="VLESS 终极全能监控版", page_icon="🎛️", layout="wide")

RESULT_FILE = "scan_results.json"
CONFIG_FILE = "app_config.json"
SAVED_IP_FILE = "good_ips.txt"

# 注入 CSS
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    div[data-testid="column"] { background-color: #1a1c24; border: 1px solid #2d3139; border-radius: 8px; padding: 15px; }
    .badge-normal { background-color: #2ECC40; color: #000; padding: 4px 10px; border-radius: 4px; font-weight: bold; }
    .badge-peak { background-color: #0074D9; color: #fff; padding: 4px 10px; border-radius: 4px; font-weight: bold; }
    .badge-native { background-color: #B10DC9; color: #fff; padding: 4px 10px; border-radius: 4px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 核心功能函数 (完全保留原始逻辑)
# ===========================

def get_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f: return json.load(f)
    return {"mode": "☀️ 正常使用排位"}

def save_config(mode):
    with open(CONFIG_FILE, "w") as f: json.dump({"mode": mode}, f)

def generate_cold_ips(count=30):
    prefixes = ["162.159.36", "162.159.46", "198.41.214", "172.64.198", "103.21.244"]
    return [f"{random.choice(prefixes)}.{random.randint(1, 254)}" for _ in range(count)]

def get_ip_extended_info(ip):
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=country,isp,hosting", timeout=2.5).json()
        return {"country": r.get("country", "Unk"), "isp": r.get("isp", "Unk"), "is_native": not r.get("hosting", True)}
    except: return {"country": "Unk", "isp": "Unk", "is_native": False}

def ping0_tcp_test(ip, count=5):
    lats, success = [], 0
    for _ in range(count):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.7); t1 = time.perf_counter()
            s.connect((ip, 443)); s.close()
            lats.append((time.perf_counter() - t1) * 1000); success += 1
        except: pass
    if not lats: return {"avg": 9999, "jitter": 0, "loss": 100}
    return {"avg": int(statistics.mean(lats)), "jitter": int(statistics.stdev(lats)) if len(lats) > 1 else 0, "loss": int(((count-success)/count)*100)}

def sync_dns(ip):
    try:
        cfg = st.secrets
        url = f"https://api.cloudflare.com/client/v4/zones/{cfg['zone_id']}/dns_records"
        headers = {"Authorization": f"Bearer {cfg['api_token']}", "Content-Type": "application/json"}
        recs = requests.get(url, headers=headers, params={"name": cfg['record_name']}, timeout=10).json()
        if recs["result"]:
            rid = recs["result"][0]["id"]
            if recs["result"][0]["content"] == ip: return "✅ IP未变"
            requests.put(f"{url}/{rid}", headers=headers, json={"type":"A","name":cfg['record_name'],"content":ip,"ttl":60,"proxied":False})
            return f"🚀 已更新: {ip}"
    except: return "⚠️ API/Secrets异常"
    return "❌ 记录无效"

# ===========================
# 3. 后台守护线程逻辑 (整合全功能)
# ===========================

def background_worker():
    while True:
        try:
            current_mode = get_config()["mode"]
            pool, seen = [], set()
            
            # 1. 爬虫源复活
            urls = ["https://www.cloudflare.com/ips-v4", 
                    "https://raw.githubusercontent.com/DerGoogler/CloudFlare-IP-Best/main/ip.txt"]
            for u in urls:
                try: 
                    ips = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', requests.get(u, timeout=10).text)
                    for ip in random.sample(ips, min(len(ips), 100)):
                        if ip not in seen: pool.append({"ip": ip, "type": "hot"}); seen.add(ip)
                except: pass

            # 2. 避峰模式注入
            if current_mode == "🌙 晚高峰避峰排位":
                for ip in generate_cold_ips(50):
                    if ip not in seen: pool.append({"ip": ip, "type": "cold"}); seen.add(ip)

            # 3. 多线程深度测试 (保留原始评分)
            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
                def run_test(node):
                    ip = node['ip']
                    p0 = ping0_tcp_test(ip)
                    if p0['avg'] > 800: return None
                    info = get_ip_extended_info(ip)
                    
                    # 测速逻辑
                    speed = 0.0
                    try:
                        s_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes=2000000", headers={"Host": "speed.cloudflare.com"}, timeout=4)
                        if r.status_code == 200: speed = (len(r.content)/1024/1024) / (time.perf_counter() - s_t)
                    except: pass

                    # 原始评分引擎
                    score = 100
                    if current_mode == "🌙 晚高峰避峰排位":
                        score -= (p0['loss']*50 + p0['jitter']*5 + p0['avg']/10) + (speed*8)
                        if node['type'] == "cold": score += 20
                    elif current_mode == "🧬 原生IP分数排位":
                        score -= (p0['loss']*20 + p0['avg']/4) + (speed*10)
                        if info['is_native']: score += 1000
                    else:
                        score -= (p0['loss']*20 + p0['avg']/5 + p0['jitter']*1) + (speed*15)
                    
                    return {**node, "score": round(score,1), "tcp": p0['avg'], "jitter": p0['jitter'], 
                            "loss": p0['loss'], "speed": round(speed,2), "isp": info['isp'], 
                            "is_native": info['is_native'], "country": info['country']}

                futs = [ex.submit(run_test, n) for n in pool]
                for f in concurrent.futures.as_completed(futs):
                    res = f.result()
                    if res: results.append(res)

            if results:
                results.sort(key=lambda x: x['score'], reverse=True)
                winner = results[0]
                sync_msg = sync_dns(winner['ip'])
                # 保存结果
                with open(RESULT_FILE, "w") as f:
                    json.dump({"last_run": datetime.now().strftime("%H:%M:%S"), "winner": winner, "sync_msg": sync_msg, "table": results[:30]}, f)
        except Exception as e: print(f"Worker Error: {e}")
        time.sleep(600)

# 启动线程
import threading
if "worker_active" not in st.session_state:
    threading.Thread(target=background_worker, daemon=True).start()
    st.session_state.worker_active = True

# ===========================
# 4. 前端展示 (找回 Badge 和 酷炫 UI)
# ===========================
with st.sidebar:
    st.header("⚙️ 策略中心")
    current_cfg = get_config()
    new_mode = st.radio("🎯 排位策略", ["☀️ 正常使用排位", "🌙 晚高峰避峰排位", "🧬 原生IP分数排位"], index=["☀️ 正常使用排位", "🌙 晚高峰避峰排位", "🧬 原生IP分数排位"].index(current_cfg["mode"]))
    if new_mode != current_cfg["mode"]:
        save_config(new_mode)
        st.toast(f"已切换至: {new_mode}, 下次扫描生效")

st.title("🎛️ VLESS 终极全能监控版")

if os.path.exists(RESULT_FILE):
    with open(RESULT_FILE, "r") as f: data = json.load(f)
    winner = data['winner']
    
    st.success(f"🔄 后台守护中 | 模式: {new_mode} | 上次更新: {data['last_run']}")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("冠军 IP", winner['ip'])
    c2.metric("延迟", f"{winner['tcp']}ms", f"±{winner['jitter']}")
    c3.metric("测速", f"{winner['speed']}MB/s")
    c4.metric("解析状态", data['sync_msg'])

    st.divider()
    df = pd.DataFrame(data['table'])
    st.dataframe(df[['score', 'ip', 'tcp', 'speed', 'isp', 'is_native', 'country']], use_container_width=True)
else:
    st.warning("⏳ 正在初始化后台任务，请等待首次扫描结果...")

time.sleep(30)
st.rerun()
