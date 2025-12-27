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
import ssl  # <--- 新增模块
import base64 # <--- 新增模块
from datetime import datetime
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 基础配置 (请填入你的真实 VLESS 信息)
# ===========================
st.set_page_config(page_title="VLESS 四川电信终极版", page_icon="🐼", layout="wide")

# !!! 请在此处填入你的真实节点信息，用于生成订阅 !!!
VLESS_CONFIG = {
    "uuid": "de14b0a2-9f3e-4343-9821-2f3423423423", # 示例 UUID，请修改
    "host": "your.domain.com",                     # 你的伪装域名 (SNI)
    "path": "/ws",                                 # WS 路径
    "port": 443
}

RESULT_FILE = "scan_results.json"
CONFIG_FILE = "app_config.json"
SAVED_IP_FILE = "good_ips.txt"

# ... (CSS 样式保持不变) ...
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    div[data-testid="column"] { background-color: #15171e; border: 1px solid #262730; border-radius: 8px; padding: 15px; }
    .gpt-mode-active { border: 2px solid #2ECC71 !important; }
    </style>
    """, unsafe_allow_html=True)

# ... (get_config, save_config, get_time_slot, get_geo_and_gpt_status 等函数保持不变) ...

# ===========================
# 🚀 新增核心：TLS 握手测试
# ===========================
def check_tls_handshake(ip, sni_host):
    """
    模拟真实的 SSL/TLS 握手。
    如果 IP 被墙或者 SNI 被阻断，这里会报错。
    """
    try:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        # 设置超时 1.5秒 (比 TCP 握手稍长，因为涉及加密交换)
        conn = context.wrap_socket(
            socket.socket(socket.AF_INET),
            server_hostname=sni_host # 关键：发送 SNI
        )
        conn.settimeout(1.5)
        
        t1 = time.perf_counter()
        conn.connect((ip, 443))
        dur = (time.perf_counter() - t1) * 1000
        conn.close()
        return {"status": True, "latency": int(dur)}
    except:
        return {"status": False, "latency": 9999}

# ===========================
# 🚀 新增核心：VLESS 链接生成器
# ===========================
def generate_vless_link(ip, remarks):
    """生成 vless:// 分享链接"""
    # 格式: vless://uuid@ip:443?encryption=none&security=tls&sni=host&type=ws&host=host&path=path#remarks
    c = VLESS_CONFIG
    link = f"vless://{c['uuid']}@{ip}:{c['port']}?encryption=none&security=tls&sni={c['host']}&type=ws&host={c['host']}&path={c['path']}#{remarks}"
    return link

def generate_clash_yaml(ip, remarks):
    """生成 Clash 代理配置段"""
    c = VLESS_CONFIG
    return f"""
  - name: {remarks}
    type: vless
    server: {ip}
    port: {c['port']}
    uuid: {c['uuid']}
    network: ws
    tls: true
    udp: true
    servername: {c['host']}
    ws-opts:
      path: {c['path']}
      headers:
        Host: {c['host']}
    """

# ... (Smart Crawler 爬虫部分保持不变) ...

# ... (ping0_tcp_test, get_china_latency 等保持不变) ...
# 为了节省篇幅，这里复用你上一版的函数，只修改 background_worker 和 算分逻辑

# 修正后的评分算法，加入 TLS 权重
def calculate_score_v2(mode, avg, jitter, loss, speed, gpt_status, tls_ok):
    if not tls_ok: return 0 # TLS 握手失败，直接归零 (伪通IP)
    
    score = 100.0
    # ... (原有逻辑) ...
    loss_penalty = 6 if mode != "🤖 GPT 独享专线" else 4
    score -= (loss * loss_penalty)
    
    limit = 280 if mode == "🤖 GPT 独享专线" else 180
    if avg > limit: score -= (avg - limit) / 5
    
    score -= jitter * 1.5
    score += min(speed * 3, 30)
    
    if mode == "🤖 GPT 独享专线":
        if gpt_status == "✅ 支持": score += 10
        else: return 0 # GPT 模式下不支持 GPT 也不要
    
    return max(0, round(score, 1))

# ===========================
# 3. 后台 Worker (集成 TLS 测试)
# ===========================
def background_worker():
    while True:
        try:
            cfg = get_config(); mode = cfg["mode"]; time_slot = get_time_slot()
            pool = smart_crawler(mode, time_slot) # 假设 smart_crawler 已定义
            
            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
                def process_node(node):
                    ip = node['ip']
                    
                    # 1. 基础国测 TCP
                    cn_lat = get_china_latency(ip) # 假设已定义
                    if cn_lat > 600: return None
                    
                    # 2. 🔥 新增：TLS 握手真连接测试
                    # 使用你的真实域名测试，防止 SNI 阻断
                    tls = check_tls_handshake(ip, VLESS_CONFIG['host'])
                    if not tls['status']: return None # 握手失败，这是个假 IP
                    
                    # 3. 测速
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes=200000", headers={"Host": "speed.cloudflare.com"}, timeout=2)
                        speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    # 4. Geo & GPT
                    geo = get_geo_and_gpt_status(ip) # 假设已定义
                    
                    # 5. Ping0
                    p0 = ping0_tcp_test(ip) # 假设已定义
                    if p0['loss'] > 25: return None
                    
                    # 6. 算分
                    score = calculate_score_v2(mode, p0['avg'], p0['jitter'], p0['loss'], speed, geo['gpt'], True)
                    
                    if score <= 0: return None
                    
                    return {
                        "ip": ip, "score": score, "cn_lat": cn_lat, "speed": round(speed, 2),
                        "loss": p0['loss'], "jitter": p0['jitter'], 
                        "source": node['source'], "region": geo['region'], "gpt": geo['gpt'],
                        "tls_lat": tls['latency'] # 记录 TLS 延迟
                    }

                futs = [ex.submit(process_node, n) for n in pool]
                for f in concurrent.futures.as_completed(futs):
                    res = f.result()
                    if res: results.append(res)

            if results:
                results.sort(key=lambda x: x['score'], reverse=True)
                winner = results[0]
                
                # ... (入库和 DNS 同步逻辑保持不变) ...
                with open(SAVED_IP_FILE, "a") as f:
                    for r in results[:3]: f.write(f"{r['ip']}\n")
                
                sync_dns(winner['ip']) # 假设已定义

                state = {"last_run": datetime.now().strftime("%H:%M:%S"), "time_slot": time_slot, "mode": mode, "winner": winner, "sync_msg": "已同步", "table": results[:25]}
                with open(RESULT_FILE, "w") as f: json.dump(state, f)
                
        except Exception as e: print(f"Worker Error: {e}")
        time.sleep(300 if mode == "🤖 GPT 独享专线" else 600)

# 启动线程
if "bg_thread" not in st.session_state:
    import threading
    threading.Thread(target=background_worker, daemon=True).start()
    st.session_state.bg_thread = True

# ===========================
# 4. 前端展示 (集成订阅生成)
# ===========================
# ... (侧边栏逻辑保持不变) ...
with st.sidebar:
    st.header("🐼 四川电信控制台")
    curr = get_config()
    new_mode = st.radio("排位模式", ["☀️ 正常使用排位", "🌙 晚高峰避峰排位", "🤖 GPT 独享专线"], index=0)
    if new_mode != curr.get("mode"):
        save_config(new_mode)
        st.toast(f"模式切换: {new_mode}", icon="🚀")

st.title("🐼 VLESS 电信 GPT 终极版")

if os.path.exists(RESULT_FILE):
    with open(RESULT_FILE, "r") as f: data = json.load(f)
    winner = data['winner']
    df = pd.DataFrame(data['table'])
    
    # 顶部状态
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👑 冠军 IP", winner['ip'])
    c2.metric("🔒 TLS 握手", f"{winner['tls_lat']} ms", delta="真连接")
    c3.metric("📉 延迟/丢包", f"{winner['cn_lat']}ms / {winner['loss']}%")
    c4.metric("📊 得分", f"{winner['score']}")
    
    st.divider()

    # 🔥 新增区域：一键订阅
    st.subheader("🔗 节点订阅")
    
    # 生成链接
    vless_url = generate_vless_link(winner['ip'], f"四川电信优选_{data['last_run']}")
    clash_cfg = generate_clash_yaml(winner['ip'], f"四川电信优选_{data['last_run']}")
    
    tab_link, tab_clash = st.tabs(["🚀 VLESS 链接", "🐱 Clash 配置"])
    
    with tab_link:
        st.code(vless_url, language="text")
        st.caption("复制上方链接，在 V2RayN / v2box 中从剪贴板导入即可。")
        
    with tab_clash:
        st.code(clash_cfg, language="yaml")
        st.caption("复制上方文本，追加到你的 Clash 配置文件 proxies 部分。")

    st.divider()
    
    # ... (散点图和表格逻辑保持不变) ...
    st.subheader("🧬 节点分布图")
    st.scatter_chart(df, x='cn_lat', y='score', color='gpt', size='speed', use_container_width=True)

    st.subheader("📋 详细报告 (已过滤 TLS 阻断)")
    st.dataframe(
        df,
        column_order=("score", "ip", "gpt", "tls_lat", "cn_lat", "loss", "speed", "source"),
        column_config={
            "tls_lat": st.column_config.NumberColumn("TLS握手", format="%d ms"),
            "score": st.column_config.ProgressColumn("得分", format="%.0f", min_value=0, max_value=100),
            "cn_lat": st.column_config.NumberColumn("TCP延迟", format="%d ms"),
            # ... 其他配置 ...
        },
        use_container_width=True,
        hide_index=True
    )

else:
    st.warning("🐼 系统升级中：正在进行 TLS 真连接探测... 首次运行稍慢")
    time.sleep(5)
    st.rerun()

time.sleep(10)
st.rerun()
