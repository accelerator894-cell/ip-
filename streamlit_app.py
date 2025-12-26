import streamlit as st
import requests
import socket
import time
from concurrent.futures import ThreadPoolExecutor

# ================= 配置区：请务必填入你自己的 ID =================
CF_API_TOKEN = "你的API令牌"  
ZONE_ID = "你的区域ID"       
RECORD_ID = "你的记录ID"     
DNS_NAME = "speed"           
# =============================================================

# 候选 IP 段
IP_CANDIDATES = ["104.16.120.", "104.17.210.", "104.18.15.", "104.19.100.", "172.67.180."]

def test_ip_speed(ip, port=443, timeout=1):
    start = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        sock.close()
        return ip, (time.time() - start) * 1000
    except:
        return ip, float('inf')

def get_best_ip():
    ips = [f"{r}{i}" for r in IP_CANDIDATES for i in range(1, 21)]
    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(test_ip_speed, ips))
    valid = [r for r in results if r[1] < float('inf')]
    valid.sort(key=lambda x: x[1])
    return valid[0] if valid else (None, None)

def update_dns(new_ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records/{RECORD_ID}"
    headers = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}
    data = {"type": "A", "name": DNS_NAME, "content": new_ip, "ttl": 120, "proxied": False}
    response = requests.put(url, headers=headers, json=data)
    return response.status_code == 200

# --- 网页界面 ---
st.title("⚡ Cloudflare 自动优选同步")

if st.button("发现最快 IP，立即同步到云端"):
    with st.spinner("正在测速中..."):
        best_ip, latency = get_best_ip()
        if best_ip:
            st.write(f"找到最快 IP: {best_ip} ({latency:.2f}ms)")
            if update_dns(best_ip):
                st.success("✅ 同步成功！")
                st.balloons()
            else:
                st.error("❌ API 更新失败，请检查配置")
        else:
            st.error("❌ 未找到可用 IP")
