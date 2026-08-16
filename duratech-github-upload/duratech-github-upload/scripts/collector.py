"""
DURATECH 卖家精灵选品数据采集器 (HTTP POST API + page 翻页)
通过卖家精灵 v2 POST 接口获取数据，支持翻页突破 60 产品限制
关键发现：翻页只需在 POST 数据中添加 page=N&size=60 参数
"""
import json
import sys
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
)

COOKIES_PATH = Path(SESSIONS_DIR) / "cookies.json"


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def build_request_data(category_en, mode_config, page_num=1, page_size=60):
    """
    构造 POST 请求数据
    翻页关键：添加 page=N&size=60 参数
    """
    target_idx = CATEGORY_BSR_INDEX[category_en]

    data = {
        "marketId": "1",
        "nodeIdPath": "",
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
        "subCategoriesDtoList[0].code": "",
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


def parse_products_from_html(html, category_en):
    """使用 BeautifulSoup 解析产品数据（内置去重）"""
    from bs4 import BeautifulSoup
    products = []
    seen_in_page = set()
    soup = BeautifulSoup(html, 'lxml')

    cards = soup.select('.content-grid-product-box')
    if not cards:
        cards = soup.select('.module-grid-product')

    for card in cards:
        asin_el = card.select_one('[data-asin]')
        if not asin_el:
            continue
        asin = asin_el.get('data-asin', '')
        
        # 页面内去重（HTML 中可能有重复卡片）
        if asin in seen_in_page:
            continue
        seen_in_page.add(asin)

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

        products.append({
            'category': category_en,
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


def fetch_products_page(category_en, collect_type, session, page_num, page_size=60):
    """
    通过 POST 获取指定页的产品数据
    使用 requests.Session 管理 cookie（包括服务器返回的 JSESSIONID）
    """
    mode_config = COLLECT_MODES.get(collect_type, COLLECT_MODES['new'])
    data = build_request_data(category_en, mode_config, page_num, page_size)

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

        if 'HTTP状态 404' in html or '登录' in html[:1000]:
            log(f"    [WARN] 返回非产品页面")
            return None

        products = parse_products_from_html(html, category_en)
        return products

    except Exception as e:
        log(f"    [ERROR] POST 请求失败: {e}")
        return None


def run(collect_type="new", max_pages=20, only_categories=None):
    """主流程 - POST + page 参数翻页，突破 60 产品限制"""
    log(f"开始采集 - 类型: {collect_type}")
    log(f"目标类目: {only_categories or CATEGORIES}")
    log(f"最大翻页数: {max_pages}（每页最多 60 个产品）")

    if not COOKIES_PATH.exists():
        log(f"[ERROR] Cookie 文件不存在: {COOKIES_PATH}")
        return None

    cookies = json.loads(COOKIES_PATH.read_text())
    categories = only_categories or CATEGORIES
    results = {}

    for cat_en in categories:
        log(f"\n{'='*50}")
        log(f"[类目] {cat_en}")
        all_products = []
        seen_asins = set()
        consecutive_empty = 0

        # 使用 Session 保持 JSESSIONID
        session = requests.Session()
        for c in cookies:
            session.cookies.set(c['name'], c['value'], domain=c.get('domain', '.sellersprite.com'))

        for page_num in range(1, max_pages + 1):
            log(f"  第 {page_num} 页 [POST page={page_num}]...")

            products = fetch_products_page(cat_en, collect_type, session, page_num)

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

            # ASIN 跨页去重
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

            # 新增为 0 → 无新数据
            if new_count == 0:
                log(f"    [STOP] 无新产品，翻页结束")
                break

            # 本页不足 60 → 最后一页
            if len(products) < 60:
                log(f"    [INFO] 本页不足 60 条，已到最后一页")
                break

        results[cat_en] = all_products
        log(f"  ✅ {cat_en}: 共 {len(all_products)} 条（跨越 {page_num} 页）")

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
    args = parser.parse_args()

    run(
        collect_type=args.type,
        max_pages=args.max_pages,
        only_categories=args.categories,
    )
