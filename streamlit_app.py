import streamlit as st
import requests
import time
import re
import random
import os
import pandas as pd
import concurrent.futures
import statistics
import socket
from datetime import datetime
import urllib3

# 禁用 HTTPS 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 页面配置
# ===========================
st.set_page_config(page_title="VLESS 竞速-电信增强版", page_icon="⚡", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0b1623; color: #E0E0E0; }
    .stMetric { background-color: #162a47; border-radius: 10px; padding: 10px; border-left: 5px solid #005bac; }
    div[data-testid="stExpander"] { background-color: #162a47; border: none; }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 核心配置 (请确保在 Streamlit Cloud Secrets 中配置)
# ===========================
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except Exception:
    st.error("❌ 配置缺失！请在 Secrets 中配置 api_token, zone_id, record_name")
    st.stop()

DB_FILE = "telecom_racing.log"
SAVED_IP_FILE = "telecom_best_ips.txt"

# ===========================
# 3. 补全缺失的工具函数
# ===========================

def load_saved_ips():
    """读取已保存的电信精英 IP"""
    if not os.path.exists(SAVED_IP_FILE): return []
    with open(SAVED_IP_FILE, "r") as f:
        content = f.read()
        return list(set(re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', content)))

def get_competitor_pool():
    """【补全】构建针对电信的选手池"""
    competitors = []
    seen_ips = set()
    
    # 1. 电信友好型种子选手 (直连表现较好的段)
    telecom_seeds = ["1.1.1.1", "1.0.0.1", "104.16.0.1", "172.67.1.1"]
    for ip in telecom_seeds:
        competitors.append({"ip": ip, "source": "🏠 电信种子"})
        seen_ips.add(ip)
        
    # 2. 加载本地历史精英
    saved = load_saved_ips()
    for ip in saved:
        if ip not in seen_ips:
            competitors.append({"ip": ip, "source": "💾 电信历史"})
            seen_ips.add(ip)
            
    # 3. 自动化海选 (增加更多源)
    target_total = 100 
    needed = target_total - len(competitors)
    
    if needed > 0:
        urls = [
            "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
            "https://www.cloudflare.com/ips-v4"
        ]
        scraped_pool = set()
        
        def fetch(url):
            try:
                resp = requests.get(url, timeout=5)
                return re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', resp.text)
            except: return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            for res in ex.map(fetch, urls):
                for ip in res: scraped_pool.add(ip)
        
        scraped_list = list(scraped_pool)
        if scraped_list:
            picked = random.sample(scraped_list, min(len(scraped_list), needed))
            for ip in picked:
                if ip not in seen_ips:
                    competitors.append({"ip": ip, "source": "☁️ 爬虫海选"})
    
    return competitors

def tcp_ping(ip, port=443, timeout=0.8):
    """电信链路快速探测"""
    try:
        start = time.time()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, port))
        s.close()
        return int((time.time() - start) * 1000)
    except:
        return 9999

def calculate_telecom_score(tcp_lat, jitter, loss, speed):
    """电信专属评分算法 (重罚丢包)"""
    score = 100
    if tcp_lat < 170: score += 25  # 电信香港/日本优选延迟
    elif tcp_lat > 280: score -= (tcp_lat - 280) / 2
    
    # 丢包是电信体验的核心痛点
    if loss > 0:
        score -= (loss * 15) + 40 
    
    score -= jitter * 2.5
    score += min(speed * 12, 60) # 速度加成
    return round(score, 1)

def deep_test_telecom(node):
    """深度评测逻辑"""
    ip = node['ip']
    latencies = []
    
    # 测试 3 次 TCP
    for _ in range(3):
        lat = tcp_ping(ip)
        if lat < 9999: latencies.append(lat)
        time.sleep(0.05)
    
    if not latencies: return None
    
    avg_tcp = statistics.mean(latencies)
    jitter = statistics.stdev(latencies) if len(latencies) > 1 else 0
    loss_rate = ((3 - len(latencies)) / 3) * 100

    # 针对电信的 2MB 实测
    speed_mb = 0.0
    try:
        s_time = time.time()
        r = requests.get(f"http://{ip}/__down?bytes=2000000", 
                         headers={"Host": "speed.cloudflare.com"}, timeout=5)
        if r.status_code == 200:
            speed_mb = (len(r.content)/1024/1024) / (time.time() - s_time)
    except: pass

    score = calculate_telecom_score(avg_tcp, jitter, loss_rate, speed_mb)
    
    is_elite = False
    if score > 85 and node['source'] == "☁️ 爬虫海选":
        with open(SAVED_IP_FILE, "a") as f:
            f.write(f"{ip}\n")
        is_elite = True

    return {
        "ip": ip, "source": node['source'], "is_new": is_elite,
        "tcp": int(avg_tcp), "jitter": int(jitter), 
        "loss": int(loss_rate), "speed": round(speed_mb, 2), "score": score
    }

def sync_dns(ip):
    """Cloudflare DNS 同步"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        recs = requests.get(url, headers=headers, params=params, timeout=5).json()
        if not recs.get("result"): return "❌ 解析不存在"
        rid = recs["result"][0]["id"]
        if recs["result"][0]["content"] == ip: return "✅ IP 已是最新"
        requests.put(f"{url}/{rid}", headers=headers, json={
            "type": "A", "name": CF_CONFIG['record_name'], "content": ip, "ttl": 60, "proxied": False
        })
        return f"🚀 已切换至电信优选: {ip}"
    except: return "⚠️ API 异常"

# ===========================
# 4. 主界面
# ===========================
st.title("🏎️ VLESS 竞速 - 电信(CT)专调版")

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    st.info("💡 优化策略：大幅提高丢包权重，增加 2MB 大流量实测，适配电信骨干网。")
with col2:
    if st.button("🧹 清空电信库"):
        if os.path.exists(SAVED_IP_FILE): os.remove(SAVED_IP_FILE)
        st.toast("库已重置")
with col3:
    start = st.button("🏁 开始电信专项赛", type="primary", use_container_width=True)

if start:
    tasks = get_competitor_pool()
    st.write(f"📡 正在检测 {len(tasks)} 个潜力节点...")
    progress = st.progress(0)
    
    results = []
    # 电信并发不宜过高，设定为 20 防止被运营商侧临时阻断
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        futs = [ex.submit(deep_test_telecom, t) for t in tasks]
        for i, fut in enumerate(concurrent.futures.as_completed(futs)):
            progress.progress((i + 1) / len(tasks))
            res = fut.result()
            if res: results.append(res)
            
    if results:
        results.sort(key=lambda x: x['score'], reverse=True)
        winner = results[0]
        
        st.success(f"🏆 电信冠军: {winner['ip']} | 来源: {winner['source']}")
        sync_msg = sync_dns(winner['ip'])
        
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("综合得分", winner['score'], "CT-Optimized")
        k2.metric("延迟", f"{winner['tcp']} ms")
        k3.metric("带宽", f"{winner['speed']} MB/s")
        k4.metric("丢包", f"{winner['loss']}%")
        
        st.caption(f"📝 {sync_msg}")
        
        st.divider()
        df = pd.DataFrame(results)
        st.dataframe(df[['score', 'ip', 'tcp', 'speed', 'loss', 'source']], use_container_width=True)
    else:
        st.error("❌ 未发现适合电信的节点。")
