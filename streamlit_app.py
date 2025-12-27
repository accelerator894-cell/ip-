import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. 页面设置与美化 ---
st.set_page_config(page_title="4K 引擎：终极全能版", page_icon="🏎️", layout="centered")

# --- 2. 配置加载 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except Exception:
    st.error("❌ 配置缺失：请在 Secrets 面板配置 api_token, zone_id 和 record_name")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 核心功能函数 ---

def check_cf_status():
    """实时监控 API 健康度"""
    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        r = requests.get(url, headers=headers, timeout=5).json()
        return "🟢 正常" if r.get("success") else "🔴 受限"
    except: return "🟡 延迟"

def fetch_global_ips():
    """【功能回归】自动搜集全球 IP 源"""
    sources = [
        "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
        "https://raw.githubusercontent.com/vfarid/cf-ip-scanner/main/pings.txt"
    ]
    ips = set()
    for url in sources:
        try:
            r = requests.get(url, timeout=5)
            found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
            ips.update(found)
        except: continue
    # 随机采样 15 个，平衡速度
    return random.sample(list(ips), min(len(ips), 15))

def quick_ping(ip, label):
    """快速探测延迟"""
    data = {"ip": ip, "type": label, "lat": 9999, "nf": "❓", "score": 0}
    try:
        start = time.time()
        r = requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        if r.status_code < 500:
            data["lat"] = int((time.time() - start) * 1000)
    except: pass
    return data

def deep_test(data):
    """流媒体解锁测试"""
    try:
        nf = requests.get(f"http://{data['ip']}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.2)
        data["nf"] = "✅" if nf.status_code in [200, 301, 302] else "❌"
        data["score"] = 1 if data["nf"] == "✅" else 0
    except: data["nf"] = "❌"
    return data

def save_winner(winner):
    """【功能回归】将冠军写入磁盘文件，永不丢失"""
    try:
        log = f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | {winner['lat']}ms | {winner['type']}\n"
        with open(DB_FILE, "a", encoding="utf-8") as f:
            f.write(log)
    except: pass

# --- 4. UI 界面 ---

st.title("🏎️ 4K 引擎：终极全能控制台")

with st.sidebar:
    st.header("🔐 云端监控")
    health = check_cf_status()
    st.metric("API 健康度", health)
    st.write("📊 额度策略：1200次/5分钟 (免费版)")
    st.divider()
    mode = st.radio("优选模式", ("⚡ 速度优先", "🎬 解锁优先"))
    if st.button("🗑️ 清空历史记录文件"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

with st.spinner("🕵️ 正在同步全球数据源并进行阶梯式质检..."):
    results = [] 
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1", "173.245.58.1", "172.64.36.5", "162.159.46.10", "188.114.97.1", "104.16.160.1", "104.17.160.1", "104.18.160.1", "104.19.160.1", "104.20.160.1", "104.21.160.1", "104.22.160.1"]
    
    # 获取全球搜集 IP
    dynamic_ips = fetch_global_ips()
    for ip in base_ips: results.append(quick_ping(ip, "🏠 基础"))
    for ip in dynamic_ips: results.append(quick_ping(ip, "🌍 搜集"))
    
    # 筛选并排序
    active = [r for r in results if r["lat"] < 9999]
    if active:
        active.sort(key=lambda x: x['lat'])
        top_candidates = active[:6] # 取最快的前6名进行深度解锁测试
        for q in top_candidates: deep_test(q)
        
        if "速度" in mode:
            top_candidates.sort(key=lambda x: x['lat'])
        else:
            top_candidates.sort(key=lambda x: (-x['score'], x['lat']))
            
        winner = top_candidates[0]
        
        # 保存记录
        save_winner(winner)

        # 冠军展示
        st.success(f"🎯 本轮优选冠军：{winner['ip']} ({winner['type']})")
        c1, c2 = st.columns(2)
        c1.metric("最低延迟", f"{winner['lat']}ms")
        c2.metric("流媒体状态", winner['nf'])

        # 实时看板 (平铺显示)
        st.subheader("📊 实时节点分类看板")
        st.dataframe(results, use_container_width=True)
        
        # 历史数据库展示 (平铺显示)
        st.divider()
        st.subheader("📜 极品 IP 历史存盘 (刷新不丢失)")
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r", encoding="utf-8") as f:
                history = f.readlines()
                st.code("".join(history[-15:])) # 显示最近15条记录
        else:
            st.write("暂无历史存盘数据")
    else:
        st.error("😰 探测异常，请检查 Secrets 配置。")

st.caption(f"🕒 巡检完成时间: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
