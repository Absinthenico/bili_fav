# B站收藏夹自动整理工具

将 Bilibili 收藏夹中的视频按规则自动分类到指定文件夹，告别手动整理。

## 功能特性

- **两阶段架构**：扫描分类 → 执行移动，分离设计更安全
- **智能分类**：UP主映射 + 关键词匹配 + 默认兜底
- **断点续传**：移动中断后可从断点继续，不会重复操作
- **Playwright 浏览器自动化**：控制真实浏览器操作，彻底绕过反爬

## 分类规则

| 收藏夹 | 分类逻辑 |
|--------|---------|
| 知识提升 | 编程/数学/科技类 UP主 |
| 跑步电台 | 适合通勤/运动时听的内容 |
| 人文知识 | 历史/科普/社会类 |
| 人生自我 | 自我提升/认知成长 |
| 有趣娱乐 | 搞笑/游戏/生活娱乐 |
| 教程 | 各类教程视频 |
| 找工作 | 面试/求职/职场相关 |
| 默认 | 无法匹配的视频 |

优先级：UP主直接映射 > 关键词匹配 > 默认收藏夹

## 快速开始

### 1. 安装依赖

```bash
pip install requests playwright
playwright install chromium
```

### 2. 初始化配置（首次使用）

```bash
python bilibili_fav_playwright.py --setup
```

浏览器会自动打开，登录B站后按回车，脚本会自动：
- 提取 Cookie
- 获取所有收藏夹及 FID
- 生成 `config.json`（登录凭证）
- 生成 `rule.json`（分类规则模板）

### 3. 编辑分类规则

编辑 `rule.json` 自定义你的分类逻辑：

```json
{
    "default_folder": "默认",
    "multi_page": {
        "enabled": true,
        "threshold": 3,
        "target_folder": "教程"
    },
    "up_map": {
        "UP主名称": "目标收藏夹"
    },
    "keyword_rules": [
        {
            "keywords": ["关键词1", "关键词2"],
            "target_folder": "目标收藏夹",
            "scope": "all"
        }
    ]
}
```

- **default_folder**：未匹配视频的归入收藏夹
- **multi_page**：多分P视频自动归类（可关闭）
- **up_map**：UP主 → 收藏夹直接映射
- **keyword_rules**：关键词匹配规则，scope 支持 `"all"`（标题+简介）或 `"title"`（仅标题）

### 4. 运行

```bash
# 扫描阶段：分析所有视频并生成分类文档
python bilibili_fav_playwright.py --scan

# 测试扫描（只处理前 50 个）
python bilibili_fav_playwright.py --scan --test 50

# 移动阶段：执行分类移动
python bilibili_fav_playwright.py --move

# 测试移动（只移动前 10 个）
python bilibili_fav_playwright.py --move --test 10
```

## 项目结构

```
├── bilibili_fav_playwright.py   # 主程序（Playwright 浏览器自动化）
├── config.json                  # 登录凭证（敏感，不入 Git）
├── config.example.json          # 配置模板
├── rule.json                    # 分类规则（可自由修改，不入 Git）
├── rule.example.json            # 规则模板
├── get_cookies.py               # Cookie 获取助手
├── test_move.py                 # 移动功能测试
└── 收藏夹分类需要.md             # 原始需求文档
```

## API 参考

| 接口 | 用途 |
|------|------|
| `/x/v3/fav/resource/list` | 获取收藏夹内容 |
| `/x/v3/fav/resource/deal` | 添加/移除收藏 |
| `/x/frontend/finger/spi` | 刷新设备指纹 |
| `/x/web-interface/nav` | 验证登录状态 |

## 常见问题

**Q: 怎么获取收藏夹 FID？**
打开收藏夹页面，URL 中的数字就是 FID，例如 `space.bilibili.com/123456/favlist?fid=3949211879`

**Q: Cookie 过期了怎么办？**
重新从浏览器获取，更新 `config.json` 即可。

**Q: 移动中断了怎么办？**
直接重新运行 `--move`，脚本会跳过已处理的视频，从断点继续。

## License

MIT
