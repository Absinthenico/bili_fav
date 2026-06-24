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
  python bilibili_fav_playwright.py --setup             # 首次使用，初始化配置
  python bilibili_fav_playwright.py --scan              # 扫描
  python bilibili_fav_playwright.py --scan --test 50    # 测试扫描
  python bilibili_fav_playwright.py --move              # 移动
  python bilibili_fav_playwright.py --move --test 10    # 测试移动

配置文件：
  config.json  — 登录凭证（--setup 自动生成）
  rule.json    — 分类规则（--setup 生成模板，可自行编辑）
==========================================================
"""

import os
import json
import time
import re
import argparse
from datetime import datetime
from collections import Counter, defaultdict

# ============================================================
# 配置加载
# ============================================================

_dir = os.path.dirname(os.path.abspath(__file__))

# 全局变量，由 load_config() 填充
FOLDERS = None
RULES = None

CONFIG = {
    "output_dir": "D:\\工作",
    "scan_json": "D:\\工作\\收藏夹扫描结果.json",
    "scan_log": "D:\\工作\\收藏夹扫描日志.txt",
    "move_log": "D:\\工作\\收藏夹移动日志.txt",
    "cookie_file": "D:\\工作\\.bilibili_cookies.json",
}


def _load_json(filename):
    """加载同目录下的 JSON 文件，不存在返回 None"""
    path = os.path.join(_dir, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _validate_rule(rule):
    """验证规则文件结构，返回是否有效"""
    errors = []
    if "up_map" not in rule:
        errors.append("缺少 up_map 字段")
    if "keyword_rules" not in rule:
        errors.append("缺少 keyword_rules 字段")
    for i, kw_rule in enumerate(rule.get("keyword_rules", [])):
        if "keywords" not in kw_rule:
            errors.append(f"keyword_rules[{i}] 缺少 keywords 字段")
        if "target_folder" not in kw_rule:
            errors.append(f"keyword_rules[{i}] 缺少 target_folder 字段")
    if errors:
        print("  ❌ rule.json 格式错误:")
        for e in errors:
            print(f"     - {e}")
        return False
    return True


def load_config():
    """加载 config.json 和 rule.json，供 --scan / --move 使用"""
    global FOLDERS, RULES

    config_data = _load_json("config.json")
    if not config_data:
        print("  ❌ 未找到 config.json，请先运行: python bilibili_fav_playwright.py --setup")
        raise SystemExit(1)

    rule_data = _load_json("rule.json")
    if not rule_data:
        print("  ❌ 未找到 rule.json，请先运行: python bilibili_fav_playwright.py --setup")
        raise SystemExit(1)

    if not _validate_rule(rule_data):
        raise SystemExit(1)

    FOLDERS = config_data["folders"]
    RULES = rule_data


# ============================================================
# 分类器（复用规则逻辑）
# ============================================================

def classify_video(video: dict) -> dict:
    """对单个视频进行分类（规则来自 rule.json）"""
    title = video.get("title", "")
    upper_name = video.get("upper", {}).get("name", "").strip()
    page_count = video.get("page_count", 1)
    desc = video.get("intro", "")

    default_folder = RULES.get("default_folder", "默认")

    # 规则1: UP主
    up_map = RULES.get("up_map", {})
    if upper_name in up_map:
        return {"target_folder": up_map[upper_name],
                "match_rule": f"UP主匹配: {upper_name}", "confidence": 1.0}

    # 规则2: 关键词
    for kw_rule in RULES.get("keyword_rules", []):
        keywords = kw_rule["keywords"]
        folder = kw_rule["target_folder"]
        scope = kw_rule.get("scope", "all")
        for kw in keywords:
            kw_lower = kw.lower()
            text = (title + " " + desc).lower() if scope == "all" else title.lower()
            if kw_lower in text:
                source = "简介" if kw_lower in desc.lower() and kw_lower not in title.lower() else "标题"
                return {"target_folder": folder,
                        "match_rule": f"关键词: '{kw}' ({source})", "confidence": 0.9}

    # 规则3: 多分P
    mp = RULES.get("multi_page", {})
    if mp.get("enabled", False) and page_count > mp.get("threshold", 3):
        return {"target_folder": mp.get("target_folder", default_folder),
                "match_rule": f"多分P ({page_count}P)", "confidence": 0.7}

    return {"target_folder": default_folder, "match_rule": "无匹配", "confidence": 0.0}


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

    load_config()

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
        default_folder = RULES.get("default_folder", "默认")
        print(f"\n  获取「{default_folder}」收藏夹视频...")
        all_videos = fetch_all_videos(page, FOLDERS[default_folder])
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

    load_config()

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

        default_folder = RULES.get("default_folder", "默认")
        src_fid = FOLDERS[default_folder]
        log_file = open(CONFIG["move_log"], "a", encoding="utf-8")
        log_file.write(f"\n{'='*60}\n移动会话: {datetime.now()}\n待处理: {len(to_move)}\n{'='*60}\n\n")

        success = 0
        fail = 0

        for i, entry in enumerate(to_move):
            aid = entry["aid"]
            title = entry["title"]
            target = entry["classify"]["target_folder"]
            rule = entry["classify"]["match_rule"]

            if target == default_folder:
                entry["move_status"] = "success"
                success += 1
                continue

            tar_fid = FOLDERS.get(target)
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

def _write_rule_template(rule_path, folder_names, default_folder):
    """生成 rule.json 模板"""
    rule_template = {
        "_说明": "分类规则配置 — 修改此文件即可自定义分类逻辑，无需改代码",
        "default_folder": default_folder,
        "multi_page": {
            "enabled": False,
            "threshold": 3,
            "target_folder": folder_names[1] if len(folder_names) > 1 else default_folder
        },
        "up_map": {},
        "keyword_rules": [
            {
                "keywords": ["关键词1", "关键词2"],
                "target_folder": folder_names[1] if len(folder_names) > 1 else default_folder,
                "scope": "all"
            }
        ]
    }

    with open(rule_path, "w", encoding="utf-8") as f:
        json.dump(rule_template, f, ensure_ascii=False, indent=2)
    print(f"  ✅ 规则模板已保存到: {rule_path}")
    print(f"  💡 请编辑 rule.json 添加你的分类规则，然后再运行 --scan")


def phase_setup():
    """
    初始化配置：自动获取 Cookie 和收藏夹列表，生成 config.json 和 rule.json
    """
    from playwright.sync_api import sync_playwright

    print("\n" + "=" * 60)
    print("  B站收藏夹整理 - 初始化配置")
    print("=" * 60)

    config_path = os.path.join(_dir, "config.json")
    rule_path = os.path.join(_dir, "rule.json")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/126.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # Step 1: 登录
        print("\n  📌 第1步：登录B站")
        print("  浏览器即将打开，请登录你的B站账号...")
        page.goto("https://passport.bilibili.com/login")
        input("\n  登录完成后，按回车继续...")

        # 验证登录
        page.goto("https://api.bilibili.com/x/web-interface/nav")
        content = page.content()
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if not json_match:
            print("  ❌ 无法获取登录信息，请重试")
            browser.close()
            return

        nav_data = json.loads(json_match.group())
        if nav_data.get("code") != 0:
            print("  ❌ 未登录或登录失败，请重试")
            browser.close()
            return

        uname = nav_data["data"].get("uname", "未知")
        mid = nav_data["data"].get("mid", 0)
        print(f"  ✅ 登录成功: {uname} (UID: {mid})")

        # Step 2: 提取 Cookie
        print("\n  📌 第2步：提取 Cookie")
        cookies = context.cookies()
        cookie_dict = {}
        for c in cookies:
            if c["name"] in ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5",
                             "buvid3", "buvid4", "b_nut", "b_lsid"]:
                cookie_dict[c["name"]] = c["value"]

        if "DedeUserID" not in cookie_dict:
            cookie_dict["DedeUserID"] = str(mid)

        print(f"  ✅ 获取到 {len(cookie_dict)} 个 Cookie 字段")

        # Step 3: 获取收藏夹列表
        print("\n  📌 第3步：获取收藏夹列表")
        page.goto(f"https://api.bilibili.com/x/v3/fav/folder/created/list-all?up_mid={mid}")
        content = page.content()
        json_match = re.search(r'\{.*\}', content, re.DOTALL)

        folders = {}
        if json_match:
            folder_data = json.loads(json_match.group())
            if folder_data.get("code") == 0:
                folder_list = folder_data.get("data", {}).get("list", [])
                for f in folder_list:
                    folders[f["title"]] = f["id"]
                    print(f"    📁 {f['title']} (FID: {f['id']}, 视频数: {f['media_count']})")
                print(f"  ✅ 共 {len(folders)} 个收藏夹")
            else:
                print(f"  ⚠ 获取收藏夹失败: {folder_data.get('message')}")
        else:
            print("  ⚠ 解析收藏夹列表失败")

        # Step 4: 生成 config.json
        print("\n  📌 第4步：生成 config.json")
        config = {
            "cookies": cookie_dict,
            "folders": folders
        }

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        print(f"  ✅ 配置已保存到: {config_path}")

        # 保存浏览器 cookie（备用）
        full_cookies = context.cookies()
        with open(CONFIG["cookie_file"], "w", encoding="utf-8") as f:
            json.dump(full_cookies, f, ensure_ascii=False, indent=2)
        print(f"  ✅ 浏览器 Cookie 已保存到: {CONFIG['cookie_file']}")

        browser.close()

    # Step 5: 生成 rule.json
    folder_names = list(folders.keys())
    default_folder = folder_names[0] if folder_names else "默认"

    if os.path.exists(rule_path):
        print(f"\n  ⚠ rule.json 已存在")
        confirm = input("  是否覆盖？输入 y 确认，其他跳过: ").strip().lower()
        if confirm != "y":
            print("  ℹ 已跳过 rule.json，保留现有规则")
        else:
            _write_rule_template(rule_path, folder_names, default_folder)
    else:
        print("\n  📌 第5步：生成 rule.json 分类规则模板")
        _write_rule_template(rule_path, folder_names, default_folder)

    print("\n" + "=" * 60)
    print("  🎉 初始化完成！")
    print("  下一步:")
    print("    1. 编辑 rule.json 配置分类规则（可选）")
    print("    2. python bilibili_fav_playwright.py --scan")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="B站收藏夹整理（浏览器自动化版）")
    parser.add_argument("--setup", action="store_true", help="初始化配置（自动获取Cookie和收藏夹）")
    parser.add_argument("--scan", action="store_true", help="扫描收藏夹")
    parser.add_argument("--move", action="store_true", help="执行移动")
    parser.add_argument("--test", type=int, default=0, help="测试模式，只处理前N个")
    parser.add_argument("--headless", action="store_true", help="无头模式（不显示浏览器窗口）")

    args = parser.parse_args()

    if not args.setup and not args.scan and not args.move:
        parser.print_help()
        print("\n  示例:")
        print("    python bilibili_fav_playwright.py --setup            # 首次使用，初始化配置")
        print("    python bilibili_fav_playwright.py --scan             # 扫描收藏夹")
        print("    python bilibili_fav_playwright.py --scan --test 50   # 测试扫描")
        print("    python bilibili_fav_playwright.py --move             # 执行移动")
        print("    python bilibili_fav_playwright.py --move --test 10   # 测试移动")
        return

    if args.setup:
        phase_setup()
    if args.scan:
        phase_scan(headless=args.headless, test_count=args.test)
    if args.move:
        phase_move(headless=args.headless, test_count=args.test)


if __name__ == "__main__":
    main()
