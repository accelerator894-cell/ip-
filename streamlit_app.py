import streamlit as st
import requests
import time
from datetime import datetime

# --- 1. 配置加载 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except Exception:
    st.error("❌ 错误：未检测到 Secrets 配置")
    st.stop()

# 优选 IP 池
IP_LIST = [
    "108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1", 
    "173.245.58.1", "172.64.36.5", "162.159.46.10", "188.114.97.1"
]

# --- 2. 功能函数 ---

def check_streaming(ip):
    """流媒体解锁探测"""
    status = {"Netflix": "❌", "YouTube": "❌"}
    headers = {"User-Agent": "Mozilla/5.0"}
    # Netflix
    try:
        r = requests.get(f"http://{ip}/title/80018499", headers={**headers, "Host": "www.netflix.com"}, timeout=2.0)
        if r.status_code in [200, 301, 302]: status["Netflix"] = "✅"
    except: pass
    # YouTube
    try:
        r = requests.get(f"http://{ip}/premium", headers={**headers, "Host": "www.youtube.com"}, timeout=2.0)
        if r.status_code == 200: status["YouTube"] = "✅"
    except: pass
    return status

def check_ip_quality(ip):
    """多维质检"""
    quality = {"ip": ip, "lat": 9999, "loss": 100, "stream": {}}
    latencies = []
    success_count = 0
    for _ in range(3):
        try:
            start = time.time()
            resp = requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.5)
            if resp.status_code < 500:
                latencies.append(int((time.time() - start) * 1000))
                success_count += 1
        except: continue
    if success_count > 0:
        quality["lat"] = sum(latencies) / len(latencies)
        quality["loss"] = int(((3 - success_count) / 3) * 100)
        quality["stream"] = check_streaming(ip)
    return quality

def update_dns(new_ip):
    """同步 DNS"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}", "Content-Type": "application/json"}
    try:
        r = requests.get(f"{url}?name={CF_CONFIG['record_name']}", headers=headers, timeout=10).json()
        if r.get("success") and r.get("result"):
            record = r["result"][0]
            if record["content"] == new_ip: return f"✅ 已是最佳 IP", False
            u = requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            }, timeout=10).json()
            return f"🚀 已切换至: {new_ip}", True
    except: pass
    return "⚠️ 同步失败", False

# --- 3. 界面渲染 ---

st.set_page_config(page_title="4K 优选控制台", page_icon="🔘")
st.title("🔘 4K 自动优选引擎")

# --- 核心切换按钮 (侧边栏) ---
st.sidebar.header("⚙️ 引擎设置")
mode = st.sidebar.radio(
    "选择优选模式:",
    ("⚡ 速度优先 (低延迟/低丢包)", "🎬 解锁优先 (流媒体通过数)")
)
st.sidebar.write(f"当前模式: **{mode}**")

with st.spinner("🔍 正在按照您的偏好筛选 IP..."):
    results = []
    for ip in IP_LIST:
        q = check_ip_quality(ip)
        if q["lat"] < 9999: results.append(q)

    if results:
        # 根据切换按钮调整排序逻辑
        if "速度优先" in mode:
            # 权重：丢包率 > 延迟
            results.sort(key=lambda x: (x['loss'], x['lat']))
        else:
            # 权重：流媒体 ✅ 数量(降序) > 丢包率 > 延迟
            def stream_count(x): return list(x['stream'].values()).count("✅")
            results.sort(key=lambda x: (-stream_count(x), x['loss'], x['lat']))
        
        winner = results[0]
        
        # UI 展示
        st.subheader(f"🎯 选定 IP: {winner['ip']}")
        c1, c2 = st.columns(2)
        c1.metric("平均延迟", f"{int(winner['lat'])}ms")
        c2.metric("丢包率", f"{winner['loss']}%")
        
        st.write(f"📺 Netflix: {winner['stream']['Netflix']} | 🎥 YouTube: {winner['stream']['YouTube']}")
        
        # 自动同步
        msg, updated = update_dns(winner['ip'])
        st.info(f"📋 状态: {msg}")
        if updated: st.balloons()
    else:
        st.error("探测失败，执行保底同步...")
        update_dns(IP_LIST[0])

st.divider()
st.caption(f"🕒 巡检时间: {datetime.now().strftime('%H:%M:%S')}")

time.sleep(600)
st.rerun()
