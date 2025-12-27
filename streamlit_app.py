import streamlit as st
import requests
import time
import re
import os
from datetime import datetime

# --- 1. 配置加载 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except:
    st.error("❌ 配置缺失：请在 Secrets 中填写必要密钥")
    st.stop()

DB_FILE = "best_ip_history.txt" # 本地持久化文件

# --- 2. 持久化存储函数（考虑性能与安全） ---

def save_winner_to_disk(winner_data):
    """安全地将冠军 IP 存入磁盘文件"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        log_entry = f"{timestamp} | {winner_data['ip']} | Lat: {winner_data['lat']}ms | Type: {winner_data['type']}\n"
        
        # 读取旧数据进行体量控制
        lines = []
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
        
        # 始终将最新的放在最前面，并限制 100 条
        lines.insert(0, log_entry)
        with open(DB_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines[:100])
    except Exception as e:
        # 即使存盘失败，也要保证主流程不崩溃
        print(f"磁盘写入告警: {e}")

def get_history_from_disk():
    """从磁盘读取历史数据"""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return f.readlines()
    return []

# --- 3. 核心逻辑（采用阶梯探测提速） ---

# (此处省略之前的 fetch_and_clean_ips, quick_ping, deep_stream_test 等函数，保持逻辑一致)

# --- 4. 界面渲染 ---

st.set_page_config(page_title="4K 引擎：深度存盘版", page_icon="🗄️")
st.title("🗄️ 4K 引擎：极速优选与深度存盘")

# 侧边栏：历史回顾
with st.sidebar:
    st.header("⚙️ 系统管理")
    if st.button("🗑️ 清空所有持久化数据"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.success("已清空")

with st.spinner("🕵️ 正在同步全球数据并进行存盘检查..."):
    # (假设通过阶梯探测选出了本轮 winner)
    
    # 逻辑：只有当 IP 与上一轮不同时，才触发磁盘写入（保护性能）
    if 'last_winner_ip' not in st.session_state or st.session_state.last_winner_ip != winner['ip']:
        save_winner_to_disk(winner)
        st.session_state.last_winner_ip = winner['ip']
        st.toast("💾 发现更优节点，已自动存盘！")

    # 展示当前冠军
    st.success(f"🎯 本轮优选：{winner['ip']}")
    
    # 展示持久化历史
    st.divider()
    st.subheader("📜 历史极品 IP 库（刷新不丢失）")
    history_logs = get_history_from_disk()
    if history_logs:
        st.code("".join(history_logs)) # 使用代码块展示，方便复制
    else:
        st.write("暂无存盘记录")

# 10 分钟循环
time.sleep(600)
st.rerun()
