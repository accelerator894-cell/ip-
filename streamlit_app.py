import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. 页面初始化 ---
st.set_page_config(page_title="Cloudflare 自动优选 Pro", page_icon="⚡", layout="centered")

# 隐藏多余菜单，打造 APP 质感
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1.5rem;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 严格读取 Secrets (保留你成功的配置) ---
try:
    # 使用 .strip() 防止复制时带入空格
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except Exception as e:
    st.error(f"❌ 配置文件读取失败: {e}")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 核心功能函数 ---

def sync_dns(new_ip):
    """同步 IP 到 Cloudflare (基于验证成功的逻辑)"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    
    try:
        # 1. 搜索记录
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        search = requests.get(url, headers=headers, params=params, timeout=10).json()
        
        if not search.get("success"):
            return f"❌ API 拒绝访问: {search.get('errors')[0]['message']}"
            
        if not search.get("result"):
            return f"❌ 未找到记录: {CF_CONFIG['record_name']} (请检查域名拼写)"

        # 2. 对比与更新
        record = search["result"][0]
        if record["content"] == new_ip:
            return "✅ 当前已是最新 IP，无需更新"
            
        update = requests.put(f"{url}/{record['id']}", headers=headers, json={
            "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
        }).json()
        
        if update.get("success"):
            return f"🚀 同步成功！已指向 {new_ip}"
        return "❌ 更新失败"
            
    except Exception as e:
        return f"⚠️ 网络异常: {str(e)}"

def get_global_ips():
    """获取全球优选 IP 池"""
    sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
    pool = set()
    try:
        r = requests.get(sources[0], timeout=5)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        pool.update(found)
    except: pass
    # 随机取 10 个作为补充
    return random.sample(list(pool), min(len(pool), 10))

def test_speed(ip):
    """测速函数"""
    try:
        start = time.time()
        # 模拟真实访问
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.5)
        return int((time.time() - start) * 1000)
    except:
        return 9999

# --- 4. 全自动运行主程序 ---

st.title("⚡ Cloudflare 自动优选 Pro")

# 侧边栏状态
with st.sidebar:
    st.header("⚙️ 监控面板")
    # 快速检查 API 连通性
    try:
        check = requests.get("https://api.cloudflare.com/client/v4/user/tokens/verify", 
                           headers={"Authorization": f"Bearer {CF_CONFIG['api_token']}"}, timeout=3).json()
        status = "🟢 正常" if check.get("success") else "🔴 异常"
    except: status = "🟡 连接中"
    
    st.metric("API 状态", status)
    
    if st.button("🗑️ 清空历史记录"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

# 主界面巡检逻辑
with st.spinner("🕵️ 正在全自动巡检全球节点..."):
    results = []
    # 你的高优 IP 列表
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    
    # 1. 混合 IP 池
    candidates = base_ips + get_global_ips()
    
    # 2. 测速
    for ip in candidates:
        lat = test_speed(ip)
        if lat < 9999:
            results.append({"ip": ip, "lat": lat})
    
    if results:
        # 按延迟排序，取第一名
        results.sort(key=lambda x: x['lat'])
        winner = results[0]
        
        # 3. 结果展示
        st.success(f"🏆 本轮冠军: {winner['ip']} (延迟 {winner['lat']}ms)")
        
        # 4. 执行同步
        msg = sync_dns(winner['ip'])
        if "成功" in msg or "最新" in msg:
            st.info(msg)
        else:
            st.error(msg)
            
        # 5. 看板与历史
        st.subheader("📊 实时数据看板")
        st.dataframe(results, use_container_width=True)
        
        # 写入历史
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | {winner['lat']}ms\n")
            
        if os.path.exists(DB_FILE):
            st.divider()
            with st.expander("📜 历史优选记录", expanded=False):
                with open(DB_FILE, "r") as f:
                    st.text("".join(f.readlines()[-10:]))
    else:
        st.warning("⚠️ 本轮探测所有节点均超时，等待下一次重试...")

st.caption(f"🕒 最后更新: {datetime.now().strftime('%H:%M:%S')} (每 10 分钟自动刷新)")

# --- 5. 自动循环引擎 ---
time.sleep(600) # 600秒 = 10分钟
st.rerun()
