"""
==========================================================
B站收藏夹整理 — 浏览器自动化版本
==========================================================
使用 Playwright 控制真实浏览器，彻底绕过反爬

原理：
  - 启动一个真实的 Chrome 浏览器
  - 你手动登录B站（只需一次）
  - 脚本通过浏览器执行移动操作
  - B站看到的完全是正常浏览器行为

安装：
  pip install playwright
  playwright install chromium

用法：
  python bilibili_fav_playwright.py --scan              # 扫描
  python bilibili_fav_playwright.py --scan --test 50    # 测试扫描
  python bilibili_fav_playwright.py --move              # 移动
  python bilibili_fav_playwright.py --move --test 10    # 测试移动
==========================================================
"""

import os
import json
import time
import re
import argparse
from datetime import datetime
from collections import Counter, defaultdict

# 加载config.json
_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
try:
    with open(_config_path, "r", encoding="utf-8") as f:
        _config_file = json.load(f)
except FileNotFoundError:
    print(f"  ❌ 未找到 config.json，请复制 config.example.json 并填入你的信息")
    raise SystemExit(1)

# ============================================================
# 配置
# ============================================================

CONFIG = {
    "output_dir": "D:\\工作",
    "scan_json": "D:\\工作\\收藏夹扫描结果.json",
    "scan_log": "D:\\工作\\收藏夹扫描日志.txt",
    "move_log": "D:\\工作\\收藏夹移动日志.txt",
    "cookie_file": "D:\\工作\\.bilibili_cookies.json",

    # 收藏夹ID（从config.json读取）
    "folders": _config_file["folders"],

    # UP主归类规则
    "up_map": {
        "网络小白_Uncle城": "知识提升", "SYSTEM-RAMOS-ZDY": "知识提升",
        "3Blue1Brown": "知识提升", "林亦LYi": "知识提升",
        "小约翰可汗": "跑步电台", "马督工": "跑步电台",
        "小德MOMO": "跑步电台", "小Lin说": "跑步电台",
        "认知进化的Vivian": "跑步电台", "Larry想做技术大佬": "跑步电台",
        "芳斯塔芙": "跑步电台", "大冰直播间": "跑步电台",
        "中国食品报融媒体": "跑步电台", "戒社": "跑步电台",
        "地球知识局": "人文知识", "睿画三国": "人文知识",
        "苏老拳_": "人文知识", "漫士沉思录": "人文知识",
        "医学科普联盟": "人文知识", "冷却报告": "人文知识",
        "赛雷三分钟": "人文知识", "毕导": "人文知识",
        "毕的二阶导": "人文知识", "画渣花小烙": "人文知识",
        "差评君": "人文知识", "短的差评君": "人文知识",
        "GaryVee加里维纳查克": "人生自我", "意识星球住民BeAware": "人生自我",
        "我才是熊猫大G": "有趣娱乐", "超级小桀的日常": "有趣娱乐",
        "神奇的维C": "有趣娱乐", "Evelinas": "有趣娱乐",
        "沫子瞪片": "有趣娱乐",
    },

    # 关键词规则: (关键词列表, 目标收藏夹, 匹配范围)
    "keyword_rules": [
        (["做菜", "烹饪", "菜谱", "食谱", "做饭", "家常菜", "炒菜", "炖菜",
          "烘焙", "蛋糕", "面包", "甜点", "甜品", "料理", "食材", "调味",
          "红烧", "清蒸", "爆炒", "凉拌", "煲汤", "火锅", "烧烤", "腌制",
          "厨房", "厨艺", "下厨", "大厨", "美食制作", "美食教程"], "菜单2", "all"),
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
    ],
}


# ============================================================
# 分类器（复用规则逻辑）
# ============================================================

def classify_video(video: dict) -> dict:
    """对单个视频进行分类"""
    title = video.get("title", "")
    upper_name = video.get("upper", {}).get("name", "").strip()
    page_count = video.get("page_count", 1)
    desc = video.get("intro", "")

    # 规则1: UP主
    if upper_name in CONFIG["up_map"]:
        return {"target_folder": CONFIG["up_map"][upper_name],
                "match_rule": f"UP主匹配: {upper_name}", "confidence": 1.0}

    # 规则2: 关键词
    for keywords, folder, scope in CONFIG["keyword_rules"]:
        for kw in keywords:
            kw_lower = kw.lower()
            text = (title + " " + desc).lower() if scope == "all" else title.lower()
            if kw_lower in text:
                source = "简介" if kw_lower in desc.lower() and kw_lower not in title.lower() else "标题"
                return {"target_folder": folder,
                        "match_rule": f"关键词: '{kw}' ({source})", "confidence": 0.9}

    # 规则3: 多分P
    if page_count > 3:
        return {"target_folder": "教程",
                "match_rule": f"多分P ({page_count}P)", "confidence": 0.7}

    return {"target_folder": "默认", "match_rule": "无匹配", "confidence": 0.0}


def tag_video(video: dict) -> dict:
    """打标签"""
    title = video.get("title", "")
    desc = video.get("intro", "")
    page_count = video.get("page_count", 1)
    duration = video.get("duration", 0)

    # 语言
    cn = len(re.findall(r'[一-鿿]', title + desc))
    en = len(re.findall(r'[a-zA-Z]{3,}', title + desc))
    language = "中英混合" if cn > 0 and en > 0 else "中文" if cn > 0 else "英文" if en > 0 else "其他"

    # 时长
    if duration <= 180:
        dur_type = "短视频"
    elif duration <= 600:
        dur_type = "中视频"
    else:
        dur_type = "长视频"

    # 形式
    text = (title + " " + desc).lower()
    if page_count > 3:
        fmt = "系列视频"
    elif any(kw in text for kw in ["教程", "教学", "课程", "入门"]):
        fmt = "教程"
    elif any(kw in text for kw in ["科普", "揭秘", "原理"]):
        fmt = "科普"
    elif any(kw in text for kw in ["杂谈", "聊天", "吐槽"]):
        fmt = "杂谈"
    elif any(kw in text for kw in ["vlog", "日常", "记录"]):
        fmt = "Vlog"
    elif any(kw in text for kw in ["评测", "测评", "开箱"]):
        fmt = "评测"
    elif any(kw in text for kw in ["搞笑", "沙雕", "整活"]):
        fmt = "娱乐搞笑"
    else:
        fmt = "其他"

    return {"language": language, "topic": "未分类", "format_type": fmt, "duration_type": dur_type}


# ============================================================
# Playwright 浏览器操作
# ============================================================

def get_browser_context(playwright, headless=False):
    """
    获取浏览器上下文
    如果有保存的cookie则加载，否则需要手动登录
    """
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36",
    )

    # 尝试加载已保存的cookie
    import os
    if os.path.exists(CONFIG["cookie_file"]):
        with open(CONFIG["cookie_file"], "r") as f:
            cookies = json.load(f)
        context.add_cookies(cookies)
        print(f"  ✅ 已加载保存的Cookie")

    return browser, context


def login_and_save_cookies(context):
    """
    打开B站登录页面，等待用户手动登录，然后保存cookie
    """
    page = context.new_page()
    page.goto("https://www.bilibili.com")

    print("\n  请在浏览器中手动登录B站")
    print("  登录完成后，在终端按回车继续...")

    # 等待用户登录
    input()

    # 保存cookie
    cookies = context.cookies()
    with open(CONFIG["cookie_file"], "w") as f:
        json.dump(cookies, f, indent=2)
    print(f"  ✅ Cookie已保存到 {CONFIG['cookie_file']}")

    page.close()


def check_login(page) -> bool:
    """检查是否已登录"""
    page.goto("https://api.bilibili.com/x/web-interface/nav")
    content = page.content()
    try:
        # 从页面内容提取JSON
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            if data.get("code") == 0:
                print(f"  ✅ 登录成功: {data['data'].get('uname')}")
                return True
    except:
        pass
    print("  ❌ 未登录或Cookie已过期")
    return False


def fetch_all_videos(page, media_id: int) -> list:
    """通过浏览器获取收藏夹所有视频（用API）"""
    all_videos = []
    pn = 1
    page_size = 20

    while True:
        url = f"https://api.bilibili.com/x/v3/fav/resource/list?media_id={media_id}&pn={pn}&ps={page_size}&type=0&order=mtime"
        page.goto(url)
        content = page.content()

        try:
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if data.get("code") != 0:
                    break
                medias = data.get("data", {}).get("medias") or []
                if not medias:
                    break
                all_videos.extend(medias)
                total = data["data"].get("total_count", "?")
                print(f"\r  ⏳ 已获取 {len(all_videos)} / {total}", end="", flush=True)

                if not data["data"].get("has_more", False):
                    break
        except Exception as e:
            print(f"\n  ⚠ 解析失败: {e}")
            break

        pn += 1
        time.sleep(0.5)

    print()
    return all_videos


def move_video_via_page(page, aid: int, src_fid: int, tar_fid: int) -> tuple:
    """
    通过浏览器页面操作移动视频

    方法：直接调用浏览器内的fetch API
    这样所有cookie、header都由浏览器自动处理
    """
    js_code = f"""
    async () => {{
        try {{
            // Step 1: 添加到目标收藏夹
            const addResp = await fetch('https://api.bilibili.com/x/v3/fav/resource/deal', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/x-www-form-urlencoded',
                }},
                body: 'rid={aid}&type=2&add_media_ids={tar_fid}&csrf=' + getCSRF(),
                credentials: 'include'
            }});
            const addData = await addResp.json();

            if (addData.code !== 0) {{
                return {{success: false, error: '添加失败: ' + addData.message}};
            }}

            // 等待1秒
            await new Promise(r => setTimeout(r, 1000));

            // Step 2: 从源收藏夹删除
            const delResp = await fetch('https://api.bilibili.com/x/v3/fav/resource/deal', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/x-www-form-urlencoded',
                }},
                body: 'rid={aid}&type=2&del_media_ids={src_fid}&csrf=' + getCSRF(),
                credentials: 'include'
            }});
            const delData = await delResp.json();

            if (delData.code !== 0) {{
                return {{success: false, error: '删除失败: ' + delData.message}};
            }}

            return {{success: true, error: ''}};
        }} catch (e) {{
            return {{success: false, error: e.toString()}};
        }}
    }}
    """

    try:
        # 先确保在B站页面上（这样cookie才能生效）
        if "bilibili.com" not in page.url:
            page.goto("https://www.bilibili.com")
            time.sleep(2)

        result = page.evaluate(js_code)
        return result.get("success", False), result.get("error", "")
    except Exception as e:
        return False, str(e)


def getCSRF():
    """从cookie中获取bili_jct"""
    # 这个函数在JS中通过document.cookie获取
    pass


# ============================================================
# 阶段1: 扫描
# ============================================================

def phase_scan(headless=False, test_count=0):
    """扫描收藏夹，生成文档"""
    from playwright.sync_api import sync_playwright

    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║          阶段1：扫描收藏夹（浏览器模式）                 ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    with sync_playwright() as p:
        browser, context = get_browser_context(p, headless=headless)
        page = context.new_page()

        # 检查登录状态
        if not check_login(page):
            login_and_save_cookies(context)
            if not check_login(page):
                print("  ❌ 登录失败")
                browser.close()
                return

        # 获取所有视频
        print(f"\n  获取默认收藏夹视频...")
        all_videos = fetch_all_videos(page, CONFIG["folders"]["默认"])
        total = len(all_videos)
        print(f"  ✅ 共 {total} 个视频")

        if test_count > 0:
            all_videos = all_videos[:test_count]
            total = test_count

        # 分类
        print(f"\n  开始分类...")
        scan_results = []
        folder_stats = defaultdict(int)
        log_file = open(CONFIG["scan_log"], "w", encoding="utf-8")
        log_file.write(f"B站收藏夹扫描日志\n时间: {datetime.now()}\n总数: {total}\n{'='*60}\n\n")

        for i, video in enumerate(all_videos):
            title = video.get("title", "")
            upper_name = video.get("upper", {}).get("name", "")
            tag = tag_video(video)
            result = classify_video(video)
            target = result["target_folder"]
            folder_stats[target] += 1

            entry = {
                "index": i + 1,
                "aid": video.get("id", 0),
                "bvid": video.get("bvid", ""),
                "title": title,
                "desc": video.get("intro", ""),
                "upper_name": upper_name,
                "upper_mid": video.get("upper", {}).get("mid", 0),
                "page_count": video.get("page_count", 1),
                "duration": video.get("duration", 0),
                "play_count": video.get("cnt_info", {}).get("play", 0),
                "cover": video.get("cover", ""),
                "tags": tag,
                "classify": result,
                "move_status": "pending",
                "move_error": "",
            }
            scan_results.append(entry)

            # 日志
            log_file.write(f"[{i+1}/{total}] {title}\n")
            log_file.write(f"  AV{entry['aid']} | {upper_name}\n")
            log_file.write(f"  标签: [{tag['language']}][{tag['format_type']}][{tag['duration_type']}]\n")
            log_file.write(f"  分类: → {target} ({result['match_rule']})\n\n")

            # 进度
            print(f"\r  [{i+1}/{total}] → {target} | {title[:30]}", end="", flush=True)

        print()
        log_file.close()

        # 保存JSON
        doc = {
            "version": "2.0",
            "generated_at": datetime.now().isoformat(),
            "total_videos": total,
            "folder_stats": dict(folder_stats),
            "videos": scan_results,
        }
        with open(CONFIG["scan_json"], "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)

        print(f"\n  ✅ 扫描完成")
        print(f"  文档: {CONFIG['scan_json']}")
        print(f"  日志: {CONFIG['scan_log']}")
        print(f"\n  分类统计:")
        for folder, count in sorted(folder_stats.items(), key=lambda x: -x[1]):
            print(f"    {folder}: {count}")

        browser.close()


# ============================================================
# 阶段2: 移动
# ============================================================

def phase_move(headless=False, test_count=0):
    """读取文档，通过浏览器移动视频"""
    from playwright.sync_api import sync_playwright

    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║          阶段2：移动视频（浏览器模式）                   ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    # 读取文档
    try:
        with open(CONFIG["scan_json"], "r", encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        print(f"  ❌ 未找到文档: {CONFIG['scan_json']}")
        print("  请先运行 --scan")
        return

    videos = doc["videos"]
    to_move = [v for v in videos if v["move_status"] != "success"]
    already = len(videos) - len(to_move)

    print(f"  总视频: {len(videos)} | 已完成: {already} | 待处理: {len(to_move)}")

    if test_count > 0:
        to_move = to_move[:test_count]

    if not to_move:
        print("  ✅ 全部已移动")
        return

    with sync_playwright() as p:
        browser, context = get_browser_context(p, headless=headless)
        page = context.new_page()

        # 确保在B站页面
        page.goto("https://www.bilibili.com")
        time.sleep(2)

        if not check_login(page):
            login_and_save_cookies(context)
            page.goto("https://www.bilibili.com")
            time.sleep(2)

        src_fid = CONFIG["folders"]["默认"]
        log_file = open(CONFIG["move_log"], "a", encoding="utf-8")
        log_file.write(f"\n{'='*60}\n移动会话: {datetime.now()}\n待处理: {len(to_move)}\n{'='*60}\n\n")

        success = 0
        fail = 0

        for i, entry in enumerate(to_move):
            aid = entry["aid"]
            title = entry["title"]
            target = entry["classify"]["target_folder"]
            rule = entry["classify"]["match_rule"]

            if target == "默认":
                entry["move_status"] = "success"
                success += 1
                continue

            tar_fid = CONFIG["folders"].get(target)
            if not tar_fid:
                entry["move_status"] = "failed"
                entry["move_error"] = f"无fid: {target}"
                fail += 1
                continue

            ok, err = move_video_via_page(page, aid, src_fid, tar_fid)

            if ok:
                entry["move_status"] = "success"
                entry["move_error"] = ""
                success += 1
                log_file.write(f"✅ [{i+1}/{len(to_move)}] {title} → {target}\n")
            else:
                entry["move_status"] = "failed"
                entry["move_error"] = err
                fail += 1
                log_file.write(f"❌ [{i+1}/{len(to_move)}] {title} | {err}\n")

            # 进度
            done = success + fail
            bar_len = 30
            filled = int(bar_len * done / len(to_move))
            bar = "█" * filled + "░" * (bar_len - filled)
            icon = "✅" if ok else "❌"
            print(f"\r  [{bar}] {done}/{len(to_move)} {icon} → {target} | {title[:25]}   ", end="", flush=True)

            # 每20个保存
            if done % 20 == 0:
                with open(CONFIG["scan_json"], "w", encoding="utf-8") as f:
                    json.dump(doc, f, ensure_ascii=False, indent=2)

            # 延迟（浏览器模式可以短一些，因为是真实请求）
            time.sleep(2)

        print()
        log_file.close()

        # 保存最终结果
        with open(CONFIG["scan_json"], "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)

        final_ok = sum(1 for v in videos if v["move_status"] == "success")
        final_fail = sum(1 for v in videos if v["move_status"] == "failed")
        print(f"\n  完成! 成功: {success} | 失败: {fail}")
        print(f"  累计成功: {final_ok} | 累计失败: {final_fail}")

        browser.close()


# ============================================================
# 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="B站收藏夹整理（浏览器自动化版）")
    parser.add_argument("--scan", action="store_true", help="扫描收藏夹")
    parser.add_argument("--move", action="store_true", help="执行移动")
    parser.add_argument("--test", type=int, default=0, help="测试模式，只处理前N个")
    parser.add_argument("--headless", action="store_true", help="无头模式（不显示浏览器窗口）")

    args = parser.parse_args()

    if not args.scan and not args.move:
        parser.print_help()
        print("\n  示例:")
        print("    python bilibili_fav_playwright.py --scan")
        print("    python bilibili_fav_playwright.py --scan --test 50")
        print("    python bilibili_fav_playwright.py --move")
        print("    python bilibili_fav_playwright.py --move --test 10")
        return

    if args.scan:
        phase_scan(headless=args.headless, test_count=args.test)
    if args.move:
        phase_move(headless=args.headless, test_count=args.test)


if __name__ == "__main__":
    main()
