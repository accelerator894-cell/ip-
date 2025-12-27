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
from datetime import datetime, timedelta
import urllib3

# 禁用 HTTPS 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 页面配置
# ===========================
st.set_page_config(page_title="VLESS 电信全自动排位版", page_icon="🤖", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0b1623; color: #E0E0E0; }
    .stMetric { background-color: #162a47; border-radius: 10px; padding: 10px; border-left: 5px solid #005bac; }
    .auto-status { color: #2ECC40; font-weight: bold; animation: blinker 2s linear infinite; }
    @keyframes blinker { 50% { opacity: 0; } }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 配置加载
# ===========================
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except:
    st.error("❌ Secrets 配置缺失")
    st.stop()

DB_FILE = "telecom_racing.log"
SAVED_IP_FILE = "telecom_best_ips.txt"

# ===========================
# 3. 增强型爬虫与工具函数
# ===========================

def load_saved_ips():
    if not os.path.exists(SAVED_IP_FILE): return []
    with open(SAVED_IP_FILE, "r") as f:
        return list(set(re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', f.read())))

def get_enhanced_pool():
    """【高数量+高质量】爬虫逻辑"""
    competitors = []
    seen_ips = set()
    
    # A. 电信核心种子 (高质量保障)
    seeds = ["1.1.1.1", "1.0.0.1", "104.16.0.1", "172.67.1.1", "104.17.0.1", "104.19.0.1"]
    for ip in seeds:
        competitors.append({"ip": ip, "source": "💎 电信种子"})
        seen_ips.add(ip)

    # B. 历史精英
    for ip in load_saved_ips():
        if ip not in seen_ips:
            competitors.append({"ip": ip, "source": "💾 历史精英"})
            seen_ips.add(ip)

    # C. 多源高频率海选 (增加数量)
    urls = [
        "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
        "https://www.cloudflare.com/ips-v4",
        "https://raw.githubusercontent.com/vfarid/cf-ip-scanner/main/ips.txt",
        "https://raw.githubusercontent.com/stockrt/cloudflare-ips/master/cloudflare-ips.txt"
    ]
    
    scraped_pool = set()
    def fetch(url):
        try:
            r = requests.get(url, timeout=6, headers={'User-Agent': 'Mozilla/5.0'})
            return re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        except: return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        for res in ex.map(fetch, urls):
            for ip in res: scraped_pool.add(ip)
    
    # 随机抽取 200 个进行大规模排位
    scraped_list = list(scraped_pool)
    if scraped_list:
        picked = random.sample(scraped_list, min(len(scraped_list), 200))
        for ip in picked:
            if ip not in seen_ips:
                competitors.append({"ip": ip, "source": "🌊 深海爬虫"})
    
    return competitors

def tcp_ping(ip, timeout=0.7):
    try:
        start = time.time()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, 443))
        s.close()
        return int((time.time() - start) * 1000)
    except: return 9999

def deep_test_node(node):
    ip = node['ip']
    lats = []
    for _ in range(3):
        res = tcp_ping(ip)
        if res < 9999: lats.append(res)
    
    if not lats: return None
    
    avg_lat = statistics.mean(lats)
    loss = ((3 - len(lats)) / 3) * 100
    jitter = statistics.stdev(lats) if len(lats) > 1 else 0
    
    # 2MB 速度实测
    speed = 0.0
    try:
        s_time = time.time()
        r = requests.get(f"http://{ip}/__down?bytes=2000000", 
                         headers={"Host": "speed.cloudflare.com"}, timeout=4)
        if r.status_code == 200:
            speed = (len(r.content)/1024/1024) / (time.time() - s_time)
    except: pass

    # 电信专用评分公式
    score = 100 - (avg_lat / 5) - (loss * 15) - (jitter * 2) + (speed * 12)
    
    # 高质量节点自动存库
    if score > 88 and node['source'] == "🌊 深海爬虫":
        with open(SAVED_IP_FILE, "a") as f: f.write(f"{ip}\n")

    return {"ip": ip, "score": round(score, 1), "lat": int(avg_lat), "speed": round(speed, 2), "loss": int(loss), "source": node['source']}

def sync_dns(ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        recs = requests.get(url, headers=headers, params={"name": CF_CONFIG['record_name']}, timeout=5).json()
        if recs["result"]:
            rid = recs["result"][0]["id"]
            if recs["result"][0]["content"] == ip: return "已是最佳节点"
            requests.put(f"{url}/{rid}", headers=headers, json={"type":"A","name":CF_CONFIG['record_name'],"content":ip,"ttl":60,"proxied":False})
            return f"同步成功: {ip}"
    except: return "DNS同步异常"
    return "未找到记录"

# ===========================
# 4. 主逻辑
# ===========================
st.title("🤖 VLESS 电信自动化排位系统")

with st.sidebar:
    st.header("⚙️ 自动化设置")
    is_auto = st.toggle("开启自动轮巡模式", value=False)
    interval = st.select_slider("执行频率 (分钟)", options=[15, 30, 60, 120], value=30)
    st.divider()
    if is_auto:
        st.markdown(f"状态: <span class='auto-status'>● 自动运行中</span>", unsafe_allow_html=True)
        st.info(f"每 {interval} 分钟将自动刷新爬虫并重测")

manual_start = st.button("🚀 立即开始手动排位", type="primary", use_container_width=True)

# 自动运行触发逻辑
if "last_run" not in st.session_state: st.session_state.last_run = datetime.min

should_run = manual_start
if is_auto:
    if datetime.now() - st.session_state.last_run > timedelta(minutes=interval):
        should_run = True

if should_run:
    st.session_state.last_run = datetime.now()
    with st.status("📡 正在深度检索电信友好节点...", expanded=True) as status:
        pool = get_enhanced_pool()
        st.write(f"已获取 {len(pool)} 个待测样本...")
        
        results = []
        progress = st.progress(0)
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
            futs = [ex.submit(deep_test_node, n) for n in pool]
            for i, f in enumerate(concurrent.futures.as_completed(futs)):
                progress.progress((i+1)/len(pool))
                res = f.result()
                if res: results.append(res)
        
        status.update(label="✅ 排位赛结束！", state="complete")

    if results:
        results.sort(key=lambda x: x['score'], reverse=True)
        winner = results[0]
        
        # UI 展示
        st.success(f"🏆 电信冠军: {winner['ip']} ({winner['source']})")
        dns_msg = sync_dns(winner['ip'])
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("综合得分", winner['score'])
        c2.metric("延迟", f"{winner['lat']}ms")
        c3.metric("电信带宽", f"{winner['speed']}MB/s")
        c4.metric("解析状态", dns_msg)
        
        with st.expander("📊 查看完整排位表"):
            st.table(pd.DataFrame(results[:20]))
    
    # 自动重刷机制
    if is_auto:
        st.toast(f"任务完成，将在 {interval} 分钟后再次运行")
        time.sleep(5)
        st.rerun()
