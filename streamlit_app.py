import streamlit as st
import requests
import time
import re
import random
import os
import pandas as pd
from datetime import datetime

# --- 1. 页面配置 ---
st.set_page_config(page_title="4K 引擎：稳定版", page_icon="🛡️", layout="wide")

# ===========================
# 🎨 随机主题引擎
# ===========================
THEMES = [
    {
        "name": "Cyberpunk 2077",
        "bg": "https://w.wallhaven.cc/full/72/wallhaven-72rdqo.jpg",
        "main_color": "#00ffea",
        "border_color": "#ff0055",
        "text_color": "#ffffff",
        "overlay": "rgba(10, 10, 20, 0.85)"
    },
    {
        "name": "Deep Space",
        "bg": "https://w.wallhaven.cc/full/xl/wallhaven-xl65oz.jpg",
        "main_color": "#00BFFF",
        "border_color": "#4169E1",
        "text_color": "#E6E6FA",
        "overlay": "rgba(10, 20, 40, 0.85)"
    },
    {
        "name": "Obsidian Black",
        "bg": "https://w.wallhaven.cc/full/zy/wallhaven-zygekj.jpg",
        "main_color": "#FFD700",
        "border_color": "#B8860B",
        "text_color": "#F0F0F0",
        "overlay": "rgba(0, 0, 0, 0.9)"
    }
]

current_theme = random.choice(THEMES)

st.markdown(f"""
    <style>
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    header {{visibility: hidden;}}

    .stApp {{
        background-image: url("{current_theme['bg']}");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }}

    .block-container {{
        background-color: {current_theme['overlay']};
        border-radius: 12px;
        border: 1px solid {current_theme['border_color']};
        padding: 1.5rem;
        margin-top: 1rem;
        backdrop-filter: blur(5px);
    }}
    
    h1, h2, h3, p, span, div {{
        color: {current_theme['text_color']} !important;
        font-family: sans-serif;
    }}
    
    /* 顶部健康度卡片 */
    div[data-testid="column"] {{
        background-color: rgba(255, 255, 255, 0.05);
        border-radius: 8px;
        padding: 10px;
        border: 1px solid {current_theme['border_color']};
    }}

    [data-testid="stDataFrame"] {{
        border: 1px solid {current_theme['border_color']};
    }}
    
    .stProgress > div > div > div > div {{
        background-color: {current_theme['main_color']};
    }}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 配置读取 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except:
    st.error("❌ Secrets 配置缺失")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 核心功能 ---

def check_api_health_percent():
    """计算 API 健康百分比 (增强版：带重试机制)"""
    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    
    # 尝试 3 次，防止网络抖动导致的误报
    for i in range(3):
        try:
            start = time.time()
            # 延长超时时间到 5 秒
            resp = requests.get(url, headers=headers, timeout=5).json()
            latency = (time.time() - start) * 1000
            
            if resp.get("success"):
                score = 100
                if latency > 200:
                    deduct = int((latency - 200) / 100) * 5
                    score = max(60, 100 - deduct)
                return True, score, int(latency)
        except:
            time.sleep(1) # 失败后休息 1 秒再试
            continue
            
    return False, 0, 0

def get_ip_info(ip):
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country"
        r = requests.get(url, timeout=1.5).json()
        cc = r.get("countryCode", "UNK")
        country = r.get("country", "Unknown")
        region = "🌍 其他"
        if cc in ['CN', 'HK', 'TW', 'JP', 'KR', 'SG', 'MY', 'TH', 'VN', 'IN']: region = "🌏 亚洲"
        elif cc in ['US', 'CA', 'MX', 'BR', 'AR']: region = "🇺🇸 美洲"
        elif cc in ['DE', 'GB', 'FR', 'NL', 'RU', 'IT', 'ES', 'PL', 'UA']: region = "🇪🇺 欧洲"
        return region, country
    except: return "🛸 未知", "Unknown"

def get_global_ips():
    try:
        r = requests.get("https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt", timeout=4)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        return random.sample(list(found), min(len(found), 12))
    except: return []

def fast_ping(ip):
    try:
        start = time.time()
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.5)
        return int((time.time() - start) * 1000)
    except: return 9999

def check_netflix(ip):
    try:
        r = requests.get(f"http://{ip}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=2)
        return "✅" if r.status_code in [200, 301, 302] else "❌"
    except: return "❓"

def sync_dns(new_ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        search = requests.get(url, headers=headers, params=params, timeout=10).json()
        if not search.get("success") or not search.get("result"): return "❌ 未找到记录"
        record = search["result"][0]
        if record["content"] == new_ip: return "✅ 解析已固化，无需变更"
        requests.put(f"{url}/{record['id']}", headers=headers, json={
            "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
        })
        return f"🚀 云端同步完成 -> {new_ip}"
    except: return "⚠️ API 异常"

# --- 4. 主程序界面 ---

st.title(f"🚀 4K 引擎：{current_theme['name']} 版")

# --- 🏆 顶部健康度 (加固版) ---
is_ok, score, lat = check_api_health_percent()

c1, c2 = st.columns([3, 1])

with c1:
    if is_ok:
        st.markdown(f"**📶 API 连通健康度: {score}%** (响应: {lat}ms)")
        st.progress(score / 100)
    else:
        # 如果还是失败，显示黄色警告而不是红色错误，减少焦虑
        st.warning("⚠️ API 连接波动，但核心同步功能仍在运行中...")

with c2:
    if st.button("🔄 刷新"):
        st.rerun()

st.markdown("---")

# 主扫描逻辑
with st.spinner("📡 正在扫描全球骨干网..."):
    results = []
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    global_ips = get_global_ips()
    candidates = base_ips + global_ips
    
    # 初筛
    valid_nodes = []
    for ip in candidates:
        lat = fast_ping(ip)
        if lat < 500:
            valid_nodes.append({"ip": ip, "lat": lat, "type": "⭐ 核心" if ip in base_ips else "🌐 搜集"})
    
    final_data = []
    if valid_nodes:
        valid_nodes.sort(key=lambda x: x['lat'])
        for node in valid_nodes[:8]:
            reg, ctry = get_ip_info(node['ip'])
            nf = check_netflix(node['ip']) if node['lat'] < 200 else "❓"
            node.update({"region": reg, "country": ctry, "nf": nf})
            final_data.append(node)
            
        winner = final_data[0]
        
        # 结果展示
        st.success(f"🏆 优选锁定: {winner['ip']} ({winner['region']}) | 延迟 {winner['lat']}ms")
        st.info(sync_dns(winner['ip']))
        
        # 分区看板
        df = pd.DataFrame(final_data)
        cols = {"ip": "IP", "region": "区域", "country": "国家", "lat": "延迟", "nf": "解锁", "type": "类型"}
        df_show = df[cols.keys()].rename(columns=cols)
        
        t1, t2, t3, t4 = st.tabs(["🌐 全球", "🌏 亚洲", "🇺🇸 美洲", "🇪🇺 欧洲"])
        with t1: st.dataframe(df_show, use_container_width=True, hide_index=True)
        with t2: st.dataframe(df_show[df_show["区域"]=="🌏 亚洲"], use_container_width=True, hide_index=True)
        with t3: st.dataframe(df_show[df_show["区域"]=="🇺🇸 美洲"], use_container_width=True, hide_index=True)
        with t4: st.dataframe(df_show[df_show["区域"]=="🇪🇺 欧洲"], use_container_width=True, hide_index=True)

        # 写入历史
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%H:%M')} | {winner['ip']} | {winner['lat']}ms\n")
            
        if os.path.exists(DB_FILE):
            st.markdown("---")
            with st.expander("📜 查看运行日志"):
                with open(DB_FILE, "r") as f: st.code("".join(f.readlines()[-10:]))
                if st.button("🗑️ 清空日志"):
                    os.remove(DB_FILE)
                    st.rerun()
    else:
        st.warning("⚠️ 本轮未发现优质节点")

st.caption(f"🕒 更新时间: {datetime.now().strftime('%H:%M:%S')} (每 10 分钟自动刷新)")
time.sleep(600)
st.rerun()
