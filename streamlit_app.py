import streamlit as st
import requests
import time
import re
import random
import os
import pandas as pd # 需要用到 pandas 进行数据分类
from datetime import datetime

# --- 1. 页面配置 ---
st.set_page_config(page_title="4K 引擎：全球分区版", page_icon="🌍", layout="centered")

# 美化样式
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1.5rem;}
    /* 调整 Tab 样式 */
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #f0f2f6; border-radius: 5px; }
    .stTabs [aria-selected="true"] { background-color: #e8f0fe; font-weight: bold; }
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
    try:
        url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
        headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
        resp = requests.get(url, headers=headers, timeout=3).json()
        return "🟢 正常" if resp.get("success") else "🔴 异常"
    except: return "🟡 连接中"

def get_ip_location(ip):
    """【新功能】查询 IP 地理位置"""
    try:
        # 使用 ip-api.com 查询 (免费接口，注意频率限制)
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country"
        r = requests.get(url, timeout=2).json()
        cc = r.get("countryCode", "UNK")
        country = r.get("country", "Unknown")
        
        # 简单区域映射
        region = "🌍 其他"
        if cc in ['CN', 'HK', 'TW', 'JP', 'KR', 'SG', 'MY', 'TH', 'VN', 'IN']:
            region = "🌏 亚洲"
        elif cc in ['US', 'CA', 'MX', 'BR', 'AR']:
            region = "🇺🇸 美洲"
        elif cc in ['DE', 'GB', 'FR', 'NL', 'RU', 'IT', 'ES', 'PL', 'UA']:
            region = "🇪🇺 欧洲"
            
        return region, f"{country} ({cc})"
    except:
        return "👽 未知", "Unknown"

def get_global_ips():
    sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
    pool = set()
    try:
        r = requests.get(sources[0], timeout=5)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        pool.update(found)
    except: pass
    # 随机取 12 个 (增加样本量以便分类)
    return random.sample(list(pool), min(len(pool), 12))

def test_node(ip, label):
    data = {"ip": ip, "type": label, "lat": 9999, "nf": "❓", "region": "Thinking...", "country": "..."}
    try:
        # 1. 获取地理位置 (新)
        data["region"], data["country"] = get_ip_location(ip)
        
        # 2. 测延迟
        start = time.time()
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.5)
        data["lat"] = int((time.time() - start) * 1000)
        
        # 3. 测解锁
        if data["lat"] < 250:
            nf = requests.get(f"http://{ip}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.5)
            data["nf"] = "✅" if nf.status_code in [200, 301, 302] else "❌"
    except: pass
    return data

def sync_dns(new_ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        search = requests.get(url, headers=headers, params=params, timeout=10).json()
        if not search.get("success") or not search.get("result"):
            return f"❌ 未找到记录"
        
        record = search["result"][0]
        if record["content"] == new_ip:
            return "✅ 解析已是最新"
            
        update = requests.put(f"{url}/{record['id']}", headers=headers, json={
            "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
        }).json()
        return f"🚀 同步成功 -> {new_ip}" if update.get("success") else "❌ 更新失败"
    except Exception as e: return f"⚠️ 异常: {str(e)}"

# --- 4. 主程序 ---

st.title("🌍 4K 引擎：全球分区版")

with st.sidebar:
    st.header("⚙️ 监控中心")
    st.metric("API 状态", check_api_health())
    if st.button("🗑️ 清空历史"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

with st.spinner("🕵️ 全球巡检中 (正在进行区域归类)..."):
    results = []
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    global_ips = get_global_ips()
    
    # 扫描
    for ip in base_ips: results.append(test_node(ip, "🏠 专属"))
    for ip in global_ips: results.append(test_node(ip, "🌍 搜集"))
    
    # 过滤有效 IP
    active = [r for r in results if r["lat"] < 9999]
    
    if active:
        active.sort(key=lambda x: x['lat'])
        winner = active[0]
        
        # 冠军展示
        st.success(f"🏆 全球总冠军: {winner['ip']} | {winner['region']} | 延迟 {winner['lat']}ms")
        st.info(sync_dns(winner['ip']))
        
        # --- 分区展示核心逻辑 ---
        st.subheader("📊 区域分类看板")
        
        # 创建标签页
        tab_all, tab_asia, tab_us, tab_eu = st.tabs(["🌐 全部节点", "🌏 亚洲专区", "🇺🇸 美洲专区", "🇪🇺 欧洲专区"])
        
        # 转为 DataFrame 以便展示
        df = pd.DataFrame(active)
        # 调整列顺序和名称
        cols_map = {"ip": "IP地址", "region": "区域", "country": "国家/地区", "lat": "延迟(ms)", "nf": "解锁", "type": "来源"}
        df_display = df[["ip", "region", "country", "lat", "nf", "type"]].rename(columns=cols_map)

        with tab_all:
            st.dataframe(df_display, use_container_width=True, hide_index=True)
            
        with tab_asia:
            df_asia = df_display[df_display["区域"] == "🌏 亚洲"]
            if not df_asia.empty: st.dataframe(df_asia, use_container_width=True, hide_index=True)
            else: st.info("本轮未探测到亚洲优选节点")
            
        with tab_us:
            df_us = df_display[df_display["区域"] == "🇺🇸 美洲"]
            if not df_us.empty: st.dataframe(df_us, use_container_width=True, hide_index=True)
            else: st.info("本轮未探测到美洲优选节点")
            
        with tab_eu:
            df_eu = df_display[df_display["区域"] == "🇪🇺 欧洲"]
            if not df_eu.empty: st.dataframe(df_eu, use_container_width=True, hide_index=True)
            else: st.info("本轮未探测到欧洲优选节点")
            
        # 历史记录
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%H:%M')} | {winner['ip']} | {winner['region']} | {winner['lat']}ms\n")
            
        if os.path.exists(DB_FILE):
            st.divider()
            with st.expander("📜 历史优选记录"):
                with open(DB_FILE, "r") as f: st.text("".join(f.readlines()[-15:]))
    else:
        st.warning("⚠️ 全网探测超时，请检查网络。")

st.caption(f"🕒 更新时间: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
