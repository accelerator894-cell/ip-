import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. 配置加载 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except Exception:
    st.error("❌ 配置缺失：请在 Secrets 中配置 api_token, zone_id 和 record_name")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 2. 核心功能函数 ---

def check_cf_status():
    """检测 API 健康度"""
    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        r = requests.get(url, headers=headers, timeout=5).json()
        return "🟢 正常" if r.get("success") else "🔴 受限"
    except: return "🟡 延迟"

def fetch_and_clean_ips():
    """搜集全球 IP"""
    sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
    ips = set()
    for url in sources:
        try:
            r = requests.get(url, timeout=5)
            found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
            ips.update(found)
        except: continue
    return random.sample(list(ips), min(len(ips), 10))

def quick_ping(ip, label):
    """阶梯质检第一阶段"""
    data = {"ip": ip, "type": label, "lat": 9999, "nf": "❓", "score": 0}
    try:
        start = time.time()
        r = requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        if r.status_code < 500:
            data["lat"] = int((time.time() - start) * 1000)
    except: pass
    return data

def save_winner(winner):
    """持久化存盘"""
    try:
        log = f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | {winner['lat']}ms\n"
        with open(DB_FILE, "a") as f: f.write(log)
    except: pass

# --- 3. 页面渲染 ---

st.set_page_config(page_title="4K 终极版", page_icon="🛡️")
st.title("🛡️ 4K 引擎：终极整合版")

with st.sidebar:
    st.header("🔐 云端监控")
    health = check_cf_status()
    st.metric("API 健康度", health)
    if st.button("🗑️ 清空历史"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

# --- 4. 自动化流程 ---

with st.spinner("🕵️ 全球巡检中..."):
    # 初始化 results 避免 NameError
    results = []
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1", "173.245.58.1"]
    
    # 快速测速
    dynamic_ips = fetch_and_clean_ips()
    for ip in base_ips: results.append(quick_ping(ip, "🏠 基础"))
    for ip in dynamic_ips: results.append(quick_ping(ip, "🌍 搜集"))
    
    active = [r for r in results if r["lat"] < 9999]
    if active:
        active.sort(key=lambda x: x['lat'])
        winner = active[0]
        
        # 保存记录
        if 'last_winner' not in st.session_state or st.session_state.last_winner != winner['ip']:
            save_winner(winner)
            st.session_state.last_winner = winner['ip']

        # 显示冠军
        st.success(f"🎯 本轮冠军: {winner['ip']}")
        st.metric("延迟", f"{winner['lat']}ms")

        # 数据看板
        st.subheader("📊 全球节点分类看板")
        st.dataframe(results, use_container_width=True)
        
        # 历史展示
        if os.path.exists(DB_FILE):
            st.divider()
            st.subheader("📜 历史存盘")
            with open(DB_FILE, "r") as f:
                st.code(f.read())
    else:
        st.error("❌ 所有节点探测失败，请检查密钥是否正确。")

time.sleep(600)
st.rerun()
