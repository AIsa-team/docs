"""Remove stale monetary rate claims from public prose, never contract data.

Runtime x-aisa-pricing and request quotes own prices. Upstream source bytes and
their review receipts remain intact; this is a public presentation transform.
Amounts describing payments, market data, examples or units are not API rates.
"""
from __future__ import annotations

import copy
import re
from decimal import Decimal, InvalidOperation

PRICE_BEGIN = '<!-- aisa-pricing:start -->'
PRICE_END = '<!-- aisa-pricing:end -->'


def strip_price_summary(text):
    return re.sub(r'\s*' + re.escape(PRICE_BEGIN) + r'.*?' + re.escape(PRICE_END), '', text, flags=re.S).strip()


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


def pricing_summary(pricing, language='en'):
    """Render only declared prices; an estimate is never a unit or fixed price."""
    if not isinstance(pricing, dict) or not pricing:
        return ''
    zh = language == 'zh'
    unavailable = pricing.get('reference_unavailable') or pricing.get('estimate_unavailable_reason') or pricing.get('estimate_source') == 'unavailable'
    estimate = None if unavailable else usd(pricing.get('default_request_estimate_usd'))
    fixed = pricing.get('customer_pricing') == 'fixed_success' or pricing.get('cost_contract') == 'fixed_success'
    if estimate is not None and fixed:
        summary = f'公开参考价格：每次成功请求 {estimate} USD。' if zh else f'Published reference price: {estimate} USD per successful request.'
    elif estimate is not None:
        summary = f'默认请求预估费用：{estimate} USD（不是固定价格）。' if zh else f'Default request estimate: {estimate} USD (not a fixed price).'
        if pricing.get('cost_contract') in {'response_usd', 'response_count', 'response_sku', 'response_units', 'request_formula', 'response_components', 'plan_units'}:
            summary = ('按用量计费；' if zh else 'Usage-based billing; ') + summary
    else:
        summary = '当前未提供请求参考价格；请使用接口支持的报价功能确认费用。' if zh else 'A request reference price is not currently available; use a request quote where supported.'
    rate = usd(pricing.get('unit_rate_usd'))
    unit = pricing.get('unit')
    if rate is not None and isinstance(unit, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', unit):
        summary += f' 声明的单位费率：每 {unit} {rate} USD。' if zh else f' Declared unit rate: {rate} USD per {unit}.'
    summary += ' 最终费用以账户适用价格及实际结算为准。' if zh else ' Account-specific pricing and final settlement may differ.'
    return summary


def add_price_summary(operation, language='en'):
    """Replace a generated paragraph on each run so price changes cannot stick."""
    description = strip_price_summary(operation.get('description', ''))
    summary = pricing_summary(operation.get('x-aisa-pricing'), language)
    if summary:
        description = description.replace(NOTICE, '').replace(NOTICE_ZH, '').strip()
        operation['description'] = (description + '\n\n' + PRICE_BEGIN + '\n' + summary + '\n' + PRICE_END).strip()
    elif 'description' in operation:
        operation['description'] = description
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


def clean_text(text: str, language: str = 'en') -> str:
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
    for index in range(0, len(chunks), 2):
        chunk = re.sub(r'(?m)^[ \t]*[;；][ \t]*', '', chunks[index])
        chunk = re.sub(r'(?m)^[ \t]*[-*][ \t]*$', '', chunk)
        chunk = re.sub(r'(?m)^#{1,6} (?:Price|Pricing)[ \t]*\n(?=\s*(?:#|$))', '', chunk)
        chunks[index] = re.sub(r'\n{3,}', '\n\n', chunk)
    result = ''.join(chunks).strip()
    if notice not in result:
        result = (result + '\n\n' + notice).strip()
    return result


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
            add_price_summary(result)
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
        chunks[index] = ''.join(lines)
    # Clean the complete body once so the notice cannot strip the newline
    # before a fenced example or become text inside a CodeGroup.
    body = clean_text(''.join(chunks), language)
    if (header, body) == original:
        return text
    return '---\n' + header + '\n---\n' + body
