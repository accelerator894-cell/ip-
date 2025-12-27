import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. APP 视觉与页面美化 ---
st.set_page_config(page_title="4K 终极控制台", page_icon="🚀", layout="centered")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1.5rem;}
    .stMetric {background-color: #f0f2f6; padding: 10px; border-radius: 10px;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心配置加载 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except:
    st.error("❌ Secrets 配置丢失，请检查后台配置。")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 重新优化的监控函数 ---

def check_cf_health():
    """深度诊断 API 状态"""
    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        r = requests.get(url, headers=headers, timeout=5).json()
        if r.get("success"):
            return "🟢 正常", "通信良好", r
        else:
            # 提取具体的错误信息
            errors = r.get("errors", [])
            err_msg = errors[0].get("message", "未知权限错误") if errors else "令牌无效"
            return "🔴 受限", f"错误原因: {err_msg}", r
    except Exception as e:
        return "🟡 故障", f"连接超时: {str(e)}", {}

# --- 4. 核心逻辑函数 ---

def fetch_ips():
    sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
    ips = set()
    try:
        r = requests.get(sources[0], timeout=5)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        ips.update(found)
    except: pass
    return random.sample(list(ips), min(len(ips), 12))

def quick_ping(ip, label):
    data = {"ip": ip, "type": label, "lat": 9999, "nf": "❓"}
    try:
        start = time.time()
        r = requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=0.8)
        if r.status_code < 500:
            data["lat"] = int((time.time() - start) * 1000)
    except: pass
    return data

# --- 5. 侧边栏渲染 (优化重点) ---

with st.sidebar:
    st.title("🛡️ 系统守护")
    status, detail, raw_json = check_cf_health()
    
    # 用大指标显示状态
    st.metric("API 运行状态", status)
    
    # 如果受限，用醒目的红色文字提醒
    if "🔴" in status:
        st.error(detail)
    else:
        st.success(detail)
    
    # 新增：调试折叠框，点开看原始报错
    with st.expander("🔍 API 诊断原始数据"):
        st.json(raw_json)

    st.divider()
    mode = st.radio("优选偏好", ("⚡ 速度优先", "🎬 解锁优先"))
    if st.button("🗑️ 清理本地缓存"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

# --- 6. 主流程执行 ---

st.title("🚀 4K 引擎：全能优选控制台")

with st.spinner("🕵️ 正在进行全球 IP 巡检..."):
    results = []
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    
    dynamic_ips = fetch_ips()
    for ip in base_ips: results.append(quick_ping(ip, "🏠 基础"))
    for ip in dynamic_ips: results.append(quick_ping(ip, "🌍 搜集"))
    
    active = [r for r in results if r["lat"] < 9999]
    if active:
        active.sort(key=lambda x: x['lat'])
        winner = active[0]
        
        # 冠军看板
        st.success(f"🎯 本轮优选：{winner['ip']} | 延迟: {winner['lat']}ms")
        
        # 展示详细看板
        st.subheader("📊 实时节点分类看板")
        st.table(results)
    else:
        st.error("😰 探测全灭，请检查网络或 API 配置。")

st.caption(f"🕒 自动刷新时间: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
