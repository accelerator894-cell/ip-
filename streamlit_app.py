import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. Pro 级页面初始化 ---
st.set_page_config(page_title="Cloudflare Pro 控制台", page_icon="⚡", layout="centered")

# 深度 CSS 注入：隐藏无关元素，打造原生 App 质感
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1rem; padding-bottom: 1rem;}
    .stMetric {background-color: #f0f2f6; border-radius: 8px; padding: 10px;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 严格配置加载 (Strict Mode) ---
# 逻辑：直接读取 st.secrets，不设 default 值。
# 如果 Secrets 配置错，程序直接拒绝运行，杜绝“猜错”的可能性。
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except Exception as e:
    st.error(f"❌ 严重错误：Secrets 配置无法读取。请检查后台配置格式。\n错误详情: {str(e)}")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 工业级核心函数 ---

def check_health():
    """API 握手检查"""
    try:
        url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
        res = requests.get(url, headers={"Authorization": f"Bearer {CF_CONFIG['api_token']}"}, timeout=5).json()
        return "🟢 正常" if res.get("success") else f"🔴 鉴权失败: {res['errors'][0]['message']}"
    except: return "🟡 连接超时"

def strict_dns_sync(best_ip):
    """严格模式 DNS 同步"""
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    zone_url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    
    try:
        # 1. 精确搜索：必须完全匹配 record_name
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        search = requests.get(zone_url, headers=headers, params=params).json()
        
        if not search.get("success") or not search.get("result"):
            # 调试信息：如果找不到，告诉用户到底 API 搜的是什么
            return f"❌ 未找到记录。API正在搜索: [{CF_CONFIG['record_name']}]。请核对Cloudflare后台是否完全一致。"
            
        record = search["result"][0]
        record_id = record["id"]
        current_ip = record["content"]
        
        # 2. 幂等性检查：如果 IP 没变，不浪费 API 调用次数
        if current_ip == best_ip:
            return f"✅ 已是最佳 ({best_ip})"
            
        # 3. 执行更新
        update_payload = {
            "type": "A", 
            "name": CF_CONFIG['record_name'], 
            "content": best_ip, 
            "ttl": 60, 
            "proxied": False
        }
        update = requests.put(f"{zone_url}/{record_id}", headers=headers, json=update_payload).json()
        
        if update.get("success"):
            return f"🚀 同步成功 -> {best_ip}"
        else:
            return f"❌ 更新被拒: {update['errors'][0]['message']}"
            
    except Exception as e:
        return f"⚠️ 通信异常: {str(e)}"

def get_global_ips():
    """全球 IP 资源池搜集"""
    sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
    pool = set()
    try:
        r = requests.get(sources[0], timeout=3)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        pool.update(found)
    except: pass
    # 随机取 10 个，保持轻量化
    return random.sample(list(pool), min(len(pool), 10))

def pro_test(ip, label):
    """双重质检：延迟 + 伪装 Host 测试 + Netflix"""
    data = {"ip": ip, "type": label, "lat": 9999, "nf": "❓"}
    try:
        start = time.time()
        # 关键：使用配置的 record_name 作为 Host 头，模拟真实访问
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        data["lat"] = int((time.time() - start) * 1000)
        
        # 只有延迟极低 (<200ms) 的节点才有资格测 Netflix
        if data["lat"] < 200:
            nf_check = requests.get(f"http://{ip}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.5)
            data["nf"] = "✅" if nf_check.status_code in [200, 301, 302] else "❌"
    except: pass
    return data

# --- 4. 主程序逻辑 ---

st.title("⚡ Cloudflare 自动优选 Pro")

# 侧边栏状态区
with st.sidebar:
    st.header("🛡️ 系统核心")
    health = check_health()
    st.metric("API 状态", health)
    
    st.divider()
    mode = st.radio("优选策略", ["⚡ 极速优先", "🎬 媒体优先"])
    
    if st.button("🗑️ 格式化历史库"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

# 主界面执行区
with st.spinner("🕵️ Pro 引擎正在扫描全球骨干网..."):
    results = []
    # 你的黄金 IP 列表
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    
    # 1. 并行搜集
    dynamic_ips = get_global_ips()
    
    # 2. 深度测试
    for ip in base_ips: results.append(pro_test(ip, "🏠 专属"))
    for ip in dynamic_ips: results.append(pro_test(ip, "🌍 搜集"))
    
    # 3. 智能决策
    active_nodes = [r for r in results if r["lat"] < 9999]
    
    if active_nodes:
        # 根据策略排序
        if "极速" in mode:
            active_nodes.sort(key=lambda x: x['lat'])
        else:
            # 媒体模式：Netflix 优先，然后看延迟
            active_nodes.sort(key=lambda x: (0 if x['nf']=="✅" else 1, x['lat']))
            
        winner = active_nodes[0]
        
        # 4. 结果呈现
        st.success(f"🏆 优选冠军: {winner['ip']} | 延迟: {winner['lat']}ms")
        
        # 5. 执行同步 (关键步骤)
        sync_msg = strict_dns_sync(winner['ip'])
        if "❌" in sync_msg:
            st.error(sync_msg) # 红色报错，醒目
        else:
            st.info(sync_msg)  # 蓝色/绿色提示，成功
            
        # 6. 数据看板 (所有功能回归)
        st.subheader("📊 实时节点遥测")
        st.dataframe(results, use_container_width=True)
        
        # 7. 历史持久化
        timestamp = datetime.now().strftime('%m-%d %H:%M')
        log_entry = f"{timestamp} | {winner['ip']} | {winner['lat']}ms | {winner['nf']}\n"
        with open(DB_FILE, "a", encoding="utf-8") as f: f.write(log_entry)
        
        if os.path.exists(DB_FILE):
            st.divider()
            with st.expander("📜 查看极品 IP 历史库 (最近 20 条)", expanded=True):
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    st.code("".join(lines[-20:]))
    else:
        st.error("⚠️ 全球探测失败。请检查 Secrets 中的 record_name 是否正确，或网络是否连通。")

st.caption(f"⏱️ 自动巡检系统 | 最后更新: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600) # 10分钟轮询
st.rerun()
