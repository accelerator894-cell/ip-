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
from datetime import datetime
import urllib3

# 禁用 HTTPS 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 全局配置与常量
# ===========================
st.set_page_config(page_title="VLESS 智能进化版", page_icon="🧬", layout="wide")

RESULT_FILE = "scan_results.json"   # 前端展示
DB_FILE = "ip_database.json"        # 正式精英库 (老兵)
CRAWLER_FILE = "crawler_pool.json"  # 爬虫缓冲池 (新兵训练营)
CONFIG_FILE = "app_config.json"     # 配置

# 极速启动种子
QUICK_SEEDS = [
    "104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1", 
    "104.16.16.16", "104.24.24.24", "172.64.0.1", "104.18.18.18"
]

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    div[data-testid="stMetricValue"] { font-size: 24px; color: #00ffca; }
    div[data-testid="column"] { background-color: #1a1c24; border: 1px solid #2d2f3b; border-radius: 8px; padding: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
    .stDataFrame { border: 1px solid #2d2f3b; border-radius: 5px; }
    div.stButton > button { width: 100%; border-radius: 5px; background-color: #262730; color: white; border: 1px solid #4e505e; }
    div.stButton > button:hover { border-color: #00ffca; color: #00ffca; }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 核心类定义
# ===========================

class IPDatabase:
    """正式精英数据库 (只存最好的)"""
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

    def save(self):
        with self.lock:
            try:
                tmp = self.filepath + ".tmp"
                with open(tmp, "w", encoding='utf-8') as f: 
                    json.dump(self.data, f, indent=2, ensure_ascii=False)
                os.replace(tmp, self.filepath)
            except: pass

    def update_ip(self, ip, stats):
        with self.lock:
            # 只有分数合格才进入正式库 (例如 > 40分)
            if stats['score'] < 40: return 
            
            if ip not in self.data:
                self.data[ip] = stats
            else:
                # 优胜劣汰：只有新成绩更好才更新核心数据
                old = self.data[ip].get('score', 0)
                if stats['score'] >= old:
                    stats['created_at'] = self.data[ip].get('created_at', stats['last_test'])
                    self.data[ip] = stats
                else:
                    self.data[ip]['last_test'] = stats['last_test'] # 仅更新活跃时间

    def get_top_ips(self, limit=20):
        valid = list(self.data.values())
        valid.sort(key=lambda x: x.get('score', 0), reverse=True)
        return valid[:limit]

class CrawlerPool:
    """爬虫缓冲池 (新兵营)，最大存20个"""
    def __init__(self, filepath, max_size=20):
        self.filepath = filepath
        self.max_size = max_size
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

    def fill_pool(self):
        """如果池子没满，去公网抓取补充"""
        if len(self.ips) >= self.max_size: return
        try:
            url = "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"
            txt = requests.get(url, timeout=4).text
            found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', txt)
            
            # 随机打乱抓取结果
            random.shuffle(found)
            
            with self.lock:
                for ip in found:
                    if len(self.ips) >= self.max_size: break
                    if ip not in self.ips:
                        self.ips.append(ip)
            self.save()
        except: pass

    def get_batch(self, batch_size=5):
        """取出一批去送死(测试)"""
        with self.lock:
            # 取出前N个
            batch = self.ips[:batch_size]
            return batch

    def remove_batch(self, tested_ips):
        """测试完了，无论死活都从池子里踢出去"""
        with self.lock:
            self.ips = [ip for ip in self.ips if ip not in tested_ips]
            self.save()

# ===========================
# 3. 辅助函数
# ===========================

def get_config():
    default = {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443}
    try:
        with open(CONFIG_FILE, "r", encoding='utf-8') as f: return {**default, **json.load(f)}
    except: return default

def save_config(new_conf):
    curr = get_config()
    curr.update(new_conf)
    with open(CONFIG_FILE, "w", encoding='utf-8') as f: json.dump(curr, f, indent=2)

def get_geo_info(ip):
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode,isp,hosting", timeout=2).json()
        cc = r.get("countryCode", "US")
        return {"cc": cc, "gpt": "✅" if cc not in ['CN','HK','RU','IR','KP'] else "❌", "is_native": not r.get("hosting", True)}
    except: return {"cc": "Unk", "gpt": "❓", "is_native": False}

def ping0_test(ip, port=443, count=4):
    lats, success = [], 0
    for _ in range(count):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.6)
            t1 = time.perf_counter(); s.connect((ip, port)); s.close()
            lats.append((time.perf_counter()-t1)*1000); success += 1
        except: pass
    if not lats: return {"avg": 999, "jitter": 99, "loss": 100}
    return {"avg": int(statistics.mean(lats)), "jitter": int(statistics.stdev(lats)) if len(lats)>1 else 0, "loss": int(((count-success)/count)*100)}

def calculate_score(mode, p0, speed, geo):
    score = 100.0
    score -= p0['loss'] * 5 
    limit = 280 if mode == "🤖 GPT 独享专线" else (150 if mode == "⚡ 极速低延迟" else 200)
    if mode == "🤖 GPT 独享专线" and geo['gpt'] == "❌": return 0
    if p0['avg'] > limit: score -= (p0['avg'] - limit) / 3
    score -= p0['jitter'] * 1
    score += min(speed * 5, 40)
    if mode == "🎬 流媒体解锁专线" and not geo['is_native']: score -= 30
    return max(0, round(score, 1))

def classify_ip(p0, speed, geo):
    tags = []
    if p0['loss'] == 0 and p0['jitter'] < 10: tags.append("🎮 游戏/金融")
    if p0['avg'] < 140: tags.append("⚡ 极速")
    if geo['is_native']: tags.append("🎬 原生")
    if geo['gpt'] == "✅": tags.append("🤖 GPT")
    tags.append(geo['cc'])
    return tags

# ===========================
# 4. 后台进化线程 (Worker)
# ===========================

def background_worker():
    db = IPDatabase(DB_FILE)
    pool = CrawlerPool(CRAWLER_FILE, max_size=20) # 限制爬虫池最大20个
    
    while True:
        try:
            cfg = get_config()
            mode = cfg.get("mode", "☀️ 正常使用排位")
            
            scan_targets = []
            
            # 1. 种子选手 (永远保留)
            scan_targets.extend([{"ip": ip, "src": "⚡ 种子"} for ip in QUICK_SEEDS])
            
            # 2. 历史精英 (复查)
            top_db = db.get_top_ips(10)
            for item in top_db:
                scan_targets.append({"ip": item['ip'], "src": "📂 历史"})
            
            # 3. 爬虫池新兵 (关键修改)
            # 先尝试填满池子
            pool.fill_pool()
            # 从池子里拿出 5-8 个进行测试
            new_recruits = pool.get_batch(8) 
            for ip in new_recruits:
                scan_targets.append({"ip": ip, "src": "🕷️ 爬虫"})
            
            # 去重
            unique_targets = {v['ip']:v for v in scan_targets}.values()
            
            # --- 执行并发测试 ---
            current_results = []
            tested_pool_ips = [] # 记录哪些爬虫IP被测试了
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
                def task(target):
                    ip = target['ip']
                    port = cfg.get('port', 443)
                    
                    # 基础筛选
                    p0 = ping0_test(ip, port)
                    if p0['loss'] > 40: return None 
                    
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        url = f"http://{ip}/__down?bytes=200000"
                        r = requests.get(url, headers={"Host": "speed.cloudflare.com"}, timeout=3)
                        if r.status_code == 200:
                            speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    geo = get_geo_info(ip)
                    score = calculate_score(mode, p0, speed, geo)
                    
                    # 记录这个IP是来自爬虫的，方便后续从池子删除
                    if target['src'] == "🕷️ 爬虫":
                        tested_pool_ips.append(ip)

                    if score <= 10: return None
                    
                    return {
                        "ip": ip, "score": score, "loss": p0['loss'], "avg": p0['avg'],
                        "speed": round(speed, 2), "tags": classify_ip(p0, speed, geo),
                        "src": target['src'], "last_test": datetime.now().strftime("%H:%M:%S")
                    }

                futs = [ex.submit(task, t) for t in unique_targets]
                for f in concurrent.futures.as_completed(futs):
                    r = f.result()
                    if r: 
                        current_results.append(r)
                        # 🔥 晋升机制：只有优秀的才存入正式DB
                        db.update_ip(r['ip'], r)

            # --- 收尾工作 ---
            # 1. 从爬虫池中移除已测试的IP (无论好坏，腾出位置给下一批新IP)
            if tested_pool_ips:
                pool.remove_batch(tested_pool_ips)

            # 2. 保存结果供前端显示
            if current_results:
                db.save()
                current_results.sort(key=lambda x: x['score'], reverse=True)
                
                # 更新状态
                state = {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "mode": mode,
                    "winner": current_results[0],
                    "table": current_results[:50],
                    "pool_size": len(pool.ips) # 调试用：显示池子剩余数量
                }
                
                tmp = RESULT_FILE + ".tmp"
                with open(tmp, "w", encoding='utf-8') as f: json.dump(state, f, ensure_ascii=False)
                os.replace(tmp, RESULT_FILE)

        except Exception as e: print(f"Err: {e}")
        time.sleep(8) # 休息一下

if "bg_thread" not in st.session_state:
    t = threading.Thread(target=background_worker, daemon=True)
    t.start()
    st.session_state.bg_thread = True

# ===========================
# 5. 前端 UI
# ===========================
with st.sidebar:
    st.header("🛠️ 配置控制台")
    cfg = get_config()
    modes = ["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线", "🎬 流媒体解锁专线"]
    curr = cfg.get("mode", modes[0])
    idx = modes.index(curr) if curr in modes else 0
    new_mode = st.radio("优选策略", modes, index=idx)
    
    st.markdown("---")
    with st.expander("⚙️ 扫描参数设置"):
        new_host = st.text_input("伪装域名", value=cfg.get("host", "speed.cloudflare.com"))
        new_port = st.number_input("端口", value=cfg.get("port", 443))
        
    if st.button("💾 保存配置"):
        save_config({"mode": new_mode, "host": new_host, "port": new_port})
        st.toast(f"✅ 策略更新: {new_mode}", icon="🔀")
        if os.path.exists(RESULT_FILE): os.remove(RESULT_FILE)
        time.sleep(1); st.rerun()

st.title("🧬 Cloudflare 优选 IP 监控台")

if os.path.exists(RESULT_FILE):
    try:
        with open(RESULT_FILE, "r", encoding='utf-8') as f: data = json.load(f)
        winner = data['winner']
        
        st.markdown("### 🏆 当前最强 IP")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("IP 地址", winner['ip'])
        c2.metric("延迟", f"{winner['avg']} ms")
        c3.metric("速度", f"{winner['speed']} MB/s")
        c4.metric("得分", f"{winner['score']}")
        st.caption(f"特性: {winner['tags']}")
        
        st.divider()
        st.subheader(f"🧬 基因库 (策略: {data['mode']})")
        st.text(f"🕷️ 爬虫池存量: {data.get('pool_size', 0)} / 20 (自动补充中)")
        
        df = pd.DataFrame(data['table'])
        if 'tags' in df.columns: df['tags'] = df['tags'].apply(lambda x: " ".join(x) if isinstance(x, list) else str(x))
        
        st.dataframe(
            df,
            column_order=("score", "ip", "avg", "loss", "speed", "tags", "src"),
            column_config={
                "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=100, format="%.0f"),
                "speed": st.column_config.NumberColumn("速度", format="%.2f MB"),
            },
            use_container_width=True, hide_index=True
        )
    except: st.warning("🔄 数据刷新中..."); time.sleep(1); st.rerun()
else:
    st.info("🧬 初始化爬虫池并进行首轮测试..."); time.sleep(2); st.rerun()

time.sleep(5); st.rerun()
