import streamlit as st
import requests
import threading
import time
import urllib.parse
from datetime import datetime

# ==========================================
# 1. 配置中心 (请替换为你的实际信息)
# ==========================================
CF_CONFIG = {
    "api_token": "92os9FwyeG7jQDYpD6Rb0Cxrqu5YjtUjGfY1xKBm",
    "7aa1c1ddfd9df2690a969d9f977f82ae": "",
    "efc4c37be906c8a19a67808e51762c1f": "speed",  # 你要更新的二级域名
}

# 你提供的 VLESS 链接列表（支持粘贴多个）
VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.136.0:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@188.114.97.1:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@141.101.120.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#%E7%BE%8E%E5%9B%BD70",
    # ... 你可以继续添加更多链接
]

# ==========================================
# 2. 核心逻辑类 (API + 测速 + 自动化)
# ==========================================
class AutoOptimizer:
    def __init__(self, config, links):
        self.config = config
        self.links = links
        self.headers = {
            "Authorization": f"Bearer {config['api_token']}",
            "Content-Type": "application/json"
        }
        self.best_ip = "等待测速..."
        self.last_update = "尚未运行"
        self.status_log = []
        self.is_running = False

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_log.append(f"[{timestamp}] {message}")
        if len(self.status_log) > 15: self.status_log.pop(0)

    def parse_ips(self):
        """解析 VLESS 列表提取 IP"""
        ips = []
        for link in self.links:
            try:
                parts = urllib.parse.urlparse(link)
                ip = parts.netloc.split('@')[-1].split(':')[0]
                ips.append(ip)
            except: continue
        return list(set(ips))

    def get_latency(self, ip):
        """测试 IP 延迟 (TCP 连接测试)"""
        try:
            start = time.time()
            # 使用较小的 timeout 快速跳过无效 IP
            requests.get(f"https://{ip}", timeout=1.5, verify=False)
            return int((time.time() - start) * 1000)
        except:
            return 9999

    def update_cf_dns(self, ip):
        """更新 Cloudflare DNS 记录"""
        base_url = "https://api.cloudflare.com/client/v4"
        # 1. 获取记录 ID
        list_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records?name={self.config['record_name']}"
        try:
            res = requests.get(list_url, headers=self.headers).json()
            if not res.get("success") or not res["result"]:
                self.log(f"❌ 未找到域名 {self.config['record_name']} 的解析记录")
                return False
            
            record_id = res["result"][0]["id"]
            current_ip = res["result"][0]["content"]

            if current_ip == ip:
                self.log("✅ CF 记录已是最优，无需重复更新")
                return True

            # 2. 执行更新
            update_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records/{record_id}"
            data = {"type": "A", "name": self.config['record_name'], "content": ip, "ttl": 60, "proxied": False}
            put_res = requests.put(update_url, headers=self.headers, json=data).json()
            return put_res.get("success")
        except Exception as e:
            self.log(f"❌ API 异常: {str(e)}")
            return False

    def run_forever(self):
        """自动化循环线程"""
        self.is_running = True
        while True:
            self.log("🔄 开始新一轮自动优选...")
            ips = self.parse_ips()
            
            results = []
            for ip in ips:
                delay = self.get_latency(ip)
                if delay < 9999:
                    results.append((ip, delay))
            
            if results:
                results.sort(key=lambda x: x[1])
                top_ip = results[0][0]
                self.log(f"🏆 最优 IP 锁定: {top_ip} ({results[0][1]}ms)")
                
                if self.update_cf_dns(top_ip):
                    self.best_ip = top_ip
                    self.last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.log(f"🚀 已自动同步到 Cloudflare")
            else:
                self.log("⚠️ 测速失败，未发现有效节点")
            
            self.log("💤 进入休眠，10分钟后再次巡检...")
            time.sleep(600) # 每 10 分钟运行一次

# ==========================================
# 3. Streamlit UI 展现层
# ==========================================
def main():
    st.set_page_config(page_title="CF 自动化优选", page_icon="⚡")
    st.title("🛡️ Cloudflare 节点自动巡检系统")

    # 单例模式启动后台线程
    if 'optimizer' not in st.session_state:
        st.session_state.optimizer = AutoOptimizer(CF_CONFIG, VLESS_LINKS)
        thread = threading.Thread(target=st.session_state.optimizer.run_forever, daemon=True)
        thread.start()

    opt = st.session_state.optimizer

    # 仪表盘
    col1, col2, col3 = st.columns(3)
    col1.metric("当前最优 IP", opt.best_ip)
    col2.metric("待监测节点数", len(set(VLESS_LINKS)))
    col3.metric("最后更新", opt.last_update.split(" ")[-1])

    st.divider()

    # 日志显示
    st.subheader("⚙️ 自动化运行日志")
    log_container = st.container(height=300)
    with log_container:
        for entry in reversed(opt.status_log):
            if "❌" in entry: st.error(entry)
            elif "🚀" in entry: st.success(entry)
            else: st.text(entry)

    # 自动刷新 UI (每 10 秒)
    time.sleep(10)
    st.rerun()

if __name__ == "__main__":
    main()