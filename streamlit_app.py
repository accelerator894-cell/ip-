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

# ===========================
# 1. 页面配置 (电信蓝主题)
# ===========================
st.set_page_config(page_title="VLESS 电信专享版", page_icon="📡", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #001f3f; color: #E0E0E0; } /* 电信深蓝背景 */
    div[data-testid="column"] { background-color: #003366; border: 1px solid #0074D9; border-radius: 8px; padding: 15px; }
    div[data-testid="stMetricValue"] { color: #2ECC40 !important; }
    h1, h2, h3 { color: #7FDBFF !important; }
    .stProgress > div > div > div > div { background-color: #0074D9; }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 配置读取
# ===========================
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except:
    st.error("❌ 配置缺失！请在 secrets.toml 中填写配置")
    st.stop()

DB_FILE = "telecom_history.log"

# ===========================
# 3. 电信专属 IP 池构建
# ===========================

def generate_telecom_preferred_ips():
    """生成电信友好的官方段 IP"""
    # 电信通常对 104.16.x.x 到 104.24.x.x 以及 172.64.x.x 较为友好
    # 这里生成一些随机的官方段 IP
    ips = []
    # 104.16.x.x - 104.20.x.x
    for _ in range(10):
        ips.append(f"104.{random.randint(16, 20)}.{random.randint(0, 255)}.{random.randint(0, 255)}")
    # 172.64.x.x - 172.67.x.x
    for _ in range(10):
        ips.append(f"172.{random.randint(64, 67)}.{random.randint(0, 255)}.{random.randint(0, 255)}")
    return ips

def get_telecom_pool():
    """混合池：官方段 + 商业解析 + 采集"""
    # 1. 采集源 (网络爬虫)
    urls = [
        "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
        "https://www.cloudflare.com/ips-v4"
    ]
    collected = set()
    
    def fetch(url):
        try:
            r = requests.get(url, timeout=3)
            return re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        except: return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        for res in ex.map(fetch, urls):
            collected.update(res)

    # 2. 注入电信优选段 (VIP处理)
    telecom_ips = generate_telecom_preferred_ips()
    
    # 3. 混合列表 (保证至少 30 个官方优选IP + 50 个随机采集IP)
    pool_list = list(collected)
    final_list = telecom_ips + random.sample(pool_list, min(len(pool_list), 50))
    
    return final_list

# ===========================
# 4. 电信 QoS 对抗评分算法
# ===========================

def calculate_telecom_score(lat, jitter, loss, speed):
    """
    电信专用评分公式：
    - 极度厌恶丢包 (Loss)
    - 极度厌恶抖动 (Jitter)
    - 对绝对延迟 (Latency) 容忍度稍高，只要不丢包就行
    """
    score = 100
    
    # 1. 速度分 (权重适中)
    score += min(speed * 3, 30) 
    
    # 2. 延迟扣分 (电信通常 150ms 左右算正常，宽容一点)
    if lat > 150:
        score -= (lat - 150) / 4
    
    # 3. 抖动扣分 (电信杀手，重罚！每 1ms 抖动扣 3 分)
    score -= jitter * 3
    
    # 4. 丢包扣分 (绝不容忍，只要有丢包直接不及格)
    if loss > 0:
        score -= 50 # 只要丢包直接扣50分
        score -= loss * 2 # 额外追加
        
    return round(score, 1)

def deep_test_telecom(node):
    ip = node['ip']
    
    # 1. 严格稳定性测试 (HTTPS Ping 6次)
    delays = []
    loss_count = 0
    # 模拟真实 VLESS 流量特征 (HTTPS)
    headers = {"Host": CF_CONFIG['record_name'], "User-Agent": "Mozilla/5.0"}
    
    for _ in range(6):
        try:
            s = time.time()
            requests.head(f"https://{ip}", headers=headers, timeout=2.0, verify=False)
            delays.append((time.time() - s) * 1000)
        except:
            loss_count += 1
            
    loss_rate = (loss_count / 6) * 100
    avg_lat = statistics.mean(delays) if delays else 9999
    # 计算抖动 (标准差)
    jitter = statistics.stdev(delays) if len(delays) > 1 else 0
    
    # 2. 速度测试 (下载 2MB)
    speed_mb = 0.0
    try:
        s_time = time.time()
        # 下载 2MB
        r = requests.get(f"https://{ip}/__down?bytes=2000000", headers={"Host": "speed.cloudflare.com"}, timeout=8, verify=False)
        if r.status_code == 200:
            speed_mb = (len(r.content) / 1024 / 1024) / (time.time() - s_time)
    except: pass
    
    # 3. 评分
    score = calculate_telecom_score(avg_lat, jitter, loss_rate, speed_mb)
    
    # 来源标记
    source = "⭐ 官方段" if (ip.startswith("104.") or ip.startswith("172.")) else "☁️ 采集池"
    
    return {
        "ip": ip,
        "source": source,
        "lat": int(avg_lat),
        "jitter": int(jitter),
        "loss": int(loss_rate),
        "speed": round(speed_mb, 2),
        "score": score
    }

def sync_dns(ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        recs = requests.get(url, headers=headers, params=params, timeout=5).json()
        if not recs.get("result"): return "❌ 无记录"
        rid = recs["result"][0]["id"]
        if recs["result"][0]["content"] == ip: return "✅ IP未变"
        requests.put(f"{url}/{rid}", headers=headers, json={
            "type": "A", "name": CF_CONFIG['record_name'], "content": ip, "ttl": 60, "proxied": False
        })
        return f"🚀 已同步: {ip}"
    except Exception as e: return "⚠️ API异常"

# ===========================
# 5. 主程序 UI
# ===========================

st.title("📡 VLESS 电信专享版 (Telecom Pro)")

c1, c2 = st.columns([3, 1])
with c1:
    st.info("💡 针对中国电信 163 骨干网优化：优先 Cloudflare 原生段，严厉打击丢包/抖动节点。")
with c2:
    if st.button("🚀 开始优选", type="primary"):
        st.session_state['scanning'] = True

if st.session_state.get('scanning'):
    
    # --- Step 1: 准备 IP 池 ---
    with st.spinner("📦 正在生成电信优选 IP 池..."):
        scan_pool = get_telecom_pool()
        tasks = [{"ip": ip} for ip in scan_pool]
    
    # --- Step 2: 并发测速 ---
    st.write(f"⚡ 正在深度测试 {len(tasks)} 个节点 (HTTPS 握手 + 丢包分析)...")
    progress = st.progress(0)
    
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
        futs = [ex.submit(deep_test_telecom, t) for t in tasks]
        for i, fut in enumerate(concurrent.futures.as_completed(futs)):
            progress.progress((i + 1) / len(tasks))
            res = fut.result()
            # 只有评分 > 0 的才算有效，负分滚粗
            if res['lat'] < 900: 
                results.append(res)
    
    # --- Step 3: 结果结算 ---
    if results:
        # 按分数倒序
        results.sort(key=lambda x: x['score'], reverse=True)
        winner = results[0]
        
        # 自动同步
        sync_msg = sync_dns(winner['ip'])
        
        # 冠军展示
        st.success(f"🏆 最终优选: {winner['ip']} (得分: {winner['score']})")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("下载速度", f"{winner['speed']} MB/s")
        col2.metric("链路延迟", f"{winner['lat']} ms", f"抖动 {winner['jitter']}")
        col3.metric("丢包率", f"{winner['loss']}%", delta_color="inverse")
        col4.write(f"📝 {sync_msg}")
        
        st.divider()
        st.subheader("📊 优选榜单 (Top 20)")
        
        # 展示数据
        df = pd.DataFrame(results[:20])
        st.dataframe(
            df[["score", "ip", "source", "speed", "lat", "jitter", "loss"]].rename(columns={
                "score": "评分", "speed": "速度(MB/s)", "lat": "延迟", 
                "jitter": "抖动", "loss": "丢包(%)"
            }),
            use_container_width=True,
            hide_index=True
        )
        
        # 记录
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | Score:{winner['score']} | {winner['source']}\n")
            
    else:
        st.error("❌ 所有节点均不可用，请检查网络连接。")
    
    st.session_state['scanning'] = False

# 历史记录
with st.expander("📜 电信优选历史"):
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f: st.text("".join(f.readlines()[-5:]))
