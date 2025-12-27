import streamlit as st
import requests
import time
import re
import random
import os
import pandas as pd
import concurrent.futures
import statistics
from datetime import datetime

# ===========================
# 1. 页面配置
# ===========================
st.set_page_config(page_title="VLESS 全能评测室", page_icon="🧪", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #FAFAFA; }
    div[data-testid="column"] { background-color: #1E1E1E; border: 1px solid #333; border-radius: 8px; padding: 15px; }
    /* 进度条颜色 */
    .stProgress > div > div > div > div { background-color: #00FF99; }
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
    st.error("❌ 配置缺失！请检查 secrets.toml")
    st.stop()

DB_FILE = "scan_history.log"

# ===========================
# 3. 基础工具函数
# ===========================

@st.cache_data(ttl=3600)
def get_ip_info(ip):
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country"
        r = requests.get(url, timeout=2).json()
        cc = r.get("countryCode", "UNK")
        if cc in ['CN', 'HK', 'TW', 'JP', 'KR', 'SG']: return "🌏 亚洲", r.get("country")
        if cc in ['US', 'CA', 'MX']: return "🇺🇸 美洲", r.get("country")
        if cc in ['DE', 'GB', 'FR', 'NL']: return "🇪🇺 欧洲", r.get("country")
        return "🌍 其他", r.get("country")
    except:
        return "🛸 未知", "Unknown"

def get_collected_ips():
    """获取 IP 池 (含官方源保底)"""
    sources = [
        "https://www.cloudflare.com/ips-v4", # 官方源
        "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
        "https://raw.githubusercontent.com/w8ves/CF-IP/master/speedtest.txt"
    ]
    all_ips = set()
    
    def fetch(url):
        try:
            r = requests.get(url, timeout=4)
            return re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        except: return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        for res in ex.map(fetch, sources): all_ips.update(res)
    
    # 扩大样本量到 80 个以增加命中率
    final_list = list(all_ips)
    return random.sample(final_list, min(len(final_list), 80))

# ===========================
# 4. 深度测试核心逻辑
# ===========================

def basic_ping(ip):
    """初筛：单次 Ping"""
    try:
        start = time.time()
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        return int((time.time() - start) * 1000)
    except: return 9999

def advanced_test(node):
    """精测：抖动、丢包、速度、解锁"""
    ip = node['ip']
    
    # 1. 丢包与抖动测试 (Ping 5次)
    delays = []
    loss_count = 0
    for _ in range(5):
        try:
            s = time.time()
            requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.5)
            delays.append((time.time() - s) * 1000)
        except:
            loss_count += 1
            
    # 计算稳定性指标
    loss_rate = (loss_count / 5) * 100
    avg_lat = statistics.mean(delays) if delays else 9999
    jitter = int(statistics.stdev(delays)) if len(delays) > 1 else 0
    
    # 2. 速度测试 (下载 1MB 小文件)
    speed_mb = 0.0
    try:
        # 使用 CF 官方测速点，模拟真实回源
        s_time = time.time()
        # 下载 1MB 数据
        r = requests.get(f"http://{ip}/__down?bytes=1000000", headers={"Host": "speed.cloudflare.com"}, timeout=5, stream=True)
        size = 0
        for chunk in r.iter_content(chunk_size=1024):
            size += len(chunk)
            if size >= 1000000: break
        duration = time.time() - s_time
        if duration > 0:
            speed_mb = (size / 1024 / 1024) / duration # MB/s
    except:
        speed_mb = 0.0

    # 3. 流媒体解锁 (Netflix + YouTube)
    nf_status = "❓"
    yt_status = "❓"
    try:
        # Netflix
        r_nf = requests.get(f"http://{ip}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=2)
        nf_status = "✅" if r_nf.status_code in [200, 301, 302] else "❌"
        # YouTube (简单检测)
        r_yt = requests.get(f"http://{ip}", headers={"Host": "www.youtube.com"}, timeout=2)
        yt_status = "✅" if r_yt.status_code == 200 else "❌"
    except: pass

    return {
        "ip": ip,
        "source": node['source'],
        "region": node['region'],
        "country": node['country'],
        "lat": int(avg_lat),      # 平均延迟
        "jitter": jitter,         # 抖动
        "loss": f"{int(loss_rate)}%", # 丢包
        "speed": f"{speed_mb:.2f}",   # 速度
        "nf": nf_status,
        "yt": yt_status
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
    except Exception as e: return "⚠️ API错误"

# ===========================
# 5. 主程序逻辑
# ===========================

st.title("🧪 VLESS 全能评测室")

col_btn, col_info = st.columns([1, 3])
with col_btn:
    start_btn = st.button("🚀 开始深度体检", type="primary", use_container_width=True)
with col_info:
    st.info("💡 评测项目：延迟(Latency) | 抖动(Jitter) | 丢包(Loss) | 速度(Speed) | 解锁(Unlock)")

if start_btn:
    
    # --- 第一阶段：海选 (快速 Ping) ---
    st.subheader("1️⃣ 第一阶段：全球海选 (Broad Scan)")
    status_text = st.empty()
    bar = st.progress(0)
    
    # 准备 IP
    local_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    collected_ips = get_collected_ips()
    
    # 合并任务
    tasks = [{"ip": ip, "source": "🏠 预设"} for ip in local_ips] + \
            [{"ip": ip, "source": "☁️ 采集"} for ip in collected_ips]
    
    status_text.text(f"正在对 {len(tasks)} 个节点进行快速 Ping...")
    
    candidates = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
        future_map = {ex.submit(basic_ping, t['ip']): t for t in tasks}
        done = 0
        for fut in concurrent.futures.as_completed(future_map):
            done += 1
            bar.progress(done / len(tasks))
            lat = fut.result()
            if lat < 1000: # 初筛合格线
                node = future_map[fut]
                # 顺便查一下地区，为精测做准备
                reg, ctry = get_ip_info(node['ip'])
                candidates.append({**node, "lat": lat, "region": reg, "country": ctry})
    
    if not candidates:
        st.error("❌ 第一阶段全军覆没，请检查网络。")
        st.stop()
        
    # 选出前 10 名进入复赛
    candidates.sort(key=lambda x: x['lat'])
    top_10 = candidates[:10]
    
    st.success(f"✅ 海选结束，{len(candidates)} 个节点在线，前 10 名进入深度体检。")
    st.divider()
    
    # --- 第二阶段：精测 (深度测试) ---
    st.subheader("2️⃣ 第二阶段：深度体检 (Deep Test)")
    st.caption("正在进行：5次连Ping测抖动/丢包 + 1MB下载测速 + 媒体解锁检测...")
    
    final_results = []
    bar2 = st.progress(0)
    
    # 这里不能并发太高，防止测速抢带宽导致结果不准
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(advanced_test, node) for node in top_10]
        for i, fut in enumerate(concurrent.futures.as_completed(futs)):
            bar2.progress((i + 1) / len(top_10))
            final_results.append(fut.result())
            
    # --- 结果展示 ---
    # 综合排序：优先看丢包(Loss)，其次看延迟(Lat)，最后看速度(Speed 倒序，大的好)
    # 这里简单处理：按延迟排
    final_results.sort(key=lambda x: x['lat'])
    winner = final_results[0]
    
    # 同步 DNS
    sync_msg = sync_dns(winner['ip'])
    
    # 冠军展示
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("🏆 优选 IP", winner['ip'])
    with c2: st.metric("平均延迟", f"{winner['lat']} ms", f"抖动 ±{winner['jitter']}")
    with c3: st.metric("下载速度", f"{winner['speed']} MB/s")
    with c4: st.metric("丢包率", winner['loss'], delta_color="inverse")
    
    st.info(f"📝 {sync_msg}")
    
    # 详细表格
    df = pd.DataFrame(final_results)
    
    # 重命名列以显示更好看
    st.dataframe(
        df[["source", "ip", "region", "country", "lat", "jitter", "loss", "speed", "nf", "yt"]].rename(columns={
            "source": "来源", "ip": "IP", "region": "区域", "country": "国家",
            "lat": "延迟(ms)", "jitter": "抖动", "loss": "丢包", "speed": "速度(MB/s)",
            "nf": "Netflix", "yt": "YouTube"
        }),
        use_container_width=True,
        hide_index=True
    )
    
    # 写入日志
    with open(DB_FILE, "a") as f:
        f.write(f"{datetime.now().strftime('%H:%M')} | {winner['ip']} | {winner['lat']}ms | Speed:{winner['speed']}MB/s\n")

# 历史记录
with st.expander("📜 查看历史记录"):
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f: st.text("".join(f.readlines()[-5:]))
