# API 契约文档自动化：完成规格与验收标准

状态：待评审的实施规格，尚未开始按本规格修改代码。
日期：2026-10-01。
本轮仅编写与审查 spec；不修代码、不更新发布 pin、不合并、不运行生产 SQL、不部署。

## 1. 目标与完成的含义

目标是：所有现有及未来的对外 integration endpoint 都进入同一条契约链路；接口事实只维护一次；Docs、网站、MCP、Router 和发现入口自动消费；没有定义、无法转换、来源过期和版本失配都不会被静默当作正确文档。

这里的“一劳永逸”指消除多处重复维护和静默漂移。供应商新增规则仍需有权威来源；系统不从示例猜必填、类型、默认值或价格，也不把上游正常运行作为文档准确性的替代证据。

本规格固定三个可分别判断的结果，不能相互替代：

| 结果 | 必须成立 | 不能据此宣称 |
| --- | --- | --- |
| 通用机制完成 | 全量计账、新接口自动纳管、无损消费、来源治理、失败报告和回归门禁成立 | 所有缺失定义已补齐、生产已生效 |
| 正式交付完成 | 严格正式输入检查通过，发布和各消费者部署完成，真实入口读回一致 | 所有上游永远可用、历史未知定义自动变已知 |
| 所有启用接口文档完整 | 必需请求/响应定义缺口为零，已声明公共协议无丢失，来源有有效维护依据 | 所有特殊协议均能在每个消费者执行 |

整体需求的“全部完成”必须同时满足以上三个结果。允许阶段交付，但报告必须明确阶段，不能用“修复五项”代替“需求完成”。用户此前暂缓具体来源调查，不等于批准生产欠账基线或认可全部文档完整。

## 2. 为什么之前反复修复仍没有闭环

之前的工作方式存在五个问题：

1. 先按局部 finding 修复，没有先固定全部入口、字段职责和完成条件。
2. 验证接口数量、ID 和加载成功，多于验证完整请求/响应声明是否经过转换与展示仍保真。
3. 将 `primary response`、示例和扁平字段表当成完整响应契约，遗漏数组、组合 schema、多个状态及媒体。
4. 将局部测试、离线全量快照、正式发布输入和生产读回混在一个“ready”判断里。
5. 自动发现新接口已有实现，但手工/固定版本来源维护及正式发布启动流程没有作为最终验收的独立前置条件。

这些问题属于契约投影、消费和交付的完整性，不需要改变请求执行或计费才能修复。后续按本规格的需求矩阵审查，先确定整个工作包的边界，再实施，禁止只补眼前一个页面或一个供应商。

## 3. 范围与约束

纳入范围：runtime integration inventory 中所有配置 endpoint；现有 V2 Profile、公共 handler/request descriptor、async lifecycle、Batch/GAQL 等已纳入投影的公共契约；Docs EN/ZH API 页面和导航、provider/aggregate OpenAPI、网站 API 详情、MCP/Router 文档详情及发现索引。

已有禁用或退役接口必须被计账；不恢复其执行能力。183 个历史禁用 legacy 排除项只有在报告了具体排除理由时才算纳管，不算已生成完整可调用契约。生命周期 operation 可能没有独立数据库 endpoint 行，必须另行对账。

不扩大到未纳入本次 inventory 的管理 API、模型网关重构或全部营销内容。发现入口中引用 integration 接口、价格、数量、能力的事实属于范围；一般产品说明与长篇指南仍有编辑负责人。

不改变 routing、auth、validation、admission、quote、pricing、charging、settlement、上游调用和现有执行限制。文档不能反向修改 runtime。MCP 输出校验保持现状；文档完整性不能变成已经扣费后拒绝成功响应的理由。

复用现有 Profile、source mirror、registry、composer、coverage/pending、消费者 compiler、workflow 与版本监测。不增加新的契约数据库、配置中心、schema 语言、队列或逐接口探测服务。

## 4. 冻结基线与已证实缺口

以下是已审查代码和 2026-09-30 派生的离线快照，不是新查询的生产总数：

| 层 | 基线与当前证据 |
| --- | --- |
| Runtime | PR #579，`dea1899f9833af083c822566420e21ea3a2c129e`；2,162 配置 endpoint，1,979 projected，183 disabled legacy excluded |
| Docs | PR #126，`89296da5fac52ad51b360ca24005cc2f5a03daa0`；42 输出、1,930 operation；12 enabled + 90 disabled request pending，62 response gap |
| Website | PR #139，`87be2447689bf303de99eebc8f138336b8db242b`；1,918 enabled operation 对账；完整请求声明已保留，完整响应未保留 |
| MCP | PR #10，`084c1cff6400409c2c893a017c8a34873595845e`；65 server 载入，1,918 operation 可发现；1,859 known response，60 response pending，其中一项同时已知部分与缺口 |
| Router | PR #93，`c842fa0bad68afb5ed395d926b5210ddfc707604`；诊断全量编译 1,919 endpoint / 7 plan，含一个保留 legacy operation；251 执行限制不变 |
| 来源 | Docs 仓库 67 个 mirror：48 manual、18 refreshable、1 pinned；这是来源文件分母，不是 provider 或 endpoint 分母 |

必须补齐的实现边界：

- 网站 `shared/contractCatalog.mjs` 只选择第一个 JSON 成功响应并读顶层 `properties`，详情页只展示响应示例。
- MCP `response_contract.py` 只收集成功响应；`schema_page.complete` 目前描述成功 payload 的完整程度，不能代表全部公共请求/响应/协议已完整。
- Router `compilePrimaryResponse` 只保存主响应；详情中未知响应也可能返回 `{}`，缺少未知与明确无约束的区分。
- 网站 Next 实际 discovery route 的 `/openapi.yaml` 读取浮动 docs URL，而详情使用固定 SHA；两者需要纳入同版本验收。旧 Express 的 llms 注释不能代替 Next 实际路由证据。
- llms/Agent Card 等摘要中仍需审计手写接口数量、能力与价格事实；纯编辑说明可以保留，接口事实不能成为第二份主表。
- Docs 代码 CI 目前因缺正式 index/facts 返回 `not_assessed`；正式 reviewed baseline、runtime identity bootstrap 和消费者部署收敛未完成。
- 网站完整测试有 24 个已复现的历史失败；最终提交 CI 已失败于首页脚本 1,102,487 bytes 超过 850,000 预算。不能据“没有新增失败”宣称全部 CI 通过。

## 5. 契约权威与无损文档要求

### 5.1 每类事实只有一个 owner

| 事实 | 权威 | 消费规则 |
| --- | --- | --- |
| identity、公共 method/path、状态 | backend endpoint binding + 实际 runtime projection | 保留已发布 ID、别名和页面 URL，不由消费者重新命名 |
| runtime 校验的请求、默认、约束、公共转换 | 绑定 Profile 或实际 handler/public descriptor | 原有 schema 和语义优先，保留条件约束与 caller/provider 边界 |
| 透传 payload 定义 | exact binding 对应的审核来源 | 不按相似路径猜；新 provider 仅补一次来源绑定，同来源的新 endpoint 自动继承 |
| 公共状态、headers、links、auth、错误 | runtime 公共协议声明 | 不继承供应商私有 errors/headers/auth 充当公共协议 |
| 成功响应 payload | runtime 声明优先；符合现有明确透传/公共路由规则的审核来源补充 | 历史声明仅按既有规则保留并标来源，不假装本次新验证 |
| 静态价格与计量说明 | 精确 CustomerPricing/Profile 绑定及策略 | 保留来源和 estimate 语义；个性化实时 quote 独立 |
| 长篇说明与翻译 | Git editorial/translation | 仅修改说明，不改 wire 标识符和接口事实 |

公共 OpenAPI 3.1 是无损文档载体。不增加另一套简化 schema 主格式。发现列表可以精简；按需详情必须能取得同版本的完整 operation 和其引用闭包。

### 5.2 按需详情必须保留的信息

1. 有效 `(in, name)` 参数及 path/operation 覆盖结果；required、schema/content、style、explode、allowReserved 等已声明序列化信息。
2. requestBody 的 required、全部媒体类型、schema、encoding、已声明示例。
3. 全部已声明公共 response 状态，包括具体状态、范围状态和 default；每个状态的 description、content/media/schema/examples、headers、links。
4. 数组、scalar、nullable、无约束/布尔 schema、composition、条件/依赖、additionalProperties、enum/default/const/format/边界、递归及共享 `$ref` 的原有语义。
5. pending、缺失或不能表达的具体原因；source revision、docs SHA、provider document hash 及 consumer/compiler revision。
6. root/path/operation 继承后的有效公共 servers、security 及可达公共 security schemes；不能混入供应商密钥、私有 host 或采购配置。
7. 若存在已声明公共 callbacks/webhooks，保留同版本文档及引用；消费者无法表达时具名报告限制，不因此新增执行能力或静默丢弃。

未知定义、明确声明 `{}`、204/205 No Content、部分已知必须区分。不要用空对象或“没有示例”推导完整性。示例与 schema 是不同信息：缺少示例不等于缺少定义；已有示例不能证明完整 schema。

MCP/Router 现有 `arguments_schema`、`response_schema`、primary response 字段保持兼容，新增按需文档信息，不改变它们的执行输入或 admission。可使用原公共 OpenAPI 片段加可达声明作为文档详情；不要求工具列表和卡片装入整份 schema。

Router 的返回类型由公开 OpenAPI/generated 类型约束。机器详情采用显式 opt-in 的完整文档字段：默认旧请求不增加额外响应字段，opt-in 才返回完整文档视图或固定 docs SHA/hash、可取回的完整详情引用。需同步公开响应定义、生成类型和实际 MCP 外壳，验证旧默认请求/响应与收费调用校验保持原状。网站自己的按需详情可直接携带完整文档。不能只在内部 model 增字段就算端到端完成。

完整性必须有作用域：请求声明、成功响应、全部已声明公共协议、示例、来源维护、发布收敛分别报告。已有 `schema_page.complete` 的含义要明确；它不能被解释为整个 endpoint 已验收。

### 5.3 消费者责任矩阵

| 入口 | 必须提供 | 必须验证 |
| --- | --- | --- |
| Docs provider/aggregate OpenAPI | 完整公共声明、来源和 pending | operation 集合、引用闭包、生成稳定性与权威一致性 |
| Docs EN/ZH 页面与导航 | 有效参数、响应、示例、已知限制、精确 OpenAPI 引用 | 实际页面绑定可解析；两种语言 wire/schema 相同；新增自动入导航，旧 URL 保持 |
| 网站按需详情 | 全请求、全公共响应、schema/refs、示例、缺口；固定版本 | 实际 UI 展示与 loader/proxy/fallback 完整性，不只测 projector |
| 网站 `/openapi.yaml` | 与该部署详情相同 SHA 的原文/校验镜像 | 禁止浮动 docs origin 混入另一版本；同版本 fallback 或明确失败 |
| MCP `get_details` | 兼容现有字段 + 完整公共文档视图/可取回的同版本契约、缺口与完整性作用域 | 实际 root mount、主题别名、local/router backend 均验证，不只测 helper |
| Router schema/details | 兼容 primary response + 完整公共文档视图/可取回的同版本契约、未知声明 | 实际 compiler、bundle 读写、service、MCP 外壳；执行限制仍独立 |
| llms/Agent Card/ai-plugin/MCP manifest | 自动成员/事实摘要和同版本详情引用 | 不复制参数/价格表；接口数量、能力来自对应真实 producer；链接可用、版本可追溯 |
| 实时 quote/availability | 保持原实时来源及时间/上下文 | 不以静态文档或能力报告冒充实际报价、执行支持或供应商可用性 |

“详情完整”不要求所有状态都出现一套 UI 表格，但必须提供可读、可取回的完整已声明数据。单纯链接浮动文档或只留下示例不满足无损消费。

## 6. 全量纳管、缺口与未来接入

### 6.1 两个分母分别对账

endpoint inventory 的每行恰有 projected、pending 或 excluded(reason) 的结果；以现有 runtime index 的分区为准。projected endpoint 生成的每个 method/lifecycle operation 再恰有 composed、pending 或明确历史状态。不能拿 1,918 operation 的加载成功代替 2,162 endpoint 的覆盖证明。

全部消费结果按 ID 和 method/path 集合比较，报告缺失、额外、重复、错误归属和显式排除。允许现有历史项，但必须具名有 provenance，不能被计作新 runtime 事实。

### 6.2 新增 endpoint 的唯一日常流程

1. 通过现有后台配置 endpoint，绑定真实 Profile/handler/source；获取稳定 ID。
2. runtime 投影自动进入 index；Docs 自动发现并组合。
3. 已支持形态自动通过通用验证与消费；发布后自动更新各入口。
4. 缺来源、坏 binding 或不支持形态自动产生具体 pending；不能要求修改多个消费者名单，也不能假装 schema 完整。

新来源格式可以需要一次 importer/converter；新执行协议可以需要单独 adapter。这些必须在接入报告中被识别，不纳入文档项目的执行改造。

### 6.3 现有欠账与新增欠账

复用 coverage/pending、响应 gap 和 source metadata；不新建第二份手写 endpoint 清单。

已知欠账的独立审核基线使用完整 Git SHA，至少核对 ID、method/path、gap 类别、稳定原因、相关 source/binding/profile 证据。请求与响应缺口分别对账，禁止只比较数量。source 整体 hash 或临时错误文案变化不能把所有无关欠账误报为新项，但实际绑定或相关声明改变必须失效旧豁免。

新 endpoint 或新/改变的必需定义缺口不得自动进入批准基线。受影响的未定义文档不能作为 complete 发布；安全保留 last-good 或明确 partial/pending，其他独立合格 provider 继续按已有隔离规则处理。以上不改变 endpoint 的 runtime enabled、admission 或计费。

12 个 enabled request 和 62 个 response gap 暂缓时，通用机制仍可验证，但整体“启用接口文档完整”不能通过。90 个 disabled request gap 继续可见，不因完成启用接口验收而消失或自动启用。

## 7. 来源维护如何形成长期闭环

按来源治理，不按 endpoint 重复维护。新 endpoint 继承所属来源策略。

在现有 source metadata/registry binding 中明确 owner、权威依据、refresh policy、版本/hash、审核方式与复查到期时间。信息只保留一个写入口；registry 引用 mirror，报告从它们生成。

| 来源类别 | 必须做的事 | 不允许的结论 |
| --- | --- | --- |
| automatic/refreshable | 自动获取、校验、语义 diff；变化进入既有 review PR；失败保留旧内容及失败证据 | fetch 成功即证明运行兼容；失败仍刷新证据年龄 |
| manual | 每个来源有 owner 和可追溯依据；能改自动来源的先迁移；剩余项有定期复查及到期告警 | skip 即“已检查通过”；没有监测依据却承诺自动发现上游改版 |
| pinned | 保留固定原因、版本与 owner；明确更新/解除条件；可跟踪官方新版本信号或按期人工复查 | 固定旧 SHA 被重新读取即“上游最新” |

本 draft 的默认方案：自动来源复用既有 refresh workflow 改为每日，每次获取失败立即使该次 workflow/报告失败，下一周期重试；manual/pinned 复查周期 30 天，以最近有证据的成功审核起算。更改周期或固定策略须由来源 owner 通过同一 source policy review，形成新 policy revision，不能由任务运行临时豁免。当前工作流仍为每月上游刷新，以上尚未实施或验证。不能把复查间隔宣传为供应商改版发现的绝对上限。

来源报告必须覆盖全部来源文件，区分 unchanged/changed/fetch_failed/manual_due/manual_overdue/pinned/unknown，列版本、最近成功核验及原因。新增来源缺 owner/策略/依据时，不得通过文档来源 readiness。

来源到期和获取失败通过现有 workflow summary/artifact 与版本监测呈现；不需要新的监控平台。已过期 last-good 可以保留服务，但不能标为 fresh 或 complete。需实际到期复查后才解除告警，不能单纯改时间绕过。

来源声明、维护策略与观测收据分离：镜像/契约保留 source hash、版本和 policy 引用；收据复用 workflow 报告/缓存/artifact，按 `(source_hash, policy_revision)` 关联，记录 checked_at、last_successful_review_at、review_due_at、判断和证据引用。策略本身有版本，观察时间不参与契约内容 hash；成功但无内容变化只更新报告，不重写镜像 fetched_at 或制造新 schema revision。

更新人工复查时间必须附官方文档/发行说明/供应商确认等依据、被审核 hash、reviewer 与检查结果；获取失败、单纯重读本地镜像或改日期不算成功复查。固定版本详情显示来源 as-of、关联审核期限及证据引用，不声称实时 fresh。到期且没有匹配收据，或报告缺失时，显示 overdue/unknown；不增加全局实时查询服务。人工源无法自动证明供应商未变，来源 freshness 与 schema 完整性分别标记。

## 8. 验证：先有固定 oracle，再实现

oracle 直接读取固定版本的公共声明、runtime facts 和来源；不能调用待测消费者的同一投影函数再与自身比较。优先复用现有 schema resolver、测试 fixtures 和实际官方源片段；断言期待内容必须独立定义。

oracle 分两层：代表性矩阵采用人工审查的 expected semantic graph，其转换/引用闭包期待不能使用待测实现的同一函数，基础 JSON/YAML parser 可以共享；全量采用独立 source/binding 对账与声明字段路径、继承规则和 refs 闭包检查。消费者对比固定规范文档，Docs composer 自身再对比 runtime/source 证据。不要另写一个完整 composer 与现有 composer 相互证明，也不能让待测 composer 的输出成为它自身的期待图。

同一冻结输入依次经过真实 runtime HTTP、Docs composer/page generation、网站 proxy/loader/UI、MCP root、Router compiler/bundle/service。每个消费者按其职责对比声明图和引用闭包，而非仅数量、顶层 properties 或成功加载。

| 验收编号 | 覆盖形态/事件 | 必须观察到 |
| --- | --- | --- |
| C01 | 全量 inventory、provider grouping、历史/disabled、method/lifecycle 展开 | 集合/计账无无解释遗漏、重复或归属错误 |
| C02 | 真实后台新增 provider，再新增第二条 endpoint | 同一链路自动发现；不改 consumer allowlist、旧 ID/URL 不变 |
| C03 | path/query/header/cookie、继承覆盖、schema/content、style/explode、公共 security/servers | 原声明和序列化保留；有效公共认证与路由来源一致且不泄露私有配置；同名不同 location 不互相覆盖；不能支持的消费明确说明 |
| C04 | object/array/scalar/null/boolean、nested/map、composition/条件/依赖/约束 | Docs 和按需详情均保真；实际 UI 可读；不要求增加执行适配 |
| C05 | OAS 3.0→3.1、递归/共享/escaped refs、外部/坏 refs、字面 `$ref` | 保留语义，合法闭包有限；坏引用明确失败，JSON 实例不当引用解析 |
| C06 | 全部公共 status/default/range、多成功/错误、headers/links、204/205 | 已声明数据保留；未知、无约束、无内容分开；不导入供应商私有协议 |
| C07 | JSON/+json/text/binary/multipart/form/stream | 已声明媒体保留；文档支持与执行支持分开，不伪造 JSON |
| C08 | media/named/ref/schema examples、显式 null、缺例、例子不合约 | 已有示例不丢；不从无例生成假的响应；cURL 与声明/现有 compiler 相符 |
| C09 | 请求、响应、binding、source 变化及新缺口 | 新缺口不能自动获得旧债豁免；同数量不同缺口被识别；来源审阅 diff 可读 |
| C10 | source fetch 失败、manual 到期、pinned 新版本信号、恢复 | 旧证据保留，失效可见，不能假称 fresh；真实复核后清除 |
| C11 | 版本/hash/ID 不符、缺 metadata、丢一次 dispatch、后续 scheduled 恢复 | 同版本 fallback 或失败；公开版本检查能发现滞后并证明恢复 |
| C12 | EN/ZH 页面/导航、llms、卡片、下载、MCP manifest、详情引用 | 正确 ID 集合与有效固定引用；不保留第二份手写接口事实表 |
| C13 | 价格/执行限制与调用行为回归 | bindings、静态 pricing、251 既有限制不变；mock 请求/响应、auth、quote/use 不受文档元数据改变 |
| C14 | 正式锁定 publication 和真实部署后读回 | 严格源验证启用，非诊断/不可激活产物；独立选定发布 SHA，全部 required 入口一致 |

完整输入必须测试所有操作；复杂形态的实际 UI/协议端点采用上述代表性样本，不对每个供应商收费调用。需要样本还没有覆盖的形态时，先补本矩阵和 oracle 再实现，不能靠测试自己刚写的分支宣称需求完成。

## 9. 代码验证与发布验收分离，解除启动死锁

复用现有 workflows，明确两种检查。它们是检查结果，不是新的业务状态机。

**代码检查**：固定可回放的 sanitized runtime evidence、source/docs SHA 和历史版本，执行 C01–C13 的适用部分、相关完整测试及实际跨仓消费者检查。不依赖尚未上线的 public facts；正式输入缺失必须报告，但不能使所有 generator/consumer 代码 PR 都只能先部署才能合并。

**发布检查**：实际 generated publication/source-lock 推进必须有正式 runtime index/facts、独立审核欠账基线、真实候选图和来源审阅依据。`not_assessed` 非通过，不能用于启用发布。代码检查不能替代本检查。

检查归属必须在 W0 固定到具体 workflow/job 与变更类型：Runtime 固定 Docs 的三条 E2E、Docs 单元/离线 candidate、网站生成/TypeScript/详情/UI、本项目预算、MCP 完整 validation、Router compiler/bundle/service 及 image checks 属于代码检查。正式 `pull-openapi` 写入、generated publication PR、各消费者 release source-lock、catalog publish/activation 属于发布检查；同时包含代码与生成产物的 PR 必须同时通过，不能按“代码 PR”绕过真实产物检查。既有 Docs 依赖 public cache 的候选 job 必须改为正确分层，正式 publication 检查不得降级。

首个欠账基线可以先从经独立审阅的冻结输入、身份 manifest 和生成 coverage/response gaps 准备：审阅记录引用该完整 Git SHA、输入 hash 和明确的待补集合，由非生成任务本身确认批准，再配置现有 baseline 引用。它可以先于 runtime 部署准备，解除启动依赖；批准只允许保留同一债，不证明输入已在线或允许发布。部署后的正式 facts 与基线不一致时仍需失败和重新审阅。当前临时诊断基线尚未获得该批准。

若当前 branch protection 把依赖未部署证据的检查设为所有代码 PR 的必需项，应拆分 check/PR 范围并明确 required-check 配置，再按现有部署权限完成 bootstrap。不得先部署未审代码、伪造正式 cache、自动批准临时基线或把 exit 3 改成成功。

网站 24 个历史失败按失败文件/原因分组定责；本项目必需 gate 与首页预算必须通过。其他与本项目无关的全套失败若继续存在，必须有明确的独立审阅记录和影响边界；实现者不能自行豁免或降低预算。无论是否有例外，都不得声称完整测试全绿。

## 10. 实施工作包与依赖顺序

| 工作包 | owner/位置 | 输出与退出条件 |
| --- | --- | --- |
| W0：锁定规格与 oracle | Runtime + Docs，现有 tests | 固定本规格矩阵、完整输入与来源哈希、所有声明形态样本及期待图、具体 required checks、调度/job/cache 时限；审查无遗漏后再改实现 |
| W1：无损消费与入口版本 | 网站/MCP/Router 的 compiler、details、UI、discovery routes | 共同完成 C03–C08/C12；补齐网站响应、MCP 公共协议详情、Router 非 primary/unknown；保留旧字段兼容；OpenAPI/llms/卡片来源一致 |
| W2：来源与欠账治理 | Docs existing source metadata、refresh、readiness、reports | 全 67 来源归类与 owner/期限，request/response 欠账分别比较，C09/C10 通过；不改 runtime admission |
| W3：可合并代码验证与正式 gate | 各仓 existing CI + cross-repo 固定输入 | W1/W2 同一全量快照验收；代码检查可独立通过；正式发布仍严格；所有本项目 required checks 通过，历史失败边界明确 |
| W4：正式 bootstrap、发布与读回 | 现有后台维护、runtime、Docs、消费者 release owners | 完成正式 runtime facts、审核来源/欠账基线、固定 publication、全部 required consumer 激活及 C11/C14；本轮不执行 |
| W5：逐项补来源内容 | 现有契约/source owner | 按真实依据关闭 enabled request/response 缺口；最终“所有启用接口文档完整”验收为零，不从数量变化推断调用成功 |

W0 → W1/W2 → W3 → W4 是机制交付的关键路径。W5 可独立推进，但不完成就不能声称整体文档完整；用户暂缓它时不无限扩大 W1–W3。

每个包开始前列全涉及字段和入口；完成后先由独立 reviewer 对本规格逐行比对，再进行测试/修复。功能形态可以拆包，不能按 provider 开补丁或依赖最后再发现一个消费者。

新 finding 必须归属已有验收项：若实现未达要求，作为同包 bug 修复；若是新增产品要求，先更新 spec 和矩阵再改代码。不得移动完成标准，亦不得用“迭代低价值”关闭未满足的硬条件。

## 11. 正式启动与长期日常流程

以下为后续发布方案，不是本轮执行授权：

1. 复核最新完整 inventory、历史 published identities 与初始 ID manifest；固定来源和精确 migration/import 方案。
2. 按现有审批执行 additive identity schema；import 先 dry-run/verify 后显式应用。仅写空 identity，保留历史 ID、状态、路由、价格和时间戳。
3. 先安装通过代码检查的消费者兼容代码和工作流，继续使用旧正式 pin，不激活新契约；再部署 runtime，读回公开 index/每个 catalog 的事实/hash，保留 sanitized 正式 evidence。不要拿旧离线重建 inventory 冒充生产事实。
4. 从正式输入生成候选，独立审阅既有债和 source policy；运行严格 publication gate，保留完整候选报告。
5. 发布 Docs 不可变 SHA/hash。消费者仅使用该 SHA；复用 dispatch 与 scheduled pull，检查 GitHub App 权限、发布开关、branch protection 和各实际部署渠道已可用。
6. 正式编译、构建并激活各消费者；`VerifyDocsGit=false` / `Activatable=false` 诊断产物不得充当正式发布证明。
7. 独立读回 runtime、Docs EN/ZH/OpenAPI、网站、MCP、Router 与 discovery 实际入口，检查成员、完整声明样本、facts/document hash、docs SHA、consumer build revision。
8. 验证新增 endpoint、更新声明、禁用 endpoint、失败保留和丢 dispatch 后恢复的完整流程；保存观察时间和收敛延迟。无需收费上游调用。

上线后日常流程是：在唯一来源修改/新增 → 自动生成与校验 → 声明变更审阅 → 不可变发布 → 消费更新 → 实际读回/滞后告警。不会再要求逐个通知网站、MCP、Router 重填事实。

不承诺未经测量的“5 分钟同步”。现有 runtime/docs 拉取每 30 分钟、网站每 30 分钟、MCP/Router 约每小时；自动阶段还包含构建/部署/缓存。

本 draft 设定的自动化预算：已审核来源/binding 生效到 Docs 候选生成不超过 60 分钟；目标 Docs SHA 已发布、所有人工 release 前置满足后，正常传播和丢一次 dispatch 的 scheduled 恢复均在 4 小时内完成最慢 required consumer 的一致性读回。W0 按每条实际 workflow 的调度、最大 job 时长、全部 CDN/cache/SWR 窗口核算并冻结预算及检查频率；不能满足时，在改实现前提出具体预算/缓存方案修订。不能在 W4 失败后扩大 deadline 使失败变通过。

需要人工声明/lock 审核时，单独报告 pending_review、owner、请求时间与到期时间，默认提醒期限为一个工作日；不能把人工等待算作有界自动恢复，也不能隐去真实端到端等待时间。正式总交付在该等待解除前仍未完成。自动阶段超过冻结预算即失败并保留各阶段时间与滞后原因；后续版本监测至少每小时检查，及时报告预算超时。W4 必须实测一个正常更新和一次丢 dispatch 后恢复，验证既定时限，而非事后才定义时限。

## 12. 最终验收清单与交付记录

每次最终 review 保存一个总报告，引用固定 revision、输入哈希、声明矩阵和具体证据；不要只链接临时目录。尽可能由现有 CI 生成 artifact，仓库记录验收命令/版本与结果边界。

- [ ] 全量 endpoint 及 operation 集合都有唯一结果，无无解释遗漏。
- [ ] 新 provider 和后续 endpoint 无消费者名单改动即可自动纳管。
- [ ] 所有已声明公共请求/响应经过全部规定详情入口无语义丢失，复杂形态与实际 UI/外壳已验证。
- [ ] 所有 discovery/download/EN/ZH 入口在职责范围内引用同一来源版本，旧 URL/ID/别名稳定。
- [ ] 全部来源有治理方式，manual/pinned 局限和过期状态可见。
- [ ] 既有 request/response 欠账透明，新缺口不能静默豁免；未知不冒充无约束。
- [ ] 本项目代码和发布 required checks 各自通过；例外与完整 suite 失败如实记录。
- [ ] 正式 identity/runtime evidence、Docs publication、consumer activation 和独立 live convergence 已完成。
- [ ] 更新、禁用、获取失败及 dispatch 恢复流程有可保存证据。
- [ ] runtime 执行、认证、计费、定价和既有限制保持原样。
- [ ] 启用接口必需 request/response 来源缺口为零，才可使用“全部文档完整”的结论。

规格完成后，W0 已落成[固定验收包](api-contract-acceptance/README.md)：五个仓库版本、全量离线输入及哈希、独立预期、C01–C14 检查入口与职责已固定。包完整性、预期自身检查和离线重放已验证；这不表示消费者实现、页面、正式发布或整体内容通过。现有时限不满足目标的路径及[具体修订方案](api-contract-acceptance/timing-remediation.md)已记录，时限可行性仍须 W3/W4 配置证据与实测。后续按 W1/W2 → W3 推进，不能跳到另一轮零散补丁。

## 13. 依据与现有入口

本规格替代旧单一来源设计中尚未落地的实现设想作为后续完成工作的验收依据，不改写其历史状态。旧文档及各 PR 中已验证机制继续复用。

- [原始设计](api-contract-single-source-design.md)：目标、唯一 owner、业务发布与文档分离。
- [Runtime PR #579](https://github.com/AIsa-team/AIsaServices/pull/579)：runtime projection、identity、跨仓 E2E。
- [Docs PR #126](https://github.com/AIsa-team/docs/pull/126)：发现、组合、coverage/readiness、来源刷新和收敛检查。
- [Website PR #139](https://github.com/AIsa-team/aisa-landing-page/pull/139)：固定版本目录、详情、fallback、生成与发现入口。
- [MCP PR #10](https://github.com/AIsa-team/aisa-mcp/pull/10)：registry defaults、真实 loader/root、独立响应说明。
- [Router PR #93](https://github.com/AIsa-team/aisa-tool-router/pull/93)：registry compiler、bundle、schema service、source lock。

精确基线源码定位：Docs `scripts/compose_openapi.py:420`、`scripts/contract_readiness.py:203`、`scripts/check_contract_candidate.py:145`、`scripts/refresh_upstream.py:75`；Website `shared/contractCatalog.mjs:114`、`client/src/pages/ApiDetail.tsx:339`、`app/api/discovery/[filename]/route.ts:14`、`app/api/discovery/rootLlms.ts:92`；MCP `src/aisa_mcp/response_contract.py:91`、`src/aisa_mcp/search/contract.py:94`；Router `internal/catalog/compiler/compiler.go:893`、`internal/toolrouter/service.go:401`。

数据和测试基线来自 2026-10-01 修复验证报告及同日只读 review；正式实施须重新固定当前 revision，不直接把历史统计或临时证据当成 live acceptance。
