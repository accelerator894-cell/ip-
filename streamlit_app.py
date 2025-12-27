import streamlit as st
import requests
import time
from datetime import datetime

# ... (保持前面的 CF_CONFIG 不变) ...

def update_dns(new_ip):
    """更新 Cloudflare DNS 记录"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {
        "Authorization": f"Bearer {CF_CONFIG['api_token']}",
        "Content-Type": "application/json"
    }
    try:
        # 获取现有记录
        r = requests.get(f"{url}?name={CF_CONFIG['record_name']}", headers=headers, timeout=10).json()
        if r.get("success") and r.get("result"):
            record = r["result"][0]
            # 只有当 IP 不同时才更新，避免频繁操作被限流
            if record["content"] == new_ip: 
                return f"✅ IP 已是 {new_ip}，无需更新"
            
            u = requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A", 
                "name": CF_CONFIG['record_name'], 
                "content": new_ip, 
                "ttl": 60, 
                "proxied": False # 注意：选优选IP通常需要关闭小黄云(False)
            }, timeout=10).json()
            
            if u.get("success"):
                return f"🚀 成功同步至: {new_ip}"
            else:
                return f"❌ 权限错误: {u.get('errors')}"
    except Exception as e:
        return f"⚠️ API 通讯故障: {str(e)}"
    return "🔍 未发现匹配的域名记录"

# --- 页面逻辑 ---
st.title("🚀 DNS 强制优选同步器")

# 增加一个“手动强制同步”按钮，方便测试 API 是否打通
if st.button("🔄 立即强制同步第一个 IP"):
    msg = update_dns(IP_LIST[0])
    st.write(msg)

with st.spinner("📡 正在尝试穿透探测..."):
    results = []
    for ip in IP_LIST:
        try:
            # 简化探测：仅测试 HTTP 连接，不进行深度握手，提高成功率
            start = time.time()
            requests.head(f"http://{ip}", timeout=1.5) 
            results.append({"ip": ip, "lat": int((time.time() - start) * 1000)})
        except:
            continue

    if results:
        results.sort(key=lambda x: x['lat'])
        winner_ip = results[0]['ip']
        st.success(f"探测成功！最优 IP: {winner_ip}")
    else:
        # 【重要改进】如果探测全灭，强制取列表第一个 IP 尝试更新，防止死循环失败
        winner_ip = IP_LIST[0]
        st.warning("⚠️ 云端探测全数失败（网络屏蔽），将尝试强制同步列表首位 IP。")

    # 执行同步
    sync_result = update_dns(winner_ip)
    st.info(f"同步状态汇报: {sync_result}")

st.write(f"最后检查: {datetime.now().strftime('%H:%M:%S')}")
