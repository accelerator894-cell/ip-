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
# 1. 基础配置与全量常量
# ===========================
st.set_page_config(page_title="VLESS 猎手进化版", page_icon="🧬", layout="wide")

RESULT_FILE = "scan_results.json"   
DB_FILE = "ip_database.json"        
CRAWLER_FILE = "crawler_pool.json"  
NICHE_FILE = "niche_pool.json"      
CONFIG_FILE = "app_config.json"     

QUICK_SEEDS = ["104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1"]
GOLDEN_SUBNETS = ["104.28.0.0/16", "172.67.128.0/17", "104.21.0.0/16", "172.64.0.0/13", "103.21.244.0/22"]

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    div[data-testid="stMetricValue"] { font-size: 22px; color: #00ffca; }
    div[data-testid="column"] { background-color: #1a1c24; border-radius: 8px; padding: 12px; border: 1px solid #2d2f3b; }
    .stDataFrame { border: 1px solid #2d2f3b; }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 核心类定义 (找回丢失的池管理逻辑)
# ===========================

class IPDatabase:
    """正式精英库：执行优胜劣汰替换逻辑"""
    def __init__(self, filepath):
        self.filepath = filepath
        self.lock = threading.Lock()
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding='utf-8') as f: return json.load(f)
            except: return {}
        return {}

    def update_ip(self, ip, stats):
        with self.lock:
            if stats['score'] < 30: return 
            if ip not in self.data or stats['score'] >= self.data[ip].get('score', 0):
                stats['created_at'] = self.data.get(ip, {}).get('created_at', stats['last_test'])
                self.data[ip] = stats
            else:
                self.data[ip]['last_test'] = stats['last_test']

    def save(self):
        with self.lock:
            tmp = self.filepath + ".tmp"
            with open(tmp, "w", encoding='utf-8') as f: json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.filepath)

    def get_top_ips(self, limit=15):
        valid = list(self.data.values())
        valid.sort(key=lambda x: x.get('score', 0), reverse=True)
        return valid[:limit]

class BasePool:
    def __init__(self, filepath, max_size=20):
        self.filepath, self.max_size = filepath, max_size
        self.lock = threading.Lock()
        self.ips = self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f: return json.load(f)
            except: return []
        return []

    def save(self):
        with self.lock:
            with open(self.filepath, "w") as f: json.dump(self.ips, f)

    def get_batch(self, size=8):
        with self.lock: return self.ips[:size]

    def remove_batch(self, tested):
        with self.lock:
            self.ips = [i for i in self.ips if i not in tested]
            self.save()

class CrawlerPool(BasePool):
    def fill(self):
        if len(self.ips) >= self.max_size: return
        try:
            r = requests.get("https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt", timeout=3)
            found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
            random.shuffle(found)
            with self.lock:
                for ip in found:
                    if len(self.ips) >= self.max_size: break
                    if ip not in self.ips: self.ips.append(ip)
            self.save()
        except: pass

class NichePool(BasePool):
    def fill(self):
        if len(self.ips) >= self.max_size: return
        new_ips = []
        for _ in range(self.max_size - len(self.ips) + 5):
            try:
                net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
                new_ips.append(str(net.network_address + random.randint(1, net.num_addresses - 2)))
            except: pass
        with self.lock:
            for ip in new_ips:
                if len(self.ips) >= self.max_size: break
                if ip not in self.ips: self.ips.append(ip)
        self.save()

# ===========================
# 3. 找回丢失的测试函数
# ===========================

def get_geo_info(ip):
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,isp", timeout=1.0).json()
        if r.get("status") == "success":
            return {"country": r.get("country"), "cc": r.get("countryCode"), "isp": r.get("isp")}
    except: pass
    return {"country": "Unknown", "cc": "UN", "isp": "Unknown"}

def ping_test(ip, port=443, count=4):
    lats = []
    for _ in range(count):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.5)
            t1 = time.perf_counter(); s.connect((ip, port)); s.close()
            lats.append((time.perf_counter()-t1)*1000)
        except: pass
    if not lats: return {"avg": 999, "loss": 100}
    return {"avg": int(statistics.mean(lats)), "loss": int(((count-len(lats))/count)*100)}

def calculate_score(mode, p, speed, geo):
    score = 100.0 - p['loss'] * 5 - (p['avg'] - 150) / 3 if p['avg'] > 150 else 100.0 - p['loss'] * 5
    score += min(speed * 5, 40)
    if mode == "🤖 GPT 独享专线" and geo['cc'] in ['CN', 'HK']: return 0
    return max(0, round(score, 1))

# ===========================
# 4. 后台进化线程 (全功能逻辑)
# ===========================

def background_worker():
    db = IPDatabase(DB_FILE)
    cp, np = CrawlerPool(CRAWLER_FILE), NichePool(NICHE_FILE)
    
    while True:
        try:
            cfg = get_config()
            targets = [{"ip": i, "src": "⚡ 种子"} for i in QUICK_SEEDS]
            targets += [{"ip": i['ip'], "src": "📂 历史"} for i in db.get_top_ips(12)]
            
            cp.fill(); np.fill()
            c_ips = cp.get_batch(); n_ips = np.get_batch()
            targets += [{"ip": i, "src": "🕷️ 爬虫"} for i in c_ips]
            targets += [{"ip": i, "src": "💎 冷门"} for i in n_ips]
            
            unique_targets = {v['ip']:v for v in targets}.values()
            results, tested_c, tested_n = [], [], []

            with concurrent.futures.ThreadPoolExecutor(max_workers=25) as ex:
                def task(t):
                    ip = t['ip']
                    p = ping_test(ip, cfg['port'])
                    if p['loss'] > 40: return None
                    
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes=150000", headers={"Host": "speed.cloudflare.com"}, timeout=2)
                        speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    geo = get_geo_info(ip)
                    score = calculate_score(cfg['mode'], p, speed, geo)
                    
                    if t['src'] == "🕷️ 爬虫": tested_c.append(ip)
                    if t['src'] == "💎 冷门": tested_n.append(ip)
                    
                    res = {"ip": ip, "score": score, "avg": p['avg'], "speed": round(speed, 2), 
                           "src": t['src'], "cc": geo['cc'], "country": geo['country'], "last_test": datetime.now().strftime("%H:%M:%S")}
                    db.update_ip(ip, res)
                    return res

                futs = [ex.submit(task, t) for t in unique_targets]
                for f in concurrent.futures.as_completed(futs):
                    r = f.result()
                    if r: results.append(r)
            
            cp.remove_batch(tested_c); np.remove_batch(tested_n); db.save()
            
            if results:
                results.sort(key=lambda x: x['score'], reverse=True)
                with open(RESULT_FILE + ".tmp", "w", encoding='utf-8') as f:
                    json.dump({"last_run": datetime.now().strftime("%H:%M:%S"), "mode": cfg['mode'], 
                               "winner": results[0], "table": results[:40], "std_pool": len(cp.ips), "niche_pool": len(np.ips)}, f, ensure_ascii=False)
                os.replace(RESULT_FILE + ".tmp", RESULT_FILE)

        except: pass
        time.sleep(10)

def get_config():
    try:
        with open(CONFIG_FILE, "r") as f: return json.load(f)
    except: return {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443}

if "bg_thread" not in st.session_state:
    threading.Thread(target=background_worker, daemon=True).start()
    st.session_state.bg_thread = True

# ===========================
# 5. 前端渲染 (分类标记与国家)
# ===========================

def safe_load():
    if not os.path.exists(RESULT_FILE): return None
    try:
        with open(RESULT_FILE, "r", encoding='utf-8') as f: return json.load(f)
    except: return None

res_data = safe_load()

with st.sidebar:
    st.header("🛠️ 配置控制台")
    cfg = get_config()
    m_list = ["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线", "🎬 流媒体解锁专线"]
    new_m = st.radio("优选策略", m_list, index=m_list.index(cfg['mode']) if cfg['mode'] in m_list else 0)
    if st.button("💾 保存配置"):
        with open(CONFIG_FILE, "w") as f: json.dump({"mode": new_m, "host": cfg['host'], "port": cfg['port']}, f)
        st.toast(f"切换至: {new_m}", icon="🔀")
        if os.path.exists(RESULT_FILE): os.remove(RESULT_FILE)
        time.sleep(0.5); st.rerun()

if res_data:
    w = res_data['winner']
    st.title("🧬 Cloudflare 猎手进化版")
    st.markdown(f"### 🏆 当前最强: `{w['ip']}` | 📍 {w['cc']} {w['country']}")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("进化得分", w['score'])
    c2.metric("延迟 (ms)", w['avg'])
    c3.metric("速度 (MB/s)", w['speed'])
    c4.metric("来源类型", w['src'])

    st.divider()
    st.subheader(f"🧬 基因库 (策略: {res_data['mode']})")
    
    col1, col2 = st.columns(2)
    col1.info(f"🕷️ 爬虫池: {res_data.get('std_pool', 0)} / 20")
    col2.success(f"💎 冷门池: {res_data.get('niche_pool', 0)} / 20")

    df = pd.DataFrame(res_data['table'])
    df['分类来源'] = df['src']
    df['地理位置'] = df['cc'] + " " + df['country']
    
    st.dataframe(
        df,
        column_order=("score", "分类来源", "ip", "地理位置", "avg", "speed", "last_test"),
        column_config={
            "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=100),
            "speed": st.column_config.NumberColumn("速度 MB/s"),
            "avg": st.column_config.NumberColumn("延迟 ms"),
        },
        use_container_width=True, hide_index=True
    )
    st.caption(f"最后进化时间: {res_data['last_run']} | 系统每 10 秒自动演化优胜劣汰")
    time.sleep(5); st.rerun()
else:
    st.info("🚀 正在极速连接四川电信骨干网并加载基因库... (约需 5-10 秒)")
    time.sleep(2); st.rerun()
