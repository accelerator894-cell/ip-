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
# 1. 页面配置
# ===========================
st.set_page_config(page_title="VLESS 四川电信监控台", page_icon="🐼", layout="wide")

RESULT_FILE = "scan_results.json"
CONFIG_FILE = "app_config.json"
SAVED_IP_FILE = "good_ips.txt"

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    div[data-testid="column"] { background-color: #15171e; border: 1px solid #262730; border-radius: 8px; padding: 15px; }
    .gpt-mode-active { border: 2px solid #2ECC71 !important; }
    </style>
    """, unsafe_allow_html=True)

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
        
        # OpenAI 黑名单 (简化版)
        blocked_cc = ['CN', 'HK', 'RU', 'IR', 'KP', 'CU', 'SY', 'MO']
        gpt_status = "✅ 支持" if cc not in blocked_cc else "❌ 不支持"
        
        return {"cc": cc, "region": region_name, "isp": isp, "gpt": gpt_status}
    except:
        return {"cc": "Unk", "region": "❓ 未知", "isp": "Unk", "gpt": "❓ 未知"}

# --- TLS 握手测试 (通用版) ---
def check_tls_handshake(ip):
    """
    模拟 TLS 握手，验证 IP 是否能处理加密流量。
    使用通用 SNI (speed.cloudflare.com) 进行探测，确保是有效的 CF 节点。
    """
    try:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        # 1.5秒超时
        conn = context.wrap_socket(
            socket.socket(socket.AF_INET),
            server_hostname="speed.cloudflare.com" # 通用检测
        )
        conn.settimeout(1.5)
        
        t1 = time.perf_counter()
        conn.connect((ip, 443))
        dur = (time.perf_counter() - t1) * 1000
        conn.close()
        return {"status": True, "latency": int(dur)}
    except:
        return {"status": False, "latency": 9999}

def calculate_score(mode, avg, jitter, loss, speed, gpt_status, tls_ok):
    # 1. TLS 阻断直接归零
    if not tls_ok: return 0 
    
    # 2. GPT 模式一票否决
    if mode == "🤖 GPT 独享专线" and gpt_status != "✅ 支持": return 0

    score = 100.0
    
    # 3. 丢包惩罚 (四川电信敏感)
    loss_penalty = 6 if mode != "🤖 GPT 独享专线" else 4
    score -= (loss * loss_penalty)
    
    # 4. 延迟基准
    limit = 280 if mode == "🤖 GPT 独享专线" else 180
    if avg > limit: score -= (avg - limit) / 5
    
    # 5. 抖动与速度
    score -= jitter * 1.5
    score += min(speed * 3, 30)
    
    # 6. GPT 加分
    if mode == "🤖 GPT 独享专线" and gpt_status == "✅ 支持":
        score += 10

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

    # 3. 全网爬虫
    if time_slot != "PEAK":
        try:
            urls = ["https://www.cloudflare.com/ips-v4", "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
            for u in urls:
                txt = requests.get(u, timeout=3).text
                found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', txt)
                sample_size = 50 if mode == "🤖 GPT 独享专线" else 30
                for ip in random.sample(found, min(len(found), sample_size)):
                    if ip not in seen:
                        pool.append({"ip": ip, "source": "🕷️ 全网爬虫"}); seen.add(ip)
        except: pass
    return pool

def background_worker():
    while True:
        try:
            cfg = get_config(); mode = cfg["mode"]; time_slot = get_time_slot()
            pool = smart_crawler(mode, time_slot)
            
            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
                def process_node(node):
                    ip = node['ip']
                    
                    # 1. 国测筛选
                    cn_lat = get_china_latency(ip)
                    if cn_lat > 600: return None
                    
                    # 2. TLS 真连接测试 (无配置版)
                    tls = check_tls_handshake(ip)
                    if not tls['status']: return None 
                    
                    # 3. 测速
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes=200000", headers={"Host": "speed.cloudflare.com"}, timeout=2)
                        speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    # 4. Geo & GPT
                    geo = get_geo_and_gpt_status(ip)
                    
                    # 5. Ping0
                    p0 = ping0_tcp_test(ip)
                    if p0['loss'] > 25: return None
                    
                    # 6. 算分
                    score = calculate_score(mode, p0['avg'], p0['jitter'], p0['loss'], speed, geo['gpt'], True)
                    
                    if score <= 0: return None
                    
                    return {
                        "ip": ip, "score": score, "cn_lat": cn_lat, "speed": round(speed, 2),
                        "loss": p0['loss'], "jitter": p0['jitter'], 
                        "source": node['source'], "region": geo['region'], "gpt": geo['gpt'],
                        "tls_lat": tls['latency']
                    }

                futs = [ex.submit(process_node, n) for n in pool]
                for f in concurrent.futures.as_completed(futs):
                    res = f.result()
                    if res: results.append(res)

            if results:
                results.sort(key=lambda x: x['score'], reverse=True)
                winner = results[0]
                
                with open(SAVED_IP_FILE, "a") as f:
                    for r in results[:3]: f.write(f"{r['ip']}\n")
                
                sync_dns(winner['ip'])

                state = {"last_run": datetime.now().strftime("%H:%M:%S"), "time_slot": time_slot, "mode": mode, "winner": winner, "sync_msg": "已同步", "table": results[:25]}
                with open(RESULT_FILE, "w") as f: json.dump(state, f)
                
        except Exception as e: print(f"Worker Error: {e}")
        time.sleep(300 if mode == "🤖 GPT 独享专线" else 600)

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
    new_mode = st.radio("排位模式", ["☀️ 正常使用排位", "🌙 晚高峰避峰排位", "🤖 GPT 独享专线"], index=0)
    if new_mode != curr.get("mode"):
        save_config(new_mode)
        st.toast(f"模式切换: {new_mode}", icon="🚀")

st.title("🐼 VLESS 电信 GPT 专版")

if os.path.exists(RESULT_FILE):
    with open(RESULT_FILE, "r") as f: data = json.load(f)
    winner = data['winner']
    df = pd.DataFrame(data['table'])
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👑 冠军 IP", winner['ip'])
    c2.metric("🔒 TLS 握手", f"{winner['tls_lat']} ms")
    c3.metric("📉 延迟/丢包", f"{winner['cn_lat']}ms / {winner['loss']}%")
    c4.metric("📊 得分", f"{winner['score']}")
    
    st.divider()

    st.subheader("🧬 节点分布图")
    st.scatter_chart(df, x='cn_lat', y='score', color='gpt', size='speed', use_container_width=True)

    st.subheader("📋 详细报告")
    st.dataframe(
        df,
        column_order=("score", "ip", "gpt", "tls_lat", "cn_lat", "loss", "speed", "source"),
        column_config={
            "tls_lat": st.column_config.NumberColumn("TLS握手", format="%d ms"),
            "score": st.column_config.ProgressColumn("得分", format="%.0f", min_value=0, max_value=100),
            "cn_lat": st.column_config.NumberColumn("TCP延迟", format="%d ms"),
            "loss": st.column_config.NumberColumn("丢包", format="%d%%"),
            "speed": st.column_config.NumberColumn("速度", format="%.2f MB/s"),
        },
        use_container_width=True,
        hide_index=True
    )

else:
    st.warning("🐼 系统正在后台筛选优质节点，请稍候...")
    time.sleep(5)
    st.rerun()

time.sleep(10)
st.rerun()
