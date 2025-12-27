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
    st.error("❌ 错误：未检测到 Secrets 配置，请在 Streamlit 后台设置。")
    st.stop()

# 2. 从你提供的列表提取 IP (过滤掉重复和不可用项)
IP_LIST = [
    "173.245.58.1", "162.159.61.1", "108.162.192.5", "162.159.46.10", "172.64.36.5",
    "188.114.97.1", "141.101.120.5", "198.41.214.1", "104.17.78.1", "104.16.160.1",
    "172.64.32.12", "172.67.168.8", "104.25.120.36", "162.159.44.5", "103.21.244.5"
]

def update_dns(new_ip):
    """同步最优 IP 到 Cloudflare"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}", "Content-Type": "application/json"}
    try:
        r = requests.get(f"{url}?name={CF_CONFIG['record_name']}", headers=headers, timeout=5).json()
        if r.get("success") and r.get("result"):
            record = r["result"][0]
            if record["content"] == new_ip: return "✅ IP 稳定"
            u = requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            }, timeout=5).json()
            return "🚀 自动修正成功" if u.get("success") else f"❌ 失败: {u.get('errors')[0]['message']}"
    except: return "⚠️ 通讯异常"
    return "🔍 未发现记录"

# --- 页面执行 ---
st.set_page_config(page_title="终极整合版", page_icon="⚡")
st.title("⚡ 全自动 4K 优选引擎")

with st.spinner("🔄 正在穿透云端网络探测节点..."):
    results = []
    # 扩大探测范围
    for ip in IP_LIST:
        # 尝试两个常用端口
        for port in [443, 2053]:
            try:
                start = time.time()
                # 关键改进：带上 Host 伪装并允许更长的握手时间
                requests.get(
                    f"https://{ip}:{port}/cdn-cgi/trace", 
                    headers={"Host": "milet.qzz.io"}, 
                    timeout=2.0, 
                    verify=False
                )
                results.append({"ip": ip, "lat": int((time.time() - start) * 1000)})
                break # 只要一个端口通了就跳过当前 IP 的后续端口测试
            except: continue

    if results:
        results.sort(key=lambda x: x['lat'])
        winner = results[0]
        msg = update_dns(winner['ip'])
        
        c1, c2 = st.columns(2)
        c1.metric("当前冠军 IP", winner['ip'])
        c2.metric("穿透延迟", f"{winner['lat']} ms")
        st.success(f"同步状态: {msg}")
    else:
        st.error("❌ 探测失败：云端无法连接这些 IP。这通常是因为 Cloudflare 节点在云端环境被盾拦截，请尝试添加更多不同段的 IP。")

st.info(f"📅 最后检查时间: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
