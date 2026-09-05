"""
DURATECH 卖家精灵「查竞品工具」单 ASIN 数据获取
入口：/v2/competitor-lookup/monthly?...&textareaValue=ASIN&competing=true
返回产品行各指标卡（均为 <button class="btn btn-white pop-ele" data-asin=...>），解析自真实页面结构：
  - 基础字段（title/price/bsr/rating/reviews/available/img）取任一完整卡 data-* 属性
  - 近30天销量卡    pop-type="sales" + <span class="text-primary">816</span>      + div.text-muted 环比(-10%)
  - 月销售额卡      pop-type="sales" + 文本 "$8,152"（无 text-primary span）       + div.text-muted 环比(-10%)
  - BSR 变化卡      button[data-bsrrank] 内 <span>11,114</span> + text-danger -766 / -7%
  - 月度销量趋势    div.morris-table-inline[data-y] = [{x:202401,y:28},...]
用于：
  - 任务2：批量更新追踪看板产品最新销量/月销额/售价/BSR 并标注变化
  - 任务3：手动输入 ASIN 加入追踪看板
"""
import json
import re
import sys
import requests
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from config import SESSIONS_DIR, SUB_CATEGORIES

COOKIES_PATH = Path(SESSIONS_DIR) / "cookies.json"
BASE_MONTHLY = "https://www.sellersprite.com/v2/competitor-lookup/monthly"


def _build_category_node_map():
    """从 config.SUB_CATEGORIES 构建「一级类目 nodeId 首段 -> 四大类名」映射。

    SUB_CATEGORIES 结构：{大类名: [{name, cn, level, node_id_path, ...}, ...]}
    node_id_path 首段即卖家精灵一级类目 nodeId（如 15684181=Automotive）。
    """
    m = {}
    for l1, subs in (SUB_CATEGORIES or {}).items():
        for s in subs:
            path = (s.get("node_id_path") or "").strip()
            if path:
                m[path.split(":")[0]] = l1
    return m


# 一级类目 nodeId 首段 -> 四大类名
CATEGORY_NODE_MAP = _build_category_node_map()

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': 'https://www.sellersprite.com/v2/competitor-lookup',
}


def _session():
    if not COOKIES_PATH.exists():
        raise RuntimeError(f"Cookie 文件不存在: {COOKIES_PATH}")
    cookies = json.loads(COOKIES_PATH.read_text(encoding="utf-8"))
    s = requests.Session()
    for c in cookies:
        s.cookies.set(c['name'], c['value'],
                      domain=c.get('domain', '.sellersprite.com'))
    return s


def _clean_num(text):
    """' 11,114 ' / '$8,152' / '1.2万' -> '11114'/'8152'/'12000'；失败返回 ''"""
    if not text:
        return ''
    t = text.strip().replace(',', '').replace('$', '').replace('￥', '')
    if not t:
        return ''
    m = re.search(r'(-?[\d.]+)\s*([万亿WwKk]?)', t)
    if not m:
        return ''
    v = float(m.group(1))
    unit = m.group(2)
    if unit == '万' or unit == 'w' or unit == 'W':
        v *= 10000
    elif unit == '亿':
        v *= 100000000
    elif unit.lower() == 'k':
        v *= 1000
    if v == int(v):
        return str(int(v))
    return str(v)


def _fmt_num(num):
    """int/float -> 千分位字符串；None/'' -> ''"""
    if num in (None, ''):
        return ''
    try:
        f = float(num)
    except (ValueError, TypeError):
        return str(num)
    if f == int(f):
        return f"{int(f):,}"
    return f"{f:,.2f}"


def _parse_detail(html, asin):
    """从查竞品页面 HTML 提取产品各指标。返回 dict；失败字段为空。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'lxml')
    asin_key = asin.upper()

    # ---- 1) 基础字段：任一与目标 ASIN 完全一致的完整指标卡（pop-ele 且带 data-title）----
    # 注意：页面可能同时包含其它产品的行（例如粘贴多 ASIN），因此必须精确匹配 data-asin，
    # 绝不能兜底取「任意产品」，否则无效 ASIN 会被错配成无关产品。
    base = {}
    for el in soup.select('button.pop-ele[data-asin]'):
        if el.get('data-asin', '').upper() == asin_key and el.get('data-title'):
            base = {
                'title': el.get('data-title', '').strip(),
                'image': el.get('data-imgurl', ''),
                'price': _clean_num(el.get('data-price', '')),
                'bsr': _clean_num(el.get('data-bsrrank', '')),
                'rating': el.get('data-rating', ''),
                'reviews': _clean_num(el.get('data-reviews', '')),
                'available': el.get('data-available', ''),
            }
            break
    if not base:
        return None
    # available: "Mon Jan 08 09:10:00 CST 2024" -> "2024-01-08"
    try:
        dt = datetime.strptime(base['available'], '%a %b %d %H:%M:%S %Z %Y')
        base['available'] = dt.strftime('%Y-%m-%d')
    except Exception:
        pass

    # ---- 2) 近30天销量卡 + 月销售额卡（pop-type="sales"）----
    sales, monthly = '', ''
    sales_pct, monthly_pct = '', ''
    for btn in soup.select('button.pop-ele[pop-type="sales"][data-asin]'):
        if btn.get('data-asin', '').upper() != asin.upper():
            continue
        sp = btn.select_one('span.text-primary')
        pct = (btn.select_one('div.text-muted').get_text(strip=True)
               if btn.select_one('div.text-muted') else '')
        raw = btn.get_text(' ', strip=True)
        if sp is not None:
            # 无 $ 的销量卡：<span class="text-primary">816</span> / -10%
            sales = _clean_num(sp.get_text(strip=True))
            sales_pct = _clean_num(pct)
        elif raw.startswith('$') or '￥' in raw:
            # 月销售额卡：文本 "$8,152" / -10%
            monthly = _clean_num(raw.split()[0] if raw else raw)
            monthly_pct = _clean_num(pct)
    # 兜底：月销额 = 销量 × 单价（页面偶缺失金额卡时）
    if not monthly and sales and base.get('price'):
        try:
            monthly = str(int(float(sales) * float(base['price'])))
        except (ValueError, TypeError):
            pass

    # ---- 2.5) 售价变化（价格卡 text-muted：多数为 '-'，有折扣/调价时显示 ±%）----
    price_pct = ''
    for btn in soup.select('button.pop-ele[data-asin][pop-type="history"]'):
        if btn.get('data-asin', '').upper() != asin.upper():
            continue
        inner = btn.get_text(' ', strip=True)
        if '$' not in inner and '￥' not in inner:
            continue  # 非价格卡（价格卡文本形如 $9.99 + text-muted）
        mm = btn.select_one('div.text-muted')
        if mm:
            v = mm.get_text(strip=True).replace('%', '').strip()
            if v and v not in ('-', '--', 'None'):
                price_pct = v
        break

    # ---- 3) BSR 变化卡：button[data-bsrrank] 内 <span>11114</span> + text-danger 变化 -766 / -7% ----
    bsr_delta, bsr_pct = '', ''
    for btn in soup.select('button.pop-ele[data-bsrrank]'):
        if btn.get('data-asin', '').upper() != asin.upper():
            continue
        danger = [d.get_text(strip=True) for d in btn.select('div.text-muted span.text-danger')]
        if danger:
            # danger[0] 为含 iconfont 的变化数值 span，取其数字部分
            joined = ' '.join(danger)
            nums = re.findall(r'([+-]?[\d.]+%?)', joined)
            if len(nums) >= 2:
                bsr_delta = _clean_num(nums[0])
                bsr_pct = _clean_num(nums[1])
            break

    # ---- 4) 月度销量趋势 data-y：[{x:202401,y:28}, ...] ----
    trend = []
    y_el = soup.select_one('div.morris-table-inline[data-y]')
    if y_el:
        raw = re.sub(r"[\s']+", '', y_el.get('data-y') or '')
        try:
            trend = [{'x': x, 'y': int(float(y))}
                     for x, y in re.findall(r'\{x:(\d{6}),y:([\d.]+)\}', raw)]
        except Exception:
            pass

    # ---- 5) 类目路径 nodeIdPath -> 四大类 ----
    # 查竞品列表 checkbox 带 data-item-asin + data-nodeIdPath（如 15684181:15718271）
    category = ''
    _ak = re.escape(asin.upper())
    m = re.search(r'data-item-asin="' + _ak + r'"[^>]*data-nodeIdPath="([^"]+)"', html)
    if not m:
        m = re.search(r'data-nodeIdPath="([^"]+)"[^>]*data-item-asin="' + _ak + r'"', html)
    if m:
        first = m.group(1).split(':')[0]
        category = CATEGORY_NODE_MAP.get(first, '')

    # ---- 6) 变体数：产品行 tr.bg-white 文本（用 offer-listing/{ASIN} 链接定位目标行） ----
    # 查竞品产品详情行含「变体数: 无 / N」，data-* 属性不含该字段
    variants = ''
    for tr in soup.select('tr.bg-white'):
        if re.search(r'offer-listing/' + _ak, str(tr), re.I):
            vm = re.search(r'变体数\s*[:：]\s*(\d+|无)', tr.get_text())
            if vm:
                variants = vm.group(1)
            break

    return {
        'asin': asin.upper(),
        'title': base['title'],
        'brand': '',                      # 品牌页面未单列，保留空（调用方可回填）
        'image': base['image'],
        'price': base['price'],
        'price_pct': price_pct,           # 售价变化（价格卡 text-muted；'-' 表示无变化 -> 空）
        'bsr': base['bsr'],
        'sales': sales,
        'sales_pct': sales_pct,           # 近30天销量环比 %
        'monthly_sales': monthly,
        'monthly_pct': monthly_pct,       # 月销售额环比 %
        'bsr_delta': bsr_delta,           # BSR 较上月变化量
        'bsr_pct': bsr_pct,               # BSR 较上月变化 %
        'rating': base['rating'],
        'reviews': base['reviews'],
        'variants': variants,             # 变体数（'无'/'N'/''）
        'category': category,             # 四大类之一；非四大类/未识别 -> ''
        'available': base['available'],
        'trend': trend,
    }


def fetch_product(asin, market_id='1', month='bsr_sales_nearly', with_variants=True):
    """抓取单个 ASIN 查竞品数据。

    返回 dict（含 asin/title/price/bsr/sales/sales_pct/monthly_sales/
    monthly_pct/bsr_delta/bsr_pct/rating/reviews/category/variants/available/trend）。
    失败返回 {'error': ..., 'status': ...}；ASIN 不存在返回 {'error': 'NOT_FOUND'}。
    """
    params = {
        'marketId': market_id, 'nodeIdPath': '', 'order.field': 'total_units',
        'order.desc': 'true', 'symbol': '', 'token': '', 'station': 'US',
        'competing': 'true', 'type': 'monthly', 'monthName': month,
        'keywords': '', 'brand0': '', 'sellerName': '',
        'textareaValue': asin,
    }
    s = _session()
    try:
        resp = s.get(BASE_MONTHLY, params=params, headers=HEADERS,
                     timeout=30, allow_redirects=False)
    except requests.RequestException as e:
        return {'error': f'网络请求失败: {e}', 'status': 0}
    if resp.status_code in (302, 401, 403):
        return {'error': 'Cookie 失效或未登录', 'status': resp.status_code}
    if 'login' in (resp.headers.get('Location', '') or '').lower():
        return {'error': 'Cookie 已失效，请重新上传', 'status': 401}
    html = resp.text
    if len(html) < 5000:
        return {'error': '返回非产品页面', 'status': 200}

    detail = _parse_detail(html, asin)
    if detail is None:
        if '验证码' in html or '人机验证' in html:
            return {'error': '可能触发人机验证，请稍后重试', 'status': 200}
        return {'error': f'未在查竞品结果中找到 ASIN {asin}', 'status': 200}
    return detail


def fetch_products_batch(asins, **kw):
    """批量抓取多个 ASIN。返回 (success_dict, errors_list)。"""
    out, errors = {}, []
    for a in asins:
        try:
            r = fetch_product(a, **kw)
            if r and 'error' in r:
                errors.append({'asin': a, 'error': r['error']})
            elif r:
                out[a.upper()] = r
        except Exception as e:
            errors.append({'asin': a, 'error': str(e)})
    return out, errors


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='查竞品工具获取单 ASIN 产品信息')
    parser.add_argument('asins', nargs='+', help='一个或多个 ASIN')
    args = parser.parse_args()
    prods, errs = fetch_products_batch(args.asins)
    for a, p in prods.items():
        print(f"=== {a} ===")
        for k in ('title', 'price', 'bsr', 'sales', 'sales_pct',
                  'monthly_sales', 'monthly_pct', 'bsr_delta', 'bsr_pct',
                  'rating', 'reviews', 'available', 'trend'):
            v = p.get(k, '')
            if k == 'trend':
                print(f"  trend: {len(v)} 个月 | 尾部 {v[-3:] if v else ''}")
            else:
                print(f"  {k}: {v}")
    if errs:
        print("\n错误:", errs)
