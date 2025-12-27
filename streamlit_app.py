import streamlit as st
import requests
import threading
import time
import urllib.parse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# 1. 核心数据持久化：确保数据在刷新后依然存在
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

def add_log(msg, type="info"):
    t = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs.append({"t": t, "m": msg, "type": type})
    if len(st.session_state.logs) > 10: st.session_state.logs.pop(0)

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
            top = results[0]
            # 执行 CF 同步 (此处省略详细代码以保持精炼)
            # ... update_cf_logic ...
            
            # 强制更新全局状态
            st.session_state.best_ip = top['ip']
            st.session_state.latency = top['lat']
            st.session_state.last_update = datetime.now().strftime("%H:%M:%S")
        time.sleep(600)

# 启动后台线程 (仅启动一次)
if 'thread_started' not in st.session_state:
    st.session_state.thread_started = True
    threading.Thread(target=worker, daemon=True).start()

# 界面渲染
st.title("⚡ 闪电版优选 (全局同步版)")
c1, c2, c3 = st.columns(3)
c1.metric("最优 IP", st.session_state.best_ip)
c2.metric("当前延迟", f"{st.session_state.latency} ms")
c3.metric("更新时间", st.session_state.last_update)

st.divider()
for l in reversed(st.session_state.logs):
    st.code(f"[{l['t']}] {l['m']}")

time.sleep(5)
st.rerun()