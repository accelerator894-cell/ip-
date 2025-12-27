import streamlit as st
import requests
import time
from datetime import datetime

# 1. 自动配置检测
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except:
    st.error("❌ 错误：未检测到 Secrets 配置")
    st.stop()

IP_LIST = [
    "108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1", 
    "173.245.58.1", "172.64.36.5", "162.159.46.10", "188.114.97.1"
]

def update_dns(new_ip):
    """强制更新逻辑：无论云端能否连通，都尝试修改 DNS"""
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
            if record["content"] == new_ip:
                return f"✅ DNS 已指向 {new_ip}，无需操作"
            
            # 执行修改
            u = requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A",
                "name": CF_CONFIG['record_name'],
                "content": new_ip,
                "ttl": 60,
                "proxied": False # 优选 IP 必须关闭代理（灰色小黄云）
            }, timeout=10).json()
            
            return f"🚀 成功！DNS 已切换至: {new_ip}" if u.get("success") else f"❌ API 报错: {u.get('errors')[0]['message']}"
    except Exception as e:
        return f"⚠️ 通讯故障: {str(e)}"
    return "🔍 域名不存在，请检查 record_name"

# --- UI 界面 ---
st.set_page_config(page_title="DNS 强制修复版", page_icon="⚡")
st.title("⚡ 全自动 4K 优选引擎")

# 新增：手动强制同步按钮，用于排查 API 权限
if st.sidebar.button("🛠️ 强制同步第一个 IP (测试用)"):
    test_msg = update_dns(IP_LIST[0])
    st.sidebar.write(test_msg)

with st.spinner("🔍 正在尝试探测延迟..."):
    results = []
    for ip in IP_LIST:
        try:
            start = time.time()
            # 简化探测，只发 HEAD 请求尝试穿透
            requests.head(f"http://{ip}", timeout=1.0)
            results.append({"ip": ip, "lat": int((time.time() - start) * 1000)})
        except:
            continue

    # --- 核心改进逻辑 ---
    if results:
        results.sort(key=lambda x: x['lat'])
        target_ip = results[0]['ip']
        st.success(f"📡 探测成功：最优 IP {target_ip} ({results[0]['lat']}ms)")
    else:
        # 即使全部失败，也取第一个 IP 进行保底更新
        target_ip = IP_LIST[0]
        st.warning("⚠️ 云端探测被封锁！正在执行【保底强制同步】方案...")

    # 执行同步操作
    status_msg = update_dns(target_ip)
    
    # 显示状态卡片
    st.info(f"📋 同步反馈: {status_msg}")
    st.metric("目标 IP", target_ip)

st.write(f"📅 最后检查时间: {datetime.now().strftime('%H:%M:%S')}")

# 自动刷新
time.sleep(600)
st.rerun()
