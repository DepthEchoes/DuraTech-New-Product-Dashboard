"""
DURATECH HTML 筛选页面生成器
生成含图片、勾选框、导出 Excel 功能的交互式 HTML
"""
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from config import (
    CATEGORIES, CATEGORY_SHORT_NAMES, EXPORT_FIELDS, WORKSPACE_OUTPUT,
    COLLECT_MODES, HOT_PRODUCT,
)


def translate_title(title):
    if not title:
        return ""
    terms = [
        ("Car Windshield Sunshade", "汽车挡风玻璃遮阳罩"),
        ("Windshield Sun Shade", "挡风玻璃遮阳板"),
        ("Windshield Sunshade", "挡风玻璃遮阳罩"),
        ("Tire Inflator", "轮胎充气器"),
        ("Portable Air Compressor", "便携式空气压缩机"),
        ("Air Compressor", "空气压缩机"),
        ("Car Mount", "车载支架"),
        ("Magsafe Car Mount", "磁吸车载支架"),
        ("Magnetic Phone Holder", "磁性手机支架"),
        ("Phone Holder", "手机支架"),
        ("Phone Holders", "手机支架"),
        ("Cabin Air Filter", "空调滤清器"),
        ("Air Filter", "空气过滤器"),
        ("Jump Starter", "应急启动电源"),
        ("Portable Lithium Jump Starter", "便携式锂电池应急启动电源"),
        ("Car Accessories", "汽车配件"),
        ("Automotive Sun Screen", "汽车遮阳帘"),
        ("Acrylic Paint", "丙烯颜料"),
        ("Acrylic Paint Markers", "丙烯颜料笔"),
        ("Paint Marker", "油漆笔"),
        ("Paint Pens", "油漆笔"),
        ("Flat Back Crystal Rhinestones", "平底水晶钻石"),
        ("Flat Back", "平底"),
        ("Rhinestones", "水钻"),
        ("Crystal Rhinestones", "水晶钻石"),
        ("Essential Oils", "精油"),
        ("Tea Tree Oil", "茶树精油"),
        ("Flying Insect Trap", "飞虫捕捉器"),
        ("Insect Trap", "昆虫捕捉器"),
        ("Ant Killer", "蚂蚁药"),
        ("Ant Killer Bait Stations", "蚂蚁诱饵站"),
        ("Water Filter", "滤水器"),
        ("Standard Water Filter", "标准滤水器"),
        ("Replacement Water Filter", "替换滤水器"),
        ("Painter's Tape", "美纹纸胶带"),
        ("Spray Paint", "喷漆"),
        ("Cordless", "无绳"),
        ("Rechargeable", "可充电"),
        ("Waterproof", "防水"),
        ("Stainless Steel", "不锈钢"),
        ("Aluminum", "铝"),
        ("Copper", "铜"),
        ("Professional", "专业级"),
        ("Heavy Duty", "重型"),
        ("Premium", "优质"),
        ("Ultra", "超"),
        ("Blocks UV Rays", "阻挡紫外线"),
        ("Keeps Interior Cool", "保持车内凉爽"),
        ("Blocks 99% Heat", "阻挡99%热量"),
        ("Universal Fit", "通用适配"),
        ("for Car", "汽车用"),
        ("for Cars", "汽车用"),
        ("for Trucks", "卡车用"),
        ("for SUVs", "SUV用"),
        ("for Toyota", "丰田"),
        ("for Honda", "本田"),
        ("for iPhone", "苹果手机"),
        ("for Men", "男士"),
        ("for Women", "女士"),
        ("Set", "套装"),
        ("Kit", "套件"),
        ("with", "带"),
        ("and", "和"),
    ]
    result = title
    for en, cn in terms:
        result = result.replace(en, cn)
    if result == title:
        result = f"[{title[:50]}]"
    return result


def assign_labels(products, collect_type):
    for p in products:
        if collect_type == "new":
            p['__label__'] = '潜力新品'
        else:
            sales = int(p.get('sales', 0)) if str(p.get('sales', '')).isdigit() else 0
            if sales >= HOT_PRODUCT['head_min']:
                p['__label__'] = '头部爆品'
            elif sales >= HOT_PRODUCT['standard_min']:
                p['__label__'] = '标准爆品'
            else:
                p['__label__'] = '爆品'
    return products


def build_html(json_path, collect_type, output_path=None, export_port=58900):
    """生成 HTML 筛选页面"""
    raw = json.loads(Path(json_path).read_text())
    mode = COLLECT_MODES.get(collect_type, COLLECT_MODES['new'])
    prefix = mode['output_prefix']
    date_str = datetime.now().strftime("%Y-%m-%d")

    if output_path is None:
        output_path = Path(WORKSPACE_OUTPUT) / f"{prefix}_{date_str}.html"

    # 整理数据（含去重）
    all_products = []
    seen_asins = set()
    for cat_en in CATEGORIES:
        products = raw.get(cat_en, [])
        products = assign_labels(products, collect_type)
        for p in products:
            asin = p.get('asin', '')
            if asin and asin in seen_asins:
                continue  # 跨类目或类目内重复，跳过
            seen_asins.add(asin)
            p['category_en'] = cat_en
            p['category_short'] = CATEGORY_SHORT_NAMES.get(cat_en, cat_en)
            p['_title_cn'] = translate_title(p.get('title', ''))
            all_products.append(p)

    label_colors = {
        '潜力新品': '#E2EFDA',
        '标准爆品': '#FCE4D6',
        '头部爆品': '#F4B4B4',
    }

    # 构建 HTML
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{prefix} {date_str}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: "Microsoft YaHei", "微软雅黑", Arial, sans-serif; font-size: 13px; background: #f5f5f5; }}
.header {{ background: #2F5496; color: #fff; padding: 12px 20px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 100; }}
.header h1 {{ font-size: 18px; }}
.header .info {{ font-size: 12px; opacity: 0.9; }}
.toolbar {{ background: #fff; padding: 10px 20px; border-bottom: 1px solid #ddd; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; position: sticky; top: 56px; z-index: 99; }}
.toolbar button {{ padding: 6px 16px; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; font-family: inherit; }}
.btn-export {{ background: #2F5496; color: #fff; }}
.btn-export:hover {{ background: #1e3a6e; }}
.btn-select-all {{ background: #28a745; color: #fff; }}
.btn-deselect-all {{ background: #dc3545; color: #fff; }}
.toolbar .count {{ margin-left: auto; font-weight: bold; color: #666; }}
.filter-group {{ display: flex; gap: 5px; align-items: center; }}
.filter-group select {{ padding: 4px 8px; border: 1px solid #ccc; border-radius: 3px; font-size: 12px; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; }}
th {{ background: #2F5496; color: #fff; padding: 8px 6px; font-size: 11px; text-align: center; position: sticky; top: 106px; z-index: 50; white-space: nowrap; }}
td {{ padding: 6px; border-bottom: 1px solid #eee; vertical-align: middle; font-size: 11px; }}
tr:hover {{ background: #f8f9ff; }}
tr.selected {{ background: #d4edda !important; }}
img.product-img {{ width: 80px; height: 80px; object-fit: contain; border: 1px solid #eee; border-radius: 4px; background: #fafafa; }}
.cb-col {{ width: 30px; text-align: center; }}
.cb-col input {{ transform: scale(1.3); cursor: pointer; }}
.label-badge {{ display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: bold; }}
.title-cell {{ max-width: 300px; word-wrap: break-word; }}
.cn-cell {{ max-width: 250px; color: #666; word-wrap: break-word; }}
.num-cell {{ text-align: right; white-space: nowrap; }}
.price-cell {{ color: #c00; font-weight: bold; }}
.rating {{ color: #f0ad4e; font-weight: bold; }}
a {{ color: #2F5496; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.category-tab {{ display: inline-block; padding: 4px 12px; border-radius: 3px; cursor: pointer; font-size: 12px; background: #e9ecef; border: 1px solid #ddd; }}
.category-tab.active {{ background: #2F5496; color: #fff; border-color: #2F5496; }}
.toast {{ position: fixed; top: 20px; right: 20px; background: #28a745; color: #fff; padding: 10px 20px; border-radius: 4px; z-index: 9999; display: none; }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>{prefix} {date_str}</h1>
    <div class="info">{collect_type.upper()} 采集 · 共 <span id="totalCount">{len(all_products)}</span> 个产品</div>
  </div>
</div>

<div class="toolbar">
  <button class="btn-select-all" onclick="selectAll()">✅ 全选</button>
  <button class="btn-deselect-all" onclick="deselectAll()">⬜ 取消全选</button>
  <div class="filter-group">
    <label>类目:</label>
    <select id="categoryFilter" onchange="filterTable()">
      <option value="all">全部类目</option>
"""
    for cat_en in CATEGORIES:
        short = CATEGORY_SHORT_NAMES.get(cat_en, cat_en)
        html += f'      <option value="{cat_en}">{short}</option>\n'

    html += f"""    </select>
  </div>
  <div class="filter-group">
    <label>标签:</label>
    <select id="labelFilter" onchange="filterTable()">
      <option value="all">全部标签</option>
"""
    for label, color in label_colors.items():
        html += f'      <option value="{label}">{label}</option>\n'

    html += """    </select>
  </div>
  <button class="btn-export" onclick="exportExcel()">📥 导出勾选的到 Excel</button>
  <span class="count">已勾选: <span id="selectedCount">0</span></span>
</div>

<table id="productTable">
<thead>
<tr>
  <th class="cb-col"><input type="checkbox" id="checkAll" onchange="toggleAll(this)"></th>
  <th>主图</th>
  <th>产品类目</th>
  <th>ASIN</th>
  <th>品牌</th>
  <th>Item Name(标题)</th>
  <th>中文简介</th>
  <th>近30天销量</th>
  <th>月销售额</th>
  <th>零售价</th>
  <th>上架时间</th>
  <th>卖家</th>
  <th>评分</th>
  <th>评论数</th>
  <th>BSR排名</th>
  <th>变体数</th>
  <th>标签</th>
</tr>
</thead>
<tbody>
"""

    for i, p in enumerate(all_products):
        label = p.get('__label__', '')
        row_color = label_colors.get(label, '')
        img_url = p.get('image', '')

        html += f"""<tr class="product-row" data-category="{p['category_en']}" data-label="{label}" data-id="{i}">
  <td class="cb-col"><input type="checkbox" class="row-check" onchange="updateCount()"></td>
  <td><img class="product-img" src="{img_url}" loading="lazy" onerror="this.style.display='none'" alt=""></td>
  <td>{p['category_short']}</td>
  <td><a href="https://www.amazon.com/dp/{p.get('asin','')}" target="_blank">{p.get('asin','')}</a></td>
  <td>{p.get('brand','')}</td>
  <td class="title-cell">{p.get('title','')}</td>
  <td class="cn-cell">{p.get('_title_cn','')}</td>
  <td class="num-cell">{p.get('sales','')}</td>
  <td class="num-cell">{p.get('monthly_sales','')}</td>
  <td class="num-cell price-cell">{p.get('price','')}</td>
  <td>{p.get('available','')}</td>
  <td>{p.get('seller','')}</td>
  <td class="num-cell rating">{p.get('rating','')}</td>
  <td class="num-cell">{p.get('reviews','')}</td>
  <td class="num-cell">{p.get('bsr','')}</td>
  <td class="num-cell">{p.get('variants','')}</td>
  <td><span class="label-badge" style="background:{row_color}">{label}</span></td>
</tr>
"""

    html += """</tbody></table>

<div class="toast" id="toast"></div>

<script>
function updateCount() {
  const checked = document.querySelectorAll('.row-check:checked');
  document.getElementById('selectedCount').textContent = checked.length;
  document.getElementById('checkAll').indeterminate = checked.length > 0 && checked.length < document.querySelectorAll('.row-check').length;
  document.getElementById('checkAll').checked = checked.length === document.querySelectorAll('.row-check').length;
}

function toggleAll(cb) {
  const visible = Array.from(document.querySelectorAll('.product-row')).filter(r => r.style.display !== 'none');
  visible.forEach(r => {
    r.querySelector('.row-check').checked = cb.checked;
    r.classList.toggle('selected', cb.checked);
  });
  updateCount();
}

function selectAll() {
  const visible = Array.from(document.querySelectorAll('.product-row')).filter(r => r.style.display !== 'none');
  visible.forEach(r => {
    r.querySelector('.row-check').checked = true;
    r.classList.add('selected');
  });
  updateCount();
}

function deselectAll() {
  document.querySelectorAll('.row-check').forEach(cb => {
    cb.checked = false;
    cb.closest('tr').classList.remove('selected');
  });
  updateCount();
}

function filterTable() {
  const catVal = document.getElementById('categoryFilter').value;
  const labelVal = document.getElementById('labelFilter').value;
  document.querySelectorAll('.product-row').forEach(row => {
    const cat = row.dataset.category;
    const label = row.dataset.label;
    const show = (catVal === 'all' || cat === catVal) && (labelVal === 'all' || label === labelVal);
    row.style.display = show ? '' : 'none';
  });
  updateCount();
}

document.querySelectorAll('.row-check').forEach(cb => {
  cb.addEventListener('change', function() {
    this.closest('tr').classList.toggle('selected', this.checked);
    updateCount();
  });
});

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 2000);
}

async function exportExcel() {
  const checked = document.querySelectorAll('.row-check:checked');
  if (checked.length === 0) {
    showToast('请先勾选产品');
    return;
  }

  const btn = document.querySelector('.btn-export');
  btn.textContent = '⏳ 生成中...';
  btn.disabled = true;

  const data = [];
  checked.forEach(cb => {
    const row = cb.closest('tr');
    const cells = row.querySelectorAll('td');
    // 使用 data-category 获取完整类目名（而非表格缩写）
    const fullCategory = row.dataset.category || cells[2].textContent;
    data.push({
      category: fullCategory,
      asin: cells[3].textContent,
      brand: cells[4].textContent,
      image: row.querySelector('img')?.src || '',
      title: cells[5].textContent,
      _title_cn: cells[6].textContent,
      sales: cells[7].textContent,
      monthly_sales: cells[8].textContent,
      price: cells[9].textContent,
      available: cells[10].textContent,
      seller: cells[11].textContent,
      rating: cells[12].textContent,
      reviews: cells[13].textContent,
      bsr: cells[14].textContent,
      variants: cells[15].textContent,
      __label__: cells[16].textContent,
    });
  });

  // 先尝试调用后端导出服务
  try {
    const resp = await fetch(`http://127.0.0.1:EXPORT_PORT/export`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({products: data, type: 'COLLECT_TYPE'}),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || ('HTTP ' + resp.status));
    }
    const blob = await resp.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const date = new Date().toISOString().slice(0,10);
    const prefix = 'COLLECT_TYPE' === 'new' ? 'DuraTech_新品筛选' : 'DuraTech_爆品筛选';
    a.download = prefix + '_' + date + '.xlsx';
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
    showToast('已导出 ' + data.length + ' 条产品');
    btn.textContent = '📥 导出勾选的到 Excel';
    btn.disabled = false;
    return;
  } catch(e) {
    console.error('后端导出失败，自动 fallback 到 JSON 下载:', e);
  }

  // Fallback: 下载 JSON 数据文件，用户可在本地用脚本转 Excel
  try {
    const date = new Date().toISOString().slice(0,10);
    const prefix = 'COLLECT_TYPE' === 'new' ? 'DuraTech_新品筛选' : 'DuraTech_爆品筛选';
    const blob = new Blob([JSON.stringify({products: data, type: 'COLLECT_TYPE'}, null, 2)], {type: 'application/json'});
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = prefix + '_' + date + '.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
    showToast('已下载 JSON (' + data.length + ' 条) - 用 Python 脚本转 Excel');
  } catch(e) {
    showToast('下载失败: ' + e.message);
    console.error(e);
  }
  btn.textContent = '📥 导出勾选的到 Excel';
  btn.disabled = false;
}
</script>"""
    
    # 替换占位符
    html = html.replace('EXPORT_PORT', str(export_port))
    html = html.replace('COLLECT_TYPE', collect_type)
    
    # 追加结束标签
    html += '\n</body>\n</html>'

    Path(output_path).write_text(html, encoding='utf-8')
    print(f"[OK] HTML 已生成: {output_path}")
    print(f"     产品总数: {len(all_products)}")
    return output_path


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', '-j', required=True, help='原始 JSON 数据文件')
    parser.add_argument('--type', '-t', choices=['new', 'hot'], required=True, help='new/hot')
    parser.add_argument('--output', '-o', help='输出 HTML 路径')
    parser.add_argument('--port', '-p', type=int, default=58900, help='导出服务端口')
    args = parser.parse_args()

    build_html(
        json_path=args.json,
        collect_type=args.type,
        output_path=args.output,
        export_port=args.port,
    )
