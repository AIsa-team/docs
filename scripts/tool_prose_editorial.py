"""Reviewed editorial corrections, not a keyword filter or a pricing engine.

Only exact known prose clauses are replaced. Wire names, enum values, examples,
attribution credits, financial credit data and product prices are not API rates.
"""
import json
from pathlib import Path
import re
from functools import lru_cache

NOTICE = ("For AIsa charges, use AIsa's applicable pricing and a request quote where "
          "supported. Upstream usage counters do not define AIsa prices or refunds.")

# Literal request values, response keys/messages and examples, not explanatory
# prose. These strings must not be translated into invalid wire values.
WIRE_LITERAL_TEXT = set('''一周内 一天内 上海 不限 主体类型 九宫格 二次元 云南
互联网新闻信息服务许可证编号 内容类目 北京 医疗健康 半年内 厨房电器 团播 国艺
好物合集 家电 广东 开箱 归属地 所属行业 手机 故事 数码 普通笔记 服务单位 服务类别
服饰 母婴 汽车 测评类 浙江 游戏 热销商品 生活好物评测 直播笔记 相亲 美妆 美妆个护
舞蹈 茶 视频号 视频笔记 认证时间 该视频没有可用字幕 音乐 颜值 食品饮料
男 女 行业洞察 产品洞察 用户洞察 趋势洞察'''.split())


@lru_cache(maxsize=1)
def billing_corrections():
    return json.loads((Path(__file__).parent / 'data/tool-prose-billing-corrections.json').read_text())

TRANSLATIONS = {
    'AliExpress / 速卖通': 'AliExpress', 'Facebook公开数据': 'Facebook public data',
    'Google搜索数据': 'Google Search data', 'Meta广告库': 'Meta Ad Library',
    'TikTok广告库': 'TikTok Ad Library', 'QQ互选': 'QQ Huxuan',
    '京东:': 'JD.com:', '淘宝:': 'Taobao:', '豆瓣:': 'Douban:',
    '闲鱼:': 'Xianyu:', '网页提取:': 'Web extraction:',
    '商品详情': 'Product details', '商品搜索': 'Product search',
    '创建监测任务': 'Create a monitoring task', '删除监测任务': 'Delete a monitoring task',
    '查询监测任务': 'Get a monitoring task', '分页拉取文章': 'Retrieve posts with pagination',
    '全量更新监测任务': 'Replace the monitoring task configuration',
    '启用或暂停监测任务': 'Enable or pause a monitoring task',
    'Semrush 相关关键词：给定种子关键词返回语义相关扩展词（搜索量/CPC/竞争度/结果数/趋势）。按返回行计费。':
        'Find semantically related keywords from a seed keyword, with search volume, CPC, competition, result counts and trends.',
    '透传 AI 搜索 source: chatgpt/gemini/perplexity/google_search/google_ai_mode;返回 答案+引用+来源URL。Caller 传完整 body(含 source),原样转发 POST /v1/queries。':
        'Forward an AI search request using source chatgpt/gemini/perplexity/google_search/google_ai_mode. Returns an answer, citations and source URLs. Supply the complete body, including source; it is forwarded unchanged to POST /v1/queries.',
    'Ministry of Finance (国債金利情報)': 'Ministry of Finance government bond interest-rate data',
    'award notices (決標公告)': 'award notices',
    'failed-to-award notices (無法決標)': 'failed-to-award notices',
    'cancellation notices (撤銷公告)': 'cancellation notices',
    'tender notices (招標公告 and sibling notice types)': 'tender notices and related notice types',
    'Filters: 区分 (`kubun`)': 'Filters: classification (`kubun`)',
    'the 区分 program labels': 'the classification program labels',
    'Organiс': 'Organic',  # Upstream Latin word containing a Cyrillic c.
    '地区代码：US/SG/MY/PH/TH/VN/ID/JP/MX；GB 和 BR 暂不支持 / Region code: US/SG/MY/PH/TH/VN/ID/JP/MX; GB and BR are unavailable':
        'Region code: US/SG/MY/PH/TH/VN/ID/JP/MX; GB and BR are unavailable.',
}


def english_prose(text):
    # These are reviewed prose fragments. Chinese wire literals deliberately
    # remain intact: translating category labels or JSON keys breaks requests.
    for before, after in TRANSLATIONS.items():
        text = text.replace(before, after)
    return text


def editorial_text(text, *, native=False, notice=False):
    text = english_prose(text)
    if native:
        return text
    original = text
    for row in billing_corrections():
        text = text.replace(row['before'], row['after'])
    if text == original:
        return text
    text = re.sub(r'(?m)^#{1,6} Response handling[ \t]*(?:\n|$)(?=\s*(?:#{1,6} |$))', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    if notice and text != original and NOTICE not in text:
        text += '\n\n' + NOTICE
    return text
