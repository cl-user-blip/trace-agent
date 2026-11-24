from __future__ import annotations

import html
import json
from pathlib import Path


STYLE = """
:root{font-family:Inter,'Segoe UI','Microsoft YaHei',sans-serif;color:#dce5f1;background:#0c1323}
*{box-sizing:border-box}body{margin:0}main{max-width:1120px;margin:auto;padding:60px 34px}
.eyebrow{letter-spacing:3px;font-size:12px;color:#5de4c7}h1{font-size:clamp(32px,5vw,58px);letter-spacing:-2px;margin:14px 0}h2{font-size:24px;margin-top:34px}
p{color:#a7b8ce;line-height:1.8}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:32px 0}
.card,.panel{background:#141f32;border:1px solid #29384e;border-radius:14px;padding:22px}.card strong{display:block;font-size:32px;color:#fff;margin-top:12px}
.badge{padding:6px 10px;background:#174c47;border-radius:18px;color:#76f0d1;font-size:12px}pre{white-space:pre-wrap;word-break:break-word;line-height:1.65;font-size:13px}
details{border-left:2px solid #3d5a75;margin:12px 0;padding:12px 20px;background:#101a2c}summary{cursor:pointer;font-weight:600}summary small{color:#8ba4bd;margin-left:14px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:14px 10px;border-bottom:1px solid #29384e;font-size:14px}th{color:#72dfc5}
footer{color:#7188a3;margin-top:42px;font-size:12px}a{color:#76e0cc}.pass{color:#70e2be}.fail{color:#ffaf9b}
"""


def shell(title, body):
    return f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{STYLE}</style><main>{body}<footer>TRACE AGENT · Original synthetic fixtures · Offline rule simulator · No live LLM evaluation</footer></main></html>'


def public_state(state):
    clean = dict(state)
    clean["knowledge_root"] = "<knowledge-root>"
    return clean


def export_trace(store, state, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    events = store.events(state["id"])
    payload = {"state": public_state(state), "events": events}
    (out / "trace.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    esc = html.escape
    timeline = "".join(
        f'<details><summary>{i+1:02d} · {esc(e["kind"])}<small>{esc(e["time"][11:23])} UTC</small></summary><pre>{esc(json.dumps(e["payload"],ensure_ascii=False,indent=2))}</pre></details>'
        for i, e in enumerate(events))
    body = f'''<div class="eyebrow">DURABLE AGENT RUNTIME / TRACE VIEWER</div><h1>每一步，都可以追踪。</h1>
<p>本次运行使用 <span class="badge">{esc(state['provider'])}</span> 策略。状态、工具参数、重试与引用均写入 SQLite journal。</p>
<div class="cards"><div class="card">STATE<strong>{esc(state['status'])}</strong></div><div class="card">DECISIONS<strong>{state['decisions']}</strong></div><div class="card">TOOL ATTEMPTS<strong>{state['attempts']}</strong></div><div class="card">EVENTS<strong>{len(events)}</strong></div></div>
<h2>任务与结果</h2><div class="panel"><p>{esc(state['task'])}</p><pre>{esc(state.get('answer') or state.get('error') or '运行已暂停，可从检查点继续。')}</pre></div>
<h2>完整执行轨迹</h2><p>点击事件查看真实参数和观测结果；此视图不展示模型隐藏推理。</p>{timeline}'''
    (out / "index.html").write_text(shell("Trace Agent · Execution Trace", body), encoding="utf-8")
    return out / "index.html"


def export_eval(report, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = "".join(f'<tr><td>{html.escape(c["name"])}</td><td>{html.escape(c["purpose"])}</td><td class="{"pass" if c["passed"] else "fail"}">{"PASS" if c["passed"] else "FAIL"}</td><td>{html.escape(str(c["observed"]))}</td></tr>' for c in report["cases"])
    body = f'''<div class="eyebrow">REPRODUCIBLE FAILURE EVALUATION / OFFLINE</div><h1>从正常路径到故障恢复。</h1>
<p>在原创微型知识库上验证工程语义，不代表通用 Agent 的智能水平。所有数字来自执行断言。</p>
<div class="cards"><div class="card">CASES PASSED<strong>{report['passed']} / {report['total']}</strong></div><div class="card">PROVIDER<strong>Offline</strong></div><div class="card">LIVE API CALLS<strong>0</strong></div></div>
<div class="panel"><table><thead><tr><th>案例</th><th>验证目标</th><th>结果</th><th>实际观测</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>如何理解结果</h2><p>通过率只针对这些固定案例。工具边界测试、恢复语义和重试测试与离线抽取问答分开计分。未衡量真实模型的幻觉率、任务泛化或线上延迟。</p>'''
    (out / "index.html").write_text(shell("Trace Agent · Evaluation", body), encoding="utf-8")
