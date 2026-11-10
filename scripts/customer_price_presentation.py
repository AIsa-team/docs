"""Customer price copy from published declarations, without supplier arithmetic.

Reference totals and customer unit prices have already been priced by Runtime.
Never multiply those totals again or promote a supplier rate/estimator to a
customer tariff. The only local conversion is integer customer micro-USD, and
the declared cache share of that same customer price (rounded as Runtime does).
"""
from decimal import Decimal, InvalidOperation
import re


def usd(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return '$' + (format(amount, 'f').rstrip('0').rstrip('.') if amount % 1 else format(amount, '.0f'))


def customer_micros(pricing):
    value = pricing.get('customer_micros_usd')
    return value if type(value) is int and value >= 0 else None


def reference_total(pricing):
    if (pricing.get('reference_unavailable') or pricing.get('estimate_unavailable_reason')
            or pricing.get('estimate_source') == 'unavailable'):
        return None
    return usd(pricing.get('default_request_estimate_usd'))


def price_family(pricing):
    kind = pricing.get('kind')
    if kind in {'no_customer_charge', 'fixed_request', 'metered_event', 'metered_result', 'model_catalog', 'unpriced'}:
        return kind
    if pricing.get('customer_pricing') == 'fixed_success':
        return 'fixed_success'
    cost = pricing.get('cost_contract')
    if cost in {'fixed_success', 'request_formula', 'plan_units'}:
        # A fixed supplier label can still use a request-dependent estimator.
        return 'request_dependent'
    if cost == 'response_count':
        return 'result_dependent'
    if cost in {'response_components', 'response_sku'}:
        return 'components'
    return 'usage'


def literal(text):
    """Keep declaration text from turning into MDX/HTML or forged headings."""
    return ''.join(f'&#{ord(c)};' if c in '<>{}[]\\`*_|\n\r' else c for c in str(text))


def event_description(pricing, zh):
    description = pricing.get('description')
    if not isinstance(description, str) or not description.strip():
        return ''
    # The metering identity is not a price or customer condition.
    meter = pricing.get('meter')
    if isinstance(meter, str) and meter:
        description = re.sub(r'^Publication is metered under ' + re.escape(meter)
                             + r'(?::<[^>]+>)?\.\s*', '', description)
    # Translate the current typed Social tariff without hard-coding any prices.
    social = re.search(r'an X post costs (\$[\d.]+), or (\$[\d.]+) when its effective text contains a URL '
                       r'\(media URLs do not select the text-URL price\); a post on any other platform costs (\$[\d.]+)\.', description)
    if pricing.get('meter') == 'social.post.published' and social:
        x, link, other = social.groups()
        text = (f'每个成功发布的目标单独收费：X 普通帖子 {x} USD；正文含链接 {link} USD（媒体链接不影响价格）；'
                f'其他平台 {other} USD。草稿和发布失败的目标不收费。' if zh else
                f'Per successfully published target: X {x} USD; X with a link in the post text {link} USD '
                f'(media links do not change the price); other platforms {other} USD. '
                'Drafts and failed targets are not charged.')
        # Do not invent a waiver if an older/newer declaration lacks it.
        if 'Draft creation is free.' not in description or 'A failed target is not charged' not in description:
            return literal(description)
        if 'Accepted or unknown responses remain pending' in description:
            text += ' 待确认目标在确认发布后结算。' if zh else ' Pending targets settle after publication is confirmed.'
        return text
    return literal(description.strip())


def fixed_conditions(pricing, zh):
    """Preserve customer-relevant conditions from the existing typed tariff."""
    description = pricing.get('description', '')
    if not isinstance(description, str):
        return ''
    parts = []
    if 'Failed or unknown outcomes are not charged.' in description:
        parts.append('失败或结果未知时不收费。' if zh else 'Failed or unknown outcomes are not charged.')
    cache = re.search(r'Repeated identical requests within (\d+) (minutes|hours) are served from cache at no charge', description)
    if cache:
        duration, unit = cache.groups()
        parts.append(f'{duration} {"分钟" if unit == "minutes" else "小时"}内的相同请求命中缓存时免费。' if zh else
                     f'Identical requests served from cache within {duration} {unit} are free.')
        if 'force a fresh read, which is charged' in description:
            parts.append('强制刷新按次收费。' if zh else 'A forced refresh is charged.')
    return ' '.join(parts)


def fixed_request_summary(pricing, zh):
    def t(en, cn): return cn if zh else en
    unavailable = t('Price unavailable.', '价格暂不可用。')
    # An explicit failed reference must not fall back to a stale scalar amount.
    if (pricing.get('reference_unavailable') or pricing.get('estimate_unavailable_reason')
            or pricing.get('estimate_source') == 'unavailable'):
        return unavailable
    parts = []
    micros = customer_micros(pricing)
    amount = usd(Decimal(micros) / 1_000_000) if micros is not None else reference_total(pricing)
    resource = 'cache_hit_share_bps' in pricing
    if amount:
        if resource:
            parts.append(t(f'Normal-tier reference price: {amount} USD per delivered read.', f'普通用户参考价格：每次成功交付查询 {amount} USD。'))
            parts.append(t('A read that delivers nothing is not charged.', '未交付查询结果时不收费。'))
            share = pricing['cache_hit_share_bps']
            if micros is not None and type(share) is int and 0 < share <= 10000:
                # Resource execution skips the store when no hit price is
                # published (share=0); only a positive share offers reuse.
                cached = (micros * share + 9999) // 10000
                cached_amount = usd(Decimal(cached) / 1_000_000)
                parts.append(t(f'Stored result: {cached_amount} USD.', f'使用已存结果：{cached_amount} USD。'))
        elif pricing.get('estimate_source') == 'configured_fixed_price':
            parts.append(t(f'Published reference price: {amount} USD per completed job.', f'公开参考价格：每个完成的任务 {amount} USD。'))
        elif micros is not None:
            parts.append(t(f'Published reference price: {amount} USD per successful request.', f'公开参考价格：每次成功请求 {amount} USD。'))
        else:
            # kind alone does not make an arbitrary reference estimator a tariff.
            parts.append(t(f'Default request estimate: {amount} USD.', f'默认请求预估费用：{amount} USD。'))
    variants = pricing.get('variants')
    if isinstance(variants, dict):
        for name, variant in sorted(variants.items()):
            if not isinstance(variant, dict):
                continue
            label = literal(name)
            if variant.get('status') == 'disabled':
                parts.append(t(f'{label}: unavailable.', f'{label}：暂不可用。'))
            else:
                # Variants inherit the parent's delivered-read unit, not its price.
                child = dict(variant, kind='fixed_request')
                if resource and 'cache_hit_share_bps' not in child:
                    child['cache_hit_share_bps'] = pricing['cache_hit_share_bps']
                child.pop('variants', None)
                parts.append(f'{label}: ' + fixed_request_summary(child, zh))
    conditions = fixed_conditions(pricing, zh)
    if conditions:
        parts.append(conditions)
    return ' '.join(parts) or unavailable


def pricing_summary(pricing, language='en'):
    if not isinstance(pricing, dict) or not pricing:
        return ''
    zh = language == 'zh'
    def t(en, cn): return cn if zh else en
    family = price_family(pricing)
    if family == 'no_customer_charge':
        return t('No additional charge for this operation.', '此操作不另收费。')
    if family == 'unpriced':
        return t('Price not yet published; this operation is unavailable.', '价格尚未发布，此操作暂不可用。')
    if family == 'fixed_request':
        summary = fixed_request_summary(pricing, zh)
    elif family == 'metered_event':
        summary = event_description(pricing, zh) or t('Charged per successful event; price unavailable.', '按成功事件收费；价格暂不可用。')
    elif family == 'model_catalog':
        # Runtime carries the selected model's billing units and the n semantics.
        description = pricing.get('description', '')
        if not isinstance(description, str):
            description = ''
        if 'whatever n is' in description:
            summary = t('Price depends on the selected model. Fixed-price models charge once per request, regardless of n; token-priced models charge for actual token usage.',
                        '价格取决于所选模型。固定价模型每次请求收取一次费用，不随 n 改变；按 token 定价的模型按实际用量收费。')
        elif 'per second, per request or by tokens' in description:
            summary = t('Price depends on the model, resolution and duration; the selected model is billed per second, per request or by token usage.',
                        '价格取决于模型、分辨率和时长；按所选模型的每秒、每次请求或 token 用量价格计费。')
        else:
            summary = t('Price depends on the selected model and request options.', '价格取决于所选模型和请求选项。')
    else:
        total = reference_total(pricing)
        if family == 'fixed_success' and total:
            summary = t(f'Published reference price: {total} USD per successful request.', f'公开参考价格：每次成功请求 {total} USD。')
        else:
            leads = {
                'request_dependent': ('Request pricing.', '请求费用。'),
                'result_dependent': ('Charged for the actual billable results.', '按实际计费结果数量收费。'),
                'components': ('Charged for the combined usage of the billable components.', '按各计费项目的实际用量合计收费。'),
                'metered_result': ('Charged for actual usage when the job completes.', '任务完成后按实际用量收费。'),
                'usage': ('Usage-based pricing.', '按实际用量收费。'),
            }
            summary = t(*leads.get(family, ('Price unavailable.', '价格暂不可用。')))
            # Only an explicitly CUSTOMER-priced unit can be shown as a tariff.
            unit_price = usd(pricing.get('customer_unit_price_usd'))
            if (pricing.get('reference_unavailable') or
                    pricing.get('estimate_unavailable_reason') not in (None, '', 'request_dependent_units')):
                unit_price = None
            if unit_price is not None:
                summary += ' ' + t(f'Published reference price: {unit_price} USD per billable unit.', f'公开参考价格：每计费单位 {unit_price} USD。')
            if total is not None:
                summary += ' ' + t(f'Default request estimate: {total} USD. The final charge depends on actual usage.',
                                   f'默认请求预估费用：{total} USD。最终费用以实际用量为准。')
            elif unit_price is None and family != 'fixed_success':
                summary += ' ' + t('A price estimate is not currently available.', '当前暂无预估金额。')
    return summary + ' ' + t('Your account price may differ; use a request quote where supported.',
                            '账户适用价格可能不同；支持报价的接口可按实际请求获取报价。')
