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
import threading

# 禁用 HTTPS 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 基础配置与样式
# ===========================
st.set_page_config(page_title="VLESS 智能进化版", page_icon="🧬", layout="wide")

# 常量定义
RESULT_FILE = "scan_results.json"   # 前端展示用 (实时快照)
DB_FILE = "ip_database.json"        # 核心数据库 (历史沉淀)
CONFIG_FILE = "app_config.json"     # 用户配置

# 极速启动种子 (电信/联通/移动优化段)
QUICK_SEEDS = [
    "104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1", 
    "104.16.16.16", "104.24.24.24", "172.64.0.1", "104.18.18.18"
]

# 自定义 CSS 美化
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    div[data-testid="stMetricValue"] { font-size: 24px; color: #00ffca; }
    div[data-testid="column"] { background-color: #1a1c24; border: 1px solid #2d2f3b; border-radius: 8px; padding: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
    .stDataFrame { border: 1px solid #2d2f3b; border-radius: 5px; }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 核心功能类与工具函数
# ===========================

class IPDatabase:
    """JSON 数据库管理：负责长久记忆"""
    def __init__(self, filepath):
        self.filepath = filepath
        self.lock = threading.Lock() # 线程锁，防止读写冲突
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
                with open(self.filepath, "w", encoding='utf-8') as f: 
                    json.dump(self.data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Save DB Error: {e}")

    def update_ip(self, ip, stats):
        """更新或添加 IP 信息"""
        with self.lock:
            if ip not in self.data:
                self.data[ip] = stats
            else:
                # 保留历史最高分记录，但更新最近一次测试时间
                old_score = self.data[ip].get('score', 0)
                if stats['score'] >= old_score:
                    # 如果新分数更高，完全覆盖
                    stats['created_at'] = self.data[ip].get('created_at', stats['last_test'])
                    self.data[ip] = stats
                else:
                    # 否则只更新最近活跃时间
                    self.data[ip]['last_test'] = stats['last_test']

    def get_top_ips(self, limit=20):
        """获取数据库中表现最好的 IP"""
        valid_ips = list(self.data.values())
        # 简单排序：分数高优先
        valid_ips.sort(key=lambda x: x.get('score', 0), reverse=True)
        return valid_ips[:limit]

def get_config():
    """读取配置，包含 VLESS UUID 等信息"""
    default_conf = {
        "mode": "☀️ 正常使用排位",
        "uuid": "8f91b6a0-e8ee-4120-8a43-8a438a438a43", # 示例 UUID
        "host": "speed.cloudflare.com",
        "port": 443
    }
    try:
        with open(CONFIG_FILE, "r", encoding='utf-8') as f:
            cfg = json.load(f)
            return {**default_conf, **cfg} # 合并默认值
    except:
        return default_conf

def save_config(new_conf):
    current = get_config()
    current.update(new_conf)
    with open(CONFIG_FILE, "w", encoding='utf-8') as f:
        json.dump(current, f, indent=2)

def generate_vless(ip, port, uuid, host, name_tag):
    """生成 VLESS 链接字符串"""
    # 格式: vless://UUID@IP:PORT?encryption=none&security=tls&sni=HOST&fp=random&type=ws&host=HOST&path=%2F#REMARKS
    # 针对 Cloudflare 优选 IP，通常 security=tls, sni=host
    alias = f"{name_tag}-{ip}"
    return f"vless://{uuid}@{ip}:{port}?encryption=none&security=tls&sni={host}&fp=random&type=ws&host={host}&path=%2F#{alias}"

# ===========================
# 3. 扫描与逻辑处理
# ===========================

def get_geo_info(ip):
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,isp,hosting"
        r = requests.get(url, timeout=1.5).json()
        cc = r.get("countryCode", "US")
        is_native = not r.get("hosting", True) # 非托管机房通常被认为是原生
        # 简单粗暴判断 GPT 支持 (排除不支持的地区)
        gpt = "✅" if cc not in ['CN', 'HK', 'RU', 'IR', 'KP'] else "❌"
        return {"cc": cc, "isp": r.get("isp", ""), "gpt": gpt, "is_native": is_native}
    except: 
        return {"cc": "Unk", "isp": "", "gpt": "❓", "is_native": False}

def ping0_test(ip, port=443, count=4):
    lats, success = [], 0
    for _ in range(count):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            t1 = time.perf_counter()
            s.connect((ip, port))
            s.close()
            lats.append((time.perf_counter()-t1)*1000)
            success += 1
        except: pass
    
    if not lats: return {"avg": 999, "jitter": 99, "loss": 100}
    avg = int(statistics.mean(lats))
    jitter = int(statistics.stdev(lats)) if len(lats)>1 else 0
    loss = int(((count-success)/count)*100)
    return {"avg": avg, "jitter": jitter, "loss": loss}

def classify_ip(p0, speed, geo):
    """🏷️ 自动打标系统"""
    tags = []
    if p0['loss'] == 0 and p0['jitter'] < 10: tags.append("🎮 游戏/金融")
    if p0['avg'] < 150: tags.append("⚡ 极速")
    if geo['is_native']: tags.append("🎬 原生解锁")
    if geo['gpt'] == "✅": tags.append("🤖 GPT")
    
    region_map = {'HK': '🇭🇰 香港', 'JP': '🇯🇵 日本', 'SG': '🇸🇬 新加坡', 'US': '🇺🇸 美国', 'KR': '🇰🇷 韩国'}
    tags.append(region_map.get(geo['cc'], f"🏳️ {geo['cc']}"))
    
    return tags

def calculate_score(mode, p0, speed, geo):
    """🧠 评分算法"""
    score = 100.0
    
    # 基础扣分：丢包是死罪，延迟是硬伤
    score -= p0['loss'] * 5 
    
    # 模式差异化评分
    if mode == "🤖 GPT 独享专线":
        if geo['gpt'] == "❌": return 0 # 不支持直接淘汰
        limit = 280
    elif mode == "⚡ 极速低延迟":
        limit = 150
    else:
        limit = 200 # 默认宽容度
        
    if p0['avg'] > limit: score -= (p0['avg'] - limit) / 3
    
    score -= p0['jitter'] * 1
    score += min(speed * 5, 40) # 速度加分，上限40分
    
    return max(0, round(score, 1))

# ===========================
# 4. 后台进化线程
# ===========================

def background_worker():
    """后台默默工作的辛勤园丁"""
    db = IPDatabase(DB_FILE)
    first_run = True
    
    while True:
        try:
            cfg = get_config()
            mode = cfg.get("mode", "☀️ 正常使用排位")
            
            # --- 1. 获取目标 ---
            scan_targets = []
            
            # 始终加入一些种子，保持活性
            scan_targets.extend([{"ip": ip, "src": "⚡ 种子"} for ip in QUICK_SEEDS])
            
            # 从数据库回顾旧的强者
            top_db = db.get_top_ips(15)
            for item in top_db:
                scan_targets.append({"ip": item['ip'], "src": "📂 历史"})
                
            # 爬虫抓取 (模拟)
            if not first_run or len(top_db) < 5:
                try:
                    # 这里使用了 GitHub 上常见的公开 Cloudflare IP 列表
                    url = "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"
                    txt = requests.get(url, timeout=3).text
                    fresh_ips = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', txt)
                    # 随机抽取 20 个进行“基因突变”测试
                    for ip in random.sample(fresh_ips, min(len(fresh_ips), 25)):
                        scan_targets.append({"ip": ip, "src": "🕷️ 爬虫"})
                except: pass

            first_run = False
            
            # 去重
            unique_targets = {v['ip']:v for v in scan_targets}.values()

            # --- 2. 并发测试 ---
            current_results = []
            workers = 20 # 线程数
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                def task(target):
                    ip = target['ip']
                    
                    # 快速 Ping 检测，不通直接跳过
                    p0 = ping0_test(ip, cfg['port'])
                    if p0['loss'] > 40: return None # 丢包太严重直接丢弃
                    
                    # 测速 (下载小文件)
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        # 使用 speed.cloudflare.com 的测速接口
                        url = f"http://{ip}/__down?bytes=200000"
                        r = requests.get(url, headers={"Host": "speed.cloudflare.com"}, timeout=2.5)
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

            # --- 3. 结果保存 ---
            if current_results:
                db.save()
                current_results.sort(key=lambda x: x['score'], reverse=True)
                
                # 生成给前端看的数据包
                winner = current_results[0]
                vless_link = generate_vless(winner['ip'], cfg['port'], cfg['uuid'], cfg['host'], "Best-IP")
                
                state = {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "mode": mode,
                    "winner": winner,
                    "vless_link": vless_link,
                    "table": current_results[:50]
                }
                
                # 原子写入防止读取错误
                tmp_file = RESULT_FILE + ".tmp"
                with open(tmp_file, "w", encoding='utf-8') as f: json.dump(state, f, ensure_ascii=False)
                os.replace(tmp_file, RESULT_FILE)

        except Exception as e:
            print(f"Loop Error: {e}")
        
        # 休息时间：扫描越久，休息越久，避免滥用
        time.sleep(15)

# 启动后台线程 (单例模式)
if "bg_thread" not in st.session_state:
    t = threading.Thread(target=background_worker, daemon=True)
    t.start()
    st.session_state.bg_thread = True

# ===========================
# 5. 前端 UI 展示
# ===========================

# 侧边栏配置
with st.sidebar:
    st.header("🛠️ 配置控制台")
    
    cfg = get_config()
    
    # 模式选择
    modes = ["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线"]
    current_mode = cfg.get("mode", modes[0])
    try: idx = modes.index(current_mode)
    except: idx = 0
    new_mode = st.radio("优选策略", modes, index=idx)
    
    # UUID 配置
    with st.expander("🔑 VLESS 参数设置"):
        new_uuid = st.text_input("UUID", value=cfg.get("uuid", ""), type="password")
        new_host = st.text_input("伪装域名 (Host)", value=cfg.get("host", "speed.cloudflare.com"))
        
    if st.button("💾 保存配置并重启进化"):
        save_config({"mode": new_mode, "uuid": new_uuid, "host": new_host})
        st.toast("配置已保存，正在重新计算...", icon="🧬")
        time.sleep(1)
        st.rerun()
        
    st.divider()
    st.info("ℹ️ 后台正在自动从互联网和历史数据库中寻找最佳 IP，无需人工干预。")

# 主界面
st.title("🧬 Cloudflare VLESS 智能进化版")

if os.path.exists(RESULT_FILE):
    try:
        with open(RESULT_FILE, "r", encoding='utf-8') as f: 
            data = json.load(f)
            
        winner = data['winner']
        
        # --- 顶部：冠军展示 ---
        st.markdown("### 🏆 当前最佳节点")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("IP 地址", winner['ip'], delta="优选冠军")
        c2.metric("延迟 (ms)", f"{winner['avg']} ms", delta_color="inverse")
        c3.metric("下载速度", f"{winner['speed']} MB/s")
        c4.metric("进化得分", winner['score'])
        
        # 标签展示
        st.markdown("**特性标签:** " + " ".join([f"`{t}`" for t in winner['tags']]))
        
        # VLESS 链接复制区
        st.success("👇 复制下方的链接到 v2rayN / NecroBox / Shadowrocket")
        st.code(data['vless_link'], language="text")
        
        st.divider()
        
        # --- 底部：详细列表 ---
        st.subheader(f"🧬 基因库优选列表 (策略: {data['mode']})")
        
        df = pd.DataFrame(data['table'])
        
        # 数据清洗，防止某些列不存在
        if 'tags' in df.columns:
            df['tags'] = df['tags'].apply(lambda x: ", ".join(x) if isinstance(x, list) else str(x))
            
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
        
        st.caption(f"上次更新: {data['last_run']} | 数据库持续进化中...")
        
    except Exception as e:
        st.warning(f"正在写入数据，请稍后... ({e})")
        time.sleep(2)
        st.rerun()
else:
    st.info("🧬 系统初始化中，正在进行第一轮基因进化扫描... (约需 5-10 秒)")
    # 增加一个假的进度条提升体验
    progress_text = "扫描网络节点中..."
    my_bar = st.progress(0, text=progress_text)
    for percent_complete in range(100):
        time.sleep(0.05)
        my_bar.progress(percent_complete + 1, text=progress_text)
    time.sleep(1)
    st.rerun()

# 自动刷新逻辑 (避免过度刷新影响复制)
# 使用 Session State 计数器来实现“慢刷新”
if 'refresh_count' not in st.session_state:
    st.session_state.refresh_count = 0

time.sleep(5) 
st.rerun()
