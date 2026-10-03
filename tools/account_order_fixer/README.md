# OAS 多账号上号顺序修复工具

本工具位于 `D:\Entertainment\Tool\scripts\utils\OAS_account_order_fixer`，是包外独立维护的 Windows CLI 工具。它用于通过重设 MultiDailyAltAcc 账号项的 `last_complete_time`，校正下一轮多账号上号顺序。

## 启动

双击 `启动.bat`。它会根据自身位置定位并使用 `D:\Entertainment\Tool\OAS\toolkit\python.exe`，不依赖当前工作目录，也不会安装任何包。

也可以在命令行运行：

```powershell
& "D:\Entertainment\Tool\OAS\toolkit\python.exe" "D:\Entertainment\Tool\scripts\utils\OAS_account_order_fixer\main.py"
```

默认只扫描 `D:\Entertainment\Tool\OAS\config`；候选必须包含连续的 `sup_account_list_N` 账号项和可识别的字符串 `last_complete_time`。`template*.json` 一律不会列为候选。

## 两种方向

- 正序上号：`#1 → #2 → ... → #N`。工具给 #1 写最新时间，随后每个账号递减 1 分钟。
- 倒序上号：`#N → ... → #2 → #1`。工具给 #N 写最新时间，随后每个账号递减 1 分钟。

已知 OAS 规则为：`last_complete_time` 越晚，下一轮越早上号。工具以当前本机时间的前一天作为时间基准，避免当天任务被误判为已完成；随后按所选方向每个账号递减 1 分钟。工具会在确认前显示当前和目标的实际账号名称顺序，必须手动输入 `YES` 才会写入。

## 安全边界

- 动态识别所有 `sup_account_list_N`，按数字后缀排序；不假设 30 个账号。
- 发现编号缺口（例如 `1,2,3,5`）会提示并拒绝修改。
- 时间必须能统一识别为受支持格式；无法可靠识别时停止，不会擅自转换格式。
- 每次写入前先复制原 JSON 到 `backup\`，备份失败即停止，不覆盖或自动删除旧备份。
- 不使用 `json.dump`。工具通过定位 JSON 字符串值，只替换选中账号的 `last_complete_time`，保持原有 JSON key 顺序、缩进、schema 和其他字段文本不变。
- 写入后会重新读取验证账号数、账号名称、时间唯一性、目标顺序，并验证最终文件等于“原文仅替换目标时间值”的预期文本。

如 JSON 结构、时间格式或账号编号以后变化，工具可能拒绝修改；这是保护机制。

## 自测

以下命令只读取真实 OAS JSON 的结构；实际写入测试都发生在本工具目录的临时副本中，结束后自动清理：

```powershell
& "D:\Entertainment\Tool\OAS\toolkit\python.exe" -B "D:\Entertainment\Tool\scripts\utils\OAS_account_order_fixer\tests.py"
```

自测覆盖 3/7 个账号、正序、倒序、编号缺口、缺少 `last_complete_time`、重复旧时间及非目标文本不变。
