"""Remove stale monetary rate claims from public prose, never contract data.

Runtime x-aisa-pricing and request quotes own prices. Upstream source bytes and
their review receipts remain intact; this is a public presentation transform.
Amounts describing payments, market data, examples or units are not API rates.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import yaml
from customer_price_presentation import pricing_summary, reference_total, usd

# Legacy markers. Mintlify shows an HTML comment in an OpenAPI description as
# literal text, so new summaries carry no marker; these are only stripped.
PRICE_BEGIN = '<!-- aisa-pricing:start -->'
PRICE_END = '<!-- aisa-pricing:end -->'
# A generated summary is the description's last paragraph. It always opens with
# one of these leads and closes with the settlement sentence of its language.
SUMMARY_LEADS = (
    'Published reference price: ', 'Default request estimate: ',
    'Request pricing.', 'Usage-based pricing.', 'Charged for the actual billable results.',
    'Charged for the combined usage', 'Charged for actual usage', 'Price depends on',
    'Normal-tier reference price:', '请求费用。', '按实际用量收费。', '按实际计费结果数量收费。',
    '按各计费项目', '任务完成后', '价格取决于', '普通用户参考价格：',
    'Usage-based billing; Default request estimate: ',
    'A request reference price is not currently available; ',
    '公开参考价格：', '默认请求预估费用：', '按用量计费；默认请求预估费用：', '当前未提供请求参考价格；',
)
SUMMARY_ENDS = ('Account-specific pricing and final settlement may differ.', '最终费用以账户适用价格及实际结算为准。',
                'Your account price may differ; use a request quote where supported.',
                '账户适用价格可能不同；支持报价的接口可按实际请求获取报价。')
SUMMARY = re.compile(
    r'(?:\A|\n[ \t]*\n)[ \t]*(?:' + '|'.join(map(re.escape, SUMMARY_LEADS)) + r')[^\n]*?(?:'
    + '|'.join(map(re.escape, SUMMARY_ENDS)) + r')\s*\Z')


def strip_price_summary(text):
    text = re.sub(r'\s*' + re.escape(PRICE_BEGIN) + r'.*?' + re.escape(PRICE_END), '', text, flags=re.S)
    while True:
        stripped = SUMMARY.sub('', text)
        # These complete legacy generated paragraphs have no settlement suffix.
        stripped = re.sub(r'(?:\A|\n[ \t]*\n)(?:No charge\.|No additional charge for this operation\.|'
                          r'Price not yet published; this operation is unavailable\.|'
                          r'不收费。|此操作不另收费。|价格尚未发布；此操作暂不可用。)\s*\Z', '', stripped)
        if stripped == text:
            return text.strip()
        text = stripped


def remove_price_summary(operation):
    """Keep prices out of the operation description.

    Mintlify shows the description under the page title, so a price there
    leads the page. The page's cost section shows the price instead
    (readable_contract_notes.readable_block).
    """
    description = strip_price_summary(operation.get('description', ''))
    if pricing_summary(operation.get('x-aisa-pricing')):
        for notice in (NOTICE, NOTICE_ZH, *LEGACY_NOTICES):
            description = description.replace(notice, '').strip()
    if description:
        operation['description'] = description
    else:
        operation.pop('description', None)
    return operation

MONEY = re.compile(r'(?:US)?\$\s*\d[\d,]*(?:\.\d+)?(?:\s*USD)?|\b\d[\d,]*(?:\.\d+)?\s*\$|\b\d+(?:\.\d+)?\s*(?:USD|美元|cents?)\b', re.I)
CREDIT_VALUE = r'(?:\d[\d,]*(?:\.\d+)?|ceil\([^()]+\)|zero|one|two|three|four|five|ten|a)'
CREDIT_AMOUNT = r'(?<![A-Za-z0-9_.])' + CREDIT_VALUE + r'[ -]*(?:(?:more|full|flat|search|finder)\s+)*(?:credits?\b|积分|点数)'
CREDIT_TARIFF = r'variable credit prices|one flat credit whether'
CREDITS = re.compile(CREDIT_AMOUNT + '|' + CREDIT_TARIFF, re.I)
PRICE_DIAL = re.compile(
    r'\b(?:THIS IS THE PRICE DIAL|THIS IS THE COST DIAL|PRICE DIAL|COST DIAL)\b', re.I)
# "per" and "cached" alone also describe academic credits and account balances.
# Require a billing verb, a rate for an API unit, or a specific cache response.
CREDIT_CONTEXT = re.compile(
    r'\b(?:cost\w*|pric\w*|bill\w*|charg\w*|pay|adds|capped|expensive|cheapest|dearest)\b|'
    r'\bat\s+' + CREDIT_AMOUNT + r'|'
    + CREDIT_AMOUNT + r'(?:[ -]+per[ -]+(?:(?:returned|found|matched|nonempty)[ -]+)?(?:\d+[ -]+)?(?:call|request|returned|found|matched|nonempty|company|record|person|keyword|anchor|domain|row|profile|ad|brand|item|result)\b|[ -]+(?:flat|way|surface)\b)|'
    r'cached response|one-credit map band|' + CREDIT_TARIFF + r'|收费|计费|消耗|扣除', re.I)
RATE = re.compile(
    r'\bbill(?:ed|ing|s)?\b|\bcharg(?:e|ed|es|ing)\b|\bpric(?:e|ing)\b|'
    r'\b(?:flat|rate|surcharge|upstream|per\s+(?:call|request|item|row|job|1M\s+tokens))\b|'
    r'\bat\s+\$|'
    r'/\s*(?:request|call|次)\b|计费|收费|每次|每请求', re.I)
LEGACY_NOTICES = (
    'For current API pricing, see the published x-aisa-pricing metadata. Where supported, obtain a quote for your exact request.',
    '当前 API 价格请查看公开的 x-aisa-pricing 信息；接口支持报价时，请针对实际请求获取报价。',
)
# Old generated placeholders, recognized for removal only.
NOTICE = 'See the Cost and request rules section for current pricing. Where supported, obtain a quote for your exact request.'
NOTICE_ZH = '当前价格请查看费用与请求规则；接口支持报价时，可针对实际请求获取报价。'
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


def strip_credit_prices(text):
    """Remove supplier tariff clauses while retaining caller and outcome rules.

    A credit balance or a response value is not a tariff. Only prose with a
    credit tariff and billing context enters this transform; examples
    and reviewed payload descriptions are excluded by the callers.
    """
    if not (CREDITS.search(text) or PRICE_DIAL.search(text)) or not (CREDIT_CONTEXT.search(text) or PRICE_DIAL.search(text)):
        return text
    unit = r'(?:\s+(?:per\s+(?:(?:returned|found|started|matched)\s+)?[\w-]+(?:\s+returned)?|each|a hit))?'
    # Zero-priced failures/empty results are outcome rules, not positive rates.
    zero = r'(?:0(?:\.0+)?|zero)\s*(?:credits?\b|积分|点数)'
    text = re.sub(r'\b(billed|charged)\s+' + zero, r'not \1', text, flags=re.I)
    text = re.sub(r'\bcosts\s+' + zero, 'incurs no charge', text, flags=re.I)
    text = re.sub(r'\bcost\s+' + zero, 'incur no charge', text, flags=re.I)
    text = re.sub(r'(?:消耗|扣除)\s*' + zero, '不收费', text)
    # Hyphenated rates are words in prose, not identifiers or response fields.
    text = re.sub(r'(' + CREDIT_VALUE + r')-credit', r'\1 credit', text, flags=re.I)
    text = re.sub(r'credit-per-', 'credit per ', text, flags=re.I)
    text = re.sub(r'credit per ([a-z]+)-', r'credit per \1 ', text, flags=re.I)
    # Preserve the useful half of mixed price/usage clauses before dropping rates.
    text = re.sub(r',\s*so a full page is ~?' + CREDIT_AMOUNT, '', text, flags=re.I)
    text = re.sub(r';\s*(?:[\w-]+ can raise it to|all add-ons can bring one record to)\s+\d+\.', '.', text, flags=re.I)
    text = re.sub(r'\s+is the cheap one\s+at\s+' + CREDIT_AMOUNT + unit + r',?\s+but(?=\s+returns)', '', text, flags=re.I)
    text = re.sub(r'\s+at\s+' + CREDIT_AMOUNT + unit + r'(?=,?\s+but\s+returns)', '', text, flags=re.I)
    text = re.sub(r'\s*—\s*same\s+' + CREDIT_AMOUNT + unit + r'\s+price but\s+', ' — with ', text, flags=re.I)
    text = re.sub(r'\bthe\s+' + CREDIT_AMOUNT + r'\s+way\b', 'a way', text, flags=re.I)
    text = re.sub(r'\b' + CREDIT_AMOUNT + r'\s+flat\s*—\s*the cheap way to\s+', 'Use this to ', text, flags=re.I)
    if re.search(r'in one\s+' + CREDIT_AMOUNT + r'\s+call', text, re.I):
        text = re.sub(r'([a-z]+)\s+\(\d+(?:\.\d+)?\)(?=(?:\.(?=\d)|[^.!?\n])*tiers return)', r'\1', text, flags=re.I)
    text = re.sub(r'\s+in one\s+' + CREDIT_AMOUNT + r'\s+call\s*—\s*the same price as calling both',
                  ' in one call', text, flags=re.I)
    text = re.sub(r'\bThis is the most expensive endpoint[^.\n]*?\s*—\s*and\s+', '', text, flags=re.I)
    text = re.sub(r'\b(?:At\s+' + CREDIT_AMOUNT + r'\s+this is the cheapest|The dearest of|THE MOST EXPENSIVE ROUTE HERE|Same\s+' + CREDIT_AMOUNT + r' per hit rate)(?:\.(?=\d)|[^.;\n])*', '', text, flags=re.I)
    text = re.sub(r'\s+at the same \d+(?:\.\d+)? rate', '', text, flags=re.I)
    text = re.sub(r'\bThis is the fixed\s+' + CREDIT_AMOUNT + r'\s+surface\.\s*', '', text, flags=re.I)
    text = re.sub(r'\s+keeps this request inside[^.\n]*?one[ -]credit map band', '', text, flags=re.I)
    text = re.sub(r'\bThe\s+' + CREDIT_AMOUNT + r'\s+base search is exposed\.\s*', '', text, flags=re.I)
    text = re.sub(r'\s+because (?:they have separate variable credit prices|it adds one or more scrape credits for every returned page)', '', text, flags=re.I)
    text = re.sub(r',\s*bounding the search at\s+' + CREDIT_AMOUNT, '', text, flags=re.I)
    text = re.sub(r'\bOne flat credit whether you\s+', 'You can ', text, flags=re.I)
    text = re.sub(r'\bAdds\s+' + CREDIT_AMOUNT + r'\s+when true', 'May affect request pricing when true', text, flags=re.I)
    text = re.sub(r'\s*[,;]\s*(?:one credit per returned [a-z]+|and every returned row costs a credit)', '', text, flags=re.I)
    text = re.sub(r'(Choose projection:[^.\n]+)', lambda m: re.sub(r'\s+' + CREDIT_AMOUNT + r'(?:\s+per nonempty call)?', '', m[0], flags=re.I), text)
    text = re.sub(r'\s*;\s*the price follows the type[^.\n]*(?:\.[0-9][^.\n]*)*', '', text, flags=re.I)
    text = re.sub(r'\bCosts?\s+' + CREDIT_AMOUNT + r'\s+if ([^.\n]+),\s*' + CREDIT_AMOUNT + r'\s+otherwise',
                  r'This operation is billed if \1, and also otherwise', text, flags=re.I)
    text = re.sub(r'\bcosts?\s+' + CREDIT_AMOUNT + r'(?=\s+(?:even when|for AI transcription))', 'is billed', text, flags=re.I)
    text = re.sub(r'\b(verdicts?|results?|errors?)\s+(costs?)\s+' + CREDIT_AMOUNT,
                  lambda m: m[1] + (' is billed' if m[2].lower() == 'costs' else ' are billed'),
                  text, flags=re.I)
    # A provider-priced error may be absorbed by the service. Keep that error
    # condition and its following settlement explanation together.
    text = re.sub(r'\bcosts?\s+[A-Z][\w.-]+\s+' + CREDIT_AMOUNT,
                  'incurs provider usage', text)
    text = re.sub(r'\s+and still costs?\s+' + CREDIT_AMOUNT, ' and is still billed', text, flags=re.I)
    text = re.sub(r'\s+and charges\s+' + CREDIT_AMOUNT, '', text, flags=re.I)
    text = re.sub(r': same credits,', ':', text, flags=re.I)
    # Keep cache metadata and enrichment fields inside mixed parentheses.
    def parenthetical(match):
        value = match[1]
        if not CREDITS.search(value):
            return match[0]
        value = re.sub(r'^' + CREDIT_AMOUNT + r'\s*,\s*', '', value, flags=re.I)
        value = re.sub(r';\s*costs?\s+' + CREDIT_AMOUNT + unit + r'.*$', '', value, flags=re.I)
        if re.fullmatch(CREDIT_AMOUNT + unit, value, re.I):
            return ''
        if CREDITS.search(value) and CREDIT_CONTEXT.search(value):
            value = strip_credit_prices(value)
        return '(' + value + ')' if value else ''
    text = re.sub(r'[（(]([^()（）\n]*)[）)]', parenthetical, text)
    text = re.sub(r'\bCOST DIAL\s*[—:-]\s*', '', text, flags=re.I)
    # A supplier sometimes labels a parameter as a price dial without stating
    # the amount in the same sentence. Keep the request bounds and remove only
    # that editorial tariff marker.
    text = re.sub(
        r'\s*[—–:-]\s*THIS IS THE PRICE DIAL\b\s*:?\s*'
        r'(?:you\s+pay\s+)?' + CREDIT_AMOUNT + unit,
        '', text, flags=re.I)
    text = re.sub(r'\s*[—–:-]\s*THIS IS THE PRICE DIAL\b', '', text, flags=re.I)
    text = re.sub(r'\s*[—–:-]\s*THIS IS THE COST DIAL\b', '', text, flags=re.I)
    text = re.sub(r'\s*[—–]\s*(?:THIS IS THE PRICE|THIS IS THE COST|PRICE DIAL|you pay|and DOUBLES the price)[^\n.]*', '', text, flags=re.I)
    text = re.sub(r'\bTHIS IS THE PRICE\s*[—:-][^\n.]*', '', text, flags=re.I)
    # Remove a supplier authorization explanation but retain the actual limit.
    text = re.sub(r'[^.!?\n;]*\bcapped at\s+' + CREDIT_AMOUNT + r',\s*so\s*', ' ', text, flags=re.I)
    text = re.sub(r',\s*which\s+(?:bills|costs)\b[^.;\n)]*' + CREDIT_AMOUNT + r'[^.;\n)]*', '', text, flags=re.I)
    text = re.sub(r'\s+at\s+' + CREDIT_AMOUNT + unit + r'(?:\s*=\s*' + CREDIT_AMOUNT + r')?', '', text, flags=re.I)
    text = re.sub(r'\s*[,;]\s*cost(?:ing|s)?\s+' + CREDIT_AMOUNT + unit + r'[^\n.;)]*', '', text, flags=re.I)
    text = re.sub(r'\s+and\s+(?:may\s+)?costs?\s+' + CREDIT_AMOUNT + unit + r'(?:\s+rather than one)?', '', text, flags=re.I)
    text = re.sub(r'\s+costs?\s+' + CREDIT_AMOUNT + unit + r'\s+and(?=\s+also\s+includes)', '', text, flags=re.I)
    text = re.sub(r'\s+adds\s+' + CREDIT_AMOUNT + r'[^\n.;)]*', '', text, flags=re.I)
    # Retain explicit failure/404 billing conditions without the supplier unit.
    text = re.sub(r'\b(billed|charged)\s+' + CREDIT_AMOUNT + r'(?:\s*\(\$[\d.]+\))?', r'\1', text, flags=re.I)
    # A trailing pricing clause must not swallow an opt-in instruction or limit.
    text = re.sub(r':\s*[^.!?\n;]*\b(?:costs?|bills)\s+(?:a flat\s+)?' + CREDIT_AMOUNT + r'[^.!?\n;]*', '', text, flags=re.I)
    text = re.sub(r';\s*on [^.;\n]*\b(?:base|tier) price unchanged', '', text, flags=re.I)
    text = re.sub(r'Response detail and fixed price[^:.]*:[^.\n]*' + CREDIT_AMOUNT + r'[^.\n]*\.',
                  'Response detail.', text, flags=re.I)
    # Remaining standalone tariff sentences contain no customer price authority.
    parts = re.split(r'(\n+|(?<=[.!?])\s+(?!\d)|(?<=[。！？])|[;；，][ \t]*)', text)
    for i in range(0, len(parts), 2):
        part = parts[i]
        if not part or not CREDITS.search(part):
            continue
        if CREDIT_CONTEXT.search(part):
            parts[i] = ''
            if i + 1 < len(parts) and '\n' not in parts[i + 1]:
                parts[i + 1] = ''
    result = ''.join(parts)
    result = re.sub(r'[ \t]+([.;；。)])', r'\1', result)
    result = re.sub(r'([;；])[ \t]*(?=[.;；。]|$)', '', result)
    result = re.sub(r'([.!?。！？])[ \t]*[;；][ \t]*', r'\1 ', result)
    result = re.sub(r'\s*\(\s*\)', '', result)
    return result.strip()


def reconcile_free_claim(text, pricing):
    """A positive customer success price contradicts an unqualified Free claim."""
    if not isinstance(pricing, dict) or pricing.get('customer_pricing') != 'fixed_success':
        return text
    amount = reference_total(pricing)
    if amount is None or amount == '$0' or pricing.get('reference_unavailable'):
        return text
    # A standalone billing sentence/clause, never descriptions such as free text
    # or quoted example data. Remove it without creating a pricing placeholder.
    chunks = FENCES.split(text)
    for index in range(0, len(chunks), 2):
        chunks[index] = re.sub(r'(^|(?<=[.!?])\s+)Free[,;]\s*([a-z])',
                               lambda m: m[1] + m[2].upper(), chunks[index])
        chunks[index] = re.sub(r'(^|(?<=[.!?])\s+)Free(?:\.(?=\s|$)|$)', r'\1', chunks[index])
    return ''.join(chunks).strip()


def clean_text(text: str, language: str = 'en') -> str:
    """Remove obsolete tariffs/notices without inserting replacement price prose."""
    generated_notices = (*LEGACY_NOTICES, NOTICE, NOTICE_ZH)
    if not MONEY.search(text) and not CREDITS.search(text) and not PRICE_DIAL.search(text) and not any(notice in text for notice in generated_notices):
        return text
    chunks = FENCES.split(text)
    changed = False
    for index in range(0, len(chunks), 2):
        chunk = chunks[index]
        chunk = strip_credit_prices(chunk)
        changed |= chunk != chunks[index]
        # The Cost section renders the customer price. A removed supplier
        # tariff must not become another placeholder directing readers there.
        for notice in generated_notices:
            chunk = chunk.replace(notice, '')
        changed |= chunk != chunks[index]
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
    return result


def documented_payload_fields(node: dict) -> bool:
    """Reviewed field prose describes payload values, including business prices."""
    if node.get('x-aisa-schema-completeness') == 'documented-fields-only':
        return True
    content = node.get('content')
    return isinstance(content, dict) and any(
        isinstance(media, dict) and isinstance(media.get('schema'), dict)
        and media['schema'].get('x-aisa-schema-completeness') == 'documented-fields-only'
        for media in content.values())



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
        had_description = 'description' in result
        if is_operation and isinstance(result.get('description'), str):
            result['description'] = strip_price_summary(result['description'])
            result['description'] = reconcile_free_claim(result['description'], result.get('x-aisa-pricing'))
        for field in ('description', 'summary', 'title'):
            if isinstance(result.get(field), str):
                # A response field table is part of the data contract. Product
                # prices, delivery fees and subscription prices are not API
                # billing claims, even when their descriptions contain dollars.
                if field == 'description' and documented_payload_fields(result):
                    continue
                # OpenAPI declarations are machine-facing input to the page
                # and locale generators.  Keep customer pricing in
                # x-aisa-pricing/readable_contract_notes; never append the
                # page-level pricing notice to a parameter, schema, response,
                # summary, or title description.
                result[field] = clean_text(result[field])
        if is_operation:
            remove_price_summary(result)
            # Keep the declaration shape stable when a stale billing-only
            # operation description is removed. Locale generation relies on
            # this invariant for protocol parity.
            if had_description and 'description' not in result:
                result['description'] = ''
        return result

    # Paths and reusable declaration names are user-controlled map keys. Walk
    # the top-level map in place so presentation cleanup cannot reorder the
    # generated OpenAPI document and create unrelated mirror churn.
    output = {}
    for key, value in document.items():
        if key == 'paths' and isinstance(value, dict):
            output[key] = {path: walk(item) for path, item in value.items()}
        else:
            output[key] = walk(value)
    return output


def strip_tariff_columns(text):
    """Keep the business columns of API rate tables, without supplier tariffs."""
    lines = text.splitlines(keepends=True)
    price_names = {'price', 'pricing', 'cost', 'usd', '价格', '费用', '计费'}
    credit_names = {'credit', 'credits', '积分', '点数'}
    api_names = {'section', 'endpoint', 'api', 'operation', 'request', 'plan', '接口', '操作', '请求', '套餐'}
    index = 0
    while index + 1 < len(lines):
        if not lines[index].lstrip().startswith('|'):
            index += 1
            continue
        end = index + 1
        while end < len(lines) and lines[end].lstrip().startswith('|'):
            end += 1
        endings = [line[len(line.rstrip('\r\n')):] for line in lines[index:end]]
        rows = [re.split(r'(?<!\\)\|', line.rstrip('\r\n')) for line in lines[index:end]]
        if len(rows) < 2 or not all(re.fullmatch(r'\s*:?-+:?\s*', cell)
                                    for cell in rows[1][1:] if cell.strip()):
            index = end
            continue
        names = [cell.strip().strip('*`').lower() for cell in rows[0]]
        credit_columns = {i for i, name in enumerate(names) if name in credit_names}
        price_columns = {i for i, name in enumerate(names) if name in price_names}
        placeholders = any(re.search(r'See current pricing|See the published pricing|见当前定价', cell, re.I)
                           for row in rows[2:] for i, cell in enumerate(row) if i in price_columns)
        tariff = credit_columns or placeholders or set(names) & api_names
        removed = price_columns | credit_columns if tariff else set()
        if removed:
            for row_index, row in enumerate(rows):
                if not any(name for i, name in enumerate(names) if i not in removed):
                    lines[index + row_index] = ''
                else:
                    lines[index + row_index] = '|'.join(cell for i, cell in enumerate(row) if i not in removed) + endings[row_index]
        index = end
    return ''.join(lines)


def clean_page(text: str, language: str = 'en') -> str:
    """Clean handwritten API-page prose before adding Runtime's managed block."""
    from runtime_localize_openapi_zh import split_frontmatter, replace_frontmatter_value
    from readable_contract_notes import strip_generated_block
    header, body = split_frontmatter(strip_generated_block(text))
    original = (header, body)
    metadata = yaml.safe_load(header) or {}
    for key in ('description', 'excerpt'):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            updated = clean_text(strip_price_summary(value), language)
            if updated != value:
                header = replace_frontmatter_value(header, key, updated)
    # Preserve business columns, never replace supplier prices with placeholders.
    chunks = FENCES.split(body)
    for index in range(0, len(chunks), 2):
        prose = strip_tariff_columns(chunks[index])
        core = prose.strip()
        # A chunk sits between fences (for example `<CodeGroup>` before its
        # first block); keep its surrounding newlines so a fence stays on its own line.
        # Legacy summaries also appeared in the MDX body, including free and
        # unpublished prices with no monetary amount. Remove the whole block
        # before rate cleanup; otherwise that cleanup leaves its markers behind.
        without_summary = strip_price_summary(core)
        cleaned = clean_text(without_summary, language) if without_summary else ''
        # Removing a final tariff sentence can leave one space at a paragraph
        # end. Preserve two-space Markdown hard breaks and fenced examples.
        if cleaned != without_summary:
            cleaned = re.sub(r'(?<=\S)[ \t](?=\n)', '', cleaned)
        if cleaned != core:
            prose = prose[:len(prose) - len(prose.lstrip())] + cleaned + prose[len(prose.rstrip()):]
        chunks[index] = prose
    body = ''.join(chunks)
    if (header, body) == original:
        return text
    return '---\n' + header + '\n---\n' + body


DESCRIPTION_HASH = 'x-aisa-generated-description-sha256'


def refresh_page_description(text, operation, language='en', translate=None):
    """Override Mintlify's inherited prose without changing canonical OpenAPI.

    An empty description falls back to the original operation, so billing-only
    descriptions use the endpoint title. Track only generated values: a manual
    edit takes ownership, while unchanged generated prose follows source updates.
    """
    from runtime_localize_openapi_zh import split_frontmatter, replace_frontmatter_value
    if not text.startswith('---\n'):
        return text
    header, body = split_frontmatter(text)
    metadata = yaml.safe_load(header) or {}
    if not metadata.get('openapi'):
        return text
    existing = metadata.get('description')
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()
    owned = isinstance(existing, str) and metadata.get(DESCRIPTION_HASH) == digest(existing)

    def cleaned(value):
        if not isinstance(value, str):
            return ''
        return clean_text(reconcile_free_claim(strip_price_summary(value),
                          operation.get('x-aisa-pricing')), language).strip()

    source_description = operation.get('description') or ''
    if not owned and not existing and cleaned(source_description) == source_description:
        return text  # Clean inherited descriptions need no presentation override.
    authored = cleaned(existing) if existing and not owned else ''
    description = authored
    if not description:
        description = cleaned(source_description)
        if language == 'zh' and translate and description:
            description = cleaned(translate(description))
        if not description:
            # The page title already follows the existing localization policy.
            description = cleaned(metadata.get('title')) or cleaned(operation.get('summary'))
        if not description:
            return text  # No business description or title to project.
    if 'description' in metadata:
        header = replace_frontmatter_value(header, 'description', description)
    else:
        header += '\ndescription: ' + json.dumps(description, ensure_ascii=False)
    if not authored:
        if DESCRIPTION_HASH in metadata:
            header = replace_frontmatter_value(header, DESCRIPTION_HASH, digest(description))
        else:
            header += '\n' + DESCRIPTION_HASH + ': ' + json.dumps(digest(description))
    elif DESCRIPTION_HASH in metadata:
        # A user-edited description must not be overwritten on the next run.
        header = re.sub(r'^' + re.escape(DESCRIPTION_HASH) + r':[^\n]*\n?', '', header, flags=re.M).rstrip('\n')
    return '---\n' + header + '\n---\n' + body
