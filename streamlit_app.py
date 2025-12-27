import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. 配置加载 (Secrets) ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except:
    st.error("❌ 配置缺失：请在 Secrets 中配置 api_token, zone_id 和 record_name")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 2. 核心功能函数 ---

def check_cf_status():
    """监控 API 健康度"""
    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        r = requests.get(url, headers=headers, timeout=5).json()
        return "🟢 正常" if r.get("success") else "🔴 受限"
    except: return "🟡 延迟"

def fetch_global_ips():
    """【功能回归】自动搜集全球 IP"""
    sources = [
        "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
        "https://raw.githubusercontent.com/vfarid/cf-ip-scanner/main/pings.txt"
    ]
    ips = set()
    for url in sources:
        try:
            r = requests.get(url, timeout=5)
            found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
            ips.update(found)
        except: continue
    return random.sample(list(ips), min(len(ips), 15)) # 抽取15个确保速度

def quick_ping(ip, label):
    """【性能优化】快速探测"""
    data = {"ip": ip, "type": label, "lat": 9999, "nf": "❓", "score": 0}
    try:
        start = time.time()
        # 阶梯式：1秒超时排除死IP
        r = requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        if r.status_code < 500:
            data["lat"] = int((time.time() - start) * 1000)
    except: pass
    return data

def deep_test(data):
    """【功能回归】流媒体解锁测试"""
    try:
        nf = requests.get(f"http://{data['ip']}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.2)
        data["nf"] = "✅" if nf.status_code in [200, 301, 302] else "❌"
        data["score"] = 1 if data["nf"] == "✅" else 0
    except: data["nf"] = "❌"
    return data

def save_winner(winner):
    """【功能回归】历史记录存盘"""
    try:
        log = f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | {winner['lat']}ms | {winner['type']}\n"
        lines = []
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r") as f: lines = f.readlines()
        lines.insert(0, log)
        with open(DB_FILE, "w") as f: f.writelines(lines[:50])
    except: pass

# --- 3. 页面渲染 ---

st.set_page_config(page_title="4K 引擎：全能终极版", page_icon="🏎️")
st.title("🏎️ 4K 引擎：全能终极版")

with st.sidebar:
    st.header("🔐 云端监控")
    health = check_cf_status()
    st.metric("API 健康度", health)
    mode = st.radio("优选模式", ("⚡ 速度优先", "🎬 解锁优先"))
    if st.button("🗑️ 清空本地历史数据"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

# --- 4. 自动化主流程 ---

with st.spinner("🕵️ 正在全球进货并进行阶梯式质检..."):
    # 关键修复：预先初始化 results 避免 NameError
    results = [] 
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1", "173.245.58.1", "172.64.36.5", "162.159.46.10", "188.114.97.1", "104.16.160.1", "104.17.160.1", "104.18.160.1", "104.19.160.1", "104.20.160.1", "104.21.160.1", "104.22.160.1"]
    
    # 1. 搜集并快测
    dynamic_ips = fetch_global_ips()
    for ip in base_ips: results.append(quick_ping(ip, "🏠 基础"))
    for ip in dynamic_ips: results.append(quick_ping(ip, "🌍 搜集"))
    
    # 2. 筛选活着的 IP
    active = [r for r in results if r["lat"] < 9999]
    if active:
        active.sort(key=lambda x: x['lat'])
        top_6 = active[:6] # 只取前6名测解锁，保命速度
        for q in top_6: deep_test(q)
        
        # 3. 模式排序
        if "速度" in mode: top_6.sort(key=lambda x: x['lat'])
        else: top_6.sort(key=lambda x: (-x['score'], x['lat']))
        
        winner = top_6[0]
        
        # 4. 存盘记录
        if 'last_winner' not in st.session_state or st.session_state.last_winner != winner['ip']:
            save_winner(winner)
            st.session_state.last_winner = winner['ip']

        # 5. UI 展示（冠军面板）
        st.success(f"🎯 本轮优选：{winner['ip']} ({winner['type']})")
        c1, c2, c3 = st.columns(3)
        c1.metric("平均延迟", f"{winner['lat']}ms")
        c2.metric("流媒体分", winner['score'])
        c3.write(f"📺 NF: {winner['nf']}")

        # 【看板回归】全球节点分类看板
        st.subheader("📊 全球节点分类看板")
        st.dataframe(results, use_container_width=True)
        
        # 【功能回归】历史存盘展示
        if os.path.exists(DB_FILE):
            st.divider()
            st.subheader("📜 极品历史 IP 库 (刷新不丢)")
            with open(DB_FILE, "r") as f:
                st.code(f.read())
    else:
        st.error("😰 探测全灭，请检查 Secrets 配置或网络。")

st.caption(f"🕒 下次巡检时间: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
