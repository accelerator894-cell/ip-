import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. 页面配置与 APP 美化 ---
st.set_page_config(page_title="4K 引擎：全能全自动版", page_icon="🏎️", layout="centered")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1.5rem;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 配置安全加载 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except:
    st.error("❌ Secrets 配置丢失，请在 Streamlit 后台重新配置。")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 核心功能整合 ---

def check_cf_status():
    """诊断 API 健康度"""
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
    """【找回功能】自动搜集全球 IP"""
    sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
    ips = set()
    try:
        r = requests.get(sources[0], timeout=5)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        ips.update(found)
    except: pass
    # 随机采样 10 个确保速度
    return random.sample(list(ips), min(len(ips), 10))

def test_ip_performance(ip, label):
    """【找回功能】延迟 + 解锁测试"""
    data = {"ip": ip, "type": label, "lat": 9999, "nf": "❓"}
    try:
        start = time.time()
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        data["lat"] = int((time.time() - start) * 1000)
        
        # 仅对低延迟 IP 进行解锁测试
        if data["lat"] < 200:
            nf = requests.get(f"http://{ip}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.2)
            data["nf"] = "✅" if nf.status_code in [200, 301, 302] else "❌"
    except: pass
    return data

def sync_dns(new_ip):
    """【全自动功能】自动修改 DNS 记录"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        # 获取记录 ID
        recs = requests.get(url, headers=headers, params={"name": CF_CONFIG['record_name']}).json()
        if recs["success"] and recs["result"]:
            rid = recs["result"][0]["id"]
            if recs["result"][0]["content"] == new_ip:
                return "✅ 已是最新"
            # 更新
            res = requests.put(f"{url}/{rid}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            }).json()
            return "🚀 同步成功" if res["success"] else "❌ 同步失败"
        return "❌ 未找到 A 记录"
    except: return "⚠️ API 异常"

# --- 4. 自动化主流程 ---

st.title("🚀 4K 引擎：终极控制台")

with st.sidebar:
    st.header("⚙️ 系统监控")
    health = check_cf_status()
    st.metric("API 健康度", health)
    
    mode = st.radio("优选偏好", ("⚡ 速度优先", "🎬 解锁优先"))
    if st.button("🗑️ 清空历史记录"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

with st.spinner("🕵️ 全球巡检中，正在整合所有功能..."):
    results = []
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    
    # 1. 搜集并测试
    dynamic_ips = fetch_global_ips()
    for ip in base_ips: results.append(test_ip_performance(ip, "🏠 基础"))
    for ip in dynamic_ips: results.append(test_ip_performance(ip, "🌍 搜集"))
    
    # 2. 筛选冠军
    active = [r for r in results if r["lat"] < 9999]
    if active:
        active.sort(key=lambda x: x['lat'])
        winner = active[0]
        
        # 3. 结果展示与自动同步
        st.success(f"🎯 本轮冠军：{winner['ip']} | 延迟：{winner['lat']}ms")
        sync_status = sync_dns(winner['ip'])
        st.info(f"🛰️ 云端同步状态：{sync_status}")

        # 4. 【看板回归】
        st.subheader("📊 实时节点分类看板")
        st.dataframe(results, use_container_width=True)
        
        # 5. 【历史库回归】
        with open(DB_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | {winner['lat']}ms\n")
        
        if os.path.exists(DB_FILE):
            st.divider()
            st.subheader("📜 极品历史 IP 库")
            with open(DB_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
                st.code("".join(lines[-15:])) # 显示最近15条
    else:
        st.error("😰 探测全灭，请检查网络或 Secrets。")

st.caption(f"🕒 下次自动巡检预定: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
