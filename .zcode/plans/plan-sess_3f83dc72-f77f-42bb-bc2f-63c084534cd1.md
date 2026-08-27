## 背景

`aisbench_auto_tools_prefix` 现在从 `GSM8K.jsonl`(仅 **1319 行**)挑文本再截断/重复到目标长度。当 `data_num` 较大(默认 8192)时必然产生大量重复行。需要新增「随机数据集」模式:用 tokenizer 词表随机采样 token 拼成精确长度的文本(参考 ClawPerf `tokenizer.generate_random_content` 与 LLM-Performence `gen_exact_tokens` 的迭代修正法)。

## 设计要点(已与用户确认)

1. **触发**:`--dataset_source {gsm8k, random}`,默认 `gsm8k`(完全兼容现状)。`random` 与 `--dataset_type normal/prefix_cache`、变长参数(`--length_mean` 等)可组合。仅在 `--dataset` 为 `none`(自动生成)时生效;指定了数据集路径时忽略。
2. **`--seed`**:已存在(默认 1)。扩展语义:
   - `seed == 0` → **纯随机**(RNG 由系统时间播种,不可复现)。
   - `seed > 0` → 确定性可复现(每行用 `random.Random(seed + 行号)` 独立播种,行间天然不重复)。
3. **去重指纹文件**(仅 `random` + `seed==0` 时启用):新增 `random_picked.txt`,每行存最终数据行的 `sha256` 指纹。
   - 生成前加载已有指纹到内存 `dedup_set`;候选行若命中则换偏移重采(最多 N 次);本次新增指纹追加写回文件。
   - `seed>0` 时不读写该文件(保确定性),仅内存去重兜底。
   - 与 gsm8k 的 `picked_ids.txt` 完全分离,互不影响。
4. **文件名**:随机数据集用 `RANDOM-` 前缀(如 `RANDOM-in2048-num160-<base>.jsonl`、`prefix-RANDOM-in...-<base>.jsonl`),避免与 gsm8k 缓存混淆。
5. **缓存跳过**:random 模式不走 `create_gsm8k_dataset` 里的「文件已存在则跳过」逻辑,每次重新生成(保证 `seed=0` 每次新数据)。

## 核心算法(端口自 LLM-Performence `gen_exact_tokens`,不做昂贵的 safe-token 预过滤,改用迭代修正——ClawPerf 已验证可行,且省去 cache 文件)

```
pool = tokenizer 词表中所有非 special、且 >=0 的 token id
ids = 随机采样 target_len 个 id
循环最多 15 次:
  text = decode(ids)
  cur = encode(text) 长度
  cur == target_len -> 返回 text
  cur > target -> 按溢出比例裁掉若干 id
  cur < target -> 补采 (deficit + 10% 余量) 个 id
末次仍不精确 -> 强制截断到 target_len 再 decode(兜底)
```

## 文件改动

### 1. `generate_dataset.py`(主改动)
- 新增:
  - `_get_vocab_pool(tokenizer)` → 非 special token id 列表(复用 ClawPerf 写法)。
  - `_gen_random_exact_text(tokenizer, pool, rng, target_len)` → 上述迭代算法,返回精确 `target_len` token 的文本。
  - `_load_fingerprints(path)` / `_append_fingerprints(path, new_hashes)` → 指纹文件读写。
  - `_init_random_dedup(seed)` → `seed==0` 时加载 `random_picked.txt` 并返回 `(dedup_set, True)`;否则 `({}, False)`。
  - `create_random_dataset(tokenizer_path, target_len, number, seed, dedup_set=None, fp_active=False)` → 生成 `number` 行精确 `target_len` 随机文本,逐行去重(命中指纹则换 `random.Random(seed/时间 + offset)` 重采),返回 list(基本不会返回 None;极端情况返回已达成的部分)。
- 修改 `create_multi_prefix_dataset(...)` 与 `_create_prefix_dataset_variable(...)`:
  - 新增 `dataset_source="gsm8k"` 形参;末位追加以保持现有位置参数调用兼容。
  - `is_random = dataset_source == "random"`;若是则 `_init_random_dedup(seed)`。
  - 定义内部 dispatcher `_base_rows(target_len, count, pflag=0)`:random → `create_random_dataset(...)`(pflag==0 的行经指纹去重;pflag==1 的前缀池不去重,靠 per-index seed 保证 distinct);gsm8k → 原有 `create_dataset(...)`。
  - 把函数内 5 处 `create_dataset(...)` 调用替换为 `_base_rows(...)`。
  - 输出文件名 `GSM8K-` ↔ `RANDOM-` 前缀分支。
  - 变长路径:random 仍走「生成最大长度池 → 逐行截断」,因截断随机文本仍是随机文本,且最终去重已覆盖;不另开 per-row 精确生成分支(降低复杂度)。
  - 前缀模式的 3 个边界 token 仍用现有 `generate_unique_tokens(...)`(本就是随机 token,无需改)。

### 2. `aisbench_test.py`
- `parse_arguments`:新增 `--dataset_source`(`type=str, default="gsm8k", choices=["gsm8k","random"], help="gsm8k or random"`)。
- `__main__`:读取 `dataset_source = args.dataset_source`;`logging.info`;传入 `create_gsm8k_dataset(...)`。
- `create_gsm8k_dataset(...)` 形参末位加 `dataset_source="gsm8k"`,转发给两处 `create_multi_prefix_dataset(...)` 调用(行 61、83)。
- normal 路径的「文件已存在则跳过」分支:random 时跳过该缓存检查,强制生成(并在 random 时把文件名按 `RANDOM-` 计算)。

### 3. `README.md`
- 参数表加 `--dataset_source` 行。
- 「数据集生成逻辑」节加随机模式说明:词表随机 token + 迭代精确长度;`seed=0` 纯随机 + `random_picked.txt` 跨次去重;`seed>0` 确定性。
- 命令示例加一条(如 `... --dataset_source random --seed 0 ...` 与 `... --dataset_source random --seed 42 ...`)。
- FAQ 加:「`random_picked.txt` 是什么 / 想重置随机去重」→ 删除该文件即可。

### 不改动
`config.py`、`save_file.py`、`data_picker.py`、`cal_prefix_hit_rate.py`、`default_api.py`、`GSM8K.jsonl`。

## 验证方式(实现后)
- 不接服务的纯生成验证:直接 `python -c` 调 `create_multi_prefix_dataset(..., dataset_source="random")`,检查输出 jsonl 行数、每行 token 数精确等于 `input_len`、无重复行;`seed=42` 两次运行输出一致;`seed=0` 两次运行输出不同且 `random_picked.txt` 增长。
- gsm8k 回归:不带 `--dataset_source` 跑一次 normal 生成,确认行为与改动前一致(文件名 `GSM8K-`、走 `picked_ids.txt`)。
- 需要真实 tokenizer 才能完整验证精确长度;若环境无 tokenizer,至少做语法 import 与 `--help` 冒烟。
