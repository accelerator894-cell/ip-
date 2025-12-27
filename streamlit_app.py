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
# 1. 页面配置 (黑客风UI)
# ===========================
st.set_page_config(page_title="VLESS 竞速 - 原生IP特供版", page_icon="🧬", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    div[data-testid="column"] { background-color: #1a1c24; border: 1px solid #2d3139; border-radius: 8px; padding: 15px; }
    
    /* Ping0 风格标签 */
    .ping0-label { color: #8a92a6; font-size: 0.8rem; font-weight: bold; }
    .ping0-value { color: #00ff41; font-family: 'Courier New', monospace; font-size: 1.4rem; }
    
    /* 原生 IP 标签高亮 */
    .tag-native { background-color: #2ECC40; color: #000; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8rem; }
    .tag-dc { background-color: #FF4136; color: #fff; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8rem; }
    .isp-text { color: #7FDBFF; font-size: 0.9rem; }
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
    st.error("❌ 配置缺失！请检查 secrets.toml")
    st.stop()

DB_FILE = "racing_history.log"
SAVED_IP_FILE = "good_ips.txt"

# ===========================
# 3. 核心工具：IP 深度画像
# ===========================

@st.cache_data(ttl=3600)
def get_ip_extended_info(ip):
    """
    获取 Ping0 级别的 IP 详情：ISP, ASN, 是否原生(Hosting)
    """
    try:
        # 请求包含 isp, org, as, hosting(用于判断原生)
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country,isp,org,as,hosting"
        r = requests.get(url, timeout=3).json()
        
        # 基础信息
        cc = r.get("countryCode", "UNK")
        country = r.get("country", "Unknown")
        isp = r.get("isp", "Unknown ISP")
        asn = r.get("as", "")
        
        # 判断原生：hosting 为 False 通常代表住宅/商业IP (原生)
        is_hosting = r.get("hosting", True) 
        ip_type = "🧬 原生" if not is_hosting else "🏢 数据中心"
        
        return {
            "country": country,
            "cc": cc,
            "isp": isp,
            "asn": asn,
            "type": ip_type,
            "is_native": not is_hosting
        }
    except:
        return {"country": "Unknown", "cc": "UNK", "isp": "Unknown", "asn": "", "type": "🛸 未知", "is_native": False}

def ping0_tcp_test(ip, port=443, count=5):
    """模拟 Ping0 TCP 握手"""
    latencies = []
    success = 0
    for _ in range(count):
        try:
            start = time.perf_counter()
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.8)
            s.connect((ip, port))
            s.close()
            latencies.append((time.perf_counter() - start) * 1000)
            success += 1
        except: pass
        time.sleep(0.01)
    
    if not latencies: return {"avg": 9999, "min": 9999, "jitter": 0, "loss": 100}
    
    return {
        "avg": int(statistics.mean(latencies)),
        "min": int(min(latencies)),
        "jitter": int(statistics.stdev(latencies)) if len(latencies) > 1 else 0,
        "loss": int(((count - success) / count) * 100)
    }

def get_enhanced_pool():
    competitors = []
    seen_ips = set()
    
    # 电信优选种子
    seeds = ["1.1.1.1", "1.0.0.1", "104.16.0.1", "172.67.1.1"]
    for ip in seeds:
        competitors.append({"ip": ip, "source": "💎 官方优选"})
        seen_ips.add(ip)
    
    # 历史库
    if os.path.exists(SAVED_IP_FILE):
        with open(SAVED_IP_FILE, "r") as f:
            for ip in re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', f.read()):
                if ip not in seen_ips:
                    competitors.append({"ip": ip, "source": "💾 历史"})
                    seen_ips.add(ip)

    # 爬虫源
    urls = [
        "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
        "https://www.cloudflare.com/ips-v4"
    ]
    scraped = set()
    def fetch(url):
        try: return re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', requests.get(url, timeout=5).text)
        except: return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        for res in ex.map(fetch, urls):
            for ip in res: scraped.add(ip)
    
    # 抽取 120 个进行深度检测
    picked = random.sample(list(scraped), min(len(scraped), 120))
    for ip in picked:
        if ip not in seen_ips:
            competitors.append({"ip": ip, "source": "☁️ 爬虫"})
    return competitors

def deep_test_node(node):
    ip = node['ip']
    
    # 1. Ping0 TCP 测试
    p0 = ping0_tcp_test(ip)
    if p0['avg'] > 800: return None

    # 2. 获取原生/ISP信息
    info = get_ip_extended_info(ip)

    # 3. 速度测试 (2MB)
    speed_mb = 0.0
    try:
        s_time = time.perf_counter()
        r = requests.get(f"http://{ip}/__down?bytes=2000000", headers={"Host": "speed.cloudflare.com"}, timeout=4)
        if r.status_code == 200:
            speed_mb = (len(r.content)/1024/1024) / (time.perf_counter() - s_time)
    except: pass

    # 4. 评分公式 (原生IP额外加分)
    score = 100 - (p0['avg'] / 5) - (p0['loss'] * 20) + (speed_mb * 12) - (p0['jitter'] * 2)
    
    # 原生 IP 稀缺性加分
    if info['is_native']: score += 10 

    # 保存逻辑
    if score > 85 and node['source'] == "☁️ 爬虫":
        with open(SAVED_IP_FILE, "a") as f: f.write(f"{ip}\n")

    return {
        "score": round(score, 1),
        "ip": ip,
        "type": info['type'], # 原生 vs 数据中心
        "isp": info['isp'],   # 运营商
        "country": info['country'],
        "tcp_avg": p0['avg'],
        "jitter": p0['jitter'],
        "speed": round(speed_mb, 2),
        "loss": p0['loss'],
        "source": node['source']
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
# 4. 主界面逻辑
# ===========================
st.title("🧬 VLESS 竞速 - 原生IP特供版")

# Session 初始化
if "last_run" not in st.session_state: st.session_state.last_run = datetime.min
if "auto_enabled" not in st.session_state: st.session_state.auto_enabled = True

# 侧边栏
with st.sidebar:
    st.header("⚙️ 控制台")
    st.session_state.auto_enabled = st.toggle("⏱️ 10分钟自动循环", value=st.session_state.auto_enabled)
    st.divider()
    if st.button("🗑️ 清空精英库"):
        if os.path.exists(SAVED_IP_FILE): os.remove(SAVED_IP_FILE)

# 自动触发判定
now = datetime.now()
auto_trigger = st.session_state.auto_enabled and (now - st.session_state.last_run >= timedelta(minutes=10))
manual_start = st.button("🏁 开始原生探测", type="primary", use_container_width=True)

if manual_start or auto_trigger:
    st.session_state.last_run = now
    
    with st.status("🔍 正在扫描全球节点 (含原生检测)...", expanded=True) as status:
        pool = get_enhanced_pool()
        st.write(f"目标样本: {len(pool)} 个 | 正在进行 Ping0 握手与 ISP 识别...")
        
        results = []
        progress = st.progress(0)
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
            futs = [ex.submit(deep_test_node, x) for x in pool]
            for i, f in enumerate(concurrent.futures.as_completed(futs)):
                progress.progress((i+1)/len(pool))
                res = f.result()
                if res: results.append(res)
        status.update(label="✅ 检测完成", state="complete")

    if results:
        results.sort(key=lambda x: x['score'], reverse=True)
        winner = results[0]
        dns_msg = sync_dns(winner['ip'])
        
        # === 冠军展示区 (Ping0 风格) ===
        st.markdown(f"### 🏆 冠军节点: {winner['ip']}")
        
        # 标签栏
        tag_class = "tag-native" if "原生" in winner['type'] else "tag-dc"
        st.markdown(f"""
        <span class='{tag_class}'>{winner['type']}</span> 
        <span class='isp-text'>🏢 {winner['isp']} ({winner['country']})</span>
        """, unsafe_allow_html=True)
        
        st.divider()
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("综合评分", winner['score'])
        c2.metric("Ping0 延迟", f"{winner['tcp_avg']} ms", f"抖动 {winner['jitter']}")
        c3.metric("下载带宽", f"{winner['speed']} MB/s")
        c4.metric("同步状态", dns_msg)
        
        # === 详细列表 ===
        st.subheader("📊 深度排位表")
        df = pd.DataFrame(results)
        
        # 配置列显示
        st.dataframe(
            df[['score', 'ip', 'type', 'isp', 'tcp_avg', 'speed', 'loss']],
            use_container_width=True,
            column_config={
                "score": st.column_config.ProgressColumn("评分", format="%.1f"),
                "ip": "IP 地址",
                "type": "IP 类型",
                "isp": "运营商 (ISP)",
                "tcp_avg": st.column_config.NumberColumn("Ping0(ms)", format="%d"),
                "speed": st.column_config.NumberColumn("带宽(MB/s)", format="%.2f"),
                "loss": st.column_config.NumberColumn("丢包(%)", format="%d")
            }
        )
    
    # 自动循环逻辑
    if st.session_state.auto_enabled:
        time.sleep(2)
        st.rerun()

# 保持唤醒
if st.session_state.auto_enabled:
    time.sleep(30)
    st.rerun()
