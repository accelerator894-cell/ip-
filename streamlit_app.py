import streamlit as st
import requests
import time
import urllib.parse
from datetime import datetime

# 1. 基础配置
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except:
    st.error("❌ Secrets 未配置")
    st.stop()

VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@173.245.58.1:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG1",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.61.1:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG2",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@108.162.192.5:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#AP",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.46.10:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG3",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@172.64.36.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG4"
]

def update_cf(ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        r = requests.get(f"{url}?name={CF_CONFIG['record_name']}", headers=headers).json()
        if r.get("success") and r.get("result"):
            rid = r["result"][0]["id"]
            if r["result"][0]["content"] == ip: return "稳定"
            requests.put(f"{url}/{rid}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": ip, "ttl": 60, "proxied": False
            })
            return "已同步"
    except: return "同步失败"
    return "未知"

# --- 核心执行区 ---
st.title("⚡ 强力触发版优选")
status_area = st.empty()
status_area.info("正在即时扫描节点...")

# 解析 IP
ips = [urllib.parse.urlparse(l).netloc.split('@')[-1].split(':')[0] for l in VLESS_LINKS]
results = []

# 顺序快速扫描 (不使用多线程，避免云端冲突)
for ip in ips:
    try:
        start = time.time()
        # 使用更轻量的 trace 请求
        requests.get(f"https://{ip}/cdn-cgi/trace", timeout=0.8, verify=False)
        results.append({"ip": ip, "lat": int((time.time() - start) * 1000)})
    except:
        continue

if results:
    results.sort(key=lambda x: x['lat'])
    winner = results[0]
    sync_status = update_cf(winner['ip'])
    
    # 直接显示结果
    c1, c2, c3 = st.columns(3)
    c1.metric("当前冠军 IP", winner['ip'])
    c2.metric("实测延迟", f"{winner['lat']} ms")
    c3.metric("CF 同步状态", sync_status)
    status_area.success(f"✅ 巡检完成！当前时间: {datetime.now().strftime('%H:%M:%S')}")
else:
    status_area.error("❌ 所有节点连接超时，请检查节点 IP 是否可用")

st.divider()
st.caption("系统每 10 分钟自动重载。你可以通过手动刷新网页立即触发测速。")

# 自动刷新占位
time.sleep(600)
st.rerun()
