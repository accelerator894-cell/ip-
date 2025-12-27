import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. 页面设置与 APP 美化 ---
st.set_page_config(page_title="4K 引擎：全能控制台", page_icon="🏎️", layout="centered")

# 隐藏 Streamlit 官方页眉页脚，提供纯净的 APP 体验
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1.5rem;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 配置安全加载 ---
# 代码会自动优先读取 Secrets 面板中的设置，若面板为空则使用默认值
try:
    CF_CONFIG = {
        "api_token": st.secrets.get("api_token", "DkZQIM9zcq6G47z9Rh9HOuaGqviwa1rYXnImobbr").strip(),
        "zone_id": st.secrets.get("zone_id", "7aa1c1ddfd9df2690a969d9f977f82ae").strip(),
        "record_name": st.secrets.get("record_name", "speed.milet.qzz.io").strip(),
    }
except:
    st.error("❌ 配置文件读取失败，请检查 Streamlit 后台 Secrets 设置")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 核心功能函数整合 ---

def check_cf_status():
    """诊断 API 健康度与 Token 有效性"""
    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        r = requests.get(url, headers=headers, timeout=5).json()
        if r.get("success"):
            return "🟢 正常"
        # 提取 Cloudflare 返回的具体错误原因
        err = r.get("errors", [{}])[0].get("message", "令牌无效")
        return f"🔴 {err}"
    except: return "🟡 连接延迟"

def fetch_global_ips():
    """【功能回归】自动从全球源搜集 IP"""
    sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
    ips = set()
    try:
        r = requests.get(sources[0], timeout=5)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        ips.update(found)
    except: pass
    return random.sample(list(ips), min(len(ips), 10))

def test_performance(ip, label):
    """【功能回归】延迟测速 + 流媒体解锁深度质检"""
    data = {"ip": ip, "type": label, "lat": 9999, "nf": "❓"}
    try:
        start = time.time()
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        data["lat"] = int((time.time() - start) * 1000)
        
        # 仅对低延迟节点（<200ms）进行流媒体测试，节省加载时间
        if data["lat"] < 200:
            nf = requests.get(f"http://{ip}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.2)
            data["nf"] = "✅" if nf.status_code in [200, 301, 302] else "❌"
    except: pass
    return data

def sync_dns(new_ip):
    """【全自动核心】同步冠军 IP 到 Cloudflare 解析"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        # 1. 精确检索对应的 A 记录
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        recs = requests.get(url, headers=headers, params=params).json()
        if recs["success"] and recs["result"]:
            record = recs["result"][0]
            if record["content"] == new_ip:
                return "✅ 解析已是最新"
            # 2. 发现变化，执行云端同步
            res = requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            }).json()
            return "🚀 同步成功" if res["success"] else f"❌ 同8步失败: {res['errors'][0]['message']}"
        return "❌ 未找到记录 (请检查 record_name)"
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

with st.spinner("🕵️ 全球巡检中，正在整合所有功能..."):
    results = []
    # 基础高优池
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    
    # 搜集外部 IP
    dynamic_ips = fetch_global_ips()
    for ip in base_ips: results.append(test_performance(ip, "🏠 基础"))
    for ip in dynamic_ips: results.append(test_performance(ip, "🌍 搜集"))
    
    active = [r for r in results if r["lat"] < 9999]
    if active:
        active.sort(key=lambda x: x['lat'])
        winner = active[0]
        
        # 冠军展示与自动同步
        st.success(f"🎯 本轮冠军：{winner['ip']} | 延迟：{winner['lat']}ms")
        sync_status = sync_dns(winner['ip'])
        st.info(f"🛰️ 云端同步状态：{sync_status}")

        # 【功能回归】实时看板
        st.subheader("📊 实时节点分类看板")
        st.dataframe(results, use_container_width=True)
        
        # 【功能回归】历史存盘记录
        log_entry = f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | {winner['lat']}ms\n"
        with open(DB_FILE, "a", encoding="utf-8") as f: f.write(log_entry)
        
        if os.path.exists(DB_FILE):
            st.divider()
            st.subheader("📜 极品历史 IP 库")
            with open(DB_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
                # 只显示最近的 15 条记录
                st.code("".join(lines[-15:])) 
    else:
        st.error("😰 探测全灭，请检查网络环境。")

st.caption(f"🕒 下次自动巡检预定: {datetime.now().strftime('%H:%M:%S')}")

# 每 10 分钟自动重刷页面，保持解析最新
time.sleep(600)
st.rerun()
