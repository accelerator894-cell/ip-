import streamlit as st
import requests
import threading
import time
import urllib.parse
from datetime import datetime

# ==========================================
# 1. 配置中心
# ==========================================
CF_CONFIG = {
    "api_token": "92os9FwyeG7jQDYpD6Rb0Cxrqu5YjtUjGfY1xKBm", 
    "zone_id": "7aa1c1ddfd9df2690a969d9f977f82ae",
    "record_name": "speed.milet.qzz.io", 
}

VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.136.0:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@188.114.97.1:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@141.101.120.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#%E7%BE%8E%E5%9B%BD70",
]

# ==========================================
# 2. 自动化管理逻辑 (优化版)
# ==========================================
class ProOptimizer:
    def __init__(self, config, links):
        self.config = config
        self.links = links
        self.token = str(config.get("api_token", "")).strip()
        self.headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        self.best_ip = "188.114.97.1"
        self.current_latency = 999
        self.last_update = datetime.now().strftime("%H:%M:%S")
        self.status_log = []

    def log(self, message, type="info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_log.append({"time": timestamp, "msg": message, "type": type})
        if len(self.status_log) > 12: self.status_log.pop(0)

    def get_average_latency(self, ip, count=3):
        """多次测速取平均值，排除抖动"""
        latencies = []
        for _ in range(count):
            try:
                start = time.time()
                # 使用 verify=False 忽略 SSL 证书校验，加快测速速度
                requests.get(f"https://{ip}", timeout=1.2, verify=False)
                latencies.append((time.time() - start) * 1000)
                time.sleep(0.1) # 两次测试间稍作停顿
            except:
                continue
        return int(sum(latencies) / len(latencies)) if latencies else 9999

    def update_cf_dns(self, new_ip, new_latency):
        """带有阈值保护的更新逻辑"""
        # 优化点：如果新 IP 提升不明显 (小于 20ms)，则不更新以保持连接稳定
        if self.best_ip == new_ip:
            self.log(f"✅ IP 未变动，当前延迟: {new_latency}ms", "success")
            return True
            
        diff = self.current_latency - new_latency
        if diff < 20 and self.current_latency != 999:
            self.log(f"⚖️ 提升仅 {diff}ms (不足20ms)，放弃切换以保持稳定", "info")
            return True

        base_url = "https://api.cloudflare.com/client/v4"
        try:
            self.log(f"🛰️ 提升明显 ({diff}ms)，正在同步 CF...", "info")
            list_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records?name={self.config['record_name']}"
            res = requests.get(list_url, headers=self.headers, timeout=10).json()
            
            if res.get("success") and res.get("result"):
                record = res["result"][0]
                update_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records/{record['id']}"
                data = {"type": "A", "name": self.config['record_name'], "content": new_ip, "ttl": 60, "proxied": False}
                put_res = requests.put(update_url, headers=self.headers, json=data, timeout=10).json()
                
                if put_res.get("success"):
                    self.log(f"🚀 同步成功: {new_ip} ({new_latency}ms)", "success")
                    return True
            return False
        except Exception as e:
            self.log(f"⚠️ 更新异常: {str(e)}", "error")
            return False

    def run_loop(self):
        while True:
            self.log("🔄 开启专业级巡检 (多次采样模式)...", "info")
            ips = list(set([urllib.parse.urlparse(l).netloc.split('@')[-1].split(':')[0] for l in self.links if l.startswith("vless")]))
            
            results = []
            for ip in ips:
                avg_l = self.get_average_latency(ip)
                if avg_l < 2000:
                    results.append((ip, avg_l))
            
            if results:
                results.sort(key=lambda x: x[1])
                top_ip, top_latency = results[0]
                self.log(f"🏆 筛选完成: {top_ip} (平均 {top_latency}ms)", "info")
                
                if self.update_cf_dns(top_ip, top_latency):
                    self.best_ip = top_ip
                    self.current_latency = top_latency
                    self.last_update = datetime.now().strftime("%H:%M:%S")
            
            time.sleep(600)

# ==========================================
# 3. Streamlit UI
# ==========================================
def main():
    st.set_page_config(page_title="CF 优选 Pro", layout="centered")
    st.title("🛡️ 自动优选同步系统 Pro")

    if 'pro_opt' not in st.session_state:
        st.session_state.pro_opt = ProOptimizer(CF_CONFIG, VLESS_LINKS)
        threading.Thread(target=st.session_state.pro_opt.run_loop, daemon=True).start()

    opt = st.session_state.pro_opt

    c1, c2, c3 = st.columns(3)
    c1.metric("当前 IP", opt.best_ip)
    c2.metric("平均延迟", f"{opt.current_latency}ms")
    c3.metric("最后更新", opt.last_update)

    st.divider()
    st.subheader("⚙️ 智能运行日志")
    for entry in reversed(opt.status_log):
        m = f"[{entry['time']}] {entry['msg']}"
        if entry['type'] == "success": st.success(m)
        elif entry['type'] == "error": st.error(m)
        else: st.code(m)

    time.sleep(10)
    st.rerun()

if __name__ == "__main__":
    main()
