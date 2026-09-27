# 角色设定图 → Seedance → 序列帧

这是异步视频任务 API，不是实时视频流。使用 API Key（Bearer），不需要为此配置 Access Key / Secret Key 和请求签名。API Key 所属项目需要开通目标模型权限。默认模型 `doubao-seedance-2-0-mini-260615`，480p、1:1、4 秒、`generate_audio: false`、`watermark: false`。不添加未经验证的 camera_fixed 参数；固定镜头写入提示词。

新任务先按 [chroma-workflow.md](chroma-workflow.md) 准备纯洋红参考图，并把 `assets/chroma-background-prompt.txt` 合入动作提示词，删除原来的灰底要求。`plan` 只缩放、补边，不会自动替换不透明图片内部的旧背景。

## 本地配置与生成

将 `SEEDDANCE_ARK_API_KEY` 配置到运行脚本的进程环境。不要写入提示词、项目配置、聊天或版本库。仅在某个终端设置环境变量不会自动传给已经打开的桌面应用；可在该终端执行脚本，或从已配置的环境启动应用。`doctor` 仅显示是否配置，不显示密钥。沿用 workflow.md 的 Python 环境和依赖。

以下 `PYTHON`、`SKILL` 和 `JOB` 代表实际 Python、Skill 与本次作业目录，执行时替换为路径：

```sh
PYTHON SKILL/scripts/ark_video.py doctor
PYTHON SKILL/scripts/ark_video.py plan --image character.png --prompt action.txt --out JOB --crop 768,512,384,512
PYTHON SKILL/scripts/ark_video.py submit JOB --ledger budget.json --policy SKILL/assets/cost-policy.json
PYTHON SKILL/scripts/ark_video.py wait JOB --seconds 50
PYTHON SKILL/scripts/ark_video.py download JOB
```

`plan` 完全离线。`--crop` 是可选的 x,y,宽,高，仅适用于实际检查过的设定图布局。它生成保留原图像素的方形 `input.png`；检查是否只有一个角色、朝向正确、没有文字/邻格角色、背景统一且头脚完整，再调用 `submit`。四角背景中值用于补边，复杂或不均匀背景需先提供干净参考图。不要把整张多视图当单个角色的首帧。

默认 `reference_image` 与平台多模态参考示例一致。需要锁定首帧时，可在 plan 显式加 `--mode first_frame`。角色动画仍用选定朝向的单人图，不自动上传整张多视图。两种输入模式不能混用。单张参考不保证人物一致性或跑姿正确。

`assets/run-right-prompt.txt` 是当前岑雨的朝右跑动示例，含左机械前臂设定；其他角色应改写身份、装备、动作和方向。循环动作要求持续动作、对侧协调、自然蹬地与腾空、固定镜头、原地跑、统一纯色背景、无投影/运动模糊。跳跃、攻击等非循环动作应描述起势—动作—收势并在导出时关闭 loop。不要要求把二维序列帧直接画在生成视频里。

## 恢复、查询与费用边界

- `job.json` 保存输入哈希、提示词和参数；`state.json` 保存任务 ID 与状态。`remote.json` 含短期视频签名 URL，应视作私有作业数据，避免提交或分享整个作业目录。
- `submit` 先写独占提交标记再 POST。已有 ID 时绝不重复创建；网络结果不明时停在 `submission_unknown`，不能删除标记盲目重试。
- 使用 `ark_video.py list --page 1 --page-size 20` 或控制台核实提交时间、输入、模型，确认是同一任务后 `ark_video.py attach JOB --task cgt-...`。脚本只校验模型，无法自行证明提示词相同。无法确认时先处理歧义，不创建第二条。
- `wait` 每次最多约 50 秒轮询（网络耗时可能额外延长），返回后可继续调用。等待超时不等于远端取消。失败/过期应检查控制台原因，不自动付费重试。
- 成功后及时 `download`；官方说明视频 URL 约 24 小时有效，任务记录保留 7 天。下载失败只重试下载，不重新生成。缓存视频会校验已记录哈希。
- 下载不向 CDN 发送 API Key，也不跟随重定向。未知 CDN 域名需根据官方返回值核实后修改白名单。
- 用户明确要求取消/删除时才使用 `delete JOB --confirm-task cgt-...`。排队任务可取消，运行中任务不能取消；删除记录不代表退款。不要自动清理云端任务。

## 接入抽帧与透明导出

```sh
PYTHON SKILL/scripts/video_to_sprite.py extract JOB/video.mp4 --out JOB/source
PYTHON SKILL/scripts/video_to_sprite.py prepare JOB/source --config matte.json --out JOB/matte-v1
PYTHON SKILL/scripts/video_to_sprite.py build JOB/matte-v1 --config clip.json --out JOB/sprites-v1
```

具体配置见 [workflow.md](workflow.md)。查看 source/overview.jpg 后选择稳定的完整步态周期，不能照搬旧视频的第 67–83 帧或投影坐标。先用默认去底配置，检查暗/亮背景上的白边、手指和浅色护甲，再决定是否开启边缘去污染。循环起止、抠图与视觉验收由 Skill 执行检查，并非无人值守的质量保证。

最终输出包含透明 PNG、图集、逐帧时长、GIF/HTML 预览和 Godot SpriteFrames。保留 job.json、视频哈希和所选帧配置以便复现。只有用户要求时才替换游戏资产。

## 官方依据

- [鉴权与 Base URL](https://docs.volcengine.com/docs/ark/base-url-and-authentication?lang=en)
- [创建](https://api.volcengine.com/api-docs/view?serviceCode=ark&version=2024-01-01&action=CreateContentsGenerationsTasks)
- [查询](https://api.volcengine.com/api-docs/view?serviceCode=ark&version=2024-01-01&action=GetContentsGenerationsTask)
- [列表](https://api.volcengine.com/api-docs/view?serviceCode=ark&version=2024-01-01&action=ListContentsGenerationsTasks)
- [取消/删除](https://api.volcengine.com/api-docs/view?serviceCode=ark&version=2024-01-01&action=DeleteContentsGenerationsTasks)

默认配置来自本项目用户已在平台验证的设置；离线测试不代表账号已开通模型，也不代表真实生成质量通过。

## 费用预估与预算控制

密钥变量为用户指定的 `SEEDDANCE_ARK_API_KEY`（包含 SEEDDANCE 的双 D 拼写），不回退读取旧 ARK_API_KEY。预算功能完全本地，不查询云账户余额。

先执行 `estimate JOB --policy SKILL/assets/cost-policy.json` 查看报价。当前估算仅支持 mini、图片输入、1:1、480p/720p；以输出宽×高×24×秒数÷1024 估算 Token。480p 方形按 640×640 计算，4 秒预计 38400 Token；23 元/百万 Token 原价约 0.8832 元。20% 余量预留为 1.0599 元。这是估计而非服务端最高收费承诺。

价格文件带有效期，到期拒绝新提交；复核官方价格后更新。不要因看见企业优惠就自动套用。资源包抵扣和现金费用不能混为一谈，本地金额按配置单价折算，不代表现金实际扣除。

由用户确定预算后执行（下列金额只是命令示例，不代表授权）：

```sh
PYTHON SKILL/scripts/ark_video.py budget-init budget.json --total 10 --per-job 2
PYTHON SKILL/scripts/ark_video.py estimate JOB --policy SKILL/assets/cost-policy.json
PYTHON SKILL/scripts/ark_video.py submit JOB --ledger budget.json --policy SKILL/assets/cost-policy.json
PYTHON SKILL/scripts/ark_video.py cost-report budget.json
```

同一批任务使用同一个 ledger。预算检查和预留在文件锁内进行，包含正在生成和结果不明的任务。提交必须指定预算与价格文件；超预算在网络请求前阻止。成功查询到 completion_tokens 后按提交时保存的单价更新台账。没有用量的失败或取消任务暂不释放预留，核实账单后才能人工调整；不要为了重试删除台账。修改提示词或图像请创建新作业。

报告区分 estimated_yuan（生成前估计）、reserved_yuan（预算占用）、usage_based_estimated_yuan（实际 Token 折价）和 bill_amount_yuan（未接入账单时为空）。account_balance_yuan 为 null、cloud_balance_connected 为 false，绝不伪装成真实余额。预算只限制此台账内本工具的新提交，无法限制控制台或其他程序消费，也无法阻止远端任务实际用量超过预估。

云账户余额/最终账单需另行接入费用中心 AK/SK 只读查询；目前未接通，不能仅凭视频 API Key 提供。尚未确认 Seedance 资源包余量公开 API，资源包剩余量以费用中心为准。

创建失败时 create-error.json 保存 HTTP 状态、业务 error_code、request_id 和脱敏错误说明，供平台支持定位。不保存原始响应或认证头。历史计划保留原来的 image_role，不自动改写已预留预算的作业；切换模式应创建新计划并核实旧任务与预算。参考图模式调整不代表已解决 403 权限错误。

## 跳跃视频的取景与拒收

已观察到：普通站姿参考图的站立身高过大，纵跳叠加举手后，手臂在原片中出画；抠图无法恢复不存在的像素。后续跳跃应另制参考画布：角色约占画布高度 55%–60%，脚底置于约 85% 高度，顶部预留约 30%；通过缩小原图并补纯色背景完成，不裁角色。提示词限制低幅跳跃、肘部弯曲、手不超过头顶、完整全身固定镜头。尺寸约束是降低风险，不能保证模型遵守。

去底前检查整段解码帧，重点查看腾空顶点手指/头发与四边的距离；若身体碰边或有明显解剖拖影，标记源片失败，不靠侵蚀、补透明画布或降低 alpha 假装修复。游戏跳跃另需去除视频整体升降，避免和游戏物理重复叠加。
