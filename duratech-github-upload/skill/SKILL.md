---
name: sellersprite-scout
description: 卖家精灵亚马逊选品自动化采集工具。通过卖家精灵选品器 API 采集新品和爆品数据，生成 HTML 筛选页面（含图片、勾选框）和 Excel 报表。支持四大类目、双池（新品池+爆品池）分离输出、每周一定时自动执行。
version: "1.0.0"
author: "DuraTech"
---

# 卖家精灵选品自动化采集 Skill

> 通过卖家精灵 v2 选品器 API，自动采集亚马逊美国站四大类目的新品和爆品数据，生成交互式 HTML 筛选页面和 Excel 报表。

## 功能概述

1. **双池采集**：新品池（月销≥300） + 爆品池（月销≥2000），各自独立输出
2. **HTML 筛选页**：含产品图片、勾选框、类目/标签筛选、一键导出勾选产品到 Excel
3. **Excel 报表**：微软雅黑字体、标签颜色标记、冻结表头、自动筛选
4. **定时任务**：每周一早上 9:00 自动执行

## 前置条件

1. 卖家精灵账号（已登录）
2. 浏览器中导出完整 Cookie JSON（通过 EditThisCookie 插件）

## 使用方法

### 1. 准备 Cookie

用户在 Chrome 中登录卖家精灵后，通过 EditThisCookie 导出完整 JSON，粘贴提供给 Agent。

### 2. 运行采集

```bash
# 采集全部（新品+爆品）
bash /workspace/sellersprite-automation/scripts/run_all.sh

# 仅新品
bash /workspace/sellersprite-automation/scripts/run_all.sh new

# 仅爆品
bash /workspace/sellersprite-automation/scripts/run_all.sh hot
```

### 3. 输出文件

```
/workspace/
  DuraTech 亚马逊新品机会_YYYY-MM-DD.html   ← HTML 筛选页面
  DuraTech 亚马逊新品机会_YYYY-MM-DD.xlsx   ← Excel 报表
  DuraTech 亚马逊爆品机会_YYYY-MM-DD.html
  DuraTech 亚马逊爆品机会_YYYY-MM-DD.xlsx
```

## 目标类目

| 英文名 | 中文名 | BSR ID |
|--------|--------|--------|
| Arts, Crafts & Sewing | 艺术、工艺和缝纫 | arts-crafts |
| Automotive | 汽车用品 | automotive |
| Patio, Lawn & Garden | 庭院、草坪和园艺 | lawn-garden |
| Tools & Home Improvement | 家居装修 | hi |

## 采集规则

### 新品池
- 模式：销量飙升榜 (rapid-growth)
- 月销量 ≥ 300
- 标签：潜力新品（绿色）

### 爆品池
- 模式：销量飙升榜 (rapid-growth)
- 月销量 ≥ 2000
- 标签：标准爆品（橙色，2000-5000）/ 头部爆品（红色，≥5000）

### 导出字段（16列）

产品类目 → ASIN → 品牌 → 主图 → Item Name(标题) → 中文简介 → 近30天销量 → 月销售额 → 零售价 → 上架时间 → 卖家信息 → 评分 → 评论数 → BSR排名 → 变体数 → 标签

## 定时任务

| 任务 | Cron | 时间 |
|------|------|------|
| 新品采集 | `0 0 9 * * 1` | 每周一 09:00 |
| 爆品采集 | `0 0 9 * * 1` | 每周一 09:00 |

## Agent 执行指令

当用户提供卖家精灵 Cookie JSON 后，按以下步骤执行：

1. 将 Cookie JSON 保存到 `sessions/cookies.json`
2. 运行 `python collector.py --type new --max-pages 5`
3. 运行 `python collector.py --type hot --max-pages 5`
4. 运行 `python html_builder.py --json <new_json> --type new`
5. 运行 `python html_builder.py --json <hot_json> --type hot`
6. 运行 `python excel_builder.py --json <new_json> --type new`
7. 运行 `python excel_builder.py --json <hot_json> --type hot`
8. 向用户展示生成的文件路径

## 依赖

- Python 3.11+
- requests, beautifulsoup4, lxml, openpyxl, Pillow
- 不需要浏览器（纯 HTTP API 采集）
