import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. 极致 APP 视觉优化 ---
st.set_page_config(page_title="Cloudflare 自动优选同步", page_icon="⚡", layout="centered")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1.5rem;}
    .stMetric {background-color: #f0f2f6; padding: 10px; border-radius: 10px;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心配置加载 (使用你测试成功的 Secrets) ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except:
    st.error("❌ 配置读取失败，请检查 Streamlit 后台 Secrets 设置")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 核心功能函数 ---

def sync_dns(new_ip):
    """同步优选 IP 到 Cloudflare"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        # 1. 精确查找 A 记录
        recs = requests.get(url, headers=headers, params={"name": CF_CONFIG['record_name'], "type": "A"}).json()
        if recs["success"] and recs["result"]:
            rid = recs["result"][0]["id"]
            if recs["result"][0]["content"] == new_ip:
                return "✅ 解析已是最新"
            # 2. 执行云端同步更新
            res = requests.put(f"{url}/{rid}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            }).json()
            return "🚀 同步成功" if res["success"] else "❌ 同步失败"
        return "❌ 未找到记录 (请检查 record_name)"
    except: return "⚠️ API 通信异常"

def fetch_global_ips():
    """找回功能：自动搜集全球活跃 IP 源"""
    sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
    ips = set()
    try:
        r = requests.get(sources[0], timeout=5)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        ips.update(found)
    except: pass
    return random.sample(list(ips), min(len(ips), 10))

def test_performance(ip, label):
    """找回功能：延迟测速 + 解锁深度质检"""
    data = {"ip": ip, "type": label, "lat": 9999, "nf": "❓"}
    try:
        start = time.time()
        # 使用 record_name 作为 Host 探测，确保真实性
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        data["lat"] = int((time.time() - start) * 1000)
        # 低延迟节点进行 Netflix 解锁测试
        if data["lat"] < 200:
            nf = requests.get(f"http://{ip}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.2)
            data["nf"] = "✅" if nf.status_code in [200, 301, 302] else "❌"
    except: pass
    return data

# --- 4. 自动化主流程 ---

st.title("⚡ Cloudflare 自动优选同步")

with st.sidebar:
    st.header("⚙️ 系统监控")
    # API 健康检测
    test_url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    r = requests.get(test_url, headers={"Authorization": f"Bearer {CF_CONFIG['api_token']}"}).json()
    st.metric("API 健康度", "🟢 正常" if r.get("success") else "🔴 受限")
    
    st.divider()
    if st.button("🗑️ 清空历史记录"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

with st.spinner("🕵️ 正在执行全球巡检并同步解析..."):
    results = []
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    
    # 搜集并测试
    dynamic_ips = fetch_global_ips()
    for ip in base_ips: results.append(test_performance(ip, "🏠 基础"))
    for ip in dynamic_ips: results.append(test_performance(ip, "🌍 搜集"))
    
    active = [r for r in results if r["lat"] < 9999]
    if active:
        active.sort(key=lambda x: x['lat'])
        winner = active[0]
        
        # 1. 展示当前最优
        st.success(f"找到最快 IP: {winner['ip']} (延迟: {winner['lat']}ms)")
        
        # 2. 自动同步 DNS
        sync_status = sync_dns(winner['ip'])
        if "成功" in sync_status or "最新" in sync_status:
            st.info(f"✅ 解析同步成功！已指向 {winner['ip']}")
        else:
            st.error(f"❌ 同步状态: {sync_status}")

        # 3. 找回功能：分类看板
        st.subheader("📊 实时节点分类看板")
        st.dataframe(results, use_container_width=True)
        
        # 4. 找回功能：历史存盘
        with open(DB_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | {winner['lat']}ms\n")
        
        if os.path.exists(DB_FILE):
            st.divider()
            st.subheader("📜 极品历史 IP 库")
            with open(DB_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
                st.code("".join(lines[-15:]))
    else:
        st.error("😰 探测异常，请检查配置或网络环境。")

st.caption(f"🕒 更新时间: {datetime.now().strftime('%H:%M:%S')}")

# 每 10 分钟自动巡检一次
time.sleep(600)
st.rerun()
