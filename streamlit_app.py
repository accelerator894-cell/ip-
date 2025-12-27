import streamlit as st
import requests
import threading
import time
import urllib.parse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# 1. 核心状态持久化
if 'best_ip' not in st.session_state: st.session_state.best_ip = "等待测速"
if 'latency' not in st.session_state: st.session_state.latency = 0
if 'last_update' not in st.session_state: st.session_state.last_update = "尚未同步"

# 2. 安全读取 Secrets
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except:
    st.error("❌ 未检测到 Secrets 配置，请在 Streamlit 后台设置。")
    st.stop()

VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@173.245.58.1:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG1",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.61.1:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG2",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@108.162.192.5:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#AP",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.46.10:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG3",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@172.64.36.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG4"
]

# --- 关键：真正的 Cloudflare 修改逻辑 ---
def push_to_cloudflare(target_ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}", "Content-Type": "application/json"}
    try:
        # 第一步：查找 Record ID
        res = requests.get(f"{url}?name={CF_CONFIG['record_name']}", headers=headers, timeout=10).json()
        if res.get("success") and res.get("result"):
            record_id = res["result"][0]["id"]
            current_ip = res["result"][0]["content"]
            if current_ip == target_ip: return "skip"
            
            # 第二步：更新 IP
            put_res = requests.put(f"{url}/{record_id}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": target_ip, "ttl": 60, "proxied": False
            }, timeout=10).json()
            return "success" if put_res.get("success") else "fail"
    except: return "error"
    return "fail"

def worker():
    while True:
        ips = list(set([urllib.parse.urlparse(l).netloc.split('@')[-1].split(':')[0] for l in VLESS_LINKS]))
        results = []
        with ThreadPoolExecutor(max_workers=5) as ex:
            for ip in ips:
                try:
                    s = time.time()
                    requests.get(f"https://{ip}/cdn-cgi/trace", timeout=1.5, verify=False)
                    results.append({"ip": ip, "lat": int((time.time()-s)*1000)})
                except: continue
        if results:
            results.sort(key=lambda x: x['lat'])
            winner = results[0]
            # 执行同步
            push_to_cloudflare(winner['ip'])
            # 更新界面状态
            st.session_state.best_ip = winner['ip']
            st.session_state.latency = winner['lat']
            st.session_state.last_update = datetime.now().strftime("%H:%M:%S")
        time.sleep(600)

# 启动测速引擎
if 'active' not in st.session_state:
    st.session_state.active = True
    threading.Thread(target=worker, daemon=True).start()

# 页面布局
st.title("⚡ 闪电优选 (全功能版)")
st.write(f"正在守护: `{CF_CONFIG['record_name']}`")
c1, c2, c3 = st.columns(3)
c1.metric("最优 IP", st.session_state.best_ip)
c2.metric("当前延迟", f"{st.session_state.latency} ms")
c3.metric("最后更新时间", st.session_state.last_update)
st.divider()
st.info("每 10 分钟自动检测并同步。系统启动后请等待 20 秒完成首次同步。")

time.sleep(10)
st.rerun()
