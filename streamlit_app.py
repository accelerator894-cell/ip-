import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. 页面配置 ---
st.set_page_config(page_title="4K 引擎：终极完全体", page_icon="⚡", layout="centered")

# 隐藏 Streamlit 默认菜单，美化界面
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1.5rem;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 严格读取配置 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except Exception as e:
    st.error(f"❌ 配置读取失败: {e}")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 功能函数群 ---

def check_api_health():
    """检测 API 健康度"""
    try:
        url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
        headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
        resp = requests.get(url, headers=headers, timeout=3).json()
        return "🟢 正常" if resp.get("success") else "🔴 异常"
    except:
        return "🟡 连接中..."

def get_global_ips():
    """搜集全球 IP"""
    sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
    pool = set()
    try:
        r = requests.get(sources[0], timeout=5)
        # 正则提取 IP
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        pool.update(found)
    except: pass
    # 随机取 10 个，保证速度
    return random.sample(list(pool), min(len(pool), 10))

def test_node(ip, label):
    """全能测试：延迟 + Netflix 解锁"""
    data = {"ip": ip, "type": label, "lat": 9999, "nf": "❓"}
    try:
        # 1. 测延迟
        start = time.time()
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.5)
        data["lat"] = int((time.time() - start) * 1000)
        
        # 2. 测解锁 (仅对低延迟节点测试，节省时间)
        if data["lat"] < 200:
            nf = requests.get(f"http://{ip}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.5)
            data["nf"] = "✅" if nf.status_code in [200, 301, 302] else "❌"
    except: pass
    return data

def sync_dns_robust(new_ip):
    """稳健的 DNS 同步逻辑 (保留成功经验)"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    
    try:
        # 精确搜索
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        search = requests.get(url, headers=headers, params=params, timeout=10).json()
        
        if not search.get("success") or not search.get("result"):
            return f"❌ 未找到记录: {CF_CONFIG['record_name']}"

        record = search["result"][0]
        if record["content"] == new_ip:
            return "✅ 当前已是最新 IP，无需更新"
            
        # 更新
        update = requests.put(f"{url}/{record['id']}", headers=headers, json={
            "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
        }).json()
        
        return f"🚀 同步成功！已指向 {new_ip}" if update.get("success") else "❌ 更新失败"
            
    except Exception as e:
        return f"⚠️ 网络错误: {str(e)}"

# --- 4. 主程序界面 ---

st.title("⚡ 4K 引擎：终极完全体")

# 侧边栏：API 健康度回归！
with st.sidebar:
    st.header("⚙️ 监控中心")
    health_status = check_api_health()
    st.metric("API 健康度", health_status)
    
    st.divider()
    if st.button("🗑️ 清空历史记录"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

# 主运行区
with st.spinner("🕵️ 全球巡检中 (搜集+测速+解锁检测)..."):
    results = []
    
    # 基础 IP 池
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    # 动态搜集
    global_ips = get_global_ips()
    
    # 执行测试
    for ip in base_ips: results.append(test_node(ip, "🏠 专属"))
    for ip in global_ips: results.append(test_node(ip, "🌍 搜集"))
    
    # 筛选有效节点
    active = [r for r in results if r["lat"] < 9999]
    
    if active:
        # 按延迟排序
        active.sort(key=lambda x: x['lat'])
        winner = active[0]
        
        # 1. 冠军展示
        st.success(f"🏆 本轮冠军: {winner['ip']} | 延迟: {winner['lat']}ms | 解锁: {winner['nf']}")
        
        # 2. 自动同步
        sync_msg = sync_dns_robust(winner['ip'])
        if "成功" in sync_msg or "无需更新" in sync_msg:
            st.info(sync_msg)
        else:
            st.error(sync_msg)
            
        # 3. 数据看板 (全功能回归)
        st.subheader("📊 实时节点详情")
        st.dataframe(results, use_container_width=True)
        
        # 4. 历史记录
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | {winner['lat']}ms\n")
            
        if os.path.exists(DB_FILE):
            st.divider()
            with st.expander("📜 查看历史优选记录", expanded=False):
                with open(DB_FILE, "r") as f:
                    st.text("".join(f.readlines()[-15:]))
    else:
        st.warning("⚠️ 本轮所有节点超时，等待下次重试...")

st.caption(f"🕒 最后更新: {datetime.now().strftime('%H:%M:%S')} (每 10 分钟自动刷新)")

# 自动循环
time.sleep(600)
st.rerun()
