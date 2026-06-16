# Strategy Patch — 字段契约

写到 spec 的 `expected_output_paths.strategy_patch` 路径。平台用一个**严格白名单**校验：出现任何白名单以外的字段，整个 patch 被拒（`StrategyPatchError`），你的复盘不生效。

## 只允许这 7 个字段（多一个就被拒）

```json
{
  "effective_sources": ["成功 fetch 的 source 描述，含类型或域名"],
  "avoid_sources": ["<domain> — <failure_reason: 403 / 404 / bot-blocked / login-required>"],
  "effective_query_patterns": ["产出真实 JD URL 的 query 模式"],
  "avoid_query_patterns": ["只返回搜索结果页的 query 模式"],
  "coverage_by_workstream": { "<workstream_label>": "sufficient | weak | missing" },
  "key_learnings": ["本轮新发现"],
  "recommended_next_searches": ["下一轮优先方向，对应 missing / weak workstream"]
}
```

空 patch（`{}`）也合法。

## 合并语义（决定你写「增量」还是「全量」）

- **list 字段 union 合并**（累积，不替换）：`effective_sources`、`avoid_sources`、`effective_query_patterns`、`avoid_query_patterns`、`key_learnings`。→ 只写本轮**新增**的即可。
- **`recommended_next_searches` 整体替换**：写出你希望下一轮看到的**完整**列表。
- **`coverage_by_workstream` 按 key 更新**：只动你这轮有结论的 workstream。

## coverage_by_workstream 的 key 约束

key **必须是 `configs/workstream_taxonomy.yaml` 里的合法 workstream label**（value 取 `sufficient` / `weak` / `missing`）。这条目前**没有运行时校验兜底**——靠你保证。先读 taxonomy 配置确认合法 label 再写。
