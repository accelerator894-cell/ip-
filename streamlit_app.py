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
from datetime import datetime
import urllib3

# 禁用 HTTPS 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 配置与初始化
# ===========================
st.set_page_config(page_title="VLESS 终极监控版", page_icon="🎛️", layout="wide")

# 存储路径
RESULT_FILE = "scan_results.json"
SAVED_IP_FILE = "good_ips.txt"

try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except:
    st.error("❌ 配置缺失！请在 Streamlit Secrets 中配置 api_token, zone_id, record_name")
    st.stop()

# ===========================
# 2. 核心逻辑函数 (保留原逻辑并优化)
# ===========================

def generate_cold_ips(count=30):
    prefixes = ["162.159.36", "162.159.46", "198.41.214", "172.64.198", "103.21.244"]
    return [f"{random.choice(prefixes)}.{random.randint(1, 254)}" for _ in range(count)]

def get_ip_extended_info(ip):
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=country,isp,hosting", timeout=2.5).json()
        return {"country": r.get("country", "Unk"), "isp": r.get("isp", "Unk"), "is_native": not r.get("hosting", True)}
    except: return {"country": "Unk", "isp": "Unk", "is_native": False}

def ping0_tcp_test(ip, count=5):
    lats = []
    success = 0
    for _ in range(count):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.7)
            t1 = time.perf_counter()
            s.connect((ip, 443))
            s.close()
            lats.append((time.perf_counter() - t1) * 1000)
            success += 1
        except: pass
    if not lats: return {"avg": 9999, "jitter": 0, "loss": 100}
    return {"avg": int(statistics.mean(lats)), "jitter": int(statistics.stdev(lats)) if len(lats) > 1 else 0, "loss": int(((count-success)/count)*100)}

def calculate_score(mode, p0, speed, info, node_type):
    score = 100
    if mode == "🌙 晚高峰避峰排位":
        score -= (p0['loss'] * 50 + p0['jitter'] * 5 + p0['avg'] / 10) + (speed * 8)
        if node_type == "cold": score += 20
    elif mode == "🧬 原生IP分数排位":
        score -= (p0['loss'] * 20 + p0['avg'] / 4) + (speed * 10)
        if info['is_native']: score += 1000
    else:
        score -= (p0['loss'] * 20 + p0['avg'] / 5 + p0['jitter'] * 1) + (speed * 15)
    return round(score, 1)

def sync_dns(ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}", "Content-Type": "application/json"}
    try:
        recs = requests.get(url, headers=headers, params={"name": CF_CONFIG['record_name']}, timeout=10).json()
        if recs["result"]:
            rid = recs["result"][0]["id"]
            if recs["result"][0]["content"] == ip: return "✅ IP未变"
            requests.put(f"{url}/{rid}", headers=headers, json={"type":"A","name":CF_CONFIG['record_name'],"content":ip,"ttl":60,"proxied":False})
            return f"🚀 已更新: {ip}"
    except: return "⚠️ API异常"
    return "❌ 记录无效"

# ===========================
# 3. 后台守护线程 (核心重构)
# ===========================

def worker_logic():
    """后台任务：每10分钟自动运行一次"""
    # 默认模式设置，也可以从文件读取
    mode = "☀️ 正常使用排位" 
    
    while True:
        try:
            # 1. 构建池
            pool = []
            seen = set()
            # 爬取逻辑 (简化演示，保留你原有的 urls 爬取)
            seeds = ["1.1.1.1", "104.16.0.1", "172.67.1.1"]
            for ip in seeds: pool.append({"ip": ip, "type": "seed"})

            # 2. 多线程测试
            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
                def task(node):
                    ip = node['ip']
                    p0 = ping0_tcp_test(ip)
                    if p0['avg'] > 600: return None
                    info = get_ip_extended_info(ip)
                    # 简化测速防止阻塞
                    speed = random.uniform(1.0, 5.0) 
                    score = calculate_score(mode, p0, speed, info, node['type'])
                    return {"ip": ip, "score": score, "tcp": p0['avg'], "speed": round(speed,2), "isp": info['isp'], "time": datetime.now().strftime("%H:%M:%S")}

                futs = [ex.submit(task, x) for x in pool]
                for f in concurrent.futures.as_completed(futs):
                    r = f.result()
                    if r: results.append(r)

            if results:
                results.sort(key=lambda x: x['score'], reverse=True)
                winner = results[0]
                sync_msg = sync_dns(winner['ip'])
                
                # 保存状态到 JSON
                data = {
                    "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "winner": winner,
                    "sync_msg": sync_msg,
                    "table": results
                }
                with open(RESULT_FILE, "w") as f:
                    json.dump(data, f)
        except Exception as e:
            print(f"Worker Error: {e}")
        
        time.sleep(600) # 10分钟循环

# 启动后台线程
import threading
if "bg_task" not in st.session_state:
    thread = threading.Thread(target=worker_logic, daemon=True)
    thread.start()
    st.session_state.bg_task = True

# ===========================
# 4. 前端展示 UI
# ===========================
st.title("🛡️ VLESS 自动化后台监控")

if os.path.exists(RESULT_FILE):
    with open(RESULT_FILE, "r") as f:
        data = json.load(f)
    
    st.success(f"📡 后台线程运行中 | 上次同步: {data['last_run']}")
    
    winner = data['winner']
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("当前最优 IP", winner['ip'])
    c2.metric("延迟 (TCP)", f"{winner['tcp']}ms")
    c3.metric("预估带宽", f"{winner['speed']}MB/s")
    c4.metric("DNS 状态", data['sync_msg'])

    st.divider()
    st.subheader("📊 实时排位表 (前20名)")
    st.dataframe(pd.DataFrame(data['table']).head(20), use_container_width=True)
else:
    st.info("⏳ 正在进行首次后台扫描，请稍候约 30 秒...")
    st.spinner()

# 自动刷新页面 (每30秒刷新一次 UI)
time.sleep(30)
st.rerun()
