import streamlit as st
import requests
import time
import re
import random
from datetime import datetime

# --- 1. 基础配置 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except Exception:
    st.error("❌ 错误：请检查 Secrets 配置")
    st.stop()

# 你的 15 个稳定基础 IP
BASE_IP_LIST = [
    "108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1", 
    "173.245.58.1", "172.64.36.5", "162.159.46.10", "188.114.97.1",
    "104.16.160.1", "104.17.160.1", "104.18.160.1", "104.19.160.1",
    "104.20.160.1", "104.21.160.1", "104.22.160.1"
]

# 网络自动搜集源
AUTO_SOURCES = [
    "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
    "https://raw.githubusercontent.com/vfarid/cf-ip-scanner/main/pings.txt"
]

# --- 2. 核心功能 ---

def fetch_auto_ips():
    """自动抓取并提取 IP"""
    discovered = set()
    for url in AUTO_SOURCES:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                # 正则匹配所有 IP 格式
                found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
                discovered.update(found)
        except: continue
    # 随机取 15 个新发现的 IP，防止总数过多导致测速过慢
    return random.sample(list(discovered), min(len(discovered), 15))

def check_ip_full_quality(ip):
    """多维质检：延迟 + 丢包 + 流媒体"""
    q = {"ip": ip, "lat": 9999, "loss": 100, "stream": {"Score": 0, "NF": "❌", "YT": "❌"}}
    lats = []
    success = 0
    headers = {"User-Agent": "Mozilla/5.0", "Host": CF_CONFIG['record_name']}
    
    # 3轮采样测延迟与稳定性
    for _ in range(3):
        try:
            start = time.time()
            res = requests.head(f"http://{ip}", headers=headers, timeout=1.5)
            if res.status_code < 500:
                lats.append(int((time.time() - start) * 1000))
                success += 1
        except: continue
        
    if success > 0:
        q["lat"] = sum(lats) / len(lats)
        q["loss"] = int(((3 - success) / 3) * 100)
        # 流媒体探测
        try:
            # Netflix 探测
            nf = requests.get(f"http://{ip}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.5)
            if nf.status_code in [200, 301, 302]: 
                q["stream"]["NF"] = "✅"; q["stream"]["Score"] += 1
            # YouTube 探测
            yt = requests.get(f"http://{ip}/premium", headers={"Host": "www.youtube.com"}, timeout=1.5)
            if yt.status_code == 200: 
                q["stream"]["YT"] = "✅"; q["stream"]["Score"] += 1
        except: pass
    return q

def perform_sync(new_ip):
    """同步至 Cloudflare"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        r = requests.get(f"{url}?name={CF_CONFIG['record_name']}", headers=headers).json()
        if r["success"] and r["result"]:
            record = r["result"][0]
            if record["content"] == new_ip: return "✅ 已经是最佳 IP"
            requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            })
            return f"🚀 已成功更新为: {new_ip}"
    except: return "⚠️ 同步失败"

# --- 3. UI 界面 ---

st.set_page_config(page_title="全球自动优选系统", page_icon="📡")
st.title("📡 全球 IP 自动巡检系统")

# 侧边栏设置
st.sidebar.header("⚙️ 自动化配置")
mode = st.sidebar.radio("优选模式", ("⚡ 速度优先", "🎬 解锁优先"))
auto_fetch = st.sidebar.toggle("开启全球自动搜集", value=True)

with st.spinner("🕵️ 正在进行全自动巡检..."):
    # 构建总 IP 池
    final_pool = BASE_IP_LIST.copy()
    if auto_fetch:
        discovered_ips = fetch_auto_ips()
        final_pool.extend(discovered_ips)
        st.sidebar.write(f"已额外搜集到 {len(discovered_ips)} 个全球节点")

    # 执行质检
    results = []
    for ip in final_pool:
        results.append(check_ip_full_quality(ip))
    
    active = [r for r in results if r["lat"] < 9999]
    
    if active:
        # 排序策略
        if "速度" in mode:
            active.sort(key=lambda x: (x['loss'], x['lat']))
        else:
            active.sort(key=lambda x: (-x['stream']['Score'], x['loss'], x['lat']))
        
        winner = active[0]
        
        # 显示结果
        st.subheader(f"🎯 本轮冠军: {winner['ip']}")
        c1, c2, c3 = st.columns(3)
        c1.metric("延迟", f"{int(winner['lat'])}ms")
        c2.metric("稳定性", f"{100-winner['loss']}%")
        c3.metric("流媒体分", winner['stream']['Score'])
        
        st.write(f"📺 Netflix: {winner['stream']['NF']} | 🎥 YouTube: {winner['stream']['YT']}")
        
        # 状态同步
        sync_status = perform_sync(winner['ip'])
        st.info(f"📋 同步反馈: {sync_status}")
        
        # 看板
        with st.expander("📊 查看所有节点体检报告"):
            st.table([{
                "IP": r['ip'], 
                "延迟": f"{int(r['lat'])}ms" if r['lat'] < 9999 else "超时",
                "解锁": f"NF:{r['stream']['NF']} YT:{r['stream']['YT']}",
                "类型": "基础" if r['ip'] in BASE_IP_LIST else "搜集"
            } for r in results])
    else:
        st.error("所有 IP 均不可用，请检查网络！")

st.divider()
st.caption(f"🕒 下次自动巡检将在 10 分钟后开始 | 当前时间: {datetime.now().strftime('%H:%M:%S')}")

# 自动循环
time.sleep(600)
st.rerun()
