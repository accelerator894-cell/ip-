import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. APP 视觉与 PWA 美化 ---
st.set_page_config(page_title="4K 引擎：全自动控制台", page_icon="🚀", layout="centered")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1.5rem;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 配置加载 ---
# 建议通过 Secrets 管理，但这里我已为你做了容错处理
try:
    CF_CONFIG = {
        "api_token": st.secrets.get("api_token", "DkZQIM9zcq6G47z9Rh9HOuaGqviwa1rYXnImobbr").strip(),
        "zone_id": st.secrets.get("zone_id", "").strip(),
        "record_name": st.secrets.get("record_name", "milet.qzz.io").strip(),
    }
except:
    st.error("❌ Secrets 配置丢失，请在 Streamlit 后台设置。")
    st.stop()

# --- 3. 核心功能：API 诊断与 DNS 同步 ---

def check_cf_health():
    """实时诊断 Token 有效性"""
    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        r = requests.get(url, headers=headers, timeout=5).json()
        if r.get("success"):
            return "🟢 正常", "Token 已就绪"
        return "🔴 受限", r.get("errors", [{}])[0].get("message", "权限不足")
    except:
        return "🟡 延迟", "云端连接异常"

def sync_to_cloudflare(new_ip):
    """【新增】自动修改 DNS 解析记录"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        # 1. 查找现有的 A 记录
        records = requests.get(url, headers=headers, params={"name": CF_CONFIG['record_name'], "type": "A"}).json()
        if not records.get("success") or not records.get("result"):
            return "❌ 未找到记录 (请检查 Zone ID)"
        
        record = records["result"][0]
        if record["content"] == new_ip:
            return "✅ 解析已是最新"
        
        # 2. 执行更新
        update_url = f"{url}/{record['id']}"
        payload = {"type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False}
        res = requests.put(update_url, headers=headers, json=payload).json()
        
        return "🚀 解析同步成功" if res.get("success") else "❌ 修改失败"
    except Exception as e:
        return f"⚠️ 同步异常"

# --- 4. 自动化主流程 ---

st.title("🚀 4K 引擎：全自动版")

with st.sidebar:
    st.header("⚙️ 系统状态")
    status, msg = check_cf_health()
    st.metric("API 健康度", status)
    if "🔴" in status: st.error(msg)
    else: st.success(msg)
    
    st.divider()
    if st.button("🔄 立即重新巡检"):
        st.rerun()

with st.spinner("🕵️ 全球巡检中，正在为您挑选最优路径..."):
    results = []
    # 基础高优池
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    
    # 执行探测 (此处简化为快测逻辑以保速度)
    for ip in base_ips:
        try:
            start = time.time()
            r = requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
            lat = int((time.time() - start) * 1000)
            results.append({"ip": ip, "lat": lat, "type": "🏠 基础"})
        except:
            continue
    
    if results:
        results.sort(key=lambda x: x['lat'])
        winner = results[0]
        
        # UI 展示
        st.success(f"🎯 本轮冠军：{winner['ip']} | 延迟：{winner['lat']}ms")
        
        # 自动同步 DNS
        with st.status("☁️ 正在同步到云端...") as s:
            sync_status = sync_to_cloudflare(winner['ip'])
            s.update(label=sync_status, state="complete")
        
        st.subheader("📊 节点分类看板")
        st.table(results)
    else:
        st.error("😰 探测失败，请检查 API 配置或网络环境。")

st.caption(f"🕒 下次自动更新预定: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
