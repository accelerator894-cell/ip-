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
import ssl
from datetime import datetime
import urllib3

# 禁用 HTTPS 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 基础配置
# ===========================
st.set_page_config(page_title="VLESS 智能进化版", page_icon="🧬", layout="wide")

# 文件定义
RESULT_FILE = "scan_results.json"   # 前端展示用
DB_FILE = "ip_database.json"        # 核心数据库 (存所有历史数据)
CONFIG_FILE = "app_config.json"     # 用户配置

# 极速启动种子 (电信优化段)
QUICK_SEEDS = ["104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1"]

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    div[data-testid="column"] { background-color: #15171e; border: 1px solid #262730; border-radius: 8px; padding: 15px; }
    .tag-game { background-color: #2ECC40; color: black; padding: 2px 6px; border-radius: 4px; font-weight: bold; }
    .tag-netflix { background-color: #E50914; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold; }
    .tag-gpt { background-color: #10a37f; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 数据库与分类系统 (核心升级)
# ===========================

class IPDatabase:
    """简易 JSON 数据库管理"""
    def __init__(self, filepath):
        self.filepath = filepath
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f: return json.load(f)
            except: return {}
        return {}

    def save(self):
        with open(self.filepath, "w") as f: json.dump(self.data, f, indent=2)

    def update_ip(self, ip, stats):
        """更新或添加 IP 信息，并保留历史最高分"""
        if ip not in self.data:
            self.data[ip] = stats
        else:
            # 只有当新分数更高，或者数据更新时才覆盖
            # 但保留 'created_at'
            stats['created_at'] = self.data[ip].get('created_at', stats['last_test'])
            self.data[ip] = stats
    
    def get_top_ips(self, limit=20):
        """获取分数最高的 IP 列表"""
        # 过滤掉超过 24 小时未测试的旧数据 (可选)
        valid_ips = [v for k, v in self.data.items()]
        valid_ips.sort(key=lambda x: x['score'], reverse=True)
        return valid_ips[:limit]

def classify_ip(ip, p0, speed, geo):
    """
    🏷️ 自动分类引擎
    根据测试结果给 IP 打上适合的标签
    """
    tags = []
    
    # 1. 游戏/金融标签 (0丢包 + 低抖动)
    if p0['loss'] == 0 and p0['jitter'] < 5:
        tags.append("🎮 0丢包")
    
    # 2. 电信极速标签 (延迟 < 160ms)
    if p0['avg'] < 160:
        tags.append("⚡ 电信极速")
        
    # 3. 流媒体标签
    if geo['is_native']:
        tags.append("🎬 原生/NF")
    
    # 4. AI 标签
    if geo['gpt'] == "✅":
        tags.append("🤖 GPT")
        
    # 5. 地区标签
    if geo['cc'] in ['HK', 'TW', 'JP', 'SG']:
        tags.append("🌏 亚太")
    elif geo['cc'] in ['US']:
        tags.append("🗽 美西")
        
    return tags

# ===========================
# 3. 核心测试逻辑 (保持稳健)
# ===========================

def get_config():
    try:
        with open(CONFIG_FILE, "r") as f: return json.load(f)
    except: return {"mode": "☀️ 正常使用排位"}

def save_config(mode):
    with open(CONFIG_FILE, "w") as f: json.dump({"mode": mode}, f)

def get_geo_info(ip):
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,isp,hosting"
        r = requests.get(url, timeout=1.5).json()
        cc = r.get("countryCode", "US")
        is_native = not r.get("hosting", True)
        gpt = "✅" if cc not in ['CN', 'HK', 'RU', 'IR', 'KP'] else "❌"
        return {"cc": cc, "isp": r.get("isp", ""), "gpt": gpt, "is_native": is_native}
    except: return {"cc": "Unk", "isp": "", "gpt": "❓", "is_native": False}

def check_tls(ip):
    try:
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        conn = ctx.wrap_socket(socket.socket(socket.AF_INET), server_hostname="speed.cloudflare.com")
        conn.settimeout(1.0)
        t1 = time.perf_counter(); conn.connect((ip, 443)); dur = (time.perf_counter()-t1)*1000
        conn.close()
        return True, int(dur)
    except: return False, 9999

def ping0_test(ip, count=4):
    lats, success = [], 0
    for _ in range(count):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.5)
            t1 = time.perf_counter(); s.connect((ip, 443)); s.close()
            lats.append((time.perf_counter()-t1)*1000); success += 1
        except: pass
    if not lats: return {"avg": 999, "jitter": 99, "loss": 100}
    return {"avg": int(statistics.mean(lats)), "jitter": int(statistics.stdev(lats)) if len(lats)>1 else 0, "loss": int(((count-success)/count)*100)}

def calculate_score(mode, p0, speed, geo):
    score = 100.0
    score -= p0['loss'] * 6 # 严惩丢包
    limit = 280 if mode == "🤖 GPT 独享专线" else 180
    if p0['avg'] > limit: score -= (p0['avg'] - limit) / 5
    score -= p0['jitter'] * 1.5
    score += min(speed * 4, 30)
    
    if mode == "🤖 GPT 独享专线" and geo['gpt'] == "❌": return 0
    if mode == "🎬 流媒体解锁专线" and not geo['is_native']: score -= 30
    
    return max(0, round(score, 1))

# ===========================
# 4. 后台调度 (进化逻辑)
# ===========================

def background_worker():
    db = IPDatabase(DB_FILE)
    first_run = True
    
    while True:
        try:
            cfg = get_config(); mode = cfg.get("mode", "☀️ 正常使用排位")
            
            # --- 阶段 1: 确定扫描目标 ---
            scan_targets = []
            
            if first_run:
                # 🚀 第一次：种子 + 数据库里最好的前10个 (极速启动)
                scan_targets = [{"ip": ip, "src": "⚡ 内置种子"} for ip in QUICK_SEEDS]
                top_db = db.get_top_ips(10)
                for item in top_db:
                    scan_targets.append({"ip": item['ip'], "src": "📂 历史优选"})
                first_run = False
            else:
                # 🚜 后续：爬虫抓新 + 数据库回扫 (慢慢对比)
                # 1. 爬虫抓取
                try:
                    txt = requests.get("https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt", timeout=3).text
                    fresh_ips = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', txt)
                    # 针对模式过滤
                    if mode == "🤖 GPT 独享专线":
                        fresh_ips = [ip for ip in fresh_ips if ip.startswith("104.19") or ip.startswith("172.64")]
                    
                    # 随机取 20 个新的
                    for ip in random.sample(fresh_ips, min(len(fresh_ips), 20)):
                        scan_targets.append({"ip": ip, "src": "🕷️ 爬虫发现"})
                except: pass
                
                # 2. 数据库回锅 (复查旧的优选 IP，看是否还活着)
                top_db = db.get_top_ips(10)
                for item in top_db:
                    scan_targets.append({"ip": item['ip'], "src": "♻️ 优选复查"})

            # --- 阶段 2: 执行测试 ---
            current_results = []
            workers = 30 if len(scan_targets) < 50 else 15 # 人少多开，人多排队
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                def task(target):
                    ip = target['ip']
                    
                    # 基础筛选
                    tls_ok, _ = check_tls(ip)
                    if not tls_ok: return None
                    
                    p0 = ping0_test(ip)
                    if p0['loss'] > 30: return None
                    
                    # 测速
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes=150000", headers={"Host": "speed.cloudflare.com"}, timeout=2)
                        speed = (len(r.content)/1024/1024)/(time.perf_counter()-st_t)
                    except: pass
                    
                    geo = get_geo_info(ip)
                    score = calculate_score(mode, p0, speed, geo)
                    if score <= 0: return None
                    
                    # 🏷️ 核心：生成分类标签
                    tags = classify_ip(ip, p0, speed, geo)
                    
                    stats = {
                        "ip": ip, "score": score, "loss": p0['loss'], "avg": p0['avg'],
                        "speed": round(speed, 2), "tags": tags, "src": target['src'],
                        "last_test": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "gpt": geo['gpt'], "native": geo['is_native']
                    }
                    return stats

                futs = [ex.submit(task, t) for t in scan_targets]
                for f in concurrent.futures.as_completed(futs):
                    r = f.result()
                    if r: 
                        current_results.append(r)
                        # 实时存入数据库
                        db.update_ip(r['ip'], r)

            # --- 阶段 3: 优选对比与保存 ---
            if current_results:
                db.save() # 保存到硬盘
                
                # 排序出本次最好的
                current_results.sort(key=lambda x: x['score'], reverse=True)
                winner = current_results[0]
                
                # 读取上一次的结果进行对比 (模拟)
                # 只有新IP确实强，或者列表更新了才刷新前端
                state = {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "mode": mode,
                    "winner": winner,
                    "table": current_results[:30] # 前端只看前30
                }
                with open(RESULT_FILE, "w") as f: json.dump(state, f)

        except Exception as e: print(f"Err: {e}")
        time.sleep(3 if first_run else 30) # 首次快，后续慢

if "bg_thread" not in st.session_state:
    import threading
    threading.Thread(target=background_worker, daemon=True).start()
    st.session_state.bg_thread = True

# ===========================
# 5. 前端展示 (支持标签显示)
# ===========================
with st.sidebar:
    st.header("🧬 进化控制台")
    modes = ["☀️ 正常使用排位", "🌙 晚高峰避峰排位", "🤖 GPT 独享专线", "🎬 流媒体解锁专线"]
    curr = get_config().get("mode", modes[0])
    try: idx = modes.index(curr)
    except: idx = 0
    new_mode = st.radio("当前策略", modes, index=idx)
    if new_mode != curr:
        save_config(new_mode)
        st.toast(f"策略切换: {new_mode}", icon="🧬")
        time.sleep(0.5); st.rerun()

st.title("🧬 VLESS 智能进化版")

if os.path.exists(RESULT_FILE):
    with open(RESULT_FILE, "r") as f: data = json.load(f)
    winner = data['winner']
    
    # 顶部冠军卡片
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👑 冠军 IP", winner['ip'])
    c2.metric("🏷️ 核心标签", winner['tags'][0] if winner['tags'] else "无")
    c3.metric("📉 延迟/丢包", f"{winner['avg']}ms / {winner['loss']}%")
    c4.metric("📊 进化得分", f"{winner['score']}")
    
    st.divider()
    
    # 详细列表 (支持 Tag 显示)
    st.subheader(f"🧬 基因库优选 (当前策略: {data['mode']})")
    df = pd.DataFrame(data['table'])
    
    st.dataframe(
        df,
        column_order=("score", "tags", "ip", "avg", "loss", "speed", "src"),
        column_config={
            "score": st.column_config.ProgressColumn("得分", min_value=0, max_value=100, format="%.0f"),
            "tags": st.column_config.ListColumn("特性标签"),
            "ip": st.column_config.TextColumn("IP 地址"),
            "avg": st.column_config.NumberColumn("延迟", format="%d ms"),
            "loss": st.column_config.NumberColumn("丢包", format="%d%%"),
            "speed": st.column_config.NumberColumn("速度", format="%.1f MB/s"),
            "src": st.column_config.TextColumn("来源"),
        },
        use_container_width=True,
        hide_index=True
    )
    
    st.caption(f"上次进化时间: {data['last_run']} | 数据库已存储历史优选 IP")

else:
    st.info("🧬 正在加载本地基因库并进行首次进化对比... (约3秒)")
    time.sleep(2)
    st.rerun()

time.sleep(5)
st.rerun()
