"""Remove stale monetary rate claims from public prose, never contract data.

Runtime x-aisa-pricing and request quotes own prices. Upstream source bytes and
their review receipts remain intact; this is a public presentation transform.
Amounts describing payments, market data, examples or units are not API rates.
"""
from __future__ import annotations

import copy
import re
from decimal import Decimal, InvalidOperation

# Legacy markers. Mintlify shows an HTML comment in an OpenAPI description as
# literal text, so new summaries carry no marker; these are only stripped.
PRICE_BEGIN = '<!-- aisa-pricing:start -->'
PRICE_END = '<!-- aisa-pricing:end -->'
# A generated summary is the description's last paragraph. It always opens with
# one of these leads and closes with the settlement sentence of its language.
SUMMARY_LEADS = (
    'Published reference price: ', 'Default request estimate: ',
    'Usage-based billing; Default request estimate: ',
    'A request reference price is not currently available; ',
    '公开参考价格：', '默认请求预估费用：', '按用量计费；默认请求预估费用：', '当前未提供请求参考价格；',
)
SUMMARY_ENDS = ('Account-specific pricing and final settlement may differ.', '最终费用以账户适用价格及实际结算为准。')
SUMMARY = re.compile(
    r'(?:\A|\n[ \t]*\n)[ \t]*(?:' + '|'.join(map(re.escape, SUMMARY_LEADS)) + r')[^\n]*?(?:'
    + '|'.join(map(re.escape, SUMMARY_ENDS)) + r')\s*\Z')


def strip_price_summary(text):
    text = re.sub(r'\s*' + re.escape(PRICE_BEGIN) + r'.*?' + re.escape(PRICE_END), '', text, flags=re.S)
    while True:
        stripped = SUMMARY.sub('', text)
        if stripped == text:
            return text.strip()
        text = stripped


def usd(value):
    """Format a published JSON number without float arithmetic or guessing."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return '$' + (format(amount, 'f').rstrip('0').rstrip('.') if amount % 1 else format(amount, '.0f'))


# Contracts whose charge follows what the response consumes.
METERED = {'response_usd', 'response_count', 'response_sku', 'response_units', 'request_formula',
           'response_components', 'plan_units'}
# Readable names for declared billing units; other units show their words.
UNIT_NAMES = {
    'provider_credit': ('provider credit', '提供商额度'),
    'similarweb_credit': ('SimilarWeb credit', 'SimilarWeb 额度'),
    'firecrawl_credit': ('Firecrawl credit', 'Firecrawl 额度'),
    'tavily_credit': ('Tavily credit', 'Tavily 额度'),
    'akta_credit': ('Akta credit', 'Akta 额度'),
    'similar_creator_point': ('similar-creator point', '相似达人点数'),
    'email_lookup_point': ('email lookup point', '邮箱查询点数'),
}


def unit_name(unit, language='en'):
    if not isinstance(unit, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', unit):
        return None
    names = UNIT_NAMES.get(unit)
    if names:
        return names[1] if language == 'zh' else names[0]
    return unit.replace('_', ' ')


def pricing_summary(pricing, language='en'):
    """Render only declared prices; an estimate is never a unit or fixed price.

    The words follow the pricing guide: "Fixed per call" and "Metered".
    """
    if not isinstance(pricing, dict) or not pricing:
        return ''
    zh = language == 'zh'
    unavailable = pricing.get('reference_unavailable') or pricing.get('estimate_unavailable_reason') or pricing.get('estimate_source') == 'unavailable'
    estimate = None if unavailable else usd(pricing.get('default_request_estimate_usd'))
    fixed = pricing.get('customer_pricing') == 'fixed_success' or pricing.get('cost_contract') == 'fixed_success'
    if estimate is not None and fixed:
        return f'按次固定：每次成功请求 {estimate}。' if zh else f'Fixed per call: {estimate} per successful request.'
    rate = usd(pricing.get('unit_rate_usd'))
    unit = unit_name(pricing.get('unit'), language)
    metered = pricing.get('cost_contract') in METERED or (rate is not None and unit)
    if zh:
        per = ('每个' + (' ' if unit and unit[0].isascii() else '') + f'{unit} {rate}') if rate is not None and unit else ''
        about = f'参考请求约 {estimate}' if estimate is not None else ''
        if metered:
            detail = '，'.join(part for part in (per, about) if part)
            summary = '按量计费：' + detail + '。' if detail else '按量计费。'
        else:
            summary = about + '。' if about else ''
        if estimate is None:
            summary += '暂无参考价格，接口支持报价时请先获取报价。'
        return summary
    per = f'{rate} per {unit}' if rate is not None and unit else ''
    if metered:
        summary = f'Metered: {per}.' if per else 'Metered.'
        if estimate is not None:
            summary = (summary + f' A reference request costs about {estimate}.') if per else f'Metered: a reference request costs about {estimate}.'
    else:
        summary = f'A reference request costs about {estimate}.' if estimate is not None else ''
    if estimate is None:
        summary = (summary + ' ' if summary else '') + 'No reference price yet; get a quote first where the endpoint supports quotes.'
    return summary


def remove_price_summary(operation):
    """Keep prices out of the operation description.

    Mintlify shows the description under the page title, so a price there
    leads the page. The page's cost section shows the price instead
    (readable_contract_notes.readable_block).
    """
    description = strip_price_summary(operation.get('description', ''))
    if pricing_summary(operation.get('x-aisa-pricing')):
        description = description.replace(NOTICE, '').replace(NOTICE_ZH, '').strip()
    if description:
        operation['description'] = description
    else:
        operation.pop('description', None)
    return operation

MONEY = re.compile(r'(?:US)?\$\s*\d[\d,]*(?:\.\d+)?(?:\s*USD)?|\b\d[\d,]*(?:\.\d+)?\s*\$|\b\d+(?:\.\d+)?\s*(?:USD|美元|cents?)\b', re.I)
RATE = re.compile(
    r'\bbill(?:ed|ing|s)?\b|\bcharg(?:e|ed|es|ing)\b|\bpric(?:e|ing)\b|'
    r'\b(?:flat|rate|surcharge|upstream|per\s+(?:call|request|item|row|job|1M\s+tokens))\b|'
    r'\bat\s+\$|'
    r'/\s*(?:request|call|次)\b|计费|收费|每次|每请求', re.I)
NOTICE = 'For current API pricing, see the published x-aisa-pricing metadata. Where supported, obtain a quote for your exact request.'
NOTICE_ZH = '当前 API 价格请查看公开的 x-aisa-pricing 信息；接口支持报价时，请针对实际请求获取报价。'
# Examples and code are data, even when they happen to contain billing words.
FENCES = re.compile(r'(```[^\n]*\n.*?```|~~~[^\n]*\n.*?~~~|<pre\b[^>]*>.*?</pre>)', re.S | re.I)
PARTS = re.compile(r'(\n+|[;；](?![^()]*\))|(?<=[.!?。！？])\s+(?!\d)|<br\s*/?>|</?p\b[^>]*>|(?=\bNote:?)|(?<=false)(?=Note))', re.I)
NON_RATE = re.compile(r'products that cost|sort by|(?:minimum|maximum) price of|price per contract|price_centicents|YES at|NO at|shares redeem', re.I)
PRICE_PARENTHETICAL = re.compile(
    r'\(\s*(?:US)?\$\s*\d+(?:\.\d+)?(?:\s*/\s*(?:request|call)(?:[^()\n]*))?\s*\)', re.I)
CONDITIONAL_SURCHARGE = re.compile(
    r'\byou will be (?:charged|billed) (?:extra\s+)?(?:' + MONEY.pattern + r')(?:\s+extra)?', re.I)


def reconcile_free_claim(text, pricing):
    """A positive customer success price contradicts an unqualified Free claim."""
    if not isinstance(pricing, dict) or pricing.get('customer_pricing') != 'fixed_success':
        return text
    amount = usd(pricing.get('default_request_estimate_usd'))
    if amount is None or amount == '$0' or pricing.get('reference_unavailable'):
        return text
    # A standalone billing sentence/clause, never descriptions such as free text.
    return re.sub(r'(?:(?<=\.)|^)\s*Free(?=[.,;]|$)',
                  ' See the published pricing', text)


def clean_text(text: str, language: str = 'en', add_notice: bool = True) -> str:
    """Drop price clauses, retaining separate usage rules and non-price prose."""
    if not MONEY.search(text):
        return text
    notice = NOTICE_ZH if language == 'zh' else NOTICE
    chunks = FENCES.split(text)
    changed = False
    for index in range(0, len(chunks), 2):
        chunk = chunks[index]
        # Keep the model choice while removing its obsolete rate assertion.
        chunk, count = re.subn(r'(`[^`]+`) is billed at \$\d+(?:\.\d+)? per request\.', r'\1 is supported.', chunk)
        changed |= bool(count)
        # Preserve the condition that changes provider usage while removing its
        # stale monetary amount. This does not assert a customer surcharge.
        chunk, count = CONDITIONAL_SURCHARGE.subn('provider usage may increase', chunk)
        changed |= bool(count)
        parts = PARTS.split(chunk)
        for j in range(0, len(parts), 2):
            part = parts[j]
            if MONEY.search(part) and RATE.search(part) and not NON_RATE.search(part):
                # A usage sentence can end with a separate API-billing clause.
                # Keep its batch limit rather than deleting the complete line.
                usage = re.split(r',\s*this (?:interface|endpoint) charges\b', part, maxsplit=1, flags=re.I)
                if len(usage) == 2 and not MONEY.search(usage[0]):
                    parts[j] = usage[0].rstrip(' ,') + '.'
                    changed = True
                    continue
                variable = re.search(r'\bCharged by (.*?),\s*(?:' + MONEY.pattern + r')\s+per [^,;.]+,\s*(.+)', part, flags=re.I)
                if variable:
                    parts[j] = 'Provider usage depends on ' + variable[1] + '; ' + variable[2]
                    changed = True
                    continue
                # An API-rate parenthetical must not take its surrounding batch
                # limits or other caller instructions with it.
                without_rate, count = PRICE_PARENTHETICAL.subn('', part)
                if count and not MONEY.search(without_rate):
                    parts[j] = without_rate.rstrip()
                    changed = True
                    continue
                # A price-only bullet under a Price heading has its unit in the
                # same clause. Keep surrounding non-price bullets untouched.
                # Row limits are request rules, not monetary rates.
                limits = re.findall(r'\(up to \d+ rows; header row excluded\)', part)
                parts[j] = (' '.join(limits).strip('()') + '.') if limits else ''
                if j + 1 < len(parts) and parts[j + 1] in (';', '；'):
                    parts[j + 1] = ''
                changed = True
        chunks[index] = ''.join(parts)
    if not changed:
        return text
    result = ''.join(chunks)
    result = re.sub(r'(?m)^[ \t]*[;；][ \t]*', '', result)
    result = re.sub(r'(?m)^[ \t]*[-*][ \t]*$', '', result)
    result = re.sub(r'(?m)^#{1,6} (?:Price|Pricing)[ \t]*\n(?=\s*(?:#|$))', '', result)
    result = re.sub(r'\n{3,}', '\n\n', result).strip()
    if add_notice and notice not in result:
        result = (result + '\n\n' + notice).strip()
    return result


def place_notice(body: str, notice: str) -> str:
    """Put the page notice where the removed price line stood: before the first
    section heading outside code, never inside a component or glued to a fence."""
    if notice in body:
        return body
    chunks = FENCES.split(body)
    for index in range(0, len(chunks), 2):
        match = re.search(r'(?m)^#{2,6} ', chunks[index])
        if match:
            head, tail = chunks[index][:match.start()], chunks[index][match.start():]
            chunks[index] = head.rstrip('\n') + '\n\n' + notice + '\n\n' + tail
            return ''.join(chunks)
    return body.rstrip('\n') + '\n\n' + notice + '\n'


def clean_document(document: dict) -> dict:
    """Walk declaration objects without changing examples or extension metadata."""
    from compose_openapi import map_contract_children

    def walk(node):
        if isinstance(node, list):
            return [walk(child) for child in node]
        if not isinstance(node, dict):
            return copy.deepcopy(node)
        result = map_contract_children(node, walk)
        is_operation = isinstance(result.get('operationId'), str)
        if is_operation and isinstance(result.get('description'), str):
            result['description'] = strip_price_summary(result['description'])
            result['description'] = reconcile_free_claim(result['description'], result.get('x-aisa-pricing'))
        for field in ('description', 'summary', 'title'):
            if isinstance(result.get(field), str):
                result[field] = clean_text(result[field])
        if is_operation:
            remove_price_summary(result)
        return result

    # Paths and reusable declaration names are user-controlled map keys.
    output = walk({k: v for k, v in document.items() if k != 'paths'})
    if 'paths' in document:
        output['paths'] = {path: walk(item) for path, item in document['paths'].items()}
    return output


def clean_page(text: str, language: str = 'en') -> str:
    """Clean handwritten API-page prose before adding Runtime's managed block."""
    from runtime_localize_openapi_zh import split_frontmatter, frontmatter_value, replace_frontmatter_value
    from readable_contract_notes import strip_generated_block
    header, body = split_frontmatter(strip_generated_block(text))
    original = (header, body)
    for key in ('description', 'excerpt'):
        value = frontmatter_value(header, key)
        if value:
            updated = clean_text(value, language)
            if updated != value:
                header = replace_frontmatter_value(header, key, updated)
    # Preserve the useful section/parameter columns of handwritten rate tables.
    changed_prose = False
    chunks = FENCES.split(body)
    for index in range(0, len(chunks), 2):
        lines = chunks[index].splitlines(keepends=True)
        price_columns = []
        for i, line in enumerate(lines):
            if not line.lstrip().startswith('|'):
                price_columns = []
                continue
            cells = line.split('|')
            columns = [j for j, cell in enumerate(cells) if cell.strip().lower() in ('price', 'pricing', '计费', '价格')]
            if columns:
                price_columns = columns
            elif price_columns and MONEY.search(line):
                for j in price_columns:
                    if j < len(cells) and MONEY.search(cells[j]):
                        cells[j] = ' 见当前定价 ' if language == 'zh' else ' See current pricing '
                lines[i] = '|'.join(cells)
        prose = ''.join(lines)
        core = prose.strip()
        # A chunk sits between fences (for example `<CodeGroup>` before its
        # first block); keep its surrounding newlines so a fence stays on its own line.
        cleaned = clean_text(core, language, add_notice=False) if core else core
        if cleaned != core:
            changed_prose = True
            prose = prose[:len(prose) - len(prose.lstrip())] + cleaned + prose[len(prose.rstrip()):]
        chunks[index] = prose
    body = ''.join(chunks)
    if changed_prose:
        body = place_notice(body, NOTICE_ZH if language == 'zh' else NOTICE)
    if (header, body) == original:
        return text
    return '---\n' + header + '\n---\n' + body
