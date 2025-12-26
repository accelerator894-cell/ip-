import streamlit as st
import requests
import socket
import time
import json
from concurrent.futures import ThreadPoolExecutor

# ================= 配置区：已根据你提供的信息修正 =================
CF_API_TOKEN = "92os9FwyeG7jQDYpD6Rb0Cxrqu5YjtUjGfY1xKBm".strip()
ZONE_ID = "7aa1c1ddfd9df2690a969d9f977f82ae".strip()
RECORD_ID = "efc4c37be906c8a19a67808e51762c1f".strip()

# 注意：这里建议只写前缀 "speed"，如果之前报错，请改回这个
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
    
    # 构造请求头，确保 Authorization 后面只有一个空格
    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "type": "A",
        "name": DNS_NAME,
        "content": str(new_ip),
        "ttl": 120,
        "proxied": False
    }
    
    try:
        # 使用 json=payload 会自动处理 utf-8 编码，无需手动指定
        response = requests.put(url, headers=headers, json=payload, timeout=10)
        return response.status_code == 200, response.text
    except Exception as e:
        return False, str(e)

# --- 网页界面 ---
st.set_page_config(page_title="CF 优选同步", page_icon="⚡")
st.title("⚡ Cloudflare 自动优选同步")

if st.button("发现最快 IP，立即同步到云端", type="primary"):
    with st.spinner("正在全球节点中搜寻最快路径..."):
        best_ip, latency = get_best_ip()
        if best_ip:
            st.info(f"找到最快 IP: {best_ip} (延迟: {latency:.2f}ms)")
            
            success, result_text = update_dns(best_ip)
            if success:
                st.success(f"✅ 解析同步成功！已指向 {best_ip}")
                st.balloons()
            else:
                # 如果失败，把具体错误打印出来
                st.error(f"❌ 同步失败。CF 返回信息: {result_text}")
        else:
            st.error("❌ 未能找到可用 IP，请稍后重试。")

st.divider()
st.caption("提示：同步成功后，请在手机设置中将“私人 DNS”改回“自动”即可享受加速。")
