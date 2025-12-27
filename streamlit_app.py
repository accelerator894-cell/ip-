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
st.set_page_config(page_title="VLESS 猎手进化版", page_icon="🧬", layout="wide")

RESULT_FILE = "scan_results.json"   
DB_FILE = "ip_database.json"        
CRAWLER_FILE = "crawler_pool.json"  
NICHE_FILE = "niche_pool.json"      
CONFIG_FILE = "app_config.json"     

QUICK_SEEDS = ["104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1"]
GOLDEN_SUBNETS = ["104.28.0.0/16", "172.67.128.0/17", "104.21.0.0/16", "172.64.0.0/13"]

# ===========================
# 2. 稳健的 IO 读写逻辑 (防止黑屏)
# ===========================

def safe_save_json(path, data):
    """使用临时文件中转写入，防止前端读取到空文件导致崩溃"""
    try:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        print(f"Save Error: {e}")

def safe_load_json(path, default):
    if not os.path.exists(path): return default
    try:
        with open(path, "r", encoding='utf-8') as f:
            return json.load(f)
    except: return default

# ===========================
# 3. 核心进化类
# ===========================

class EliteDatabase:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = safe_load_json(path, {})

    def update(self, ip, stats):
        """自动替换逻辑：分数更高则晋升"""
        with self.lock:
            if stats['score'] < 30: return
            if ip not in self.data or stats['score'] >= self.data[ip].get('score', 0):
                # 保留首次发现时间
                stats['created_at'] = self.data.get(ip, {}).get('created_at', stats['last_test'])
                self.data[ip] = stats
            else:
                self.data[ip]['last_test'] = stats['last_test']

    def get_top(self, limit=15):
        with self.lock:
            items = list(self.data.values())
            items.sort(key=lambda x: x.get('score', 0), reverse=True)
            return items[:limit]

# [此处省略 BasePool, CrawlerPool, NichePool 逻辑，保持 20 个上限限制]

# ===========================
# 4. 优化测试逻辑 (四川电信友好)
# ===========================

def get_geo(ip):
    """标记国家地区"""
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=country,countryCode", timeout=1.0).json()
        return {"country": r.get("country", "Unk"), "cc": r.get("countryCode", "??")}
    except: return {"country": "Unknown", "cc": "??"}

def fast_ping(ip, port=443):
    """极速预检，不通则直接丢弃"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.5)
        t1 = time.perf_counter(); s.connect((ip, port)); s.close()
        return int((time.perf_counter() - t1) * 1000)
    except: return None

# ===========================
# 5. 后台流水线 (流水线式更新)
# ===========================

def background_process():
    db = EliteDatabase(DB_FILE)
    # 模拟池初始化...
    while True:
        cfg = safe_load_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "port": 443})
        
        # 组装任务 (种子+历史+爬虫+冷门)
        # 执行测试并实时更新 DB
        
        # 将最新快照写入 RESULT_FILE，供前端渲染
        # 每 10 秒一轮循环
        time.sleep(10)

# ===========================
# 6. 前端展示 (防阻塞)
# ===========================

st.title("🧬 Cloudflare 猎手进化版")

# 侧边栏配置
with st.sidebar:
    st.header("🛠️ 配置控制台")
    conf = safe_load_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "port": 443})
    m_list = ["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线"]
    new_m = st.radio("优选策略", m_list, index=m_list.index(conf['mode']) if conf['mode'] in m_list else 0)
    if st.button("💾 保存并加速进化"):
        safe_save_json(CONFIG_FILE, {"mode": new_m, "port": 443})
        st.toast(f"已切换至: {new_m}", icon="⚡")
        time.sleep(1); st.rerun()

# 渲染实时数据
res = safe_load_json(RESULT_FILE, None)

if res:
    # 顶部冠军卡片
    w = res['winner']
    st.markdown(f"### 🏆 冠军 IP: `{w['ip']}` ({w['cc']} {w['country']})")
    
    # 详细列表与分类标记
    df = pd.DataFrame(res['table'])
    df['标记'] = df['src']
    df['地理'] = df['cc'] + " " + df['country']
    
    st.dataframe(df[['score', '标记', 'ip', '地理', 'avg', 'speed']], use_container_width=True, hide_index=True)
    st.caption(f"上次同步: {res['last_run']} | 数据库持续演化中...")
    
    time.sleep(5); st.rerun()
else:
    st.info("🚀 正在为您极速连接四川电信骨干网并加载本地基因库... (初次约需 10 秒)")
    time.sleep(3); st.rerun()
