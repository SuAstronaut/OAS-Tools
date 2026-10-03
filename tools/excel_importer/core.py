# -*- coding: utf-8 -*-
"""OAS 小号 Excel 导入工具 —— 核心逻辑（纯标准库，无第三方依赖，可独立测试）。

职责：
- 读取 .xlsx（标准库 zipfile + XML，含 merged cell 系统列）
- 按 Excel 顺序（位置分组 + 组内保序）解析账号
- 「位置映射」：Excel 位置 -> 任意 OAS config JSON 文件名（不再硬编码小号1/2/3.json）
- 扫描 OAS config/*.json，按 MultiDailyAltAcc schema 过滤候选
- 自动同名匹配；无法匹配时由用户手动选择（未映射则禁止导入）
- 对比当前 JSON 生成预览计划（新增/更新/顺序变化/缩容/错误）
- 正式导入：备份 -> 内存构建 -> 原子写 -> 验证

约束：
- Excel 是账号顺序的单一事实来源，绝不按邮箱去 JSON 里搜索匹配。
- 只能写通过位置映射选中的 OAS config JSON。
"""
import datetime
import json
import os
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# 配置（集中在此，不散落硬编码）
# ---------------------------------------------------------------------------

# 列名（羁绊情况 或 基本情况）
FLOWER_COL_ALIASES = ('羁绊情况', '基本情况')
REQUIRED_COLS = ('系统', '位置', '邮箱', '名称', '区服')

# 系统列：安卓 -> True（勾选=安卓）；苹果/iOS -> False
ANDROID_VALUES = {'安卓', 'android', 'android系统'}
IOS_VALUES = {'ios', '苹果', 'apple', 'iphone'}

# 新增账号的日常默认开关（用户统一配置；只应用于新创建的账号槽）
NEW_ACCOUNT_DEFAULTS = {
    'alliedteam_ap_enable': True,
    'donatejade_enable': True,
    'courtyard_enable': True,
    'mail_enable': True,
    'cooperation_enable': True,
    'weekaward_enable': True,
    'mysteryshop_enable': True,
    'tree_planting_enable': 2,
    'trialbattle_enable': True,
    'summon_up_enable': True,
    'publish_sr_enable': True,
}

# 已有账号只同步这 5 项（Excel 指定字段）
SYNC_FIELDS = ('account', 'character', 'svr', 'apple_or_android', 'isflower')

# 过滤候选 JSON 时排除的文件名模式
EXCLUDED_CONFIG_NAMES = ('template',)
EXCLUDED_CONFIG_EXACT = {'oas1.json'}

_XLSX_URI = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_XLSX_NS = '{%s}' % _XLSX_URI


class ImportError_(Exception):
    """工具级错误（含用户可读消息）。"""


class RowError(Exception):
    """单行校验错误。"""


# ---------------------------------------------------------------------------
# .xlsx 读取（标准库，含 merged cell）
# ---------------------------------------------------------------------------

def _col_letters(ref):
    return ''.join(ch for ch in ref if ch.isalpha())


def _col_index(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - ord('A') + 1)
    return n - 1


def _parse_merge_range(ref):
    """解析 'A2:A4' / 'A2:C4' -> (row1, row2, col1, col2)，均为 0-based。"""
    if not ref or ':' not in ref:
        return None
    a, b = ref.split(':', 1)
    ma = re.match(r'([A-Za-z]+)(\d+)', a)
    mb = re.match(r'([A-Za-z]+)(\d+)', b)
    if not ma or not mb:
        return None
    c1 = _col_index(ma.group(1)); c2 = _col_index(mb.group(1))
    r1 = int(ma.group(2)) - 1; r2 = int(mb.group(2)) - 1
    if r1 > r2:
        r1, r2 = r2, r1
    if c1 > c2:
        c1, c2 = c2, c1
    return (r1, r2, c1, c2)


def read_xlsx(path):
    """读取 .xlsx，返回 (rows, merged_cells)。

    rows: list[list[str]]（合并区域内的空白格已用左上角值填充）
    merged_cells: set[(row_idx, col_idx)] —— 原本为空、值来自合并区域左上角（0-based）
    """
    if not os.path.exists(path):
        raise ImportError_('Excel 文件不存在: %s' % path)
    if not path.lower().endswith('.xlsx'):
        raise ImportError_('仅支持 .xlsx 文件: %s' % path)
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if 'xl/worksheets/sheet1.xml' not in names:
                raise ImportError_('xlsx 中未找到工作表 sheet1（可能是其它格式）')
            shared = []
            if 'xl/sharedStrings.xml' in names:
                ss = ET.fromstring(z.read('xl/sharedStrings.xml'))
                for si in ss.findall(_XLSX_NS + 'si'):
                    texts = [t.text or '' for t in si.iter(_XLSX_NS + 't')]
                    shared.append(''.join(texts))
            root = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            rows_out = []
            for row in root.iter(_XLSX_NS + 'row'):
                cells = {}
                max_idx = -1
                for c in row.findall(_XLSX_NS + 'c'):
                    ref = c.get('r', '')
                    idx = _col_index(_col_letters(ref)) if ref else -1
                    t = c.get('t')
                    val = ''
                    v = c.find(_XLSX_NS + 'v')
                    if v is not None and v.text is not None:
                        val = v.text
                    elif t == 'inlineStr':
                        isel = c.find(_XLSX_NS + 'is')
                        if isel is not None:
                            texts = [x.text or '' for x in isel.iter(_XLSX_NS + 't')]
                            val = ''.join(texts)
                    if t == 's' and val != '':
                        try:
                            val = shared[int(float(val))]
                        except (ValueError, IndexError):
                            val = ''
                    if val is None:
                        val = ''
                    if idx >= 0:
                        cells[idx] = val
                        max_idx = max(max_idx, idx)
                if max_idx < 0:
                    continue
                line = [cells.get(i, '') for i in range(max_idx + 1)]
                rows_out.append(line)
            merged_cells = set()
            mc = root.find(_XLSX_NS + 'mergeCells')
            if mc is not None:
                for m in mc.findall(_XLSX_NS + 'mergeCell'):
                    rng = _parse_merge_range(m.get('ref'))
                    if rng is None:
                        continue
                    r1, r2, c1, c2 = rng
                    if r1 >= len(rows_out):
                        continue
                    top = rows_out[r1][c1] if c1 < len(rows_out[r1]) else ''
                    for rr in range(r1, min(r2 + 1, len(rows_out))):
                        while len(rows_out[rr]) <= c2:
                            rows_out[rr].append('')
                        for cc in range(c1, c2 + 1):
                            if rr == r1 and cc == c1:
                                continue
                            if rows_out[rr][cc] == '':
                                rows_out[rr][cc] = top
                                merged_cells.add((rr, cc))
            return rows_out, merged_cells
    except zipfile.BadZipFile:
        raise ImportError_('无法打开 Excel（不是有效的 zip/xlsx）: %s' % path)
    except ET.ParseError:
        raise ImportError_('无法解析 Excel 内部 XML: %s' % path)


# ---------------------------------------------------------------------------
# .xlsx 写入（标准库，用于导出模板）
# ---------------------------------------------------------------------------

def write_xlsx(path, header, rows, extra_sheets=None):
    """用标准库写一个简单的 .xlsx（一个主表 + 可选说明表）。"""
    def _sheet_xml(data_rows, header_row=None):
        all_rows = ([header_row] if header_row else []) + data_rows
        ns = _XLSX_URI
        body = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                '<worksheet xmlns="%s"><sheetData>' % ns]
        for r, row in enumerate(all_rows, start=1):
            cells = []
            for cidx, val in enumerate(row):
                ref = chr(ord('A') + cidx) + str(r)
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    cells.append('<c r="%s" t="n"><v>%s</v></c>' % (ref, val))
                else:
                    text = str(val).replace('&', '&').replace('<', '<').replace('>', '>')
                    cells.append('<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
                                 % (ref, text))
            body.append('<row r="%d">%s</row>' % (r, ''.join(cells)))
        body.append('</sheetData></worksheet>')
        return ''.join(body)

    def _shared_xml():
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<sst xmlns="%s" count="0" uniqueCount="0"></sst>' % _XLSX_URI)

    sheets = [('Sheet1', header, rows)]
    if extra_sheets:
        sheets.extend(extra_sheets)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="xml" ContentType="application/xml"/>'
              '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>')
        for i in range(len(sheets)):
            ct += ('<Override PartName="/xl/worksheets/sheet%d.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1))
        ct += '</Types>'
        z.writestr('[Content_Types].xml', ct)
        z.writestr('_rels/.rels',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        wb_rel = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">')
        for i in range(len(sheets)):
            wb_rel += ('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>'
                       % (i + 2, i + 1))
        wb_rel += '</Relationships>'
        z.writestr('xl/_rels/workbook.xml.rels', wb_rel)
        wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>')
        for i, (name, _, _) in enumerate(sheets, start=1):
            wb += '<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (name, i, i + 1)
        wb += '</sheets></workbook>'
        z.writestr('xl/workbook.xml', wb)
        for i, (_, header_row, data_rows) in enumerate(sheets, start=1):
            z.writestr('xl/worksheets/sheet%d.xml' % i, _sheet_xml(data_rows, header_row))
        z.writestr('xl/sharedStrings.xml', _shared_xml())


def export_template(path):
    """导出 Excel 模板（主表 + 说明 sheet）。"""
    header = ['系统', '位置', '邮箱', '名称', '区服', '羁绊情况']
    note_rows = [
        ['系统：', '安卓 / Android -> 安卓(True)；IOS / 苹果 -> 苹果(False)；空白继承上一行'],
        ['位置：', '任意名称，如 小号1 / A组 / 安卓A（将映射到某个 OAS config JSON）'],
        ['羁绊情况：', '0=零花 1=一花 2=二花 3=三花（空白默认按 0）'],
        ['数据顺序：', '同一位置按 Excel 从上到下依次对应目标 JSON 第 1、第 2、第 3……个账号'],
        ['邮箱 / 名称 / 区服：', '对应 OAS 账号 / 角色名 / 服务器'],
    ]
    extra = [('说明', None, note_rows)]
    write_xlsx(path, header, [], extra_sheets=extra)


# ---------------------------------------------------------------------------
# Excel 解析（位置分组 + 组内保序；位置为任意名称）
# ---------------------------------------------------------------------------

def _norm(value):
    if value is None:
        return ''
    return str(value).strip()


def _parse_system_value(value):
    """系统列值 -> True(安卓) / False(IOS/苹果) / None(无法解析)。

    注意：False 是合法业务值（IOS），绝不视为空/错误；只有 None 表示无法解析。
    """
    v = _norm(value)
    if not v:
        return None
    low = v.lower()
    if low in ANDROID_VALUES or low.startswith('android'):
        return True
    if low in IOS_VALUES or low == 'ios':
        return False
    return None


def _parse_flower(value, blank_is_zero):
    """几花账号：严格 0-3 整数；空白按选项；非法报错。"""
    v = _norm(value)
    if not v:
        if blank_is_zero:
            return 0
        return None  # 保留原值（取消勾选"空白按0"时）
    if re.fullmatch(r'[0-3]', v):
        return int(v)
    raise RowError('几花账号非法: %r（仅允许 0/1/2/3）' % v)


def parse_excel(rows, blank_flower_zero=True, merged_cells=None):
    """解析 Excel 二维数据为按位置分组的账号记录（组内保持 Excel 原始顺序）。

    返回 (positions: dict[位置 -> list[AccountRow]], errors: list[dict], warnings: list[str])
    位置可以是任意非空名称（小号1/A组/安卓A 等）。
    """
    if not rows:
        raise ImportError_('Excel 没有任何数据行')
    header = rows[0]
    header_norm = [_norm(h) for h in header]
    col_idx = {}
    for i, h in enumerate(header_norm):
        if h in REQUIRED_COLS and h not in col_idx:
            col_idx[h] = i
        if h in FLOWER_COL_ALIASES and 'flower' not in col_idx:
            col_idx['flower'] = i
    missing = [c for c in REQUIRED_COLS if c not in col_idx]
    if missing:
        raise ImportError_('Excel 缺少必需列: %s（表头应为：系统/位置/邮箱/名称/区服/羁绊情况）'
                           % '、'.join(missing))
    if 'flower' not in col_idx:
        raise ImportError_('Excel 缺少羁绊情况列（表头应为：系统/位置/邮箱/名称/区服/羁绊情况）')

    if merged_cells is None:
        merged_cells = set()
    positions = {}
    errors = []
    warnings = []
    seen_email = {}       # (位置, 邮箱) -> excel 行号
    seen_full = {}        # (位置, 邮箱+名称+区服+系统) -> excel 行号
    cross_email = {}      # 邮箱 -> set(位置)
    sys_prev = None       # 全局上一有效系统（系统列是整表合并块，空白继承上一行）

    for r in range(1, len(rows)):
        line = rows[r]
        def g(key):
            i = col_idx.get(key)
            if i is None or i >= len(line):
                return ''
            return _norm(line[i])

        excel_row = r + 1
        if all(_norm(c) == '' for c in line):
            continue  # 完全空白行忽略
        pos = g('位置')
        if not pos:
            errors.append({'excel_row': excel_row, 'reason': '位置为空（不允许继承，每行必须填写位置名称）'})
            continue
        email = g('邮箱')
        name = g('名称')
        svr = g('区服')
        flower_raw = g('flower')

        row = {'pos': pos, 'excel_row': excel_row, 'index': None,
               'email': email, 'name': name, 'svr': svr,
               'flower_raw': flower_raw, 'error': None}
        try:
            if not email:
                raise RowError('邮箱为空')
            if not name:
                raise RowError('名称为空')
            # 系统列：有值->用当前值；属于合并单元格->read_xlsx 已用左上角值填充；
            # 普通空白->继承上一有效系统(fallback)并警告；无来源->ERROR
            sys_col_i = col_idx['系统']
            sys_raw_cell = line[sys_col_i] if sys_col_i < len(line) else ''
            is_merged = (r, sys_col_i) in merged_cells
            if _norm(sys_raw_cell):
                sys_val = _parse_system_value(sys_raw_cell)
                source = 'merged' if is_merged else '直接'
                if sys_val is None:
                    raise RowError('系统无法识别: %r（仅安卓/Android 或 IOS/苹果）' % sys_raw_cell)
                sys_prev = sys_val
            else:
                if sys_prev is None:
                    raise RowError('系统列为空且无前值/合并来源，无法继承')
                sys_val = sys_prev
                source = 'merged' if is_merged else 'fallback'
                if not is_merged:
                    warnings.append('Excel 第 %d 行系统空白，继承上一行（非合并单元格）' % excel_row)
            row['system'] = sys_val
            row['system_source'] = source
            row['flower'] = _parse_flower(flower_raw, blank_flower_zero)
        except RowError as e:
            row['error'] = str(e)
            errors.append({'excel_row': excel_row, 'reason': str(e)})
            continue

        if svr == '':
            warnings.append('Excel 第 %d 行（%s / %s）区服为空' % (excel_row, pos, name))

        # 完全相同的记录（同位置 + 同邮箱 + 同角色 + 同区服 + 同系统）→ ERROR
        key_full = (pos, email, name, svr, row.get('system'))
        if key_full in seen_full:
            errors.append({'excel_row': excel_row,
                           'reason': '同一位置完全相同记录重复（与第 %d 行）' % seen_full[key_full]})
            row['error'] = '账号重复'
        else:
            seen_full[key_full] = excel_row
        # 同一位置邮箱重复但记录不同（如同账号不同角色槽位）→ 警告，允许
        key_email = (pos, email)
        if key_email in seen_email:
            if not row.get('error'):
                warnings.append('Excel 第 %d 行：同一位置邮箱重复但记录不同（与第 %d 行）: %s'
                                % (excel_row, seen_email[key_email], email))
        else:
            seen_email[key_email] = excel_row

        cross_email.setdefault(email, set()).add(pos)
        positions.setdefault(pos, []).append(row)

    for email, poss in cross_email.items():
        if len(poss) > 1:
            warnings.append('同一邮箱出现在多个位置: %s -> %s（可能为同一登录账号不同槽位，允许）'
                            % (email, '、'.join(sorted(poss))))
    for pos, lst in positions.items():
        for i, row in enumerate(lst, start=1):
            row['index'] = i
    return positions, errors, warnings


# ---------------------------------------------------------------------------
# OAS config 扫描 与 位置映射
# ---------------------------------------------------------------------------

def is_multi_daily_account_json(data):
    """按 schema 判断：是否 MultiDailyAltAcc 账号配置 JSON。

    至少要求存在 multi_daily_alt_acc 且其下有多账号配置与账号槽结构。
    """
    if not isinstance(data, dict):
        return False
    mda = data.get('multi_daily_alt_acc')
    if not isinstance(mda, dict):
        return False
    cfg = mda.get('multi_daily_alt_acc_config')
    if not isinstance(cfg, dict):
        return False
    has_slots = any(str(k).startswith('sup_account_list_') for k in mda)
    # 允许极少数尚未有账号槽但仍属多账号结构的（空配置）；为稳妥要求结构键存在
    return 'sup_account_count' in cfg or has_slots


def scan_config_json(oas_root):
    """扫描 <oas_root>/config/*.json，返回符合 MultiDailyAltAcc schema 的文件名列表。

    过滤：template*.json、oas1.json、非 MultiDailyAltAcc 结构的 JSON。
    """
    cfg_dir = os.path.join(oas_root, 'config')
    if not os.path.isdir(cfg_dir):
        raise ImportError_('OAS 目录缺少 config 子目录: %s' % cfg_dir)
    out = []
    for fn in sorted(os.listdir(cfg_dir)):
        if not fn.lower().endswith('.json'):
            continue
        if fn in EXCLUDED_CONFIG_EXACT:
            continue
        if any(fn.startswith(prefix) for prefix in EXCLUDED_CONFIG_NAMES):
            continue
        try:
            with open(os.path.join(cfg_dir, fn), encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue
        if is_multi_daily_account_json(data):
            out.append(fn)
    return out


def auto_match(positions, json_files):
    """同名自动匹配：位置字符串 == JSON 文件名 basename（去掉 .json）时自动匹配。"""
    mapping = {}
    base_by_name = {}
    for fn in json_files:
        base_by_name[fn[:-5] if fn.lower().endswith('.json') else fn] = fn
    for pos in positions:
        if pos in base_by_name:
            mapping[pos] = base_by_name[pos]
    return mapping


def validate_mapping(mapping, positions, oas_root):
    """校验位置映射。返回 (errors: list[str])。

    规则：每个 Excel 出现的位置都必须已映射；目标文件存在且为合法结构；
    不允许两个位置映射到同一个 JSON。
    """
    errors = []
    seen_target = {}
    cfg_dir = os.path.join(oas_root, 'config')
    for pos in positions:
        target = (mapping or {}).get(pos)
        if not target:
            errors.append('位置「%s」未选择目标 JSON' % pos)
            continue
        if target in seen_target:
            errors.append('位置「%s」与「%s」映射到同一 JSON（%s），不允许' % (pos, seen_target[target], target))
            continue
        seen_target[target] = pos
        p = os.path.join(cfg_dir, target)
        if not os.path.exists(p):
            errors.append('位置「%s」目标 JSON 不存在: %s' % (pos, target))
            continue
        try:
            with open(p, encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            errors.append('位置「%s」目标 JSON 无法解析: %s' % (pos, target))
            continue
        if not is_multi_daily_account_json(data):
            errors.append('位置「%s」目标 JSON 不是 MultiDailyAltAcc 账号配置: %s' % (pos, target))
    return errors


def config_path(oas_root, filename):
    """目标 JSON 完整路径。"""
    return os.path.join(oas_root, 'config', filename)


def load_oas_json(oas_root, mapping):
    """按位置映射读取 JSON，返回 {位置: data}（仅加载映射中且存在的位置）。"""
    out = {}
    for pos, fn in (mapping or {}).items():
        p = config_path(oas_root, fn)
        if not os.path.exists(p):
            raise ImportError_('位置「%s」目标 JSON 不存在: %s' % (pos, fn))
        with open(p, encoding='utf-8') as f:
            out[pos] = json.load(f)
    return out


# ---------------------------------------------------------------------------
# JSON 读取 / 原子写入
# ---------------------------------------------------------------------------

def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _check_dup_json(text):
    dup = []

    def hook(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                dup.append(k)
            d[k] = v
        return d

    json.loads(text, object_pairs_hook=hook)
    return dup


def save_json_atomic(path, data):
    """原子写：临时文件 -> 校验 -> os.replace。失败时原文件不变。"""
    d = os.path.dirname(path) or '.'
    tmp = os.path.join(d, '.%s.oas_imp.tmp' % os.path.basename(path))
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False, default=str)
    dup = _check_dup_json(text)
    if dup:
        raise ImportError_('生成的新 JSON 存在重复 key: %s' % dup[:5])
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    os.replace(tmp, path)


def _accounts_of(mda):
    """从 multi_daily_alt_acc 中提取按数字序的账号列表（dicts）。"""
    items = []
    for k, v in mda.items():
        if k.startswith('sup_account_list_'):
            try:
                n = int(k[len('sup_account_list_'):])
            except ValueError:
                continue
            items.append((n, k, v))
    items.sort(key=lambda x: x[0])
    return [(k, v) for _, k, v in items]


def _build_accounts_dict(accounts):
    return {'sup_account_list_%d' % i: acct for i, acct in enumerate(accounts, start=1)}


# ---------------------------------------------------------------------------
# 预览计划
# ---------------------------------------------------------------------------

def build_plan(positions, json_by_pos):
    """生成预览计划。返回 (plan: list[dict], stats: dict, blockers: list[str])。

    positions 与 json_by_pos 的键一致（Excel 出现且已映射的位置）。
    """
    plan = []
    stats = {'new': 0, 'update': 0, 'order_change': 0, 'shrink': 0, 'error': 0}
    blockers = []
    for pos, rows in positions.items():
        if pos not in json_by_pos:
            continue
        mda = (json_by_pos.get(pos) or {}).get('multi_daily_alt_acc') or {}
        accounts = _accounts_of(mda)
        n_excel = len(rows)
        n_json = len(accounts)
        if n_excel < n_json:
            stats['shrink'] += (n_json - n_excel)
            blockers.append('%s：现有 %d 个账号，Excel 只有 %d 个，将减少 %d 个（默认禁止缩容）'
                            % (pos, n_json, n_excel, n_json - n_excel))
        for row in rows:
            i = row['index']
            item = {
                'pos': pos, 'index': i,
                'system': row.get('system'), 'email': row['email'], 'name': row['name'],
                'svr': row['svr'], 'flower': row.get('flower'), 'flower_raw': row['flower_raw'],
                'old_name': '', 'status': '无变化', 'excel_row': row['excel_row'],
                'svr_warn': (row['svr'] == ''),
                'error': row.get('error') or '',
                'system_source': row.get('system_source') or '',
            }
            if row.get('error'):
                item['status'] = '错误'
                stats['error'] += 1
                plan.append(item)
                continue
            if i <= n_json:
                old = accounts[i - 1][1]
                old_name = old.get('character', '')
                item['old_name'] = old_name
                if old_name != row['name']:
                    item['status'] = '顺序变化'
                    stats['order_change'] += 1
                    stats['update'] += 1
                else:
                    changed = False
                    if old.get('account', '') != row['email']:
                        changed = True
                    if old.get('svr', '') != row['svr']:
                        changed = True
                    if bool(old.get('apple_or_android', True)) != row['system']:
                        changed = True
                    old_flower = old.get('isflower', 0)
                    if row['flower'] is not None and old_flower != row['flower']:
                        changed = True
                    if changed:
                        item['status'] = '将更新'
                        stats['update'] += 1
            else:
                item['status'] = '将新增'
                stats['new'] += 1
                if row['svr'] == '':
                    item['error'] = '新账号区服为空'
                    blockers.append('新账号（%s 第 %d 个）区服为空，无法导入' % (pos, i))
                    item['status'] = '错误'
                    stats['error'] += 1
            plan.append(item)
    return plan, stats, blockers


# ---------------------------------------------------------------------------
# 正式导入
# ---------------------------------------------------------------------------

def apply_plan(json_by_pos, plan, oas_root, mapping, allow_shrink=False,
               blank_flower_zero=True, errors=None):
    """正式导入（先备份，再逐位置构建新 JSON，原子写，最后验证）。

    mapping: {位置 -> 目标 JSON 文件名}。返回 (backup_dir, summary, verify_errors)。
    任何失败抛 ImportError_，原文件不变。
    """
    if errors:
        raise ImportError_('Excel 存在 %d 个错误行，禁止正式导入（请先修正）: 如 %s'
                           % (len(errors), errors[0].get('reason', '')))
    stat_errs = statistics_check(plan)
    if stat_errs:
        raise ImportError_('禁止导入（内部统计异常）: %s' % '；'.join(stat_errs))
    per_pos = {}
    for item in plan:
        per_pos.setdefault(item['pos'], []).append(item)
    if any(i.get('status') == '错误' for i in plan):
        raise ImportError_('存在错误行，禁止正式导入（请先修正 Excel）')
    for pos, items in per_pos.items():
        n_excel = len(items)
        mda = (json_by_pos.get(pos) or {}).get('multi_daily_alt_acc') or {}
        n_json = len(_accounts_of(mda))
        if n_excel < n_json and not allow_shrink:
            raise ImportError_('%s：Excel 账号数量(%d)少于现有 JSON(%d)，未勾选“允许删除尾部多余账号”，禁止导入'
                               % (pos, n_excel, n_json))

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    # 备份保存在「程序所在目录/backup」，绝不在 OAS 仓库内
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backup', stamp)
    os.makedirs(backup_dir, exist_ok=True)
    for pos, items in per_pos.items():
        fn = mapping[pos]
        src = config_path(oas_root, fn)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(backup_dir, os.path.basename(fn)))

    for pos, items in per_pos.items():
        fn = mapping[pos]
        target = config_path(oas_root, fn)
        data = json_by_pos.get(pos)
        if data is None:
            raise ImportError_('位置「%s」缺少 JSON 数据: %s' % (pos, fn))
        mda = data.get('multi_daily_alt_acc')
        if not isinstance(mda, dict):
            raise ImportError_('%s 缺少 multi_daily_alt_acc 结构' % fn)
        accounts = _accounts_of(mda)
        new_accounts = []
        for it in items:
            i = it['index']
            if i <= len(accounts):
                acct = dict(accounts[i - 1][1])
                acct['account'] = it['email']
                acct['character'] = it['name']
                if it['svr']:
                    acct['svr'] = it['svr']
                acct['apple_or_android'] = bool(it['system'])
                if it['flower'] is not None:
                    acct['isflower'] = it['flower']
                new_accounts.append(acct)
            else:
                new_accounts.append(_new_account_dict(it))
        n_excel = len(items)
        if allow_shrink and n_excel < len(accounts):
            new_accounts = new_accounts[:n_excel]
        new_mda = dict(mda)
        for k in list(new_mda.keys()):
            if k.startswith('sup_account_list_'):
                del new_mda[k]
        for k, v in _build_accounts_dict(new_accounts).items():
            new_mda[k] = v
        cfg = new_mda.get('multi_daily_alt_acc_config')
        if isinstance(cfg, dict):
            cfg['sup_account_count'] = len(new_accounts)
            new_mda['multi_daily_alt_acc_config'] = cfg
        data['multi_daily_alt_acc'] = new_mda
        save_json_atomic(target, data)

    verify_errors = verify_import(per_pos, oas_root, mapping)
    summary = {'backup_dir': backup_dir,
               'positions': {pos: len(items) for pos, items in per_pos.items()}}
    return backup_dir, summary, verify_errors


def _new_account_dict(item):
    """官方默认账号结构 + Excel 指定 5 项 + 用户统一默认开关。"""
    acct = {
        'character': item['name'],
        'svr': item['svr'],
        'account': item['email'],
        'account_alias': '',
        'apple_or_android': bool(item['system']),
        'last_complete_time': '2023-01-01 00:00:00',
        'alliedteam_battle_enable': False,
        'alliedteam_limit_count': 30,
        'alliedteam_invite_count': 2,
        'alliedteam_ap_enable': True,
        'donatejade_enable': True,
        'courtyard_enable': True,
        'mail_enable': True,
        'cooperation_enable': True,
        'returngift_enable': True,
        'weekaward_enable': True,
        'mysteryshop_enable': True,
        'isflower': item['flower'] if item['flower'] is not None else 0,
        'kekkaiActivation_enable': True,
        'KekkaiUtilize_enable': True,
        'tree_planting_enable': 2,
        'trialbattle_enable': True,
        'summon_up_enable': True,
        'publish_sr_enable': True,
    }
    acct.update(NEW_ACCOUNT_DEFAULTS)
    return acct


def verify_import(per_pos, oas_root, mapping):
    """导入后重新读取 JSON，验证顺序与字段是否与 Excel 计划一致。"""
    errors = []
    for pos, items in per_pos.items():
        fn = mapping[pos]
        target = config_path(oas_root, fn)
        try:
            data = load_json(target)
        except Exception as e:
            errors.append('%s 重新读取失败: %s' % (pos, e))
            continue
        mda = data.get('multi_daily_alt_acc') or {}
        accounts = _accounts_of(mda)
        if len(accounts) != len(items):
            errors.append('%s 账号数量不符: JSON=%d Excel=%d' % (pos, len(accounts), len(items)))
        for it in items:
            i = it['index']
            if i > len(accounts):
                errors.append('%s 第 %d 个账号缺失' % (pos, i))
                continue
            acct = accounts[i - 1][1]
            if acct.get('character') != it['name']:
                errors.append('%s 第 %d 个角色名不符: JSON=%r Excel=%r'
                              % (pos, i, acct.get('character'), it['name']))
            if acct.get('account') != it['email']:
                errors.append('%s 第 %d 个账号不符: JSON=%r Excel=%r'
                              % (pos, i, acct.get('account'), it['email']))
            if it['svr'] and acct.get('svr') != it['svr']:
                errors.append('%s 第 %d 个区服不符' % (pos, i))
            if bool(acct.get('apple_or_android', True)) != bool(it['system']):
                errors.append('%s 第 %d 个系统不符' % (pos, i))
            if it['flower'] is not None and acct.get('isflower') != it['flower']:
                errors.append('%s 第 %d 个几花不符' % (pos, i))
    return errors


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------

def summarize(plan):
    """统计总账号/安卓/IOS/几花分布（含按位置计数）。"""
    total = 0
    android = 0
    ios = 0
    flower = {0: 0, 1: 0, 2: 0, 3: 0}
    posn = {}
    invalid = 0
    for it in plan:
        if it.get('status') == '错误':
            invalid += 1
            continue
        total += 1
        if it.get('system') is True:
            android += 1
        elif it.get('system') is False:
            ios += 1
        f = it.get('flower')
        if f in flower:
            flower[f] += 1
        posn[it['pos']] = posn.get(it['pos'], 0) + 1
    return {'total': total, 'android': android, 'ios': ios,
            'flower': flower, 'invalid': invalid, 'positions': posn}


def statistics_check(plan):
    """内部统计一致性校验：总账号 == 安卓+IOS == 各位置之和。返回错误列表。"""
    s = summarize(plan)
    errs = []
    if s['android'] + s['ios'] != s['total']:
        errs.append('总账号(%d) != 安卓(%d) + IOS(%d)'
                    % (s['total'], s['android'], s['ios']))
    if sum(s['positions'].values()) != s['total']:
        errs.append('总账号(%d) != 各位置之和(%d)'
                    % (s['total'], sum(s['positions'].values())))
    return errs
