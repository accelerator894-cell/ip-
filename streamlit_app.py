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
    st.error("❌ 错误：请在 Secrets 中配置 api_token, zone_id 和 record_name")
    st.stop()

# --- 2. 找回并补全你的完整 IP 列表 ---
IP_LIST = [
    "108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1", 
    "173.245.58.1", "172.64.36.5", "162.159.46.10", "188.114.97.1",
    "104.16.160.1", "104.17.160.1", "104.18.160.1", "104.19.160.1",
    "104.20.160.1", "104.21.160.1", "104.22.160.1"
]

# --- 3. 核心功能函数 ---

def check_streaming(ip):
    """流媒体解锁深度探测"""
    status = {"Netflix": "❌", "YouTube": "❌", "Score": 0}
    headers = {"User-Agent": "Mozilla/5.0"}
    # Netflix 检测
    try:
        nf_res = requests.get(f"http://{ip}/title/80018499", headers={**headers, "Host": "www.netflix.com"}, timeout=2.0)
        if nf_res.status_code in [200, 301, 302]: 
            status["Netflix"] = "✅"
            status["Score"] += 1
    except: pass
    # YouTube 检测
    try:
        yt_res = requests.get(f"http://{ip}/premium", headers={**headers, "Host": "www.youtube.com"}, timeout=2.0)
        if yt_res.status_code == 200: 
            status["YouTube"] = "✅"
            status["Score"] += 1
    except: pass
    return status

def check_ip_quality(ip):
    """多维质检：延迟 + 丢包 + 流媒体"""
    q = {"ip": ip, "lat": 9999, "loss": 100, "stream": {"Score": 0, "Netflix": "❌", "YouTube": "❌"}}
    lats = []
    success = 0
    for _ in range(3): # 采样 3 次计算稳定性
        try:
            start = time.time()
            r = requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.5)
            if r.status_code < 500:
                lats.append(int((time.time() - start) * 1000))
                success += 1
        except: continue
    if success > 0:
        q["lat"] = sum(lats) / len(lats)
        q["loss"] = int(((3 - success) / 3) * 100)
        q["stream"] = check_streaming(ip)
    return q

def update_dns(new_ip):
    """更新 Cloudflare DNS"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}", "Content-Type": "application/json"}
    try:
        r = requests.get(f"{url}?name={CF_CONFIG['record_name']}", headers=headers, timeout=10).json()
        if r.get("success") and r.get("result"):
            record = r["result"][0]
            if record["content"] == new_ip: return "✅ IP 已是最佳", False
            u = requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            }, timeout=10).json()
            return f"🚀 已切换至: {new_ip}", True
    except: pass
    return "⚠️ 同步异常", False

# --- 4. 界面展示 ---

st.set_page_config(page_title="4K 终极引擎", page_icon="📡")
st.title("📡 4K 自动优选 (终极整合版)")

# 侧边栏模式切换
st.sidebar.header("⚙️ 引擎设置")
mode = st.sidebar.radio("优选模式", ("⚡ 速度优先 (低延迟)", "🎬 解锁优先 (流媒体)"))

with st.spinner(f"🔍 正在对 {len(IP_LIST)} 个节点进行深度质检..."):
    results = []
    for ip in IP_LIST:
        results.append(check_ip_quality(ip))
    
    active_results = [r for r in results if r["lat"] < 9999]

    if active_results:
        # 排序逻辑
        if "速度" in mode:
            active_results.sort(key=lambda x: (x['loss'], x['lat']))
        else:
            # 权重：解锁数(降序) > 丢包(升序) > 延迟(升序)
            active_results.sort(key=lambda x: (-x['stream']['Score'], x['loss'], x['lat']))
            if active_results[0]['stream']['Score'] == 0:
                st.sidebar.warning("💡 当前列表无解锁 IP，已按稳定性排序")

        winner = active_results[0]
        
        # 结果看板
        st.subheader(f"🎯 选定节点: {winner['ip']}")
        c1, c2, c3 = st.columns(3)
        c1.metric("平均延迟", f"{int(winner['lat'])}ms")
        c2.metric("丢包率", f"{winner['loss']}%")
        c3.metric("流媒体分", winner['stream']['Score'])
        
        st.write(f"📺 Netflix: {winner['stream'].get('Netflix')} | 🎥 YouTube: {winner['stream'].get('YouTube')}")

        # 自动同步
        status_msg, updated = update_dns(winner['ip'])
        st.info(f"📋 系统反馈: {status_msg}")
        if updated: st.balloons()
        
        # 数据详情
        with st.expander("📊 查看完整 IP 质检看板"):
            st.table([{
                "IP 地址": r['ip'],
                "延迟": f"{int(r['lat'])}ms" if r['lat'] < 9999 else "超时",
                "稳定性": f"{100 - r['loss']}%",
                "解锁状态": f"NF:{r['stream'].get('Netflix','❌')} YT:{r['stream'].get('YouTube','❌')}"
            } for r in results])
    else:
        st.error("❌ 所有 IP 探测失败，请检查网络或更新列表！")

st.divider()
st.caption(f"🕒 最后巡检时间: {datetime.now().strftime('%H:%M:%S')}")

# 10 分钟循环
time.sleep(600)
st.rerun()
