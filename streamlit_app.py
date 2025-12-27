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
# 1. 页面与主题配置
# ===========================
st.set_page_config(page_title="4K VLESS 引擎：极速版", page_icon="⚡", layout="wide")

THEMES = [
    {"name": "Cyberpunk", "bg": "https://w.wallhaven.cc/full/72/wallhaven-72rdqo.jpg", "main": "#00ffea", "border": "#ff0055", "text": "#ffffff", "overlay": "rgba(10, 10, 20, 0.85)"},
    {"name": "Deep Space", "bg": "https://w.wallhaven.cc/full/xl/wallhaven-xl65oz.jpg", "main": "#00BFFF", "border": "#4169E1", "text": "#E6E6FA", "overlay": "rgba(10, 20, 40, 0.85)"},
    {"name": "Obsidian", "bg": "https://w.wallhaven.cc/full/zy/wallhaven-zygekj.jpg", "main": "#FFD700", "border": "#B8860B", "text": "#F0F0F0", "overlay": "rgba(0, 0, 0, 0.9)"}
]
theme = random.choice(THEMES)

st.markdown(f"""
    <style>
    .stApp {{ background-image: url("{theme['bg']}"); background-size: cover; background-attachment: fixed; }}
    .block-container {{ background-color: {theme['overlay']}; border: 1px solid {theme['border']}; border-radius: 12px; padding: 1.5rem; backdrop-filter: blur(5px); }}
    h1, h2, h3, p, span, div {{ color: {theme['text']} !important; font-family: sans-serif; }}
    div[data-testid="stMetricValue"] {{ color: {theme['main']} !important; }}
    .stProgress > div > div > div > div {{ background-color: {theme['main']}; }}
    div[data-testid="column"] {{ border: 1px solid {theme['border']}; background: rgba(255,255,255,0.05); border-radius: 8px; padding: 10px; }}
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 核心配置读取
# ===========================
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except Exception:
    st.error("❌ 缺少 secrets.toml 配置！请在 .streamlit/secrets.toml 中配置 api_token, zone_id 和 record_name。")
    st.stop()

DB_FILE = "vless_history.log"

# ===========================
# 3. 功能函数定义
# ===========================

@st.cache_data(ttl=3600)  # 缓存 1 小时，减少 API 调用
def get_ip_info(ip):
    """获取 IP 地理位置（带缓存）"""
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country"
        r = requests.get(url, timeout=2).json()
        cc = r.get("countryCode", "UNK")
        region = "🌍 其他"
        if cc in ['CN', 'HK', 'TW', 'JP', 'KR', 'SG']: region = "🌏 亚洲"
        elif cc in ['US', 'CA', 'MX']: region = "🇺🇸 美洲"
        elif cc in ['DE', 'GB', 'FR', 'NL']: region = "🇪🇺 欧洲"
        return region, r.get("country", "Unknown")
    except:
        return "🛸 未知", "Unknown"

def check_api_health():
    """Cloudflare API 健康检查"""
    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        start = time.time()
        resp = requests.get(url, headers=headers, timeout=5).json()
        latency = int((time.time() - start) * 1000)
        if resp.get("success"):
            return True, latency
    except:
        pass
    return False, 0

def get_global_ips():
    """获取动态 IP 池"""
    try:
        # 使用更稳定的优选 IP 列表源
        r = requests.get("https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt", timeout=5)
        ips = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        return random.sample(ips, min(len(ips), 15)) # 增加样本数
    except:
        return []

def fast_ping(ip):
    """模拟 VLESS 握手测试 (HTTPing)"""
    try:
        start = time.time()
        # 使用 HEAD 请求减少流量，Host 指向你的域名验证穿透
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.5)
        return int((time.time() - start) * 1000)
    except:
        return 9999

def check_netflix(ip):
    """Netflix 解锁检测"""
    try:
        r = requests.get(f"http://{ip}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=2)
        return "✅" if r.status_code in [200, 301, 302] else "❌"
    except:
        return "❓"

def process_single_node(node_data):
    """单个节点处理逻辑（用于并发）"""
    ip = node_data['ip']
    lat = fast_ping(ip)
    
    # 只有延迟低于 800ms 才进行后续详情查询，节省资源
    if lat < 800:
        region, country = get_ip_info(ip)
        # 只有延迟极低才测 Netflix
        nf = check_netflix(ip) if lat < 300 else "❓"
        return {
            "ip": ip,
            "region": region,
            "country": country,
            "lat": lat,
            "nf": nf,
            "type": node_data['type']
        }
    return None

def sync_dns(new_ip):
    """更新 Cloudflare DNS 记录"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        # 1. 查找记录
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        search = requests.get(url, headers=headers, params=params, timeout=10).json()
        
        if not search.get("success") or not search.get("result"):
            return "❌ 未找到 DNS 记录，请先在 CF 后台手动创建"
            
        record = search["result"][0]
        if record["content"] == new_ip:
            return "✅ 当前 IP 依然最优，无需更新"
            
        # 2. 更新记录
        update_url = f"{url}/{record['id']}"
        payload = {
            "type": "A", "name": CF_CONFIG['record_name'], 
            "content": new_ip, "ttl": 60, "proxied": False # VLESS 通常不开启小黄云
        }
        res = requests.put(update_url, headers=headers, json=payload).json()
        
        if res.get("success"):
            return f"🚀 解析已更新: {record['content']} -> {new_ip}"
        else:
            return f"⚠️ 更新失败: {res.get('errors')[0].get('message')}"
            
    except Exception as e:
        return f"⚠️ API 通信错误: {str(e)}"

# ===========================
# 4. 主程序 UI
# ===========================

st.title(f"🚀 VLESS 智能引擎 ({theme['name']})")

# 顶部状态栏
api_ok, api_lat = check_api_health()
c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    if api_ok:
        st.success(f"📡 API 连接正常 ({api_lat}ms)")
    else:
        st.warning("⚠️ API 连接波动")
with c2:
    st.metric("目标域名", CF_CONFIG['record_name'])
with c3:
    if st.button("🔄 立即刷新"):
        st.rerun()

st.divider()

# 核心扫描逻辑
with st.spinner("⚡ 正在并发扫描全球骨干网..."):
    # 1. 准备候选列表
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    dynamic_ips = get_global_ips()
    
    tasks = []
    # 标记来源
    for ip in base_ips: tasks.append({"ip": ip, "type": "⭐ 核心"})
    for ip in dynamic_ips: tasks.append({"ip": ip, "type": "🌐 动态"})
    
    valid_nodes = []
    
    # 2. 多线程并发执行 (最大 10 线程)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(process_single_node, tasks)
        for res in results:
            if res:
                valid_nodes.append(res)
    
    # 3. 结果决策
    if valid_nodes:
        # 按延迟排序
        valid_nodes.sort(key=lambda x: x['lat'])
        winner = valid_nodes[0]
        
        # 显示冠军
        st.balloons()
        msg = sync_dns(winner['ip'])
        
        col_win, col_log = st.columns([2, 1])
        with col_win:
            st.info(f"🏆 **优选结果**: {winner['ip']}")
            st.caption(f"📍 {winner['region']} - {winner['country']} | 📶 延迟: {winner['lat']}ms | 🎬 Netflix: {winner['nf']}")
            st.write(f"📝 **同步状态**: {msg}")
            
        # 记录日志
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | {winner['lat']}ms | {msg}\n")

        # 数据表格展示
        df = pd.DataFrame(valid_nodes)
        df_show = df[["ip", "region", "country", "lat", "nf", "type"]].rename(columns={
            "ip": "IP 地址", "region": "区域", "country": "国家", "lat": "延迟(ms)", "nf": "解锁", "type": "类型"
        })
        
        tab1, tab2 = st.tabs(["📊 所有节点", "📜 运行日志"])
        with tab1:
            st.dataframe(df_show, use_container_width=True, hide_index=True)
        with tab2:
            if os.path.exists(DB_FILE):
                with open(DB_FILE, "r") as f:
                    lines = f.readlines()
                    st.code("".join(lines[-10:])) # 只显示最后10行

    else:
        st.error("⚠️ 全球扫描完成，但未发现可用节点，请检查网络设置。")

# 底部自动刷新机制
st.caption(f"🕒 最后更新: {datetime.now().strftime('%H:%M:%S')} (600秒后自动轮询)")
time.sleep(600)
st.rerun()
