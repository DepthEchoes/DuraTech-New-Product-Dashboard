"""
DURATECH 卖家精灵自动化采集 - 配置常量
"""

# ============================================================
# 卖家精灵 URL
# ============================================================
BASE_URL = "https://www.sellersprite.com/cn"
LOGIN_URL = "https://www.sellersprite.com/cn/w/user/login"
PRODUCT_RESEARCH_URL = "https://www.sellersprite.com/v2/product-research"
# 关键 API 端点（POST）
API_URL = "https://www.sellersprite.com/v2/product-research/monthly"

# ============================================================
# 四大目标类目
# ============================================================
CATEGORIES = [
    "Arts, Crafts & Sewing",
    "Automotive",
    "Patio, Lawn & Garden",
    "Tools & Home Improvement",
]

CATEGORY_SHORT_NAMES = {
    "Arts, Crafts & Sewing": "ArtsCrafts",
    "Automotive": "Automotive",
    "Patio, Lawn & Garden": "PatioLawn",
    "Tools & Home Improvement": "ToolsHome",
}

# 类目 BSR ID 映射（来自卖家精灵 v2 后端精确对应）
# 索引 -> bsrIds[N] = 类目短码, titles[N] = 类目显示名
BSR_CATEGORY_MAP = {
    1:  ("",                        ""),
    2:  ("amazon-devices",          "Amazon Devices & Accessories"),
    3:  ("boost",                   "Amazon Launchpad"),
    4:  ("appliances",              "Appliances"),
    5:  ("arts-crafts",             "Arts, Crafts & Sewing"),
    6:  ("automotive",              "Automotive"),
    7:  ("baby-products",           "Baby"),
    8:  ("beauty",                  "Beauty & Personal Care"),
    10: ("music",                   "CDs & Vinyl"),
    11: ("photo",                   "Camera & Photo"),
    12: ("wireless",                "Cell Phones & Accessories"),
    13: ("fashion",                 "Clothing, Shoes & Jewelry"),
    14: ("pc",                      "Computers & Accessories"),
    15: ("electronics",             "Electronics"),
    16: ("gift-cards",              "Gift Cards"),
    17: ("grocery",                 "Grocery & Gourmet Food"),
    18: ("handmade",                "Handmade Products"),
    19: ("hpc",                     "Health & Household"),
    20: ("home-garden",             "Home & Kitchen"),
    21: ("industrial",              "Industrial & Scientific"),
    22: ("digital-text",            "Kindle Store"),
    23: ("kitchen",                 "Kitchen & Dining"),
    24: ("musical-instruments",     "Musical Instruments"),
    25: ("office-products",         "Office Products"),
    26: ("lawn-garden",             "Patio, Lawn & Garden"),
    27: ("pet-supplies",            "Pet Supplies"),
    28: ("pantry",                  "Prime Pantry"),
    29: ("software",                "Software"),
    30: ("sporting-goods",          "Sports & Outdoors"),
    31: ("sports-collectibles",     "Sports Collectibles"),
    32: ("hi",                      "Tools & Home Improvement"),
    33: ("toys-and-games",          "Toys & Games"),
    34: ("videogames",              "Video Games"),
}

# 类目名 -> bsrIds 索引
CATEGORY_BSR_INDEX = {
    "Arts, Crafts & Sewing": 5,
    "Automotive": 6,
    "Patio, Lawn & Garden": 26,
    "Tools & Home Improvement": 32,
}

# 类目中文名
CATEGORY_CN_MAP = {
    "Arts, Crafts & Sewing": "艺术、工艺和缝纫",
    "Automotive": "汽车用品",
    "Patio, Lawn & Garden": "庭院、草坪和园艺",
    "Tools & Home Improvement": "家居装修",
}

# ============================================================
# 类目黑名单 (关键词，不区分大小写)
# ============================================================
BLACKLIST_KEYWORDS = [
    "成人用品", "adult", "sex toy",
    "电子烟", "vape", "e-cigarette", "e-liquid",
    "烟草", "tobacco", "cigarette", "cigar",
    "处方药", "prescription", "pharmaceutical",
    "生鲜食品", "fresh food", "perishable",
    "活体宠物", "live pet", "live animal",
    "易燃易爆", "flammable", "explosive", "hazardous",
    "侵权", "infringement", "counterfeit",
]

# ============================================================
# 统一基础门槛
# ============================================================
MIN_RATING = 3.5          # 评分 >= 3.5
MIN_REVIEWS = 10           # 评论数 >= 10
FBA_PRIORITY = True        # FBA 优先

# 无品牌/杂货店排除关键词
NO_BRAND_KEYWORDS = ["generic", "unbranded", "no brand", "n/a", "无品牌", "no logo"]

# ============================================================
# 新品搜集条件
# ============================================================
NEW_PRODUCT = {
    "max_days_listed": 30,          # 上架 <=30天
    "min_daily_sales": 5,            # 日均销量 >5
    "max_variations": 5,             # 变体数量 <=5
    "max_bsr_rank": 5000,            # BSR类目排名 <=5000
    "min_weekly_new_reviews": 3,     # 7天新增评论 >=3
    "label": "潜力新品",
}

# ============================================================
# 爆品搜集条件
# ============================================================
HOT_PRODUCT = {
    "min_monthly_sales": 2000,       # 月销量 >2000
    "min_days_listed": 60,           # 上架 >=60天
    "max_outofstock_days": 7,        # 断货 <7天
    "standard_min": 2000,            # 标准爆品下限
    "standard_max": 5000,            # 标准爆品上限
    "head_min": 5000,                # 头部爆品下限
    "label_standard": "标准爆品",
    "label_head": "头部爆品",
}

# ============================================================
# 选品模式参数 (API 请求参数)
# 根据用户截图：月销量≥5 + 上架时间=近30天 + 无月销量环比
# ============================================================
COLLECT_MODES = {
    "new": {
        "minSales": 5,                 # 月销量 ≥5
        "putawayMonth": "1",           # 上架时间=近30天
        "monthName": "bsr_sales_nearly",  # 月份=最近30天
        "label": "潜力新品",
        "output_prefix": "DuraTech 亚马逊新品机会",
    },
    "hot": {
        "minSales": 2000,              # 月销量 ≥2000
        "putawayMonth": "12",          # 上架时间=近1年（爆品要已上架一定时间）
        "monthName": "bsr_sales_nearly",
        "label": "爆品",
        "output_prefix": "DuraTech 亚马逊爆品机会",
    },
}

# ============================================================
# 风控剔除条件
# ============================================================
RISK_CONTROL = {
    "max_daily_new_reviews": 200,     # 单日新增评论 >200 剔除
    "max_price_volatility": 0.6,      # 30天售价波动 >60% 剔除
    "max_review_spike_ratio": 0.5,    # 7天新增/总评论 >50% 可疑
}

# ============================================================
# 导出字段 (18列)
# ============================================================
EXPORT_FIELDS = [
    "产品类目",
    "ASIN",
    "品牌",
    "主图",
    "Item Name(标题)",
    "中文简介",
    "近30天销量(父体)",
    "月销售额",
    "零售价",
    "上架时间",
    "卖家信息",
    "评分",
    "评论数",
    "BSR排名",
    "变体数",
    "标签",
]

# ============================================================
# 采集配置
# ============================================================
MAX_PAGES_PER_CATEGORY = 50   # 每个类目最大翻页数
PAGE_DELAY_MIN = 2             # 页面间最小等待秒数
PAGE_DELAY_EXTRA = 3           # 每5页额外延时
REQUEST_TIMEOUT = 30           # 页面加载超时(秒)

# ============================================================
# 输出配置
# ============================================================
OUTPUT_DIR = "/workspace/sellersprite-automation/output"
LOGS_DIR = "/workspace/sellersprite-automation/logs"
SESSIONS_DIR = "/workspace/sellersprite-automation/sessions"
WORKSPACE_OUTPUT = "/workspace"
FILE_PREFIX = "DURATECH_亚马逊产品机会"
