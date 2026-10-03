# OAS-Tools

个人维护的 OAS 辅助工具集合。OAS-Tools 与 OAS 主仓库独立，不是 OAS 运行时依赖。

| 工具 | 用途 | 入口 |
|---|---|---|
| [Diagnostic Assistant](tools/diagnostic_assistant/README.md) | 为 AI / 人工分析提供日志 catalog、parser、证据和诊断报告 | `tools/diagnostic_assistant/main.py` |
| [Click Analyzer](tools/click_analyzer/README.md) | 检查点击坐标、分布、热区和时间轨迹 | `tools/click_analyzer/点击分布分析器.html` |
| [Excel Importer](tools/excel_importer/README.md) | Excel 多账号表导入 MultiDailyAltAcc JSON；会写配置 | `tools/excel_importer/启动.bat` |
| [Account Order Fixer](tools/account_order_fixer/README.md) | 调整 last_complete_time，影响多账号登录排序；会写配置 | `tools/account_order_fixer/启动.bat` |

## 当前使用边界

首版是一次性 COPY 镜像。日常使用仍保持原来的 `scripts/utils/OAS_*` 路径；本仓库承担版本管理、代码备份和未来维护，没有切换入口或建立自动同步。未来 canonical source 另行决定。

44 个复制文件保持原始字节，包括业务代码、BAT、PowerShell 和工具说明。原说明中的旧目录、验收日期与未随仓库分发的报告引用属于历史记录，不是新的运行路径。

本机建议布局为同一父目录下的 `OAS/`、`OAS-Tools/`、`scripts/`。Account Order Fixer 的三层父目录推导在这个布局下仍指向 OAS；它的 BAT 和 Diagnostic Assistant 的生产根仍保留原本机路径。Excel 启动器通过选择 OAS 根目录建立本地 settings。首版没有承诺任意机器直接双击运行。

backup、私人 settings、真实报告、真实点击导出与日志验收 JSON 未复制。诊断器仅保留人工 fixtures；单文件点击 HTML 是 tracked release artifact。原 Excel 测试包含与真实角色重合的标签，未复制，使用新增的纯人工数据测试。

## 人工数据测试

Python 工具使用标准库；建议 Python 3.10+。GUI 需要 tkinter，Windows 启动器使用 PowerShell。Click Analyzer 的开发测试需要 Node.js，用户打开 HTML 不需要 Node。

在仓库根运行：

```text
python -B tools/account_order_fixer/tests_mirror.py
python -B -m unittest discover -s tools/excel_importer/tests -v
python -B -m unittest discover -s tools/diagnostic_assistant/tests -v
python -B tools/diagnostic_assistant/main.py --help
python -B tools/diagnostic_assistant/main.py catalog --fixtures --log-root tools/diagnostic_assistant/fixtures/sample_oas/log --date 2026-10-02
node --test tools/click_analyzer/test.js
```

`tests_mirror.py` 将原测试中的配置读取替换为临时人工配置，再验证取消、YES 确认、备份和写后检查。Excel 测试把目标配置及备份都限制在临时目录。业务代码没有为测试修改。

不要用真实 OAS 配置做写入测试。`validate-local.js` 会读取指定日志并写验收结果，不属于首版 synthetic 测试；本轮未执行。

LICENSE_PENDING：首版未添加许可证，代码来源与合适的许可需要另行确认。

镜像清单、隐私判断和验证结果见 [MIRROR_REPORT.md](MIRROR_REPORT.md)。
