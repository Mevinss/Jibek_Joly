"""OpenAI Responses adapter. Only the documented fixed endpoint receives credentials."""
import asyncio
import httpx
import logging
import time
from ..settings import settings
from .prompt import SYSTEM_PROMPT
from .tools import tool_schemas


class ProviderUnavailable(Exception):
    pass


async def respond(items, *, tools=True, fast=False, extra_instructions='', config=settings):
    started = time.perf_counter()
    if config.llm_provider != 'openai' or not config.llm_api_key.get_secret_value():
        raise ProviderUnavailable('provider_not_configured')
    body = {'model': config.llm_model_fast if fast else config.llm_model_chat,
            'input': items, 'instructions': SYSTEM_PROMPT + '\n' + extra_instructions,
            'max_output_tokens': 1600, 'store': False}
    if tools:
        body['tools'] = [dict(type='function', name=t['name'], description=t['description'],
                              parameters=t['input_schema'], strict=False) for t in tool_schemas()]
        body['parallel_tool_calls'] = False
    async with httpx.AsyncClient(timeout=25) as client:
        for attempt in range(2):
            try:
                r = await client.post('https://api.openai.com/v1/responses', json=body,
                                      headers={'Authorization': 'Bearer ' + config.llm_api_key.get_secret_value()})
                if (r.status_code == 429 or r.status_code >= 500) and attempt == 0:
                    await asyncio.sleep(.5)
                    continue
                if r.status_code != 200:
                    raise ProviderUnavailable(f'provider_http_{r.status_code}')
                result = r.json()
                if result.get('status') != 'completed':
                    raise ProviderUnavailable('provider_incomplete')
                usage = result.get('usage', {})
                logging.getLogger('ai.provider').info('response latency_ms=%.1f input_tokens=%s output_tokens=%s',
                    (time.perf_counter()-started)*1000, usage.get('input_tokens'), usage.get('output_tokens'))
                return result
            except httpx.HTTPError:
                if attempt: raise ProviderUnavailable('provider_network_error') from None
    raise ProviderUnavailable('provider_unavailable')


def output_text(result):
    return ''.join(part.get('text', '') for item in result.get('output', [])
                   if item.get('type') == 'message' for part in item.get('content', [])
                   if part.get('type') == 'output_text')
