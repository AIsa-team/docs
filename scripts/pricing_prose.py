"""Remove stale monetary rate claims from public prose, never contract data.

Runtime x-aisa-pricing and request quotes own prices. Upstream source bytes and
their review receipts remain intact; this is a public presentation transform.
Amounts describing payments, market data, examples or units are not API rates.
"""
from __future__ import annotations

import copy
import re
from customer_price_presentation import pricing_summary, usd

PRICE_BEGIN = '<!-- aisa-pricing:start -->'
PRICE_END = '<!-- aisa-pricing:end -->'


def strip_price_summary(text):
    return re.sub(r'\s*' + re.escape(PRICE_BEGIN) + r'.*?' + re.escape(PRICE_END), '', text, flags=re.S).strip()


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
NOTICE = 'See Pricing for current prices. Where supported, get a quote for your request.'
NOTICE_ZH = '当前价格请查看费用说明；支持报价的接口可按实际请求获取报价。'
OLD_NOTICE = 'For current API pricing, see the published x-aisa-pricing metadata. Where supported, obtain a quote for your exact request.'
OLD_NOTICE_ZH = '当前 API 价格请查看公开的 x-aisa-pricing 信息；接口支持报价时，请针对实际请求获取报价。'
# Examples and code are data, even when they happen to contain billing words.
FENCES = re.compile(r'(```[^\n]*\n.*?```|~~~[^\n]*\n.*?~~~|<pre\b[^>]*>.*?</pre>)', re.S | re.I)
PARTS = re.compile(r'(\n+|[;；](?![^()]*\))|(?<=[.!?。！？])\s+(?!\d)|<br\s*/?>|</?p\b[^>]*>|(?=\bNote:?)|(?<=false)(?=Note))', re.I)
NON_RATE = re.compile(r'products that cost|sort by|(?:minimum|maximum) price of|price per contract|price_centicents|YES at|NO at|shares redeem', re.I)
# The space before the parenthetical goes with it, so no "item ." remains.
PRICE_PARENTHETICAL = re.compile(
    r'[ \t]*\(\s*(?:US)?\$\s*\d+(?:\.\d+)?(?:\s*/\s*(?:request|call)(?:[^()\n]*))?\s*\)', re.I)
# A sentence (single line breaks allowed) saying a request is charged or billed once.
UPSTREAM_ONCE_SENTENCE = re.compile(
    r'(?<![^\s])(?=[^\s.!?])(?:[^.!?\n]|\n(?!\n))*?\b(?:charged|billed)\s+(?:only\s+)?once\b[^.!?\n]*[.!?]', re.I)


def drop_upstream_once(chunk):
    """Drop each such sentence with the spacing on one side of it."""
    count = 0
    while match := UPSTREAM_ONCE_SENTENCE.search(chunk):
        begin, end = match.span()
        after = re.match(r'[ \t]+(?=\S)', chunk[end:])
        if after:
            end += after.end()
        else:
            begin = len(chunk[:begin].rstrip(' \t'))
        chunk = chunk[:begin] + chunk[end:]
        count += 1
    return chunk, count


# A sentence that is only a billing statement once its amount is removed.
BILLING_ONLY = re.compile(r'\W*(?:billed|charged|priced)\b', re.I)
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
    # Notices from earlier generators must also refresh when they have no
    # monetary literal. Fenced examples remain data, as with rate cleanup.
    if OLD_NOTICE in text or OLD_NOTICE_ZH in text:
        chunks = FENCES.split(text)
        for index in range(0, len(chunks), 2):
            chunks[index] = chunks[index].replace(OLD_NOTICE, NOTICE).replace(OLD_NOTICE_ZH, NOTICE_ZH)
        text = ''.join(chunks)
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
        # Upstream request de-duplication ("Repeat lookups of the same tweet
        # within the same UTC day are charged once") is not AIsa's charge rule;
        # x-aisa-pricing is. Single line breaks stay inside a sentence.
        chunk, count = drop_upstream_once(chunk)
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
                    if BILLING_ONLY.match(without_rate):
                        # "Billed as a posts read ($0.005)." says nothing once
                        # its amount is gone: drop the sentence and its spacing.
                        parts[j] = ''
                        if j + 1 < len(parts) and parts[j + 1].strip(' \t') == '':
                            parts[j + 1] = ''
                        elif j > 0 and parts[j - 1].strip(' \t') == '':
                            parts[j - 1] = ''
                    else:
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
