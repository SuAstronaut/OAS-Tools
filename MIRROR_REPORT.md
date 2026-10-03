# OAS-Tools 首版镜像报告

本轮采用 COPY / MIRROR。正式使用位置仍为 `D:\Entertainment\Tool\scripts\utils\`，新目录为 `D:\Entertainment\Tool\OAS-Tools`。开始时新目录不存在；没有覆盖既有项目。OAS-Tools 是独立工具集合，不是 OAS 的运行时依赖。

此报告记录提交前的白名单与验证结果。最终 Git HEAD、远端创建结果及 PRIVATE 状态以交付摘要中的实际核验为准。远端目标是当前登录账号下的 OAS-Tools，必须私有。

## 复制白名单

44 个原文件，共 299,297 字节；复制前后逐文件 SHA-256 相同。没有修改复制文件的业务逻辑、路径、入口或换行。

| 新目录 | 原目录（位于 scripts/utils） | 原样复制内容 |
|---|---|---|
| tools/diagnostic_assistant | OAS_diagnostic_assistant | catalog.py、main.py、models.py、parser.py、reader.py、report.py、README.md；tests/test_catalog.py、tests/test_diagnostic.py；fixtures 下 13 个人工 TXT |
| tools/click_analyzer | OAS_click_analyzer | core.js、app.js、style.css、index.template.html、build.js、preview.js、test.js、validate-local.js、README.md、验证说明.md、点击分布分析器.html |
| tools/excel_importer | OAS_excel_importer | main.py、core.py、launcher.ps1、启动.bat、README.md、settings.example.json、OAS账号导入模板.xlsx |
| tools/account_order_fixer | OAS_account_order_fixer | main.py、tests.py、README.md、启动.bat |

新增文件仅为根 README.md、.gitignore、本报告，以及两个测试文件：`tools/account_order_fixer/tests_mirror.py`、`tools/excel_importer/tests/test_mirror.py`。共 49 个拟提交文件，没有复制嵌套 Git 历史。

```text
OAS-Tools/
├─ README.md
├─ .gitignore
├─ MIRROR_REPORT.md
└─ tools/
   ├─ diagnostic_assistant/  # 22 原文件，含 tests 与 fixtures
   ├─ click_analyzer/        # 11 原文件，含单文件 HTML 交付物
   ├─ excel_importer/        # 7 原文件 + 1 新合成测试
   └─ account_order_fixer/   # 4 原文件 + 1 新测试隔离入口
```

## 明确排除

- 四个原工具中的 backup、settings.json、缓存、临时输出、运行输出均未复制。
- Diagnostic Assistant 的 7 个报告全部未复制。真实报告和来源不明报告排除；带 synthetic 名称的旧 D1 报告也含本机绝对根路径，首版同样排除。
- Click Analyzer 的 examples 与真实日志验收.json 未复制；单文件 HTML 则作为正式交付物保留。
- 原 Excel `tests/run_tests.py` 未复制，具体隐私发现见下表；新增测试只使用人工数据。
- OAS_coop_statistics、OAS_patch_installer、OAS_local_patch、旧 updater/candidate 仓库、scripts/test 完全未处理，没有修改、删除或归档。
- 没有复制 OAS/config、真实账号 Excel、真实协作 CSV 或实际 OAS 日志。

## 隐私复查

在 Git 初始化和暂存之前，扫描白名单文件中的本机路径、账号/邮箱/角色、token/password/cookie/API key/secret/webhook，并检查 GitHub token、私钥和常见密钥格式。另从原两个操作工具备份中只读提取账号、角色等值，在内存中交叉比对拟提交文件，不输出这些实际值。163 个实际账号/角色等标识在最终白名单文本中匹配数为 0。

| 文件及行号（原目录为 scripts/utils） | 类型 | 风险及处理 |
|---|---|---|
| OAS_excel_importer/tests/run_tests.py:83、96、100、154、161、162、236、362、363、369、370 | 与实际备份角色值重合，值 `<redacted>` | BLOCKED_FROM_GIT；不复制、不改原文件，新增完全人工的测试 |
| tools/account_order_fixer/启动.bat:6；tools/diagnostic_assistant/reader.py:13 | 本机 OAS / Python 绝对路径 | LOCAL_PATH，低风险路径兼容信息；保留原字节，只进入私有仓库 |
| tools/account_order_fixer/README.md:3、7、12、15、40；tools/click_analyzer/README.md:18、75；tools/diagnostic_assistant/README.md:33、40、131；tools/excel_importer/README.md:16、21、50、51、52、56、75、113、115 | 历史本机路径与使用示例 | LOCAL_PATH，低风险；保留原文。历史路径和未复制报告链接不代表已切换运行入口 |
| tools/click_analyzer/test.js:9 | 人工邮箱 example.test | 合成测试数据；与实际账号不匹配 |
| tools/diagnostic_assistant/tests/test_diagnostic.py:256–263；tests/test_catalog.py:142–143 | SECRET_* 等防泄漏测试标记 | 人工测试字符串，不是凭据 |

扫描没有发现实际 token、密码、cookie、私钥或 webhook 凭据。字段名、关键字和人工测试标记不能等同于真实秘密；逐项查看上下文后保留。根说明和本报告中的本机工具路径也是明确的目录记录。

Excel 模板再次检查了 ZIP 内容和全部 sheet XML：第一张表仅有 6 个表头（系统、位置、邮箱、名称、区服、羁绊情况）；第二张表是使用说明。没有账号行，没有 hidden sheet、defined names、作者 metadata 或外部连接，适合原样复制。

.gitignore 精确排除本机 settings、backup、output、缓存、实际报告和点击验收结果；保留 settings.example.json、人工 TXT fixtures 与单文件 HTML。synthetic reports / examples 预留独立命名空间，不使用整个 reports/ 的全局忽略规则。未来新增文件仍需独立隐私审查。

## 路径与行为

原工具和副本目录深度相同。Account Order Fixer 从 `__file__` 上推三层，在当前同级布局下仍得到 `D:\Entertainment\Tool`，默认配置根仍为 OAS/config。BAT 使用原 OAS toolkit Python，但执行当前 BAT 所在目录的 main.py。没有改原入口，也没有运行真实配置的写入流程。

Excel 复制版没有 settings.json。launcher 会在用户实际使用时选择 OAS 根，创建副本自己的本机 settings；它的 backup 仍由自己的 core.py 路径定位。该 GUI/launcher 本轮未启动，PowerShell 只做语法解析。

Diagnostic Assistant 保留原生产 OAS 根；本轮显式使用副本 fixtures 测试，不读取真实日志。默认报告路径位于副本目录。Click Analyzer 单文件 HTML 与用当前 JS/CSS/template 在内存生成的内容完全相同，没有重写交付 HTML，也没有运行真实日志验收脚本。

这是本机可兼容的一次性镜像，尚未承诺任意机器直接双击运行。不做 shared/src/packages/framework/docker、插件系统或顺便重构。

## 验证结果

| 工具 | 状态 | 证据 |
|---|---|---|
| Account Order Fixer | PASS | 原 7 项测试在新测试入口中被隔离到人工临时配置；另验证取消和 YES 确认，共 9 项检查通过。预览、备份原字节、原子写入、写后验证正常；取消不写配置、不产备份 |
| Excel Importer | PASS | 新增 9 项标准库 unittest 通过：解析、顺序、空系统继承、非法羁绊、计划不改输入、新增账号、阻止缩减、模板、临时 XLSX、临时导入及备份、保留未知字段与保存失败隔离 |
| Diagnostic Assistant | PASS | 原 70 项 unittest 通过，无跳过；--help 正常；显式 fixture 根 catalog 读取 6,536 字节，按日期选择 12 个人工日志；parser、report 等由测试覆盖 |
| Click Analyzer | PASS | 原 test.js 的 15 项测试通过；6 个 JS 文件语法检查通过；单文件 HTML 与源码内存生成结果相同；本地浏览器演示提取 240 次点击，散点/热力/时间轨迹可切换，09:01:00–09:01:30 筛出 31 条，无浏览器 error/warn |
| Excel 原 tests/run_tests.py | SKIPPED_FOR_SAFETY | 含实际角色值重合，且原写入测试不适合作为原目录直接运行验证；没有执行，使用新增人工数据测试 |
| Click validate-local.js / 真实日志验收 | SKIPPED_FOR_SAFETY | 会读取真实日志并写验收文件；未执行，使用纯人工演示及原 JS 单元测试 |

所有写入测试仅针对临时目录、人工配置；没有把真实 OAS/config 或原 backup 当作写入目标。Python 使用 -B，未安装依赖。

浏览器测试发现一个既有轻微显示问题：时间格式错误后改为合法值，统计会正常更新，但旧“无法分析”提示保留；重新加载演示可清除。本轮不改副本代码，留待后续维护。

## 原目录保护与后续

本轮开始时 scripts 全目录基线：13,488 个文件，509,172,801 字节。按排序相对路径和逐文件内容 SHA-256 汇总的摘要为 `a2079667fa2bd6a2660be08c5feb319384836b02f9fc6a4ea88dc9cc63fcf35e`；提交前/交付前复算作为原目录完整性检查。没有对原目录调用编辑、移动、删除或格式化操作。

OAS 的原有工作区改动只读记录：dev_tools/test_scheduler_shortcuts.py、module/server/log_stats.py 已修改；dev_tools/test_log_stats_execution_time.py 未跟踪。本轮不处理它们，不改 OAS Git、配置或工作日志。

LICENSE_PENDING：没有自行添加 MIT 或其他许可证。来源与许可另行核实。

后续建议将 OAS-Tools 作为 canonical source，再让旧 scripts 路径只负责启动；具体切换需下一轮决定和验证。本轮不切换、不建 symlink/junction、不建立自动同步、不创建计划任务，也不自动覆盖原工具。
