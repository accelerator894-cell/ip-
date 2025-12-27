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

# 2. 节点素材库
VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@173.245.58.1:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG1",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.61.1:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG2",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@108.162.192.5:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#AP",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.46.10:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG3",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@172.64.36.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG4"
]

def update_dns(new_ip):
    """补全：真正的 DNS 更新逻辑"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}", "Content-Type": "application/json"}
    try:
        r = requests.get(f"{url}?name={CF_CONFIG['record_name']}", headers=headers, timeout=5).json()
        if r.get("success") and r.get("result"):
            record = r["result"][0]
            if record["content"] == new_ip: return "✅ IP 稳定，无需操作"
            u = requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            }, timeout=5).json()
            return "🚀 成功：IP 已自动修正" if u.get("success") else f"❌ 失败: {u.get('errors')[0]['message']}"
    except: return "⚠️ 通讯异常"
    return "🔍 未发现记录"

# --- 页面执行 ---
st.set_page_config(page_title="终极穿透版", page_icon="⚡")
st.title("⚡ 全自动 4K 优选引擎")

with st.spinner("🔄 正在穿透防火墙探测节点..."):
    ips = [urllib.parse.urlparse(l).netloc.split('@')[-1].split(':')[0] for l in VLESS_LINKS]
    results = []
    
    for ip in ips:
        try:
            start = time.time()
            # 关键改进：伪装 Host 头部，绕过云端拦截
            requests.get(f"https://{ip}/cdn-cgi/trace", headers={"Host": "milet.qzz.io"}, timeout=1.2, verify=False)
            results.append({"ip": ip, "lat": int((time.time() - start) * 1000)})
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
        st.error("❌ 探测失败：云端无法连接这些 IP。请检查 IP 是否被封或更换 IP 列表。")

st.info(f"📅 最后检查时间: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
