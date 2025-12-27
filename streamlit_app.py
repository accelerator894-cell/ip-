import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. Pro 级页面初始化 ---
st.set_page_config(page_title="Cloudflare Pro 控制台", page_icon="⚡", layout="centered")

# 深度 CSS 注入
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1rem; padding-bottom: 2rem;}
    .stMetric {background-color: #f5f5f5; border-radius: 8px; padding: 10px; border: 1px solid #e0e0e0;}
    .reportview-container .main .block-container {max-width: 800px;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 严格配置加载 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except Exception as e:
    st.error(f"❌ 配置读取严重错误：{str(e)}")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 核心诊断与功能函数 ---

def diagnose_zone():
    """Pro 级诊断：反查 Zone ID 归属"""
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        # 1. 检查 Token
        verify = requests.get("https://api.cloudflare.com/client/v4/user/tokens/verify", headers=headers).json()
        if not verify.get("success"):
            return False, f"🔴 Token 无效: {verify['errors'][0]['message']}"
            
        # 2. 反查 Zone 信息
        zone_url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}"
        zone_info = requests.get(zone_url, headers=headers).json()
        
        if not zone_info.get("success"):
            return False, f"🔴 Zone ID 错误: 无法找到该区域，请检查 ID 是否复制正确。"
            
        real_zone_name = zone_info["result"]["name"]
        return True, f"🟢 配置正常 (Zone: {real_zone_name})"
    except Exception as e:
        return False, f"🟡 网络或 API 异常: {str(e)}"

def strict_dns_sync(best_ip):
    """带调试能力的 DNS 同步"""
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    zone_url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    
    try:
        # 1. 精确搜索
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        search = requests.get(zone_url, headers=headers, params=params).json()
        
        # 2. 深度调试逻辑
        if not search.get("success") or not search.get("result"):
            # 如果找不到，尝试列出该 Zone 下的前 3 条记录，帮用户排查
            debug_list = requests.get(zone_url, headers=headers, params={"per_page": 3}).json()
            existing_records = [r['name'] for r in debug_list.get('result', [])]
            
            error_msg = f"""
            ❌ 未找到记录 [{CF_CONFIG['record_name']}]
            ---- 深度诊断 ----
            当前 Zone ID 下的前 3 条记录是:
            {existing_records}
            
            👉 如果你的记录不在其中，说明 Zone ID 填错了（你可能填了主域名的 ID，但记录在子域名区域里）。
            """
            return error_msg
            
        record = search["result"][0]
        if record["content"] == best_ip:
            return f"✅ 解析已是最新 ({best_ip})"
            
        # 3. 执行更新
        update = requests.put(f"{zone_url}/{record['id']}", headers=headers, json={
            "type": "A", "name": CF_CONFIG['record_name'], "content": best_ip, "ttl": 60, "proxied": False
        }).json()
        
        if update.get("success"):
            return f"🚀 同步成功 -> {best_ip}"
        return f"❌ 更新失败: {update['errors'][0]['message']}"
            
    except Exception as e:
        return f"⚠️ API 通信错误: {str(e)}"

def get_global_ips():
    """全球 IP 资源池"""
    sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
    pool = set()
    try:
        r = requests.get(sources[0], timeout=3)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        pool.update(found)
    except: pass
    return random.sample(list(pool), min(len(pool), 10))

def pro_test(ip, label):
    """双重质检"""
    data = {"ip": ip, "type": label, "lat": 9999, "nf": "❓"}
    try:
        start = time.time()
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        data["lat"] = int((time.time() - start) * 1000)
        
        if data["lat"] < 200:
            nf = requests.get(f"http://{ip}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.5)
            data["nf"] = "✅" if nf.status_code in [200, 301, 302] else "❌"
    except: pass
    return data

# --- 4. 主程序逻辑 ---

st.title("⚡ Cloudflare Pro 诊断台")

# 侧边栏：核心诊断区
with st.sidebar:
    st.header("🔍 系统自检")
    is_healthy, health_msg = diagnose_zone()
    
    if is_healthy:
        st.success(health_msg)
    else:
        st.error(health_msg)
        st.stop() # 如果配置错了，直接停止运行，防止报错刷屏
    
    st.divider()
    mode = st.radio("优选策略", ["⚡ 极速模式", "🎬 奈飞模式"])
    if st.button("🗑️ 清空历史库"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

# 主界面：执行区
with st.spinner("🕵️ Pro 引擎正在扫描全球骨干网..."):
    results = []
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    
    dynamic_ips = get_global_ips()
    for ip in base_ips: results.append(pro_test(ip, "🏠 专属"))
    for ip in dynamic_ips: results.append(pro_test(ip, "🌍 搜集"))
    
    active = [r for r in results if r["lat"] < 9999]
    
    if active:
        if "极速" in mode:
            active.sort(key=lambda x: x['lat'])
        else:
            active.sort(key=lambda x: (0 if x['nf']=="✅" else 1, x['lat']))
            
        winner = active[0]
        
        # 结果展示
        st.success(f"🏆 冠军 IP: {winner['ip']} | 延迟: {winner['lat']}ms")
        
        # 同步
        sync_msg = strict_dns_sync(winner['ip'])
        
        if "❌" in sync_msg:
            st.error(sync_msg) # 这里会显示详细的诊断信息
        else:
            st.info(sync_msg)
            
        # 数据看板
        st.subheader("📊 实时遥测数据")
        st.dataframe(results, use_container_width=True)
        
        # 历史记录
        with open(DB_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | {winner['lat']}ms\n")
            
        if os.path.exists(DB_FILE):
            st.divider()
            with st.expander("📜 极品历史库", expanded=True):
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    st.code("".join(f.readlines()[-15:]))
    else:
        st.error("⚠️ 全球探测失败，请检查网络连通性。")

st.caption(f"⏱️ 自动巡检 | 更新于: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
