import streamlit as st
import requests
import time
import re
import random
import os
import pandas as pd
from datetime import datetime

# --- 1. 页面配置 ---
st.set_page_config(page_title="4K 引擎：全球极速版", page_icon="🚀", layout="centered")

# 界面美化
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1rem;}
    /* 侧边栏优化 */
    [data-testid="stSidebar"] {background-color: #f8f9fa;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 配置读取 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except Exception as e:
    st.error(f"❌ 配置读取失败: {e}")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 核心功能函数 ---

def check_api_health():
    """优先检测 API 健康度"""
    try:
        url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
        headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
        # 设置极短超时，防止卡住页面
        resp = requests.get(url, headers=headers, timeout=2).json()
        if resp.get("success"):
            return True, "🟢 API 正常 (已连接)"
        else:
            return False, f"🔴 权限错误: {resp['errors'][0]['message']}"
    except:
        return False, "🟡 网络连接超时"

def get_ip_info(ip):
    """查询 IP 地理位置 (仅对优选 IP 执行)"""
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country"
        r = requests.get(url, timeout=1.5).json() # 短超时
        cc = r.get("countryCode", "UNK")
        country = r.get("country", "Unknown")
        
        # 区域判断
        region = "🌍 其他"
        if cc in ['CN', 'HK', 'TW', 'JP', 'KR', 'SG', 'MY', 'TH', 'VN', 'IN', 'ID', 'PH']:
            region = "🌏 亚洲"
        elif cc in ['US', 'CA', 'MX', 'BR', 'AR', 'CL']:
            region = "🇺🇸 美洲"
        elif cc in ['DE', 'GB', 'FR', 'NL', 'RU', 'IT', 'ES', 'PL', 'UA', 'TR']:
            region = "🇪🇺 欧洲"
            
        return region, country
    except:
        return "🛸 未知", "Unknown"

def get_global_ips():
    sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
    pool = set()
    try:
        r = requests.get(sources[0], timeout=3)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        pool.update(found)
    except: pass
    return random.sample(list(pool), min(len(pool), 15))

def fast_ping(ip):
    """纯粹的测速 (不查地理位置，保证速度)"""
    try:
        start = time.time()
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        return int((time.time() - start) * 1000)
    except:
        return 9999

def check_netflix(ip):
    """解锁检测"""
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
        
        if not search.get("success") or not search.get("result"):
            return "❌ 未找到 A 记录"
            
        record = search["result"][0]
        if record["content"] == new_ip:
            return "✅ 已是最新 IP"
            
        update = requests.put(f"{url}/{record['id']}", headers=headers, json={
            "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
        }).json()
        
        return f"🚀 同步成功 -> {new_ip}" if update.get("success") else "❌ 更新失败"
    except Exception as e: return f"⚠️ 异常: {e}"

# --- 4. 主界面逻辑 ---

st.title("🚀 4K 引擎：全球极速版")

# 侧边栏：优先加载
with st.sidebar:
    st.header("⚙️ 状态监控")
    
    # 立即执行检查
    is_ok, status_msg = check_api_health()
    if is_ok:
        st.success(status_msg)
    else:
        st.error(status_msg)
    
    st.divider()
    if st.button("🗑️ 清空历史"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

# 主运行区
with st.spinner("⚡ 正在极速扫描全球节点..."):
    results = []
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    global_ips = get_global_ips()
    
    # 1. 第一阶段：极速测速 (过滤掉连不上的)
    candidates = base_ips + global_ips
    valid_nodes = []
    
    for ip in candidates:
        lat = fast_ping(ip)
        if lat < 500: # 只处理 500ms 以内的
            valid_nodes.append({"ip": ip, "lat": lat, "type": "🏠 专属" if ip in base_ips else "🌍 搜集"})
    
    # 2. 第二阶段：精细查询 (只查有效节点)
    final_data = []
    if valid_nodes:
        # 按延迟排序，只处理前 8 名，防止 API 耗时过长
        valid_nodes.sort(key=lambda x: x['lat'])
        top_nodes = valid_nodes[:8] 
        
        for node in top_nodes:
            # 查地理位置
            reg, ctry = get_ip_info(node['ip'])
            # 查解锁 (仅低延迟)
            nf = check_netflix(node['ip']) if node['lat'] < 200 else "❓"
            
            node.update({"region": reg, "country": ctry, "nf": nf})
            final_data.append(node)
            
        # 选冠军
        winner = final_data[0]
        
        # 3. 结果展示
        st.success(f"🏆 冠军: {winner['ip']} ({winner['region']}) | 延迟: {winner['lat']}ms")
        st.info(sync_dns(winner['ip']))
        
        # --- 分区展示 ---
        st.subheader("📊 全球节点分区看板")
        
        df = pd.DataFrame(final_data)
        cols_map = {"ip": "IP地址", "region": "区域", "country": "国家", "lat": "延迟", "nf": "解锁", "type": "来源"}
        df_show = df[["ip", "region", "country", "lat", "nf", "type"]].rename(columns=cols_map)
        
        tab1, tab2, tab3, tab4 = st.tabs(["🌐 全部", "🌏 亚洲", "🇺🇸 美洲", "🇪🇺 欧洲"])
        
        with tab1: st.dataframe(df_show, use_container_width=True, hide_index=True)
        with tab2: 
            d = df_show[df_show["区域"]=="🌏 亚洲"]
            if not d.empty: st.dataframe(d, use_container_width=True, hide_index=True)
            else: st.caption("暂无亚洲优选节点")
        with tab3:
            d = df_show[df_show["区域"]=="🇺🇸 美洲"]
            if not d.empty: st.dataframe(d, use_container_width=True, hide_index=True)
            else: st.caption("暂无美洲优选节点")
        with tab4:
            d = df_show[df_show["区域"]=="🇪🇺 欧洲"]
            if not d.empty: st.dataframe(d, use_container_width=True, hide_index=True)
            else: st.caption("暂无欧洲优选节点")

        # 历史记录
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%H:%M')} | {winner['ip']} | {winner['region']} | {winner['lat']}ms\n")
            
        if os.path.exists(DB_FILE):
            st.divider()
            with st.expander("📜 历史记录"):
                with open(DB_FILE, "r") as f: st.text("".join(f.readlines()[-10:]))
                
    else:
        st.warning("⚠️ 本轮探测无可用节点")

st.caption(f"🕒 更新于: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
