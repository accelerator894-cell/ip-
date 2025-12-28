import streamlit as st
import pandas as pd
import time
import threading
import random
import socket
import json
from pathlib import Path
from collections import Counter
from typing import Dict, List, Tuple, Optional, Any
import concurrent.futures
from dataclasses import dataclass, asdict
from datetime import datetime
import logging

# ==================== 配置部分 ====================
@dataclass
class Config:
    """应用配置"""
    BASE_DIR: Path = Path(".")
    DB_FILE: Path = BASE_DIR / "data" / "ip_db.json"
    STATE_FILE: Path = BASE_DIR / "data" / "state.json"
    FAIL_FILE: Path = BASE_DIR / "data" / "fail_db.json"
    LOG_FILE: Path = BASE_DIR / "data" / "app.log"
    
    # 连接参数
    UUID: str = "123e4567-e89b-12d3-a456-426614174000"
    REALITY_PUB: str = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A..."
    REALITY_SID: str = "abcd1234efgh5678"
    SNI: str = "speed.cloudflare.com"
    
    # 场景配置
    SCENES: List[str] = ["normal", "gpt", "stream", "custom"]
    FINGERPRINT: Dict[str, str] = {
        "normal": "chrome", 
        "gpt": "firefox", 
        "stream": "safari", 
        "custom": "chrome"
    }
    
    # 种子IP
    SEEDS: List[str] = [
        "104.19.19.19", 
        "104.18.20.126", 
        "172.64.198.1", 
        "172.67.1.1", 
        "104.21.32.13"
    ]
    
    # 测试参数
    TEST_PORT: int = 443
    TEST_TIMEOUT: float = 2.0
    MAX_WORKERS: int = 10
    UPDATE_INTERVAL: int = 30  # 秒
    
    # 健康度权重
    WEIGHT_COLO: float = 0.4
    WEIGHT_LATENCY: float = 0.3
    WEIGHT_SUCCESS: float = 0.3
    
    # 场景特定规则
    GPT_MIN_SPEED: float = 1.0  # MB/s
    STREAM_MAX_LATENCY: float = 150  # ms
    HEALTH_SWITCH_THRESHOLD: float = 0.15
    HEALTH_GOOD_THRESHOLD: float = 0.85

config = Config()

# 创建必要目录
config.BASE_DIR.mkdir(exist_ok=True)
(config.BASE_DIR / "data").mkdir(exist_ok=True)
(config.BASE_DIR / "profiles").mkdir(exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== 数据模型 ====================
@dataclass
class IPStats:
    """IP统计数据结构"""
    latency: List[float]
    colo: List[str]
    speed: List[float]
    success: int = 0
    fail: int = 0
    source: str = ""
    last_seen: str = ""
    health: float = 0.0
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'IPStats':
        """从字典创建实例"""
        # 处理可能的缺失字段
        defaults = {
            "latency": [],
            "colo": [],
            "speed": [],
            "success": 0,
            "fail": 0,
            "source": "",
            "last_seen": "",
            "health": 0.0
        }
        
        # 确保所有字段都有值
        for key, value in defaults.items():
            if key not in data:
                data[key] = value
        
        return cls(**data)

# ==================== 文件操作 ====================
class DataManager:
    """数据文件管理"""
    
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
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except IOError as e:
            logger.error(f"保存文件失败 {path}: {e}")
            return False
    
    @staticmethod
    def load_ip_db() -> Dict[str, Dict]:
        """加载IP数据库"""
        data = DataManager.load_json(config.DB_FILE, {})
        # 确保所有IP数据都有正确的结构
        for ip in data:
            data[ip] = IPStats.from_dict(data[ip]).to_dict()
        return data
    
    @staticmethod
    def save_ip_db(data: Dict) -> bool:
        """保存IP数据库"""
        return DataManager.save_json(config.DB_FILE, data)
    
    @staticmethod
    def load_state() -> Dict[str, str]:
        """加载状态数据"""
        return DataManager.load_json(config.STATE_FILE, {})
    
    @staticmethod
    def save_state(data: Dict) -> bool:
        """保存状态数据"""
        return DataManager.save_json(config.STATE_FILE, data)
    
    @staticmethod
    def load_fail_db() -> Dict[str, int]:
        """加载失败数据库"""
        return DataManager.load_json(config.FAIL_FILE, {})
    
    @staticmethod
    def save_fail_db(data: Dict) -> bool:
        """保存失败数据库"""
        return DataManager.save_json(config.FAIL_FILE, data)

# ==================== IP测试模块 ====================
class IPTester:
    """IP测试器"""
    
    @staticmethod
    def test_single_ip(ip: str) -> Tuple[Optional[float], Optional[str], float, str]:
        """测试单个IP的性能"""
        try:
            # 创建TCP套接字进行连接测试
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(config.TEST_TIMEOUT)
                start_time = time.perf_counter()  # 使用更高精度的计时器
                s.connect((ip, config.TEST_PORT))
                latency = (time.perf_counter() - start_time) * 1000  # 转换为毫秒
                s.close()
                
                # 模拟数据（实际使用时应该获取真实数据）
                colo_list = ["SFO", "LAX", "NYC", "SG", "HK", "LON", "FRA", "SYD"]
                colo = random.choice(colo_list)
                speed = random.uniform(0.5, 5.0)  # 扩展速度范围
                sources = ["📂 全量扫描", "⚡ 优质种子", "🏆 历史优秀", "🕷️ 爬虫", "💎 冷门"]
                source = random.choice(sources)
                
                logger.debug(f"IP测试成功: {ip} 延迟: {latency:.1f}ms 速度: {speed:.2f}MB/s")
                return latency, colo, speed, source
                
        except socket.timeout:
            logger.debug(f"IP测试超时: {ip}")
            return None, None, 0, "超时"
        except (socket.error, ConnectionRefusedError, OSError) as e:
            logger.debug(f"IP测试失败: {ip} - {e}")
            return None, None, 0, "失败"
    
    @staticmethod
    def test_multiple_ips(ips: List[str]) -> Dict[str, Tuple]:
        """并发测试多个IP"""
        results = {}
        
        # 如果没有IP需要测试，返回空字典
        if not ips:
            return results
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
            # 为每个IP创建测试任务
            future_to_ip = {executor.submit(IPTester.test_single_ip, ip): ip for ip in ips}
            
            # 收集结果
            for future in concurrent.futures.as_completed(future_to_ip):
                ip = future_to_ip[future]
                try:
                    # 设置超时以防万一
                    results[ip] = future.result(timeout=config.TEST_TIMEOUT + 2)
                except concurrent.futures.TimeoutError:
                    results[ip] = (None, None, 0, "超时")
                    logger.warning(f"IP测试任务超时: {ip}")
                except Exception as e:
                    results[ip] = (None, None, 0, f"错误: {str(e)[:50]}")
                    logger.error(f"IP测试任务异常: {ip} - {e}")
        
        logger.info(f"完成IP批量测试，共测试 {len(ips)} 个IP，成功 {len([r for r in results.values() if r[0] is not None])} 个")
        return results

# ==================== 健康度计算 ====================
class HealthScorer:
    """健康度评分器"""
    
    @staticmethod
    def calculate_colo_stability(colos: List[str]) -> float:
        """计算Colo稳定性"""
        if not colos:
            return 0.0
        
        # 只考虑最近10次结果
        recent_colos = colos[-10:] if len(colos) > 10 else colos
        counter = Counter(recent_colos)
        
        if not counter:
            return 0.0
            
        most_common_count = counter.most_common(1)[0][1]
        return most_common_count / len(recent_colos)
    
    @staticmethod
    def calculate_latency_score(latencies: List[float]) -> float:
        """计算延迟分数"""
        if not latencies:
            return 0.0
        
        # 只考虑最近10次结果
        recent_latencies = latencies[-10:] if len(latencies) > 10 else latencies
        
        if not recent_latencies:
            return 0.0
            
        avg_latency = sum(recent_latencies) / len(recent_latencies)
        
        # 延迟在0-50ms: 满分，50-200ms: 线性衰减，200ms以上: 0分
        if avg_latency <= 50:
            return 1.0
        elif avg_latency <= 200:
            return 1.0 - (avg_latency - 50) / 150
        else:
            return 0.0
    
    @staticmethod
    def calculate_success_rate(success: int, fail: int) -> float:
        """计算成功率"""
        total = success + fail
        if total == 0:
            return 0.0
        return success / total
    
    @staticmethod
    def calculate_speed_score(speeds: List[float]) -> float:
        """计算速度分数"""
        if not speeds:
            return 0.0
            
        recent_speeds = speeds[-5:] if len(speeds) > 5 else speeds
        avg_speed = sum(recent_speeds) / len(recent_speeds)
        
        # 速度在3MB/s以上: 满分，0-3MB/s: 线性计算
        return min(avg_speed / 3.0, 1.0)
    
    @staticmethod
    def calculate_health_score(stats: IPStats) -> float:
        """计算综合健康度分数"""
        if not stats.latency:
            return 0.0
            
        colo_score = HealthScorer.calculate_colo_stability(stats.colo)
        latency_score = HealthScorer.calculate_latency_score(stats.latency)
        success_score = HealthScorer.calculate_success_rate(stats.success, stats.fail)
        speed_score = HealthScorer.calculate_speed_score(stats.speed)
        
        # 加权计算综合分数
        health = (
            colo_score * config.WEIGHT_COLO +
            latency_score * config.WEIGHT_LATENCY +
            success_score * config.WEIGHT_SUCCESS +
            speed_score * 0.1  # 速度占10%权重
        )
        
        # 确保分数在0-1之间
        health = max(0.0, min(1.0, health))
        return round(health, 3)
    
    @staticmethod
    def should_switch(current_ip: Optional[str], current_stats: Optional[IPStats], 
                     candidate_stats: IPStats, scene: str) -> bool:
        """判断是否需要切换IP"""
        # 如果当前没有IP，则切换
        if current_ip is None:
            return True
            
        # 如果当前IP没有统计信息，则切换
        if current_stats is None:
            return True
            
        # 场景特定规则
        if scene == "gpt":
            if candidate_stats.speed and candidate_stats.speed[-1] < config.GPT_MIN_SPEED:
                return False
            # GPT场景更看重速度
            candidate_speed = HealthScorer.calculate_speed_score(candidate_stats.speed)
            current_speed = HealthScorer.calculate_speed_score(current_stats.speed)
            if candidate_speed < current_speed * 1.2:  # 速度没有明显提升则不切换
                return False
                
        if scene == "stream":
            if candidate_stats.latency and candidate_stats.latency[-1] > config.STREAM_MAX_LATENCY:
                return False
            # 流媒体场景更看重延迟
            candidate_latency = HealthScorer.calculate_latency_score(candidate_stats.latency)
            current_latency = HealthScorer.calculate_latency_score(current_stats.latency)
            if candidate_latency < current_latency * 1.1:  # 延迟没有明显改善则不切换
                return False
            
        # 获取健康度分数
        current_health = current_stats.health or 0.0
        candidate_health = candidate_stats.health
        
        # 如果当前健康度已经很高，则不切换
        if current_health >= config.HEALTH_GOOD_THRESHOLD:
            return False
            
        # 如果候选IP健康度提升超过阈值，则切换
        return candidate_health - current_health >= config.HEALTH_SWITCH_THRESHOLD

# ==================== NekoBox配置生成 ====================
class NekoBoxGenerator:
    """NekoBox配置生成器"""
    
    @staticmethod
    def generate_profile(scene: str, ip: str) -> Dict:
        """生成NekoBox配置文件"""
        profile = {
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
        
        # 根据场景调整配置
        if scene == "gpt":
            # GPT场景可能需要不同的路由设置
            profile["route"]["rules"] = [
                {
                    "type": "field",
                    "domain": ["openai.com", "chat.openai.com", "api.openai.com"],
                    "outboundTag": f"CF-{scene.upper()}"
                }
            ]
        elif scene == "stream":
            # 流媒体场景可能需要不同的路由设置
            profile["route"]["rules"] = [
                {
                    "type": "field",
                    "domain": ["netflix.com", "youtube.com", "twitch.tv"],
                    "outboundTag": f"CF-{scene.upper()}"
                }
            ]
        
        return profile
    
    @staticmethod
    def save_profile(scene: str, ip: str) -> Optional[Path]:
        """保存配置文件"""
        try:
            profile = NekoBoxGenerator.generate_profile(scene, ip)
            file_path = config.BASE_DIR / "profiles" / f"nekobox_{scene}.json"
            
            if DataManager.save_json(file_path, profile):
                logger.info(f"配置文件已保存: {file_path} (IP: {ip})")
                return file_path
            return None
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            return None

# ==================== 核心管理器 ====================
class IPHunterManager:
    """IP猎手管理器"""
    
    def __init__(self):
        self.db = DataManager.load_ip_db()
        self.state = DataManager.load_state()
        self.fail_db = DataManager.load_fail_db()
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        
    def update_ip_stats(self, ip: str, test_result: Tuple) -> None:
        """更新IP统计数据"""
        latency, colo, speed, source = test_result
        
        with self._lock:
            # 获取或创建统计对象
            ip_data = self.db.get(ip, {})
            stats = IPStats.from_dict(ip_data)
            
            # 更新数据
            if latency is not None:
                stats.latency.append(latency)
                stats.latency = stats.latency[-20:]  # 保留最近20次
                stats.success += 1
                
                if colo:
                    stats.colo.append(colo)
                    stats.colo = stats.colo[-20:]
                
                if speed:
                    stats.speed.append(speed)
                    stats.speed = stats.speed[-20:]
                    
                # 如果是新IP，设置来源
                if not stats.source and source:
                    stats.source = source
            else:
                stats.fail += 1
                # 记录失败到独立数据库
                self.fail_db[ip] = self.fail_db.get(ip, 0) + 1
                
            stats.last_seen = datetime.now().isoformat()
            stats.health = HealthScorer.calculate_health_score(stats)
            
            # 保存回数据库
            self.db[ip] = stats.to_dict()
            logger.debug(f"更新IP统计: {ip} 健康度: {stats.health} 延迟: {latency if latency else '失败'}ms")
    
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
                    
                    # 跳过没有足够数据的IP
                    if not stats.latency or len(stats.latency) < 3:
                        continue
                    
                    # 跳过失败次数过多的IP
                    if stats.fail > 5 and stats.success / (stats.success + stats.fail) < 0.5:
                        continue
                    
                    # 场景过滤
                    if scene == "gpt" and stats.speed and stats.speed[-1] < config.GPT_MIN_SPEED:
                        continue
                    if scene == "stream" and stats.latency and stats.latency[-1] > config.STREAM_MAX_LATENCY:
                        continue
                    
                    if stats.health > candidate_score:
                        candidate_score = stats.health
                        candidate_ip = ip
                
                # 如果没有找到候选IP，尝试从种子IP中选择
                if not candidate_ip and config.SEEDS:
                    candidate_ip = random.choice(config.SEEDS)
                    logger.warning(f"场景 {scene} 没有合适的候选IP，使用随机种子IP: {candidate_ip}")
                
                if candidate_ip and candidate_ip != current_ip:
                    candidate_stats = IPStats.from_dict(self.db.get(candidate_ip, {}))
                    if HealthScorer.should_switch(current_ip, current_stats, candidate_stats, scene):
                        old_ip = current_ip or "无"
                        self.state[scene] = candidate_ip
                        NekoBoxGenerator.save_profile(scene, candidate_ip)
                        logger.info(f"场景 {scene} 切换IP: {old_ip} -> {candidate_ip}")
    
    def run_scheduler(self) -> None:
        """调度器主循环"""
        logger.info("IP猎人调度器启动")
        self._running = True
        
        cycle_count = 0
        
        while self._running:
            try:
                cycle_count += 1
                logger.debug(f"开始第 {cycle_count} 轮调度")
                
                # 测试种子IP
                test_results = IPTester.test_multiple_ips(config.SEEDS)
                
                # 更新统计
                for ip, result in test_results.items():
                    self.update_ip_stats(ip, result)
                
                # 每5轮进行一次评估和切换
                if cycle_count % 5 == 0:
                    self.evaluate_and_switch()
                    
                    # 保存数据
                    DataManager.save_ip_db(self.db)
                    DataManager.save_state(self.state)
                    DataManager.save_fail_db(self.fail_db)
                    
                    logger.info(f"第 {cycle_count} 轮调度完成，数据库记录数: {len(self.db)}")
                else:
                    logger.debug(f"第 {cycle_count} 轮测试完成")
                
            except Exception as e:
                logger.error(f"调度器错误: {e}", exc_info=True)
            
            # 等待下一轮
            time.sleep(config.UPDATE_INTERVAL)
    
    def start(self) -> None:
        """启动后台线程"""
        if not self._running:
            logger.info("启动IP猎人后台线程")
            self._thread = threading.Thread(target=self.run_scheduler, daemon=True)
            self._thread.start()
        else:
            logger.warning("IP猎人后台线程已在运行")
    
    def stop(self) -> None:
        """停止后台线程"""
        if self._running:
            logger.info("停止IP猎人后台线程")
            self._running = False
            if self._thread:
                self._thread.join(timeout=5)
                if self._thread.is_alive():
                    logger.warning("后台线程未能正常停止")
        else:
            logger.warning("IP猎人后台线程未在运行")
    
    def get_top_ips(self, n: int = 10) -> List[Dict]:
        """获取排名前N的IP"""
        with self._lock:
            # 过滤掉没有足够数据的IP
            valid_ips = []
            for ip, ip_data in self.db.items():
                stats = IPStats.from_dict(ip_data)
                if stats.latency and len(stats.latency) >= 1:
                    valid_ips.append((ip, ip_data))
            
            # 按健康度排序
            sorted_ips = sorted(
                valid_ips,
                key=lambda x: x[1].get('health', 0),
                reverse=True
            )[:n]
            
            result = []
            for ip, data in sorted_ips:
                stats = IPStats.from_dict(data)
                
                # 计算平均延迟和速度
                avg_latency = round(sum(stats.latency[-5:]) / len(stats.latency[-5:]), 1) if stats.latency else 999
                avg_speed = round(sum(stats.speed[-5:]) / len(stats.speed[-5:]), 2) if stats.speed else 0.0
                
                result.append({
                    "IP": ip,
                    "评分": stats.health,
                    "延迟(ms)": avg_latency,
                    "速度(MB/s)": avg_speed,
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
                    
                    # 计算平均延迟和速度
                    avg_latency = round(sum(stats.latency[-3:]) / len(stats.latency[-3:]), 1) if stats.latency else 0
                    avg_speed = round(sum(stats.speed[-3:]) / len(stats.speed[-3:]), 2) if stats.speed else 0
                    
                    status[scene] = {
                        "ip": ip,
                        "health": stats.health,
                        "latency": avg_latency,
                        "speed": avg_speed,
                        "colo": stats.colo[-1] if stats.colo else "UNK",
                        "last_seen": stats.last_seen[:16] if stats.last_seen else "从未"
                    }
                else:
                    status[scene] = {"ip": "无", "health": 0, "latency": 0, "speed": 0, "colo": "无", "last_seen": "从未"}
            return status
    
    def get_system_stats(self) -> Dict[str, Any]:
        """获取系统统计信息"""
        with self._lock:
            total_ips = len(self.db)
            
            # 统计健康IP数量
            healthy_ips = 0
            for ip_data in self.db.values():
                stats = IPStats.from_dict(ip_data)
                if stats.health >= 0.7:
                    healthy_ips += 1
            
            # 统计各场景使用情况
            scene_ips = {}
            for scene in config.SCENES:
                ip = self.state.get(scene)
                if ip and ip != "无":
                    scene_ips[scene] = ip
            
            return {
                "total_ips": total_ips,
                "healthy_ips": healthy_ips,
                "active_scenes": len([ip for ip in scene_ips.values() if ip != "无"]),
                "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
    
    def test_custom_ip(self, ip: str) -> Dict[str, Any]:
        """测试自定义IP"""
        try:
            logger.info(f"开始测试自定义IP: {ip}")
            latency, colo, speed, source = IPTester.test_single_ip(ip)
            
            result = {
                "ip": ip,
                "success": latency is not None,
                "latency": round(latency, 1) if latency else None,
                "colo": colo,
                "speed": round(speed, 2) if speed else 0.0,
                "source": source if latency else "测试失败"
            }
            
            # 如果测试成功，更新到数据库
            if latency is not None:
                self.update_ip_stats(ip, (latency, colo, speed, "手动测试"))
                # 立即保存数据库
                DataManager.save_ip_db(self.db)
                logger.info(f"自定义IP测试成功: {ip} 延迟: {latency:.1f}ms")
            else:
                logger.warning(f"自定义IP测试失败: {ip}")
                
            return result
            
        except Exception as e:
            logger.error(f"自定义IP测试异常: {ip} - {e}")
            return {
                "ip": ip,
                "success": False,
                "error": str(e)
            }

# ==================== Streamlit前端 ====================
class StreamlitApp:
    """Streamlit应用前端"""
    
    def __init__(self):
        self.manager = IPHunterManager()
        self._init_session_state()
    
    def _init_session_state(self):
        """初始化会话状态"""
        if "app_started" not in st.session_state:
            self.manager.start()
            st.session_state.app_started = True
            st.session_state.test_history = []
        
        if "auto_refresh" not in st.session_state:
            st.session_state.auto_refresh = True
        
        if "last_refresh" not in st.session_state:
            st.session_state.last_refresh = time.time()
        
        if "custom_ip_test_result" not in st.session_state:
            st.session_state.custom_ip_test_result = None
    
    def render_sidebar(self):
        """渲染侧边栏"""
        with st.sidebar:
            st.title("⚙️ 控制面板")
            
            # 系统状态
            st.subheader("系统状态")
            system_stats = self.manager.get_system_stats()
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("IP总数", system_stats["total_ips"])
            with col2:
                st.metric("健康IP", system_stats["healthy_ips"])
            
            st.metric("活跃场景", system_stats["active_scenes"])
            st.caption(f"最后更新: {system_stats['last_update']}")
            
            st.divider()
            
            # 控制按钮
            st.subheader("控制")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔄 手动刷新", use_container_width=True):
                    st.session_state.last_refresh = time.time()
                    st.rerun()
            
            with col2:
                if st.button("📊 更新配置", use_container_width=True):
                    # 强制重新评估并更新配置
                    with st.spinner("更新配置中..."):
                        self.manager.evaluate_and_switch()
                        st.success("配置已更新!")
                        time.sleep(1)
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
            
            # 批量测试
            with st.expander("批量测试"):
                ip_list = st.text_area(
                    "输入IP列表 (每行一个)",
                    placeholder="1.2.3.4\n5.6.7.8\n...",
                    height=100
                )
                
                if st.button("批量测试IP", use_container_width=True) and ip_list:
                    ips = [ip.strip() for ip in ip_list.split('\n') if ip.strip()]
                    if ips:
                        with st.spinner(f"批量测试 {len(ips)} 个IP..."):
                            results = IPTester.test_multiple_ips(ips)
                            success_count = len([r for r in results.values() if r[0] is not None])
                            st.success(f"测试完成: {success_count}/{len(ips)} 个IP成功")
            
            # 单个测试
            custom_ip = st.text_input("测试单个IP:", placeholder="1.2.3.4")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("测试此IP", use_container_width=True) and custom_ip:
                    with st.spinner(f"测试IP {custom_ip}..."):
                        result = self.manager.test_custom_ip(custom_ip)
                        st.session_state.custom_ip_test_result = result
                        st.rerun()
            
            with col2:
                if st.button("清空结果", use_container_width=True):
                    st.session_state.custom_ip_test_result = None
                    st.rerun()
            
            # 显示测试结果
            if st.session_state.custom_ip_test_result:
                result = st.session_state.custom_ip_test_result
                if result["success"]:
                    st.success(f"✅ 测试成功")
                    st.info(f"""
                    **IP:** {result['ip']}  
                    **延迟:** {result['latency']}ms  
                    **速度:** {result['speed']}MB/s  
                    **Colo:** {result['colo']}  
                    **来源:** {result['source']}
                    """)
                else:
                    st.error(f"❌ 测试失败")
                    if "error" in result:
                        st.error(f"错误: {result['error']}")
            
            st.divider()
            
            # 操作说明
            with st.expander("📖 使用说明