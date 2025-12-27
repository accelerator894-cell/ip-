import streamlit as st
import requests
import time
import re
from datetime import datetime

# --- 1. 配置加载 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except Exception:
    st.error("❌ 错误：请在 Secrets 中配置 Cloudflare 相关参数")
    st.stop()

# 公开的 IP 采集源（示例使用社区维护的优质源）
SOURCES = [
    "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
    "https://raw.githubusercontent.com/vfarid/cf-ip-scanner/main/pings.txt"
]

# --- 2. 自动搜集函数 ---

def fetch_global_ips():
    """从多个源抓取最新 IP"""
    raw_ips = set()
    for url in SOURCES:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                # 使用正则表达式提取 IP 地址
                found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', resp.text)
                raw_ips.update(found)
        except:
            continue
    # 为了保证效率，我们随机取前 30 个进行深度质检
    import random
    list_ips = list(raw_ips)
    return random.sample(list_ips, min(len(list_ips), 30))

# --- 3. 质检与同步函数 (沿用之前的成熟逻辑) ---

def check_streaming(ip):
    status = {"Netflix": "❌", "YouTube": "❌", "Score": 0}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        nf_res = requests.get(f"http://{ip}/title/80018499", headers={**headers, "Host": "www.netflix.com"}, timeout=1.5)
        if nf_res.status_code in [200, 301, 302]: 
            status["Netflix"] = "✅"; status["Score"] += 1
    except: pass
    try:
        yt_res = requests.get(f"http://{ip}/premium", headers={**headers, "Host": "www.youtube.com"}, timeout=1.5)
        if yt_res.status_code == 200: 
            status["YouTube"] = "✅"; status["Score"] += 1
    except: pass
    return status

def check_ip_quality(ip):
    q = {"ip": ip, "lat": 9999, "loss": 100, "stream": {"Score": 0}}
    lats = []
    success = 0
    for _ in range(2): # 搜集模式下采样 2 次以换取速度
        try:
            start = time.time()
            requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
            lats.append(int((time.time() - start) * 1000))
            success += 1
        except: continue
    if success > 0:
        q["lat"] = sum(lats) / len(lats)
        q["loss"] = int(((2 - success) / 2) * 100)
        q["stream"] = check_streaming(ip)
    return q

def update_dns(new_ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        r = requests.get(f"{url}?name={CF_CONFIG['record_name']}", headers=headers).json()
        if r["success"] and r["result"]:
            record = r["result"][0]
            if record["content"] == new_ip: return "✅ IP 已最新"
            requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            })
            return f"🚀 已更新至: {new_ip}"
    except: return "⚠️ 同步失败"

# --- 4. 界面展示 ---

st.set_page_config(page_title="全球 IP 自动搜集引擎", page_icon="🌍")
st.title("🌍 全球 IP 自动搜集 & 筛选系统")

mode = st.sidebar.radio("优选模式", ("⚡ 速度优先", "🎬 解锁优先"))

if st.button("🔄 立即重新搜集并质检"):
    st.rerun()

with st.spinner("🕵️ 正在全球范围内搜集最新 IP 段..."):
    ips = fetch_global_ips()
    st.write(f"📡 已搜集到 {len(ips)} 个待检测节点")
    
    results = []
    progress_bar = st.progress(0)
    for i, ip in enumerate(ips):
        results.append(check_ip_quality(ip))
        progress_bar.progress((i + 1) / len(ips))

    active = [r for r in results if r["lat"] < 9999]
    if active:
        # 排序逻辑
        if "速度" in mode:
            active.sort(key=lambda x: (x['loss'], x['lat']))
        else:
            active.sort(key=lambda x: (-x['stream']['Score'], x['loss'], x['lat']))
        
        winner = active[0]
        st.success(f"🎯 自动搜集之王: {winner['ip']}")
        
        # 数据看板
        c1, c2, c3 = st.columns(3)
        c1.metric("平均延迟", f"{int(winner['lat'])}ms")
        c2.metric("丢包率", f"{winner['loss']}%")
        c3.metric("流媒体分", winner['stream']['Score'])
        
        status = update_dns(winner['ip'])
        st.info(f"📢 DNS 同步状态: {status}")
    else:
        st.error("😰 这一批搜集的 IP 全军覆没，请点击上方按钮重试。")

st.divider()
st.caption(f"🕒 最后搜集时间: {datetime.now().strftime('%H:%M:%S')}")

# 自动刷新 (建议搜集模式下时间设长一点，如 30 分钟)
time.sleep(1800)
st.rerun()
