import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. APP 视觉与页面设置 ---
st.set_page_config(page_title="4K 引擎：全能终极版", page_icon="🏎️", layout="centered")

# APP 化视觉美化：隐藏侧边栏按钮、页脚、顶部标识
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .block-container {padding-top: 1.5rem;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# --- 2. 安全配置加载 (Secrets) ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except Exception:
    st.error("❌ 配置缺失：请在 Streamlit 后台 Secrets 面板配置密钥。")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 核心功能函数 ---

def check_cf_status():
    """监控 API 健康度并返回具体错误信息"""
    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        r = requests.get(url, headers=headers, timeout=5).json()
        if r.get("success"):
            return "🟢 正常"
        else:
            # 这里的 r.get("errors") 会捕获具体的错误原因
            errs = r.get("errors", [])
            msg = errs[0].get("message", "权限不足") if errs else "验证失败"
            return f"🔴 {msg}"
    except Exception as e:
        return f"🟡 连接延迟"

def fetch_global_ips():
    """自动搜集全球 IP"""
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
    # 随机采样 15 个，平衡速度与质量
    return random.sample(list(ips), min(len(ips), 15))

def quick_ping(ip, label):
    """阶梯质检：快速筛选低延迟 IP"""
    data = {"ip": ip, "type": label, "lat": 9999, "nf": "❓", "score": 0}
    try:
        start = time.time()
        # 1.0s 超时快速剪枝
        r = requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        if r.status_code < 500:
            data["lat"] = int((time.time() - start) * 1000)
    except: pass
    return data

def deep_test(data):
    """深度解锁测试（仅限尖子生）"""
    try:
        nf = requests.get(f"http://{data['ip']}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.2)
        data["nf"] = "✅" if nf.status_code in [200, 301, 302] else "❌"
        data["score"] = 1 if data["nf"] == "✅" else 0
    except: data["nf"] = "❌"
    return data

def save_winner(winner):
    """历史记录深度存盘：记录极品 IP"""
    try:
        log = f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | {winner['lat']}ms | {winner['type']}\n"
        lines = []
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r", encoding="utf-8") as f: lines = f.readlines()
        lines.insert(0, log)
        with open(DB_FILE, "w", encoding="utf-8") as f: f.writelines(lines[:50])
    except: pass

# --- 4. 自动化主流程与 UI ---

st.title("🏎️ 4K 引擎：全能控制台")

with st.sidebar:
    st.header("🔐 云端监控")
    health_status = check_cf_status()
    st.metric("API 健康度", health_status)
    mode = st.radio("优选模式", ("⚡ 速度优先", "🎬 解锁优先"))
    if st.button("🗑️ 清空历史存盘"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

with st.spinner("🕵️ 全球巡检中，正在优化您的网络..."):
    # 1. 初始化结果集
    results = [] 
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1", "173.245.58.1", "172.64.36.5", "162.159.46.10", "188.114.97.1", "104.16.160.1", "104.17.160.1", "104.18.160.1", "104.19.160.1", "104.20.160.1", "104.21.160.1", "104.22.160.1"]
    
    # 2. 搜集并执行快速快测
    dynamic_ips = fetch_global_ips()
    for ip in base_ips: results.append(quick_ping(ip, "🏠 基础"))
    for ip in dynamic_ips: results.append(quick_ping(ip, "🌍 搜集"))
    
    # 3. 筛选通畅节点
    active = [r for r in results if r["lat"] < 9999]
    if active:
        # 阶梯优化：只选延迟前 6 名测解锁
        active.sort(key=lambda x: x['lat'])
        top_6 = active[:6]
        for q in top_6: deep_test(q)
        
        # 4. 根据模式决定本轮冠军
        if "速度" in mode:
            top_6.sort(key=lambda x: x['lat'])
        else:
            top_6.sort(key=lambda x: (-x['score'], x['lat']))
        
        winner = top_6[0]
        
        # 5. 持久化存盘检查
        if 'last_winner_ip' not in st.session_state or st.session_state.last_winner_ip != winner['ip']:
            save_winner(winner)
            st.session_state.last_winner_ip = winner['ip']

        # 6. UI 面板展示
        st.success(f"🎯 本轮优选：{winner['ip']} ({winner['type']})")
        col1, col2, col3 = st.columns(3)
        col1.metric("延迟", f"{winner['lat']}ms")
        col2.metric("流媒体分", winner['score'])
        col3.write(f"📺 Netflix: {winner['nf']}")

        # 7. 全球看板展示
        st.subheader("📊 全球节点分类看板")
        st.dataframe(results, use_container_width=True)
        
        # 8. 历史存盘展示
        if os.path.exists(DB_FILE):
            st.divider()
            st.subheader("📜 极品历史 IP 库 (刷新不丢)")
            with open(DB_FILE, "r", encoding="utf-8") as f:
                st.code(f.read())
    else:
        st.error("😰 探测异常。请检查 Secrets 配置或 API 健康度提示。")

st.caption(f"🕒 下次自动巡检预定时间: {datetime.now().strftime('%H:%M:%S')}")

# 10 分钟自动重刷
time.sleep(600)
st.rerun()
