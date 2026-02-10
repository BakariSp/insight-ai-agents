"""Block type schemas for LLM system prompt injection.

These schemas tell the LLM what structured block types are available
and how to output them using ```block:type JSON fences.
The frontend ReportRenderer already supports all these block types.
"""

BLOCK_SCHEMA_PROMPT = r'''
## 可用的结构化 Block 类型

你可以在报告中使用以下结构化 block。使用 ```block:类型名 包裹 JSON 输出。
block 之间可以穿插普通 markdown 文字作为分析叙述。

### kpi_grid — KPI 指标卡片
适用: 展示关键统计指标 (平均分、及格率、提交率等)

```block:kpi_grid
{
  "data": [
    {"label": "平均分", "value": 72.5, "status": "up", "subtext": "较上次 +5.2"},
    {"label": "及格率", "value": "85%", "status": "up", "subtext": "提升显著"},
    {"label": "最高分", "value": 98, "status": "neutral"},
    {"label": "提交率", "value": "92%", "status": "down", "subtext": "3人未交"}
  ]
}
```

status 取值: "up" (好/上升), "down" (差/下降), "neutral" (中性)
value 可以是数字或字符串 (如 "85%")

### chart — 数据图表
适用: 分数分布、趋势对比、占比分析

```block:chart
{
  "variant": "bar",
  "title": "分数段分布",
  "xAxis": ["0-60", "60-70", "70-80", "80-90", "90-100"],
  "series": [{"name": "人数", "data": [3, 5, 12, 8, 2]}]
}
```

variant 取值: "bar" (柱状图), "line" (折线图), "pie" (饼图), "radar" (雷达图), "distribution" (横向分布)

### table — 数据表格
适用: 学生明细、成绩排名、错题列表

```block:table
{
  "title": "学生成绩明细",
  "headers": ["排名", "姓名", "分数", "评价"],
  "rows": [
    {"cells": [1, "张三", 95, "优秀"], "status": "success"},
    {"cells": [2, "李四", 62, "及格"], "status": "normal"},
    {"cells": [3, "王五", 45, "不及格"], "status": "warning"}
  ],
  "highlightRules": [
    {"column": 2, "condition": "below", "value": 60, "style": "warning"}
  ]
}
```

row.status 取值: "normal", "warning", "success", "error"
highlightRules 可选，用于自动高亮特定列的值

### suggestion_list — 教学建议列表
适用: 改进建议、行动计划、关注事项

```block:suggestion_list
{
  "title": "教学建议",
  "items": [
    {"title": "加强基础概念训练", "description": "多数学生在基础题上失分严重，建议增加课堂练习", "priority": "high", "category": "教学建议"},
    {"title": "关注落后学生", "description": "3名学生成绩持续下滑，建议个别辅导", "priority": "medium", "category": "关注学生"}
  ]
}
```

priority 取值: "high" (高优先), "medium" (中), "low" (低)

### markdown (特殊样式)
直接写的文字自动变成普通 markdown block。如需特殊样式 (高亮提示):

```block:markdown
{"content": "全班及格率显著下降，需重点关注！", "variant": "warning"}
```

variant 取值: "default", "insight" (蓝色洞察), "warning" (橙色警告), "success" (绿色成功)

## 输出规则

1. 每个 tab 用 `## [TAB:key] label` 开头
2. tab 内混合使用 ```block:类型名 和普通 markdown 文字
3. 数据展示**优先用结构化 block** (kpi_grid/chart/table)，分析文字用 markdown
4. 不要把所有内容都塞进一个 block，合理拆分
5. JSON 必须是合法格式，不要有注释或尾逗号
6. 每个 ```block:xxx 必须用 ``` 结尾闭合
'''
