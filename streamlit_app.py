import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. 配置加载 (建议在 Streamlit 后台 Secrets 设置) ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"], # 这里填入你刚才发的令牌
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except Exception:
    st.error("❌ 配置缺失：请在 Secrets 面板配置 api_token, zone_id 和 record_name")
    st.stop()

DB_FILE = "best_ip_history.txt" # 持久化存盘文件

# --- 2. 核心监控与功能函数 ---

def check_cf_status():
    """实时监控 API 健康度"""
    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        r = requests.get(url, headers=headers, timeout=5).json()
        return "🟢 正常" if r.get("success") else "🔴 受限"
    except: return "🟡 延迟"

def fetch_and_clean_ips():
    """搜集全球 IP 并清理旧数据"""
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
    return random.sample(list(ips), min(len(ips), 15))

def quick_ping(ip, label):
    """阶梯质检第一步：快速延迟探测"""
    data = {"ip": ip, "type": label, "lat": 9999, "score": 0, "nf": "❓"}
    try:
        start = time.time()
        r = requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        if r.status_code < 500:
            data["lat"] = int((time.time() - start) * 1000)
    except: pass
    return data

def deep_test(data):
    """阶梯质检第二步：深度解锁探测"""
    try:
        r = requests.get(f"http://{data['ip']}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.2)
        if r.status_code in [200, 301, 302]: 
            data["nf"] = "✅"; data["score"] = 1
        else: data["nf"] = "❌"
    except: data["nf"] = "❌"
    return data

def save_to_disk(winner):
    """持久化存盘逻辑：IP 变动才写入，保护性能"""
    try:
        log = f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | {winner['lat']}ms | {winner['type']}\n"
        lines = []
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r") as f: lines = f.readlines()
        lines.insert(0, log)
        with open(DB_FILE, "w") as f: f.writelines(lines[:50]) # 保留最近50条
    except: pass

# --- 3. UI 界面布局 ---

st.set_page_config(page_title="终极优选控制台", page_icon="🛡️")
st.title("🛡️ 4K 引擎：终极整合版")

# 侧边栏监控
with st.sidebar:
    st.header("🔐 云端健康")
    st.metric("API 状态", check_cf_status())
    mode = st.sidebar.radio("优选模式", ("⚡ 速度优先", "🎬 解锁优先"))
    if st.button("🗑️ 清空历史记录"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

# --- 4. 自动化执行流程 ---

with st.spinner("🕵️ 全球巡检中，正在为您挑选极品节点..."):
    # 获取搜集IP
    dynamic_ips = fetch_and_clean_ips()
    
    # 基础IP来自你提供的 15 个稳定地址
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1", "173.245.58.1", "172.64.36.5", "162.159.46.10", "188.114.97.1", "104.16.160.1", "104.17.160.1", "104.18.160.1", "104.19.160.1", "104.20.160.1", "104.21.160.1", "104.22.160.1"]
    
    # 阶梯质检
    results = []
    for ip in base_ips: results.append(quick_ping(ip, "🏠 基础"))
    for ip in dynamic_ips: results.append(quick_ping(ip, "🌍 搜集"))
    
    active = [r for r in results if r["lat"] < 9999]
    if active:
        active.sort(key=lambda x: x['lat'])
        top_candidates = active[:6] # 只取前6名进行解锁测试，确保加载飞快
        for c in top_candidates: deep_test(c)
        
        # 模式排序
        if "速度" in mode:
            top_candidates.sort(key=lambda x: x['lat'])
        else:
            top_candidates.sort(key=lambda x: (-x['score'], x['lat']))
        
        winner = top_candidates[0]
        
        # 保存与显示
        if 'last_ip' not in st.session_state or st.session_state.last_ip != winner['ip']:
            save_to_disk(winner)
            st.session_state.last_ip = winner['ip']
        
        st.success(f"🎯 本轮冠军: {winner['ip']} ({winner['type']})")
        st.metric("最低延迟", f"{winner['lat']}ms", delta=f"解锁: {winner['nf']}")

        # 分类看板
        with st.expander("📊 查看详细 IP 性能看板"):
            st.table(results)
            
        # 历史记录 (持久化)
        if os.path.exists(DB_FILE):
            st.divider()
            st.subheader("📜 历史极品 IP 库 (刷新不丢失)")
            with open(DB_FILE, "r") as f:
                st.code(f.read())
    else:
        st.error("所有节点探测失败，请检查配置或令牌权限。")

st.caption(f"🕒 下次自动巡检时间: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
