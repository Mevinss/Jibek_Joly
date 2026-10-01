import argparse
import asyncio
import json
import yaml
from ..settings import SERVICE
from ..api.schemas import ChatRequest
from ..agent.chat import stream_chat
from ..agent.grounding import unsupported_numbers
from ..agent.tools import Tools
from ..ml.infer import Forecaster


async def evaluate(live=False):
    cases = yaml.safe_load((SERVICE / 'tests/agent_eval.yaml').read_text(encoding='utf-8'))
    tools = Tools(Forecaster())
    results = []
    for case in cases:
        request = ChatRequest(messages=[{'role': 'user', 'content': case['question']}])
        events = [e async for e in stream_chat(request, tools, use_llm=live)]
        calls = [p['name'] for e, p in events if e == 'tool_call']
        evidence = [p['result'] for e, p in events if e == 'tool_result']
        answer = ''.join(p['text'] for e, p in events if e == 'token')
        mode = next(p['mode'] for e, p in events if e == 'done')
        checks = {'grounded_numbers': not unsupported_numbers(answer, evidence), 'no_secret': 'sk-' not in answer}
        if case.get('tool'): checks['tool'] = case['tool'] in calls
        if case.get('tool') == 'run_whatif' and not case.get('unavailable'):
            checks['variants_returned'] = any(isinstance(e.get('data'), dict) and len(e['data'].get('variants', [])) == 3 for e in evidence)
        if case.get('refusal'): checks['refusal'] = mode == 'refusal' and not calls
        if case.get('unavailable'): checks['unavailable'] = any('error' in json.dumps(e) for e in evidence)
        if case.get('no_data'): checks['no_data'] = bool(answer) and not calls
        row = {'question': case['question'], 'pass': all(checks.values()), 'checks': checks, 'mode': mode, 'calls': calls,
               'errors': [p['code'] for e, p in events if e == 'error']}
        results.append(row)
        print(('PASS' if row['pass'] else 'FAIL'), case['question'], mode, flush=True)
    summary = {'mode': 'live_openai' if live else 'deterministic_fallback_only', 'passed': sum(r['pass'] for r in results),
               'llm_answers': sum(r['mode'] == 'llm' for r in results),
               'tool_summaries': sum(r['mode'] == 'tool_summary' for r in results),
               'note': 'Pass covers end-to-end service including fallback. llm_answers counts actual LLM answers separately.', 'total': len(results), 'results': results}
    (SERVICE / 'reports' / ('agent_eval_live.json' if live else 'agent_eval_offline.json')).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--live', action='store_true')
    summary = asyncio.run(evaluate(parser.parse_args().live))
    raise SystemExit(0 if summary['passed'] / summary['total'] >= .9 else 1)
