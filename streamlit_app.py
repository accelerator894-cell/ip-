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
# 1. 页面配置与样式
# ===========================
st.set_page_config(page_title="VLESS 区域分层版", page_icon="🌐", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #FAFAFA; }
    div[data-testid="column"] { background-color: #1E1E1E; border: 1px solid #333; border-radius: 8px; padding: 15px; }
    /* 调整 Tab 样式 */
    button[data-baseweb="tab"] { font-size: 18px; font-weight: bold; }
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
# 3. 核心功能函数
# ===========================

@st.cache_data(ttl=3600)
def get_ip_info(ip):
    """获取区域信息"""
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country"
        r = requests.get(url, timeout=2).json()
        cc = r.get("countryCode", "UNK")
        if cc in ['CN', 'HK', 'TW', 'JP', 'KR', 'SG', 'MY', 'TH', 'VN']: return "🌏 亚洲", r.get("country")
        if cc in ['US', 'CA', 'MX', 'BR', 'AR']: return "🇺🇸 美洲", r.get("country")
        if cc in ['DE', 'GB', 'FR', 'NL', 'RU', 'IT', 'EU']: return "🇪🇺 欧洲", r.get("country")
        return "🌍 其他", r.get("country")
    except:
        return "🛸 未知", "Unknown"

def get_collected_ips():
    """获取网络采集 IP"""
    sources = [
        "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
        "https://raw.githubusercontent.com/w8ves/CF-IP/master/speedtest.txt"
    ]
    all_ips = set()
    def fetch(url):
        try:
            return re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', requests.get(url, timeout=3).text)
        except: return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        for res in ex.map(fetch, sources): all_ips.update(res)
    
    # 随机取 60 个作为采集样本
    return random.sample(list(all_ips), min(len(all_ips), 60))

def fast_ping(ip):
    try:
        start = time.time()
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.5)
        return int((time.time() - start) * 1000)
    except: return 9999

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
    except Exception as e: return f"⚠️ 错误: {str(e)[:10]}"

# ===========================
# 4. 主逻辑
# ===========================

st.title("🌐 VLESS 分区优选 Pro")

if st.button("🚀 开始分区扫描", type="primary"):
    
    with st.spinner("⚡ 正在混合扫描：本地预设 + 网络采集..."):
        # --- 1. 数据源准备 (区分本地和采集) ---
        local_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
        collected_ips = get_collected_ips()
        
        tasks = []
        # 标记来源
        for ip in local_ips: tasks.append({"ip": ip, "source": "🏠 本地预设"})
        for ip in collected_ips: tasks.append({"ip": ip, "source": "☁️ 网络采集"})
        
        # --- 2. 并发测速 ---
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
            future_map = {ex.submit(fast_ping, t['ip']): t for t in tasks}
            for fut in concurrent.futures.as_completed(future_map):
                node = future_map[fut]
                lat = fut.result()
                if lat < 800: # 只保留有效节点
                    reg, ctry = get_ip_info(node['ip'])
                    node.update({"lat": lat, "region": reg, "country": ctry})
                    results.append(node)
        
        # --- 3. 结果展示 ---
        if results:
            results.sort(key=lambda x: x['lat'])
            winner = results[0]
            sync_msg = sync_dns(winner['ip'])
            
            # 顶部冠军卡片
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1: st.success(f"🏆 全球最优: **{winner['ip']}** ({winner['source']})")
            with c2: st.metric("延迟", f"{winner['lat']} ms")
            with c3: st.caption(f"📝 {sync_msg}")
            
            # --- 4. 分区数据表格 ---
            st.divider()
            
            # 创建 DataFrame 并重命名列
            df = pd.DataFrame(results)
            cols = {"source": "来源", "ip": "IP 地址", "lat": "延迟(ms)", "region": "区域", "country": "国家"}
            df = df[cols.keys()].rename(columns=cols)
            
            # 定义 Tabs
            t_asia, t_amer, t_euro, t_all = st.tabs(["🌏 亚洲区", "🇺🇸 美洲区", "🇪🇺 欧洲区", "🌐 所有节点"])
            
            # 渲染不同区域的函数
            def show_table(dataframe):
                st.dataframe(
                    dataframe, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "延迟(ms)": st.column_config.NumberColumn(format="%d ms"),
                    }
                )

            with t_asia:
                sub_df = df[df["区域"] == "🌏 亚洲"]
                if not sub_df.empty: show_table(sub_df)
                else: st.info("⚠️ 该区域暂无低延迟节点")
                
            with t_amer:
                sub_df = df[df["区域"] == "🇺🇸 美洲"]
                if not sub_df.empty: show_table(sub_df)
                else: st.info("⚠️ 该区域暂无低延迟节点")
                
            with t_euro:
                sub_df = df[df["区域"] == "🇪🇺 欧洲"]
                if not sub_df.empty: show_table(sub_df)
                else: st.info("⚠️ 该区域暂无低延迟节点")
                
            with t_all:
                # 在总表中，我们可以高亮“来源”列
                show_table(df)
            
            # 写入日志
            with open(DB_FILE, "a") as f:
                f.write(f"{datetime.now().strftime('%H:%M')} | {winner['ip']} | {winner['lat']}ms | {winner['source']}\n")
                
        else:
            st.error("❌ 未发现任何可用节点")

else:
    st.info("👋 点击上方按钮开始扫描")
    
# 历史日志
with st.expander("📜 查看历史记录"):
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f: st.text("".join(f.readlines()[-10:]))
