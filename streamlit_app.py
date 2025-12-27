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
st.set_page_config(page_title="VLESS 避峰竞速版", page_icon="🌙", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    div[data-testid="column"] { background-color: #1a1c24; border: 1px solid #2d3139; border-radius: 8px; padding: 15px; }
    
    /* 模式状态灯 */
    .mode-peak { color: #FF4136; font-weight: bold; animation: pulse 2s infinite; }
    .mode-normal { color: #2ECC40; font-weight: bold; }
    @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
    
    .tag-cold { background-color: #0074D9; color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; }
    .tag-hot { background-color: #FF851B; color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 配置与文件
# ===========================
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except:
    st.error("❌ 配置缺失！")
    st.stop()

DB_FILE = "racing_history.log"
SAVED_IP_FILE = "good_ips.txt"

# ===========================
# 3. 核心：冷门 IP 生成与探测
# ===========================

def get_peak_status():
    """判断是否为晚高峰 (19:00 - 23:30)"""
    now = datetime.now()
    # 简单的判断逻辑，可根据需要调整时间段
    if 19 <= now.hour <= 23:
        if now.hour == 23 and now.minute > 30: return False
        return True
    return False

def generate_cold_ips(count=50):
    """
    生成 Cloudflare 冷门/企业级网段 IP
    这些网段在拥堵时通常比 104.16.x.x 更稳
    """
    cold_cidrs = [
        "162.159.36", "162.159.46", "162.159.192", # 企业/特殊业务
        "198.41.214", "198.41.212",                # 早期段
        "172.64.198", "172.64.229",                # 较新段
        "103.21.244", "103.22.200"                 # 亚太特殊段
    ]
    ips = set()
    for _ in range(count):
        prefix = random.choice(cold_cidrs)
        ip = f"{prefix}.{random.randint(1, 254)}"
        ips.add(ip)
    return list(ips)

@st.cache_data(ttl=3600)
def get_ip_extended_info(ip):
    try:
        url = f"http://ip-api.com/json/{ip}?fields=country,isp,hosting"
        r = requests.get(url, timeout=2.5).json()
        return {
            "country": r.get("country", "Unk"),
            "isp": r.get("isp", "Unk"),
            "is_native": not r.get("hosting", True)
        }
    except: return {"country": "Unk", "isp": "Unk", "is_native": False}

def ping0_tcp_test(ip):
    latencies = []
    success = 0
    # 避峰模式下测试更严谨，测 6 次
    count = 6
    for _ in range(count):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.6)
            start = time.perf_counter()
            s.connect((ip, 443))
            s.close()
            latencies.append((time.perf_counter() - start) * 1000)
            success += 1
        except: pass
        time.sleep(0.02)
    
    if not latencies: return {"avg": 9999, "jitter": 0, "loss": 100}
    return {
        "avg": int(statistics.mean(latencies)),
        "jitter": int(statistics.stdev(latencies)) if len(latencies) > 1 else 0,
        "loss": int(((count - success) / count) * 100)
    }

def get_enhanced_pool():
    competitors = []
    seen = set()
    
    # 1. 晚高峰特供：冷门避峰 IP
    cold_ips = generate_cold_ips(40) # 每次生成40个冷门尝试
    for ip in cold_ips:
        competitors.append({"ip": ip, "source": "🧊 冷门避峰", "type": "cold"})
        seen.add(ip)

    # 2. 优质源 (DerGoogler 等)
    urls = [
        "https://raw.githubusercontent.com/DerGoogler/CloudFlare-IP-Best/main/ip.txt",
        "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        def fetch(u):
            try: return re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', requests.get(u, timeout=4).text)
            except: return []
        for res in ex.map(fetch, urls):
            for ip in random.sample(res, min(len(res), 80)):
                if ip not in seen:
                    competitors.append({"ip": ip, "source": "🔥 热门优选", "type": "hot"})
                    seen.add(ip)

    return competitors

def deep_test_node(node):
    ip = node['ip']
    is_peak = get_peak_status()
    
    # TCP 测试
    p0 = ping0_tcp_test(ip)
    
    # 动态初筛阈值：高峰期放宽延迟要求，严查丢包
    latency_limit = 800 if is_peak else 500
    if p0['avg'] > latency_limit: return None
    if is_peak and p0['loss'] > 0: return None # 高峰期丢包直接淘汰

    # 速度测试
    speed = 0.0
    try:
        s = time.perf_counter()
        r = requests.get(f"http://{ip}/__down?bytes=2000000", headers={"Host": "speed.cloudflare.com"}, timeout=5)
        if r.status_code == 200:
            speed = (len(r.content)/1024/1024) / (time.perf_counter() - s)
    except: pass

    # === 避峰动态评分算法 ===
    score = 100
    
    if is_peak:
        # 晚高峰模式：
        # 1. 极其厌恶丢包 (系数 30)
        # 2. 及其厌恶抖动 (系数 4)
        # 3. 对延迟宽容 (除以 8) -> 200ms 只扣 25分
        # 4. 冷门 IP 额外加分
        score -= (p0['loss'] * 30)
        score -= (p0['jitter'] * 4)
        score -= (p0['avg'] / 8) 
        score += (speed * 10)
        if node['type'] == 'cold': score += 15 # 鼓励选用冷门段
    else:
        # 闲时模式：追求低延迟
        score -= (p0['loss'] * 20)
        score -= (p0['jitter'] * 2)
        score -= (p0['avg'] / 5)
        score += (speed * 12)

    # 获取ISP信息
    info = get_ip_extended_info(ip)
    if info['is_native']: score += 8

    # 入库门槛
    if score > 85:
        with open(SAVED_IP_FILE, "a") as f: f.write(f"{ip}\n")

    return {
        "ip": ip, "score": round(score, 1), "source": node['source'],
        "tcp": p0['avg'], "jitter": p0['jitter'], "loss": p0['loss'],
        "speed": round(speed, 2), "country": info['country'], "isp": info['isp']
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
            return f"🚀 解析同步: {ip}"
    except: return "⚠️ API异常"
    return "❌ 记录无效"

# ===========================
# 4. 主控界面
# ===========================
st.title("🌙 VLESS 竞速 - 晚高峰避峰版")

if "last_run" not in st.session_state: st.session_state.last_run = datetime.min
if "auto_enabled" not in st.session_state: st.session_state.auto_enabled = True

is_peak = get_peak_status()

with st.sidebar:
    st.header("🎮 控制台")
    st.session_state.auto_enabled = st.toggle("⏱️ 10分钟自动循环", value=st.session_state.auto_enabled)
    
    st.divider()
    if is_peak:
        st.markdown("当前策略: <span class='mode-peak'>🌙 晚高峰避峰模式</span>", unsafe_allow_html=True)
        st.caption("算法倾向：稳定(0丢包) > 速度 > 延迟。优先挖掘冷门段。")
    else:
        st.markdown("当前策略: <span class='mode-normal'>☀️ 闲时竞速模式</span>", unsafe_allow_html=True)
        st.caption("算法倾向：极致低延迟。")

now = datetime.now()
trigger = st.session_state.auto_enabled and (now - st.session_state.last_run >= timedelta(minutes=10))
manual = st.button("🏁 启动扫描", type="primary", use_container_width=True)

if manual or trigger:
    st.session_state.last_run = now
    
    with st.status(f"🔍 正在扫描 (模式: {'避峰' if is_peak else '常规'})...", expanded=True) as status:
        pool = get_enhanced_pool()
        st.write(f"已生成冷门段与热门段共 {len(pool)} 个样本...")
        
        results = []
        prog = st.progress(0)
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
            futs = [ex.submit(deep_test_node, x) for x in pool]
            for i, f in enumerate(concurrent.futures.as_completed(futs)):
                prog.progress((i+1)/len(pool))
                res = f.result()
                if res: results.append(res)
        status.update(label="✅ 完成", state="complete")

    if results:
        results.sort(key=lambda x: x['score'], reverse=True)
        winner = results[0]
        sync_msg = sync_dns(winner['ip'])
        
        st.markdown(f"### 🏆 冠军: {winner['ip']}")
        st.markdown(f"**来源:** {winner['source']} | **ISP:** {winner['isp']}")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("评分", winner['score'])
        c2.metric("延迟", f"{winner['tcp']} ms", f"抖动 {winner['jitter']}")
        c3.metric("速度", f"{winner['speed']} MB/s")
        c4.metric("丢包率", f"{winner['loss']}%")
        
        st.caption(f"📝 {sync_msg}")
        
        st.divider()
        df = pd.DataFrame(results)
        st.dataframe(
            df[['score', 'source', 'ip', 'tcp', 'jitter', 'speed']],
            use_container_width=True,
            column_config={
                "score": st.column_config.ProgressColumn("评分", format="%.1f"),
                "source": "策略组",
                "tcp": st.column_config.NumberColumn("延迟(ms)", format="%d"),
            }
        )
    
    if st.session_state.auto_enabled:
        time.sleep(2)
        st.rerun()

if st.session_state.auto_enabled:
    time.sleep(30)
    st.rerun()
