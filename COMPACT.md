# Bilibili 收藏夹分类整理工具 - 项目状态文档

## 📌 项目概述

将 B站收藏夹中的 8422 个视频自动分类整理到 8 个指定文件夹中。

### 分类文件夹

| 文件夹名 | FID |
|---------|-----|
| 默认 | 72931279 |
| 菜单2 | 4057624379 |
| 知识提升 | 3949211879 |
| 找工作 | 3898208379 |
| 跑步电台 | 3949211779 |
| 教程 | 3922793979 |
| 人文知识 | 3919222579 |
| 人生自我 | 3955210779 |
| 有趣娱乐 | 3898191479 |

---

## 🏗️ 技术架构

### 两阶段设计

```
阶段1: --scan   → 生成 scan_result.json (包含所有视频分类结果)
阶段2: --move   → 读取 scan_result.json 并执行移动 (支持断点续传)
```

### 两个版本

1. **bilibili_fav_organizer.py** - requests 版本 (遇到 412 反爬)
2. **bilibili_fav_playwright.py** - Playwright 浏览器版本 (推荐)

### 关键 API

| API | 用途 | 参数格式 |
|-----|------|---------|
| `/x/v3/fav/resource/list` | 获取收藏夹内容 | GET |
| `/x/v3/fav/resource/deal` | 添加/移除收藏 | POST, `rid=aid&type=2&add_media_ids=fid&csrf=xxx` |
| `/x/frontend/finger/spi` | 刷新设备指纹 | GET |
| `/x/web-interface/nav` | 验证登录状态 | GET |

---

## ✅ 已解决的问题

| 问题 | 解决方案 |
|------|---------|
| POST `Expecting value` 错误 | 移除已废弃的 batch API，改用单视频 API |
| `code=2001000 参数错误` | 使用 `type=2`, `add_media_ids` (无方括号) |
| pip ProxyError | `pip install --proxy="" -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| Git 中文路径乱码 | 将 `小工具` 重命名为 `some-tool` |
| Git 找不到 | 路径: `D:\some-tool\git\Git\cmd\git.exe` |

---

## ⚠️ 当前问题

### 文件丢失

**所有项目文件已从 `D:\工作` 目录丢失**，目前只剩：
- `.git/` (空仓库)
- `.idea/` (IDE 配置)
- `__pycache__/` (编译缓存)

### HTTP 412 反爬

Bilibili 检测到脚本化请求后会返回 412 错误。requests 版本无法彻底解决，需要使用 Playwright 浏览器版本。

---

## 📋 待办事项

- [ ] **重建所有项目文件** (见下方文件清单)
- [ ] 测试 Playwright 安装: `playwright install chromium`
- [ ] 测试视频移动功能
- [ ] 配置 GitHub 仓库 (使用 config.example.json + .gitignore)
- [ ] 执行完整扫描和移动

---

## 📁 文件清单 (需重建)

### 1. config.json (敏感，不入 Git)
```json
{
  "cookies": {
    "SESSDATA": "你的SESSDATA",
    "bili_jct": "你的bili_jct",
    "DedeUserID": "12540779",
    "buvid3": "你的buvid3",
    "buvid4": "你的buvid4",
    "b_nut": "你的b_nut",
    "b_lsid": "你的b_lsid"
  },
  "folders": {
    "默认": 72931279,
    "菜单2": 4057624379,
    "知识提升": 3949211879,
    "找工作": 3898208379,
    "跑步电台": 3949211779,
    "教程": 3922793979,
    "人文知识": 3919222579,
    "人生自我": 3955210779,
    "有趣娱乐": 3898191479
  }
}
```

### 2. config.example.json (模板，入 Git)

### 3. .gitignore
```
config.json
scan_result_*.json
*.log
.bilibili_cookies.json
__pycache__/
test_move.py
get_cookies.py
```

### 4. bilibili_fav_organizer.py (requests 版本)

核心功能：
- `--scan`: 遍历所有视频，生成分类文档
- `--move`: 读取文档执行移动，支持断点续传
- 412 处理: 指数退避 30s→60s→120s

### 5. bilibili_fav_playwright.py (浏览器版本)

核心功能：
- 使用 Playwright 控制真实 Chromium
- 在浏览器上下文中执行 fetch() 绕过反爬
- 保存/加载浏览器 cookies

### 6. 收藏夹分类需要.md

用户原始需求文档，包含：
- UP主 映射规则
- 关键词匹配规则
- 标题/描述分析规则

---

## 🔧 运行指南

### 安装依赖
```bash
pip install requests playwright --proxy="" -i https://pypi.tuna.tsinghua.edu.cn/simple
playwright install chromium
```

### 执行分类 (扫描阶段)
```bash
python bilibili_fav_playwright.py --scan
```

### 执行移动
```bash
python bilibili_fav_playwright.py --move
```

### GitHub 推送
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/你的用户名/bilibili-fav-organizer.git
git push -u origin main
```

---

## 📊 Cookie 获取方法

1. 打开 Bilibili 网页版
2. 按 F12 → Application → Cookies
3. 复制以下字段：
   - SESSDATA
   - bili_jct
   - DedeUserID
   - buvid3
   - buvid4
   - b_nut
   - b_lsid

---

## 🔗 Git 路径

Git 可执行文件路径 (如 PATH 中找不到):
```
D:\some-tool\git\Git\cmd\git.exe
```

临时设置:
```powershell
$env:PATH = "D:\some-tool\git\Git\cmd;" + $env:PATH
```

---

*文档创建时间: 2026-06-12*
