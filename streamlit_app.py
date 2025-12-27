import streamlit as st
import requests
import time
from datetime import datetime

# --- 1. 自动同步逻辑 ---
def sync_dns(new_ip):
    token = st.secrets["api_token"].strip()
    zone = st.secrets["zone_id"].strip()
    name = st.secrets["record_name"].strip()
    
    headers = {"Authorization": f"Bearer {token}"}
    base_url = f"https://api.cloudflare.com/client/v4/zones/{zone}/dns_records"
    
    try:
        # 查找记录
        r = requests.get(base_url, headers=headers, params={"name": name}).json()
        if r["success"] and r["result"]:
            rid = r["result"][0]["id"]
            old_ip = r["result"][0]["content"]
            if old_ip == new_ip: return "✅ 解析已是最新"
            
            # 执行更新
            u = requests.put(f"{base_url}/{rid}", headers=headers, json={
                "type": "A", "name": name, "content": new_ip, "ttl": 60, "proxied": False
            }).json()
            return "🚀 自动同步成功" if u["success"] else f"❌ 同步失败: {u['errors'][0]['message']}"
    except Exception as e:
        return f"⚠️ 接口异常: {str(e)}"

# --- 2. 界面展示 ---
st.title("🏎️ 4K 引擎：全自动云端版")

with st.sidebar:
    st.header("🔐 API 监控")
    # 直接尝试验证新令牌
    test_url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    try:
        res = requests.get(test_url, headers={"Authorization": f"Bearer {st.secrets['api_token']}"}).json()
        if res.get("success"):
            st.success("🟢 API 已就绪")
        else:
            st.error(f"🔴 受限: {res['errors'][0]['message']}")
    except:
        st.warning("🟡 连接云端超时")

# --- 3. 运行逻辑 ---
# 假设你已经选出了 17ms 的冠军 IP (winner_ip)
winner_ip = "172.64.32.12" # 示例数据，实际由你的探测逻辑生成
st.info(f"🎯 本轮优选 IP: {winner_ip}")

if st.button("🛰️ 立即手动同步同步"):
    status = sync_dns(winner_ip)
    st.write(status)

# 自动运行逻辑
st.caption(f"🕒 巡检时间: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
