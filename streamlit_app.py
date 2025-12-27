import streamlit as st
import requests
import time
import urllib.parse
from datetime import datetime

# 1. 自动配置检测
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except:
    st.error("❌ 错误：未检测到 Secrets 配置")
    st.stop()

# 2. 从你提供的列表中精选出本地测试最快的 IP
IP_LIST = [
    "108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1", 
    "173.245.58.1", "172.64.36.5", "162.159.46.10", "188.114.97.1"
]

def update_dns(new_ip):
    """真正的同步逻辑：修正 1.1.1.1"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}", "Content-Type": "application/json"}
    try:
        r = requests.get(f"{url}?name={CF_CONFIG['record_name']}", headers=headers, timeout=10).json()
        if r.get("success") and r.get("result"):
            record = r["result"][0]
            if record["content"] == new_ip: return "✅ IP 已是最佳"
            u = requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            }, timeout=10).json()
            return "🚀 自动优选成功" if u.get("success") else "❌ 同步权限受阻"
    except: return "⚠️ API 通讯超时"
    return "🔍 未发现 DNS 记录"

# --- 页面执行 ---
st.set_page_config(page_title="终极穿透版", page_icon="🚀")
st.title("🚀 4K 自动优选 - 终极穿透版")

with st.spinner("🛰️ 正在模拟真实握手，穿透云端封锁..."):
    results = []
    # 模拟手机端 NekoBox 的探测行为
    for ip in IP_LIST:
        # 依次测试 443 和 2053 端口
        for port in [443, 2053]:
            try:
                start = time.time()
                # 核心改进：模拟浏览器 User-Agent 和特定的 Host 头部
                headers = {
                    "Host": "milet.qzz.io",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                # 增加到 2.5 秒超时，给云端握手留出足够时间
                requests.get(f"https://{ip}:{port}/cdn-cgi/trace", headers=headers, timeout=2.5, verify=False)
                results.append({"ip": ip, "lat": int((time.time() - start) * 1000)})
                break 
            except: continue

    if results:
        results.sort(key=lambda x: x['lat'])
        winner = results[0]
        sync_msg = update_dns(winner['ip'])
        
        c1, c2 = st.columns(2)
        c1.metric("当前优选 IP", winner['ip'])
        c2.metric("云端探测延迟", f"{winner['lat']} ms")
        st.success(f"同步状态: {sync_msg}")
    else:
        # 如果还是不行，显示更详细的诊断
        st.error("❌ 探测依然超时！这代表云端数据中心封锁了该 IP 段。")
        st.warning("建议：在 Secrets 里更换 record_name 试试，或者确认 API 令牌是否过期。")

st.info(f"🕒 本次自动巡检时间: {datetime.now().strftime('%H:%M:%S')}")

# 自动刷新保持运行
time.sleep(600)
st.rerun()
