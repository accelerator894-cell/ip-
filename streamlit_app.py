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

IP_LIST = [
    "108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1", 
    "173.245.58.1", "172.64.36.5", "162.159.46.10", "188.114.97.1"
]

# --- 2. 新增：流媒体解锁检测函数 ---
def check_streaming(ip):
    """检测 IP 对主流流媒体的响应状态"""
    results = {"Netflix": "❌", "YouTube": "❌"}
    headers = {"User-Agent": "Mozilla/5.0", "Host": "www.netflix.com"}
    
    # 1. Netflix 检测 (简单检测是否能握手)
    try:
        nf_res = requests.get(f"http://{ip}/title/80018499", headers=headers, timeout=2.0)
        if nf_res.status_code in [200, 301, 302]:
            results["Netflix"] = "✅"
    except:
        pass
        
    # 2. YouTube 检测
    try:
        yt_headers = {"User-Agent": "Mozilla/5.0", "Host": "www.youtube.com"}
        yt_res = requests.get(f"http://{ip}/premium", headers=yt_headers, timeout=2.0)
        if yt_res.status_code == 200:
            results["YouTube"] = "✅"
    except:
        pass
        
    return results

# --- 3. 核心功能函数 ---
def update_dns(new_ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}", "Content-Type": "application/json"}
    try:
        r = requests.get(f"{url}?name={CF_CONFIG['record_name']}", headers=headers, timeout=10).json()
        if r.get("success") and r.get("result"):
            record = r["result"][0]
            if record["content"] == new_ip: return f"✅ DNS 已指向 {new_ip}"
            u = requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            }, timeout=10).json()
            return f"🚀 成功同步: {new_ip}" if u.get("success") else "❌ 同步失败"
    except Exception as e:
        return f"⚠️ API 异常: {str(e)}"
    return "🔍 未找到记录"

def check_ip_quality(ip):
    quality = {"ip": ip, "lat": 9999, "loss": 100, "stream": {}}
    latencies = []
    success_count = 0
    
    # 基础连通性测试 (3轮)
    for _ in range(3):
        try:
            start = time.time()
            resp = requests.head(f"http://{ip}", timeout=1.5)
            if resp.status_code < 500:
                latencies.append(int((time.time() - start) * 1000))
                success_count += 1
        except: continue
    
    if success_count > 0:
        quality["lat"] = sum(latencies) / len(latencies)
        quality["loss"] = int(((3 - success_count) / 3) * 100)
        # 连通后执行流媒体检测
        quality["stream"] = check_streaming(ip)
        
    return quality

# --- 4. 页面渲染 ---
st.set_page_config(page_title="4K 深度质检引擎", page_icon="🎬")
st.title("🎬 4K 引擎 (含流媒体质检)")

with st.spinner("🔍 正在深度探测 IP 质量与流媒体解锁..."):
    results = []
    for ip in IP_LIST:
        q = check_ip_quality(ip)
        if q["lat"] < 9999:
            results.append(q)

    if results:
        # 排序：丢包 > 延迟
        results.sort(key=lambda x: (x['loss'], x['lat']))
        winner = results[0]
        
        # 结果展示
        st.subheader(f"🎯 质检冠军: {winner['ip']}")
        
        # 第一排：基础指标
        c1, c2, c3 = st.columns(3)
        c1.metric("平均延迟", f"{int(winner['lat'])} ms")
        c2.metric("丢包率", f"{winner['loss']}%")
        
        # 第二排：流媒体状态
        st.write("**流媒体解锁探测 (云端视阈):**")
        s1, s2 = st.columns(2)
        s1.write(f"📺 Netflix: {winner['stream'].get('Netflix', '❓')}")
        s2.write(f"🎥 YouTube: {winner['stream'].get('YouTube', '❓')}")
        
        # 执行同步
        sync_msg = update_dns(winner['ip'])
        st.info(f"📋 同步反馈: {sync_msg}")
    else:
        st.warning("⚠️ 探测失败，执行保底同步...")
        update_dns(IP_LIST[0])

st.divider()
st.caption(f"📅 检查时间: {datetime.now().strftime('%H:%M:%S')}")

time.sleep(600)
st.rerun()
