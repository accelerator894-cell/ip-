import streamlit as st
import requests
import time
import re
import random
from datetime import datetime

# --- 1. 配置加载 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except:
    st.error("❌ 错误：请检查 Secrets 配置")
    st.stop()

BASE_IP_LIST = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1", "173.245.58.1"] # 示例中精简，实际请补全你的15个

# --- 2. 优化：高性能质检函数 ---

def quick_check(ip, is_base):
    """第一步：快速筛选低延迟 IP"""
    q = {"ip": ip, "lat": 9999, "type": "🏠 基础" if is_base else "🌍 搜集", "stream": {"Score": 0}}
    try:
        start = time.time()
        # 极短超时设置 (1.0s)，快速排除死 IP
        r = requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        if r.status_code < 500:
            q["lat"] = int((time.time() - start) * 1000)
    except: pass
    return q

def deep_check_stream(q):
    """第二步：仅对入选优选范围的 IP 进行深度流媒体质检"""
    try:
        # 仅测 Netflix
        nf = requests.get(f"http://{q['ip']}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.2)
        if nf.status_code in [200, 301, 302]: q["stream"]["Score"] += 1
    except: pass
    return q

# --- 3. 界面逻辑 ---

st.set_page_config(page_title="极速优选版", page_icon="⚡")
st.title("⚡ 极速全自动优选引擎")

# 侧边栏
mode = st.sidebar.radio("模式", ("速度优先", "解锁优先"))

with st.spinner("🚀 正在执行极速巡检..."):
    # 搜集源精简为 10 个
    # (fetch_ips 逻辑略...)
    
    # 步骤 A：并行思路的快速探测
    results = []
    for ip in BASE_IP_LIST: results.append(quick_check(ip, True))
    # ... 加上动态搜集的 ...
    
    # 步骤 B：过滤出通畅的 IP
    active = [r for r in results if r["lat"] < 800] # 只测延迟小于 800ms 的
    
    # 步骤 C：只给排名前 5 的 IP 做深度流媒体测试（大幅提速！）
    active.sort(key=lambda x: x['lat'])
    top_candidates = active[:5]
    for q in top_candidates:
        deep_check_stream(q)
    
    # 重新排序并选出冠军
    if "速度" in mode:
        top_candidates.sort(key=lambda x: x['lat'])
    else:
        top_candidates.sort(key=lambda x: (-x['stream']['Score'], x['lat']))
    
    if top_candidates:
        winner = top_candidates[0]
        st.success(f"🎯 本轮冠军: {winner['ip']}")
        # (显示看板和同步逻辑...)
    else:
        st.error("😰 探测超时或节点全灭，请刷新重试。")

time.sleep(600)
st.rerun()
