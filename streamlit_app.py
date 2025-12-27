import streamlit as st
import requests
import threading
import time
import urllib.parse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# 1. 状态持久化
if 'best_ip' not in st.session_state: st.session_state.best_ip = "等待测速"
if 'latency' not in st.session_state: st.session_state.latency = 0
if 'last_update' not in st.session_state: st.session_state.last_update = "尚未同步"
if 'error_msg' not in st.session_state: st.session_state.error_msg = "运行正常"

# 2. 读取配置
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

def update_dns(new_ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}", "Content-Type": "application/json"}
    try:
        # 获取 Record ID
        r = requests.get(f"{url}?name={CF_CONFIG['record_name']}", headers=headers, timeout=10).json()
        if not r.get("success"):
            return f"查询失败: {r.get('errors')[0]['message']}"
        
        records = r.get("result", [])
        if not records:
            return "未找到匹配的域名记录，请检查 record_name"
        
        record = records[0]
        if record["content"] == new_ip: return "无需更新"
        
        # 更新 IP
        u = requests.put(f"{url}/{record['id']}", headers=headers, json={
            "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
        }, timeout=10).json()
        
        return "同步成功" if u.get("success") else f"同步失败: {u.get('errors')[0]['message']}"
    except Exception as e:
        return f"网络错误: {str(e)}"

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
            # 执行同步并保存结果消息
            res_msg = update_dns(winner['ip'])
            st.session_state.error_msg = res_msg
            st.session_state.best_ip = winner['ip']
            st.session_state.latency = winner['lat']
            st.session_state.last_update = datetime.now().strftime("%H:%M:%S")
        time.sleep(600)

if 'init' not in st.session_state:
    st.session_state.init = True
    threading.Thread(target=worker, daemon=True).start()

# 界面展示
st.title("⚡ 闪电优选 (故障诊断版)")
st.error(f"📡 当前系统状态: {st.session_state.error_msg}")

c1, c2, c3 = st.columns(3)
c1.metric("最优 IP", st.session_state.best_ip)
c2.metric("当前延迟", f"{st.session_state.latency} ms")
c3.metric("最后更新", st.session_state.last_update)

st.divider()
st.info("如果状态显示『同步失败』，请检查 API 令牌权限或 Zone ID 是否填错。")
time.sleep(10)
st.rerun()
