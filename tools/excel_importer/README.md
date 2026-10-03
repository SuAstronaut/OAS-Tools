# OAS 小号 Excel 导入工具（OAS_excel_importer）

一个长期使用的 Windows 小工具：把 Excel 里的多账号表，**按 Excel 从上到下的顺序**，
写进 OAS 的三个小号配置文件（`config/小号1.json`、`小号2.json`、`小号3.json`）。

## 1. 这个工具干什么

- Excel 是账号顺序的**唯一事实来源**：Excel 中同一位置的每一行，依次对应 JSON 的第 1、第 2、第 3……个账号。
- 只改账号级字段（角色名/服务器/账号/苹果安卓/几花），已有账号的其它运行状态不动。
- 新增账号自动使用官方默认结构 + 日常默认开关。
- 自动同步「小号数量」字段（`multi_daily_alt_acc_config.sup_account_count`）。
- 安全：正式导入前备份、原子写入、导入后自动校验。

## 2. 怎么启动

双击 `启动.bat`（它会调用 `D:\Entertainment\Tool\OAS\toolkit\python.exe` 打开 GUI）。

也可以手动运行：

```powershell
"D:\Entertainment\Tool\OAS\toolkit\python.exe" "D:\Entertainment\Tool\scripts\utils\OAS_excel_importer\main.py"
```

> 工具自带 tkinter；读取 xlsx 用的是 Python 标准库，**不需要**安装 openpyxl。

## 3. Excel 格式

表头（第一行）必须包含：

| 系统 | 位置 | 邮箱 | 名称 | 区服 | 羁绊情况 |
|---|---|---|---|---|---|
| 安卓 | 小号1 | 邮箱A | VAL1号 | 常世之国 | 1 |

- 「羁绊情况」列名也可以是「基本情况」。
- 完全空白行会被忽略。
- 系统：安卓/Android→安卓(True)；IOS/iOS/苹果→苹果(False)；**空白继承上一行非空值**；首行空白会报错。
- 区服：允许空白，但已有账号不覆盖、新账号区服为空会报错。
- 可点 GUI 里「导出Excel模板」生成 `OAS账号导入模板.xlsx`。

## 4. 顺序规则（最重要）

- **按 Excel 从上到下的顺序**，位置相同的行为一组，组内保持 Excel 原始相对顺序编号。
- 例如 Excel 是「小号1 / 小号2 / 小号1 / 小号3 / 小号1」，则小号1 的序号是 1、2、3（不是 1、3、5）。
- 绝不按邮箱去 JSON 里搜索匹配；绝不重排序。

## 5. 小号1/2/3 怎么映射

| Excel「位置」 | 写入文件 |
|---|---|
| 小号1 | `D:\Entertainment\Tool\OAS\config\小号1.json` |
| 小号2 | `D:\Entertainment\Tool\OAS\config\小号2.json` |
| 小号3 | `D:\Entertainment\Tool\OAS\config\小号3.json` |

## 6. 如何预览

1. 选 Excel 文件、填 OAS 路径（默认 `D:\Entertainment\Tool\OAS`）。
2. 点「读取并检查」：显示 Excel 统计（总账号/安卓/IOS/小号1/2/3/几花分布）与同步状态（新增/变化/顺序变化/缩容/错误）。
3. 点「查看完整预览」：逐行显示 位置/序号/系统/邮箱/名称/区服/几花/当前JSON角色名/状态。

状态：`无变化`、`将更新`、`将新增`、`顺序变化`、`错误`、`缩容风险`。

## 7. 如何正式导入

确认预览无误后：

1. 勾选需要的选项（「允许删除尾部多余账号」默认不勾；「空白几花按0处理」默认勾选）。
2. 点「正式导入」。
3. 工具会：先备份 → 内存构建 → 原子写 → 重新读取校验。

有错误行、缩容风险（未勾选允许缩容）时会**阻止导入**。

## 8. 自动备份在哪

```
D:\Entertainment\Tool\scripts\utils\OAS_excel_importer\backup\YYYYMMDD-HHMMSS\
```

每次正式导入前，会把本次会修改的小号 JSON 复制一份进去。备份成功后才开始改。

## 9. 0/1/2/3 是什么意思

`羁绊情况` 对应 OAS 的「几花账号」：

- 0 = 零花
- 1 = 一花
- 2 = 二花
- 3 = 三花

只允许写 0/1/2/3（int）。写 4、-1、abc、2.5 等会按错误行处理并**禁止导入**。
「空白几花按0处理」默认勾选，即空白 = 0。

## 10. 新增第 31、第 32 个账号如何处理

- 只要 Excel 里同一位置有 31 行以上，工具就会自动创建 `sup_account_list_31`、`sup_account_list_32`……（按官方默认账号结构生成），
  并把「小号数量」（`sup_account_count`）同步为新的数量。
- 新账号会自动带上一套统一的日常默认开关（补充体力/捐勾玉/庭院/邮件/协作/每周奖励/神秘商店/种树=2/试炼/UP召唤/SR碎片 全部开启）。

## 11. 删除账号为什么需要额外确认

如果 Excel 里的账号数量**少于**当前 JSON（例如原来是 30 个，现在 Excel 只有 28 个），
工具不会静默删除第 29、30 号，而是：

- 预览里标记「缩容风险」并统计将减少的数量；
- 正式导入默认**被阻止**，提示你确认是否允许缩容；
- 只有勾选「允许删除 Excel 中不存在的尾部账号」后才允许删除。

这是为了避免误删历史账号。

## 12. 出错如何恢复 backup

如果导入后发现问题：

1. 打开 `D:\Entertainment\Tool\scripts\utils\OAS_excel_importer\backup\` 下最新的 `YYYYMMDD-HHMMSS` 目录。
2. 里面是导入前的 `小号1.json / 小号2.json / 小号3.json` 原样备份。
3. 把这几个文件复制回 `D:\Entertainment\Tool\OAS\config\` 覆盖即可恢复导入前状态。

> 因为写入是「临时文件 + 原子替换」，导入中途失败时正式 JSON 不会半写坏；恢复只需把备份文件复制回去。
