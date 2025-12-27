import streamlit as st
import requests
import time
import re
import random
import os
import pandas as pd
from datetime import datetime

# --- 1. 页面配置 ---
st.set_page_config(page_title="4K 引擎：多风格轮换版", page_icon="🎨", layout="wide")

# ===========================
# 🎨 随机主题引擎 (Theme Engine)
# ===========================
THEMES = [
    {
        "name": "Cyberpunk 2077",
        "bg": "https://w.wallhaven.cc/full/72/wallhaven-72rdqo.jpg",
        "sidebar": "https://w.wallhaven.cc/full/ox/wallhaven-oxvkyl.jpg",
        "main_color": "#00ffea", # 霓虹青
        "border_color": "#ff0055", # 霓虹红
        "text_color": "#ffffff",
        "overlay": "rgba(10, 10, 20, 0.85)"
    },
    {
        "name": "Black & Gold",
        "bg": "https://w.wallhaven.cc/full/zy/wallhaven-zygekj.jpg",
        "sidebar": "https://w.wallhaven.cc/full/vg/wallhaven-vg8285.jpg",
        "main_color": "#FFD700", # 金色
        "border_color": "#B8860B", # 暗金
        "text_color": "#F0F0F0",
        "overlay": "rgba(0, 0, 0, 0.9)"
    },
    {
        "name": "Deep Space",
        "bg": "https://w.wallhaven.cc/full/xl/wallhaven-xl65oz.jpg",
        "sidebar": "https://w.wallhaven.cc/full/wy/wallhaven-wy2jj6.jpg",
        "main_color": "#00BFFF", # 深空蓝
        "border_color": "#4169E1", # 皇家蓝
        "text_color": "#E6E6FA",
        "overlay": "rgba(10, 20, 40, 0.85)"
    },
    {
        "name": "Nature Calm",
        "bg": "https://w.wallhaven.cc/full/rr/wallhaven-rr22qm.jpg",
        "sidebar": "https://w.wallhaven.cc/full/eo/wallhaven-eo88or.jpg",
        "main_color": "#98FB98", # 苍白绿
        "border_color": "#2E8B57", # 海洋绿
        "text_color": "#F5F5F5",
        "overlay": "rgba(30, 40, 30, 0.85)"
    }
]

# 随机选择一个主题
current_theme = random.choice(THEMES)

st.markdown(f"""
    <style>
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    header {{visibility: hidden;}}

    /* 全局背景 */
    .stApp {{
        background-image: url("{current_theme['bg']}");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }}

    /* 内容容器 */
    .block-container {{
        background-color: {current_theme['overlay']};
        border-radius: 12px;
        border: 1px solid {current_theme['border_color']};
        padding: 2rem;
        margin-top: 1rem;
        backdrop-filter: blur(5px);
    }}

    /* 侧边栏 */
    [data-testid="stSidebar"] {{
        background-color: {current_theme['overlay']};
        border-right: 1px solid {current_theme['border_color']};
    }}
    
    /* 文字颜色 */
    h1, h2, h3, p, span, div {{
        color: {current_theme['text_color']} !important;
        font-family: 'Segoe UI', sans-serif;
    }}
    
    /* 标题强调色 */
    h1, h2 {{
        color: {current_theme['main_color']} !important;
        text-shadow: 0 0 10px {current_theme['border_color']}80;
    }}

    /* 表格样式 */
    [data-testid="stDataFrame"] {{
        border: 1px solid {current_theme['border_color']};
    }}

    /* 成功/信息框 */
    .stSuccess, .stInfo, .stWarning {{
        background-color: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid {current_theme['main_color']};
        color: {current_theme['text_color']} !important;
    }}
    
    /* 指标卡片 */
    div[data-testid="metric-container"] {{
        background-color: rgba(255, 255, 255, 0.05);
        border-left: 4px solid {current_theme['main_color']};
        padding: 10px;
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
    st.error("❌ 配置缺失，请检查 Secrets")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 核心功能 ---

def check_api_health_percent():
    """【新功能】API 健康度百分比计算"""
    try:
        start = time.time()
        url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
        headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
        resp = requests.get(url, headers=headers, timeout=2).json()
        latency = (time.time() - start) * 1000 # 毫秒
        
        if resp.get("success"):
            # 算法：延迟越低分越高
            # <200ms = 100%
            # 每增加 100ms 扣 5%，最低 60%
            score = 100
            if latency > 200:
                deduct = int((latency - 200) / 100) * 5
                score = max(60, 100 - deduct)
            return True, score, int(latency)
        else:
            return False, 0, 0
    except:
        return False, 0, 9999

def get_ip_info(ip):
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country"
        r = requests.get(url, timeout=1).json()
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
        r = requests.get("https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt", timeout=3)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        return random.sample(list(found), min(len(found), 15))
    except: return []

def fast_ping(ip):
    try:
        start = time.time()
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        return int((time.time() - start) * 1000)
    except: return 9999

def check_netflix(ip):
    try:
        r = requests.get(f"http://{ip}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.5)
        return "✅" if r.status_code in [200, 301, 302] else "❌"
    except: return "❓"

def sync_dns(new_ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        search = requests.get(url, headers=headers, params=params, timeout=5).json()
        
        if not search.get("success") or not search.get("result"): return "❌ 未找到记录"
        record = search["result"][0]
        
        if record["content"] == new_ip: return "✅ 解析已稳如泰山"
        
        requests.put(f"{url}/{record['id']}", headers=headers, json={
            "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
        })
        return f"🚀 已同步新核心 -> {new_ip}"
    except: return "⚠️ API 通信异常"

# --- 4. 主程序 ---

st.title(f"🚀 4K 引擎：{current_theme['name']} 版")

# 侧边栏
with st.sidebar:
    st.image(current_theme['sidebar'], use_column_width=True)
    st.caption(f"🎨 当前主题: {current_theme['name']}")
    
    st.markdown("---")
    st.header("📊 系统健康度")
    
    # 优先检测 API
    is_ok, score, lat = check_api_health_percent()
    
    if is_ok:
        # 动态颜色：分数高显示绿，低显示黄/红
        color = "normal" if score > 90 else "off"
        st.metric("API 连通率", f"{score}%", f"响应 {lat}ms", delta_color=color)
        st.progress(score / 100)
    else:
        st.metric("API 连通率", "0%", "连接失败", delta_color="inverse")
        st.error("无法连接 Cloudflare")
    
    st.divider()
    if st.button("🎲 手动切换主题 / 刷新"):
        st.rerun()

# 主运行区
with st.spinner("📡 正在扫描全球骨干网络..."):
    results = []
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    global_ips = get_global_ips()
    candidates = base_ips + global_ips
    
    # 第一步：极速初筛
    valid_nodes = []
    for ip in candidates:
        lat = fast_ping(ip)
        if lat < 500:
            valid_nodes.append({"ip": ip, "lat": lat, "type": "⭐ 核心" if ip in base_ips else "🌐 搜集"})
    
    final_data = []
    if valid_nodes:
        # 第二步：精细测试前 8 名
        valid_nodes.sort(key=lambda x: x['lat'])
        for node in valid_nodes[:8]:
            reg, ctry = get_ip_info(node['ip'])
            nf = check_netflix(node['ip']) if node['lat'] < 200 else "❓"
            node.update({"region": reg, "country": ctry, "nf": nf})
            final_data.append(node)
            
        winner = final_data[0]
        
        # 冠军展示
        st.success(f"🏆 优选节点锁定: {winner['ip']} ({winner['region']}) | 延迟 {winner['lat']}ms")
        st.info(sync_dns(winner['ip']))
        
        # 分区看板
        df = pd.DataFrame(final_data)
        cols = {"ip": "IP", "region": "区域", "country": "国家", "lat": "延迟", "nf": "解锁", "type": "类型"}
        df_show = df[cols.keys()].rename(columns=cols)
        
        t1, t2, t3, t4 = st.tabs(["🌐 全球视图", "🌏 亚洲节点", "🇺🇸 美洲节点", "🇪🇺 欧洲节点"])
        with t1: st.dataframe(df_show, use_container_width=True, hide_index=True)
        with t2: st.dataframe(df_show[df_show["区域"]=="🌏 亚洲"], use_container_width=True, hide_index=True)
        with t3: st.dataframe(df_show[df_show["区域"]=="🇺🇸 美洲"], use_container_width=True, hide_index=True)
        with t4: st.dataframe(df_show[df_show["区域"]=="🇪🇺 欧洲"], use_container_width=True, hide_index=True)

        # 历史
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%H:%M')} | {winner['ip']} | {winner['lat']}ms\n")
        
        if os.path.exists(DB_FILE):
            st.markdown("---")
            with st.expander("📜 运行日志"):
                with open(DB_FILE, "r") as f: st.code("".join(f.readlines()[-10:]))
    else:
        st.warning("⚠️ 本轮扫描未发现优质节点")

st.caption(f"🕒 更新时间: {datetime.now().strftime('%H:%M:%S')} (每 10 分钟自动轮换主题与IP)")
time.sleep(600)
st.rerun()
