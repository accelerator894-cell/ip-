import streamlit as st
import requests
import time
from datetime import datetime

# ... (CF_CONFIG 保持不变) ...

def check_ip_quality(ip):
    """
    多维度质量检测：延迟 + 稳定性 + 速度
    """
    quality = {"ip": ip, "lat": 9999, "loss": 100, "speed": 0}
    latencies = []
    success_count = 0
    test_rounds = 3  # 进行3轮采样
    
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Host": "milet.qzz.io" # 模拟你的真实域名
    }

    try:
        # 1. 延迟与丢包率检测 (采样 3 次)
        for _ in range(test_rounds):
            try:
                start = time.time()
                # 测试 CF 官方节点链路状态
                res = requests.get(f"http://{ip}/cdn-cgi/trace", headers=headers, timeout=1.5)
                if res.status_code == 200:
                    latencies.append(int((time.time() - start) * 1000))
                    success_count += 1
            except:
                continue
        
        if success_count > 0:
            quality["lat"] = sum(latencies) / len(latencies) # 平均延迟
            quality["loss"] = ((test_rounds - success_count) / test_rounds) * 100 # 丢包率
            
            # 2. 模拟小文件测速 (仅对低延迟且无丢包的 IP 进行)
            if quality["loss"] == 0:
                speed_start = time.time()
                # 尝试从该 IP 下载 100KB 的小块（CF 缓存节点测速）
                speed_res = requests.get(f"https://{ip}/cdn-cgi/trace", headers=headers, timeout=2.0)
                duration = time.time() - speed_start
                # 这里简单记为：响应时间越短，速度分值越高
                quality["speed"] = round(1 / duration, 2) 

        return quality
    except:
        return quality

# --- 页面执行 ---
st.title("⚡ 深度优选引擎 (多维质检版)")

with st.spinner("📊 正在进行多维度深度质检 (延迟/丢包/速度)..."):
    results = []
    for ip in IP_LIST:
        q_data = check_ip_quality(ip)
        if q_data["lat"] < 9999: # 只记录通畅的 IP
            results.append(q_data)
    
    if results:
        # 排序逻辑：优先按丢包率，其次按延迟，最后按速度
        results.sort(key=lambda x: (x['loss'], x['lat'], -x['speed']))
        winner = results[0]
        
        # 页面显示增强
        st.success(f"🎯 深度优选成功: {winner['ip']}")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("平均延迟", f"{int(winner['lat'])}ms")
        col2.metric("丢包率", f"{winner['loss']}%", delta="稳定" if winner['loss']==0 else "不稳")
        col3.metric("速度分值", winner['speed'])
        
        # 执行 DNS 更新 (函数复用之前的)
        update_dns(winner['ip'])
    else:
        st.error("❌ 所有 IP 质检均不合格，请检查 IP 列表或云端网络。")

st.info(f"🕒 质检完成时间: {datetime.now().strftime('%H:%M:%S')}")