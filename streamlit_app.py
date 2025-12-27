import streamlit as st
import requests
import time
import re
import random
from datetime import datetime

# --- 1. 安全配置加载 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except Exception:
    st.error("❌ 安全警报：未检测到 Secrets 密钥，请在后台配置。")
    st.stop()

# 基础稳定 IP 池 (txt 提取)
BASE_IP_LIST = [
    "108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1", 
    "173.245.58.1", "172.64.36.5", "162.159.46.10", "188.114.97.1",
    "104.16.160.1", "104.17.160.1", "104.18.160.1", "104.19.160.1",
    "104.20.160.1", "104.21.160.1", "104.22.160.1"
]

# --- 2. 核心功能函数 ---

def check_cf_api_status():
    """监控 Cloudflare API 状态"""
    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        r = requests.get(url, headers=headers, timeout=5).json()
        return "🟢 正常" if r.get("success") else "🔴 密钥受限"
    except: return "🟡 连接缓慢"

def fetch_and_clean_ips():
    """自动搜集并清理，每轮只取最新 15 个全球 IP"""
    sources = [
        "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
        "https://raw.githubusercontent.com/vfarid/cf-ip-scanner/main/pings.txt"
    ]
    new_ips = set()
    for url in sources:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
                new_ips.update(found)
        except: continue
    return random.sample(list(new_ips), min(len(new_ips), 15))

def quick_ping(ip, type_label):
    """阶梯质检第一步：快速延迟测试"""
    data = {"ip": ip, "type": type_label, "lat": 9999, "loss": 0, "nf": "❓", "yt": "❓", "score": 0}
    lats = []
    success = 0
    headers = {"User-Agent": "Mozilla/5.0", "Host": CF_CONFIG['record_name']}
    for _ in range(2):
        try:
            start = time.time()
            r = requests.head(f"http://{ip}", headers=headers, timeout=1.0)
            if r.status_code < 500:
                lats.append(int((time.time() - start) * 1000))
                success += 1
        except: continue
    if success > 0:
        data["lat"] = sum(lats) / len(lats)
        data["loss"] = int(((2 - success) / 2) * 100)
    return data

def deep_stream_test(data):
    """阶梯质检第二步：深度流媒体测试（仅限尖子生）"""
    try:
        # Netflix
        nf = requests.get(f"http://{data['ip']}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.2)
        if nf.status_code in [200, 301, 302]: data["nf"] = "✅"; data["score"] += 1
        else: data["nf"] = "❌"
        # YouTube
        yt = requests.get(f"http://{data['ip']}/premium", headers={"Host": "www.youtube.com"}, timeout=1.2)
        if yt.status_code == 200: data["yt"] = "✅"; data["score"] += 1
        else: data["yt"] = "❌"
    except:
        data["nf"] = "❌"; data["yt"] = "❌"
    return data

def update_dns(new_ip):
    """最终 DNS 同步"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        r = requests.get(f"{url}?name={CF_CONFIG['record_name']}", headers=headers).json()
        if r["success"] and r["result"]:
            record = r["result"][0]
            if record["content"] == new_ip: return "✅ IP 无需变动"
            requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            })
            return f"🚀 已同步新 IP: {new_ip}"
    except: return "⚠️ 同步失败"

# --- 3. UI 布局 ---

st.set_page_config(page_title="终极优选控制台", page_icon="🛡️")
st.title("🛡️ 4K 引擎：终极全自动版")

# 侧边栏监控
st.sidebar.header("🔐 安全监控")
st.sidebar.metric("API 令牌状态", check_cf_api_status())
mode = st.sidebar.radio("优选模式", ("⚡ 速度优先", "🎬 解锁优先"))
st.sidebar.caption(f"最后更新: {datetime.now().strftime('%H:%M:%S')}")

# --- 4. 执行流程 ---

with st.spinner("🕵️ 全球巡检中，正在执行阶梯式测速..."):
    # 第一步：获取 IP
    dynamic_ips = fetch_and_clean_ips()
    
    # 第二步：快速 Ping（初步筛选）
    results = []
    for ip in BASE_IP_LIST: results.append(quick_ping(ip, "🏠 基础"))
    for ip in dynamic_ips: results.append(quick_ping(ip, "🌍 搜集"))
    
    # 过滤通畅的 IP
    active = [r for r in results if r["lat"] < 9999]
    
    if active:
        # 阶梯优化：只选延迟前 6 名进行昂贵的流媒体测试
        active.sort(key=lambda x: x['lat'])
        top_6 = active[:6]
        for q in top_6:
            deep_stream_test(q)
        
        # 第三步：根据模式最终排序
        if "速度" in mode:
            top_6.sort(key=lambda x: (x['loss'], x['lat']))
        else:
            top_6.sort(key=lambda x: (-x['score'], x['loss'], x['lat']))
        
        winner = top_6[0]
        
        # 展示冠军
        st.success(f"🎯 本轮冠军: {winner['ip']} ({winner['type']})")
        c1, c2, c3 = st.columns(3)
        c1.metric("延迟", f"{int(winner['lat'])}ms")
        c2.metric("稳定性", f"{100-winner['loss']}%")
        c3.metric("流媒体分", winner['score'])
        
        # 同步
        sync_msg = update_dns(winner['ip'])
        st.info(f"📋 同步反馈: {sync_msg}")
        
        # 全局分类看板
        st.subheader("📊 全球节点分类看板")
        st.dataframe(
            results, 
            use_container_width=True,
            column_config={
                "ip": "IP 地址", "type": "分类", "lat": "平均延迟", "loss": "丢包%", "nf": "Netflix", "yt": "YouTube"
            }
        )
    else:
        st.error("❌ 探测失败，请检查网络环境或 Secrets 配置。")

# 自动刷新
time.sleep(600)
st.rerun()
