"""
DURATECH 卖家精灵自动化采集 - 筛选规则引擎
"""
import re
from datetime import datetime, timedelta
from config import (
    BLACKLIST_KEYWORDS, MIN_RATING, MIN_REVIEWS,
    NEW_PRODUCT, HOT_PRODUCT, RISK_CONTROL,
    NO_BRAND_KEYWORDS,
)


class FilterEngine:
    def __init__(self):
        self.blacklist_re = re.compile(
            '|'.join(re.escape(kw) for kw in BLACKLIST_KEYWORDS),
            re.IGNORECASE
        )
        self.nobrand_re = re.compile(
            '|'.join(re.escape(kw) for kw in NO_BRAND_KEYWORDS),
            re.IGNORECASE
        )

    # ---- 辅助方法 ----

    def _safe_float(self, val, default=0.0):
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def _safe_int(self, val, default=0):
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default

    def _get_text(self, product, *keys):
        for k in keys:
            v = product.get(k, '')
            if v:
                return str(v).strip()
        return ''

    # ---- 黑名单检查 ----

    def is_blacklisted(self, product):
        title = self._get_text(product, 'Item Name(标题)', '标题', 'Item Name')
        brand = self._get_text(product, '品牌')
        category = self._get_text(product, '产品类目')
        combined = f"{title} {brand} {category}"
        return bool(self.blacklist_re.search(combined))

    # ---- 基础过滤 ----

    def has_sufficient_rating(self, product):
        return self._safe_float(product.get('评分', 0)) >= MIN_RATING

    def has_sufficient_reviews(self, product):
        return self._safe_int(product.get('评论数', 0)) >= MIN_REVIEWS

    def is_branded(self, product):
        brand = self._get_text(product, '品牌').lower()
        seller = self._get_text(product, '卖家信息').lower()
        if self.nobrand_re.search(brand) or self.nobrand_re.search(seller):
            return False
        return True

    def has_review_spike(self, product):
        recent = self._safe_int(product.get('7天新增评论', 0))
        total = self._safe_int(product.get('评论数', 1))
        if total > 0 and recent / total > RISK_CONTROL['max_review_spike_ratio']:
            return True
        return False

    def basic_filter(self, product):
        """前置统一过滤，返回 (通过, 原因)"""
        if self.is_blacklisted(product):
            return False, "黑名单"
        if not self.has_sufficient_rating(product):
            return False, "评分不足"
        if not self.has_sufficient_reviews(product):
            return False, "评论数不足"
        if not self.is_branded(product):
            return False, "无品牌/杂货铺"
        if self.has_review_spike(product):
            return False, "评价暴增可疑"
        return True, "通过"

    # ---- 风控检查 ----

    def risk_check(self, product):
        """风控检查，返回 True 表示通过"""
        daily_new = self._safe_int(product.get('单日新增评论', 0))
        if daily_new > RISK_CONTROL['max_daily_new_reviews']:
            return False

        price_vol = self._safe_float(product.get('价格波动率', 0))
        if price_vol > RISK_CONTROL['max_price_volatility']:
            return False

        return True

    # ---- 新品筛选 ----

    def filter_new_products(self, products):
        results = []
        for p in products:
            passed, _ = self.basic_filter(p)
            if not passed:
                continue

            days_listed = self._safe_int(p.get('上架天数', 999))
            if days_listed > NEW_PRODUCT['max_days_listed']:
                continue

            daily_sales = self._safe_float(p.get('日均销量', 0))
            if daily_sales <= NEW_PRODUCT['min_daily_sales']:
                continue

            variations = self._safe_int(p.get('变体数', 99))
            if variations > NEW_PRODUCT['max_variations']:
                continue

            bsr = self._safe_int(p.get('BSR排名', 99999))
            if bsr > NEW_PRODUCT['max_bsr_rank']:
                continue

            weekly_reviews = self._safe_int(p.get('7天新增评论', 0))
            if weekly_reviews < NEW_PRODUCT['min_weekly_new_reviews']:
                continue

            if not self.risk_check(p):
                continue

            p['标签'] = NEW_PRODUCT['label']
            results.append(p)

        return results

    # ---- 爆品筛选 ----

    def filter_hot_products(self, products):
        results = []
        for p in products:
            passed, _ = self.basic_filter(p)
            if not passed:
                continue

            monthly_sales = self._safe_int(p.get('月预估销量', 0))
            if monthly_sales <= HOT_PRODUCT['min_monthly_sales']:
                continue

            days_listed = self._safe_int(p.get('上架天数', 0))
            if days_listed < HOT_PRODUCT['min_days_listed']:
                continue

            outofstock = self._safe_int(p.get('断货天数', 0))
            if outofstock >= HOT_PRODUCT['max_outofstock_days']:
                continue

            if not self.risk_check(p):
                continue

            if monthly_sales >= HOT_PRODUCT['head_min']:
                p['标签'] = HOT_PRODUCT['label_head']
            else:
                p['标签'] = HOT_PRODUCT['label_standard']

            results.append(p)

        return results

    # ---- 去重 ----

    def deduplicate(self, products, key='asin'):
        """按指定字段去重，保留首次出现的记录"""
        seen = {}
        for p in products:
            val = p.get(key, '')
            if val and val not in seen:
                seen[val] = p
        return list(seen.values())
