import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. 页面设置与视觉美化 ---
st.set_page_config(page_title="4K 引擎：终极控制台", page_icon="🏎️", layout="centered")

# 隐藏 Streamlit 官方冗余元素，打造 APP 体验
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1.5rem;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 配置安全加载 ---
# 自动优先读取 Secrets 面板，若为空则使用你发给我的最新 API 数据
try:
    CF_CONFIG = {
        "api_token": st.secrets.get("api_token", "DkZQIM9zcq6G47z9Rh9HOuaGqviwa1rYXnImobbr").strip(),
        "zone_id": st.secrets.get("zone_id", "7aa1c1ddfd9df2690a969d9f977f82ae").strip(),
        "record_name": st.secrets.get("record_name", "speed.milet.qzz.io").strip(),
    }
except:
    st.error("❌ Secrets 配置读取异常，请检查后台设置")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 核心功能函数 ---

def check_cf_status():
    """实时诊断 API 健康度"""
    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        r = requests.get(url, headers=headers, timeout=5).json()
        if r.get("success"):
            return "🟢 正常"
        err = r.get("errors", [{}])[0].get("message", "令牌无效")
        return f"🔴 {err}"
    except: return "🟡 连接延迟"

def fetch_global_ips():
    """找回功能：自动搜集全球 IP"""
    sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
    ips = set()
    try:
        r = requests.get(sources[0], timeout=5)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        ips.update(found)
    except: pass
    return random.sample(list(ips), min(len(ips), 10))

def test_performance(ip, label):
    """找回功能：延迟 + 解锁深度测试"""
    data = {"ip": ip, "type": label, "lat": 9999, "nf": "❓"}
    try:
        start = time.time()
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        data["lat"] = int((time.time() - start) * 1000)
        
        if data["lat"] < 200:
            nf = requests.get(f"http://{ip}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.2)
            data["nf"] = "✅" if nf.status_code in [200, 301, 302] else "❌"
    except: pass
    return data

def sync_dns(new_ip):
    """全自动功能：同步优选 IP 到云端记录"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        # 1. 检索对应的 A 记录
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        recs = requests.get(url, headers=headers, params=params).json()
        if recs["success"] and recs["result"]:
            record = recs["result"][0]
            if record["content"] == new_ip:
                return "✅ 解析已是最新"
            # 2. 发现 IP 变动，执行更新
            res = requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            }).json()
            return "🚀 同步成功" if res["success"] else "❌ 同步失败"
        return "❌ 未找到 A 记录 (请核对 record_name)"
    except: return "⚠️ API 通信异常"

# --- 4. 自动化主流程 ---

st.title("🚀 4K 引擎：终极控制台")

with st.sidebar:
    st.header("⚙️ 系统状态")
    health = check_cf_status()
    st.metric("API 健康度", health)
    mode = st.radio("优选偏好", ("⚡ 速度优先", "🎬 解锁优先"))
    if st.button("🗑️ 清理历史记录"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

with st.spinner("🕵️ 全球巡检中，正在为您挑选最优路径..."):
    results = []
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    
    dynamic_ips = fetch_global_ips()
    for ip in base_ips: results.append(test_performance(ip, "🏠 基础"))
    for ip in dynamic_ips: results.append(test_performance(ip, "🌍 搜集"))
    
    active = [r for r in results if r["lat"] < 9999]
    if active:
        active.sort(key=lambda x: x['lat'])
        winner = active[0]
        
        # 结果看板
        st.success(f"🎯 本轮优选：{winner['ip']} | 延迟：{winner['lat']}ms")
        sync_status = sync_dns(winner['ip'])
        st.info(f"🛰️ 云端同步状态：{sync_status}")

        # 找回功能：分类看板
        st.subheader("📊 实时节点分类看板")
        st.dataframe(results, use_container_width=True)
        
        # 找回功能：持久化历史存盘
        log_entry = f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | {winner['lat']}ms\n"
        with open(DB_FILE, "a", encoding="utf-8") as f: f.write(log_entry)
        
        if os.path.exists(DB_FILE):
            st.divider()
            st.subheader("📜 极品历史 IP 库")
            with open(DB_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
                st.code("".join(lines[-15:])) 
    else:
        st.error("😰 探测异常，请检查配置或网络。")

st.caption(f"🕒 下次自动巡检预定: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
