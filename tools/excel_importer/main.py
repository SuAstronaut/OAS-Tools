# -*- coding: utf-8 -*-
"""OAS 小号 Excel 导入工具 —— Windows GUI（tkinter）。

支持「位置映射」：Excel 位置 -> 任意 OAS config JSON 文件名（不再硬编码小号1/2/3.json）。
映射保存在工具目录 settings.json（不含任何账号内容）。
"""
import json
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import core

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(TOOL_DIR, 'settings.json')
DEFAULT_OAS = ''


def load_settings():
    data = {'oas_path': '', 'position_mapping': {}}
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, encoding='utf-8') as f:
                saved = json.load(f)
            if isinstance(saved.get('oas_path'), str):
                data['oas_path'] = saved['oas_path']
            if isinstance(saved.get('position_mapping'), dict):
                data['position_mapping'] = {str(k): str(v) for k, v in saved['position_mapping'].items()}
    except Exception:
        pass
    return data


def save_settings(oas_path, position_mapping):
    data = {'oas_path': oas_path, 'position_mapping': position_mapping or {}}
    tmp = SETTINGS_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS_PATH)


def validate_oas_root(oas):
    """校验 OAS 根目录：必须含核心目录和当前或旧版启动入口。"""
    if not oas or not os.path.isdir(oas):
        return 'OAS 路径不存在'
    missing = []
    for name in ('config', 'module', 'tasks'):
        if not os.path.isdir(os.path.join(oas, name)):
            missing.append(name)
    if missing:
        return 'OAS 目录缺少必要结构: %s' % '、'.join(missing)
    if not (os.path.isfile(os.path.join(oas, 'server.py'))
            or os.path.isfile(os.path.join(oas, 'gui.py'))):
        return '未找到 OAS 启动入口: server.py / gui.py'
    return ''


class App:
    def __init__(self, root):
        self.root = root
        root.title('OAS 小号 Excel 导入工具（位置映射版）')
        root.geometry('720x720')
        self.excel_path = tk.StringVar()
        self.oas_path = tk.StringVar()
        self.allow_shrink = tk.BooleanVar(value=False)
        self.blank_zero = tk.BooleanVar(value=True)
        self._settings = load_settings()
        if self._settings['oas_path']:
            self.oas_path.set(self._settings['oas_path'])
        # 运行时状态
        self._state = None            # (positions, plan, stats, blockers, warnings, errors, json_by_pos, oas, mapping)
        self._positions = {}
        self._json_files = []
        self._mapping = dict(self._settings['position_mapping'])
        self._mapping_rows = {}       # 位置 -> (combobox, status_label)
        self._stat_errs = []

        self._build_ui()
        self._set_status('就绪')

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        pad = {'padx': 10, 'pady': 3}
        tk.Label(self.root, text='OAS 小号 Excel 导入工具', font=('Microsoft YaHei', 14, 'bold')).pack(pady=8)

        f1 = tk.Frame(self.root); f1.pack(fill='x', **pad)
        tk.Label(f1, text='Excel文件：', width=11, anchor='w').pack(side='left')
        tk.Entry(f1, textvariable=self.excel_path, width=48).pack(side='left')
        tk.Button(f1, text='选择', command=self._choose_excel).pack(side='left', padx=6)

        f2 = tk.Frame(self.root); f2.pack(fill='x', **pad)
        tk.Label(f2, text='OAS路径：', width=11, anchor='w').pack(side='left')
        tk.Entry(f2, textvariable=self.oas_path, width=48).pack(side='left')
        tk.Button(f2, text='选择', command=self._choose_oas).pack(side='left', padx=6)
        self._oas_valid = tk.Label(self.root, text='', fg='#888')
        self._oas_valid.pack(anchor='w', padx=12)

        tk.Button(self.root, text='读取并检查', command=self._read_and_check,
                  font=('Microsoft YaHei', 10)).pack(pady=5)

        self.stat_label = tk.Label(self.root, text='Excel 统计：（读取后显示）', justify='left', anchor='w',
                                   font=('Microsoft YaHei', 10))
        self.stat_label.pack(fill='x', **pad)
        self.sync_label = tk.Label(self.root, text='同步状态：（读取后显示）', justify='left', anchor='w',
                                   font=('Microsoft YaHei', 10))
        self.sync_label.pack(fill='x', **pad)

        # 位置 → JSON 映射
        mm = tk.LabelFrame(self.root, text='位置 → JSON 映射（Excel 位置 → OAS config 下某个 JSON）',
                           font=('Microsoft YaHei', 10))
        mm.pack(fill='x', **pad)
        self.mm_inner = tk.Frame(mm)
        self.mm_inner.pack(fill='x', padx=6, pady=4)
        self.mm_hint = tk.Label(mm, text='读取 Excel 后自动列出位置；同名 JSON 自动匹配，否则请手动选择。',
                                fg='#666', font=('Microsoft YaHei', 9))
        self.mm_hint.pack(anchor='w', padx=8, pady=2)
        mf = tk.Frame(mm); mf.pack(anchor='w', padx=8, pady=2)
        tk.Button(mf, text='自动匹配', command=self._do_auto_match).pack(side='left')
        tk.Button(mf, text='保存映射', command=self._save_mapping).pack(side='left', padx=8)
        tk.Button(mf, text='导出Excel模板', command=self._export_template).pack(side='left')

        f3 = tk.Frame(self.root); f3.pack(fill='x', **pad)
        tk.Checkbutton(f3, text='允许删除 Excel 中不存在的尾部账号（缩容）', variable=self.allow_shrink).pack(anchor='w')
        tk.Checkbutton(f3, text='空白几花账号按 0 处理', variable=self.blank_zero).pack(anchor='w')

        tk.Button(self.root, text='查看完整预览', command=self._show_preview).pack(**pad)
        tk.Button(self.root, text='正式导入', command=self._do_import,
                  font=('Microsoft YaHei', 11, 'bold'), bg='#4a90d9', fg='white').pack(pady=8)

        self.status = tk.Label(self.root, text='', anchor='w', fg='#333')
        self.status.pack(fill='x', side='bottom', padx=10, pady=4)

    def _set_status(self, msg):
        self.status.config(text=msg)

    def _choose_excel(self):
        p = filedialog.askopenfilename(title='选择 Excel 文件', filetypes=[('Excel 文件', '*.xlsx')])
        if p:
            self.excel_path.set(p)

    def _choose_oas(self):
        p = filedialog.askdirectory(title='选择 OAS 根目录（含 config / module / tasks）')
        if not p:
            return
        err = validate_oas_root(p)
        if err:
            messagebox.showerror('路径无效', err)
            return
        self.oas_path.set(p)
        self._oas_valid.config(text='OAS 路径有效：%s' % p, fg='#2a7')
        self._mapping = {}
        self._settings['position_mapping'] = {}
        self._save_mapping(quiet=True)

    # ---------------------------------------------------------------- 读取
    def _read_and_check(self):
        excel = self.excel_path.get().strip()
        oas = self.oas_path.get().strip()
        if not excel:
            messagebox.showwarning('提示', '请先选择 Excel 文件')
            return
        if validate_oas_root(oas):
            messagebox.showerror('错误', 'OAS 路径无效：%s' % validate_oas_root(oas))
            return
        try:
            rows, merged_cells = core.read_xlsx(excel)
            positions, errors, warnings = core.parse_excel(
                rows, blank_flower_zero=self.blank_zero.get(), merged_cells=merged_cells)
            json_files = core.scan_config_json(oas)
            self._positions = positions
            self._json_files = json_files
            self._mapping = {k: v for k, v in self._mapping.items() if k in positions}
            # 自动同名匹配（仅补缺）
            auto = core.auto_match(positions, json_files)
            for pos in positions:
                if pos not in self._mapping or not self._mapping.get(pos):
                    self._mapping[pos] = auto.get(pos, '')
            self._rebuild_mapping_ui()
            map_errs = core.validate_mapping(self._mapping, positions, oas)
            if map_errs:
                self._oas_valid.config(text='映射未完成：' + '；'.join(map_errs), fg='#c00')
                self.stat_label.config(text='Excel 统计：位置未全部映射，无法预览/导入')
                self.sync_label.config(text='同步状态：请完成位置映射后重新“读取并检查”')
                self._state = None
                self._set_status('已读取 Excel，等待完成位置映射')
                return
            mapping = dict(self._mapping)
            json_by_pos = core.load_oas_json(oas, mapping)
            plan, stats, blockers = core.build_plan(positions, json_by_pos)
            summ = core.summarize(plan)
            self._stat_errs = core.statistics_check(plan)
            self._state = (positions, plan, stats, blockers, warnings, errors, json_by_pos, oas, mapping)
            self._oas_valid.config(text='OAS 路径有效，映射完成', fg='#2a7')
        except core.ImportError_ as e:
            messagebox.showerror('读取失败', str(e))
            return

        pos_counts = {p: len(positions[p]) for p in positions}
        stat_txt = ('Excel 统计：\n'
                    '总账号：%d    安卓：%d    IOS：%d\n'
                    '位置计数：%s\n'
                    '几花分布：0花 %d / 1花 %d / 2花 %d / 3花 %d    非法值 %d'
                    % (summ['total'], summ['android'], summ['ios'],
                       ' '.join('%s=%d' % (p, pos_counts[p]) for p in positions),
                       summ['flower'][0], summ['flower'][1], summ['flower'][2], summ['flower'][3],
                       summ['invalid']))
        self.stat_label.config(text=stat_txt)
        sync_txt = ('同步状态：\n'
                    '新增账号：%d    字段变化：%d    顺序变化：%d    缩容风险：%d    错误：%d'
                    % (stats['new'], stats['update'], stats['order_change'],
                       stats['shrink'], stats['error']))
        if blockers:
            sync_txt += '\n⚠ ' + '\n⚠ '.join(blockers[:4])
        if warnings:
            sync_txt += '\n（警告 %d 条，见完整预览）' % len(warnings)
        if self._stat_errs:
            sync_txt += '\n\n⛔ 内部统计异常：' + '；'.join(self._stat_errs)
        self.sync_label.config(text=sync_txt)
        self._set_status('检查完成（仅预览，未写入）')

    # ---------------------------------------------------------------- 映射 UI
    def _rebuild_mapping_ui(self):
        for w in self.mm_inner.winfo_children():
            w.destroy()
        self._mapping_rows = {}
        if not self._positions:
            return
        choices = ['（请选择...）'] + self._json_files
        for pos in self._positions:
            row = tk.Frame(self.mm_inner)
            row.pack(fill='x', pady=1)
            tk.Label(row, text=pos, width=12, anchor='w').pack(side='left')
            cb = ttk.Combobox(row, values=choices, state='readonly', width=28)
            current = self._mapping.get(pos, '')
            cb.set(current if current in self._json_files else '（请选择...）')
            cb.pack(side='left', padx=4)
            st = tk.Label(row, text='已映射' if current else '未映射', fg='#2a7' if current else '#c00')
            st.pack(side='left')
            cb.bind('<<ComboboxSelected>>',
                    lambda e, p=pos, c=cb: self._on_mapping_change(p, c))
            self._mapping_rows[pos] = (cb, st)
        self._update_mapping_status()

    def _on_mapping_change(self, pos, cb):
        sel = cb.get()
        if sel == '（请选择...）':
            self._mapping.pop(pos, None)
        else:
            self._mapping[pos] = sel
        self._state = None  # 映射改变 -> 旧预览作废，必须重新读取
        self._update_mapping_status()
        self._set_status('位置映射已改变，请重新点“读取并检查”')

    def _update_mapping_status(self):
        for pos, (cb, st) in self._mapping_rows.items():
            val = self._mapping.get(pos, '')
            st.config(text='已映射' if val else '未映射',
                      fg='#2a7' if val else '#c00')

    def _do_auto_match(self):
        if not self._positions or not self._json_files:
            messagebox.showinfo('提示', '请先读取 Excel 与 OAS 路径')
            return
        auto = core.auto_match(self._positions, self._json_files)
        for pos in self._positions:
            self._mapping[pos] = auto.get(pos, self._mapping.get(pos, ''))
        self._rebuild_mapping_ui()
        self._state = None
        self._set_status('自动匹配完成，请点“读取并检查”重新预览')

    def _save_mapping(self, quiet=False):
        oas = self.oas_path.get().strip()
        if not oas:
            if not quiet:
                messagebox.showwarning('提示', '请先选择 OAS 路径')
            return
        save_settings(oas, self._mapping)
        if not quiet:
            messagebox.showinfo('已保存', '映射已保存到：\n%s' % SETTINGS_PATH)

    # ---------------------------------------------------------------- 预览
    def _show_preview(self):
        if not self._state:
            messagebox.showinfo('提示', '请先完成位置映射并“读取并检查”')
            return
        positions, plan, stats, blockers, warnings, errors, json_by_pos, oas, mapping = self._state
        win = tk.Toplevel(self.root)
        win.title('完整预览')
        win.geometry('1000x540')
        tree = ttk.Treeview(win, columns=('pos', 'json', 'idx', 'sys', 'email', 'name', 'svr', 'flower', 'old', 'status', 'err'),
                            show='headings')
        heads = {'pos': '位置', 'json': '目标JSON', 'idx': '序号', 'sys': '系统', 'email': '邮箱',
                 'name': '名称', 'svr': '区服', 'flower': '几花', 'old': '当前JSON角色名', 'status': '状态', 'err': '错误原因'}
        widths = {'pos': 60, 'json': 90, 'idx': 45, 'sys': 45, 'email': 190, 'name': 100,
                  'svr': 80, 'flower': 45, 'old': 100, 'status': 90, 'err': 140}
        for c, t in heads.items():
            tree.heading(c, text=t)
            tree.column(c, width=widths[c], anchor='w')
        for it in plan:
            sys_txt = '安卓' if it.get('system') is True else ('IOS' if it.get('system') is False else '?')
            tree.insert('', 'end', values=(
                it['pos'], mapping.get(it['pos'], '?'), it['index'], sys_txt, it['email'], it['name'],
                it['svr'], it.get('flower', ''), it['old_name'], it['status'], it.get('error', '')))
        tree.pack(fill='both', expand=True, padx=6, pady=6)
        sb = ttk.Scrollbar(win, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        if warnings:
            txt = '\n'.join(('⚠ ' + w) for w in warnings)
            tk.Label(win, text=txt, justify='left', anchor='w', fg='#a05a00',
                     font=('Microsoft YaHei', 9)).pack(fill='x', padx=8, pady=4)

    # ---------------------------------------------------------------- 模板
    def _export_template(self):
        p = filedialog.asksaveasfilename(title='导出 Excel 模板', defaultextension='.xlsx',
                                         initialfile='OAS账号导入模板.xlsx',
                                         filetypes=[('Excel 文件', '*.xlsx')])
        if not p:
            return
        try:
            core.export_template(p)
            messagebox.showinfo('完成', '模板已导出：\n%s' % p)
        except Exception as e:
            messagebox.showerror('失败', str(e))

    # ---------------------------------------------------------------- 导入
    def _do_import(self):
        if not self._state:
            messagebox.showinfo('提示', '请先完成位置映射并“读取并检查”')
            return
        positions, plan, stats, blockers, warnings, errors, json_by_pos, oas, mapping = self._state
        if self._stat_errs:
            messagebox.showerror('禁止导入', '内部统计异常：\n' + '\n'.join(self._stat_errs))
            return
        if stats['error'] > 0:
            messagebox.showerror('禁止导入', '存在 %d 个错误行，请先修正 Excel。\n\n%s'
                                 % (stats['error'], '\n'.join(blockers[:6])))
            return
        map_errs = core.validate_mapping(mapping, positions, oas)
        if map_errs:
            messagebox.showerror('禁止导入', '位置映射未完成/非法：\n' + '\n'.join(map_errs))
            return
        if stats['shrink'] > 0 and not self.allow_shrink.get():
            messagebox.showerror('禁止导入', '存在缩容风险（将减少 %d 个账号），且未勾选“允许删除尾部多余账号”。\n\n%s'
                                 % (stats['shrink'], '\n'.join(blockers[:6])))
            return
        msg = '确认按当前 Excel 顺序正式导入到以下 JSON？\n' + \
              '\n'.join('  %s → %s' % (p, mapping[p]) for p in positions)
        if stats['new'] > 0:
            msg += '\n\n将新增 %d 个账号。' % stats['new']
        if stats['order_change'] > 0:
            msg += '\n\n⚠ 检测到 %d 处账号顺序变化，导入后 JSON 顺序将跟随 Excel。' % stats['order_change']
        if not messagebox.askyesno('确认导入', msg):
            return
        try:
            backup_dir, summary, verify_errors = core.apply_plan(
                json_by_pos, plan, oas, mapping,
                allow_shrink=self.allow_shrink.get(),
                blank_flower_zero=self.blank_zero.get(),
                errors=errors)
        except core.ImportError_ as e:
            messagebox.showerror('导入失败', str(e))
            return
        if verify_errors:
            messagebox.showerror('导入完成但验证有误', '\n'.join(verify_errors[:10]))
        else:
            messagebox.showinfo('导入完成', '正式导入成功。\n备份目录：\n%s' % backup_dir)
        self._set_status('已导入（备份于 %s）' % backup_dir)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
