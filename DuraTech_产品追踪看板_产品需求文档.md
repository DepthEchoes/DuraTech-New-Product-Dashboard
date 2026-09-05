# DuraTech 产品追踪看板 · 产品需求文档

| 项目 | 内容 |
|---|---|
| 文档版本 | v3.0（2026-09-04） |
| 产品名称 | DuraTech 亚马逊选品与产品追踪系统（卖家精灵数据） |
| 适用对象 | DuraTech 选品团队 |
| 部署环境 | 阿里云 116.62.43.110 · Ubuntu · systemd `poolboard` · Flask+waitress+nginx+SQLite |

---

## 一、产品概述

DuraTech 系统围绕**亚马逊四大类目**（Arts, Crafts & Sewing / Automotive / Patio, Lawn & Garden / Tools & Home Improvement）的新品与爆品机会做**数据采集 → 筛选 → 追踪管理**的闭环工具：

```
卖家精灵(Cookie) ──采集──▶ 需求池看板（新品池/爆品池）──勾选转入──▶ 产品追踪看板
                                                                │
                          ◀──查竞品批量更新/手动加ASIN(Cookie)─────┘
                          ◀──市场分析附件（HTML/Excel）上传/预览────┘
```

系统含两大看板：**需求池看板**（选品器/筛选用）与**产品追踪看板**（重点产品跟进/市场分析用，本文档核心）。

---

## 二、业务背景与采集规则（项目基础规则）

采集/筛选遵循以下固定规则（卖家精灵批量监控/选品器配置）：

1. **前置全局排除**：成人用品、电子烟、烟草、处方药、生鲜、活体宠物、易燃易爆、侵权 IP。
2. **链接门槛**：评分 ≥3.5、评论 ≥10、排除无品牌铺货杂货店与刷单链接；FBA 优先。
3. **新品池**：上架 ≤30 天、日均销量>5、变体≤5、BSR≤5000、7 天新增评论≥3。
4. **爆品池**：月销>2000、上架≥60 天、近 30 天断货<7 天；月销≥5000 标头部爆品，2000–5000 标标准爆品；风控剔除评价暴涨/价格大幅波动链接。
5. **导出字段**：ASIN、标题、类目、售价、上架日期、日均销量、月预估销量、评分、评论数、变体数、品牌、FBA/FBM、BSR、店铺、主图。

---

## 三、产品追踪看板 · 功能需求

### 3.1 页面布局与交互

| 区域 | 内容 |
|---|---|
| 顶部 Header | 标题、返回需求池导航、右上登录用户/退出 |
| 统计卡 | 总产品、待调研、调研中、已联系、已送样、已合作、放弃、进行中 |
| 图表区 | ① 进度分布（横向堆叠条形图）② 类目分布（环形图），两图各占 50% 铺满、高 250px |
| 工具栏 | 进度筛选 / 类目筛选 / 追踪人筛选 / 搜索 / 批量更改进度 / 📥导出CSV / 🔍产品信息更新 / ➕添加ASIN / 🔄重置排序 |
| 产品表格 | 进行中（活跃）表 + 已合作区 + 放弃池 |
| 滚动 | **整页全局滚动，表头（标题行）吸顶冻结**（3 个表各自 sticky） |

### 3.2 表格列（当前 14 列）

**排序｜追踪人｜主图(120×120)｜类目⇅｜进度(备注 210×120 文本框)｜ASIN｜标题(宽180)｜来源｜近30天销量(含环比标注)｜售价(含变化标注)｜上架时间｜评分｜📎市场分析｜📌当前进度(状态选择)**

> 历史列迭代：曾包含 标签/品牌/月销售额/评论/BSR/变体 等列，均已按需求移除；变化标注随列一并去除。

### 3.3 核心功能需求

| # | 功能 | 需求说明 |
|---|---|---|
| F1 | 进度管理 | 每行「进度」备注框（210×120，多行可滚，Enter 换行）；「当前进度」下拉：待调研→调研中→已联系→已送样→已合作→放弃；编辑自动保存（localStorage+服务端） |
| F2 | 追踪人 | 每行可填追踪人，进入「追踪人」筛选；下拉**自动抓取看板中所有出现的追踪人** |
| F3 | 类目 | 手动添加时**自动识别四大类**（查竞品 `data-nodeIdPath` 首段映射）；不属于四大类自动填「其他」；类目列点击**按四大类顺序升/降序排序**；下拉自动抓取全部类目（含「其他」） |
| F4 | 搜索 | 按 ASIN / 标题实时过滤 |
| F5 | 批量进度 | 勾选多行后批量更改到某进度 |
| F6 | 拖拽/排序 | 行内上移/下移按钮 + 拖拽排序；重置排序=新品优先按销量降序 |
| F7 | 导出 CSV | 一键导出当前可见产品完整数据 |
| F8 | 手动添加 ASIN | 输入 ASIN → 校验重复/格式 → Cookie 检测（有效自动开始/过期弹上传卡）→ 抓取大类+变体+全部字段 → 加入看板（待调研）；**变体数从查竞品产品行抓取** |
| F9 | 产品信息更新 | 一键用卖家精灵「查竞品」批量刷新全部进行中产品（近30天销量/售价/BSR/评分/评论等），并在列下方**标注变化**（销量/售价环比，来自查竞品指标卡）；Cookie 有效直接跑、过期提示上传；进度条+实时日志 |
| F10 | 市场分析 | 每行 📎 入口，弹窗支持**多附件上传（HTML/Excel）→ 列表 → 新标签页预览**；附件存 `output/attachments/{asin}/`；行内角标实时显示附件数，**任何筛选/排序后保持与实际一致** |
| F11 | Cookie 机制 | 页面上传卖家精灵 Cookie（EditThisCookie JSON）→ 服务端校验（JSESSIONID/Sprite-X-Token）→ 任务前自动检测：有效直接开始，过期提示重新上传 |
| F12 | 图表交互 | 进度分布条形图（5 类 ×4 进行中进度，色块带数字）——**点击任意色块自动筛选下方产品**为该类目+该进度 |
| F13 | 任务进度条 | 「产品信息更新/添加ASIN」显示步骤+百分比+日志，完成自动刷新 |
| F14 | 风险拦截 | 无效 ASIN（查竞品查不到）拒绝添加；重复 ASIN 提示已在看板 |

### 3.4 数据字段（canonical 产品记录）

`asin / title / image / price / sales(近30天) / monthly_sales / bsr / rating / reviews / variants / category(四大类或"其他") / available / _progress / _subcategory(进度备注) / _tracker / _source(new|hot|manual) / sales_pct / monthly_pct / price_pct / bsr_delta / bsr_pct / lookup_at`

> 变化标注字段由「查竞品」结果写入（页面指标卡环比），列显示仅保留：近30天销量、售价两项的变化。

---

## 四、需求池看板（简述）

- 左侧类目树（四大类 + 细分子类目）导航与筛选
- 新品池/爆品池双标签页，产品卡片展示全部导出字段 + 图片 + 中文类目
- 勾选产品 → 一键转入追踪看板（转入后从需求池移除、去重）
- 手动采集（Cookie 上传 → 后台任务 → 进度条/日志）与状态监控
- 用户/权限：注册登录、管理员、用户管理、Cookie 安全存储

---

## 五、非功能需求

| 类别 | 要求 |
|---|---|
| 性能 | 批量更新 26 产品约 16s（卖家精灵限流时延迟）；页面自适应 1560/600px |
| 安全 | 登录鉴权（cookie+token）；XSS 转义；Cookie 文件 0600；接口白名单 |
| 数据一致性 | canonical `transferred_products.json` 为追踪看板唯一数据源；SQLite progress 表存进度/追踪人/排序；附件目录独立 |
| 稳定性 | waitress 单进程多线程（任务状态共享）；import_lock 串行化看板重建；防空数据覆盖 canonical |
| 兼容 | 依赖卖家精灵账号 Cookie 有效性（约 24h/会话），页面自动检测提示续期 |

---

## 六、主要接口（后端）

| 方法/路径 | 说明 |
|---|---|
| POST `/api/auth/login\|register\|logout`、GET `/api/auth/me` | 账号 |
| POST `/api/cookie` | 上传卖家精灵 Cookie（含 task 参数，触发 collect/lookup_update/lookup_add 异步任务） |
| GET `/api/cookie/check` | 检测当前 Cookie 是否有效（供前端决定直跑/弹上传） |
| GET `/api/collection/status` | 任务状态（task_type/step/progress/logs/result） |
| POST `/api/tracking/update/start`、`/api/tracking/add/start` | Cookie 有效时直接启动异步更新/添加 |
| POST `/api/tracking/add`、`/api/tracking/refresh` | 同步版添加/批量刷新（脚本/回归测试） |
| GET `/api/tracking/exists?asin=` | 添加前查重 |
| GET/POST `/api/tracking/edits` | 进度/备注/追踪人/排序 服务端持久化 |
| GET `/api/market/list?asin=`、`/api/market/counts?asins=` | 附件列表 / 批量计数 |
| POST `/api/market/upload` | 上传附件（HTML/Excel，多文件） |
| GET `/api/market/file/<asin>/<name>` | 新标签页预览附件 |

---

## 七、技术架构

| 层 | 技术 |
|---|---|
| 前端 | 服务端渲染 HTML（f-string 模板 + 占位符注入），Chart.js 4 + chartjs-plugin-datalabels，原生 JS（无框架） |
| 后端 | Python 3.11 / Flask / waitress |
| 数据 | SQLite（`board.db`）+ JSON canonical（`output/transferred_products.json`）+ 附件目录 `output/attachments/` |
| 采集 | requests.Session + 卖家精灵 Cookie；查竞品接口 `/v2/competitor-lookup/monthly`（按 ASIN 单查，含大类/变体/销量/BSR 标注/趋势）；产品研究接口 `/v2/product-research/monthly`（需求池类目采集） |
| 部署 | systemd `poolboard` + nginx 反代 58901；部署包 `duratech-deploy.tar.gz` 解包至 `/workspace` 后重启服务 |

---

## 八、部署与运维

```bash
# 更新（本地打包 → 上传 → 解包 → 重启）
scp duratech-deploy.tar.gz root@116.62.43.110:/root/
ssh root@116.62.43.110 "find /workspace/sellersprite-automation -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null; \
  tar -xzf /root/duratech-deploy.tar.gz -C /workspace && \
  systemctl restart poolboard && sleep 3 && systemctl is-active poolboard"
```

- 页面无变化 → 强刷浏览器（Ctrl+Shift+R）
- 「产品信息更新/添加 ASIN」提示 Cookie 过期 → 卖家精灵重新登录并导出新 Cookie 上传；卖家精灵限流（频繁请求）也会临时判无效，等待 10–30 分钟自动恢复
- 查看服务：`journalctl -u poolboard -f`

---

## 九、版本记录（主要迭代）

| 版本 | 日期 | 关键内容 |
|---|---|---|
| v1 | 07 月 | 采集器/Excel/需求池 HTML 筛选页 |
| v2 | 08 月 | 双池看板（新品/爆品）、追踪看板 v1、拖拽排序、账号系统、Cookie 安全、在线部署 |
| v2.5 | 08 下旬 | 细分类目采集、类目树导航、多用户、追踪人字段 |
| v3.0 | 09-03 | 追踪看板改造：去标签列/3按钮、列居中；查竞品批量更新+销量/月销/售价/BSR 变化标注；手动添加 ASIN；Cookie 上传卡+进度条；手动添加抓**大类+变体数**；Cookie 自动检测 |
| v3.1 | 09-04 | 删月销售额/评论/BSR/变体 4 列；主图 120×120；进度分布堆叠条形图+色块数字+点击联动筛选；类目/追踪人下拉自动抓取；非四大类自动填「其他」；市场分析附件计数保真修复；进度框 210×120；整页滚动表头吸顶 |
