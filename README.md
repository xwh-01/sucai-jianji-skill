# Short Drama Ad Planner

This repository is also an installable skill. Keep the entire directory together.

## 首次使用

Codex 先按 [环境配置引导](references/setup.md) 自动检查依赖，只提示缺失项：FFmpeg/FFprobe 已随 Skill 内置，无需填写路径；Swift 编译环境和 MediaKit CLI 缺失才提示安装。当前包支持 macOS Apple Silicon。

MediaKit Cloud ASR 需要运行环境中的 `MEDIAKIT_API_KEY`，已有配置直接复用。缺失时引导在本机配置，不要求把密钥发到聊天里，不写入项目或交付包。只检查变量存在不等于云端鉴权成功，检查阶段不上传素材或提交 ASR。纯剧本任务跳过这些媒体依赖。

## 制作前确认两个选项

提供剧本和对应视频后，Codex 会先问：“这次选几个开头？是否开启冷开版？”收到回答后再开始处理。也可以直接说明，已说明的选项不重复问：

- “选 2 个开头，只做连续版。”
- “选 1 个开头，开启冷开版。”

明确回答“按默认”时选 3 个开头、开启冷开；未说明时不会静默采用默认值。续跑已有任务沿用已冻结选择。开头数量是不同事件的数量，不是视频数量。
选 N 个开头，关闭冷开生成 N 条连续版；开启冷开按原可行性标准生成 N 至 2N 条，不能为了凑双版本硬做。
配置不会改变选段、标题包装、边界或声画检查标准，不会重写旧成品。
这是供 Codex 执行的 Skill 与命令行链路，尚不是独立图形界面应用。

运行配置支持 `"opening_count": 2` 和 `"cold_open_enabled": false`；也可初始化时指定：

```sh
python3 scripts/workflow.py /absolute/new-run init /absolute/config.json --opening-count 2 --cold-open off
```

数量须为正整数，开关接受 `on/off`。初始化后选项冻结，修改需另建运行；`status` 可查看生效设置。

## Project structure

```text
SKILL.md                  Skill entry and editorial workflow
agents/                   Skill discovery metadata
references/               Editorial rules, output contract and validated example
scripts/                  Stable command entry points
pipeline/validation.py    Edit-plan validation implementation
pipeline/workflow.py      Stage gates, locked decisions, resumable jobs and delivery
pipeline/baseline.py      Compile locked ranges into matching video/audio cuts
pipeline/media_checks.py  Read-only FFprobe/FFmpeg technical checks
pipeline/content_review.py Required continuous audiovisual review windows
pipeline/render/          Swift title, rewind and ending implementations
tests/                    Regression and compatibility tests
bin/macos-arm64/          Existing FFmpeg and FFprobe binaries
```

The existing commands in `scripts/` remain supported. Swift entry points are
relative symlinks to `pipeline/render/`; preserve symlinks when copying the skill.
The Python validator forwards to `pipeline.validation` and works from any working
directory. `scripts/with_ffmpeg.sh` remains the binary launcher.

## Verification

Run from the repository root:

```sh
python3 -m unittest discover -s tests -t .
```

The previous test command remains supported:

```sh
python3 -m unittest discover -s scripts -p 'test_*.py'
```

Default tests do not call ASR services or render videos. Source footage, run directories,
finished videos and delivery archives remain outside this skill repository.

The historical `references/validated-example.json` currently fails the existing
validator because one variant lacks `context_entry_decision.entry_search`.
Compatibility tests preserve that original result; this restructure does not
update historical examples or relax validation rules.

## Structured workflow

Follow [references/workflow.md](references/workflow.md) for configuration,
evidence receipts, per-stage contracts and recovery. The workflow manages the
existing editorial process; it is not a replacement for actual video review.

```sh
python3 scripts/workflow.py /absolute/new-run init /absolute/config.json
python3 scripts/workflow.py /absolute/new-run status
python3 scripts/workflow.py /absolute/new-run begin intake
```

After the evidence-gated planning stages finish, `render` executes the frozen
baseline recipes and unchanged Swift renderers. `inspect` performs read-only
technical checks. `package` delivers only reviewed outputs and seals the run.
Baselines use structured settings and compile both video and audio directly from
locked intervals; free-form timeline argv is rejected. Technical reports are
registered by `inspect`, and content review must cover the generated playback
windows for the exact video and plan revision. These checks do not substitute
for actually watching and listening to those windows.
Existing source footage, completed projects and delivery archives are never
adopted or overwritten in place.

Validation supports the configured opening count and cold-open policy while
preserving the default editorial checks. Swift rendering implementations and
bundled binaries are unchanged. Baseline encoding options are explicitly recorded
in each reviewed recipe, not replaced with a new global preset.

Run the opt-in real-render smoke test on macOS Apple Silicon with Xcode tools:

```sh
SUCAI_RENDER_SMOKE=1 python3 -m unittest tests.test_render_smoke -v
```

It creates short synthetic video/audio signals in a temporary directory, checks
the full wrapper sequence at 30000/1001 fps and verifies selected/reordered color
frames and audio frequencies. It never reads production footage.
