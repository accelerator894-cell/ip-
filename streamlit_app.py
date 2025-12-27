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
# 1. 页面配置与样式
# ===========================
st.set_page_config(page_title="VLESS 全能监控指挥台", page_icon="🛸", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    div[data-testid="column"] { background-color: #15171e; border: 1px solid #262730; border-radius: 8px; padding: 15px; }
    </style>
    """, unsafe_allow_html=True)

# 文件路径定义
RESULT_FILE = "scan_results.json"  # 存放给前端展示的结果
CONFIG_FILE = "app_config.json"    # 存放用户的模式设置
SAVED_IP_FILE = "good_ips.txt"     # 本地优选历史库 (你要求的本地数据筛选)

# ===========================
# 2. 基础工具函数 (所有原版逻辑回归)
# ===========================

def get_config():
    """读取用户设置的模式"""
    default = {"mode": "☀️ 正常使用排位"}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f: return json.load(f)
        except: return default
    return default

def save_config(mode):
    """保存模式设置，供后台线程读取"""
    with open(CONFIG_FILE, "w") as f:
        json.dump({"mode": mode}, f)

def generate_cold_ips(count=30):
    """【回归】冷门 IP 生成器 (避峰模式专用)"""
    prefixes = ["162.159.36", "162.159.46", "198.41.214", "172.64.198", "103.21.244"]
    return [f"{random.choice(prefixes)}.{random.randint(1, 254)}" for _ in range(count)]

def get_ip_extended_info(ip):
    """【回归】查询 ISP 和是否原生 (流媒体模式专用)"""
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=country,isp,hosting", timeout=2.0).json()
        return {
            "country": r.get("country", "Unk"),
            "isp": r.get("isp", "Unk"),
            "is_native": not r.get("hosting", True) # hosting=False 即为原生
        }
    except: return {"country": "Unk", "isp": "Unk", "is_native": False}

def get_china_latency(ip):
    """【保留】中国连通性模拟测试"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5) # 500ms 超时
        t1 = time.perf_counter()
        s.connect((ip, 443))
        dur = (time.perf_counter() - t1) * 1000
        s.close()
        return int(dur)
    except: return 999

def sync_dns(ip):
    """Cloudflare DNS 同步"""
    try:
        if "api_token" not in st.secrets: return "⚠️ 未配置 Secrets"
        cfg = st.secrets
        url = f"https://api.cloudflare.com/client/v4/zones/{cfg['zone_id']}/dns_records"
        headers = {"Authorization": f"Bearer {cfg['api_token']}", "Content-Type": "application/json"}
        # 获取记录
        recs = requests.get(url, headers=headers, params={"name": cfg['record_name']}, timeout=5).json()
        if recs["result"]:
            rid = recs["result"][0]["id"]
            current_ip = recs["result"][0]["content"]
            if current_ip == ip: return f"✅ IP未变 ({ip})"
            # 更新记录
            requests.put(f"{url}/{rid}", headers=headers, json={"type":"A","name":cfg['record_name'],"content":ip,"ttl":60,"proxied":False})
            return f"🚀 已切换: {current_ip} ➔ {ip}"
    except Exception as e: return f"❌ API错误: {str(e)[:10]}"
    return "⚠️ 记录未找到"

# ===========================
# 3. 后台智能守护线程 (融合逻辑核心)
# ===========================

def background_manager():
    """后台管家：根据 Config 模式，智能调度爬虫和测试"""
    while True:
        try:
            # A. 读取当前模式
            cfg = get_config()
            mode = cfg["mode"]
            
            # B. 构建候选池 (融合：历史 + 爬虫 + 冷门)
            pool = []
            seen = set()
            
            # 1. 本地历史回捞 (Local Data Analysis)
            if os.path.exists(SAVED_IP_FILE):
                with open(SAVED_IP_FILE, "r") as f:
                    hist_ips = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', f.read())
                    # 取最后存入的 20 个历史优选
                    for ip in hist_ips[-20:]:
                        if ip not in seen:
                            pool.append({"ip": ip, "type": "history"})
                            seen.add(ip)

            # 2. 爬虫抓取 (Hot IPs)
            urls = ["https://www.cloudflare.com/ips-v4", "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
            crawled_ips = []
            for u in urls:
                try:
                    crawled_ips.extend(re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', requests.get(u, timeout=5).text))
                except: pass
            
            # 随机取 30 个热门 IP
            if crawled_ips:
                for ip in random.sample(crawled_ips, min(len(crawled_ips), 30)):
                    if ip not in seen:
                        pool.append({"ip": ip, "type": "hot"})
                        seen.add(ip)

            # 3. 模式特供：避峰模式注入冷门 IP
            if mode == "🌙 晚高峰避峰排位":
                cold_ips = generate_cold_ips(30)
                for ip in cold_ips:
                    if ip not in seen:
                        pool.append({"ip": ip, "type": "cold"})
                        seen.add(ip)

            # C. 多线程深度测试
            results = []
            # 限制并发数为 25，平衡速度与准确性
            with concurrent.futures.ThreadPoolExecutor(max_workers=25) as ex:
                def run_full_logic(node):
                    ip = node['ip']
                    
                    # 1. 国测 (必须)
                    cn_lat = get_china_latency(ip)
                    if cn_lat > 800: return None # 连不通直接丢弃

                    # 2. 模式特判：原生检测 (流媒体模式)
                    info = {"is_native": False, "isp": "Unk"}
                    if mode == "🧬 原生IP分数排位":
                        info = get_ip_extended_info(ip)
                        # 如果是原生模式但IP非原生，直接大幅扣分或丢弃，这里选择保留但低分
                    
                    # 3. 测速 (使用 500KB 小文件平衡速度)
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes=500000", headers={"Host": "speed.cloudflare.com"}, timeout=3)
                        speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    # 4. 动态评分引擎 (核心回归)
                    score = 100
                    # 基础分
                    score -= (cn_lat / 5) 
                    score += (speed * 20)
                    
                    # 模式加成
                    if mode == "🌙 晚高峰避峰排位":
                        if node['type'] == "cold": score += 30 # 冷门IP加分
                        score -= (cn_lat / 2) # 对延迟更敏感
                        
                    elif mode == "🧬 原生IP分数排位":
                        if info['is_native']: score += 500 # 原生IP巨额加分
                        else: score -= 200
                        
                    elif node['type'] == "history":
                        score += 10 # 历史表现好的微量加分
                        
                    return {
                        "ip": ip, "score": round(score, 1), "cn_lat": cn_lat, 
                        "speed": round(speed, 2), "type": node['type'], 
                        "is_native": info.get('is_native', False)
                    }

                futs = [ex.submit(run_full_logic, n) for n in pool]
                for f in concurrent.futures.as_completed(futs):
                    res = f.result()
                    if res: results.append(res)
            
            # D. 结算与保存
            if results:
                results.sort(key=lambda x: x['score'], reverse=True)
                winner = results[0]
                
                # 1. 将好的 IP 存入本地历史 (Local Data Filter)
                good_ips = [r['ip'] for r in results if r['score'] > 0]
                with open(SAVED_IP_FILE, "a") as f: # 追加模式
                    for ip in good_ips[:3]: # 只存前3名
                        f.write(f"{ip}\n")
                
                # 2. 去重并限制历史文件大小 (防止无限膨胀)
                # (略：简单的做法是定期清理，这里先保留追加逻辑)

                # 3. 同步 DNS
                sync_msg = sync_dns(winner['ip'])
                
                # 4. 写 JSON 给前端
                save_data = {
                    "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "mode_used": mode,
                    "winner": winner,
                    "sync_msg": sync_msg,
                    "table": results[:20]
                }
                with open(RESULT_FILE, "w") as f:
                    json.dump(save_data, f)
                    
        except Exception as e:
            print(f"Worker Exception: {e}")
        
        time.sleep(600) # 10分钟循环

# 启动后台线程
if "bg_thread" not in st.session_state:
    import threading
    t = threading.Thread(target=background_manager, daemon=True)
    t.start()
    st.session_state.bg_thread = True

# ===========================
# 4. 前端交互与可视化 (融合)
# ===========================

# --- Sidebar: 找回控制权 ---
with st.sidebar:
    st.header("🎮 控制中心")
    curr_conf = get_config()
    
    # 模式选择回归
    new_mode = st.radio(
        "选择排位策略", 
        ["☀️ 正常使用排位", "🌙 晚高峰避峰排位", "🧬 原生IP分数排位"],
        index=["☀️ 正常使用排位", "🌙 晚高峰避峰排位", "🧬 原生IP分数排位"].index(curr_conf.get("mode", "☀️ 正常使用排位"))
    )
    
    if new_mode != curr_conf.get("mode"):
        save_config(new_mode)
        st.toast(f"策略已切换为 [{new_mode}]，将在下轮后台扫描生效", icon="🔄")
    
    st.info("后台线程每 10 分钟自动执行一次。")

# --- Main Dashboard ---
st.title("🛸 VLESS 全能监控指挥台")

if os.path.exists(RESULT_FILE):
    with open(RESULT_FILE, "r") as f:
        data = json.load(f)
    
    winner = data['winner']
    df = pd.DataFrame(data['table'])
    
    # 状态栏
    st.markdown(f"**当前状态**: `{data['mode_used']}` | **更新时间**: `{data['last_run']}`")
    
    # 指标卡
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👑 冠军 IP", winner['ip'])
    c2.metric("🌏 中国延迟", f"{winner['cn_lat']} ms", delta_color="inverse")
    c3.metric("⚡ 下载速度", f"{winner['speed']} MB/s")
    c4.metric("☁️ DNS 状态", data['sync_msg'])
    
    st.divider()
    
    # 可视化图表区
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.subheader("📊 综合评分 Top 10")
        if not df.empty:
            chart_data = df.head(10).set_index("ip")
            st.bar_chart(chart_data['score'], color="#0074D9")
    
    with col_right:
        st.subheader("🎯 延迟/速度 分布图")
        if not df.empty:
            st.scatter_chart(
                df, x='cn_lat', y='speed', 
                color='type', size='score', 
                use_container_width=True
            )
            st.caption("💡 提示：点越靠左上角越好 (低延迟+高速度)")

    # 详细数据表
    st.subheader("📋 详细扫描报告")
    
    # 配置列显示，增加原生标识
    col_cfg = {
        "score": st.column_config.ProgressColumn("评分", format="%.1f", min_value=0, max_value=1200),
        "cn_lat": st.column_config.NumberColumn("CN延迟", format="%d ms"),
        "speed": st.column_config.NumberColumn("速度", format="%.2f MB/s"),
        "type": st.column_config.TextColumn("来源"),
        "is_native": st.column_config.CheckboxColumn("原生解锁?")
    }
    
    st.dataframe(
        df, 
        column_order=("score", "ip", "cn_lat", "speed", "type", "is_native"),
        column_config=col_cfg, 
        use_container_width=True,
        hide_index=True
    )

else:
    st.warning("📡 后台正在初始化数据... 请稍等 10-20 秒")
    st.info(f"当前模式: {get_config()['mode']}")
    st.progress(0.4, text="正在混合历史数据与新爬取节点...")
    time.sleep(5)
    st.rerun()

# 自动刷新 UI (只刷新看数据，不重跑)
time.sleep(10)
st.rerun()
