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
from datetime import datetime
import urllib3

# 禁用 HTTPS 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 页面配置与 UI
# ===========================
st.set_page_config(page_title="VLESS 四川电信 GPT版", page_icon="🐼", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    div[data-testid="column"] { background-color: #15171e; border: 1px solid #262730; border-radius: 8px; padding: 15px; }
    /* GPT 模式下的特殊高亮 */
    .gpt-mode-active { border: 2px solid #2ECC71 !important; }
    </style>
    """, unsafe_allow_html=True)

RESULT_FILE = "scan_results.json"
CONFIG_FILE = "app_config.json"
SAVED_IP_FILE = "good_ips.txt"

# ===========================
# 2. 核心工具箱
# ===========================

def get_config():
    default = {"mode": "☀️ 正常使用排位"}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f: return json.load(f)
        except: return default
    return default

def save_config(mode):
    with open(CONFIG_FILE, "w") as f: json.dump({"mode": mode}, f)

def get_time_slot():
    h = datetime.now().hour
    if 19 <= h <= 23: return "PEAK"
    if 1 <= h <= 6:   return "IDLE"
    return "NORMAL"

# --- GPT 与 地区检测 ---
def get_geo_and_gpt_status(ip):
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country,isp,hosting"
        r = requests.get(url, timeout=2).json()
        cc = r.get("countryCode", "US")
        isp = r.get("isp", "")
        
        region_map = {
            'CN': '🇨🇳 中国', 'HK': '🇭🇰 香港', 'MO': '🇲🇴 澳门',
            'US': '🇺🇸 美国', 'JP': '🇯🇵 日本', 'SG': '🇸🇬 新加坡',
            'KR': '🇰🇷 韩国', 'TW': '🇹🇼 台湾', 'GB': '🇬🇧 英国'
        }
        region_name = region_map.get(cc, f"🌍 {cc}")

        # OpenAI 黑名单地区
        blocked_cc = ['CN', 'HK', 'RU', 'IR', 'KP', 'CU', 'SY', 'MO']
        
        gpt_status = "✅ 支持"
        if cc in blocked_cc:
            gpt_status = "❌ 不支持"
        
        return {"cc": cc, "region": region_name, "isp": isp, "gpt": gpt_status}
    except:
        return {"cc": "Unk", "region": "❓ 未知", "isp": "Unk", "gpt": "❓ 未知"}

# --- 评分算法 (含 GPT 独享逻辑) ---
def calculate_score(mode, avg, jitter, loss, speed, gpt_status, cc):
    """
    全能评分引擎：支持 电信优化、避峰、GPT 专线
    """
    # === A. ☠️ GPT 模式的一票否决权 ===
    if mode == "🤖 GPT 独享专线":
        if gpt_status != "✅ 支持":
            return 0 # 直接枪毙
        if cc == "Unk":
            return 0 # 未知地区也不要

    score = 100.0
    
    # === B. 丢包惩罚 (四川电信核心痛点) ===
    # 正常/原生模式：丢包 > 20% 也就是不及格
    # GPT 模式：稍微宽容点，允许偶尔丢包，因为只要能对话就行
    loss_penalty = 6 if mode != "🤖 GPT 独享专线" else 4
    score -= (loss * loss_penalty)
    
    # === C. 延迟评分 (基准线调整) ===
    # 四川电信直连美西基准：180ms
    # GPT 模式基准：放宽到 280ms (为了解锁，可以绕路)
    latency_benchmark = 280 if mode == "🤖 GPT 独享专线" else 180
    
    if avg > latency_benchmark:
        score -= (avg - latency_benchmark) / 5
    
    # === D. 抖动与速度 ===
    score -= jitter * 1.5
    score += min(speed * 3, 30)
    
    # === E. 模式加成 ===
    if mode == "🤖 GPT 独享专线":
        # 如果是美/日/新，额外加分 (OpenAI 最稳的区)
        if cc in ['US', 'JP', 'SG']:
            score += 20
    elif mode == "🌙 晚高峰避峰排位":
        score -= loss * 5 # 避峰最怕丢包

    return max(0, round(score, 1))

def ping0_tcp_test(ip, count=6):
    lats, success = [], 0
    for _ in range(count):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.6)
            t1 = time.perf_counter(); s.connect((ip, 443)); s.close()
            lats.append((time.perf_counter() - t1) * 1000); success += 1
        except: pass
        time.sleep(0.05)
    
    if not lats: return {"avg": 9999, "jitter": 999, "loss": 100}
    return {"avg": int(statistics.mean(lats)), "jitter": int(statistics.stdev(lats)) if len(lats) > 1 else 0, "loss": int(((count-success)/count)*100)}

def get_china_latency(ip):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5); t1 = time.perf_counter(); s.connect((ip, 443))
        dur = (time.perf_counter() - t1) * 1000; s.close()
        return int(dur)
    except: return 999

def sync_dns(ip):
    try:
        if "api_token" not in st.secrets: return "⚠️ 无 Secrets"
        cfg = st.secrets
        url = f"https://api.cloudflare.com/client/v4/zones/{cfg['zone_id']}/dns_records"
        headers = {"Authorization": f"Bearer {cfg['api_token']}", "Content-Type": "application/json"}
        recs = requests.get(url, headers=headers, params={"name": cfg['record_name']}, timeout=5).json()
        if recs["result"]:
            rid = recs["result"][0]["id"]
            if recs["result"][0]["content"] == ip: return f"✅ 稳定 ({ip})"
            requests.put(f"{url}/{rid}", headers=headers, json={"type":"A","name":cfg['record_name'],"content":ip,"ttl":60,"proxied":False})
            return f"🚀 切换: {ip}"
    except: return "❌ API 异常"
    return "⚠️ 记录丢失"

# ===========================
# 3. 智能爬虫
# ===========================
def smart_crawler(mode, time_slot):
    pool, seen = [], set()
    
    # 1. 本地固态
    if os.path.exists(SAVED_IP_FILE):
        with open(SAVED_IP_FILE, "r") as f:
            local_ips = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', f.read())
            for ip in local_ips[-15:]:
                if ip not in seen:
                    pool.append({"ip": ip, "source": "📂 本地固态"}); seen.add(ip)

    # 2. 基因衍生
    if pool:
        parents = [n['ip'] for n in pool[:5]]
        for ip in parents:
            subnet = ".".join(ip.split(".")[:3])
            for _ in range(3):
                child = f"{subnet}.{random.randint(1, 254)}"
                if child not in seen:
                    pool.append({"ip": child, "source": "🧬 基因衍生"}); seen.add(child)

    # 3. 全网爬虫 (GPT 模式倾向于找 Cloudflare 官方段，概率大)
    if time_slot != "PEAK":
        try:
            urls = ["https://www.cloudflare.com/ips-v4", "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
            for u in urls:
                txt = requests.get(u, timeout=3).text
                found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', txt)
                # 如果是 GPT 模式，多抓点，因为淘汰率高
                sample_size = 50 if mode == "🤖 GPT 独享专线" else 30
                for ip in random.sample(found, min(len(found), sample_size)):
                    if ip not in seen:
                        pool.append({"ip": ip, "source": "🕷️ 全网爬虫"}); seen.add(ip)
        except: pass
                
    return pool

def background_worker():
    while True:
        try:
            cfg = get_config()
            mode = cfg["mode"]
            time_slot = get_time_slot()
            pool = smart_crawler(mode, time_slot)
            
            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=25) as ex:
                def process_node(node):
                    ip = node['ip']
                    
                    # 1. 基础连通 (GPT 模式允许 800ms，其他 600ms)
                    lat_limit = 800 if mode == "🤖 GPT 独享专线" else 600
                    cn_lat = get_china_latency(ip)
                    if cn_lat > lat_limit: return None
                    
                    # 2. 测速
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes=200000", headers={"Host": "speed.cloudflare.com"}, timeout=2)
                        speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    # 3. Geo & GPT 
                    geo = get_geo_and_gpt_status(ip)
                    
                    # 4. Ping0
                    p0 = ping0_tcp_test(ip)
                    if p0['loss'] > 25: return None
                    
                    # 5. 算分
                    score = calculate_score(mode, p0['avg'], p0['jitter'], p0['loss'], speed, geo['gpt'], geo['cc'])
                    
                    # GPT 模式下，分数为0的直接不要
                    if score <= 0: return None
                    
                    return {
                        "ip": ip, "score": score, "cn_lat": cn_lat, "speed": round(speed, 2),
                        "loss": p0['loss'], "jitter": p0['jitter'], 
                        "source": node['source'], "region": geo['region'], "gpt": geo['gpt']
                    }

                futs = [ex.submit(process_node, n) for n in pool]
                for f in concurrent.futures.as_completed(futs):
                    res = f.result()
                    if res: results.append(res)

            if results:
                results.sort(key=lambda x: x['score'], reverse=True)
                winner = results[0]
                
                # 只有分高的才入库
                with open(SAVED_IP_FILE, "a") as f:
                    for r in results[:3]: f.write(f"{r['ip']}\n")
                
                sync_msg = sync_dns(winner['ip'])
                
                state = {"last_run": datetime.now().strftime("%H:%M:%S"), "time_slot": time_slot, "mode": mode, "winner": winner, "sync_msg": sync_msg, "table": results[:25]}
                with open(RESULT_FILE, "w") as f: json.dump(state, f)
                
        except Exception as e: print(f"Worker Error: {e}")
        time.sleep(300 if mode == "🤖 GPT 独享专线" else 600) # GPT 模式跑快点，为了找活口

if "bg_thread" not in st.session_state:
    import threading
    threading.Thread(target=background_worker, daemon=True).start()
    st.session_state.bg_thread = True

# ===========================
# 4. 前端展示
# ===========================
with st.sidebar:
    st.header("🐼 四川电信控制台")
    curr = get_config()
    # 新增了 GPT 模式
    new_mode = st.radio("排位模式", ["☀️ 正常使用排位", "🌙 晚高峰避峰排位", "🤖 GPT 独享专线"], index=0)
    if new_mode != curr.get("mode"):
        save_config(new_mode)
        st.toast(f"模式切换: {new_mode}", icon="🚀")
    
    if new_mode == "🤖 GPT 独享专线":
        st.success("🤖 已启用 GPT 强过滤：将自动剔除 HK/CN 等不支持地区，且容忍较高延迟。")

st.title("🐼 VLESS 电信 GPT 专版")

if os.path.exists(RESULT_FILE):
    with open(RESULT_FILE, "r") as f: data = json.load(f)
    winner = data['winner']
    df = pd.DataFrame(data['table'])
    
    # 动态标题
    status_color = "green" if winner['gpt'] == "✅ 支持" else "red"
    st.markdown(f"### 当前模式: `{data['mode']}`")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👑 冠军 IP", winner['ip'])
    c2.metric("🤖 GPT 状态", winner['gpt'], delta_color="off" if winner['gpt']=="✅ 支持" else "inverse")
    c3.metric("📉 延迟/丢包", f"{winner['cn_lat']}ms / {winner['loss']}%")
    c4.metric("📊 综合得分", f"{winner['score']}")
    
    st.divider()
    
    # 散点图
    st.subheader("🧬 节点分布图")
    st.scatter_chart(df, x='cn_lat', y='score', color='gpt', size='speed', use_container_width=True)

    # 表格
    st.subheader("📋 详细报告")
    st.dataframe(
        df,
        column_order=("score", "ip", "gpt", "region", "cn_lat", "loss", "speed", "source"),
        column_config={
            "score": st.column_config.ProgressColumn("得分", format="%.0f", min_value=0, max_value=100),
            "gpt": st.column_config.TextColumn("GPT"),
            "region": st.column_config.TextColumn("地区"),
            "cn_lat": st.column_config.NumberColumn("延迟", format="%d ms"),
            "loss": st.column_config.NumberColumn("丢包", format="%d%%"),
            "source": st.column_config.TextColumn("来源"),
        },
        use_container_width=True,
        hide_index=True
    )
else:
    st.warning("🐼 正在进行 GPT 线路专项清洗... 请稍候")
    time.sleep(5)
    st.rerun()

time.sleep(10)
st.rerun()
