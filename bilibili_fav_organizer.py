"""
==========================================================
B站收藏夹自动分类整理脚本 v2.0
==========================================================
两阶段架构：
  阶段1 (--scan): 遍历收藏夹 → 分类打标签 → 生成JSON文档+日志
  阶段2 (--move): 读取JSON文档 → 移动视频 → 更新状态（支持断点续传）

用法：
  python bilibili_fav_organizer.py --scan              # 扫描全部
  python bilibili_fav_organizer.py --scan --test 50    # 扫描前50个（测试）
  python bilibili_fav_organizer.py --move              # 执行移动
  python bilibili_fav_organizer.py --move --test 10    # 移动前10个（测试）

依赖安装：
  pip install requests pandas openpyxl

作者：Claude Code
日期：2026-06-18
==========================================================
"""

import os
import requests
import time
import json
import re
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Optional
from datetime import datetime


# ============================================================
# 第一部分：配置信息
# ============================================================

def _load_config_file():
    """加载config.json配置文件"""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"  ❌ 未找到配置文件: {config_path}")
        print(f"  请复制 config.example.json 为 config.json 并填入你的信息")
        raise SystemExit(1)

_config = _load_config_file()


class Config:
    """
    存储所有配置信息
    敏感信息（Cookie、收藏夹ID）从 config.json 读取
    分类规则保留在代码中（不含敏感信息）
    """

    # ---- Cookie和收藏夹（从config.json读取） ----
    COOKIES = _config["cookies"]
    FOLDERS = _config["folders"]

    # ---- UP主直接归类规则 ----
    UP_FOLDER_MAP = {
        "网络小白_Uncle城": "知识提升",
        "SYSTEM-RAMOS-ZDY": "知识提升",
        "3Blue1Brown": "知识提升",
        "林亦LYi": "知识提升",
        "小约翰可汗": "跑步电台",
        "马督工": "跑步电台",
        "小德MOMO": "跑步电台",
        "小Lin说": "跑步电台",
        "认知进化的Vivian": "跑步电台",
        "Larry想做技术大佬": "跑步电台",
        "芳斯塔芙": "跑步电台",
        "大冰直播间": "跑步电台",
        "中国食品报融媒体": "跑步电台",
        "戒社": "跑步电台",
        "地球知识局": "人文知识",
        "睿画三国": "人文知识",
        "苏老拳_": "人文知识",
        "漫士沉思录": "人文知识",
        "医学科普联盟": "人文知识",
        "冷却报告": "人文知识",
        "赛雷三分钟": "人文知识",
        "毕导": "人文知识",
        "毕的二阶导": "人文知识",
        "画渣花小烙": "人文知识",
        "差评君": "人文知识",
        "短的差评君": "人文知识",
        "GaryVee加里维纳查克": "人生自我",
        "意识星球住民BeAware": "人生自我",
        "我才是熊猫大G": "有趣娱乐",
        "超级小桀的日常": "有趣娱乐",
        "神奇的维C": "有趣娱乐",
        "Evelinas": "有趣娱乐",
        "沫子瞪片": "有趣娱乐",
    }

    # ---- 标题关键词分类规则 ----
    # 格式: (关键词列表, 目标收藏夹, 匹配范围)
    KEYWORD_RULES = [
        (["做菜", "烹饪", "菜谱", "食谱", "做饭", "家常菜", "炒菜", "炖菜",
          "烘焙", "蛋糕", "面包", "甜点", "甜品", "料理", "食材", "调味",
          "红烧", "清蒸", "爆炒", "凉拌", "煲汤", "火锅", "烧烤", "腌制",
          "厨房", "厨艺", "下厨", "大厨", "美食制作", "美食教程",
          "厨房小白", "新手做饭", "家常美食"], "菜单2", "all"),

        (["炉石传说", "炉石", "hearthstone", "酒馆战棋"], "有趣娱乐", "all"),

        (["编程", "代码", "github.com", "程序", "算法", "python", "java", "javascript",
          "c++", "rust", "golang", "前端", "后端", "全栈", "开发", "debug",
          "git", "linux", "服务器", "数据库", "sql", "api", "框架", "开源",
          "ai工具", "chatgpt", "大模型", "llm", "机器学习", "深度学习",
          "人工智能", "神经网络", "transformer", "prompt",
          "leetcode", "力扣", "数据结构", "设计模式", "架构"], "知识提升", "all"),

        (["就业", "求职", "面试", "简历", "秋招", "春招", "校招", "社招",
          "offer", "薪资", "程序员面试", "技术面试", "计算机就业", "转行",
          "职业规划", "裁员", "互联网寒冬", "找工作"], "找工作", "all"),
    ]

    # ---- 请求配置 ----
    REQUEST_DELAY = 1.0
    PAGE_SIZE = 20
    MAX_RETRIES = 3

    # ---- 输出文件路径 ----
    # ---- 输出文件 ----
    OUTPUT_DIR = "D:\\工作"
    SCAN_JSON = f"{OUTPUT_DIR}\\收藏夹扫描结果.json"
    MOVE_LOG = f"{OUTPUT_DIR}\\收藏夹移动日志.txt"
    SCAN_LOG = f"{OUTPUT_DIR}\\收藏夹扫描日志.txt"
    EXCEL_REPORT = f"{OUTPUT_DIR}\\收藏夹分类统计.xlsx"


# ============================================================
# 第二部分：B站API封装
# ============================================================

class BilibiliAPI:
    """封装B站收藏夹相关API"""

    BASE_URL = "https://api.bilibili.com"

    def __init__(self, cookies: dict):
        self.session = requests.Session()

        # 完整的浏览器请求头
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/126.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com",
            "Origin": "https://www.bilibili.com",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

        # 访问首页获取基础cookie
        try:
            self.session.get("https://www.bilibili.com", timeout=10)
        except Exception as e:
            print(f"  ⚠ 访问B站首页失败: {e}")

        # 刷新设备指纹
        self._refresh_buvid()

        # 设置用户cookie
        self.session.cookies.update(cookies)
        self.csrf = cookies.get("bili_jct", "")

        if "b_nut" not in self.session.cookies:
            self.session.cookies.set("b_nut", "100", domain=".bilibili.com")

    def _refresh_buvid(self):
        """通过SPI接口刷新设备指纹cookie"""
        try:
            resp = self.session.get(f"{self.BASE_URL}/x/frontend/finger/spi", timeout=10)
            data = resp.json()
            if data.get("code") == 0:
                b3 = data["data"]["b_3"]
                b4 = data["data"]["b_4"]
                self.session.cookies.set("buvid3", b3, domain=".bilibili.com")
                self.session.cookies.set("buvid4", b4, domain=".bilibili.com")
                print(f"  ✅ 设备指纹刷新成功")
        except Exception as e:
            print(f"  ⚠ 刷新设备指纹失败: {e}")

    def _get(self, path: str, params: dict = None) -> dict:
        """GET请求"""
        url = f"{self.BASE_URL}{path}"
        for retry in range(Config.MAX_RETRIES):
            try:
                resp = self.session.get(url, params=params, timeout=15)
                data = resp.json()
                if data.get("code") == 0:
                    return data.get("data", {})
                else:
                    print(f"  ⚠ API错误: code={data.get('code')}, msg={data.get('message')}")
                    if data.get("code") == -101:
                        print("  ❌ Cookie已过期！")
                        return {}
                    return {}
            except Exception as e:
                print(f"  ⚠ GET失败 (重试{retry+1}): {e}")
                time.sleep(2)
        return {}

    def _refresh_session(self):
        """
        刷新session，应对412反爬
        重新访问首页 + 刷新设备指纹，让B站认为是新请求
        """
        try:
            self.session.get("https://www.bilibili.com", timeout=10)
        except:
            pass
        self._refresh_buvid()
        time.sleep(2)

    def _post(self, path: str, data: dict = None, debug: bool = False) -> dict:
        """
        POST请求，带412自动退避和session刷新

        412处理策略：
          1. 检测到412 → 等待30秒冷却
          2. 刷新session（重新访问首页+SPI）
          3. 重试，等待时间指数递增（30→60→120秒）
          4. 最多重试3轮
        """
        url = f"{self.BASE_URL}{path}"
        if data is None:
            data = {}
        data["csrf"] = self.csrf

        post_headers = {"Content-Type": "application/x-www-form-urlencoded"}

        for retry in range(Config.MAX_RETRIES):
            try:
                resp = self.session.post(url, data=data, headers=post_headers, timeout=15)

                if debug:
                    print(f"  [DEBUG] URL: {url}")
                    print(f"  [DEBUG] Status: {resp.status_code}")
                    print(f"  [DEBUG] Response: {resp.text[:300]}")

                # ---- 412反爬处理 ----
                if resp.status_code == 412:
                    wait = 30 * (2 ** retry)  # 30秒、60秒、120秒
                    print(f"\n  ⚠ HTTP 412 触发反爬，冷却 {wait} 秒后重试 ({retry+1}/{Config.MAX_RETRIES})")
                    print(f"    正在刷新session...")
                    time.sleep(wait)
                    self._refresh_session()
                    continue

                if resp.status_code != 200:
                    print(f"  ⚠ HTTP错误: {resp.status_code}")
                    if retry < Config.MAX_RETRIES - 1:
                        time.sleep(5)
                        continue
                    return {}

                if not resp.text or resp.text.strip() == "":
                    print(f"  ⚠ 空响应")
                    if retry < Config.MAX_RETRIES - 1:
                        time.sleep(3)
                        continue
                    return {}

                result = resp.json()
                if result.get("code") == 0:
                    return result.get("data", {})
                else:
                    print(f"  ⚠ API错误: code={result.get('code')}, msg={result.get('message')}")
                    if result.get("code") == -111:
                        print("  ❌ CSRF token无效！")
                    if result.get("code") == -101:
                        print("  ❌ Cookie已过期！")
                    return {}

            except requests.exceptions.JSONDecodeError:
                print(f"  ⚠ JSON解析失败 (重试{retry+1}): {resp.text[:200]}")
                time.sleep(3)
            except Exception as e:
                print(f"  ⚠ POST异常 (重试{retry+1}): {e}")
                time.sleep(3)

        return {}

    def get_fav_list(self, media_id: int, page: int = 1) -> dict:
        """获取收藏夹单页视频"""
        params = {
            "media_id": media_id,
            "pn": page,
            "ps": Config.PAGE_SIZE,
            "type": 0,
            "order": "mtime",
            "platform": "web",
        }
        return self._get("/x/v3/fav/resource/list", params)

    def get_all_fav_videos(self, media_id: int, callback=None) -> list:
        """获取收藏夹所有视频（自动翻页）"""
        all_videos = []
        page = 1

        while True:
            data = self.get_fav_list(media_id, page)
            if not data:
                break

            medias = data.get("medias") or []
            if not medias:
                break

            all_videos.extend(medias)

            if callback:
                callback(len(all_videos), data.get("total_count", "?"))

            if not data.get("has_more", False):
                break

            page += 1
            time.sleep(Config.REQUEST_DELAY)

        return all_videos

    def move_single_video(self, aid: int, src_fid: int, tar_fid: int) -> tuple:
        """
        移动单个视频（添加到目标 + 从源删除）

        返回: (成功与否, 错误信息)
        """
        # Step 1: 添加到目标收藏夹
        data_add = {
            "rid": aid,
            "type": 2,
            "add_media_ids": tar_fid,
            "csrf": self.csrf,
        }
        result = self._post("/x/v3/fav/resource/deal", data_add)
        if not result and result is not None:
            return False, "添加到目标收藏夹失败"

        # Step 2: 从源收藏夹删除
        time.sleep(1)  # 两步之间间隔1秒
        data_del = {
            "rid": aid,
            "type": 2,
            "del_media_ids": src_fid,
            "csrf": self.csrf,
        }
        result = self._post("/x/v3/fav/resource/deal", data_del)

        return True, ""


# ============================================================
# 第三部分：视频标签系统
# ============================================================

class VideoTagger:
    """视频标签打标器"""

    CHINESE_PATTERN = re.compile(r'[一-鿿]')
    ENGLISH_PATTERN = re.compile(r'[a-zA-Z]{3,}')

    TOPIC_KEYWORDS = {
        "烹饪美食": ["做菜", "烹饪", "菜谱", "食谱", "做饭", "家常菜", "烘焙",
                    "蛋糕", "面包", "甜点", "料理", "美食", "厨房", "厨艺"],
        "编程技术": ["编程", "代码", "github", "程序", "算法", "python", "java",
                    "javascript", "前端", "后端", "开发", "git", "linux", "服务器",
                    "数据库", "框架", "开源", "debug", "程序设计"],
        "AI人工智能": ["ai", "chatgpt", "大模型", "llm", "机器学习", "深度学习",
                      "人工智能", "神经网络", "transformer", "prompt", "gpt", "copilot"],
        "游戏": ["炉石", "游戏", "电竞", "steam", "switch", "ps5", "手游", "端游",
                "英雄联盟", "王者荣耀", "原神", "崩坏", "吃鸡", "绝地求生"],
        "科普知识": ["科普", "知识", "科学", "物理", "化学", "生物", "数学", "历史",
                    "地理", "宇宙", "进化", "基因", "量子"],
        "人文历史": ["历史", "三国", "古代", "王朝", "文明", "哲学", "思想", "文化",
                    "人文", "艺术", "文学"],
        "就业求职": ["就业", "求职", "面试", "简历", "秋招", "春招", "offer", "薪资",
                    "裁员", "转行", "职业", "找工作", "校招", "社招"],
        "医学健康": ["医学", "健康", "疾病", "医院", "药物", "治疗", "养生", "保健",
                    "营养", "运动", "健身", "跑步"],
        "生活日常": ["vlog", "日常", "生活", "记录", "分享", "旅行", "旅游", "探店"],
        "音乐": ["音乐", "歌曲", "演唱会", "live", "翻唱", "原创音乐", "mv", "专辑"],
        "科技数码": ["手机", "电脑", "显卡", "cpu", "数码", "科技", "评测", "开箱",
                    "苹果", "华为", "小米", "iphone"],
    }

    FORMAT_KEYWORDS = {
        "教程": ["教程", "教学", "课程", "入门", "进阶", "实战", "手把手", "从零开始",
                "学习", "练习", "lesson", "tutorial", "guide"],
        "科普": ["科普", "揭秘", "原理", "为什么", "是什么", "怎么回事", "冷知识",
                "涨知识", "你知道吗"],
        "杂谈": ["杂谈", "聊天", "闲聊", "吐槽", "reaction", "回应", "评论", "看法",
                "观点", "聊聊", "说说"],
        "Vlog": ["vlog", "日常", "记录", "一天", "生活", "vlogmas", "跟我一起"],
        "评测": ["评测", "测评", "体验", "开箱", "上手", "对比", "横评"],
        "新闻资讯": ["新闻", "资讯", "盘点", "总结", "回顾", "最新", "重磅"],
        "娱乐搞笑": ["搞笑", "沙雕", "整活", "名场面", "高能", "笑死", "哈哈哈",
                    "鬼畜", "二创"],
    }

    @classmethod
    def detect_language(cls, title: str, desc: str = "") -> str:
        text = title + " " + desc
        cn = len(cls.CHINESE_PATTERN.findall(text))
        en = len(cls.ENGLISH_PATTERN.findall(text))
        if cn > 0 and en > 0:
            return "中英混合"
        elif cn > 0:
            return "中文"
        elif en > 0:
            return "英文"
        return "其他"

    @classmethod
    def detect_topic(cls, title: str, desc: str = "", tags: list = None) -> str:
        text = (title + " " + desc).lower()
        tag_text = " ".join(tags).lower() if tags else ""
        best, best_score = "未分类", 0
        for topic, keywords in cls.TOPIC_KEYWORDS.items():
            score = sum(3 if kw.lower() in tag_text else 0 for kw in keywords)
            score += sum(1 for kw in keywords if kw.lower() in text)
            if score > best_score:
                best_score, best = score, topic
        return best if best_score > 0 else "未分类"

    @classmethod
    def detect_format(cls, title: str, desc: str = "", page_count: int = 1) -> str:
        text = (title + " " + desc).lower()
        if page_count > 3:
            for kw in cls.FORMAT_KEYWORDS.get("教程", []):
                if kw in text:
                    return "教程"
            return "系列视频"
        for fmt, keywords in cls.FORMAT_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    return fmt
        return "其他"

    @classmethod
    def detect_duration_type(cls, duration: int) -> str:
        if duration <= 180:
            return "短视频"
        elif duration <= 600:
            return "中视频"
        return "长视频"

    @classmethod
    def tag_video(cls, video: dict) -> dict:
        """返回标签字典"""
        title = video.get("title", "")
        desc = video.get("intro", "")
        upper_name = video.get("upper", {}).get("name", "")
        page_count = video.get("page_count", 1)
        duration = video.get("duration", 0)
        tags = video.get("tags", [])

        return {
            "language": cls.detect_language(title, desc),
            "topic": cls.detect_topic(title, desc, tags),
            "format_type": cls.detect_format(title, desc, page_count),
            "duration_type": cls.detect_duration_type(duration),
        }


# ============================================================
# 第四部分：分类引擎
# ============================================================

class Classifier:
    """视频分类器"""

    def __init__(self):
        self.up_map = {k.strip(): v for k, v in Config.UP_FOLDER_MAP.items()}

    def classify(self, video: dict) -> dict:
        """
        返回分类结果字典:
        {"target_folder": str, "match_rule": str, "confidence": float}
        """
        title = video.get("title", "")
        upper_name = video.get("upper", {}).get("name", "").strip()
        page_count = video.get("page_count", 1)
        desc = video.get("intro", "")

        # 规则1: UP主直接归类
        if upper_name in self.up_map:
            return {
                "target_folder": self.up_map[upper_name],
                "match_rule": f"UP主匹配: {upper_name}",
                "confidence": 1.0,
            }

        # 规则2: 标题+简介关键词
        for keywords, folder, scope in Config.KEYWORD_RULES:
            for kw in keywords:
                kw_lower = kw.lower()
                if scope == "all":
                    match_text = (title + " " + desc).lower()
                else:
                    match_text = title.lower()
                if kw_lower in match_text:
                    source = "简介" if kw_lower in desc.lower() and kw_lower not in title.lower() else "标题"
                    return {
                        "target_folder": folder,
                        "match_rule": f"关键词匹配: '{kw}' (来源:{source})",
                        "confidence": 0.9,
                    }

        # 规则3: 简介深度分析
        desc_result = self._analyze_description(desc, title)
        if desc_result:
            return desc_result

        # 规则4: 多分P → 教程
        if page_count > 3:
            return {
                "target_folder": "教程",
                "match_rule": f"多分P视频 (共{page_count}P)",
                "confidence": 0.7,
            }

        # 无匹配
        return {
            "target_folder": "默认",
            "match_rule": "无匹配规则，保留原位",
            "confidence": 0.0,
        }

    def _analyze_description(self, desc: str, title: str) -> Optional[dict]:
        if not desc or len(desc.strip()) < 5:
            return None

        desc_lower = desc.lower()

        # GitHub链接
        for p in ["github.com", "github.io", "gitee.com", "gitlab.com"]:
            if p in desc_lower:
                return {"target_folder": "知识提升", "match_rule": f"简介含代码仓库: {p}", "confidence": 0.85}

        # 技术关键词
        tech = ["源码", "代码", "开源项目", "技术栈", "开发环境", "运行环境",
                "安装教程", "配置文件", "npm", "pip install", "docker",
                "api接口", "sdk", "开发文档", "技术分享", "编程入门"]
        tc = sum(1 for p in tech if p in desc_lower)
        if tc >= 2:
            return {"target_folder": "知识提升", "match_rule": f"简介含{tc}个技术词", "confidence": 0.75}

        # 求职关键词
        job = ["面试经验", "面经", "笔试", "offer", "薪资", "待遇",
               "校招", "社招", "内推", "简历", "求职", "就业指导",
               "职业发展", "晋升", "跳槽", "转行"]
        jc = sum(1 for p in job if p in desc_lower)
        if jc >= 2:
            return {"target_folder": "找工作", "match_rule": f"简介含{jc}个求职词", "confidence": 0.75}

        # 烹饪关键词
        cook = ["食材", "调料", "步骤", "做法", "烹饪", "食谱",
                "克", "毫升", "勺", "适量", "大火", "小火", "翻炒",
                "腌制", "焯水", "出锅", "摆盘"]
        cc = sum(1 for p in cook if p in desc_lower)
        if cc >= 3:
            return {"target_folder": "菜单2", "match_rule": f"简介含{cc}个烹饪词", "confidence": 0.80}

        # 游戏关键词
        game = ["炉石传说", "炉石", "卡组", "对战", "天梯", "竞技场",
                "酒馆战棋", "传说", "段位", "排位"]
        gc = sum(1 for p in game if p in desc_lower)
        if gc >= 2:
            return {"target_folder": "有趣娱乐", "match_rule": f"简介含{gc}个游戏词", "confidence": 0.80}

        # 课程关键词
        course = ["课程链接", "学习资料", "课件", "百度网盘", "pan.baidu",
                  "提取码", "课程目录", "章节"]
        crc = sum(1 for p in course if p in desc_lower)
        if crc >= 2:
            return {"target_folder": "教程", "match_rule": f"简介含{crc}个课程词", "confidence": 0.70}

        return None


# ============================================================
# 第五部分：阶段1 — 扫描（--scan）
# ============================================================

def phase_scan(test_count: int = 0):
    """
    阶段1：扫描收藏夹，生成分类文档和详细日志
    不移动任何视频，只读取和分析
    """
    start_time = time.time()

    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║          阶段1：扫描收藏夹                               ║
    ║          遍历视频 → 分类打标签 → 生成文档                ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    # 初始化
    api = BilibiliAPI(Config.COOKIES)
    classifier = Classifier()

    # 验证Cookie
    print("  [1/4] 验证Cookie...")
    test_data = api._get("/x/web-interface/nav")
    if not test_data:
        print("  ❌ Cookie无效，请重新获取！")
        return
    print(f"  ✅ 登录成功: {test_data.get('uname', '未知')}")

    # 获取所有视频
    print(f"\n  [2/4] 获取默认收藏夹视频 (fid={Config.FOLDERS['默认']})...")

    def fetch_progress(count, total):
        print(f"\r  ⏳ 已获取 {count} 个视频 (总计约{total})", end="", flush=True)

    all_videos = api.get_all_fav_videos(Config.FOLDERS["默认"], callback=fetch_progress)
    total = len(all_videos)
    print(f"\n  ✅ 共获取 {total} 个视频")

    if test_count > 0 and test_count < total:
        all_videos = all_videos[:test_count]
        total = test_count
        print(f"  ⚠ 测试模式：只处理前 {total} 个视频")

    if total == 0:
        print("  ⚠ 收藏夹为空")
        return

    # 逐个扫描
    print(f"\n  [3/4] 开始扫描分类...")
    scan_results = []       # 所有视频的扫描结果
    folder_stats = defaultdict(int)  # 各收藏夹计数

    # 打开日志文件
    log_path = Config.SCAN_LOG
    log_file = open(log_path, "w", encoding="utf-8")
    log_file.write(f"B站收藏夹扫描日志\n")
    log_file.write(f"扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    log_file.write(f"视频总数: {total}\n")
    log_file.write(f"{'='*80}\n\n")

    for i, video in enumerate(all_videos):
        aid = video.get("id", 0)
        bvid = video.get("bvid", "")
        title = video.get("title", "无标题")
        desc = video.get("intro", "")
        upper = video.get("upper", {})
        upper_name = upper.get("name", "未知")
        upper_mid = upper.get("mid", 0)
        page_count = video.get("page_count", 1)
        duration = video.get("duration", 0)
        play_count = video.get("cnt_info", {}).get("play", 0)
        fav_time = video.get("fav_time", 0)
        cover = video.get("cover", "")

        # 打标签
        tag = VideoTagger.tag_video(video)

        # 分类
        result = classifier.classify(video)

        target = result["target_folder"]
        folder_stats[target] += 1

        # 构建扫描结果
        entry = {
            "index": i + 1,
            "aid": aid,
            "bvid": bvid,
            "title": title,
            "desc": desc,
            "upper_name": upper_name,
            "upper_mid": upper_mid,
            "page_count": page_count,
            "duration": duration,
            "duration_display": f"{duration // 60}:{duration % 60:02d}",
            "play_count": play_count,
            "fav_time": fav_time,
            "cover": cover,
            "tags": tag,
            "classify": result,
            "move_status": "pending",  # pending / success / failed
            "move_error": "",
        }
        scan_results.append(entry)

        # ---- 写入日志 ----
        log_file.write(f"[{i+1}/{total}] {title}\n")
        log_file.write(f"  AV号: {aid}  BV号: {bvid}\n")
        log_file.write(f"  UP主: {upper_name} (mid={upper_mid})\n")
        log_file.write(f"  简介: {desc[:100]}{'...' if len(desc) > 100 else ''}\n")
        log_file.write(f"  分P数: {page_count}  时长: {duration//60}:{duration%60:02d}  播放: {play_count}\n")
        log_file.write(f"  封面: {cover}\n")
        log_file.write(f"  标签: [{tag['language']}] [{tag['topic']}] [{tag['format_type']}] [{tag['duration_type']}]\n")
        log_file.write(f"  分类: → {target}  (置信度:{result['confidence']:.0%})\n")
        log_file.write(f"  规则: {result['match_rule']}\n")
        log_file.write(f"\n")

        # ---- 终端进度 ----
        elapsed = time.time() - start_time
        speed = (i + 1) / elapsed if elapsed > 0 else 0
        eta = (total - i - 1) / speed if speed > 0 else 0

        bar_len = 30
        filled = int(bar_len * (i + 1) / total)
        bar = "█" * filled + "░" * (bar_len - filled)

        title_short = title[:30] + "..." if len(title) > 30 else title

        print(f"\r  [{bar}] {(i+1)/total*100:.1f}% ({i+1}/{total}) "
              f"ETA:{eta/60:.1f}min | "
              f"[{tag['language']}][{tag['topic']}] → {target}  ", end="", flush=True)

        # 每100个视频换行一次，方便查看
        if (i + 1) % 100 == 0:
            print(f"\n  ✅ 已处理 {i+1} 个")

    print()

    # 关闭日志
    log_file.write(f"\n{'='*80}\n")
    log_file.write(f"扫描完成\n")
    log_file.write(f"总耗时: {(time.time()-start_time)/60:.1f} 分钟\n")
    log_file.write(f"\n分类统计:\n")
    for folder, count in sorted(folder_stats.items(), key=lambda x: -x[1]):
        log_file.write(f"  {folder}: {count} 个\n")
    log_file.close()
    print(f"  ✅ 扫描日志已保存: {log_path}")

    # 保存JSON文档
    print(f"\n  [4/4] 保存扫描结果文档...")
    scan_doc = {
        "version": "2.0",
        "generated_at": datetime.now().isoformat(),
        "total_videos": total,
        "source_folder": {"name": "默认", "fid": Config.FOLDERS["默认"]},
        "target_folders": {k: v for k, v in Config.FOLDERS.items() if k != "默认"},
        "folder_stats": dict(folder_stats),
        "videos": scan_results,
    }

    with open(Config.SCAN_JSON, "w", encoding="utf-8") as f:
        json.dump(scan_doc, f, ensure_ascii=False, indent=2)
    print(f"  ✅ 扫描文档已保存: {Config.SCAN_JSON}")

    # 生成Excel统计
    _generate_excel(scan_results, folder_stats)

    # 打印摘要
    elapsed = time.time() - start_time
    print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                  扫描完成！                              ║
    ╠══════════════════════════════════════════════════════════╣
    ║  总视频数:  {total:<10}                                   ║
    ║  耗时:      {elapsed/60:.1f} 分钟                              ║
    ║  文档路径:  {Config.SCAN_JSON:<40}  ║
    ║  日志路径:  {Config.SCAN_LOG:<40}  ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    # 打印分类统计
    print("  📊 分类统计:")
    for folder, count in sorted(folder_stats.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        bar = "█" * int(pct / 2)
        print(f"    {folder:<10} {count:>5} ({pct:.1f}%) {bar}")


# ============================================================
# 第六部分：阶段2 — 移动（--move）
# ============================================================

def phase_move(test_count: int = 0):
    """
    阶段2：读取扫描文档，执行视频移动
    支持断点续传：自动跳过已成功的视频
    """
    start_time = time.time()

    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║          阶段2：移动视频                                 ║
    ║          读取文档 → 移动到目标收藏夹 → 更新状态          ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    # 读取扫描文档
    print("  [1/3] 读取扫描文档...")
    try:
        with open(Config.SCAN_JSON, "r", encoding="utf-8") as f:
            scan_doc = json.load(f)
    except FileNotFoundError:
        print(f"  ❌ 未找到扫描文档: {Config.SCAN_JSON}")
        print("  请先运行: python bilibili_fav_organizer.py --scan")
        return

    videos = scan_doc["videos"]
    total = len(videos)
    print(f"  ✅ 读取到 {total} 个视频")

    # 统计状态
    already_done = sum(1 for v in videos if v["move_status"] == "success")
    pending = [v for v in videos if v["move_status"] == "pending"]
    failed = [v for v in videos if v["move_status"] == "failed"]

    print(f"  📊 状态: 已成功 {already_done} | 待处理 {len(pending)} | 上次失败 {len(failed)}")

    # 待处理列表 = pending + failed（失败的重试）
    to_move = pending + failed

    if test_count > 0:
        to_move = to_move[:test_count]
        print(f"  ⚠ 测试模式：只移动前 {test_count} 个")

    if not to_move:
        print("  ✅ 所有视频已移动完成，无需操作")
        return

    # 初始化API
    api = BilibiliAPI(Config.COOKIES)
    src_fid = Config.FOLDERS["默认"]

    # 验证Cookie
    print("\n  [2/3] 验证Cookie...")
    test_data = api._get("/x/web-interface/nav")
    if not test_data:
        print("  ❌ Cookie无效！")
        return
    print(f"  ✅ 登录成功: {test_data.get('uname', '未知')}")

    # 开始移动
    print(f"\n  [3/3] 开始移动 {len(to_move)} 个视频...")
    log_file = open(Config.MOVE_LOG, "a", encoding="utf-8")
    log_file.write(f"\n{'='*80}\n")
    log_file.write(f"移动会话开始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    log_file.write(f"待处理: {len(to_move)} 个\n")
    log_file.write(f"{'='*80}\n\n")

    success_count = 0
    fail_count = 0
    move_count = 0  # 已移动计数（用于控制冷却节奏）

    # 动态延迟配置
    BASE_DELAY = 2.0        # 基础延迟（秒）
    COOLDOWN_EVERY = 30      # 每移动30个视频，主动冷却一次
    COOLDOWN_SECONDS = 15    # 主动冷却时间（秒）
    MAX_DELAY = 5.0          # 最大延迟（秒）

    for i, entry in enumerate(to_move):
        aid = entry["aid"]
        title = entry["title"]
        upper_name = entry["upper_name"]
        target = entry["classify"]["target_folder"]
        rule = entry["classify"]["match_rule"]

        # 跳过默认收藏夹（不需要移动）
        if target == "默认":
            entry["move_status"] = "success"
            entry["move_error"] = "无需移动（保留原位）"
            success_count += 1

            log_file.write(f"[{i+1}/{len(to_move)}] 跳过: {title}\n")
            log_file.write(f"  原因: 目标为默认收藏夹，无需移动\n\n")
            continue

        tar_fid = Config.FOLDERS.get(target)
        if not tar_fid:
            entry["move_status"] = "failed"
            entry["move_error"] = f"未找到收藏夹 {target} 的fid"
            fail_count += 1

            log_file.write(f"[{i+1}/{len(to_move)}] 失败: {title}\n")
            log_file.write(f"  原因: 未找到收藏夹 {target}\n\n")
            continue

        # ---- 主动冷却：每N个视频暂停一下，避免触发412 ----
        if move_count > 0 and move_count % COOLDOWN_EVERY == 0:
            print(f"\n  ⏸ 已移动 {move_count} 个，主动冷却 {COOLDOWN_SECONDS} 秒...")
            log_file.write(f"  ⏸ 主动冷却 {COOLDOWN_SECONDS} 秒\n")
            api._refresh_session()
            time.sleep(COOLDOWN_SECONDS)

        # 执行移动
        ok, err_msg = api.move_single_video(aid, src_fid, tar_fid)

        if ok:
            entry["move_status"] = "success"
            entry["move_error"] = ""
            success_count += 1
            move_count += 1

            log_file.write(f"[{i+1}/{len(to_move)}] ✅ 成功: {title}\n")
            log_file.write(f"  AV{aid} | {upper_name} | → {target} | 规则: {rule}\n\n")
        else:
            entry["move_status"] = "failed"
            entry["move_error"] = err_msg
            fail_count += 1

            log_file.write(f"[{i+1}/{len(to_move)}] ❌ 失败: {title}\n")
            log_file.write(f"  AV号: {aid}  错误: {err_msg}\n\n")

        # 进度显示
        done = success_count + fail_count
        bar_len = 30
        filled = int(bar_len * done / len(to_move))
        bar = "█" * filled + "░" * (bar_len - filled)
        title_short = title[:25] + "..." if len(title) > 25 else title

        status_icon = "✅" if ok else "❌"
        print(f"\r  [{bar}] {done/len(to_move)*100:.1f}% ({done}/{len(to_move)}) "
              f"{status_icon} → {target} | {title_short}          ", end="", flush=True)

        # 每处理20个，保存一次文档（防止中途退出丢失进度）
        if done % 20 == 0:
            with open(Config.SCAN_JSON, "w", encoding="utf-8") as f:
                json.dump(scan_doc, f, ensure_ascii=False, indent=2)

        # 动态延迟：根据已移动数量逐渐增加
        delay = min(BASE_DELAY + move_count * 0.02, MAX_DELAY)
        time.sleep(delay)

    print()

    # 保存最终文档
    with open(Config.SCAN_JSON, "w", encoding="utf-8") as f:
        json.dump(scan_doc, f, ensure_ascii=False, indent=2)

    # 写入日志汇总
    log_file.write(f"\n{'='*80}\n")
    log_file.write(f"移动会话结束\n")
    log_file.write(f"成功: {success_count}  失败: {fail_count}\n")
    log_file.write(f"总耗时: {(time.time()-start_time)/60:.1f} 分钟\n")
    log_file.close()

    # 最终统计
    final_success = sum(1 for v in videos if v["move_status"] == "success")
    final_failed = sum(1 for v in videos if v["move_status"] == "failed")
    final_pending = sum(1 for v in videos if v["move_status"] == "pending")

    print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                  移动完成！                              ║
    ╠══════════════════════════════════════════════════════════╣
    ║  本次成功:  {success_count:<10}                                   ║
    ║  本次失败:  {fail_count:<10}                                   ║
    ║  ────────────────────────────────────────────────────     ║
    ║  累计成功:  {final_success:<10} ({final_success/total*100:.1f}%)                       ║
    ║  累计失败:  {final_failed:<10}                                   ║
    ║  待处理:    {final_pending:<10}                                   ║
    ║  日志路径:  {Config.MOVE_LOG:<40}  ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    if final_failed > 0:
        print(f"  ⚠ 有 {final_failed} 个视频移动失败，重新运行 --move 即可重试")


# ============================================================
# 第七部分：Excel统计报告
# ============================================================

def _generate_excel(scan_results: list, folder_stats: dict):
    """生成Excel统计报告"""
    try:
        import pandas as pd

        # Sheet1: 视频详情
        rows = []
        for v in scan_results:
            rows.append({
                "序号": v["index"],
                "标题": v["title"],
                "UP主": v["upper_name"],
                "AV号": v["aid"],
                "BV号": v["bvid"],
                "分P数": v["page_count"],
                "时长": v["duration_display"],
                "播放量": v["play_count"],
                "语言": v["tags"]["language"],
                "主题": v["tags"]["topic"],
                "视频形式": v["tags"]["format_type"],
                "时长类型": v["tags"]["duration_type"],
                "目标收藏夹": v["classify"]["target_folder"],
                "匹配规则": v["classify"]["match_rule"],
                "置信度": f"{v['classify']['confidence']:.0%}",
                "移动状态": v["move_status"],
            })
        df_videos = pd.DataFrame(rows)

        # Sheet2: UP主统计
        upper_counter = Counter(v["upper_name"] for v in scan_results)
        df_upper = pd.DataFrame(upper_counter.most_common(), columns=["UP主", "出现次数"])

        # Sheet3: 标签统计
        all_tags = []
        for v in scan_results:
            all_tags.extend(v["tags"].values())
        tag_counter = Counter(all_tags)
        df_tags = pd.DataFrame(tag_counter.most_common(), columns=["标签", "出现次数"])

        # Sheet4: 分类统计
        df_folders = pd.DataFrame(
            sorted(folder_stats.items(), key=lambda x: -x[1]),
            columns=["收藏夹", "视频数量"]
        )

        with pd.ExcelWriter(Config.EXCEL_REPORT, engine="openpyxl") as writer:
            df_videos.to_excel(writer, sheet_name="视频详情", index=False)
            df_upper.to_excel(writer, sheet_name="UP主统计", index=False)
            df_tags.to_excel(writer, sheet_name="标签统计", index=False)
            df_folders.to_excel(writer, sheet_name="分类统计", index=False)

        print(f"  ✅ Excel报告已保存: {Config.EXCEL_REPORT}")

    except ImportError:
        print(f"  ⚠ 未安装pandas，跳过Excel。运行: pip install pandas openpyxl")


# ============================================================
# 第八部分：入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="B站收藏夹自动分类整理工具 v2.0")
    parser.add_argument("--scan", action="store_true", help="阶段1：扫描收藏夹，生成分类文档")
    parser.add_argument("--move", action="store_true", help="阶段2：读取文档，执行移动")
    parser.add_argument("--test", type=int, default=0, help="测试模式，只处理前N个视频")

    args = parser.parse_args()

    if not args.scan and not args.move:
        parser.print_help()
        print("\n  示例:")
        print("    python bilibili_fav_organizer.py --scan              # 扫描全部")
        print("    python bilibili_fav_organizer.py --scan --test 50    # 扫描前50个")
        print("    python bilibili_fav_organizer.py --move              # 执行移动")
        print("    python bilibili_fav_organizer.py --move --test 10    # 移动前10个")
        return

    if args.scan:
        phase_scan(test_count=args.test)

    if args.move:
        phase_move(test_count=args.test)


if __name__ == "__main__":
    main()
