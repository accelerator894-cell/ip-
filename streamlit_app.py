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
# 1. 页面配置与原始样式保留
# ===========================
st.set_page_config(page_title="VLESS 终极竞速版", page_icon="🏎️", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #001f3f; color: #E0E0E0; }
    div[data-testid="column"] { background-color: #003366; border: 1px solid #0074D9; border-radius: 8px; padding: 15px; }
    div[data-testid="stMetricValue"] { color: #2ECC40 !important; }
    .auto-status { color: #FF851B; font-weight: bold; animation: blinker 1.5s linear infinite; }
    @keyframes blinker { 50% { opacity: 0; } }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 配置与文件逻辑
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
# 3. 核心工具函数 (保留地理位置与原始测速)
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
    """【补全】增强型爬虫：数量从 80 提升至 200，并加入电信种子"""
    competitors = []
    seen_ips = set()
    # 增加电信优选段
    seeds = ["1.1.1.1", "1.0.0.1", "104.16.0.1", "172.67.1.1", "108.162.194.1"]
    for ip in seeds:
        competitors.append({"ip": ip, "source": "🏠 优选种子"})
        seen_ips.add(ip)
    
    # 历史精英
    if os.path.exists(SAVED_IP_FILE):
        with open(SAVED_IP_FILE, "r") as f:
            for ip in re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', f.read()):
                if ip not in seen_ips:
                    competitors.append({"ip": ip, "source": "💾 历史"})
                    seen_ips.add(ip)

    # 增强爬虫源
    urls = [
        "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
        "https://www.cloudflare.com/ips-v4",
        "https://raw.githubusercontent.com/vfarid/cf-ip-scanner/main/ips.txt"
    ]
    scraped_pool = set()
    def fetch(url):
        try: return re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', requests.get(url, timeout=5).text)
        except: return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        for res in ex.map(fetch, urls):
            for ip in res: scraped_pool.add(ip)
    
    picked = random.sample(list(scraped_pool), min(len(scraped_pool), 150))
    for ip in picked:
        if ip not in seen_ips:
            competitors.append({"ip": ip, "source": "☁️ 爬虫"})
    return competitors

def deep_test_node(node):
    """【电信优化评分算法】保留所有原始数据采集"""
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

    # 2MB 测速 (针对电信大流量探测)
    speed_mb = 0.0
    try:
        s_time = time.time()
        r = requests.get(f"http://{ip}/__down?bytes=2000000", headers={"Host": "speed.cloudflare.com"}, timeout=4)
        if r.status_code == 200:
            speed_mb = (len(r.content)/1024/1024) / (time.time() - s_time)
    except: pass

    # 电信综合评分公式 (保留高质量保存逻辑)
    score = 100 - (avg_tcp/5) - (loss*20) - (jitter*2) + (speed_mb*10)
    
    if score > 85 and node['source'] == "☁️ 爬虫":
        with open(SAVED_IP_FILE, "a") as f: f.write(f"{ip}\n")

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
# 4. 主界面渲染 (完整保留原有布局)
# ===========================
st.title("🏎️ VLESS 竞速排位版 (电信自动增强型)")

# 侧边栏：新增自动化控制
with st.sidebar:
    st.header("⚙️ 自动化控制")
    is_auto = st.toggle("开启自动轮巡", value=False)
    interval = st.select_slider("执行频率 (分钟)", options=[15, 30, 60], value=30)
    if is_auto:
        st.markdown(f"状态: <span class='auto-status'>● 循环执行中</span>", unsafe_allow_html=True)
    st.divider()
    if st.button("🗑️ 清空精英库", use_container_width=True):
        if os.path.exists(SAVED_IP_FILE): os.remove(SAVED_IP_FILE)
        st.toast("已清空")

# 顶部三栏布局 (完全保留原版)
c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    st.info("💡 机制：完全按电信质量评分 + 自动保存海选节点 + 自动轮巡解析")
with c2:
    if "last_run" in st.session_state:
        st.metric("上次运行时间", st.session_state.last_run.strftime('%H:%M:%S'))
with c3:
    manual_start = st.button("🏁 开始排位赛", type="primary", use_container_width=True)

# 运行逻辑
if "last_run" not in st.session_state: st.session_state.last_run = datetime.min
should_run = manual_start or (is_auto and (datetime.now() - st.session_state.last_run > timedelta(minutes=interval)))

if should_run:
    st.session_state.last_run = datetime.now()
    with st.spinner("Stadium: 正在对全球节点进行电信级公平竞技..."):
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
        
        # 冠军展示 (完全保留原版样式)
        st.success(f"🏆 冠军节点: {winner['ip']} | 来源: {winner['source']} | 地区: {winner['country']}")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("综合得分", winner['score'], "电信优化")
        k2.metric("Ping0 (TCP)", f"{winner['tcp']} ms", "物理延迟")
        k3.metric("下载速度", f"{winner['speed']} MB/s")
        k4.metric("丢包/抖动", f"{winner['loss']}%", f"抖动 {winner['jitter']}")
        st.caption(f"📝 {sync_msg}")
        st.divider()

        # 数据表渲染 (完全保留原版 Tab 逻辑)
        df = pd.DataFrame(results)
        display_cols = {
            "score": "评分", "ip": "IP", "source": "来源", "tcp": "Ping0(ms)", 
            "speed": "速度(MB/s)", "loss": "丢包(%)", "country": "国家"
        }
        
        def show_table(data):
            if data.empty: st.warning("当前赛区无数据")
            else:
                st.dataframe(
                    data.rename(columns=display_cols)[list(display_cols.values())],
                    use_container_width=True, hide_index=True,
                    column_config={"评分": st.column_config.ProgressColumn(min_value=-50, max_value=120)}
                )

        t1, t2, t3, t4 = st.tabs(["🌐 总榜单", "🌏 亚洲赛区", "🇺🇸 美洲赛区", "🇪🇺 欧洲赛区"])
        with t1: show_table(df)
        with t2: show_table(df[df['region'] == "🌏 亚洲"])
        with t3: show_table(df[df['region'] == "🇺🇸 美洲"])
        with t4: show_table(df[df['region'] == "🇪🇺 欧洲"])
        
        # 日志记录
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%H:%M')} | {winner['ip']} | {winner['score']} | {winner['source']}\n")
    
    if is_auto:
        time.sleep(5)
        st.rerun()

# 历史展示 (保留)
with st.expander("📜 历史战绩"):
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f: st.text("".join(f.readlines()[-5:]))
