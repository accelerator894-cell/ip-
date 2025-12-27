import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. 页面设置 ---
st.set_page_config(page_title="4K 引擎：终极全能版", page_icon="🚀", layout="centered")

# --- 2. 核心配置 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except:
    st.error("❌ 配置缺失：请在 Secrets 中配置密钥")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 功能函数整合 ---

def check_api():
    """验证令牌有效性"""
    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        r = requests.get(url, headers=headers, timeout=5).json()
        return "🟢 正常" if r.get("success") else f"🔴 {r.get('errors')[0]['message']}"
    except: return "🟡 连接延迟"

def fetch_ips():
    """找回功能：全球搜集 IP"""
    sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
    ips = set()
    try:
        r = requests.get(sources[0], timeout=5)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        ips.update(found)
    except: pass
    return random.sample(list(ips), min(len(ips), 10))

def test_performance(ip, label):
    """找回功能：延迟 + 解锁测试"""
    data = {"ip": ip, "type": label, "lat": 9999, "nf": "❓"}
    try:
        start = time.time()
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=0.8)
        data["lat"] = int((time.time() - start) * 1000)
        # 低延迟 IP 才测解锁
        if data["lat"] < 100:
            nf = requests.get(f"http://{ip}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.0)
            data["nf"] = "✅" if nf.status_code in [200, 301, 302] else "❌"
    except: pass
    return data

def sync_dns(new_ip):
    """自动同步 DNS"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        recs = requests.get(url, headers=headers, params={"name": CF_CONFIG['record_name']}).json()
        if recs["success"] and recs["result"]:
            rid = recs["result"][0]["id"]
            if recs["result"][0]["content"] == new_ip: return "✅ 已是最新"
            res = requests.put(f"{url}/{rid}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            }).json()
            return "🚀 同步成功" if res["success"] else "❌ 同步失败"
        return "❌ 未找到记录 (请检查 DNS 预设)"
    except: return "⚠️ API 异常"

# --- 4. 自动化主流程 ---

st.title("🚀 4K 引擎：终极全能版")

with st.sidebar:
    st.header("⚙️ 系统监控")
    status = check_api()
    st.metric("API 健康度", status)
    mode = st.radio("优选偏好", ("⚡ 速度优先", "🎬 解锁优先"))
    if st.button("🗑️ 清空历史库"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

with st.spinner("🕵️ 全球巡检中，正在整合所有功能..."):
    results = []
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    
    # 获取搜集 IP 并测试
    dynamic_ips = fetch_ips()
    for ip in base_ips: results.append(test_performance(ip, "🏠 基础"))
    for ip in dynamic_ips: results.append(test_performance(ip, "🌍 搜集"))
    
    active = [r for r in results if r["lat"] < 9999]
    if active:
        active.sort(key=lambda x: x['lat'])
        winner = active[0]
        
        # 冠军展示与同步
        st.success(f"🎯 本轮冠军：{winner['ip']} | 延迟：{winner['lat']}ms")
        sync_status = sync_dns(winner['ip'])
        st.info(f"🛰️ 云端同步状态：{sync_status}")

        # 找回功能：实时看板
        st.subheader("📊 全球节点分类看板")
        st.dataframe(results, use_container_width=True)
        
        # 记录历史
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now()} | {winner['ip']} | {winner['lat']}ms\n")
            
        # 找回功能：历史数据库展示
        if os.path.exists(DB_FILE):
            st.divider()
            st.subheader("📜 极品历史 IP 库")
            with open(DB_FILE, "r") as f:
                st.code(f.read())
    else:
        st.error("😰 探测失败，请检查配置")

st.caption(f"🕒 下次自动巡检预定: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
