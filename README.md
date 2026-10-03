# OAS-Tools

个人维护的 OAS 辅助工具集合。OAS-Tools 与 OAS 主仓库独立，不是 OAS 运行时依赖。

| 工具 | 用途 | 入口 |
|---|---|---|
| [Diagnostic Assistant](tools/diagnostic_assistant/README.md) | 为 AI / 人工分析提供日志 catalog、parser、证据和诊断报告 | `tools/diagnostic_assistant/main.py` |
| [Click Analyzer](tools/click_analyzer/README.md) | 检查点击坐标、分布、热区和时间轨迹 | `tools/click_analyzer/点击分布分析器.html` |
| [Excel Importer](tools/excel_importer/README.md) | Excel 多账号表导入 MultiDailyAltAcc JSON；会写配置 | `tools/excel_importer/启动.bat` |
| [Account Order Fixer](tools/account_order_fixer/README.md) | 调整 last_complete_time，影响多账号登录排序；会写配置 | `tools/account_order_fixer/启动.bat` |

## 当前使用边界

OAS-Tools 是四个工具的主维护源码（canonical source），正式运行入口仍保持原来的 `scripts/utils/OAS_*` 路径。

```text
Development / maintenance: D:\Entertainment\Tool\OAS-Tools
Runtime:                   D:\Entertainment\Tool\scripts\utils
```

在仓库根手动执行：

```powershell
.\sync_to_runtime.ps1         # 默认 dry-run，只比较 SHA256，不写文件
.\sync_to_runtime.ps1 -Apply  # 检查完成后更新白名单源码
```

同步只有 OAS-Tools → runtime 一个方向。脚本中的逐文件白名单还必须是 Git tracked 文件；新文件需要先审查、加入白名单并手动 `git add`，无需先 commit。未提交修改会显示 warning，允许同步。根 README、同步脚本及根 tests 不部署到 runtime。

backup、settings.json、reports、examples、缓存、本地输出和 runtime 独有文件均保留；仓库删除文件也不会删除 runtime 文件。没有反向同步、自动任务、监听器、Git hook 或链接。默认要求同一父目录下的 OAS-Tools 与 scripts/utils，且四个运行工具目录均已存在；同步路径中的 junction/symlink 会被拒绝。

Apply 先完整检查，再逐文件用临时文件替换并校验 SHA256。它不是四个工具整体的事务；中途发生磁盘或权限错误会停止，先前成功的文件可能已更新，请排查后重新 dry-run。同步前关闭正在使用相应工具的进程，并先测试将部署的源码。

维护流程：修改 OAS-Tools → 测试 → 查看 dry-run → 手动 -Apply → 验证 runtime → commit / push。也可以先 commit 再 Apply，不强制顺序；脚本不会自动进行 Git 写操作。

同步器安全测试使用临时人工 source/runtime：

```powershell
.\tests\test_sync_to_runtime.ps1
```

脚本支持 PowerShell 5.1+。`-SourceRoot`、`-RuntimeRoot` 是隔离测试参数；替代目录同样必须满足 OAS-Tools 与 scripts/utils 的相邻布局。`-PassThru` 可返回统计对象。首次真实检查仅执行 dry-run，没有应用同步。

首版 44 个复制文件保持原始字节，包括业务代码、BAT、PowerShell 和工具说明。原说明中的旧目录、验收日期与未随仓库分发的报告引用属于历史记录，不是新的运行路径。

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

首版镜像清单、隐私判断和验证结果见 [MIRROR_REPORT.md](MIRROR_REPORT.md)；其中“canonical source 另行决定”是首次镜像阶段的历史状态，当前维护模型以本 README 为准。
