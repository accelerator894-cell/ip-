import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. 纯净 APP 视觉美化 ---
st.set_page_config(page_title="Cloudflare 自动优选同步", page_icon="⚡", layout="centered")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1.5rem;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 严格配置加载 ---
# 不再在代码里写默认值，强制从 Secrets 读取
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except Exception as e:
    st.error(f"❌ 配置缺失或格式错误！请检查 Secrets 面板。报错信息: {e}")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 核心功能函数 ---

def sync_dns(new_ip):
    """同步冠军 IP 到 Cloudflare"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        # 1. 搜索 A 记录
        recs = requests.get(url, headers=headers, params={"name": CF_CONFIG['record_name'], "type": "A"}).json()
        if recs.get("success") and recs.get("result"):
            rid = recs["result"][0]["id"]
            if recs["result"][0]["content"] == new_ip:
                return "✅ 解析已是最新"
            # 2. 更新云端
            res = requests.put(f"{url}/{rid}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            }).json()
            return "🚀 同步成功" if res.get("success") else "❌ 同步失败"
        return f"❌ 未找到记录: {CF_CONFIG['record_name']}"
    except: return "⚠️ API 通信异常"

def fetch_ips():
    """找回功能：全球搜集源"""
    sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
    ips = set()
    try:
        r = requests.get(sources[0], timeout=5)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        ips.update(found)
    except: pass
    return random.sample(list(ips), min(len(ips), 10))

def test_ip(ip, label):
    """找回功能：测速 + 解锁"""
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

# --- 4. 自动化主流程 ---

st.title("⚡ Cloudflare 自动优选同步")

with st.sidebar:
    st.header("⚙️ 系统监控")
    test_url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    r = requests.get(test_url, headers={"Authorization": f"Bearer {CF_CONFIG['api_token']}"}).json()
    st.metric("API 健康度", "🟢 正常" if r.get("success") else "🔴 受限")

with st.spinner("🕵️ 全球巡检并同步中..."):
    results = []
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    
    # 搜集与探测
    extra_ips = fetch_ips()
    for ip in base_ips: results.append(test_ip(ip, "🏠 基础"))
    for ip in extra_ips: results.append(test_ip(ip, "🌍 搜集"))
    
    active = [r for r in results if r["lat"] < 9999]
    if active:
        active.sort(key=lambda x: x['lat'])
        winner = active[0]
        
        # 展示冠军
        st.success(f"找到最快 IP: {winner['ip']} (延迟: {winner['lat']}ms)")
        
        # 执行同步
        sync_status = sync_dns(winner['ip'])
        if "成功" in sync_status or "最新" in sync_status:
            st.info(f"✅ 解析同步成功！已指向 {winner['ip']}")
        else:
            st.error(f"❌ 同步状态: {sync_status}")

        # 找回看板
        st.subheader("📊 实时节点看板")
        st.dataframe(results, use_container_width=True)
        
        # 找回历史库
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | {winner['lat']}ms\n")
        
        if os.path.exists(DB_FILE):
            st.divider()
            st.subheader("📜 极品历史 IP 库")
            with open(DB_FILE, "r") as f:
                st.code("".join(f.readlines()[-15:]))
    else:
        st.error("😰 探测异常，请检查 Secrets 或网络。")

st.caption(f"🕒 更新时间: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
