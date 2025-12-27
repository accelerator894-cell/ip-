import streamlit as st
import requests
import time
import urllib.parse
from datetime import datetime

# 1. 基础配置读取
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except:
    st.error("❌ Secrets 未正确配置，请在 Streamlit 后台设置。")
    st.stop()

VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@173.245.58.1:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG1",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.61.1:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG2",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@108.162.192.5:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#AP",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.46.10:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG3",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@172.64.36.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG4"
]

def update_cloudflare_dns(target_ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}", "Content-Type": "application/json"}
    try:
        # 获取当前记录
        r = requests.get(f"{url}?name={CF_CONFIG['record_name']}", headers=headers, timeout=5).json()
        if r.get("success") and r.get("result"):
            record = r["result"][0]
            if record["content"] == target_ip: return "✅ IP 已经是最佳，无需更新"
            # 强制更新
            u = requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": target_ip, "ttl": 60, "proxied": False
            }, timeout=5).json()
            return "🚀 同步成功" if u.get("success") else f"❌ 同步失败: {u.get('errors')[0]['message']}"
    except Exception as e:
        return f"⚠️ API 通讯错误: {str(e)}"
    return "🔍 未找到域名记录"

# --- 执行区 ---
st.set_page_config(page_title="强力优选版", page_icon="⚡")
st.title("⚡ 强力触发版优选系统")

# 显示当前正在扫描的状态
with st.spinner("🔄 正在穿透云端网络，即时扫描节点中..."):
    ips = [urllib.parse.urlparse(l).netloc.split('@')[-1].split(':')[0] for l in VLESS_LINKS]
    results = []
    
    # 强制顺序扫描，给每个 IP 极短的超时时间，防止卡死
    for ip in ips:
        try:
            start_t = time.time()
            # 使用最轻量的 trace 探测
            requests.get(f"https://{ip}/cdn-cgi/trace", timeout=0.8, verify=False)
            results.append({"ip": ip, "lat": int((time.time() - start_t) * 1000)})
        except:
            continue

    if results:
        results.sort(key=lambda x: x['lat'])
        winner = results[0]
        sync_msg = update_cloudflare_dns(winner['ip'])
        
        # 立即展示数据
        c1, c2 = st.columns(2)
        c1.metric("当前冠军 IP", winner['ip'])
        c2.metric("实测延迟", f"{winner['lat']} ms")
        st.success(f"状态反馈: {sync_msg}")
        st.info(f"本次巡检完成时间: {datetime.now().strftime('%H:%M:%S')}")
    else:
        st.error("❌ 所有节点连接超时！请检查 Secrets 里的 API 配置或 VLESS 节点是否在线。")

st.divider()
st.caption("💡 此版本每次刷新页面都会强制测速。云端后台也会每 10 分钟自动唤醒执行一次。")

# 自动重载逻辑
time.sleep(600)
st.rerun()
