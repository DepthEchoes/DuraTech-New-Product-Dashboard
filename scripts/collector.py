"""
DURATECH 卖家精灵选品数据采集器 (HTTP POST API + page 翻页)
通过卖家精灵 v2 POST 接口获取数据，支持翻页突破 60 产品限制
关键发现：翻页只需在 POST 数据中添加 page=N&size=60 参数
"""
import json
import sys
import os
import re
from pathlib import Path
from datetime import datetime
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import (
    BASE_URL, CATEGORIES, CATEGORY_SHORT_NAMES,
    CATEGORY_BSR_INDEX, BSR_CATEGORY_MAP,
    OUTPUT_DIR, SESSIONS_DIR, MAX_PAGES_PER_CATEGORY,
    COLLECT_MODES, HOT_PRODUCT, API_URL,
    SUB_CATEGORIES, TARGET_SUBCATEGORY_NAMES,
)

COOKIES_PATH = Path(SESSIONS_DIR) / "cookies.json"


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def build_request_data(category_en, mode_config, page_num=1, page_size=60, node_id_path=None):
    """
    构造 POST 请求数据
    翻页关键：添加 page=N&size=60 参数
    node_id_path: 细分类目 nodeIdPath（如 '15684181:15718271'=Automotive:Car Care），
                  传入后卖家精灵后端直接按该最小细分类目过滤返回产品
    """
    target_idx = CATEGORY_BSR_INDEX[category_en]

    data = {
        "marketId": "1",
        "nodeIdPath": node_id_path or "",
        "order.field": "total_units",
        "order.desc": "true",
        "symbol": "Y",
        "type": "monthly",
        "tips_op_message": "",
        "tips_op_flag": "",
        "presetMode": "",
        "station": "US",
        "remainExportNum": "NEBD",
        "months": "",
        "showMode": "Y",
        "smallAndLight": "",
        "selectType": "1",
        "allChecked": "false",
        "category-in-chinese": "on",
        "monthName": mode_config.get("monthName", "bsr_sales_nearly"),
        "minSales": str(mode_config.get("minSales", 5)),
        "maxSales": "",
        "minAmount": "",
        "maxAmount": "",
        "minRanking": "",
        "maxRanking": "",
        "minRankingCv": "",
        "maxRankingCv": "",
        "minReviews": "",
        "maxReviews": "",
        "minReviewRating": "",
        "maxReviewRating": "",
        "minFba": "",
        "maxFba": "",
        "minDeliveryPrice": "",
        "maxDeliveryPrice": "",
        "lqsFrom": "",
        "lqsTo": "",
        "minSellers": "",
        "maxSellers": "",
        "minProfit": "",
        "maxProfit": "",
        "dimensionTypes": "",
        "minTotalUnitsGrowth": "",
        "maxTotalUnitsGrowth": "",
        "minTotalAmountGrowth": "",
        "maxTotalAmountGrowth": "",
        "minRankingCr": "",
        "maxRankingCr": "",
        "minPrice": "",
        "maxPrice": "",
        "minReviewsGrouth": "",
        "maxReviewsGrouth": "",
        "minQuestions": "",
        "maxQuestions": "",
        "weightUnit": "g",
        "minWeights": "",
        "maxWeights": "",
        "minVariations": "",
        "maxVariations": "",
        "sellerNations": "",
        "putawayMonth": str(mode_config.get("putawayMonth", "1")),
        "keywords": "",
        "outOfKeywords": "",
        "subCategoriesDtoList[0].code": node_id_path or "",
        "subCategoriesDtoList[0].desc": "",
        # ★ 翻页参数 ★
        "page": str(page_num),
        "size": str(page_size),
    }

    # 添加所有 titles 字段
    for idx, (bsr_id, name) in BSR_CATEGORY_MAP.items():
        data[f"titles[{idx}]"] = name

    # 添加 bsrIds — 只勾选目标类目
    for idx, (bsr_id, name) in BSR_CATEGORY_MAP.items():
        if idx == target_idx:
            data[f"bsrIds[{idx}]"] = bsr_id

    return data


def _strip_html(text):
    """移除 HTML/XML 标签与实体，保留纯文本，防止类目串里混入原始标签。

    例：'<span class="text-primary" > v2 > Arts, Crafts & Sewing'
      → ' v2 > Arts, Crafts & Sewing'
    """
    if not text:
        return text
    text = re.sub(r'<[^>]+>', '', text)          # 去标签
    text = re.sub(r'&nbsp;', ' ', text, flags=re.I)
    text = re.sub(r'&amp;', '&', text, flags=re.I)
    text = re.sub(r'&gt;', '>', text, flags=re.I)
    text = re.sub(r'&lt;', '<', text, flags=re.I)
    text = re.sub(r'&#\d+;', '', text)           # 去数字实体
    return text


def _split_path(raw, chinese_only=False):
    """把 'A > B › C' 这类路径按多种分隔符切分并去噪。"""
    if not raw:
        return []
    raw = _strip_html(raw)                       # 先剥离 HTML，避免混入标签
    parts = re.split(r'\s*[>＞›→·/]\s*', raw)
    seen = set()
    out = []
    for p in parts:
        p = p.strip().strip('>＞›→·/').strip()
        if not p:
            continue
        if chinese_only and not re.search(r'[\u4e00-\u9fff]', p):
            continue
        if p in seen or len(p) > 60 or '编辑' in p:
            continue
        # 过滤接口版本标记 / 无意义短噪声（如 v1、v2、^、~、#…）
        if re.fullmatch(r'[vV]\d{1,2}|[\^~#@!]|\.{2,}', p):
            continue
        seen.add(p)
        out.append(p)
    return out


def extract_category_paths(html, asin):
    """从 ASIN 附近 HTML 抽取 (英文类目路径, 中文类目路径)。多策略容错。

    卖家精灵不同接口/版本的面包屑写法不一，这里尝试：
      1) 标记语：同类目 / 同级类目 / 类目: ...
      2) 链接式面包屑：<a>文本</a> 链
      3) 中文类目名标记 + 链接式中文
    """
    asn_idx = html.find(asin)
    if asn_idx < 0:
        return '', ''
    # 面包屑可能在 ASIN 之前，扩大搜索窗口
    ctx = html[max(0, asn_idx - 3000): asn_idx + 25000]

    # --- 英文类目路径 ---
    en_path = ''
    for pat in [
        r'同类目[：:]\s*(.{10,800}?)(?:</|｜|$)',
        r'同级[类目][：:]\s*(.{10,800}?)(?:</|｜|$)',
        r'(?:类目|分类)[：:]\s*(.{10,800}?)(?:</|｜|$)',
    ]:
        m = re.search(pat, ctx, re.DOTALL)
        if m:
            en_path = m.group(1)
            break
    if not en_path:
        links = re.findall(r'<a[^>]*>([^<>]{1,40})</a>', ctx[:6000])
        cand = [x.strip() for x in links
                if x.strip() and '编辑' not in x and '收藏' not in x and '登录' not in x]
        if len(cand) >= 2:
            en_path = ' > '.join(cand[:5])
    en_cats = _split_path(en_path)

    # --- 中文类目路径 ---
    cn_path = ''
    m_cn = re.search(r'中文类目名?[：:]\s*(.{10,500}?)(?:#\d|重量|体积|LQS|变体数|卖家|$)', ctx, re.DOTALL)
    if m_cn:
        cn_path = m_cn.group(1)
    if not cn_path:
        cn_cands = [x for x in re.findall(r'<a[^>]*>([^<>]{1,40})</a>', ctx[:6000])
                    if re.search(r'[\u4e00-\u9fff]', x)]
        if cn_cands:
            cn_path = ' > '.join([x.strip() for x in cn_cands[:5]])
    cn_cats = _split_path(cn_path, chinese_only=True)

    return ' > '.join(en_cats[:5]), ' > '.join(cn_cats[:5])


def _match_target_subcategory(product):
    """判断产品是否属于目标细分类目（需求 A 过滤）。

    规则：
      1) 一级类目不在 SUB_CATEGORIES 中 → 直接 False（不抓该一级之外的）
      2) 一级类目在配置内 → 取 category_leaf / category_l3 / category_l2 任一
         与目标细分类目英文名（小写）比对，命中即 True
    """
    l1 = (product.get('category') or '').strip()
    if l1 not in SUB_CATEGORIES:
        return False
    target_subs = SUB_CATEGORIES.get(l1, [])
    if not target_subs:
        return True
    for field in ('category_leaf', 'category_l3', 'category_l2'):
        val = (product.get(field) or '').strip().lower()
        if val and val in TARGET_SUBCATEGORY_NAMES:
            return True
    return False


def _assign_fine_category(product):
    """为产品确定「最精确显示用类目名」fine_category（取 breadcrumb 最末端非空层级）。"""
    for field in ('category_leaf', 'category_l3', 'category_l2'):
        val = (product.get(field) or '').strip()
        if val:
            return val
    return product.get('category', '')


def _extract_node_path_map(html):
    """从返回 HTML 提取 {asin: nodeIdPath} 映射。
    卖家精灵按细分类目返回时，每个产品 checkbox 带 data-item-asin + data-nodeIdPath。
    """
    pairs = re.findall(
        r'data-item-asin="([^"]+)"[^>]*data-nodeIdPath="([^"]+)"', html)
    if not pairs:
        pairs = re.findall(
            r'data-nodeIdPath="([^"]+)"[^>]*data-item-asin="([^"]+)"', html)
        pairs = [(b, a) for a, b in pairs]
    return dict(pairs)


def _resolve_fine_category(node_id_path):
    """按 nodeIdPath 前缀匹配目标细分类目，返回 (一级类目, 细分类目名, 层级)。

    例：node_id_path='15684181:15718271:15718541'（Automotive:Car Care:Interior Care）
        目标配置 Car Care='15684181:15718271' → 前缀命中 → 返回 ('Automotive', 'Car Care', 2)
    """
    if not node_id_path:
        return None
    for l1, subs in SUB_CATEGORIES.items():
        for s in subs:
            nid = s.get("node_id_path", "")
            if nid and node_id_path.startswith(nid):
                return l1, s["name"], s["level"]
    return None


def parse_products_from_html(html, category_en):
    """使用 BeautifulSoup 解析产品数据（内置去重）"""
    from bs4 import BeautifulSoup
    products = []
    seen_in_page = set()
    soup = BeautifulSoup(html, 'lxml')

    cards = soup.select('.content-grid-product-box')
    if not cards:
        cards = soup.select('.module-grid-product')

    # 提取产品 nodeIdPath 映射（按细分类目返回时用）
    node_path_map = _extract_node_path_map(html)

    for card in cards:
        asin_el = card.select_one('[data-asin]')
        if not asin_el:
            continue
        asin = asin_el.get('data-asin', '')

        # 页面内去重（HTML 中可能有重复卡片）
        if asin in seen_in_page:
            continue
        seen_in_page.add(asin)

        # 类目面包屑（一级 → 二级 → 细分小类），多策略容错抽取
        category_path, category_cn_path = extract_category_paths(html, asin)
        levels = [c.strip() for c in category_path.split(' > ') if c.strip()]
        category_l1 = levels[0] if len(levels) > 0 else ''
        category_l2 = levels[1] if len(levels) > 1 else ''
        category_l3 = levels[2] if len(levels) > 2 else ''
        category_leaf = levels[-1] if levels else ''
        if not category_l1 and category_en:
            category_l1 = category_en

        levels_cn = [c.strip() for c in category_cn_path.split(' > ') if c.strip()]
        category_cn_l1 = levels_cn[0] if len(levels_cn) > 0 else ''
        category_cn_l2 = levels_cn[1] if len(levels_cn) > 1 else ''
        category_cn_l3 = levels_cn[2] if len(levels_cn) > 2 else ''
        category_cn_leaf = levels_cn[-1] if levels_cn else ''

        title = asin_el.get('data-title', '')
        bsr = asin_el.get('data-bsrrank', '')
        price = asin_el.get('data-price', '')
        rating = asin_el.get('data-rating', '')
        reviews = asin_el.get('data-reviews', '')
        img_url = asin_el.get('data-imgurl', '')

        brand = ''
        seller = ''
        brand_link = card.select_one('a[href*="/stores/"]')
        if brand_link:
            seller = brand_link.get_text().strip()
            brand = seller
        if not brand:
            idx = html.find(asin)
            context = html[idx:idx+5000]
            brands = re.findall(r'class="text-truncate[^"]*"[^>]*>\s*([^<\n]{2,50})', context)
            for b in brands:
                b_clean = b.strip()
                if b_clean and 'BSR' not in b_clean and '销量' not in b_clean and '变体' not in b_clean and not b_clean.startswith('$'):
                    brand = b_clean
                    seller = b_clean
                    break

        sales = ''
        sales_el = card.select_one('.module-grid-product-sales, [class*="sales"]')
        if sales_el:
            sales_text = sales_el.get_text()
            sales_m = re.search(r'销量:\s*([\d,]+)', sales_text, re.DOTALL)
            if sales_m:
                sales = sales_m.group(1).replace(',', '')
        else:
            card_text = card.get_text()
            sales_m = re.search(r'销量:\s*([\d,]+)', card_text, re.DOTALL)
            if sales_m:
                sales = sales_m.group(1).replace(',', '')

        variants = ''
        card_text = card.get_text()
        variant_m = re.search(r'变体数[：:]\s*(\d+|无)', card_text)
        if variant_m:
            variants = variant_m.group(1)

        available = asin_el.get('data-available', '')
        if available:
            try:
                dt = datetime.strptime(available, '%a %b %d %H:%M:%S %Z %Y')
                available = dt.strftime('%Y-%m-%d')
            except:
                pass

        monthly_sales = ''
        try:
            sales_num = int(sales) if sales else 0
            price_num = float(price) if price else 0
            if sales_num > 0 and price_num > 0:
                monthly_sales = f"{sales_num * price_num:,.0f}"
        except (ValueError, TypeError):
            pass

        # 按 nodeIdPath 反查目标细分类目（细分类目抓取模式下产品自带路径）
        node_path = node_path_map.get(asin, '')
        resolved = _resolve_fine_category(node_path)
        if resolved:
            fine_l1, fine_cat, fine_lv = resolved
            category_l1 = fine_l1
            # 用命中的细分类目名作为最精确显示类目
            category_leaf = fine_cat
        elif not category_l1:
            category_l1 = category_en

        products.append({
            'category': category_en,
            'category_l1': category_l1,
            'category_l2': category_l2,
            'category_l3': category_l3,
            'category_leaf': category_leaf,
            'category_path': category_path,
            'category_cn_l1': category_cn_l1,
            'category_cn_l2': category_cn_l2,
            'category_cn_l3': category_cn_l3,
            'category_cn_leaf': category_cn_leaf,
            'category_cn_path': category_cn_path,
            'node_id_path': node_path,
            'fine_category': resolved[1] if resolved else _assign_fine_category(
                {'category': category_en, 'category_leaf': category_leaf,
                 'category_l3': category_l3, 'category_l2': category_l2}),
            'asin': asin,
            'title': title.replace('&amp;', '&').replace('&quot;', '"'),
            'brand': brand,
            'image': img_url,
            'bsr': bsr,
            'sales': sales,
            'price': price,
            'monthly_sales': monthly_sales,
            'rating': rating,
            'reviews': reviews,
            'variants': variants,
            'available': available,
            'seller': seller,
        })

    return products


def fetch_products_page(category_en, collect_type, session, page_num, page_size=60, node_id_path=None):
    """
    通过 POST 获取指定页的产品数据
    使用 requests.Session 管理 cookie（包括服务器返回的 JSESSIONID）
    node_id_path: 细分类目 nodeIdPath，传入则按最小细分类目抓取
    """
    mode_config = COLLECT_MODES.get(collect_type, COLLECT_MODES['new'])
    data = build_request_data(category_en, mode_config, page_num, page_size,
                              node_id_path=node_id_path)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': 'https://www.sellersprite.com/v2/product-research',
        'Origin': 'https://www.sellersprite.com',
    }

    try:
        resp = session.post(API_URL, data=data, headers=headers, timeout=30, allow_redirects=False)

        if resp.status_code in (302, 401, 403):
            log(f"    [WARN] 请求被拒 (HTTP {resp.status_code})")
            return None

        if 'login' in resp.headers.get('Location', '').lower():
            log(f"    [WARN] Cookie 已失效，需要重新登录")
            return None

        html = resp.text

        # 调试：把真实返回的 HTML 落盘，便于按卖家精灵实际结构修正类目面包屑正则
        # 触发方式二选一：环境变量 DT_DEBUG_HTML=1，或在 output 目录放 .debug_html 标志文件
        _dbg_flag = os.environ.get('DT_DEBUG_HTML') or (Path(OUTPUT_DIR) / '.debug_html').exists()
        if _dbg_flag and page_num == 1:
            try:
                dbg = Path(OUTPUT_DIR) / f"debug_html_{category_en}_{collect_type}.html"
                dbg.write_text(html, encoding='utf-8', errors='replace')
                log(f"    [DEBUG] 原始 HTML 已保存: {dbg}")
            except Exception:
                pass

        if 'HTTP状态 404' in html or '登录' in html[:1000]:
            log(f"    [WARN] 返回非产品页面")
            return None

        products = parse_products_from_html(html, category_en)
        return products

    except Exception as e:
        log(f"    [ERROR] POST 请求失败: {e}")
        return None


def _collect_category(session, cat_en, collect_type, max_pages, node_id_path=None, label=""):
    """抓取单个类目（或单个细分类目），返回产品列表。"""
    all_products = []
    seen_asins = set()
    consecutive_empty = 0
    for page_num in range(1, max_pages + 1):
        log(f"  第 {page_num} 页 [POST page={page_num}]...")
        products = fetch_products_page(cat_en, collect_type, session, page_num,
                                       node_id_path=node_id_path)
        if products is None:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                log(f"    [STOP] 连续 {consecutive_empty} 页失败")
                break
            continue
        if not products:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                log(f"    [STOP] 连续 {consecutive_empty} 页无数据")
                break
            continue
        consecutive_empty = 0
        new_count = 0
        for p in products:
            asin = p.get('asin', '')
            if asin and asin not in seen_asins:
                seen_asins.add(asin)
                p['collect_type'] = collect_type
                p['crawled_at'] = datetime.now().isoformat()
                all_products.append(p)
                new_count += 1
        dup_count = len(products) - new_count
        log(f"    [OK] 本页 {len(products)} 条 → 新增 {new_count} 条" +
            (f"，跳过 {dup_count} 条重复" if dup_count > 0 else ""))
        if new_count == 0:
            log(f"    [STOP] 无新产品，翻页结束")
            break
        if len(products) < 60:
            log(f"    [INFO] 本页不足 60 条，已到最后一页")
            break
    return all_products


def run(collect_type="new", max_pages=20, only_categories=None, subcat_mode=True):
    """主流程 - POST + page 参数翻页，突破 60 产品限制。

    subcat_mode=True（默认）: 逐一最小细分类目抓取。
      遍历 SUB_CATEGORIES 中每个目标细分类目，用 nodeIdPath 让卖家精灵后端
      直接按该细分类目过滤返回产品（产品自带 node_id_path 与 fine_category）。
    subcat_mode=False: 按一级类目抓取后本地过滤（旧模式）。
    """
    log(f"开始采集 - 类型: {collect_type}")
    log(f"细分类目模式: {'逐一最小细分类目抓取' if subcat_mode else '一级类目+本地过滤'}")
    log(f"目标类目: {only_categories or CATEGORIES}")
    log(f"最大翻页数: {max_pages}（每页最多 60 个产品）")

    if not COOKIES_PATH.exists():
        log(f"[ERROR] Cookie 文件不存在: {COOKIES_PATH}")
        return None

    cookies = json.loads(COOKIES_PATH.read_text())
    results = {}

    if subcat_mode:
        # ===== 逐一最小细分类目抓取 =====
        # 统计需要抓取的细分类目（支持按一级类目过滤）
        subcats = []
        for l1, subs in SUB_CATEGORIES.items():
            if only_categories and l1 not in only_categories:
                continue
            for s in subs:
                subcats.append((l1, s))
        log(f"待抓细分类目: {len(subcats)} 个")

        for cat_en, sub in subcats:
            nid = sub.get("node_id_path", "")
            sub_name = sub["name"]
            lv = sub.get("level", 2)
            log(f"\n{'='*50}")
            log(f"[细分类目] {cat_en} → L{lv} {sub_name} (nodeIdPath={nid})")
            if not nid:
                log("    [SKIP] 无 node_id_path 配置")
                continue
            session = requests.Session()
            for c in cookies:
                session.cookies.set(c['name'], c['value'], domain=c.get('domain', '.sellersprite.com'))
            prods = _collect_category(session, cat_en, collect_type, max_pages, node_id_path=nid)
            # 强制给产品打上细分类目标记（防解析遗漏）
            for p in prods:
                if not p.get('fine_category'):
                    p['fine_category'] = sub_name
                p['_subcat_l1'] = cat_en
                p['_subcat_name'] = sub_name
                p['_subcat_level'] = lv
            key = f"{cat_en} > {sub_name}"
            results[key] = prods
            log(f"  ✅ {sub_name}: 共 {len(prods)} 条")
    else:
        # ===== 旧模式：一级类目 + 本地过滤 =====
        categories = only_categories or CATEGORIES
        for cat_en in categories:
            log(f"\n{'='*50}")
            log(f"[类目] {cat_en}")
            session = requests.Session()
            for c in cookies:
                session.cookies.set(c['name'], c['value'], domain=c.get('domain', '.sellersprite.com'))
            all_products = _collect_category(session, cat_en, collect_type, max_pages)
            results[cat_en] = all_products
            log(f"  ✅ {cat_en}: 共 {len(all_products)} 条")

        # 细分类目过滤（旧模式保留）
        if TARGET_SUBCATEGORY_NAMES:
            before_total = sum(len(v) for v in results.values())
            for cat_en in list(results.keys()):
                products = results[cat_en]
                filtered = [p for p in products if _match_target_subcategory(p)]
                for p in filtered:
                    p['fine_category'] = _assign_fine_category(p)
                removed = len(products) - len(filtered)
                if removed:
                    log(f"  [细分类目过滤] {cat_en}: 移除 {removed} 条非目标细分，保留 {len(filtered)} 条")
                results[cat_en] = filtered
            after_total = sum(len(v) for v in results.values())
            log(f"📋 细分类目过滤：{before_total} → {after_total} 条（移除 {before_total - after_total} 条）")
        else:
            for cat_en in results:
                for p in results[cat_en]:
                    p['fine_category'] = _assign_fine_category(p)

    # 保存
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"raw_data_{collect_type}_{ts}.json"
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))

    log(f"\n{'='*50}")
    log(f"✅ 原始数据已保存: {output_path}")
    total = sum(len(v) for v in results.values())
    log(f"📊 总条数: {total}")
    for cat_en, products in results.items():
        log(f"  {cat_en}: {len(products)} 条")
    return output_path


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--type', '-t', choices=['new', 'hot'], default='new')
    parser.add_argument('--max-pages', '-p', type=int, default=20)
    parser.add_argument('--categories', '-c', nargs='*')
    parser.add_argument('--legacy', action='store_true', help='使用旧模式（一级类目+本地过滤）')
    args = parser.parse_args()

    run(
        collect_type=args.type,
        max_pages=args.max_pages,
        only_categories=args.categories,
        subcat_mode=not args.legacy,
    )
