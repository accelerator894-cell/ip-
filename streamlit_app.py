import streamlit as st
import requests
import time
import re
import random
import os
import pandas as pd
import concurrent.futures
from datetime import datetime

# ===========================
# 1. 专业版 UI 配置 (固定暗色主题)
# ===========================
st.set_page_config(page_title="VLESS 极速机甲", page_icon="⚡", layout="wide")

# 固定 CSS 样式：暗夜黑金风格，注重数据可读性
st.markdown("""
    <style>
    .stApp {
        background-color: #0E1117;
        color: #FAFAFA;
    }
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    /* 卡片样式 */
    div[data-testid="column"] {
        background-color: #1E1E1E;
        border: 1px solid #333;
        border-radius: 8px;
        padding: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    /* 成功状态 */
    div[data-testid="stMetricValue"] {
        color: #00FF99 !important;
    }
    /* 表格样式 */
    div[data-testid="stDataFrame"] {
        border: 1px solid #444;
    }
    h1, h2, h3 {
        color: #E0E0E0 !important;
    }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 核心配置与缓存
# ===========================
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except:
    st.error("❌ 配置缺失！请在 secrets.toml 中填写 api_token, zone_id 和 record_name")
    st.stop()

DB_FILE = "scan_history.log"

@st.cache_data(ttl=3600)
def get_ip_info(ip):
    """获取 IP 地理位置 (带缓存)"""
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country"
        r = requests.get(url, timeout=2).json()
        cc = r.get("countryCode", "UNK")
        region = "🌍 其他"
        if cc in ['CN', 'HK', 'TW', 'JP', 'KR', 'SG']: region = "🌏 亚洲"
        elif cc in ['US', 'CA', 'MX']: region = "🇺🇸 美洲"
        elif cc in ['DE', 'GB', 'FR', 'NL', 'EU']: region = "🇪🇺 欧洲"
        return region, r.get("country", "Unknown")
    except:
        return "🛸 未知", "Unknown"

# ===========================
# 3. 增强型网络功能
# ===========================

def get_huge_ip_pool():
    """多源采集 IP (增强节点数)"""
    sources = [
        "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
        "https://raw.githubusercontent.com/w8ves/CF-IP/master/speedtest.txt",
        "https://www.cloudflare.com/ips-v4" # 官方段作为保底
    ]
    
    all_ips = set()
    
    # 并发获取所有源
    def fetch_url(url):
        try:
            r = requests.get(url, timeout=3)
            return re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        except:
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        results = executor.map(fetch_url, sources)
        for ip_list in results:
            all_ips.update(ip_list)
            
    # 如果抓取太少，使用内置保底
    if len(all_ips) < 10:
        base_ips = ["104.16.0.0", "104.24.0.0", "172.64.0.0", "162.159.0.0"] # 简化的段
        return base_ips
        
    # 从池子中随机抽取 50 个进行精细测速 (性能与数量的平衡)
    return random.sample(list(all_ips), min(len(all_ips), 60))

def fast_ping(ip):
    """极速握手测试"""
    try:
        start = time.time()
        # 1.5秒超时，只要握手成功即视为通畅
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.5)
        return int((time.time() - start) * 1000)
    except:
        return 9999

def check_api_health_robust():
    """抗波动 API 检查"""
    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    for _ in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200: return True
        except:
            time.sleep(0.5)
    return False

def sync_dns_record(best_ip):
    """DNS 记录同步"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        # 1. 查
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        recs = requests.get(url, headers=headers, params=params, timeout=5).json()
        if not recs.get("result"): return "❌ 无记录"
        
        record_id = recs["result"][0]["id"]
        old_ip = recs["result"][0]["content"]
        
        if old_ip == best_ip: return "✅ IP未变"
        
        # 2. 改
        data = {"type": "A", "name": CF_CONFIG['record_name'], "content": best_ip, "ttl": 60, "proxied": False}
        requests.put(f"{url}/{record_id}", headers=headers, json=data)
        return f"🚀 已更新: {old_ip} -> {best_ip}"
    except Exception as e:
        return f"⚠️ 错误: {str(e)[:20]}"

# ===========================
# 4. 主程序逻辑
# ===========================

st.title("⚡ VLESS 优选引擎 Pro")

# 顶部状态
col_status, col_btn = st.columns([3, 1])
with col_status:
    if check_api_health_robust():
        st.caption("🟢 API 连接: 正常 | 模式: 全球多源并发扫描")
    else:
        st.warning("🟠 API 连接不稳，正在重试...")

with col_btn:
    if st.button("🚀 重新扫描", use_container_width=True):
        st.rerun()

st.divider()

# 扫描过程
with st.spinner("📡 正在从 3 个源获取 IP 池并并发测速 (Max Threads: 20)..."):
    
    # 1. 准备数据
    core_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    dynamic_ips = get_huge_ip_pool() # 获取更多 IP
    
    # 确保列表去重
    scan_list = list(set(core_ips + dynamic_ips))
    
    tasks = []
    # 标记类型
    for ip in scan_list:
        tasks.append({"ip": ip, "type": "⭐ 核心" if ip in core_ips else "🌐 动态"})

    valid_nodes = []

    # 2. 高并发测速 (20线程)
    progress_bar = st.progress(0)
    completed = 0
    total = len(tasks)

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        # 提交所有任务
        future_to_ip = {executor.submit(fast_ping, t['ip']): t for t in tasks}
        
        for future in concurrent.futures.as_completed(future_to_ip):
            node = future_to_ip[future]
            lat = future.result()
            completed += 1
            progress_bar.progress(completed / total)
            
            # 过滤掉高延迟节点 (只保留 < 500ms)
            if lat < 500:
                # 只有优质节点才查地理位置，省时间
                reg, ctry = get_ip_info(node['ip'])
                valid_nodes.append({
                    "ip": node['ip'],
                    "lat": lat,
                    "region": reg,
                    "country": ctry,
                    "type": node['type']
                })
    
    progress_bar.empty()

    # 3. 结果处理
    if valid_nodes:
        valid_nodes.sort(key=lambda x: x['lat'])
        winner = valid_nodes[0]
        
        # 执行同步
        sync_msg = sync_dns_record(winner['ip'])
        
        # --- 结果看板 ---
        c1, c2, c3 = st.columns(3)
        with c1: st.metric("🏆 优选 IP", winner['ip'], delta=f"{winner['lat']} ms", delta_color="inverse")
        with c2: st.metric("📍 物理位置", f"{winner['country']}", winner['region'])
        with c3: st.info(f"📝 {sync_msg}")

        # --- 详细列表 (只显示前 20 个) ---
        st.subheader("📊 优质节点列表 (Top 20)")
        df = pd.DataFrame(valid_nodes[:20])
        st.dataframe(
            df[["ip", "lat", "region", "country", "type"]].rename(columns={"lat": "延迟(ms)", "ip": "IP地址", "region": "区域", "country": "国家"}),
            use_container_width=True,
            hide_index=True
        )
        
        # 日志记录
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%H:%M')} | {winner['ip']} | {winner['lat']}ms\n")

    else:
        st.error("⚠️ 本轮未发现可用节点，请检查网络或更换网络环境后重试。")

# 底部栏
with st.expander("📜 查看历史优选记录"):
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            st.text("".join(f.readlines()[-10:]))

# 自动刷新保持连接
time.sleep(600)
st.rerun()
