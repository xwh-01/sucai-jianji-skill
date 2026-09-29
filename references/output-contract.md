# 输出合同

## 分阶段交付

- 仅剧本模式：保存 `script-plan.md`，按用户请求列出开头文字锚点、候选比较、暂定版本路径、观众证据与待核实项。没有真实定位时不填数值秒数；不要求视频、最终标题或最终计划校验通过。
- 媒体定位或规划中途：已有索引与候选照常保存，未完成判断写入 `report.md`；不得将草案改称最终 `edit-plan.json` 来绕过状态限制。
- 完整模式：以下文件按主流程逐阶段产生；第 6 阶段完成后才形成可提交校验的最终 `edit-plan.json`。第 8 阶段核验所有已生成文件和视频后才能声明完整交付。

## 必需文件

### `source-manifest.json`

记录剧本来源、收费点范围、可用和缺失集数，以及每个视频的本地路径、时长和指纹。另记录 FFmpeg/FFprobe 与 MediaKit CLI 的路径和版本、ASR Cloud 模式，并为每集记录 MediaKit 任务 ID、识别语言、来源指纹、结果时长及原始结果文件路径；失败时保存真实状态和错误，不生成伪转写。

### `opening-candidates.json`

保存全部去重候选及直接比较结论。不得包含多维主观分数。

### `selected-openings.json`

保存恰好 3 个已锁定开头的 ID、锚点、开头窗口、真实时间证据、上下文缺口和待视频检查项。

```json
{
  "selected_openings": [
    { "candidate_id": "opening-001" },
    { "candidate_id": "opening-002" },
    { "candidate_id": "opening-003" }
  ]
}
```

数组长度必须为 3，且三个候选不能属于同一个重叠事件窗口。完整候选内容可直接内嵌，或通过 `candidate_id` 引用 `opening-candidates.json`。

### 每个开头的子目录

为三个选中开头分别建立以候选 ID 命名的子目录。每个子目录保存一份 `selected-opening.json`、一份 `edit-plan.json`、一条连续版粗剪、通过可行性判断时再增加一条冷开回接版粗剪，以及独立审阅记录。`edit-plan.json` 仍只描述当前子目录对应的一个开头，并单独运行校验器。

### `edit-plan.json`

下面仅展示字段结构，空 `ranges`、空事件清单和示意文字不构成可校验计划，不能原样提交。[validated-example.json](validated-example.json) 为旧版历史案例，缺少新版覆盖证据，不能直接通过当前校验；可运行的合成结构示例见 `scripts/test_validate_edit_plan.py`。实际执行必须使用当前项目证据，不复制案例剧情或核查结果。

```json
{
  "schema_version": "1.9",
  "case_id": "example",
  "scope": {
    "kind": "pre_paywall",
    "episodes": [1, 2, 3, 4]
  },
  "selected_opening": {
    "candidate_id": "opening-001",
    "source_video": "/absolute/path/EP3.mp4",
    "episode": 3,
    "start": 26.5,
    "end": 47.14,
    "context_gap": "none"
  },
  "cold_open_eligibility": {
    "evaluated_after_opening_locked": true,
    "eligible": true,
    "reason_code": "eligible",
    "reason": "存在与开头直接相关的前情、自然入口、干净追上、冷开结尾回声与新剧情恢复点，并能增加情绪和信息价值。",
    "checks": {
      "prior_context_exists": true,
      "causal_context_exists": true,
      "natural_entry_exists": true,
      "clean_catchup_exists": true,
      "adds_viewing_value": true
    }
  },
  "variants": [
    {
      "id": "continuous",
      "target_duration": 150,
      "opening_headline": {
        "lines": [
          "SHE PUT A KNIFE TO HER EX'S",
          "BILLIONAIRE BOSS...",
          "THEN AWAKENED THE BEAST INSIDE HIM."
        ],
        "generation": "automatic_final",
        "generation_stage": "after_story_ranges_locked",
        "purpose": "retention_hook",
        "rationale": "现有台词和画面已足够理解，字幕负责承诺后续欲望升级。",
        "affects_range_selection": false,
        "position": "top_center",
        "background": "none",
        "design_mode": "automatic_scene_adaptive",
        "sample_window": 4.0,
        "base_color": "#F7F7F4",
        "accent_color": "#F4C542",
        "accent_target": "line_3",
        "outline": "light_black",
        "qa": {
          "readability_passed": true,
          "subject_overlap_passed": true,
          "source_text_overlap_passed": true,
          "fallback_used": false
        },
        "hold_duration": 3.0,
        "fade_duration": 1.0
      },
      "end_hold": {
        "kind": "freeze_last_frame",
        "duration": 1.0,
        "visual": "shake",
        "audio": {
          "kind": "impact_clip",
          "source_video": "/absolute/path/EP3.mp4",
          "start": 99.25,
          "end": 100.25,
          "gain": 1.0,
          "speed": 1.0,
          "contains_speech": false,
          "overlaps_story_tail": false
        }
      },
      "ranges": [],
      "ending_hook": "具体内容",
      "video_checks": []
    },
    {
      "id": "cold_open",
      "target_duration": 150,
      "opening_headline": {
        "lines": [
          "SHE PUT A KNIFE TO HER EX'S",
          "BILLIONAIRE BOSS...",
          "THEN AWAKENED THE BEAST INSIDE HIM."
        ],
        "generation": "automatic_final",
        "generation_stage": "after_story_ranges_locked",
        "purpose": "retention_hook",
        "rationale": "现有台词和画面已足够理解，字幕负责承诺后续欲望升级。",
        "affects_range_selection": false,
        "position": "top_center",
        "background": "none",
        "design_mode": "automatic_scene_adaptive",
        "sample_window": 4.0,
        "base_color": "#F7F7F4",
        "accent_color": "#F4C542",
        "accent_target": "line_3",
        "outline": "light_black",
        "qa": {
          "readability_passed": true,
          "subject_overlap_passed": true,
          "source_text_overlap_passed": true,
          "fallback_used": false
        },
        "hold_duration": 3.0,
        "fade_duration": 1.0
      },
      "reset_transition": {
        "kind": "freeze_then_question_card_then_rewind",
        "freeze": {
          "duration": 0.8,
          "visual": "static",
          "audio": "silence"
        },
        "card": {
          "duration": 2.0,
          "background": "black",
          "audio": "silence",
          "text": {
            "line_1": "HOW DID SHE",
            "line_2": "END UP HERE?"
          },
          "design": "two_line_centered"
        },
        "rewind": {
          "duration": 1.0,
          "source_role": "reset_context",
          "coverage": "full_range",
          "audio": "rewind_sfx",
          "landing": "first_frame",
          "resume": "second_frame"
        }
      },
      "end_hold": {
        "kind": "freeze_last_frame",
        "duration": 1.0,
        "visual": "shake",
        "audio": {
          "kind": "impact_clip",
          "source_video": "/absolute/path/EP3.mp4",
          "start": 99.25,
          "end": 100.25,
          "gain": 1.0,
          "speed": 1.0,
          "contains_speech": false,
          "overlaps_story_tail": false
        }
      },
      "context_entry_decision": {
        "entry_search": {
          "scope_start": "待填写：授权范围正文起点",
          "scope_end": "待填写：开头前的正文终点",
          "source_evidence": "待填写：实际通读及核实记录",
          "events": [],
          "absent_layers": {}
        },
        "earlier_prefix_review": [],
        "selection_rule": "best_narrative_arc_covering_full_causal_chain",
        "hook_question": "为什么凯西会和亚瑟在房间里假装发生关系？",
        "causal_chain": [
          {
            "type": "direct_cause",
            "beat": "亚瑟提议用假叫床反击门外的挑衅者"
          },
          {
            "type": "motivation",
            "beat": "凯西受辱后想让门外的人相信她已经反击成功"
          },
          {
            "type": "relationship_context",
            "beat": "凯西与亚瑟彼此敌对，却被迫临时合作"
          }
        ],
        "selected_entry": "EP3 场景开始：女主情绪失控回到房间",
        "selection_reason": "较早的场景入口让受辱情绪、临时合作和反击行动逐级升级，回到开头时既有因果闭环也有情绪兑现。",
        "narrative_unit": "受辱后的情绪积累、抓裤腰和开头事件形成完整因果",
        "viewer_evidence": {
          "status": "video_verified",
          "dialogue_evidence": ["实际 ASR 已确认的相关对白"],
          "visual_evidence": ["实际视频已确认的相关动作"],
          "excluded_script_information": ["人物小传中的身份标签未用于判断"]
        },
        "compared_entries": [
          {
            "entry": "EP3 开头前一句对白",
            "start_event_id": "待引用已登记的直接触发事件",
            "boundary_type": "latest_complete",
            "causal_chain_complete": true,
            "story_arc": "只完成假演提议和动作解释，缺少冲突建立与情绪升级。",
            "information_gained": "说明假演的直接原因。",
            "retention_beats": ["提出假演反击"],
            "dead_zone_risk": "low",
            "emotional_build": false,
            "return_effect": "能理解，但像解释补丁，重新撞回开头过快。",
            "selected": false
          },
          {
            "entry": "EP3 场景开始：女主情绪失控回到房间",
            "start_event_id": "待引用已登记的关系或冲突事件",
            "boundary_type": "emotional_or_relationship_setup",
            "causal_chain_complete": true,
            "story_arc": "完成受辱、冲突、临时合作、反击升级和回到开头。",
            "information_gained": "建立受辱原因、临时合作和反击动机。",
            "retention_beats": ["受辱失控", "女配追上门", "假演反击"],
            "dead_zone_risk": "none",
            "emotional_build": true,
            "return_effect": "回到开头时同时兑现人物情绪和行动因果。",
            "selected": true
          }
        ],
        "forward_check": {
          "standalone_entry": true,
          "causal_chain_complete": true,
          "narrative_arc_complete": true,
          "emotional_investment_before_catchup": true,
          "change_before_catchup": true,
          "clean_opening_echo_and_resume": true
        },
        "post_opening_stop": {
          "rule": "first_new_suspense_after_payoff",
          "description": "假演爆点完成后，停在新的亲密教学要求即将开始"
        },
        "rejected_later_entries": []
      },
      "ranges": [],
      "ending_hook": "具体内容",
      "context_added": [],
      "video_checks": []
    }
  ]
}
```

`cold_open_eligibility` 必须在开头锁定后生成，且不得改变 `selected_opening`。`reason_code` 只能是：

- `eligible`
- `no_prior_context`
- `no_causal_context`
- `no_natural_entry`
- `no_clean_catchup`
- `no_added_value`

`eligible: true` 时，五个 `checks` 必须全部为 `true`，`variants` 必须同时包含 `continuous` 和 `cold_open`。`eligible: false` 时，`reason_code` 必须对应至少一个失败检查，`variants` 只能包含 `continuous`；不得输出空壳冷开回接版，也不得为了使其成立而替换开头。

每个 `ranges` 元素必须包含：

```json
{
  "source_video": "/absolute/path/EP3.mp4",
  "episode": 3,
  "start": 26.5,
  "end": 47.14,
  "role": "opening_window",
  "entry_reason": "为什么从这里进入",
  "exit_reason": "为什么在这里结束"
}
```

允许的 `role`：

- `opening_window`
- `continuous_story`
- `reset_context`
- `opening_echo`
- `resume_after_opening`
- `ending_hook`

`start` 和 `end` 使用源视频秒数，不使用拼接后时间。区间统一为 `[start, end)`，必须满足 `0 <= start < end`。冻结帧取 `end` 前最后一个实际保留帧，不取 `end` 处首个被排除帧。

冷开回接版的 `ranges` 必须按 `opening_window -> reset_context -> opening_echo -> resume_after_opening` 开始。`opening_echo` 必须且只能出现一次，是 `opening_window` 结尾的连续真子区间：来源、集数和终点与开头一致，起点晚于开头起点。它额外包含 `echo_type`（只能是 `last_line` 或 `last_action`）和非空的 `echo_content`，明确记录重复的最后一句或最后一个动作；不得用它重播整个冷开。

每个实际生成的版本都必须包含 `opening_headline`；冷开回接版存在时，与同一开头的连续版使用完全相同的三行文案和设计。`generation` 固定为 `automatic_final`，`generation_stage` 固定为 `after_story_ranges_locked`，`affects_range_selection` 固定为 `false`：系统必须先锁定全部剧情区间，再直接生成最终文案，不等待人工选稿，也不得反向改变开头或冷开回接版第二段。

`purpose` 只能是 `necessary_context` 或 `retention_hook`，并在 `rationale` 中说明判断。只有最终成片的可听台词、可见画面和画面内可读文字仍缺少必要身份、关系或处境事实时，才使用 `necessary_context`；理解已经成立时必须使用 `retention_hook`，准确承诺后续强反转或危险结果。人物小传、梗概和未被成片表达的剧本备注不能算作观众已知信息。

`design_mode` 固定为 `automatic_scene_adaptive`。标题位于顶部、无矩形底框、前两行使用 `base_color`、第三行使用 `accent_color`，并保留轻黑描边；完整显示 `3.0` 秒后用 `1.0` 秒淡出。

`sample_window` 固定为 `4.0` 秒。`base_color` 和 `accent_color` 必须记录为 `#RRGGBB`，且不能相同。`qa` 必须确认代表帧可读性、人物避让和原片文字避让均通过；若自动调整颜色、断句和字号后仍需使用白色加暖黄色默认方案，才把 `fallback_used` 设为 `true`。不能因为全自动而省略这些设计记录，也不能把人工确认设置为必需步骤。

`reset_transition` 只属于冷开回接版，由 `0.8` 秒静态末帧、`2.0` 秒黑屏问题字幕卡和 `1.0` 秒完整前情快速倒放组成。静帧和字幕卡静音；问题字幕使用一到两行短问句承接开头留下的未知；倒放覆盖 `reset_context` 全区间，落回第一帧，并从第二帧开始正常播放。每个版本都必须包含 `end_hold`：`duration` 固定为 `1.0`，`visual` 固定为 `shake`。默认 `audio.kind` 为 `impact_clip`，优先引用承载当前结尾的原剧集文件最后 `1.0` 秒，并记录绝对路径、起止时间、`gain: 1.0`、`speed: 1.0`、`contains_speech: false` 和 `overlaps_story_tail: false`；`audio.end - audio.start` 必须等于 `1.0`。没有合格鼓点或撞击尾音时允许 `audio.kind: silence`。开头标题、静帧、字幕卡、倒放和片尾冻结不属于源视频剧情区间，因此不写入 `ranges`；计算实际输出时长时必须计入这些包装段。

冷开回接版必须包含 `context_entry_decision`：

- `selection_rule`：固定为 `best_narrative_arc_covering_full_causal_chain`；必要因果链只是理解门槛，最终按连续剧情弧、情绪积累和回接体验选择，不默认偏向最晚入口。
- `hook_question`：开头留下的核心未知，必须是具体问题。
- `causal_chain`：按直接原因、人物动机、必要关系背景记录不可删除的节点；至少包含 `direct_cause` 和 `motivation`，只有理解动机确实需要时才加入 `relationship_context`。
- `selected_entry`：从候选中选出的自然叙事入口，不只写时间码。
- `selection_reason`：说明所选入口相对其他候选在剧情弧、情绪积累和回接效果上的具体优势，不能只写“信息更完整”或“离开头更近”。
- `narrative_unit`：从该入口开始能够完整建立的行动、冲突或情绪过程。
- `viewer_evidence`：将证据严格拆成 `dialogue_evidence`、`visual_evidence` 和 `excluded_script_information`。`status` 只能是 `script_only_unverified`、`asr_only_unverified` 或 `video_verified`；只有 `video_verified` 才能把最终入口理解检查标记为完成。纯剧本阶段可把明确面向观众的对白、动作、表情、道具、特效、环境声和画面文字分别写入前两类并注明待核实；人物小传、隐藏身份、内心活动、作者解释及未外化的身份、关系和动机只能进入排除项。
- `entry_search`：在选择入口前完成。`scope_start`、`scope_end` 为实际检查的授权范围起点与开头前终点的文字锚点，`source_evidence` 指向已读正文及核实记录；不得拿选中的入口充当搜索起点。`events` 按源剧情时间顺序登记相关事件，每项含唯一 `id`、`anchor`、`layers`、`connection`、`viewer_evidence`、`disposition`。`layers` 为 `relationship_setup`、`conflict_origin`、`direct_trigger` 中的一项或多项；`disposition` 为 `compare` 或 `exclude`，后者必须有具体 `exclusion_reason`。`absent_layers` 为未出现层次到缺失原因的映射，三层均存在时为 `{}`。同一事件承担多个层次应合并，不用相邻切点虚构独立候选。
- `compared_entries`：包含所有登记为 `compare` 的真实入口，每项以唯一 `start_event_id` 引用事件，并保留最晚完整入口。只有一个入口时也必须完整记录搜索及其他层次缺失、合并或排除原因。每项记录 `entry`、`boundary_type`、`causal_chain_complete`、`story_arc`、`information_gained`、`retention_beats`、`dead_zone_risk`、`emotional_build`、`return_effect` 和 `selected`。`retention_beats` 记录具体刺激、反转或关系变化，不做数值评分；`dead_zone_risk` 只能是 `none`、`low` 或 `high`。恰好一项被选中并与 `selected_entry` 一致，选中项不能是 `high`。
- `earlier_prefix_review`：对每个比选中入口更早的正式候选，记录 `event_id`、`added_information`、`retention_value`、`connection`、`cost`、`rejection_reason`，说明新增前缀的观众信息、刺激/反转、与开头联系、无推进/旁支成本和最终排除理由。选中最早候选时为 `[]`；事件清单中未进入比较的更早事件仍须有 `exclusion_reason`。
- `forward_check`：`standalone_entry`、`causal_chain_complete`、`narrative_arc_complete`、`emotional_investment_before_catchup`、`change_before_catchup` 和 `clean_opening_echo_and_resume` 必须全部为 `true`，否则继续向前扩展一个自然叙事单元或重新精修回声与恢复点。
- `post_opening_stop`：`rule` 固定为 `first_new_suspense_after_payoff`，`description` 说明爆点兑现后出现的第一个新悬疑；不能把尚未解决的开头原有问题当成新悬疑。
- `rejected_later_entries`：仅记录连必要因果链或自然边界门槛都未通过、因此没有进入正式比较的更晚入口；正式比较过的入口统一写入 `compared_entries`。

### `review.md`

入口资格（`forward_check`）与搜索覆盖（`entry_search` 及前缀比较）分别验收。校验器只检查记录结构和引用一致性，无法发现未登记的真实剧情、证明证据真实性或评价吸引力。执行者必须用完整正文核对清单；旧计划缺少覆盖记录时应重新审查，禁止自动补写“已查全”。纯剧本模式在 `script-plan.md` 中保存相同逻辑的文字记录，不伪造秒数或视频核实状态。

至少记录：

- 冷开回接可行性五项检查、结果、原因码和证据，并确认判断发生在开头锁定之后且没有改变开头。
- 所有实际生成版本各自的内容路径和总时长。
- 所有实际生成版本头顶字幕的用途、生成阶段、不影响选段的确认、自动生成文案、实际基础色和强调色、代表帧自动质检结果、`3.0` 秒保持和 `1.0` 秒淡出结果。
- 冷开回接版存在时，记录 `0.8` 秒静帧、`2.0` 秒问题字幕卡、`1.0` 秒倒放和两版末帧冻结的实际渲染结果，包括问题字幕文案、倒放落点、冻结时长与静音/音效来源及检查结果。
- 冷开回接版存在时，记录它补充的必要信息及其时长成本。
- 冷开回接版存在时，记录开头留下的核心问题、必要因果链、比较过的自然入口、最终选择理由、完整剧情弧检查、实际重复的最后一句或最后一个动作，以及爆点后的第一个新悬疑停点。
- 所有实际生成版本的尾钩。
- 实际检查过的连接点。
- 黑场、重复、动作中断或工具限制。
- 当前开头供人工观看的 1 至 2 个本地视频路径；根目录汇总报告列出三个开头实际生成的全部 3 至 6 条视频。

### `boundary-review/boundary-refinement.json`

每个开头目录必须按 [boundary-refinement.md](boundary-refinement.md) 保存一份切口精修记录。它覆盖该开头实际生成版本中的所有开始点、结束点和非连续连接，至少记录近似时间、语义合法区间、最终源时间、源帧号、切口用途、置信度、选择理由、检查项和候选点。高置信度切口允许不生成候选预览；`medium` 必须有实际检查的预览及通过依据；`low` 只能记录为失败尝试，重新精修通过前不能进入最终已锁定边界。

`edit-plan.json` 中的 `ranges.start`、`ranges.end` 和 `selected_opening` 边界必须与该文件最终锁定的时间一致。该记录只精修已有剧情边界，不得改变开头、冷开回接入口、剧情路径或尾钩语义。

## 状态规则

- 已锁定但未完成 ASR：使用文字锚点，不填写虚假数值时间。
- 已完成 ASR但未看视频：时间可标记为 `asr_aligned`，不能标记 `video_verified`。
- 视频确认后才允许把边界状态设为 `video_verified`。
- 上游决定需要改变时，明确记录回退原因并更新依赖产物，不能静默覆盖。
