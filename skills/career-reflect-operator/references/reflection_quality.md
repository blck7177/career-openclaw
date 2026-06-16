# Reflection Quality 标准

reflect 这一步几乎没有运行时校验（平台只校验 patch 顶层字段名）。因此**质量护栏全靠这份规范**——写得泛、写得没证据，平台也会照单落库，污染下一轮策略。

## strategy_patch.json 质量

- **`avoid_sources` 必须说明 failure reason**：`403` / `404` / `bot-blocked` / `login-required`。没有 evidence 的源**不要**降权。
- **`recommended_next_searches` 必须对应具体的 missing / weak workstream**，不能是「多搜一些」这类泛化建议。
- **只降有明确 failure evidence 的源**；unknown / 没试过的 source 不要降权。
- list 字段只写本轮**新增**的（平台会 union 合并，见 `strategy_patch_contract.md`）。

## reflection_report.md 质量

写到 spec 的 `expected_output_paths.reflection_report` 路径，简短即可：

- **本轮结论**：jobs saved / failed、候选质量、各 workstream 覆盖。
- **失败诊断**：哪些 source 整源被墙、哪些 query pattern 只出搜索结果页。
- **下一轮建议**：优先补哪个 workstream、用哪些有效 source / query pattern。

写完两个文件即结束。
