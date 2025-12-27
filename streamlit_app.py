import streamlit as st
import requests
import time
import re
import random
import os
from datetime import datetime

# --- 1. 基础页面设置 ---
st.set_page_config(page_title="CF 安全调试台", page_icon="🔧", layout="centered")

st.title("🔧 Cloudflare 安全调试模式")
st.write("如果看到这段文字，说明程序已成功启动。")

# --- 2. 逐步读取配置 (带状态显示) ---
st.info("第一步：读取 Secrets 配置...")

try:
    # 强制去除首尾空格，防止复制错误
    TOKEN = st.secrets["api_token"].strip()
    ZONE_ID = st.secrets["zone_id"].strip()
    RECORD = st.secrets["record_name"].strip()
    
    # 这里的打印是为了让你确认读到了什么（注意：Token 已脱敏显示前4位）
    st.text(f"配置状态：\nToken: {TOKEN[:4]}******\nZone ID: {ZONE_ID}\n域名: {RECORD}")
    st.success("✅ 配置读取成功！")
    
except Exception as e:
    st.error(f"❌ 配置读取失败！请检查 Secrets。\n报错信息: {e}")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 功能函数 ---

def manual_sync(ip):
    """手动触发同步，不自动运行"""
    url = f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    try:
        st.write(f"正在云端搜索记录: {RECORD} ...")
        # 1. 搜索
        search = requests.get(url, headers=headers, params={"name": RECORD, "type": "A"}, timeout=10).json()
        
        if not search.get("success"):
            st.error(f"API 请求被拒: {search.get('errors')}")
            return
            
        if not search.get("result"):
            st.warning(f"⚠️ 找不到记录 [{RECORD}]！")
            st.write("正在列出该 Zone ID 下真实存在的前 5 条记录，请核对：")
            # 调试：列出真实记录
            debug_recs = requests.get(url, headers=headers, params={"per_page": 5}).json()
            for r in debug_recs['result']:
                st.code(f"记录名: {r['name']} | 类型: {r['type']}")
            return

        # 2. 更新
        record_id = search["result"][0]["id"]
        st.write(f"找到记录 ID: {record_id}，正在更新指向 -> {ip}")
        
        update = requests.put(f"{url}/{record_id}", headers=headers, json={
            "type": "A", "name": RECORD, "content": ip, "ttl": 60, "proxied": False
        }).json()
        
        if update.get("success"):
            st.balloons()
            st.success(f"🚀 同步成功！域名 [{RECORD}] 已指向 {ip}")
        else:
            st.error(f"同步失败: {update}")
            
    except Exception as e:
        st.error(f"网络通信错误: {e}")

def get_ips():
    try:
        r = requests.get("https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt", timeout=5)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        return random.sample(list(found), 5)
    except:
        return ["108.162.194.1", "172.64.32.12"] # 备用 IP

# --- 4. 主操作区 ---

st.divider()
st.header("手动操作区")

# 只有点击按钮才会执行，防止自动卡死
if st.button("🚀 开始优选并同步 (点我运行)"):
    
    with st.status("正在执行任务...", expanded=True) as status:
        st.write("1. 正在获取全球 IP 池...")
        ips = get_ips()
        st.write(f"获取到 {len(ips)} 个待测节点")
        
        best_ip = None
        min_lat = 9999
        
        st.write("2. 开始测速...")
        for ip in ips:
            try:
                start = time.time()
                requests.head(f"http://{ip}", headers={"Host": RECORD}, timeout=0.5)
                lat = int((time.time() - start) * 1000)
                st.write(f"节点 {ip} -> 延迟 {lat}ms")
                if lat < min_lat:
                    min_lat = lat
                    best_ip = ip
            except:
                pass
        
        if best_ip:
            st.success(f"🏆 本轮冠军: {best_ip} (延迟 {min_lat}ms)")
            manual_sync(best_ip)
        else:
            st.error("所有节点均超时，请重试")
            
        status.update(label="任务完成", state="complete")

# 历史记录查看
if os.path.exists(DB_FILE):
    st.divider()
    st.caption("历史日志")
    with open(DB_FILE, "r") as f:
        st.text(f.read())
