# Video to Game Sprites

把角色视频转换成透明 PNG 序列帧、图集、GIF/HTML 预览和 Godot 4 SpriteFrames。可选通过火山方舟 Seedance 从角色参考图生成视频，带本地预算预留和任务恢复机制。

抽帧、抠图、拼图集均在本地运行；云端视频生成另行收费。此仓库不包含游戏代码、角色素材、密钥或真实生成任务。

## 安装

需要 Python 3.11+。在仓库目录执行：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

通过 imageio-ffmpeg 提供视频解码器，无需手动安装系统 FFmpeg。依赖下载需要联网；安装后可离线转换本地视频。

## 本地视频转序列帧

```sh
python skill/scripts/video_to_sprite.py extract inputs/video.mp4 --out outputs/run/source
python skill/scripts/video_to_sprite.py prepare outputs/run/source --config skill/assets/matte-magenta.json --out outputs/run/matte
python skill/scripts/video_to_sprite.py build outputs/run/matte --config examples/clip.json --out outputs/run/sprites
```

先检查 source/overview.jpg，再调整起止帧。examples/clip.json 的 0–24 帧仅作配置示例，不代表任何视频的正确循环；end_exclusive 对应的时间戳必须存在。

- 新视频默认使用纯洋红背景，配套 matte-magenta.json。
- 已有灰底视频使用 examples/matte-gray.json 起步，按实际边缘调整。
- 输出目录应为新目录，工具拒绝覆盖既有结果。
- Godot 导入 animation.tres 时，需要一起复制 frames/ 目录。

详细参数：[抽帧与导出](skill/references/workflow.md)、[洋红背景流程](skill/references/chroma-workflow.md)。

## 可选：参考图生成视频

密钥仅从进程环境变量读取，变量名固定为 **SEEDDANCE_ARK_API_KEY**。可以沿用本机 shell 配置。或者复制空模板后自行填写：

```sh
cp .env.example .env
# 编辑 .env 填写真实密钥；不要提交或分享此文件。
set -a
source .env
set +a
python skill/scripts/ark_video.py doctor
```

工具不会自动加载 .env。不要把密钥放进命令行参数、提示词或截图。

用透明单人 PNG 准备洋红底参考图，并把背景模板合入动作提示词：

```sh
python skill/scripts/prepare_reference.py --image inputs/character.png --out inputs/reference-magenta.png
python skill/scripts/ark_video.py plan --image inputs/reference-magenta.png --prompt skill/assets/run-right-prompt.txt --out jobs/run-right
python skill/scripts/ark_video.py estimate jobs/run-right --policy skill/assets/cost-policy.json
```

检查 jobs/run-right/input.png 和 prompt.txt，确认构图、动作与背景。plan 不联网、不收费。确认自己的预算后才创建预算台账并 submit；命令见 [云端生成与费用控制](skill/references/ark-workflow.md)。

价格文件有有效期，过期会阻止新提交；需先核实平台价格再更新。用量折价不是平台账单或账户余额。提交结果不明时不要盲目重试；同一批任务共用一个预算台账。

## 测试

```sh
python -m unittest discover -s tests -p 'test_*.py'
```

测试使用本地临时文件和模拟 API，不消耗云端生成额度。自动检查不能代替动作、美术和循环衔接的视觉验收。

## 作为 Skill 使用

skill/ 是独立技能目录，可复制为本机 skills/video-to-game-sprites/。入口是 [SKILL.md](skill/SKILL.md)，安装时保留 scripts、references 与 assets 子目录。CLI 可以脱离任何 AI 助手使用。

## 目录与隐私

- skill/scripts/：生成、预算控制、抽帧、抠图、参考图准备。
- skill/assets/：提示词和通用配置模板。
- tests/：离线测试；examples/：配置示例。
- inputs/、outputs/、jobs/：建议的本地数据目录，已忽略。

.gitignore 同时忽略 .env、remote.json、任务状态、预算台账、日志、图片、视频和压缩包。remote.json 含带签名的下载链接，不应公开。未来若要加入公开示例素材，请先确认来源与内容，再针对明确文件调整忽略规则；不要提交实际任务目录。不要用 git add -f 绕过敏感文件规则。

从游戏项目拆分的 build_hero_refresh.py、build_jump_variants.py、integrate_run_trial.py 不在此仓库，它们依赖具体角色和游戏路径。
