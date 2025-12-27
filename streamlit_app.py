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
# 1. 页面配置与四川电信UI风格
# ===========================
st.set_page_config(page_title="VLESS 四川电信定制版", page_icon="🐼", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    div[data-testid="column"] { background-color: #15171e; border: 1px solid #262730; border-radius: 8px; padding: 15px; }
    
    /* 标签颜色定义 */
    .tag-local { background-color: #2E86C1; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }
    .tag-spider { background-color: #C0392B; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }
    .tag-gpt-ok { color: #2ECC71; font-weight: bold; }
    .tag-gpt-no { color: #E74C3C; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

RESULT_FILE = "scan_results.json"
CONFIG_FILE = "app_config.json"
SAVED_IP_FILE = "good_ips.txt"

# ===========================
# 2. 核心算法工具箱
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
    if 19 <= h <= 23: return "PEAK"  # 晚高峰
    if 1 <= h <= 6:   return "IDLE"  # 闲时
    return "NORMAL"

# --- GPT 与 地区检测 ---
def get_geo_and_gpt_status(ip):
    """
    检测 IP 归属地，并判断是否支持 GPT
    """
    try:
        # 使用 ip-api (注意: 生产环境建议用离线库如 GeoIP2)
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country,isp,hosting"
        r = requests.get(url, timeout=2).json()
        cc = r.get("countryCode", "US")
        isp = r.get("isp", "")
        
        # 1. 区域判定
        region_map = {
            'CN': '🇨🇳 中国', 'HK': '🇭🇰 香港', 'MO': '🇲🇴 澳门',
            'US': '🇺🇸 美国', 'JP': '🇯🇵 日本', 'SG': '🇸🇬 新加坡',
            'KR': '🇰🇷 韩国', 'TW': '🇹🇼 台湾', 'GB': '🇬🇧 英国',
            'DE': '🇩🇪 德国', 'FR': '🇫🇷 法国'
        }
        region_name = region_map.get(cc, f"🌍 {cc}")

        # 2. GPT 资格审查 (基于 OpenAI 的地区政策)
        # OpenAI 不支持: CN, HK, RU, IR, KP 等
        blocked_cc = ['CN', 'HK', 'RU', 'IR', 'KP', 'CU', 'SY']
        gpt_status = "✅ 支持"
        if cc in blocked_cc:
            gpt_status = "❌ 不支持"
        
        return {"cc": cc, "region": region_name, "isp": isp, "gpt": gpt_status}
    except:
        return {"cc": "Unk", "region": "❓ 未知", "isp": "Unk", "gpt": "❓ 未知"}

# --- 四川电信定制评分算法 ---
def calculate_telecom_score(mode, avg, jitter, loss, speed, gpt_status):
    """
    【四川电信专用评分公式】
    特点：对延迟基准线要求更高(180ms)，极大惩罚丢包
    """
    score = 100.0
    
    # 1. 丢包惩罚 (电信晚高峰最怕这个)
    # 只要有丢包，分数直接打骨折
    score -= (loss * 6) 
    
    # 2. 延迟评分 (基准线 180ms - 典型电信直连美西延迟)
    if avg > 180:
        score -= (avg - 180) / 5  # 超过180ms，每10ms扣2分
    
    # 3. 抖动评分
    score -= jitter * 1.5
    
    # 4. 速度加成
    score += min(speed * 3, 30) # 上限加30分
    
    # 5. GPT 加权
    if gpt_status == "✅ 支持":
        score += 10 # GPT 节点额外加分
    else:
        score -= 20 # 不支持 GPT 的扣分 (既然你要测 GPT)
        
    # 模式修正
    if mode == "🌙 晚高峰避峰排位":
        score -= loss * 5 # 避峰模式下，丢包扣分加倍
    
    return max(0, round(score, 1))

def ping0_tcp_test(ip, count=6):
    """TCP 握手 (Ping0 算法)"""
    lats = []
    success = 0
    for _ in range(count):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.6)
            t1 = time.perf_counter()
            s.connect((ip, 443))
            s.close()
            lats.append((time.perf_counter() - t1) * 1000)
            success += 1
        except: pass
        time.sleep(0.05)
    
    if not lats: return {"avg": 9999, "jitter": 999, "loss": 100}
    
    avg = statistics.mean(lats)
    jitter = statistics.stdev(lats) if len(lats) > 1 else 0
    loss = ((count - success) / count) * 100
    
    return {"avg": int(avg), "jitter": int(jitter), "loss": int(loss)}

def get_china_latency(ip):
    """模拟本地(四川电信)连通性"""
    # 实际上就是测运行此代码的机器(你的电脑)到 IP 的延迟
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        t1 = time.perf_counter()
        s.connect((ip, 443))
        dur = (time.perf_counter() - t1) * 1000
        s.close()
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
# 3. 智能爬虫与分类调度
# ===========================

def smart_crawler(mode, time_slot):
    pool = []
    seen = set()
    
    # 1. 📂 本地固态 (Local) - 优先级最高
    if os.path.exists(SAVED_IP_FILE):
        with open(SAVED_IP_FILE, "r") as f:
            local_ips = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', f.read())
            # 取最新的 15 个本地优选
            for ip in local_ips[-15:]:
                if ip not in seen:
                    pool.append({"ip": ip, "source": "📂 本地固态"}) # 明确标识
                    seen.add(ip)

    # 2. 🧬 基因衍生 (Genetic)
    if pool:
        # 基于本地最好的IP，生成邻居段
        parents = [n['ip'] for n in pool[:5]]
        for ip in parents:
            subnet = ".".join(ip.split(".")[:3])
            for _ in range(3):
                child = f"{subnet}.{random.randint(1, 254)}"
                if child not in seen:
                    pool.append({"ip": child, "source": "🧬 基因衍生"}) # 明确标识
                    seen.add(child)

    # 3. 🕷️ 全网爬虫 (Crawler)
    if time_slot != "PEAK":
        try:
            # 增加一些对电信友好的 Cloudflare 段 (如 104.16..., 172.64...)
            urls = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
            for u in urls:
                txt = requests.get(u, timeout=3).text
                found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', txt)
                # 随机取 30 个
                for ip in random.sample(found, min(len(found), 30)):
                    if ip not in seen:
                        pool.append({"ip": ip, "source": "🕷️ 全网爬虫"}) # 明确标识
                        seen.add(ip)
        except: pass

    # 4. 🌙 避峰冷门
    if time_slot == "PEAK" or mode == "🌙 晚高峰避峰排位":
        cold_prefixes = ["162.159.36", "162.159.46", "198.41.214"]
        for _ in range(25):
            ip = f"{random.choice(cold_prefixes)}.{random.randint(1, 254)}"
            if ip not in seen:
                pool.append({"ip": ip, "source": "🌙 避峰冷门"})
                seen.add(ip)
                
    return pool

def background_worker():
    while True:
        try:
            cfg = get_config()
            mode = cfg["mode"]
            time_slot = get_time_slot()
            pool = smart_crawler(mode, time_slot)
            
            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
                def process_node(node):
                    ip = node['ip']
                    
                    # 1. 基础连通性 (电信本地)
                    cn_lat = get_china_latency(ip)
                    if cn_lat > 600: return None
                    
                    # 2. 深度 Ping0 测试
                    p0 = ping0_tcp_test(ip)
                    # 电信对丢包极敏感，超过 20% 直接丢弃
                    if p0['loss'] > 20: return None 
                    
                    # 3. 测速
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes=500000", headers={"Host": "speed.cloudflare.com"}, timeout=3)
                        speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    # 4. GPT 与 地区检测
                    geo = get_geo_and_gpt_status(ip)
                    
                    # 5. 算分 (电信定制版)
                    score = calculate_telecom_score(mode, p0['avg'], p0['jitter'], p0['loss'], speed, geo['gpt'])
                    
                    return {
                        "ip": ip, "score": score, "cn_lat": cn_lat, "speed": round(speed, 2),
                        "loss": p0['loss'], "jitter": p0['jitter'], 
                        "source": node['source'], # 核心：保留来源标识
                        "region": geo['region'], "gpt": geo['gpt']
                    }

                futs = [ex.submit(process_node, n) for n in pool]
                for f in concurrent.futures.as_completed(futs):
                    res = f.result()
                    if res and res['score'] > 30: # 稍微放宽一点门槛
                        results.append(res)

            if results:
                results.sort(key=lambda x: x['score'], reverse=True)
                winner = results[0]
                
                # 写入本地库 (供下次循环作为"本地固态"使用)
                with open(SAVED_IP_FILE, "a") as f:
                    for r in results[:3]: f.write(f"{r['ip']}\n")
                
                sync_msg = sync_dns(winner['ip'])
                
                state = {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "time_slot": time_slot,
                    "mode": mode,
                    "winner": winner,
                    "sync_msg": sync_msg,
                    "table": results[:25]
                }
                with open(RESULT_FILE, "w") as f: json.dump(state, f)
                
        except Exception as e: print(f"Worker Error: {e}")
        time.sleep(600)

if "bg_thread" not in st.session_state:
    import threading
    threading.Thread(target=background_worker, daemon=True).start()
    st.session_state.bg_thread = True

# ===========================
# 4. 前端可视化 (四川电信定制UI)
# ===========================
with st.sidebar:
    st.header("🐼 四川电信控制台")
    curr = get_config()
    new_mode = st.radio("排位模式", ["☀️ 正常使用排位", "🌙 晚高峰避峰排位", "🧬 原生IP分数排位"], index=0)
    if new_mode != curr.get("mode"):
        save_config(new_mode)
        st.toast(f"已切换: {new_mode}", icon="🔄")
    
    st.info("💡 提示：'本地固态' IP 来自你历史筛选的优质节点，'全网爬虫' 来自 GitHub 等源。")

st.title("🐼 VLESS 电信 GPT 专版")

if os.path.exists(RESULT_FILE):
    with open(RESULT_FILE, "r") as f: data = json.load(f)
    winner = data['winner']
    df = pd.DataFrame(data['table'])
    
    # 顶部状态
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👑 冠军 IP", winner['ip'])
    c2.metric("🌏 归属/GPT", f"{winner['region']} | {winner['gpt']}")
    c3.metric("📉 电信延迟", f"{winner['cn_lat']} ms", delta=f"-{winner['loss']}% 丢包")
    c4.metric("📊 综合得分", f"{winner['score']}")
    
    st.divider()
    
    # 分类图表
    st.subheader("🧬 IP 来源质量对比")
    # 使用 Altair 图表区分颜色
    st.scatter_chart(
        df, 
        x='cn_lat', 
        y='score', 
        color='source', # 👈 这里通过颜色区分是 本地 还是 爬虫
        size='speed',
        use_container_width=True
    )
    st.caption("👈 左上角为最佳区域 (低延迟 + 高分)")

    # 详细表格
    st.subheader("📋 详细测试报告")
    
    # 定义表格列配置
    col_config = {
        "score": st.column_config.ProgressColumn("得分", format="%.0f", min_value=0, max_value=100),
        "source": st.column_config.TextColumn("来源标签"),
        "region": st.column_config.TextColumn("归属地"),
        "gpt": st.column_config.TextColumn("GPT 资格"),
        "cn_lat": st.column_config.NumberColumn("延迟(ms)", format="%d"),
        "loss": st.column_config.NumberColumn("丢包(%)", format="%d"),
        "speed": st.column_config.NumberColumn("速度(MB/s)", format="%.2f"),
    }
    
    # 展示数据
    st.dataframe(
        df,
        column_order=("score", "ip", "source", "region", "gpt", "cn_lat", "loss", "speed"),
        column_config=col_config,
        use_container_width=True,
        hide_index=True
    )

else:
    st.warning("🐼 正在为四川电信线路进行首次选路与 GPT 检测... 请稍候 20 秒")
    st.progress(0.4)
    time.sleep(5)
    st.rerun()

time.sleep(10)
st.rerun()
