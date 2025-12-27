import streamlit as st
import requests
import time
from datetime import datetime

# --- 1. 页面配置与 APP 美化 ---
st.set_page_config(page_title="4K 引擎：终极控制台", page_icon="🚀", layout="centered")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1.5rem;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 配置安全加载 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except:
    st.error("❌ 配置缺失：请在 Secrets 中配置 api_token, zone_id 和 record_name")
    st.stop()

# --- 3. 核心功能：自动同步冠军 IP ---
def sync_dns(new_ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        # 1. 检索对应的 A 记录
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        recs = requests.get(url, headers=headers, params=params).json()
        
        if recs["success"] and recs["result"]:
            record = recs["result"][0]
            if record["content"] == new_ip:
                return "✅ 解析已是最新"
            # 2. 发现变动，执行云端同步
            res = requests.put(f"{url}/{record['id']}", headers=headers, json={
                "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
            }).json()
            return "🚀 同步成功" if res["success"] else "❌ 同步失败"
        return "❌ 未找到记录 (请核对 record_name 是否完全一致)"
    except: return "⚠️ API 通信异常"

# --- 4. 自动化主流程 ---
st.title("🚀 4K 引擎：终极控制台")

with st.sidebar:
    st.header("⚙️ 系统监控")
    # API 健康检测
    test_url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    r = requests.get(test_url, headers={"Authorization": f"Bearer {CF_CONFIG['api_token']}"}).json()
    st.metric("API 健康度", "🟢 正常" if r.get("success") else "🔴 受限")

with st.spinner("🕵️ 正在进行全球巡检..."):
    results = []
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    
    for ip in base_ips:
        try:
            start = time.time()
            requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
            lat = int((time.time() - start) * 1000)
            results.append({"ip": ip, "lat": lat, "type": "🏠 基础"})
        except: continue
    
    if results:
        results.sort(key=lambda x: x['lat'])
        winner = results[0]
        
        # 冠军展示与同步
        st.success(f"🎯 本轮冠军：{winner['ip']} | 延迟：{winner['lat']}ms")
        sync_status = sync_dns(winner['ip'])
        st.info(f"🛰️ 云端同步状态：{sync_status}")

        # 分类看板
        st.subheader("📊 实时节点分类看板")
        st.dataframe(results, use_container_width=True)
    else:
        st.error("探测失败，请检查网络环境。")

st.caption(f"🕒 更新时间: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()