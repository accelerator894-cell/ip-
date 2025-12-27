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
# 1. 页面配置与样式
# ===========================
st.set_page_config(page_title="VLESS 10分钟自动竞速版", page_icon="🏎️", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #001f3f; color: #E0E0E0; }
    div[data-testid="column"] { background-color: #003366; border: 1px solid #0074D9; border-radius: 8px; padding: 15px; }
    .auto-active { color: #2ECC40; font-weight: bold; animation: blinker 1s linear infinite; }
    @keyframes blinker { 50% { opacity: 0; } }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 基础配置
# ===========================
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except:
    st.error("❌ 配置缺失！请检查 secrets.toml")
    st.stop()

DB_FILE = "racing_history.log"
SAVED_IP_FILE = "good_ips.txt"

# ===========================
# 3. 核心功能函数 (保留原有地理/测速逻辑)
# ===========================

@st.cache_data(ttl=3600)
def get_ip_info(ip):
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country"
        r = requests.get(url, timeout=2).json()
        cc = r.get("countryCode", "UNK")
        if cc in ['CN', 'HK', 'TW', 'JP', 'KR', 'SG']: return "🌏 亚洲", r.get("country")
        if cc in ['US', 'CA', 'MX']: return "🇺🇸 美洲", r.get("country")
        if cc in ['DE', 'GB', 'FR', 'NL', 'RU']: return "🇪🇺 欧洲", r.get("country")
        return "🌍 其他", r.get("country")
    except: return "🛸 未知", "Unknown"

def tcp_ping(ip, port=443, timeout=0.8):
    try:
        start = time.time()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, port))
        s.close()
        return int((time.time() - start) * 1000)
    except: return 9999

def get_enhanced_pool():
    competitors = []
    seen_ips = set()
    # 电信种子
    seeds = ["1.1.1.1", "1.0.0.1", "104.16.0.1", "172.67.1.1"]
    for ip in seeds:
        competitors.append({"ip": ip, "source": "🏠 种子"})
        seen_ips.add(ip)
    
    # 爬虫源 (增加数量)
    urls = [
        "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
        "https://www.cloudflare.com/ips-v4"
    ]
    scraped_pool = set()
    def fetch(url):
        try: return re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', requests.get(url, timeout=5).text)
        except: return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        for res in ex.map(fetch, urls):
            for ip in res: scraped_pool.add(ip)
    
    picked = random.sample(list(scraped_pool), min(len(scraped_pool), 150))
    for ip in picked:
        if ip not in seen_ips:
            competitors.append({"ip": ip, "source": "☁️ 爬虫"})
    return competitors

def deep_test_node(node):
    ip = node['ip']
    lats = []
    for _ in range(3):
        p = tcp_ping(ip)
        if p < 9999: lats.append(p)
    
    if not lats: return None
    
    avg_tcp = statistics.mean(lats)
    loss = ((3 - len(lats)) / 3) * 100
    jitter = statistics.stdev(lats) if len(lats) > 1 else 0
    region, country = get_ip_info(ip)

    # 2MB 测速
    speed_mb = 0.0
    try:
        s_time = time.time()
        r = requests.get(f"http://{ip}/__down?bytes=2000000", headers={"Host": "speed.cloudflare.com"}, timeout=4)
        if r.status_code == 200:
            speed_mb = (len(r.content)/1024/1024) / (time.time() - s_time)
    except: pass

    # 电信评分
    score = 100 - (avg_tcp/5) - (loss*20) - (jitter*2) + (speed_mb*10)

    return {
        "ip": ip, "region": region, "country": country, 
        "source": node['source'], "score": round(score, 1),
        "tcp": int(avg_tcp), "speed": round(speed_mb, 2), 
        "loss": int(loss), "jitter": int(jitter)
    }

def sync_dns(ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        recs = requests.get(url, headers=headers, params={"name": CF_CONFIG['record_name']}, timeout=5).json()
        if recs["result"]:
            rid = recs["result"][0]["id"]
            if recs["result"][0]["content"] == ip: return "✅ IP未变"
            requests.put(f"{url}/{rid}", headers=headers, json={"type":"A","name":CF_CONFIG['record_name'],"content":ip,"ttl":60,"proxied":False})
            return f"🚀 已同步: {ip}"
    except: return "⚠️ API异常"
    return "❌ 记录不存在"

# ===========================
# 4. 自动化逻辑与界面
# ===========================
st.title("🏎️ VLESS 终极竞速 (10分钟自动版)")

# 初始化 Session State
if "last_run" not in st.session_state:
    st.session_state.last_run = datetime.min
if "auto_enabled" not in st.session_state:
    st.session_state.auto_enabled = False

with st.sidebar:
    st.header("⚙️ 自动化配置")
    st.session_state.auto_enabled = st.toggle("开启 10 分钟自动排位", value=st.session_state.auto_enabled)
    if st.session_state.auto_enabled:
        next_run = st.session_state.last_run + timedelta(minutes=10)
        time_left = next_run - datetime.now()
        if time_left.total_seconds() > 0:
            st.markdown(f"状态: <span class='auto-active'>● 等待中</span> (余 {int(time_left.total_seconds())}s)", unsafe_allow_html=True)
        else:
            st.markdown(f"状态: <span class='auto-active'>● 正在触发...</span>", unsafe_allow_html=True)

# 顶部布局
c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    st.info("💡 模式：每10分钟自动更新爬虫节点并优选延迟最低、带宽最高的节点解析。")
with c2:
    st.metric("上次运行时间", st.session_state.last_run.strftime('%H:%M:%S') if st.session_state.last_run != datetime.min else "从未运行")
with c3:
    manual_start = st.button("🏁 手动开始排位", type="primary", use_container_width=True)

# 触发条件判断
now = datetime.now()
auto_trigger = st.session_state.auto_enabled and (now - st.session_state.last_run >= timedelta(minutes=10))

if manual_start or auto_trigger:
    st.session_state.last_run = now
    with st.spinner("Stadium: 正在进行 10 分钟例行排位赛..."):
        tasks = get_enhanced_pool()
        progress = st.progress(0)
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
            futs = [ex.submit(deep_test_node, t) for t in tasks]
            for i, f in enumerate(concurrent.futures.as_completed(futs)):
                progress.progress((i + 1) / len(tasks))
                res = f.result()
                if res: results.append(res)
        
    if results:
        results.sort(key=lambda x: x['score'], reverse=True)
        winner = results[0]
        sync_msg = sync_dns(winner['ip'])
        
        st.success(f"🏆 冠军节点: {winner['ip']} | 地区: {winner['country']}")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("评分", winner['score'])
        k2.metric("延迟", f"{winner['tcp']}ms")
        k3.metric("速度", f"{winner['speed']}MB/s")
        k4.metric("解析", sync_msg)

        # 保留原版 Tab 展示
        df = pd.DataFrame(results)
        t1, t2, t3, t4 = st.tabs(["🌐 总榜单", "🌏 亚洲赛区", "🇺🇸 美洲赛区", "🇪🇺 欧洲赛区"])
        cols = ["score", "ip", "tcp", "speed", "loss", "country"]
        with t1: st.dataframe(df[cols], use_container_width=True)
        with t2: st.dataframe(df[df['region'] == "🌏 亚洲"][cols], use_container_width=True)
        with t3: st.dataframe(df[df['region'] == "🇺🇸 美洲"][cols], use_container_width=True)
        with t4: st.dataframe(df[df['region'] == "🇪🇺 欧洲"][cols], use_container_width=True)

    # 如果是自动模式，强制刷新进入下一个倒计时
    if st.session_state.auto_enabled:
        time.sleep(2)
        st.rerun()

# 自动刷新占位：如果没在运行但开启了自动，每10秒刷新一次页面看是否到点了
if st.session_state.auto_enabled:
    time.sleep(10)
    st.rerun()
