# HK IFRS 17 年报处理与分析平台使用手册

适用代码：`E:\KPMG\HKIFRS17\hk_ifrs17_platform`，按 2026 年 10 月 30 日当前代码核对。界面按钮保留英文原名，便于直接查找。本手册同时说明操作、审核判断和常见问题；实际财务结论仍以原始年报为准。

## 一、最快完成一份年报

| 顺序 | 页面 | 完成标志 |
| --- | --- | --- |
| 0 | Filing monitor | 本地报告库已有 PDF，报告年度、币种、单位和 Company／Consolidated 口径正确。 |
| 1 | Locate pages | 各目标表的**物理 PDF 页码**与续页经原图确认，并点击 `Confirm all reviewed table pages`。 |
| 2 | Extract & review | 点击 `Extract all confirmed tables`；检查提取结果，必要时编辑；点击 `Send extracted cells to Step 3 checks`。 |
| 3 | Check & publish | 完成 PDF 逐格复核，处理差额、缺失及口径疑点；`Cells to investigate` 为 0、适用规则已解决后点击 `Publish checked filing`。 |
| 4 | Integrate | 发布后整合数据已自动刷新；如需指定报告组合或重建，点击 `Build integrated dataset`。 |
| 5–6 | Insurer explorer／Peer comparison | 如页面提示尚未激活数据，点击 `Use saved verified data`；查看单家公司或同口径同期间的同业比较。 |

**核心原则：**一个报告的本年列和比较年度列分别存为两个期间，但保留该报告的同一报表口径。物理 PDF 页码从文件第一页计为 1，与正文印刷页码可能不同。数字必须与原表的年度、实体口径、行、完整列头、计量方法和单位对应；空白或短横线不是零。

## 二、启动与数据准备

在项目目录打开终端，首次安装依赖，然后启动：

```powershell
cd E:\KPMG\HKIFRS17\hk_ifrs17_platform
python -m pip install -r requirements.txt
python -m streamlit run ifrs17_app.py
```

浏览器打开终端显示的本地地址。顶部 `Step 0` 至 `Step 6` 为主要导航。PDF、审核草稿、发布记录和整合结果存于本地项目的 `disclosures`、`data` 等目录；备份或迁移项目时应一并保留这些数据。模型服务的 URL、模型名、API key 只在当前浏览器会话中使用；刷新、新开标签或重启后如提示缺失，重新填写即可。

### Step 0 · Filing monitor：登记报告和监测披露

1. `Local filing library` 可查看现有报告、PDF 是否存在、报告口径、币种和单位。选中报告后可看到 PDF 页数及文本层提示。
2. 新报告在 `Add a filing` 上传 PDF，填写 insurer name、报告封面的 legal entity、财政年度截止日、`Reporting scope`、`Source currency`、`Source statement unit`，点击 `Register PDF`。审计师模板可选；它只提供表名线索，不会替代当前 PDF 的页码确认。
3. **先查看主表标题确定口径。**例如主表写 `Consolidated statement ...`，该报告登记为 `Consolidated`；不能只根据公司名称或附注页眉推断。附注若明确切换至 Company，需要单独核对，不能混入集团数据。
4. 披露监测可按 insurer、报告年度和分组查找更新，`Check this insurer for updates` 或批量检查后可 `Download scan results Excel`。扫描命中只是网页线索，需要打开实际 PDF 确认。公司链接清单可在平台编辑保存，或下载 Excel、修改后导入。

## 三、Step 1 · Locate pages：定位物理 PDF 页

1. 选择 `Filing`。页面会显示目标年度及上一比较年度，两年均从**同一份报告**获取。
2. 展开 `Vision model settings`，填写兼容 OpenAI 接口的 URL、视觉模型名和 API key。Step 2 和 Step 3 共用本次会话的设置；Step 3 如会话中断也可通过 `Shared model connection` 重新连接。超时值可设为 120–600 秒；Kimi K2.6 在匹配服务地址时可选快速响应。
3. 在 `Model-assisted page discovery` 设置 `First physical PDF page to scan`、`Last physical PDF page to scan`，选择 `Source tables to locate`。建议先定位一组相关表，再扩展范围。扫描文件有 business review 时，应优先从已审计财务报表开始的页码扫描，并检查附注续页。
4. 默认 `Contents, titles and note radar`：用目录、页标题、前 60 页的短文本导航及附注关键词先找线索，再让模型查看必要的原始页图。扫描版 PDF 会利用本地 OCR 索引；必要时选择 `Full visual scan`。`Physical pages per model request` 默认 2；密集附注通常用 1–2 页以保留字和年份的可读性。
5. 勾选发送页面到模型服务的确认框，点击 `Locate candidate pages`。定位阶段只寻找**可见目标表格**和实际物理页，不提取金额。`Model proposals and local filtering` 可看被保留或排除的线索；`Download discovery diagnostics` 提供模型请求耗时和筛选原因。失败区间要单独重扫，不能把“没有候选”当成“没有披露”。
6. 在 `Page-number review` 中逐表核对建议页码，跨页表用逗号分开，如 `99, 100, 101, 102`。右侧 `Page preview · original full PDF page` 切换表和续页，核对标题、年份、Company／Consolidated、合同群组以及数字列。无模型建议时可手工输入。最后点击 `Confirm all reviewed table pages`。

**确认标准：**仅有目录条目、附注标题或文字说明而没有目标表格数字行／列头的页面，不应算作提取页。比较年度专页也可选入，以便从同一份报告提取两年；页码必须是页面预览所示的物理 PDF 页。更换 PDF 后，原确认页不再适用，应重新定位。

## 四、Step 2 · Extract & review：逐表提取与平行审核

Step 2 顶部列出 Step 1 已确认的 `(表格类型, 物理页)` 任务。勾选发送页图的确认框，再点击 `Extract all confirmed tables`。模型按每张表、每个物理页单独抄录，限定对应指标代码，并记录原值、原单位、期间和来源标签。失败任务在结果表中显示表名、页码和原因；可用 `Retry ... failed table page(s)` 或 `Extract selected pages` 定向重试。

一次成功重试会替换**该表页的 Pending 集合**，保留 Verified 单元格和失败页已有数据。`Draft cells` 是已填入的“期间 × 指标”记录数，发现新指标时可能增加，并非固定数量的表格格子；同一键不应因重复提取而无限累加。若数字增加异常，应在 `Review by source table` 查看新旧指标、年度及来源页，避免同义指标误映射。

### 在平台审核

1. 看 `Review by source table` 的每表数量，使用 `Table to review` 一次只展示一张表。
2. 展开该表的 `Original PDF page` 才显示原始整页。逐格核对 `Period end`、`Metric code`、`Original value`、`Source unit`、`PDF page`、`Source label` 及更细的表题、行、列、年份、证据区域；必要时直接编辑并点击 `Save source edits`。
3. `Confirm all pending tables (...) — optional` 可一次性确认已复核的 Pending 单元格。也可直接点 `Send extracted cells to Step 3 checks`；Pending 将作为候选交给 Step 3 的逐格检查，**不必先在 Excel 手工改成 Verified**。
4. 原表没有数字、只有短横线或不可辨认时，不要填零。`Value status` 可区分 `Reported`、`Derived from disclosed items`、`Not disclosed`、`Not applicable`；缺失但确实披露的格子可用 `Add a missing source cell` 补录，并留原文行列标签。

### 用 Excel 审核

点击 `Download source review Excel`，在 `Records` 等工作表核对和修改来源单元格；从 `Upload edited source review Excel` 上传，点击 `Import reviewed workbook`。若已按原 PDF 完成核查，勾选 `I checked the included source cells against the original PDF`，平台会确认导入单元格；未勾选时仍可在平台统一确认或直接送 Step 3。**平台编辑与 Excel 编辑是平行方式，数据都回到同一份 Step 2 草稿。**导入文件须只包含当前所选报告。

## 五、Step 3 · Check & publish：逐格来源核查与勾稽

Step 3 对 Step 2 送来的每个数值候选（含 Pending）检查来源完整性、单位换算、原图、算术及关联规则。页面直接显示自动结果；`Optional exception notes and sign choices` 不需要预先填写，只有真正的例外或原表符号解释才使用。

### 5.1 独立 PDF 图像核查

`Independent PDF image check` 中：

- `Image matches` 是模型已确认与原图一致的数量；`Awaiting image check` 尚未核查；`Image findings to review` 为不一致或无法辨认。它们不能合并理解为“全部失败”。
- 若 `Check PDF cells needing review` 不能点，先查当前报告是否有待查格子、发送确认框是否勾选，以及 `Shared model connection` 的 URL、模型名、API key 是否齐全。
- 点击该按钮后，模型在不读取数据库原金额的条件下重新看原始页，并核对年份、完整列路径、行、单位、合同范围和实体口径。附注页未明确改变口径时，可以继承已确认的主表口径；遇到附注明确的 Company／Consolidated 切换则以原文为准。旧核查结果中没有口径依据的关联附注格子也会重新检查。
- `Unreviewed cells and image findings` 展示观测值、行列、年份、口径及证据区域。仅当整页复读和独立数字局部复读均唯一确认原金额时，平台可自动修正金额并保留历史；错年、错列、错单位、多候选或无法辨认必须回 Step 2 或人工核查，不能为凑平差额而改数。

### 5.2 算术、跨表和例外

`Statement-to-note scope corroboration` 比较同年度主表与附注中定义和毛／净口径相容的总额；数值相符且两格的 PDF 来源已核对，可增强 Company／Consolidated 口径判断，但不能单靠相等推断口径。`Automatic arithmetic screening` 同时检查本年和比较年度，损益／OCI 变动与现金流分别作为输入，不把毛额、净额或资产、负债混算。`Every source cell` 逐格列出来源、单位、关联规则和最终结果。

`Automatic investigation` 给出差额或缺失指标的来源页和核查动作。按以下顺序处理：

1. 阅读 `Check ID`、差额或缺失代码，以及列出的物理 PDF 页。
2. 在 Step 2 原图确认年度、Company／Consolidated、保险／再保险、PAA／非 PAA、合同群组、行、完整列头、正负号和金额单位。
3. 若原值、年份、单位或指标映射错，回 Step 2 改正并再次送 Step 3；不要在 Step 3 Excel 的 `Records` 直接修改金额。
4. 若缺失指标在附注中确有披露，回 Step 1 补续页或在 Step 2 补录；若确实未披露，留附注依据、物理 PDF 页和原因。不能用期末减期初倒推未披露的变动额。
5. 返回 Step 3 复查格子和相关规则，再发布。

规则结果含 `Pass`、`Difference`、`Missing inputs`、`Not applicable`、`Not evaluated`。`Difference` 和必需输入缺失不能直接发布；个别可选附注缺口只有记录依据并符合规则条件时可接受。对报告未完整拆分 PAA／非 PAA 的方法规则，选择 `Not applicable` 前，必须写明原因和**原附注的物理 PDF 页码**。`Not evaluated` 通常表示该可选规则没有可映射来源，不能把它当成已验证相等。

### 5.3 Excel 平行核查与发布

`Download check Excel` 包含 `Records`、`Cell checks`、`Excel arithmetic`、`Check plan`、`PDF source checks`、`Manual source review`、`Checks`、`Rule catalogue` 和 `Read me` 等工作表。Excel 内有逐格和完整勾稽公式，打开后由 Excel 重新计算；`Checks` 是下载时快照。人工核对原 PDF 的结果可填 `Manual source review` 的观测金额、单位、年份、行、列、口径和 reviewer note。仅修改例外说明与人工来源观察；如 `Records` 金额需要更正，先回 Step 2 导入或编辑。

在 `Upload checked Excel` 上传文件，勾选 `I checked the Excel cell and reconciliation formulas against the source report` 后点击 `Import checked Excel`。平台会核对工作簿结构、来源观察，并**独立重算**规则，不盲信 Excel 公式缓存；导入通过后仍需点击 `Publish checked filing`。若 `Cells to investigate` 非零或规则尚未解决，发布会指出首个需处理的格子。成功发布把符合条件的候选转为 Verified，并自动刷新 Step 4 的整合快照。

## 六、Step 4–6：整合和分析

### Step 4 · Integrate

`Source coverage` 展示已发布公司、年度、币种和口径。Step 3 发布会自动刷新**全部已发布报告**的整合数据；在本页可通过 `Published filings to include` 选择子集，再点击 `Build integrated dataset` 重建并激活当前会话。`Cross-filing validation` 展示每份报告内部的规则状态，不跨不同公司或口径相加。`Download integrated Excel` 导出整合记录、覆盖率和检查表。

整合保留原表币种、原值及单位，另设 HKD 比较金额；USD 转换使用对应年度的 12 月 31 日汇率资料。缺少该年度汇率时，相应 USD 数据不能作为 HKD 比较值展示。整合绝不把不同报表口径强行合并。

### Step 5 · Insurer explorer

若提示已有保存数据但当前会话未激活，点击 `Use saved verified data`。选择 insurer 并点击 `Display selected insurer`；左侧模块导航可查看单家公司图表、底层来源和原 PDF 页，按界面选项导出报告。也可在 `Upload reviewed Excel data for Steps 5 and 6` 导入符合结构的外部已核查工作簿，平台会重算单位与规则。`Preview unpublished pilot transcriptions` 默认为关闭；打开后只是带标识的 Pending 预览，不代表发布结果。

### Step 6 · Peer comparison

先激活已保存数据；在 `Core configuration panel` 选择年度截止日组、`Reporting scope`、公司、期间、币种显示方式、单位和小数位，再选择图表模块。比较应保持实体口径一致。以 Sun Life 为例，2024 集团报告与 2025 公司报告在平台中是不同口径身份；若要同口径同比，应优先使用同一份 2025 公司报告所披露的 2025／2024 两列。页面提供底层单元格及 CSV 下载；未披露数据不会被自动补零。

## 七、常见问题与处理

| 现象 | 检查和处理 |
| --- | --- |
| Step 1 没找到某附注表，或漏掉 100–102 续页 | 看失败扫描区间、诊断与原始页；缩小到财务报表／附注范围、每次 1–2 页重扫，或手工补入物理页；确认表格数字行和年份后再保存。 |
| 扫描版 PDF 定位慢 | 默认方法先用本地文本／OCR 索引减少送模页数；首次 OCR 建索引需要时间。按相关表和较小页段定位，保留诊断记录；密集表再用视觉扫描补漏。 |
| Step 2 `No mapped cells found` | 该表页可能只含标题／说明、指标范围不匹配，或图像不清。核对表名、续页、年份和列，必要时调整 Step 1 页码，再定向重试。 |
| `Draft cells` 每次变多 | 它计数已发现的“期间 × 指标”记录，不是固定格数。用表格概览与 `Records` 核对新增代码、年度和原页；重复的同键提取应替换 Pending，而不是生成无穷副本。 |
| Step 3 图像核查按钮灰色 | 检查是否存在待查格子、是否勾选发送确认，以及共享模型连接是否完整；换浏览器会话后需重填 API key。 |
| 主表与附注都为集团，却出现 Company 冲突 | 看主表标题和附注是否明确切换实体；旧模型结果可能把公司页眉误作 Company 口径。使用新的图像复核并查看 `Scope basis`；同时核对相容的主表—附注总额。 |
| Step 3 算术差、缺失输入或不能 Publish | 在 `Automatic investigation` 找到具体规则、页码及指标；回 Step 2 改错源值／年份／列／单位，或补披露格子；真正未披露的可选项写附注页和原因。发布会显示第一个阻塞格子。 |
| Excel 上传被拒绝 | Step 2 的 Excel 只应包含当前报告；Step 3 工作簿公式和结构不能删，`Records` 与已送检源格必须一致。需要修改原值时先在 Step 2 完成，再重新下载 Step 3 Excel。 |
| Step 5／6 没有数据 | 先确认 Step 3 已发布、Step 4 有当前整合快照，再在 Step 5／6 点击 `Use saved verified data`，或回 Step 4 `Build integrated dataset` 激活。 |

## 八、来源数据和审核状态说明

一条来源记录的关键字段是报告 ID、期间、指标代码、原值、原单位、物理 PDF 页、原文行／列／表题、表格年份、证据区域和审核状态。平台使用“报告 ID × 期间 × 指标代码”识别一个目标单元格；金额百万数由原值和单位重新换算。百分比保持印刷的百分数，例如 `3.44%` 记录为 `3.44` 与 `percent`，不记为 `0.0344`。

`Pending` 表示尚未在 Step 2 人工确认，但可送 Step 3 核查；`Verified` 为完成相应审核／发布的来源记录；`Excluded` 不进入后续分析。`Match` 只代表相应 PDF 图像核查一致，不能代替与其他指标的口径判断。`Pass` 代表适用的数值关系成立；如果没有同口径、同年度、同合同群组的来源，不能为了获得 Pass 而拼接、倒推或改写原表金额。

