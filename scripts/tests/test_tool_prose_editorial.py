import unittest
import csv
import json
import re
from pathlib import Path

WIRE_LITERAL_TEXT = set('''一周内 一天内 上海 不限 主体类型 九宫格 二次元 云南
互联网新闻信息服务许可证编号 内容类目 北京 医疗健康 半年内 厨房电器 团播 国艺
好物合集 家电 广东 开箱 归属地 所属行业 手机 故事 数码 普通笔记 服务单位 服务类别
服饰 母婴 汽车 测评类 浙江 游戏 热销商品 生活好物评测 直播笔记 相亲 美妆 美妆个护
舞蹈 茶 视频号 视频笔记 认证时间 该视频没有可用字幕 音乐 颜值 食品饮料
男 女 行业洞察 产品洞察 用户洞察 趋势洞察'''.split())


class EditorialProseTests(unittest.TestCase):
    def test_reviewed_wording_proposals_are_english_with_explicit_wire_literal_exceptions(self):
        root = Path(__file__).resolve().parents[2]
        non_english = re.compile(r'[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+')
        with (root / 'docs/tool-prose-coverage-20261112.csv').open() as stream:
            for row in csv.DictReader(stream):
                self.assertFalse(non_english.search(row['summary_after']), row['operation_id'])
                fragments = set(non_english.findall(row['description_after']))
                self.assertFalse(fragments - WIRE_LITERAL_TEXT, (row['operation_id'], fragments - WIRE_LITERAL_TEXT))

    def test_original_wire_examples_are_unchanged_by_editorial_corrections(self):
        from tool_prose_history import before_tool_prose_amendment
        root = Path(__file__).resolve().parents[2]
        rows = json.loads((root / 'docs/tool-prose-changes-20261112.json').read_text())
        nested = [row for row in rows if 'pointer' in row]
        self.assertTrue(nested)
        for row in nested:
            self.assertIn(row['pointer'][-1], ('summary', 'description'))
            self.assertFalse(set(map(str, row['pointer'])) & {'enum', 'default', 'example', 'examples'})
        for name in {row['source_file'] for row in nested}:
            before_tool_prose_amendment(root, name)

    def test_all_static_source_explanations_use_english_not_bilingual_region_notes(self):
        root = Path(__file__).resolve().parents[2]
        non_english = re.compile(r'[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+')
        def visit(value):
            if isinstance(value, list):
                for child in value:
                    yield from visit(child)
            elif isinstance(value, dict):
                for key, child in value.items():
                    if key.startswith('x-') or key in ('example', 'examples', 'enum', 'default'):
                        continue
                    if key in ('summary', 'description') and isinstance(child, str):
                        yield child
                    elif isinstance(child, (dict, list)):
                        yield from visit(child)
        for path in (root / 'openapi/upstream').glob('*.json'):
            for text in visit(json.loads(path.read_text())):
                self.assertFalse(set(non_english.findall(text)) - WIRE_LITERAL_TEXT, (path, text))


if __name__ == '__main__':
    unittest.main()
