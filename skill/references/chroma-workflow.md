# 统一洋红背景：参考图 → 视频 → 抠图

新角色视频默认纯洋红 #FF00FF。当前角色有橄榄绿裤子与浅色义肢，洋红更容易与主体分离。其他角色若有洋红配饰、光效或半透明部分，应改用与主体不冲突的纯色，并同步修改参考图和提示词。不要把这一配色当成所有角色的硬要求。

## 准备单人参考图

先选择已检查过的单人透明 PNG，保留原图。使用本地工具：

```sh
PYTHON SKILL/scripts/prepare_reference.py --image character-cutout.png --out reference-magenta.png
PYTHON SKILL/scripts/ark_video.py plan --image reference-magenta.png --prompt action-with-chroma.txt --out JOB
```

`PYTHON` 为项目虚拟环境 Python，`SKILL` 为本技能路径。默认将人物放在 640 方形画布，身高最多 65%、脚底 85%、水平居中。随后现有 plan 缩放到 560 后补边，最终人物约占 57% 高度、脚底约 81%，给跳跃和伸臂留空间。检查最终 JOB/input.png，不能只检查中间图。

不透明输入默认拒绝，避免只补洋红外框、人物身后仍留灰底。若原参考图背景均匀，可显式传 `--matte-config original-background.json`，用已有算法抠除原背景，再合成洋红底。此参数必须描述原图的背景，不能直接拿洋红视频预设抠灰底。原图背景复杂则提供人工/外部分割蒙版或已去底素材；不将自动去底当作必然正确。透明输入的已有白边也会被保留，因此准备后必须查看头发、义肢、手指、裤脚。

工具还支持 `--background 00FF00` 和 `--height-ratio 0.60` 等显式覆写，拒绝覆盖已有输出。

## 视频提示词

把 assets/chroma-background-prompt.txt 合并进动作提示词，删除与之冲突的灰底/绿底、地面和阴影要求。参考图与文字必须使用同一种背景。保持纯色、无渐变/地面/投影/运动模糊/反光染色，躯干居中，四肢留安全边距。该模板不会被 API 脚本暗中追加，最终 prompt.txt 与 job.json 是实际提交内容。

仍沿用已有预算、一次提交和失败恢复规则；修改技能不等于授权生成或重试。

## 视频抠图

```sh
PYTHON SKILL/scripts/video_to_sprite.py extract JOB/video.mp4 --out JOB/source
PYTHON SKILL/scripts/video_to_sprite.py prepare JOB/source --config SKILL/assets/matte-magenta.json --out JOB/matte-v1
```

预设有意不锁定 key_color：从每帧四角估计实际背景色，允许模型偏色与压缩误差。先看 source/overview.jpg，确认背景确实均匀且四角无人；不均匀时暂停批量处理，检查素材，不用无限增大阈值来掩盖问题。必要时用实测色值覆盖 key_color，不能假设视频编码后仍精确等于 #FF00FF。

启用边缘去污染和小型封闭背景洞清理；关闭仅针对灰白边缘的 neutral_fringe_cleanup 与灰色地面阴影规则，避免误删义肢/裤脚。预设保留达到最小面积的多个连通区域，以保留手机和分离手指；仍需检查碎屑。角色自身含近似背景色时禁用封闭洞清理或改用蒙版。

验收需在深、浅背景和游戏 alpha 阈值下检查发丝、手指、机械臂、鞋底与手机；按时间播放检查边缘闪烁。纯色背景不能修复出画、肢体变形或拖影。此预设尚需用实际新生成的洋红视频验证，不保证无需调整。

## 历史素材

不重写已有任务、哈希或收费记录，不自动重生成灰底视频。已有灰底动画继续用其保存的配置；新预设仅用于新背景相符的素材。
