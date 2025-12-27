import streamlit as st
import requests
import time
from datetime import datetime

# --- 1. 配置加载 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except Exception:
    st.error("❌ 错误：未检测到 Secrets 配置")
    st.stop()

# 待检测的 IP 列表（你可以根据需要在这里添加更多 IP）
IP_LIST = [
    "108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1", 
    "173.245.58.1", "172.64.36.5", "162.159.46.10", "188.114.97.1"
]

# --- 2. 核心功能函数 ---

def update_dns(new_ip):
    """更新 Cloudflare DNS 记录"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}", "Content-Type": "application/json"}
    try:
        r = requests.get(f"{url}?name={CF_CONFIG['record_name']}", headers=headers, timeout=10).json()
        if r.get("success") and r.get("result"):
            record = r["result"][0]
            if record["content"] == new_ip:
                return f"✅ DNS 已指向 {new_ip}"
            
            u = requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            }, timeout=10).json()
            return f"🚀 成功切换至: {new_ip}" if u.get("success") else "❌ 同步失败"
    except Exception as e:
        return f"⚠️ API 异常: {str(e)}"
    return "🔍 未找到域名记录"

def check_ip_quality(ip):
    """多维度质检：平均延迟 + 丢包率 + 响应速度"""
    quality = {"ip": ip, "lat": 9999, "loss": 100, "speed_score": 0}
    latencies = []
    success_count = 0
    test_rounds = 3 # 采样次数
    
    headers = {"User-Agent": "Mozilla/5.0", "Host": CF_CONFIG['record_name']}

    for _ in range(test_rounds):
        try:
            start = time.time()
            # 使用 HTTP HEAD 请求减少流量消耗
            resp = requests.head(f"http://{ip}", headers=headers, timeout=1.5)
            if resp.status_code < 500: # 只要不是 5xx 错误都视为连通
                latencies.append(int((time.time() - start) * 1000))
                success_count += 1
        except:
            continue
    
    if success_count > 0:
        quality["lat"] = sum(latencies) / len(latencies)
        quality["loss"] = int(((test_rounds - success_count) / test_rounds) * 100)
        # 简单速度评分：1 / (平均延迟 / 1000)
        quality["speed_score"] = round(1000 / quality["lat"], 2)
        
    return quality

# --- 3. 页面渲染 ---
st.set_page_config(page_title="深度优选引擎", page_icon="⚡")
st.title("⚡ 深度优选引擎 (多维质检版)")

with st.spinner("📊 正在执行多维度质检 (延迟/丢包/速度)..."):
    results = []
    for ip in IP_LIST:
        q = check_ip_quality(ip)
        if q["lat"] < 9999:
            results.append(q)

    if results:
        # 排序权重：丢包率(升序) > 延迟(升序) > 速度分(降序)
        results.sort(key=lambda x: (x['loss'], x['lat'], -x['speed_score']))
        winner = results[0]
        
        # 显示体检报告
        st.subheader(f"🎯 质检冠军: {winner['ip']}")
        c1, c2, c3 = st.columns(3)
        c1.metric("平均延迟", f"{int(winner['lat'])} ms")
        c2.metric("丢包率", f"{winner['loss']}%")
        c3.metric("速度评分", winner['speed_score'])
        
        # 执行同步
        sync_msg = update_dns(winner['ip'])
        st.info(f"📋 同步反馈: {sync_msg}")
    else:
        # 保底逻辑：如果全失败，尝试强制同步列表第一个
        st.warning("⚠️ 云端探测全数失败，执行保底同步...")
        sync_msg = update_dns(IP_LIST[0])
        st.info(f"📋 保底同步反馈: {sync_msg}")

st.divider()
st.caption(f"📅 最后检查时间: {datetime.now().strftime('%H:%M:%S')}")

# 自动刷新 (10分钟)
time.sleep(600)
st.rerun()
