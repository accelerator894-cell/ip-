import streamlit as st
import requests
import threading
import time
import urllib.parse
from datetime import datetime

# ==========================================
# 1. 配置中心 (请严格按照这个格式填写)
# ==========================================
CF_CONFIG = {
    # 名字(Key)是固定的，请把你的实际数据填在右边的引号里
    "api_token": "92os9FwyeG7jQDYpD6Rb0Cxrqu5YjtUjGfY1xKBm", 
    "zone_id": "7aa1c1ddfd9df2690a969d9f977f82ae",
    "record_name": "speed.milet.qzz.io", 
}

# 你的 VLESS 链接库
VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.136.0:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@188.114.97.1:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@141.101.120.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#%E7%BE%8E%E5%9B%BD70",
]

# ==========================================
# 2. 自动化管理逻辑
# ==========================================
class AutoOptimizer:
    def __init__(self, config, links):
        self.config = config
        self.links = links
        # 强制清理 Token 字符串，防止 latin-1 报错
        self.token = str(config.get("api_token", "")).strip()
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        self.best_ip = "等待测速..."
        self.last_update = "尚未运行"
        self.status_log = []

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_log.append(f"[{timestamp}] {message}")
        if len(self.status_log) > 12: self.status_log.pop(0)

    def update_cf_dns(self, ip):
        """自动查询并更新 Cloudflare DNS"""
        base_url = "https://api.cloudflare.com/client/v4"
        try:
            self.log("🛰️ 正在从 Cloudflare 获取记录信息...")
            # 自动搜索对应的 Record ID
            list_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records?name={self.config['record_name']}"
            res = requests.get(list_url, headers=self.headers, timeout=10).json()
            
            if not res.get("success"):
                err = res.get('errors')[0]['message'] if res.get('errors') else "API 权限或 Token 错误"
                self.log(f"❌ API 报错: {err}")
                return False

            if not res["result"]:
                self.log(f"❌ 域名 {self.config['record_name']} 不存在，请确认 CF 记录名")
                return False
            
            record = res["result"][0]
            if record["content"] == ip:
                self.log(f"✅ CF 记录已是 {ip}，无需操作")
                return True

            self.log(f"🛠️ 发现更优 IP，开始同步: {ip}")
            update_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records/{record['id']}"
            data = {"type": "A", "name": self.config['record_name'], "content": ip, "ttl": 60, "proxied": False}
            put_res = requests.put(update_url, headers=self.headers, json=data, timeout=10).json()
            
            if put_res.get("success"):
                self.log("🚀 同步成功！")
                return True
            else:
                self.log(f"❌ 更新失败: {put_res['errors'][0]['message']}")
                return False
        except Exception as e:
            self.log(f"⚠️ 异常: {str(e)}")
            return False

    def run_forever(self):
        while True:
            self.log("🔄 开始一轮自动巡检...")
            ips = []
            for link in self.links:
                try:
                    p = urllib.parse.urlparse(link)
                    ips.append(p.netloc.split('@')[-1].split(':')[0])
                except: continue
            
            results = []
            for ip in set(ips):
                try:
                    start = time.time()
                    requests.get(f"https://{ip}", timeout=1.5, verify=False)
                    results.append((ip, int((time.time() - start) * 1000)))
                except: continue
            
            if results:
                results.sort(key=lambda x: x[1])
                top_ip = results[0][0]
                self.log(f"🏆 锁定最优 IP: {top_ip} ({results[0][1]}ms)")
                if self.update_cf_dns(top_ip):
                    self.best_ip = top_ip
                    self.last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                self.log("⚠️ 测速失败，未发现有效节点")
            
            self.log("💤 进入休眠，10分钟后再次运行")
            time.sleep(600)

# ==========================================
# 3. Streamlit UI 展现
# ==========================================
def main():
    st.set_page_config(page_title="CF 节点自动巡检", page_icon="⚡")
    st.title("🛡️ 自动优选同步系统")

    # 确保单例运行
    if 'optimizer' not in st.session_state:
        st.session_state.optimizer = AutoOptimizer(CF_CONFIG, VLESS_LINKS)
        threading.Thread(target=st.session_state.optimizer.run_forever, daemon=True).start()

    opt = st.session_state.optimizer

    m1, m2 = st.columns(2)
    m1.metric("当前生效 IP", opt.best_ip)
    m2.metric("最后更新", opt.last_update.split(" ")[-1] if " " in opt.last_update else "等待中")

    st.divider()

    st.subheader("⚙️ 自动化运行日志")
    log_area = st.container(height=400, border=True)
    with log_area:
        for msg in reversed(opt.status_log):
            if "🚀" in msg or "✅" in msg: st.success(msg)
            elif "❌" in msg or "⚠️" in msg: st.error(msg)
            else: st.code(msg)

    # 自动刷新页面 (每5秒)
    time.sleep(5)
    st.rerun()

if __name__ == "__main__":
    main()