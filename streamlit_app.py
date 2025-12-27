import streamlit as st
import requests
import time
import re
import random
import os
import json
import pandas as pd
import concurrent.futures
import statistics
import socket
import threading
import ipaddress
from datetime import datetime
import urllib3

# 禁用 HTTPS 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 基础配置与路径
# ===========================
RESULT_FILE = "scan_results.json"   
DB_FILE = "ip_database.json"        
CRAWLER_FILE = "crawler_pool.json"  
NICHE_FILE = "niche_pool.json"      
CONFIG_FILE = "app_config.json"     

QUICK_SEEDS = ["104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1"]
GOLDEN_SUBNETS = ["104.28.0.0/16", "172.67.128.0/17", "104.21.0.0/16", "172.64.0.0/13"]

# ===========================
# 2. 稳健的 IO 逻辑 (防黑屏关键)
# ===========================

def safe_save_json(path, data):
    """原子化写入：先写临时文件再替换，防止读取冲突"""
    try:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        print(f"写入失败: {e}")

def safe_load_json(path, default):
    """稳健读取：防止读取到损坏或空文件"""
    if not os.path.exists(path): return default
    try:
        with open(path, "r", encoding='utf-8') as f:
            return json.load(f)
    except: return default

# ===========================
# 3. 后台进化逻辑 (独立线程)
# ===========================

def get_geo_info(ip):
    """标记国家与地区"""
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,countryCode", timeout=1.0).json()
        if r.get("status") == "success":
            return {"country": r.get("country"), "cc": r.get("countryCode")}
    except: pass
    return {"country": "Unknown", "cc": "??"}

def run_background_task():
    """后台独立线程：负责所有的爬取和测试"""
    while True:
        try:
            # 1. 读取配置与历史基因库
            cfg = safe_load_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "port": 443})
            db_data = safe_load_json(DB_FILE, {})
            
            # 2. 爬取新样本 (GitHub & 冷门段位生成)
            # ... 此处包含 20 个上限的 Pool 填充逻辑 ...
            
            # 3. 执行优胜劣汰测试
            # 并发 Ping 和 测速 (四川电信倾向)
            # 如果新 IP 分数更高，则更新 db_data
            
            # 4. 产生前端快照
            # 格式化数据并存入 RESULT_FILE
            
            # 5. 保存基因库并进入 10 秒轮询休眠
            safe_save_json(DB_FILE, db_data)
        except Exception as e:
            print(f"后台错误: {e}")
        
        time.sleep(10)

# ===========================
# 4. 前端渲染逻辑 (零阻塞)
# ===========================

st.set_page_config(page_title="VLESS 猎手进化版", page_icon="🧬", layout="wide")
st.markdown("<style>.stApp { background-color: #0e1117; }</style>", unsafe_allow_html=True)

# 启动单例后台线程
if "evolution_thread" not in st.session_state:
    thread = threading.Thread(target=run_background_task, daemon=True)
    thread.start()
    st.session_state.evolution_thread = True

st.title("🧬 Cloudflare 猎手进化版")

# 侧边栏配置
with st.sidebar:
    st.header("🛠️ 配置控制台")
    conf = safe_load_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "port": 443})
    m_list = ["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线", "🎬 流媒体解锁专线"]
    new_m = st.radio("优选策略", m_list, index=m_list.index(conf['mode']) if conf['mode'] in m_list else 0)
    if st.button("💾 保存配置"):
        safe_save_json(CONFIG_FILE, {"mode": new_m, "port": 443})
        st.toast(f"切换策略: {new_m}", icon="⚡")
        if os.path.exists(RESULT_FILE): os.remove(RESULT_FILE)
        time.sleep(0.5); st.rerun()

# 加载实时快照
res = safe_load_json(RESULT_FILE, None)

if res:
    # 渲染冠军卡片、来源分类标记、国家标记和排行表
    w = res['winner']
    st.markdown(f"### 🏆 最强 IP: `{w['ip']}` | 📍 {w['cc']} {w['country']}")
    
    # ... 详细表格渲染代码 (df = pd.DataFrame(res['table'])) ...
    
    st.caption(f"上次进化: {res['last_run']} | 基因库持续演化中...")
    time.sleep(5); st.rerun()
else:
    # 骨架屏提示，防止黑屏
    st.info("🚀 后台线程已启动。正在极速扫描四川电信优选网段，请稍候 10 秒...")
    time.sleep(3); st.rerun()
