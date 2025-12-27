import streamlit as st
import requests
import time
import re
import random
import os
import pandas as pd
import concurrent.futures
from datetime import datetime

# ===========================
# 1. 页面配置
# ===========================
st.set_page_config(page_title="VLESS 爬虫调试版", page_icon="🕷️", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #FAFAFA; }
    div[data-testid="column"] { background-color: #1E1E1E; border: 1px solid #333; border-radius: 8px; padding: 15px; }
    /* 侧边栏样式 */
    section[data-testid="stSidebar"] { background-color: #161920; }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 配置读取
# ===========================
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except:
    st.error("❌ 配置缺失！请检查 secrets.toml")
    st.stop()

DB_FILE = "scan_history.log"

# ===========================
# 3. 核心功能
# ===========================

@st.cache_data(ttl=3600)
def get_ip_info(ip):
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country"
        r = requests.get(url, timeout=2).json()
        cc = r.get("countryCode", "UNK")
        if cc in ['CN', 'HK', 'TW', 'JP', 'KR', 'SG']: return "🌏 亚洲", r.get("country")
        if cc in ['US', 'CA', 'MX']: return "🇺🇸 美洲", r.get("country")
        if cc in ['DE', 'GB', 'FR', 'NL', 'EU']: return "🇪🇺 欧洲", r.get("country")
        return "🌍 其他", r.get("country")
    except:
        return "🛸 未知", "Unknown"

def fetch_ips_from_source(source_url, source_name):
    """带调试信息的单源抓取"""
    try:
        # 增加超时时间到 5 秒
        r = requests.get(source_url, timeout=5)
        if r.status_code == 200:
            found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
            unique_ips = list(set(found))
            return unique_ips, f"✅ 成功 ({len(unique_ips)}个)"
        else:
            return [], f"❌ 状态码 {r.status_code}"
    except Exception as e:
        return [], f"❌ 错误: {str(e)[:20]}..."

def get_collected_ips_debug():
    """多源采集器 (带侧边栏报告)"""
    sources = [
        # 官方源 (最稳)
        {"url": "https://www.cloudflare.com/ips-v4", "name": "Cloudflare官方"},
        # GitHub 源 (容易挂)
        {"url": "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt", "name": "Github源-Alvin"},
        {"url": "https://raw.githubusercontent.com/w8ves/CF-IP/master/speedtest.txt", "name": "Github源-Waves"},
    ]
    
    all_ips = set()
    report = []
    
    with st.sidebar:
        st.header("🕷️ 爬虫状态报告")
        for src in sources:
            ips, status = fetch_ips_from_source(src["url"], src["name"])
            all_ips.update(ips)
            # 显示每个源的状态
            if "✅" in status:
                st.success(f"{src['name']}: {status}")
            else:
                st.error(f"{src['name']}: {status}")
        
        st.divider()
        st.info(f"∑ 总计去重后: {len(all_ips)} 个 IP")
    
    # 无论抓到多少，都只随机取 50 个测速，防止超时
    final_list = list(all_ips)
    if len(final_list) > 50:
        return random.sample(final_list, 50)
    return final_list

def fast_ping(ip):
    try:
        start = time.time()
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.5)
        return int((time.time() - start) * 1000)
    except: return 9999

def sync_dns(ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        recs = requests.get(url, headers=headers, params=params, timeout=5).json()
        if not recs.get("result"): return "❌ 无记录"
        rid = recs["result"][0]["id"]
        if recs["result"][0]["content"] == ip: return "✅ IP未变"
        requests.put(f"{url}/{rid}", headers=headers, json={
            "type": "A", "name": CF_CONFIG['record_name'], "content": ip, "ttl": 60, "proxied": False
        })
        return f"🚀 已同步: {ip}"
    except Exception as e: return f"⚠️ API错误"

# ===========================
# 4. 主程序
# ===========================

st.title("🕷️ VLESS 爬虫修复版")

# 侧边栏手动触发
st.sidebar.button("🔄 刷新爬虫数据")

if st.button("🚀 开始混合扫描", type="primary"):
    
    # 1. 获取 IP (这一步会更新侧边栏状态)
    collected_ips = get_collected_ips_debug()
    local_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    
    # 2. 准备任务
    tasks = []
    for ip in local_ips: tasks.append({"ip": ip, "source": "🏠 本地预设"})
    for ip in collected_ips: tasks.append({"ip": ip, "source": "☁️ 网络采集"})
    
    st.toast(f"开始测速 {len(tasks)} 个节点...")

    # 3. 并发测速
    results = []
    progress_bar = st.progress(0)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        future_map = {ex.submit(fast_ping, t['ip']): t for t in tasks}
        completed = 0
        for fut in concurrent.futures.as_completed(future_map):
            node = future_map[fut]
            lat = fut.result()
            completed += 1
            progress_bar.progress(completed / len(tasks))
            
            # 放宽限制：只要不是超时(9999)，哪怕延迟高也显示出来，证明爬虫活着
            if lat < 2000: 
                # 只有低延迟才查地理位置，省时间
                if lat < 800:
                    reg, ctry = get_ip_info(node['ip'])
                else:
                    reg, ctry = "🐢 高延迟", "Unknown"
                
                node.update({"lat": lat, "region": reg, "country": ctry})
                results.append(node)
                
    progress_bar.empty()

    # 4. 结果展示
    if results:
        results.sort(key=lambda x: x['lat'])
        winner = results[0]
        sync_msg = sync_dns(winner['ip'])
        
        c1, c2 = st.columns([3, 1])
        with c1: st.success(f"🏆 优选: **{winner['ip']}** ({winner['lat']}ms)")
        with c2: st.info(sync_msg)
        
        # 表格
        st.divider()
        df = pd.DataFrame(results)
        
        # 简单统计
        source_counts = df['source'].value_counts()
        st.caption(f"📊 统计: 本地节点 {source_counts.get('🏠 本地预设', 0)} 个 | 采集节点 {source_counts.get('☁️ 网络采集', 0)} 个")
        
        st.dataframe(
            df[["source", "ip", "lat", "region", "country"]].rename(columns={"lat":"延迟", "ip":"IP"}),
            use_container_width=True,
            hide_index=True
        )
        
        # 写入日志
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%H:%M')} | {winner['ip']} | {winner['lat']}ms\n")
            
    else:
        st.error("❌ 所有节点均无法连接")
        
else:
    st.info("👈 请查看左侧侧边栏的爬虫状态，确认是否有 IP 被抓取。")
    st.warning("提示：如果 Github 源全红，说明你的运行环境无法访问 GitHub。但我已添加 Cloudflare 官方源作为保底。")

# 历史日志
with st.expander("📜 历史记录"):
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f: st.text("".join(f.readlines()[-5:]))
