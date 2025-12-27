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
# 1. 全局配置与常量
# ===========================
st.set_page_config(page_title="VLESS 猎手进化版", page_icon="🧬", layout="wide")

RESULT_FILE = "scan_results.json"   
DB_FILE = "ip_database.json"        
CRAWLER_FILE = "crawler_pool.json"  
NICHE_FILE = "niche_pool.json"      
CONFIG_FILE = "app_config.json"     

# 极速启动种子
QUICK_SEEDS = [
    "104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1", 
    "104.16.16.16", "104.24.24.24", "172.64.0.1", "104.18.18.18"
]

# 💎 黄金冷门段位
GOLDEN_SUBNETS = [
    "104.28.0.0/16", "172.67.128.0/17", "104.21.0.0/16", 
    "172.64.0.0/13", "103.21.244.0/22", "103.22.200.0/22",
    "103.31.4.0/22", "141.101.64.0/18", "108.162.192.0/18"
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
# 2. 核心类定义 (保持原样，略有精简)
# ===========================

class IPDatabase:
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
            if stats['score'] < 30: return 
            if ip not in self.data:
                self.data[ip] = stats
            else:
                old = self.data[ip].get('score', 0)
                if stats['score'] >= old:
                    stats['created_at'] = self.data[ip].get('created_at', stats['last_test'])
                    self.data[ip] = stats
                else:
                    self.data[ip]['last_test'] = stats['last_test']
    
    def get_top_ips(self, limit=20):
        valid = list(self.data.values())
        valid.sort(key=lambda x: x.get('score', 0), reverse=True)
        return valid[:limit]

class BasePool:
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

    def get_batch(self, batch_size=5):
        with self.lock: return self.ips[:batch_size]

    def remove_batch(self, tested_ips):
        with self.lock:
            self.ips = [ip for ip in self.ips if ip not in tested_ips]
            self.save()

class CrawlerPool(BasePool):
    def fill_pool(self):
        if len(self.ips) >= self.max_size: return
        try:
            # 使用更快的 CDN 地址或备用源
            url = "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"
            txt = requests.get(url, timeout=3).text
            found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', txt)
            random.shuffle(found)
            with self.lock:
                for ip in found:
                    if len(self.ips) >= self.max_size: break
                    if ip not in self.ips: self.ips.append(ip)
            self.save()
        except: pass

class NichePool(BasePool):
    def fill_pool(self):
        if len(self.ips) >= self.max_size: return
        new_ips = []
        target_count = self.max_size - len(self.ips)
        for _ in range(target_count + 5):
            subnet_str = random.choice(GOLDEN_SUBNETS)
            try:
                network = ipaddress.ip_network(subnet_str, strict=False)
                random_int = random.randint(1, network.num_addresses - 2)
                generated_ip = str(network.network_address + random_int)
                new_ips.append(generated_ip)
            except: pass
        with self.lock:
            for ip in new_ips:
                if len(self.ips) >= self.max_size: break
                if ip not in self.ips: self.ips.append(ip)
        self.save()

# ===========================
# 3. 优化后的测试逻辑
# ===========================

def get_config():
    default = {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443}
    try:
        with open(CONFIG_FILE, "r", encoding='utf-8') as f: return {**default, **json.load(f)}
    except: return default

def save_config(new_conf):
    curr = get_config()
    curr.update(new_conf)
    with open(CONFIG_FILE, "w", encoding='utf-8') as f: json.dump(curr, f, indent=2, ensure_ascii=False)

def get_geo_info(ip):
    try:
        # 缩短 API 超时时间，因为这不是最关键的
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode,isp,hosting", timeout=1.0).json()
        cc = r.get("countryCode", "US")
        return {"cc": cc, "gpt": "✅" if cc not in ['CN','HK','RU','IR','KP'] else "❌", "is_native": not r.get("hosting", True)}
    except: return {"cc": "Unk", "gpt": "❓", "is_native": False}

def quick_socket_check(ip, port=443):
    """🔥 极速预检：只尝试连接一次，超时极短。通了再做后续测试。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.4) # 400ms 握手超时，超时说明线路不行
        s.connect((ip, port))
        s.close()
        return True
    except:
        return False

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
    if p0['loss'] == 0 and p0['jitter'] < 10: tags.append("🎮 稳")
    if p0['avg'] < 140: tags.append("⚡ 快")
    if geo['is_native']: tags.append("🎬 原生")
    if geo['gpt'] == "✅": tags.append("🤖 GPT")
    tags.append(geo['cc'])
    return tags

# ===========================
# 4. 后台进化线程 (异步流水线优化)
# ===========================

def update_frontend_json(mode, winner, table, std_pool_len, niche_pool_len):
    """辅助函数：安全写入前端文件"""
    try:
        state = {
            "last_run": datetime.now().strftime("%H:%M:%S"),
            "mode": mode,
            "winner": winner,
            "table": table,
            "std_pool": std_pool_len,
            "niche_pool": niche_pool_len
        }
        tmp = RESULT_FILE + ".tmp"
        with open(tmp, "w", encoding='utf-8') as f: json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, RESULT_FILE)
    except: pass

def background_worker():
    db = IPDatabase(DB_FILE)
    std_pool = CrawlerPool(CRAWLER_FILE, max_size=20)
    niche_pool = NichePool(NICHE_FILE, max_size=20)
    
    while True:
        try:
            cfg = get_config()
            mode = cfg.get("mode", "☀️ 正常使用排位")
            
            scan_targets = []
            
            # 1. 种子 (高优先级)
            scan_targets.extend([{"ip": ip, "src": "⚡ 种子"} for ip in QUICK_SEEDS])
            
            # 2. 历史精英
            top_db = db.get_top_ips(12)
            for item in top_db:
                scan_targets.append({"ip": item['ip'], "src": "📂 历史"})
            
            # 3. 填充爬虫池
            # 使用 threading 避免爬虫动作卡住测试
            threading.Thread(target=std_pool.fill_pool).start()
            threading.Thread(target=niche_pool.fill_pool).start()
            
            # 这里的数量可以适当增加，因为我们有快速预检了
            for ip in std_pool.get_batch(8):
                scan_targets.append({"ip": ip, "src": "🕷️ 爬虫"})
            for ip in niche_pool.get_batch(8):
                scan_targets.append({"ip": ip, "src": "💎 冷门"})
            
            unique_targets = {v['ip']:v for v in scan_targets}.values()
            
            # --- 并发测试流水线 ---
            current_results = []
            tested_ips_std = [] 
            tested_ips_niche = []
            
            # 动态调整测试负载：如果是第一次运行，减少下载量以加快出图速度
            is_warmup = not os.path.exists(RESULT_FILE)
            download_bytes = 50000 if is_warmup else 200000 # 50KB vs 200KB
            
            workers = 30 # 加大并发，反正有预检
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                def task(target):
                    ip = target['ip']
                    port = cfg.get('port', 443)
                    
                    # 🔥 阶段1: 极速预检 (如果不通，直接 Pass)
                    if not quick_socket_check(ip, port):
                        # 记录失败也要清理池子
                        if target['src'] == "🕷️ 爬虫": tested_ips_std.append(ip)
                        if target['src'] == "💎 冷门": tested_ips_niche.append(ip)
                        return None
                    
                    # 阶段2: 详细 Ping
                    p0 = ping0_test(ip, port)
                    if p0['loss'] > 40: return None 
                    
                    # 阶段3: 测速 (动态大小)
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        url = f"http://{ip}/__down?bytes={download_bytes}"
                        r = requests.get(url, headers={"Host": "speed.cloudflare.com"}, timeout=2.0) # 缩短超时
                        if r.status_code == 200:
                            # 还原为 MB/s (近似值，因为只下了小包)
                            speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    geo = get_geo_info(ip)
                    bonus = 5 if target['src'] == "💎 冷门" else 0
                    score = calculate_score(mode, p0, speed, geo) + bonus
                    
                    if target['src'] == "🕷️ 爬虫": tested_ips_std.append(ip)
                    if target['src'] == "💎 冷门": tested_ips_niche.append(ip)

                    if score <= 10: return None
                    
                    return {
                        "ip": ip, "score": score, "loss": p0['loss'], "avg": p0['avg'],
                        "speed": round(speed, 2), "tags": classify_ip(p0, speed, geo),
                        "src": target['src'], "last_test": datetime.now().strftime("%H:%M:%S")
                    }

                futs = [ex.submit(task, t) for t in unique_targets]
                
                # 🔥 实时反馈循环：只要有一个结果出来，就尝试更新前端，不等全部跑完
                for f in concurrent.futures.as_completed(futs):
                    r = f.result()
                    if r: 
                        current_results.append(r)
                        db.update_ip(r['ip'], r)
                        
                        # 排序并提取冠军
                        temp_results = sorted(current_results, key=lambda x: x['score'], reverse=True)
                        winner = temp_results[0]
                        
                        # 立即刷新前端文件 (让用户马上看到结果)
                        update_frontend_json(mode, winner, temp_results[:50], len(std_pool.ips), len(niche_pool.ips))

            # --- 本轮结束后的清理与保存 ---
            if tested_ips_std: std_pool.remove_batch(tested_ips_std)
            if tested_ips_niche: niche_pool.remove_batch(tested_ips_niche)
            db.save()

        except Exception as e: print(f"Err: {e}")
        time.sleep(5) 

if "bg_thread" not in st.session_state:
    t = threading.Thread(target=background_worker, daemon=True)
    t.start()
    st.session_state.bg_thread = True

# ===========================
# 5. 前端 UI (带实时刷新说明)
# ===========================
with st.sidebar:
    st.header("🛠️ 配置控制台")
    cfg = get_config()
    modes = ["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线", "🎬 流媒体解锁专线"]
    curr = cfg.get("mode", modes[0])
    idx = modes.index(curr) if curr in modes else 0
    new_mode = st.radio("优选策略", modes, index=idx)
    
    st.markdown("---")
    with st.expander("⚙️ 扫描参数"):
        new_host = st.text_input("伪装域名", value=cfg.get("host", "speed.cloudflare.com"))
        new_port = st.number_input("端口", value=cfg.get("port", 443))
        
    if st.button("💾 保存配置"):
        save_config({"mode": new_mode, "host": new_host, "port": new_port})
        st.toast(f"✅ 策略更新: {new_mode}", icon="🔀")
        if os.path.exists(RESULT_FILE): os.remove(RESULT_FILE)
        time.sleep(0.5); st.rerun()

st.title("🧬 Cloudflare 猎手进化版 (极速启动)")

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
        st.caption(f"特性: {winner['tags']} | 来源: {winner['src']}")
        
        st.divider()
        st.subheader(f"🧬 基因库 (策略: {data['mode']})")
        
        col_p1, col_p2 = st.columns(2)
        col_p1.info(f"🕷️ 普通池: {data.get('std_pool', 0)} / 20")
        col_p2.success(f"💎 冷门池: {data.get('niche_pool', 0)} / 20")
        
        df = pd.DataFrame(data['table'])
        if 'tags' in df.columns: df['tags'] = df['tags'].apply(lambda x: " ".join(x) if isinstance(x, list) else str(x))
        
        st.dataframe(
            df,
            column_order=("score", "src", "ip", "avg", "loss", "speed", "tags"),
            column_config={
                "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=100, format="%.0f"),
                "speed": st.column_config.NumberColumn("速度", format="%.2f MB"),
                "src": st.column_config.TextColumn("来源"),
            },
            use_container_width=True, hide_index=True
        )
    except: 
        # 即使读失败也不要卡住，稍等重试
        time.sleep(0.5); st.rerun()
else:
    # 极简启动画面
    st.info("🚀 正在极速连接中... (通常只需 1-3 秒)")
    time.sleep(1); st.rerun()

# 保持自动刷新，但频率略微降低以减轻前端负担
time.sleep(3); st.rerun()
