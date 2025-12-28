import streamlit as st
import pandas as pd
import time, threading, random, socket, json
from pathlib import Path
from collections import Counter, defaultdict
from typing import Dict, List, Tuple, Optional, Any
import concurrent.futures
from dataclasses import dataclass, asdict
from datetime import datetime
import logging

# ------------------ 配置 ------------------
@dataclass
class Config:
    BASE_DIR: Path = Path(".")
    DB_FILE: Path = BASE_DIR / "data" / "ip_db.json"
    STATE_FILE: Path = BASE_DIR / "data" / "state.json"
    FAIL_FILE: Path = BASE_DIR / "data" / "fail_db.json"
    LOG_FILE: Path = BASE_DIR / "data" / "app.log"
    
    UUID: str = "123e4567-e89b-12d3-a456-426614174000"
    REALITY_PUB: str = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A..."
    REALITY_SID: str = "abcd1234efgh5678"
    SNI: str = "speed.cloudflare.com"
    
    SCENES: List[str] = ["normal", "gpt", "stream", "custom"]
    FINGERPRINT: Dict[str, str] = {"normal": "chrome", "gpt": "firefox", 
                                  "stream": "safari", "custom": "chrome"}
    SEEDS: List[str] = ["104.19.19.19", "104.18.20.126", "172.64.198.1", 
                       "172.67.1.1", "104.21.32.13"]
    
    # 测试参数
    TEST_PORT: int = 443
    TEST_TIMEOUT: float = 2.0
    MAX_WORKERS: int = 10
    UPDATE_INTERVAL: int = 30  # 秒
    
    # 健康度权重
    WEIGHT_COLO: float = 0.4
    WEIGHT_LATENCY: float = 0.3
    WEIGHT_SUCCESS: float = 0.3

config = Config()

# 创建数据目录
config.BASE_DIR.mkdir(exist_ok=True)
(config.BASE_DIR / "data").mkdir(exist_ok=True)
(config.BASE_DIR / "profiles").mkdir(exist_ok=True)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ------------------ 数据类 ------------------
@dataclass
class IPStats:
    latency: List[float]
    colo: List[str]
    speed: List[float]
    success: int = 0
    fail: int = 0
    source: str = ""
    last_seen: str = ""
    health: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'IPStats':
        return cls(**data)

# ------------------ 文件操作 ------------------
class DataManager:
    @staticmethod
    def load_json(path: Path, default: Any = None) -> Any:
        """加载JSON文件，带错误处理"""
        try:
            if not path.exists():
                return default if default is not None else {}
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"加载文件失败 {path}: {e}")
            return default if default is not None else {}
    
    @staticmethod
    def save_json(path: Path, data: Any) -> bool:
        """保存JSON文件，带错误处理"""
        try:
            # 确保目录存在
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except IOError as e:
            logger.error(f"保存文件失败 {path}: {e}")
            return False
    
    @staticmethod
    def load_ip_db() -> Dict[str, Dict]:
        return DataManager.load_json(config.DB_FILE, {})
    
    @staticmethod
    def save_ip_db(data: Dict) -> bool:
        return DataManager.save_json(config.DB_FILE, data)
    
    @staticmethod
    def load_state() -> Dict[str, str]:
        return DataManager.load_json(config.STATE_FILE, {})
    
    @staticmethod
    def save_state(data: Dict) -> bool:
        return DataManager.save_json(config.STATE_FILE, data)

# ------------------ IP 测试 ------------------
class IPTester:
    @staticmethod
    def test_single_ip(ip: str) -> Tuple[Optional[float], Optional[str], float, str]:
        """测试单个IP的性能"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(config.TEST_TIMEOUT)
                start_time = time.time()
                s.connect((ip, config.TEST_PORT))
                latency = (time.time() - start_time) * 1000
                
                # 模拟数据（实际使用时应该获取真实数据）
                colo = random.choice(["SFO", "LAX", "NYC", "SG", "HK"])
                speed = random.uniform(0.5, 3.5)
                source = random.choice(["📂 全量扫描", "⚡ 优质种子", "🏆 历史优秀", "🕷️ 爬虫", "💎 冷门"])
                
                logger.info(f"IP测试成功: {ip} 延迟: {latency:.1f}ms")
                return latency, colo, speed, source
                
        except socket.timeout:
            logger.debug(f"IP测试超时: {ip}")
            return None, None, 0, "超时"
        except (socket.error, ConnectionRefusedError) as e:
            logger.debug(f"IP测试失败: {ip} - {e}")
            return None, None, 0, "失败"
    
    @staticmethod
    def test_multiple_ips(ips: List[str]) -> Dict[str, Tuple]:
        """并发测试多个IP"""
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
            future_to_ip = {executor.submit(IPTester.test_single_ip, ip): ip for ip in ips}
            for future in concurrent.futures.as_completed(future_to_ip):
                ip = future_to_ip[future]
                try:
                    results[ip] = future.result(timeout=config.TEST_TIMEOUT + 1)
                except concurrent.futures.TimeoutError:
                    results[ip] = (None, None, 0, "超时")
        return results

# ------------------ 健康度模型 ------------------
class HealthScorer:
    @staticmethod
    def calculate_colo_stability(colos: List[str]) -> float:
        """计算Colo稳定性"""
        if not colos:
            return 0.0
        counter = Counter(colos[-10:])  # 只考虑最近10次
        most_common_count = counter.most_common(1)[0][1] if counter else 0
        return most_common_count / len(colos)
    
    @staticmethod
    def calculate_latency_score(latencies: List[float]) -> float:
        """计算延迟分数"""
        if not latencies:
            return 0.0
        avg_latency = sum(latencies[-10:]) / len(latencies[-10:])
        # 200ms为基准，延迟越低分数越高
        return max(0.0, 1.0 - min(avg_latency / 200, 1.0))
    
    @staticmethod
    def calculate_success_rate(success: int, fail: int) -> float:
        """计算成功率"""
        total = success + fail
        if total == 0:
            return 0.0
        return success / total
    
    @staticmethod
    def calculate_health_score(stats: IPStats) -> float:
        """计算综合健康度分数"""
        if not stats.latency:
            return 0.0
            
        colo_score = HealthScorer.calculate_colo_stability(stats.colo)
        latency_score = HealthScorer.calculate_latency_score(stats.latency)
        success_score = HealthScorer.calculate_success_rate(stats.success, stats.fail)
        
        health = (
            colo_score * config.WEIGHT_COLO +
            latency_score * config.WEIGHT_LATENCY +
            success_score * config.WEIGHT_SUCCESS
        )
        
        return round(health, 3)
    
    @staticmethod
    def should_switch(current_ip: Optional[str], current_stats: Optional[IPStats], 
                     candidate_stats: IPStats, scene: str) -> bool:
        """判断是否需要切换IP"""
        if current_ip is None:
            return True
            
        if current_stats is None:
            return True
            
        # 场景特定规则
        if scene == "gpt" and candidate_stats.speed[-1] < 1.0:
            return False
        if scene == "stream" and candidate_stats.latency[-1] > 150:
            return False
            
        # 健康度提升超过阈值或当前健康度过低
        current_health = current_stats.health or 0.0
        candidate_health = candidate_stats.health
        
        if current_health >= 0.85:
            return False
            
        return candidate_health - current_health >= 0.15

# ------------------ NekoBox 配置生成 ------------------
class NekoBoxGenerator:
    @staticmethod
    def generate_profile(scene: str, ip: str) -> Dict:
        """生成NekoBox配置文件"""
        return {
            "log": {"level": "warn"},
            "inbounds": [
                {
                    "type": "socks",
                    "tag": "socks-in",
                    "listen": "127.0.0.1",
                    "listen_port": 10808
                }
            ],
            "outbounds": [
                {
                    "type": "vless",
                    "tag": f"CF-{scene.upper()}",
                    "server": ip,
                    "server_port": 443,
                    "uuid": config.UUID,
                    "tls": {
                        "enabled": True,
                        "server_name": config.SNI,
                        "utls": {
                            "enabled": True,
                            "fingerprint": config.FINGERPRINT[scene]
                        },
                        "reality": {
                            "enabled": True,
                            "public_key": config.REALITY_PUB,
                            "short_id": config.REALITY_SID
                        }
                    },
                    "transport": {"type": "tcp"}
                }
            ],
            "route": {"auto_detect_interface": True}
        }
    
    @staticmethod
    def save_profile(scene: str, ip: str) -> Optional[Path]:
        """保存配置文件"""
        try:
            profile = NekoBoxGenerator.generate_profile(scene, ip)
            file_path = config.BASE_DIR / "profiles" / f"nekobox_{scene}.json"
            
            if DataManager.save_json(file_path, profile):
                logger.info(f"配置文件已保存: {file_path}")
                return file_path
            return None
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            return None

# ------------------ 核心管理器 ------------------
class IPHunterManager:
    def __init__(self):
        self.db = DataManager.load_ip_db()
        self.state = DataManager.load_state()
        self.fail_db = DataManager.load_json(config.FAIL_FILE, {})
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        
    def update_ip_stats(self, ip: str, test_result: Tuple) -> None:
        """更新IP统计数据"""
        latency, colo, speed, source = test_result
        
        with self._lock:
            # 获取或创建统计对象
            ip_data = self.db.get(ip, {})
            stats = IPStats.from_dict(ip_data) if ip_data else IPStats(
                latency=[], colo=[], speed=[], source=source
            )
            
            # 更新数据
            if latency is not None:
                stats.latency.append(latency)
                stats.latency = stats.latency[-10:]  # 保留最近10次
                stats.success += 1
                
                if colo:
                    stats.colo.append(colo)
                    stats.colo = stats.colo[-10:]
                
                if speed:
                    stats.speed.append(speed)
                    stats.speed = stats.speed[-10:]
            else:
                stats.fail += 1
                
            stats.last_seen = datetime.now().isoformat()
            stats.health = HealthScorer.calculate_health_score(stats)
            
            # 保存回数据库
            self.db[ip] = stats.to_dict()
    
    def evaluate_and_switch(self) -> None:
        """评估并切换最优IP"""
        with self._lock:
            for scene in config.SCENES:
                current_ip = self.state.get(scene)
                current_stats = None
                if current_ip and current_ip in self.db:
                    current_stats = IPStats.from_dict(self.db[current_ip])
                
                # 找到候选IP
                candidate_ip = None
                candidate_score = -1
                
                for ip, ip_data in self.db.items():
                    stats = IPStats.from_dict(ip_data)
                    
                    # 场景过滤
                    if scene == "gpt" and stats.speed and stats.speed[-1] < 1.0:
                        continue
                    if scene == "stream" and stats.latency and stats.latency[-1] > 150:
                        continue
                    
                    if stats.health > candidate_score:
                        candidate_score = stats.health
                        candidate_ip = ip
                
                if candidate_ip and candidate_ip != current_ip:
                    candidate_stats = IPStats.from_dict(self.db[candidate_ip])
                    if HealthScorer.should_switch(current_ip, current_stats, candidate_stats, scene):
                        self.state[scene] = candidate_ip
                        NekoBoxGenerator.save_profile(scene, candidate_ip)
                        logger.info(f"场景 {scene} 切换IP: {current_ip} -> {candidate_ip}")
    
    def run_scheduler(self) -> None:
        """调度器主循环"""
        logger.info("IP猎人调度器启动")
        self._running = True
        
        while self._running:
            try:
                # 测试种子IP
                test_results = IPTester.test_multiple_ips(config.SEEDS)
                
                # 更新统计
                for ip, result in test_results.items():
                    self.update_ip_stats(ip, result)
                
                # 评估和切换
                self.evaluate_and_switch()
                
                # 保存数据
                DataManager.save_ip_db(self.db)
                DataManager.save_state(self.state)
                DataManager.save_json(config.FAIL_FILE, self.fail_db)
                
                logger.debug(f"调度完成，数据库记录数: {len(self.db)}")
                
            except Exception as e:
                logger.error(f"调度器错误: {e}")
            
            time.sleep(config.UPDATE_INTERVAL)
    
    def start(self) -> None:
        """启动后台线程"""
        if not self._running:
            self._thread = threading.Thread(target=self.run_scheduler, daemon=True)
            self._thread.start()
    
    def stop(self) -> None:
        """停止后台线程"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def get_top_ips(self, n: int = 10) -> List[Dict]:
        """获取排名前N的IP"""
        with self._lock:
            sorted_ips = sorted(
                self.db.items(),
                key=lambda x: x[1].get('health', 0),
                reverse=True
            )[:n]
            
            result = []
            for ip, data in sorted_ips:
                stats = IPStats.from_dict(data)
                result.append({
                    "IP": ip,
                    "评分": stats.health,
                    "延迟(ms)": round(stats.latency[-1], 1) if stats.latency else 999,
                    "速度(MB/s)": round(stats.speed[-1], 2) if stats.speed else 0.0,
                    "来源": stats.source,
                    "Colo": stats.colo[-1] if stats.colo else "UNK",
                    "成功率": f"{stats.success}/{stats.success + stats.fail}",
                    "最后检测": stats.last_seen[:16] if stats.last_seen else "从未"
                })
            return result
    
    def get_scene_status(self) -> Dict[str, Dict]:
        """获取各场景状态"""
        with self._lock:
            status = {}
            for scene in config.SCENES:
                ip = self.state.get(scene)
                if ip and ip in self.db:
                    stats = IPStats.from_dict(self.db[ip])
                    status[scene] = {
                        "ip": ip,
                        "health": stats.health,
                        "latency": round(stats.latency[-1], 1) if stats.latency else 0,
                        "speed": round(stats.speed[-1], 2) if stats.speed else 0,
                        "colo": stats.colo[-1] if stats.colo else "UNK"
                    }
                else:
                    status[scene] = {"ip": "无", "health": 0}
            return status

# ------------------ Streamlit 前端 ------------------
class StreamlitApp:
    def __init__(self):
        self.manager = IPHunterManager()
        self._init_session_state()
    
    def _init_session_state(self):
        """初始化会话状态"""
        if "app_started" not in st.session_state:
            self.manager.start()
            st.session_state.app_started = True
        
        if "auto_refresh" not in st.session_state:
            st.session_state.auto_refresh = True
        
        if "last_refresh" not in st.session_state:
            st.session_state.last_refresh = time.time()
    
    def render_sidebar(self):
        """渲染侧边栏"""
        with st.sidebar:
            st.title("⚙️ 控制面板")
            
            # 手动刷新按钮
            if st.button("🔄 手动刷新数据", use_container_width=True):
                st.session_state.last_refresh = time.time()
                st.rerun()
            
            # 自动刷新开关
            st.session_state.auto_refresh = st.toggle(
                "自动刷新",
                value=st.session_state.auto_refresh,
                help="每30秒自动刷新数据"
            )
            
            st.divider()
            
            # 添加自定义IP测试
            st.subheader("自定义IP测试")
            custom_ip = st.text_input("输入IP地址:", placeholder="1.2.3.4")
            if st.button("测试此IP", use_container_width=True) and custom_ip:
                with st.spinner(f"测试IP {custom_ip}..."):
                    result = IPTester.test_single_ip(custom_ip)
                    latency, colo, speed, source = result
                    if latency:
                        st.success(f"延迟: {latency:.1f}ms | 速度: {speed:.2f}MB/s")
                        st.info(f"Colo: {colo} | 来源: {source}")
                    else:
                        st.error("IP测试失败")
            
            st.divider()
            
            # 系统状态
            st.subheader("系统状态")
            st.metric("IP数据库", f"{len(self.manager.db)} 条记录")
            
            # 最后更新时间
            elapsed = time.time() - st.session_state.last_refresh
            st.caption(f"最后更新: {int(elapsed)}秒前")
            
            # 操作说明
            with st.expander("使用说明"):
                st.markdown("""
                1. **normal**: 普通浏览场景
                2. **gpt**: GPT访问，要求高速
                3. **stream**: 流媒体，要求低延迟
                4. **custom**: 自定义场景
                
                ✅ 绿色: 健康度 > 0.8  
                ⚠️ 黄色: 健康度 0.5-0.8  
                🔴 红色: 健康度 < 0.5
                """)
    
    def render_main_content(self):
        """渲染主内容"""
        st.title("🧬 Cloudflare IP 猎手")
        st.markdown("### 多场景智能IP优选系统")
        
        # 场景状态卡片
        st.subheader("📊 场景状态")
        scene_status = self.manager.get_scene_status()
        
        cols = st.columns(len(config.SCENES))
        for idx, scene in enumerate(config.SCENES):
            with cols[idx]:
                status = scene_status[scene]
                container = st.container(border=True)
                
                with container:
                    # 根据健康度设置颜色
                    health = status["health"]
                    if health >= 0.8:
                        color = "green"
                        emoji = "✅"
                    elif health >= 0.5:
                        color = "orange"
                        emoji = "⚠️"
                    else:
                        color = "red"
                        emoji = "🔴"
                    
                    st.markdown(f"### {scene.upper()}")
                    st.markdown(f"**当前IP:** `{status['ip']}`")
                    st.markdown(f"**健康度:** {emoji} **{health:.3f}**")
                    
                    if status["ip"] != "无":
                        st.markdown(f"**延迟:** {status['latency']}ms")
                        st.markdown(f"**速度:** {status['speed']}MB/s")
                        st.markdown(f"**Colo:** {status['colo']}")
        
        # IP排行榜
        st.subheader("🏆 IP排行榜 (TOP 10)")
        top_ips = self.manager.get_top_ips(10)
        
        if top_ips:
            df = pd.DataFrame(top_ips)
            
            # 添加颜色编码
            def color_health(val):
                if val >= 0.8:
                    color = "green"
                elif val >= 0.5:
                    color = "orange"
                else:
                    color = "red"
                return f"color: {color}; font-weight: bold"
            
            styled_df = df.style.map(color_health, subset=['评分'])
            
            st.dataframe(
                styled_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "评分": st.column_config.NumberColumn(format="%.3f"),
                    "延迟(ms)": st.column_config.NumberColumn(format="%.1f"),
                    "速度(MB/s)": st.column_config.NumberColumn(format="%.2f")
                }
            )
        else:
            st.info("暂无IP数据，等待后台扫描...")
        
        # NekoBox配置文件下载
        st.subheader("📥 NekoBox 配置下载")
        profile_cols = st.columns(len(config.SCENES))
        
        for idx, scene in enumerate(config.SCENES):
            with profile_cols[idx]:
                profile_path = config.BASE_DIR / "profiles" / f"nekobox_{scene}.json"
                if profile_path.exists():
                    with open(profile_path, 'r') as f:
                        profile_data = f.read()
                    
                    st.download_button(
                        label=f"下载 {scene.upper()}",
                        data=profile_data,
                        file_name=f"nekobox_{scene}.json",
                        mime="application/json",
                        use_container_width=True
                    )
                    st.caption(f"IP: {scene_status[scene]['ip']}")
                else:
                    st.button(
                        f"等待生成 {scene.upper()}",
                        disabled=True,
                        use_container_width=True
                    )
    
    def run(self):
        """运行Streamlit应用"""
        st.set_page_config(
            page_title="Cloudflare IP 猎手",
            page_icon="🧬",
            layout="wide",
            initial_sidebar_state="expanded"
        )
        
        # 自动刷新逻辑
        if st.session_state.auto_refresh:
            elapsed = time.time() - st.session_state.last_refresh
            if elapsed > 30:  # 30秒自动刷新
                st.session_state.last_refresh = time.time()
                st.rerun()
        
        # 渲染界面
        self.render_sidebar()
        self.render_main_content()
        
        # 页脚信息
        st.divider()
        st.caption(f"""
        🕐 后台每 {config.UPDATE_INTERVAL} 秒自动更新 | 
        📊 数据库: {len(self.manager.db)} 个IP | 
        🔄 最后刷新: {datetime.now().strftime('%H:%M:%S')}
        """)

# ------------------ 应用入口 ------------------
if __name__ == "__main__":
    app = StreamlitApp()
    app.run()