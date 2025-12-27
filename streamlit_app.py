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

RESULT_FILE = "scan_results.json"
DB_FILE = "ip_database.json"
CONFIG_FILE = "app_config.json"

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
# 2. 核心类与辅助函数
# ===========================

class IPDatabase:
    def __init__(self, filepath):
        self.filepath = filepath
        self.lock = threading.Lock()
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding='utf-8') as f: 
                    return json.load(f)
            except: return {}
        return {}

    def save(self):
        with self.lock:
            try:
                tmp_file = self.filepath + ".tmp"
                with open(tmp_file, "w", encoding='utf-8') as f: 
                    json.dump(self.data, f, indent=2, ensure_ascii=False)
                os.replace(tmp_file, self.filepath)
            except Exception as e:
                print(f"DB Save Error: {e}")

    def update_ip(self, ip, stats):
        with self.lock:
            if ip not in self.data:
                self.data[ip] = stats
            else:
                old_score = self.data[ip].get('score', 0)
                stats['created_at'] = self.data[ip].get('created_at', stats['last_test'])
                if stats['score'] >= old_score:
                    self.data[ip] = stats
                else:
                    self.data[ip]['last_test'] = stats['last_test']

    def get_top_ips(self, limit=20):
        valid_ips = list(self.data.values())
        valid_ips.sort(key=lambda x: x.get('score', 0), reverse=True)
        return valid_ips[:limit]

def get_config():
    default_conf = {
        "mode": "☀️ 正常使用排位",
        "host": "speed.cloudflare.com",
        "port": 443
    }
    try:
        with open(CONFIG_FILE, "r", encoding='utf-8') as f:
            return {**default_conf, **json.load(f)}
    except:
        return default_conf

def save_config(new_conf):
    current = get_config()
    current.update(new_conf)
    with open(CONFIG_FILE, "w", encoding='utf-8') as f:
        json.dump(current, f, indent=2, ensure_ascii=False)

def get_geo_info(ip):
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,isp,hosting"
        r = requests.get(url, timeout=2).json()
        cc = r.get("countryCode", "US")
        is_native = not r.get("hosting", True)
        gpt = "✅" if cc not in ['CN', 'HK', 'RU', 'IR', 'KP'] else "❌"
        return {"cc": cc, "isp": r.get("isp", ""), "gpt": gpt, "is_native": is_native}
    except: 
        return {"cc": "Unk", "isp": "", "gpt": "❓", "is_native": False}

def ping0_test(ip, port=443, count=4):
    lats, success = [], 0
    for _ in range(count):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.8)
            t1 = time.perf_counter()
            s.connect((ip, port))
            s.close()
            lats.append((time.perf_counter()-t1)*1000)
            success += 1
        except: pass
    
    if not lats: return {"avg": 999, "jitter": 99, "loss": 100}
    avg = int(statistics.mean(lats))
    jitter = int(statistics.stdev(lats)) if len(lats) > 1 else 0
    loss = int(((count-success)/count)*100)
    return {"avg": avg, "jitter": jitter, "loss": loss}

def calculate_score(mode, p0, speed, geo):
    score = 100.0
    score -= p0['loss'] * 5 
    
    if mode == "🤖 GPT 独享专线":
        if geo['gpt'] == "❌": return 0
        limit = 280
    elif mode == "⚡ 极速低延迟":
        limit = 150
    else:
        limit = 200 
        
    if p0['avg'] > limit: score -= (p0['avg'] - limit) / 3
    score -= p0['jitter'] * 1
    score += min(speed * 5, 40)
    
    if mode == "🎬 流媒体解锁专线" and not geo['is_native']:
        score -= 30
        
    return max(0, round(score, 1))

def classify_ip(p0, speed, geo):
    tags = []
    if p0['loss'] == 0 and p0['jitter'] < 10: tags.append("🎮 游戏/金融")
    if p0['avg'] < 140: tags.append("⚡ 极速")
    if geo['is_native']: tags.append("🎬 原生解锁")
    if geo['gpt'] == "✅": tags.append("🤖 GPT")
    region_map = {'HK': '🇭🇰', 'JP': '🇯🇵', 'SG': '🇸🇬', 'US': '🇺🇸', 'KR': '🇰🇷', 'TW': '🇹🇼'}
    flag = region_map.get(geo['cc'], f"🏳️ {geo['cc']}")
    tags.append(flag)
    return tags

# ===========================
# 3. 后台进化线程
# ===========================

def background_worker():
    db = IPDatabase(DB_FILE)
    first_run = True
    
    while True:
        try:
            cfg = get_config()
            mode = cfg.get("mode", "☀️ 正常使用排位")
            
            scan_targets = []
            scan_targets.extend([{"ip": ip, "src": "⚡ 种子"} for ip in QUICK_SEEDS])
            
            top_db = db.get_top_ips(15)
            for item in top_db:
                scan_targets.append({"ip": item['ip'], "src": "📂 历史"})
                
            if not first_run or len(top_db) < 5:
                try:
                    url = "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"
                    txt = requests.get(url, timeout=3).text
                    fresh_ips = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', txt)
                    for ip in random.sample(fresh_ips, min(len(fresh_ips), 25)):
                        scan_targets.append({"ip": ip, "src": "🕷️ 爬虫"})
                except: pass

            first_run = False
            unique_targets = {v['ip']:v for v in scan_targets}.values()

            current_results = []
            workers = 20
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                def task(target):
                    ip = target['ip']
                    port = cfg.get('port', 443)
                    
                    p0 = ping0_test(ip, port)
                    if p0['loss'] > 40: return None
                    
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        url = f"http://{ip}/__down?bytes=200000"
                        r = requests.get(url, headers={"Host": "speed.cloudflare.com"}, timeout=3)
                        dur = time.perf_counter() - st_t
                        if r.status_code == 200:
                            speed = (len(r.content)/1024/1024) / dur
                    except: pass
                    
                    geo = get_geo_info(ip)
                    score = calculate_score(mode, p0, speed, geo)
                    if score <= 10: return None
                    
                    tags = classify_ip(p0, speed, geo)
                    
                    stats = {
                        "ip": ip, "score": score, "loss": p0['loss'], "avg": p0['avg'],
                        "speed": round(speed, 2), "tags": tags, "src": target['src'],
                        "last_test": datetime.now().strftime("%H:%M:%S"),
                        "gpt": geo['gpt'], "cc": geo['cc']
                    }
                    return stats

                futs = [ex.submit(task, t) for t in unique_targets]
                for f in concurrent.futures.as_completed(futs):
                    r = f.result()
                    if r: 
                        current_results.append(r)
                        db.update_ip(r['ip'], r)

            if current_results:
                db.save()
                current_results.sort(key=lambda x: x['score'], reverse=True)
                winner = current_results[0]
                
                # 注意：这里不再生成链接
                state = {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "mode": mode,
                    "winner": winner,
                    "table": current_results[:50]
                }
                
                tmp_file = RESULT_FILE + ".tmp"
                with open(tmp_file, "w", encoding='utf-8') as f: 
                    json.dump(state, f, ensure_ascii=False)
                os.replace(tmp_file, RESULT_FILE)

        except Exception as e:
            print(f"Loop Error: {e}")
        time.sleep(10)

if "bg_thread" not in st.session_state:
    t = threading.Thread(target=background_worker, daemon=True)
    t.start()
    st.session_state.bg_thread = True

# ===========================
# 4. 前端 UI 展示
# ===========================

with st.sidebar:
    st.header("🛠️ 配置控制台")
    
    cfg = get_config()
    
    # 模式选择
    modes = ["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线", "🎬 流媒体解锁专线"]
    curr_mode = cfg.get("mode", modes[0])
    try: idx = modes.index(curr_mode)
    except: idx = 0
    new_mode = st.radio("优选策略", modes, index=idx)
    
    st.markdown("---")
    
    # 扫描参数 (不再需要 UUID)
    with st.expander("⚙️ 扫描参数设置", expanded=False):
        new_host = st.text_input("伪装域名 (Host)", value=cfg.get("host", "speed.cloudflare.com"))
        new_port = st.number_input("端口 (Port)", value=cfg.get("port", 443))
        
    if st.button("💾 保存配置并重启进化"):
        save_config({
            "mode": new_mode, 
            "host": new_host,
            "port": new_port
        })
        
        # 🔥 这里增加了明显的切换提示 🔥
        if new_mode != curr_mode:
            st.toast(f"✅ 策略已切换为：{new_mode}", icon="🔀")
        else:
            st.toast("✅ 配置已保存，正在重新扫描...", icon="💾")
            
        if os.path.exists(RESULT_FILE): os.remove(RESULT_FILE)
        time.sleep(1.5)
        st.rerun()
        
    st.info("ℹ️ 后台正在自动从互联网和历史数据库中寻找最佳 IP，无需人工干预。")

st.title("🧬 Cloudflare 优选 IP 监控台")

if os.path.exists(RESULT_FILE):
    try:
        with open(RESULT_FILE, "r", encoding='utf-8') as f: 
            data = json.load(f)
            
        winner = data['winner']
        
        # 1. 冠军 IP 展示区
        st.markdown("### 🏆 当前最强 IP")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("IP 地址", winner['ip'], delta="Top 1")
        c2.metric("延迟 (Ping)", f"{winner['avg']} ms", delta_color="inverse")
        c3.metric("下载速度", f"{winner['speed']} MB/s")
        c4.metric("进化得分", f"{winner['score']}")
        
        st.markdown("**特性标签:** " + " ".join([f"`{t}`" for t in winner['tags']]))
        st.divider()
        
        # 2. 详细列表区
        st.subheader(f"🧬 基因库排行 (策略: {data['mode']})")
        
        df = pd.DataFrame(data['table'])
        if 'tags' in df.columns:
            df['tags'] = df['tags'].apply(lambda x: " ".join(x) if isinstance(x, list) else str(x))
            
        st.dataframe(
            df,
            column_order=("score", "ip", "avg", "loss", "speed", "tags", "src", "last_test"),
            column_config={
                "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=100, format="%.0f"),
                "ip": "IP 地址",
                "avg": st.column_config.NumberColumn("延迟", format="%d ms"),
                "loss": st.column_config.NumberColumn("丢包", format="%d%%"),
                "speed": st.column_config.NumberColumn("速度", format="%.2f MB/s"),
                "tags": "特性标签",
                "src": "来源",
                "last_test": "检测时间"
            },
            use_container_width=True,
            hide_index=True
        )
        
        st.caption(f"上次更新: {data['last_run']} | 数据库持续自动进化中...")
        
    except Exception:
        st.warning("🔄 数据同步中...")
        time.sleep(1)
        st.rerun()

else:
    st.info("🧬 系统初始化中，正在进行首轮基因扫描... (约需 5-10 秒)")
    progress_bar = st.progress(0)
    for i in range(100):
        time.sleep(0.05)
        progress_bar.progress(i + 1)
    time.sleep(1)
    st.rerun()

time.sleep(5)
st.rerun()
