# OAS Diagnostic Assistant — D1 离线只读 MVP

完全本地、Python 标准库 CLI：规则解析 + 证据索引。没有 AI 模型、网络、OCR、GUI、数据库、服务或实时监控。不 import OAS 模块，不执行游戏操作，不修复代码。

## 长期工具登记

- 文件/工具名：`OAS_diagnostic_assistant`，目录内登记；没有修改 utils 总入口。
- 创建时间：2026-10-02；创建者/provider：Codex / OpenAI。
- 用途：对明确指定的有限日志证据回答任务、页面、动作、等待、失败五问。
- 保留原因：可重复使用的离线只读诊断工具，具有独立人工 fixture 和回归测试。
- 是否属于 OAS 正式项目：否；独立于 OAS Git 仓库，不修改业务或 STAT 协议。
- 删除条件：用户确认不再需要离线诊断工具，且需保留的人工报告已另行保存。
- 源码核查 HEAD：`76312b830f9597d917216c639f116152b098d755`；本轮 OAS 开始与结束工作区干净。

## 文件

| 文件 | 职责 |
|---|---|
| `main.py` | 独立 CLI、限制验证、输出 |
| `reader.py` | 固定输入白名单、有限尾部读取、图片文件名索引、防覆盖输出 |
| `models.py` | 文件、事件、证据引用、缺口、答案结构 |
| `parser.py` | 普通原始文件日志、Rich/STAT 有限折行、异常解析 |
| `report.py` | 五问、分来源时间线、完整性说明、Markdown/JSON 报告 |
| `tests/test_diagnostic.py` | 52 项独立工具测试，全部用人工数据 |
| `fixtures/sample_oas/` | 12 个人工脱敏日志文件，模拟10项必需场景及额外动作/等待 |
| `reports/D1_synthetic_demo.md` / `.json` | 人工 fixture 的示例报告与事件索引；不是历史运行结论 |

建议 Python 3.10 或以上。已用 Codex 自带 Python 运行；没有安装依赖。下面的示例可以使用任意可用 Python；也可将 `python` 替换为完整解释器路径。`-B` 避免生成工具的字节码缓存。

## 安全示例（仅人工 fixtures）

```powershell
Set-Location 'D:\Entertainment\Tool\scripts\utils\OAS_diagnostic_assistant'
python -B main.py --fixtures --log log/2026-10-02_backend.txt
python -B main.py --fixtures --log log/2026-10-02_plan.txt --start '2026-10-02T10:00:00' --end '2026-10-02T10:00:02'
python -B main.py --fixtures --error-package log/error/1790928000000 --format json
python -B -m unittest discover -s tests -v
```

不加 `--fixtures` 时只允许固定的 `D:\Entertainment\Tool\OAS` 根目录；没有任意 `--root` 参数。本轮没有使用真实日志模式。以后读取历史正文仍应遵守当次用户授权范围。

生产模式的参数形状：

```text
python -B main.py --log log/YYYY-MM-DD_<精确名称>.txt
  [--log log/YYYY-MM-DD_<另一个精确名称>.txt]
  [--start YYYY-MM-DDTHH:MM:SS --end YYYY-MM-DDTHH:MM:SS]
  [--error-package log/error/<纯时间戳或name_时间戳>]
  [--max-files 4 --max-bytes 2097152 --max-window-minutes 30]
  [--format markdown|json] [--output <工具reports目录内的新.md或.json文件>]
```

必须明确指定至少一个日志文件或一个错误包。时间窗口用于这些指定来源，不会只凭日期自动找实例或扫描历史。`--start/--end` 必须成对；采用原始 OAS 日志的完整本地日期时间，无时区偏移。不接受只有 GUI 时分秒的格式作为可靠时间证据。

## 读取与路径限制

- 仅允许 OAS 根目录下直接 `log/YYYY-MM-DD_<精确名称>.txt`，或明确错误包的 `log.txt`。禁止 config、worklog、handoff、其他项目、任意文本路径、递归扫描及通配选择。
- 拒绝路径越界、symlink、Windows junction/reparse 路径及硬链接文本；输入根和祖先路径同样检查。路径白名单防普通路径逃逸，不承诺抵御拥有本机写权限的攻击者在检查与打开之间替换路径。
- `--fixtures` 是唯一替代根，只能读工具自带 `fixtures/sample_oas`；没有任意测试根 CLI 入口。
- 默认最多4个文本来源，实际读取总预算2MiB，分析窗口30分钟；可调硬上限分别为16个、16MiB、1440分钟。错误包 `log.txt` 也计入文件预算，缺失时仍保留该来源位置。
- 读取预算平均分给明确指定的文件，从各文件尾部读取一次。实际读取计入预算，**不为搜索时间窗口或统计行号额外读头部**。小预算可能丢失目标窗口；报告如实写缺口，不自动扩大读取。
- 显式时间窗口只过滤已经有界读取的片段；默认各来源采用该片段内最新可解析时间向前至最大窗口。多个来源分别计算，不建立全局会话顺序。
- 非文件起点读取时丢弃可能不完整的首行，用原始 byte offset 引用；从起点读取时提供1起始物理行号。字节区间统一为 `[start,end)`，包括原始换行。
- 每个片段最多解释最后20000物理行，单行超过64KiB则不解释；剩余为明确缺口。最多拼接8条 STAT/普通续行；traceback 块最多512条后续物理行。所有限制与缺口均保守处理。
- 错误包只枚举指定目录内最多256条元数据记录。PNG只引用名称，从不打开/解码图片，不读取 manifest 或其他附带文件。
- 默认只向 stdout 输出。保存报告只能创建工具 `reports/` 内的新文件，后缀需匹配格式；独占创建，不覆盖原有报告，不写源日志、错误包或 OAS 文件。退出码0为报告生成成功，2为参数、路径或 I/O 被拒绝；0不表示业务成功。

## 解析证据

支持原始 `完整日期毫秒 | 文件名:源码行号 | level | 消息`；保留时间、源码调用点、level、日志行号/byte offset。源码行号与日志行号分别记录。

- START三行块、跨日滚动提示、Scheduler Start/End、动态 `tasks/<任务>/script_task.py` 入口、TaskEnd。
- `[STAT]` JSON 的 `ev`，run/acc/task 开始与结束、error，以及其他事件类型索引；仅输出白名单 task、etype、真实布尔 ok、dur 和身份字段是否存在。不把 `run_end` 当作整轮成功，不把 `ok=true` 提升为业务目标成功。
- `[UI]`、Current page、Page arrived（含耗时前缀）、Page switch 与 Following shortest path 的计划标记。
- control.py 的 Click/long_click、Swipe/Drag 调用记录。只证明准备/尝试执行，发送、后端返回和游戏响应始终 unknown。
- 调度到期等待、Waiting for、等待按钮出现、位置稳定、detect_record集合、常见目标/导航/stable超时、Wait too long；已明示的目标/到期时间/导航局部预算可输出，其余 unknown。
- 纯文本与 Rich traceback 块、框外终止异常、OAS已知异常类型，以及少量明确失败条件白名单。不读取或输出 traceback locals，不从框内文本补造页面、动作或异常。
- 普通Rich折行与历史STAT结构性折行按 `inferred`，坏JSON、重复键、NaN、非法字段、半条、字符串中途折行、坏UTF-8及未知行均不终止其他证据解析。

页面/动作/导航日志要求对应真实调用点文件名（game_ui.py / control.py）；同样文字出现在其他模块或 traceback locals 不作为观测证据。资源/任务/页面名称使用有限标识符白名单，不能识别的形式宁可 unknown。

## 五问与可信度

每个来源分别输出五问，答案状态为 `confirmed`（已确认）、`inferred`（推断）、`unknown`（未知）；指的是证据支持的**记录事实**，不是对游戏状态的保证。

| 问题 | 判断 | 不会推断的部分 |
|---|---|---|
| 什么任务？ | 最近调度边界、STAT子任务边界、动态模块入口、TaskEnd；明确展示结束记录 | 当前仍在运行、完整嵌套调用栈、业务目标成功 |
| 最后页面？ | 最后完整且可靠的UI/Current page/Page arrived观察 | 计划目标已到达、折行页面一定可靠、故障时仍在旧页面 |
| 最近动作？ | 最近可识别的动作调用、资源名/坐标，附位置 | 成功点击、后端发送/返回、真实游戏响应 |
| 为何等待？ | 最近显式等待线索、目标、到期时间与已记录预算 | 当前等待仍有效、隐式节奏/限流、缺失等待结束 |
| 直接失败？ | 最新明确异常、超时、失败条件或STAT error/task_end(ok=false) | 根因、时间邻近即因果、异常必然未处理、恢复成功 |

重要结论有行号或byte offset引用。页面后有动作、切换、未识别记录、作用域边界，或与最新证据相隔超过60秒时提醒 stale；60秒仅为诊断提示阈值，**不是OAS超时SLA**。无论是否提示，故障时/当前页面都不从旧观察延用。

时间倒退、结束无匹配开始、重复开始无结束、窗口/预算截断、未知行、错误包无归属、所选精确实例名按下划线归一化冲突均单列。START不生成历史 session ID；错误包和普通日志始终独立分析，不凭名称或时间自动关联。同一文件名也不能证明同一进程。

## 输出

Markdown固定8节：Analysis Scope、Execution Context、Five Questions、Timeline、Failure Trigger、Evidence、Missing / Stale / Conflicting Evidence、Suggested Next Observation。

JSON输出相同诊断语义、完整的受限解析事件索引及每条引用；未知行只保留位置，不复制原始文本。Markdown时间线及索引展示最多最后200条，各问题的重要证据仍独立引用。Suggested Next Observation仅建议下一次记录或人工检查，不包含自动修复。

为减少无关暴露，不输出账号/角色/区服值、emsg、原始未知消息或locals。白名单名称和路径本身仍可能包含用户信息；这不是通用脱敏器，报告默认只保留在本地，不自动上传。

## 验证与限制

12个持久人工日志fixture覆盖：正常结束、准备切页未到达、Click后后端异常、TaskEnd但子任务失败、STAT折行、坏JSON、突然截断、跨日START、无实例错误包、下划线归一化歧义，以及额外动作/等待。图片测试只创建人工名称占位，不使用真实截图；另有临时人工样例测试半行、坏编码、超长行、链接逃逸、防覆盖等。

52项 unittest 全部通过，无跳过；测试不会读取真实历史日志、账号配置或真实截图。首轮曾发现Rich框内locals异常误判，已修复并保留回归测试。保存测试的临时输出目录使用测试专属临时根，不写生产目录。测试临时文件自动清理。

本轮只读指定源码与审计文档，未读取任何真实历史日志正文，未打开历史截图，未启动OAS/游戏/OCR/server，未上传。未修改OAS正式代码/STAT协议/历史错误包，也未写worklog/handoff；未commit/push/创建PR。

尚缺：真实日志格式的有限授权验收、旧Rich字符串折行无损恢复、通用局部Scene/业务阶段识别、完整等待结束/动作结果、精确实例/session/task-run关联、跨文件上下文拼接、错误包归属与保存完整性。当前工具不自动回翻老窗口；字节预算不足时明确unknown。

**目前无需直接进入D2。** 先在后续明确授权的少量脱敏证据上验收D1，统计五问的实际缺口；若反复卡在动作结果或执行关联，再单独申请D2少量默认关闭的观测点。D2会涉及业务边界，不能由本工具自动实施。
# D1.1 / D1.2 更新（2026-10-02）

严格 `[UI] <identifier>` 页面观察允许 `game_ui.py` 和 `logger.py` 来源；其他来源、额外文本、非法或超长标识均不作为页面观察。Click 仍只证明尝试，Page switch 仍为计划，过去的页面不能作为故障时页面。

## catalog：先找候选文件

在本工具目录运行（Python 标准库，不导入 OAS）：

```powershell
python main.py catalog --date 2026-09-27
python main.py catalog --date 2026-09-27 --instance 桌面版 --keyword 契灵 --start 2026-09-27T19:01:30 --end 2026-09-27T19:03:30
python main.py catalog --date-from 2026-09-26 --date-to 2026-09-28 --keyword Bondling --max-candidates 16 --per-file-bytes 65536 --total-bytes 262144
```

默认 stdout 为 JSON；可加 `--output D:\Entertainment\Tool\scripts\utils\OAS_diagnostic_assistant\reports\NEW_NAME.json`，只创建新文件，禁止覆盖。`--log-root` 必须精确指向固定 OAS/log；不能用于其他项目、配置或维护记录。`--fixtures --log-root <本工具 fixtures/sample_oas/log 的绝对路径>` 仅用于 synthetic 验证。

默认：最多 16 个候选、每文件 64KiB、总计 256KiB；硬上限分别为 64 个、256KiB、4MiB。最多枚举 4096 个直属目录项，按文件名倒序确定候选，不递归。`omitted_candidates` 表示因候选上限未检查的数量；`enumeration_limited` 表示目录枚举不完整。预算耗尽时后续候选保留元数据，正文线索 unknown。候选排序将实际命中关键词的文件置前；关键词未命中的抽样文件保留为 unknown，不能据此排除。

大文件只抽样头尾和分散位置；指定时间时使用最多 12 次小块定位和有预算的局部读取。定位假设时间戳大致顺序，**不能验证未读区域的时间顺序或排除隐藏事件**。小文件仅在单文件/剩余总预算允许时完整读取。所有实际读取（包括重复定位）计入预算，分片独立解析，不能跨未读空洞拼接 STAT 或 traceback。

输出解释：

- `filename_instance` confirmed：文件名标签；`instance` inferred：实例归属候选，不是已验证的进程/session。实例名精确比较，不归一化下划线。
- `visible_time_range` confirmed：抽样中观察到的时间戳范围，附原始 byte offset；`actual_run_range` unknown：不据文件日期、START 推断完整运行。
- `task_clues`：Scheduler、动态模块、STAT 和严格 `battle.py / Current tasks:` 标签线索；仅确认记录存在，不确认执行结果。
- `start_clues`：START 块只证明分隔块存在，跨日 START 不等于新进程。
- `failure_markers/count`：仅已读片段的异常/超时/ERROR/STAT 失败标记；不是全文件数量、独立异常次数或根因。没有标记且未完整读取时，其他区域的失败 unknown。
- `failure_presence`：已观察到标记时 confirmed true；仅完整读取且文本没有坏UTF-8或截断时可输出 confirmed false，否则 unknown。样本标记数量0不能替代此字段。
- `keyword` confirmed true：请求时间内的已读带时间戳消息命中。confirmed false 仅在正文完整读取后针对所选窗口成立；否则 unknown。关键词命中不自动变成任务归属。
- 时间参数均为无时区的 OAS 本地完整日期时间，必须成对且不超过 24 小时。日期筛选按文件名日期；跨日运行可能需要扩大日期筛选。

`--include-errors` 只枚举 `log/error` 包名元数据，在候选上限内列出；不读 log.txt、不遍历截图、不按时间强行关联。所有包的 `instance` 和 `possible_related_log` 当前均 unknown，命名中的实例标签也不被当作已证实关联。日期/实例/时间筛选仅针对普通日志，错误包元数据列表不应用这些筛选。普通日志用完候选名额时不会列出错误包。

此功能可降低“记不住哪个文件”的负担，但它是候选发现，不是完整运行索引。抽样未命中、预算耗尽、缺少调度边界或纯时间戳错误包仍可能无法归属；明确日期/实例/时间能提高命中率。原诊断 CLI 的尾部读取行为没有改变，严格旧窗口验收仍使用明确 byte 区间交给 parser/report，不能把 catalog 当成全窗口读取保证。
