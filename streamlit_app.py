import streamlit as st
import requests
import threading
import time
import urllib.parse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# 1. 核心数据持久化
if 'best_ip' not in st.session_state: st.session_state.best_ip = "等待测速"
if 'latency' not in st.session_state: st.session_state.latency = 0
if 'last_update' not in st.session_state: st.session_state.last_update = "尚未同步"
if 'logs' not in st.session_state: st.session_state.logs = []

try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except:
    st.error("❌ Secrets 配置丢失")
    st.stop()

VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@173.245.58.1:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG1",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.61.1:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG2",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@108.162.192.5:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#AP",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.46.10:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG3",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@172.64.36.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG4"
]

# --- 补全：真正的同步逻辑函数 ---
def update_cloudflare(new_ip):
    base_url = "https://api.cloudflare.com/client/v4"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}", "Content-Type": "application/json"}
    try:
        # 1. 获取 Record ID
        list_url = f"{base_url}/zones/{CF_CONFIG['zone_id']}/dns_records?name={CF_CONFIG['record_name']}"
        res = requests.get(list_url, headers=headers, timeout=10).json()
        if res.get("success") and res.get("result"):
            record = res["result"][0]
            if record["content"] == new_ip:
                return "skip"
            # 2. 修改 IP
            update_url = f"{base_url}/zones/{CF_CONFIG['zone_id']}/dns_records/{record['id']}"
            data = {"type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False}
            requests.put(update_url, headers=headers, json=data, timeout=10)
            return "success"
    except:
        return "error"
    return "error"

def worker():
    while True:
        # 这里不能用 add_log，因为后台线程无法直接修改 st.session_state
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
            top = results[0]
            
            # --- 修正：调用同步逻辑 ---
            sync_res = update_cloudflare(top['ip'])
            
            # 更新全局状态（此处在后台静默执行）
            st.session_state.best_ip = top['ip']
            st.session_state.latency = top['lat']
            st.session_state.last_update = datetime.now().strftime("%H:%M:%S")
        
        time.sleep(600)

# 启动后台线程
if 'thread_started' not in st.session_state:
    st.session_state.thread_started = True
    t = threading.Thread(target=worker, daemon=True)
    t.start()

# 界面渲染
st.title("⚡ 闪电版优选 (正式修复版)")
st.write(f"当前监控域名: `{CF_CONFIG['record_name']}`")

c1, c2, c3 = st.columns(3)
c1.metric("最优 IP", st.session_state.best_ip)
c2.metric("当前延迟", f"{st.session_state.latency} ms")
c3.metric("更新时间", st.session_state.last_update)

st.divider()
st.info("💡 系统每 10 分钟自动检查一次。如果 IP 没变，代表当前 IP 依然是最快的。")

# 自动刷新页面以同步数据
time.sleep(10)
st.rerun()
