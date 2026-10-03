"""Five conservative answers, separate for each source; no cross-source attribution."""
from dataclasses import asdict

from models import Answer, Issue

QUESTIONS = [
    "这段证据中正在执行什么任务？", "最后一次可靠观察到的页面是什么？",
    "最近一次动作是什么？", "已知为什么在等待吗？", "直接失败条件是什么？",
]
LABELS = {"confirmed": "已确认", "inferred": "推断", "unknown": "未知 / unknown"}


def latest(events, kinds):
    return next((e for e in reversed(events) if e.kind in kinds), None)


def five_answers(item):
    events = item.events
    answers = []
    scheduler = latest(events, {"task_start", "task_end"})
    subtask = next((e for e in reversed(events) if e.kind == "stat" and e.fields["ev"] in {"task_start", "task_end"}), None)
    module = latest(events, {"module"})
    context = latest(events, {"control_end"})
    refs = []
    texts = []
    statuses = []
    if scheduler:
        name = scheduler.fields["task"]
        texts.append(f"调度任务 {name}：{'有开始记录' if scheduler.kind == 'task_start' else '有调度结束记录'}")
        refs.append(scheduler.ref)
        statuses.append(scheduler.status)
    if subtask:
        name = subtask.fields.get("task") or "unknown"
        texts.append(f"最近 STAT 子任务 {name}：{subtask.fields['ev']}；ok={subtask.fields.get('ok', 'unknown')}")
        refs.append(subtask.ref)
        statuses.append(subtask.status if name != "unknown" else "unknown")
    if module:
        texts.append(f"最近动态模块指向 {module.fields['task']}（只证明加载入口记录）")
        refs.append(module.ref)
        statuses.append("inferred")
    if context:
        texts.append("出现 TaskEnd 控制流结束信号")
        refs.append(context.ref)
        statuses.append(context.status)
    if not refs:
        texts.append("任务 unknown：没有明确任务进入/结束记录")
    texts.append("业务目标成功 unknown；进程当前是否仍在执行 unknown；以上只描述窗口内最后记录")
    status = "unknown" if not refs or "unknown" in statuses else ("inferred" if "inferred" in statuses else "confirmed")
    answers.append(Answer(status, "；".join(texts), refs))

    page = next((e for e in reversed(events) if e.kind == "page" and e.status == "confirmed"), None)
    if page:
        after = events[events.index(page) + 1:]
        uncertain = any(e.kind in {"action", "page_plan", "page_unknown", "task_start", "start_block"}
                        or (e.kind == "stat" and e.fields["ev"] in {"acc_start", "switch_start", "run_start"}) for e in after)
        last_ts = max((e.ts for e in events if e.ts), default=None)
        aged = page.ts is not None and last_ts is not None and (last_ts - page.ts).total_seconds() > 60
        answers.append(Answer("confirmed", f"最后可靠页面观察：{page.fields['page']}，时间 {page.ts}；故障时/当前页面 unknown", [page.ref]))
        if uncertain or aged:
            item.issues.append(Issue("stale_page", "页面观察之后有动作/切换/边界或距最新证据超过60秒；不延用为故障页面（60秒仅为提示阈值）", page.ref))
    else:
        inferred_page = latest(events, {"page"})
        answers.append(Answer("unknown", "没有可靠页面观察；切页计划、路径和折行推断不证明已到达", [inferred_page.ref] if inferred_page else []))
    action = latest(events, {"action"})
    if action:
        target = action.fields.get("resource") or f"{action.fields.get('from')} -> {action.fields.get('to')}"
        answers.append(Answer(action.status, f"最近动作调用记录：{action.fields['kind']} @ {target}；只证明准备/尝试执行，后端发送/返回 unknown，游戏响应 unknown", [action.ref]))
    else:
        answers.append(Answer("unknown", "没有可识别的动作调用记录；动作和动作成功 unknown"))
    wait = latest(events, {"wait", "timeout"})
    if wait:
        reason = wait.fields.get("reason") or wait.fields.get("trigger")
        answers.append(Answer(wait.status, f"最近等待线索：{reason}，目标 {wait.fields.get('target', 'unknown')}，到期时间 {wait.fields.get('due', 'unknown')}，局部预算(s) {wait.fields.get('budget_s', 'unknown')}；当前是否仍等待和结束结果 unknown", [wait.ref]))
    else:
        answers.append(Answer("unknown", "没有明确等待线索；等待原因和当前是否在等待 unknown"))
    failure = next((e for e in reversed(events) if e.kind in {"exception", "timeout", "failure_condition"}
                    or (e.kind == "stat" and (e.fields["ev"] == "error" or (e.fields["ev"] == "task_end" and e.fields.get("ok") is False)))), None)
    if failure:
        trigger = failure.fields.get("exception") or failure.fields.get("etype") or failure.fields.get("trigger") or "STAT task_end(ok=False) / error"
        text = f"最近直接失败证据：{trigger}；条件 {failure.fields.get('trigger', 'unknown')}；只确认日志中的异常/超时/失败标记，根因 unknown；是否已局部处理或恢复 unknown"
        refs = [failure.ref]
        if not failure.fields.get("exception") and not failure.fields.get("etype"):
            typed = next((e for e in reversed(events) if e.kind == "exception" or
                          (e.kind == "stat" and e.fields["ev"] == "error" and e.fields.get("etype"))), None)
            if typed:
                text += f"；窗口内最近的具名异常记录 [{LABELS[typed.status]}] {typed.fields.get('exception') or typed.fields['etype']}，与上述标记的归属/因果关联 unknown"
                refs.append(typed.ref)
        answers.append(Answer(failure.status, text, refs))
    else:
        error = latest(events, {"error_signal", "traceback", "invalid_stat"})
        answers.append(Answer("unknown", "直接失败条件 unknown；缺少明确异常/超时/STAT 失败证据。TaskEnd 和调度 End 不作为失败或业务成功证明", [error.ref] if error else []))
    return answers


def check_boundaries(item):
    active = {}
    for event in item.events:
        if event.kind == "task_start":
            if "scheduler" in active:
                item.issues.append(Issue("missing_end", "新调度开始前未见上一任务结束；不伪造闭合", event.ref))
            active["scheduler"] = (event.fields["task"], event)
        elif event.kind == "task_end":
            previous = active.pop("scheduler", None)
            if not previous or previous[0] != event.fields["task"]:
                item.issues.append(Issue("boundary_conflict", "调度结束缺少匹配开始，或任务名冲突", event.ref))
        elif event.kind == "stat":
            ev = event.fields["ev"]
            for layer in ("run", "acc", "task"):
                if ev == layer + "_start":
                    if layer in active:
                        item.issues.append(Issue("missing_end", f"STAT {layer} 再次开始前未见结束", event.ref))
                    active[layer] = (event.fields.get("task"), event)
                elif ev == layer + "_end":
                    previous = active.pop(layer, None)
                    if previous is None or (layer == "task" and previous[0] != event.fields.get("task")):
                        item.issues.append(Issue("boundary_conflict", f"STAT {layer} 结束缺少匹配开始或名称冲突", event.ref))
        elif event.kind == "start_block":
            item.issues.append(Issue("start_not_session", "START 只为文件/读取边界；新进程/session unknown，跨日也不增加 session", event.ref))
    for layer, (_, event) in active.items():
        item.issues.append(Issue("missing_end", f"{layer} 开始后窗口内没有匹配结束；截断/仍运行/漏记均未确认", event.ref))


def build_report(files, windows, limits, root_label):
    sources = []
    groups = {}
    for item in files:
        if item.instance_candidate:
            groups.setdefault(item.instance_candidate.split("_", 1)[0], set()).add(item.instance_candidate)
    for item, window in zip(files, windows):
        check_boundaries(item)
        answers = five_answers(item)
        if item.package:
            item.issues.append(Issue("unknown_package_owner", "错误包实例/session/task-run 归属 unknown；不按名称或时间邻近绑定其他输入"))
        if item.instance_candidate and len(groups[item.instance_candidate.split("_", 1)[0]]) > 1:
            item.issues.append(Issue("ambiguous_instance", "所选名称按下划线归一化发生冲突；来源独立，稳定实例身份 unknown"))
        item.issues.append(Issue("identity_gap", "没有稳定 instance/session/task_run/frame/action/wait ID；不能合并为完整会话或证明因果链"))
        if any(e.kind == "exception" for e in item.events):
            item.issues.append(Issue("handled_unknown", "异常可能局部捕获后继续；时间邻近不能证明最近动作导致该异常"))
        item.issues = list({(i.code, i.detail, i.ref): i for i in item.issues}.values())
        sources.append({
            "path": item.path, "instance_candidate": item.instance_candidate,
            "instance_status": "inferred" if item.instance_candidate else "unknown",
            "package": item.package, "size": item.size, "read_bytes": item.read_bytes,
            "read_range": [item.read_start, item.read_start + item.read_bytes],
            "window": {"start": str(window[0]) if window[0] else None, "end": str(window[1]) if window[1] else None},
            "five_questions": [dict(question=q, **asdict(a)) for q, a in zip(QUESTIONS, answers)],
            "events": [asdict(e) | {"ts": str(e.ts) if e.ts else None} for e in item.events],
            "issues": [asdict(i) for i in item.issues], "image_refs": item.image_refs,
        })
    return {"version": "D1.1", "root": root_label, "limits": limits,
            "read_bytes": sum(item.read_bytes for item in files), "sources": sources,
            "policy": "本地只读；不同来源不合并；仅截至证据时点；root cause/business success/current live state unknown"}


def ref_label(ref):
    from models import Reference
    return Reference(**ref).label()


def safe_text(value):
    # Avoid log identifiers injecting Markdown structure; fields already allowlisted.
    return str(value).replace("\n", " ").replace("\r", " ").replace("`", "'").replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def describe(event):
    f = event["fields"]
    if event["kind"] == "stat":
        return f"STAT {f['ev']} task={f.get('task', 'unknown')} ok={f.get('ok', 'unknown')} etype={f.get('etype', 'unknown')}"
    if event["kind"] == "action":
        return f"{f['kind']} attempt @{f.get('resource', 'coordinates')}；执行/响应 unknown"
    if event["kind"] == "page":
        return f"页面观察 {f['page']}"
    return event["kind"] + " " + ", ".join(f"{k}={v}" for k, v in f.items())


def markdown(data):
    out = ["# OAS Diagnostic Assistant — D1", "", "## Analysis Scope", "",
           f"- 输入根：{safe_text(data['root'])}", f"- 限制：{safe_text(data['limits'])}；实际读取 {data['read_bytes']} bytes",
           "- 有界尾部快照，时间过滤只作用于已读证据；不是实时运行状态。不同来源分别分析，不能自动归属。",
           "- 未读图片；仅引用文件名。未导出账号/locals/原始异常消息；这不构成通用脱敏保证。"]
    for source in data["sources"]:
        out.append(f"- {safe_text(source['path'])}：size={source['size']}，read={source['read_range']}；窗口={source['window']}")
    out += ["", "## Execution Context", "", "稳定实例/session/task-run 身份 unknown；文件名仅为实例候选。"]
    for source in data["sources"]:
        out.append(f"- {safe_text(source['path'])}：候选={safe_text(source['instance_candidate'] or 'unknown')}；错误包={safe_text(source['package'] or 'none')}；业务成功 unknown")
    out += ["", "## Five Questions", ""]
    for source in data["sources"]:
        out += [f"### {safe_text(source['path'])}", ""]
        for number, answer in enumerate(source["five_questions"], 1):
            out += [f"{number}. **{answer['question']}** [{LABELS[answer['status']]}] {safe_text(answer['text'])}", ""]
            if answer["refs"]:
                out += ["   Evidence: " + "; ".join(safe_text(ref_label(r)) for r in answer["refs"]), ""]
    out += ["## Timeline", "", "保持每个来源的物理顺序；时间邻近不证明因果关系。", ""]
    for source in data["sources"]:
        meaningful = [e for e in source["events"] if e["kind"] != "unknown"]
        out.append(f"### {safe_text(source['path'])}")
        out.append("")
        # Bounded presentation only; complete parsed index is in JSON output.
        if len(meaningful) > 200:
            out.append(f"仅展示最后200/{len(meaningful)}条；完整事件索引可用 --format json 获取。")
        for e in meaningful[-200:]:
            out.append(f"- {e['ts'] or '时间 unknown'} [{LABELS[e['status']]}] {safe_text(describe(e))} — {safe_text(ref_label(e['ref']))}")
        if not meaningful:
            out.append("- unknown：窗口内没有可解释事件。")
    out += ["", "## Failure Trigger", "", "异常/超时/STAT失败标记是直接证据；根因 unknown，错误包归档成功和恢复成功 unknown。"]
    for source in data["sources"]:
        a = source["five_questions"][4]
        out.append(f"- {safe_text(source['path'])} [{LABELS[a['status']]}] {safe_text(a['text'])}" + (" — " + "; ".join(safe_text(ref_label(r)) for r in a["refs"]) if a["refs"] else ""))
    out += ["", "## Evidence", "", "引用字节范围为 UTF-8 原始文件的 [start,end)，行号为1起始物理行；源码行号与日志行号分别记录。"]
    for source in data["sources"]:
        out.append(f"- 输入：{safe_text(source['path'])}，错误包：{safe_text(source['package'] or 'none')}；read bytes={source['read_range']}")
        for e in source["events"][-200:]:
            out.append(f"- {safe_text(ref_label(e['ref']))}；{safe_text(e['source'] or 'source unknown')}:{e['source_line'] or '?'}；level={e['level'] or 'unknown'}；{e['kind']}")
        for image in source["image_refs"]:
            out.append(f"- 图片名称引用（未打开）：{safe_text(image)}；内容/与故障的关联 unknown")
    out += ["", "## Missing / Stale / Conflicting Evidence", ""]
    for source in data["sources"]:
        for issue in source["issues"]:
            out.append(f"- {safe_text(source['path'])} [{issue['code']}] {safe_text(issue['detail'])}" + (f" — {safe_text(ref_label(issue['ref']))}" if issue["ref"] else ""))
    out += ["", "## Suggested Next Observation", "",
            "- 人工核对明确指定的故障窗口及任务/子任务开始和结束记录；有字节缺口时，下一次明确指定更小来源或合适预算。",
            "- 下一次需要记录稳定实例/session/task-run 关联、页面观察时点、动作后端返回/异常及游戏响应证据。",
            "- 下一次需要记录等待目标、预算、结束原因，以及错误包实例归属与保存完整性；根因需独立证据核查。", ""]
    return "\n".join(out)
