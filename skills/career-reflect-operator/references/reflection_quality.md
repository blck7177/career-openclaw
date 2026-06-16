# Reflection Quality 标准

reflect 这一步几乎没有运行时校验（平台只校验 patch 顶层字段名）。因此**质量护栏全靠这份规范**——写得泛、写得没证据，平台也会照单落库，污染下一轮策略。

---

## strategy_patch.json 质量

- **`avoid_sources` 必须说明 failure reason**：`403` / `404` / `bot-blocked` / `login-required`。没有 evidence 的源**不要**降权。
- **`recommended_next_searches` 必须对应具体的 missing / weak workstream**，不能是「多搜一些」这类泛化建议。每条建议尽量具体：公司名、title_keywords 放宽方向、替代 source 类型。
- **只降有明确 failure evidence 的源**；unknown / 没试过的 source 不要降权。
- list 字段只写本轮**新增**的（平台会 union 合并，见 `strategy_patch_contract.md`）。
- **`recommended_next_searches` 是整体替换**（见合并语义）——写出你希望下一轮看到的完整优先列表，不超过 5 条。

---

## reflection_report.md 质量

写到 spec 的 `expected_output_paths.reflection_report` 路径。**必须包含以下四节**（简短即可，但每节不能省略）：

### 1. Run Outcome

```
- Candidates captured: N
- Jobs saved to catalog: N / Jobs failed: N
- Overall result: [productive | no-yield | partial]
- No-yield reason（如果 candidates==0）：[过窄 filter / source blocked / query 无结果 / budget 耗尽]
```

### 2. Source Diagnosis

针对本轮用到的每类 source，给出结论：

```
- [source domain 或 board slug]: [effective / failed / partial]
  - 若 failed：failure mode（403 / 404 / bot-blocked / login-required / filter too narrow）
  - 若 filter too narrow：建议放宽的参数（title_keywords / location_filter）
  - 若 effective：抓到了哪类岗位（title 举例）
```

**这一节是 `avoid_sources` / `effective_sources` patch 的直接依据**——没有诊断就不要写降权。

### 3. Strategy Diagnosis

回答以下问题（有结论的写，没结论的跳过）：

```
- Title/location filter 是否太窄？→ 建议放宽方向
- Query terms 是否太宽/太窄？→ 有效 pattern 举例 + 无效 pattern 举例
- 是否有 board_sync 返回 0 但应该有结果的公司？→ 建议下轮改用 web_search 补充
- 是否有新发现的 ATS source（已注册或建议注册）？
- Budget 分配是否合理？（哪类 move 占比过高/过低）
```

### 4. Patch Summary

用一两句话说明你写了什么 patch、下一轮策略重点：

```
- patch 更新字段：[列出非空字段]
- 下一轮优先级：[1-2 句话，对应 recommended_next_searches 的逻辑]
```

---

写完两个文件即结束（不需要做 search，不需要跑 pipeline）。
