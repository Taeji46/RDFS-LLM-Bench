# RDFS-LLM-Bench

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![License: CC BY-SA 4.0](https://img.shields.io/badge/Data%20License-CC%20BY--SA%204.0-lightgrey.svg)](LICENSE-DATA)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19867258.svg)](https://doi.org/10.5281/zenodo.19867258)

LLM における RDF Schema 推論を評価するためのベンチマークです。

英語版: [README.md](README.md)

---

## 概要

RDFS-LLM-Bench は、LLM が RDFS ベースの推論をどの程度実行できるかを体系的に評価します。
6つのコア RDFS ルール（rdfs2, rdfs3, rdfs5, rdfs7, rdfs9, rdfs11）と
13の複合ルール構成（計19ルール構成）を対象に、7種類のデータセット系列と
6種類の推論操作タイプを提供します。

---

## RDFS ルール

| ルール | 前提 | 結論 |
|---|---|---|
| rdfs2 | `<i, rdfs:domain, X>` かつ `<a, i, b>` | `<a, rdf:type, X>` |
| rdfs3 | `<i, rdfs:range, X>` かつ `<a, i, b>` | `<b, rdf:type, X>` |
| rdfs5 | `<i, rdfs:subPropertyOf, j>` かつ `<j, rdfs:subPropertyOf, k>` | `<i, rdfs:subPropertyOf, k>` |
| rdfs7 | `<i, rdfs:subPropertyOf, j>` かつ `<a, i, b>` | `<a, j, b>` |
| rdfs9 | `<X, rdfs:subClassOf, Y>` かつ `<a, rdf:type, X>` | `<a, rdf:type, Y>` |
| rdfs11 | `<X, rdfs:subClassOf, Y>` かつ `<Y, rdfs:subClassOf, Z>` | `<X, rdfs:subClassOf, Z>` |

複合ルール構成（13種）: rdfs2\_3, rdfs2\_7, rdfs2\_9, rdfs3\_7, rdfs3\_9, rdfs5\_7, rdfs9\_11, rdfs2\_3\_7, rdfs2\_3\_9, rdfs2\_5\_7, rdfs2\_9\_11, rdfs3\_5\_7, rdfs3\_9\_11

---

## データセット系列

| 系列 | ソース | 説明 |
|---|---|---|
| `rk` | LOD サンプル | DBpedia/Wikidata/schema.org の実世界トリプルをそのまま使用 |
| `ls` | LOD サンプル | ローカルシャッフル: エントリ内でタームをスワップ・デレンジ |
| `gs` | LOD サンプル | グローバルシャッフル: タームスロットにグローバルシャッフルした LOD 値を割り当て |
| `gsc` | LOD サンプル | `gs` と同様だが型一貫ケース付き（クラス: PascalCase, プロパティ: camelCase）|
| `ns` | スタンドアロン | 非意味論的: 全タームスロットにランダム8文字英数字トークン |
| `nsc` | スタンドアロン | ケース付き非意味論的: 型に応じたランダムトークン（PascalCase / camelCase）|
| `rva` | スタンドアロン | ランダム語彙割り当て: ターム種別ごとに DBpedia ローカル名をランダム割り当て |

---

## 推論操作タイプ（Inference Operation Types）

各データセットエントリには、**推論操作タイプ**に基づいたプロンプトが対応付けられます。
推論操作タイプは、モデルにどの程度のルール情報を与えるかを定義します。

| 推論操作タイプ | 略称 | 説明 |
|---|---|---|
| Necessary Rule Presentation | NRP | 推論タスクに必要なルール（群）を与え、モデルがそれを前提知識に適用する |
| All-Rule Presentation | ARP | 全 RDFS ルールを与え、モデルが必要なものを選択・適用する |

各操作タイプには3種類の**ルール情報提示形式**があります。

| 形式 | サフィックス | モデルへの提示内容 |
|---|---|---|
| フル | `-full` | ルール名 + 定義 |
| 名前のみ | `-name` | ルール名のみ |
| 定義のみ | `-def` | 定義のみ |

合計6種類の推論操作タイプ:
`NRP-full`, `NRP-name`, `NRP-def`, `ARP-full`, `ARP-name`, `ARP-def`

### ルール数ごとの有効な組み合わせ

全ての推論操作タイプが全ルール数に適用できます。

| | 1-rule | 2-rule | 3-rule |
|---|---|---|---|
| NRP-full | ✓ | ✓ | ✓ |
| NRP-name | ✓ | ✓ | ✓ |
| NRP-def  | ✓ | ✓ | ✓ |
| ARP-full | ✓ | ✓ | ✓ |
| ARP-name | ✓ | ✓ | ✓ |
| ARP-def  | ✓ | ✓ | ✓ |

NRP のプロンプトはルール数に応じてテンプレートを切り替えます。1-rule では単数形（"Solely based on this rule…"）、多 rule では複数形（"…by combining these rules"）のテンプレートを使用します。

---

## ディレクトリ構成

```
scripts/
  fetch-samples/
    1-rule/           fetch_samples_rdfs{N}.py          （6スクリプト）
    2-rule/           fetch_samples_rdfs{N}_{M}.py      （7スクリプト）
    3-rule/           fetch_samples_rdfs{N}_{M}_{K}.py  （6スクリプト）
    shared/           _base.py
  build-dataset/
    from-samples/     gen_rk.py, gen_ls.py, gen_gs-gsc.py
    standalone/       gen_ns.py, gen_nsc.py, gen_rva.py
    shared/           _base.py
    run_all.py
  llm-eval/
    tasks/            build_zeroshot_tasks.py
    adapters/         to_openai_batch.py, to_sequential.py
    run/              openai_batch_upload.py, openai_batch_download.py
                      run_sequential_openai_compat.py, run_sequential_ollama.py
    eval/             evaluate_outputs.py
    report/           aggregate_scores.py, export_excel.py,
                      compute_composite_metrics.py,
                      analyze_scaling.py, analyze_rule_accuracy.py
    shared/           rule_defs.py, prompt_builder.py, io.py, naming.py,
                      eval_utils.py
    model-config.json

data/
  lod-samples/
    {1,2,3}-rule/     lod-sample__{rule}__n{N}__f-xxxxxxxx.json
  datasets/
    {rk,ls,gs,gsc,ns,nsc,rva}/
      {1,2,3}-rule/   dataset__{type}__{rule}__n{N}__f-xxxxxxxx__b-xxxxxxxx.json
  llm-eval/
    tasks/
      zeroshot/
        {operation_type}/{dataset_type}/{n-rule}/
                        task__{op}__{type}__{rule}__n{N}__...json
    requests/
      openai-batch/
        {model-slug}/{operation_type}/{dataset_type}/{n-rule}/
                        batch__{model-slug}__{op}__{type}__{rule}__n{N}__...jsonl
      sequential/
        {model-slug}/{operation_type}/{dataset_type}/{n-rule}/
                        seq__{model-slug}__{op}__{type}__{rule}__n{N}__...jsonl
    responses/
      openai-batch/
        {model-slug}/{operation_type}/{dataset_type}/{n-rule}/
                        response__{model-slug}__{op}__{type}__{rule}__n{N}__...
                          __batch_{batch-id}__{YYYYMMDDHHMMSS}.jsonl
    eval/
      {strict,flex}/
        {response_type}/{model}/{operation_type}/{dataset_type}/{n-rule}/
                        eval-{mode}__{model}__{op}__{type}__{rule}__n{N}__...jsonl
    reports/
      {strict,flex}/
                        scores-{mode}.csv
                        scores-{mode}__{model}.xlsx
                        composite_metrics-{mode}.csv
```

---

## クイックスタート

### 1. 依存関係のインストール

```bash
pip install -r requirements.txt
```

### 2. LOD サンプルの取得

単一ルールの例:

```bash
python scripts/fetch-samples/1-rule/fetch_samples_rdfs2.py --date 20260418
```

19ルール構成を一括実行:

```bash
for f in \
  scripts/fetch-samples/1-rule/fetch_samples_*.py \
  scripts/fetch-samples/2-rule/fetch_samples_*.py \
  scripts/fetch-samples/3-rule/fetch_samples_*.py
do
  echo ">>> $f"
  python "$f" --date 20260418
done
```

### 3. `lod-sample-config.json` の更新

各ルールが参照するサンプルファイルを設定します:

```
scripts/build-dataset/lod-sample-config.json
```

### 4. ベンチマークデータセットの生成

```bash
# 全系列を一括生成
python scripts/build-dataset/run_all.py

# 個別に生成する場合
python scripts/build-dataset/from-samples/gen_rk.py
python scripts/build-dataset/from-samples/gen_ls.py
python scripts/build-dataset/from-samples/gen_gs-gsc.py
python scripts/build-dataset/standalone/gen_ns.py
python scripts/build-dataset/standalone/gen_nsc.py
python scripts/build-dataset/standalone/gen_rva.py
```

出力先: `data/datasets/{系列}/{1,2,3}-rule/dataset__*.json`

---

## LLM 評価パイプライン

### ステップ 1 — ゼロショットタスクファイルの生成

ベンチマークデータセットから各推論操作タイプのプロンプトファイルを生成します。

```bash
# 全操作タイプ・全データセット系列
python scripts/llm-eval/tasks/build_zeroshot_tasks.py

# 絞り込みの例
python scripts/llm-eval/tasks/build_zeroshot_tasks.py \
  --dataset-types rva,gs \
  --operation-types NRP-full,ARP-full \
  --rules rdfs2,rdfs9
```

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--dataset-types` | 全て | カンマ区切りのデータセット系列（例: `rva,gs`）|
| `--operation-types` | 全6種 | カンマ区切りの推論操作タイプ（例: `NRP-full,ARP-name`）|
| `--rules` | 全て | カンマ区切りのルールID（例: `rdfs2,rdfs2_3`）|
| `--entry-limit` | 0（無制限）| デバッグ用: データセットファイルあたりのエントリ上限 |
| `--max-files` | 0（無制限）| デバッグ用: 処理するファイル数の上限 |
| `--overwrite` | スキップ | 既存タスクファイルをスキップせず上書きする |
| `--verbose` | — | 保存ファイルのパスを逐次出力する（デフォルト: サマリーのみ）|

出力先: `data/llm-eval/tasks/zeroshot/{operation_type}/{dataset_type}/{n-rule}/task__*.json`

### ステップ 2 — リクエストファイルへの変換

**OpenAI Batch API 用:**

```bash
python scripts/llm-eval/adapters/to_openai_batch.py \
  --model gpt-4o-mini-2024-07-18 \
  --operation-types NRP-full \
  --dataset-types rva
```

**逐次実行（OpenAI互換 / Ollama）用:**

```bash
python scripts/llm-eval/adapters/to_sequential.py \
  --model llama3.1-8b \
  --operation-types NRP-full \
  --dataset-types rva
```

使用可能なモデルは `scripts/llm-eval/model-config.json` で定義します。`--model` にはスラグ（config のキー）を指定し、実際の API モデル名はスクリプト内部で解決されます。

### ステップ 3 — LLM 推論の実行

各ランナーは専用のキューベースディレクトリを持ちます。名前付きサブディレクトリを作成してリクエストファイルを配置し、`--queue <名前>` を指定して実行します。

```
data/llm-eval/requests/input-queues/
  openai-batch/
    <queue-name>/   ← batch__*.jsonl を配置
  openai-compat/
    <queue-name>/   ← seq__*.jsonl を配置
  ollama/
    <queue-name>/   ← seq__*.jsonl を配置
```

**OpenAI Batch:**

```bash
python scripts/llm-eval/run/openai_batch_upload.py --queue <queue-name>
python scripts/llm-eval/run/openai_batch_download.py --queue <queue-name>
```

アップロード結果は `input-queues/openai-batch/<queue-name>/upload_mapping.json` に記録されます。
全バッチが完了するまで download を繰り返し実行してください。

**逐次実行（OpenAI互換 API）:**

`model-config.json` で `runner: "sequential-openai-compat"` のモデル（DeepInfra ホスト等）が対象です。
`.env` に以下の変数を設定してください:

```
OPENAI_COMPAT_API_KEY=<your-api-key>
OPENAI_COMPAT_BASE_URL=https://api.deepinfra.com/v1/openai
```

```bash
python scripts/llm-eval/run/run_sequential_openai_compat.py --queue <queue-name>
```

**逐次実行（Ollama）:**

`model-config.json` で `runner: "sequential-ollama"` のモデルが対象です。
Ollama デーモンが起動済みで対象モデルがプル済みである必要があります。

```bash
python scripts/llm-eval/run/run_sequential_ollama.py --queue <queue-name>
```

デフォルトではローカルの Ollama デーモンを使用します。リモートホストを使用する場合は `.env` に `OLLAMA_HOST` を設定し、`--use-host` を指定してください：

```
OLLAMA_HOST=http://<host>:<port>
```

```bash
python scripts/llm-eval/run/run_sequential_ollama.py --queue <queue-name> --use-host
```

`.env` を使わずに一時的に切り替えたい場合：

```bash
python scripts/llm-eval/run/run_sequential_ollama.py --queue <queue-name> --ollama-host http://<host>:<port>
```

`--queue` を省略すると利用可能なキュー名が一覧表示されます。3スクリプト共通の引数:

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--queue` | 必須 | キューのサブディレクトリ名（例: `queue1`）|
| `--overwrite` | スキップ | 処理済みファイルも再実行・再アップロード |
| `--yes` | プロンプト表示 | 確認プロンプトをスキップ |
| `--dry-run` | — | API 呼び出しなしで実行内容を確認 |
| `--verbose` | — | スキップ時もパスを出力 |
| `--fallback-root` | スキップ | （sequential のみ）ファイル名が解析できない場合に response ルート直下に保存 |

出力先: `data/llm-eval/responses/sequential/{slug}/{operation_type}/{dataset_type}/{n-rule}/response__*.jsonl`

### ステップ 4 — 出力の評価

デフォルトでは `data/llm-eval/responses/` 以下の全レスポンス種別（`openai-batch`、`sequential` 等）をまとめて評価します。

```bash
# strict モード（デフォルト）: 正規形式 <s, p, o> のみ受け入れ
python scripts/llm-eval/eval/evaluate_outputs.py --mode strict

# flex モード: 順序ベースのマッチング。<s,p,o>・<s p o>・<X rdf:type Y> 等も受け入れ
python scripts/llm-eval/eval/evaluate_outputs.py --mode flex

# 特定のレスポンス種別のみ評価する場合
python scripts/llm-eval/eval/evaluate_outputs.py --mode strict --response-type sequential
python scripts/llm-eval/eval/evaluate_outputs.py --mode strict --response-type openai-batch
```

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--mode` | `strict` | 評価モード: `strict` または `flex` |
| `--response-type` | 全て | `responses/` 以下のサブディレクトリ（例: `openai-batch`, `sequential`）。省略時は全種別を評価 |
| `--models` | 全て | 絞り込むモデルスラグ（カンマ区切り）|
| `--operation-types` | 全て | 絞り込む推論操作タイプ（カンマ区切り）|
| `--dataset-types` | 全て | 絞り込むデータセット種別（カンマ区切り）|
| `--rules` | 全て | 絞り込むルールID（カンマ区切り）|
| `--overwrite` | スキップ | 既存の評価ファイルを上書きする |
| `--verbose` | — | ファイルごとの詳細を出力する |

出力先: `data/llm-eval/eval/{strict,flex}/{response_type}/{model}/...`

### （任意）実験状況の確認

モデルごとの実験進捗を Excel に書き出します：

```bash
python scripts/llm-eval/report/export_status_excel.py --overwrite
```

出力先: `data/llm-eval/reports/status.xlsx`（モデルごとに1シート）

各セルは (op-type, rule-id, dataset-type) の組み合わせの状態を示します：

| 記号 | 意味 |
|------|------|
| ○ | response ファイルが存在し、**全 UID がタスクファイルと一致**（正しい実験結果）|
| △ | response ファイルは存在するが、UID が一つ以上異なる（例：別のプロンプトテンプレートで実行された）|
| × | task ファイルはあるが response がない（未実験）|
| - | 構造的に定義不可能な組み合わせ（例：rdfs5 × gs/gsc）|

複合メトリクスに必要なセルはアンバー色のあみかけで強調されます。

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--task-root` | `data/llm-eval/tasks/zeroshot` | タスクファイルのルート |
| `--response-root` | `data/llm-eval/responses` | response ファイルのルート |
| `--report-root` | `data/llm-eval/reports` | 出力ディレクトリ |
| `--overwrite` | スキップ | 既存の出力ファイルを上書きする |

### （任意）API 予算の見積もり

`input-queues` 内のリクエストファイルから input/output トークン数と API コストを見積もります：

```bash
python scripts/llm-eval/run/estimate_budget.py --overwrite
```

出力先: `data/llm-eval/reports/budget_estimate.xlsx`

- **Summary シート** — モデルごとの合計トークン数と推定コスト
- **Detail シート** — (モデル, op-type, データセット, ルール) 単位の内訳

input トークンはリクエストファイルのプロンプトメッセージから計算します。
output トークンはタスクファイルの `expected_output` から推定します（ARP 系は `[used_rules: ...]` 行も含む）。

単価は `scripts/llm-eval/model-pricing.json` に USD/1M tokens 形式で記載されています。実行前に必要に応じて編集してください。

### ステップ 5 — スコアの集計

```bash
python scripts/llm-eval/report/aggregate_scores.py --mode strict
python scripts/llm-eval/report/aggregate_scores.py --mode flex
```

出力先: `data/llm-eval/reports/{strict,flex}/scores-{mode}.csv`

### ステップ 6 — Excel へのエクスポート

```bash
python scripts/llm-eval/report/export_excel.py --mode strict
python scripts/llm-eval/report/export_excel.py --mode flex
```

出力先: `data/llm-eval/reports/{strict,flex}/scores-{mode}__{model}.xlsx`

### ステップ 7 — 複合メトリクスの計算

```bash
python scripts/llm-eval/report/compute_composite_metrics.py --mode strict
python scripts/llm-eval/report/compute_composite_metrics.py --mode flex
```

出力先: `data/llm-eval/reports/{strict,flex}/composite_metrics-{mode}.csv`

### （任意）スケーリング分析

1-rule / 2-rule / 3-rule で F1 がどう変化するかを分析します（rule_info == "full" のみ対象）：

```bash
python scripts/llm-eval/report/analyze_scaling.py --mode strict
python scripts/llm-eval/report/analyze_scaling.py --mode flex
```

出力先: `data/llm-eval/reports/{strict,flex}/scaling_analysis-{mode}.xlsx`（データセット種別ごとに1シート）

### （任意）ルールレベル分析

各ルール単体の F1 を 1-rule シナリオのみ（n_rule == 1, rule_info == "full"）から算出します。マルチルールシナリオを除外することで、他ルールの難易度に汚染されない、各ルール固有の難しさを測れます：

```bash
python scripts/llm-eval/report/analyze_rule_accuracy.py --mode strict
python scripts/llm-eval/report/analyze_rule_accuracy.py --mode flex
```

出力先: `data/llm-eval/reports/{strict,flex}/rule_accuracy_analysis-{mode}.xlsx`（データセット種別ごとに1シート）

### （任意）データセット別 F1 集計

`full` 設定のみ、6セル（NRP/ARP × {1-rule, 2-rule, 3-rule}）の平均 F1 を、行=LLM・列=データセット種別の単一表にまとめます：

```bash
python scripts/llm-eval/report/f1_by_dataset_table.py --mode strict
python scripts/llm-eval/report/f1_by_dataset_table.py --mode flex
```

出力先: `data/llm-eval/reports/{strict,flex}/f1_by_dataset-{mode}.xlsx`

---

## 評価モード

評価モードはステップ 4〜7 の `--mode` 引数で切り替えます。

| モード | 説明 |
|---|---|
| `strict` | カンマ＋スペース区切りの正規形式 `<s, p, o>` のみを有効なトリプルとして受け入れます。推論能力と出力形式への従順さを同時に評価します。 |
| `flex` | `,`, ` `, `<>` のみを区切り文字として s, p, o が順序通りに含まれる `<...>` トークンを受け入れます。`<s,p,o>`, `<s p o>`, `<X rdf:type Y>` などの形式揺れに対応します。出力形式に依存せず純粋な推論能力を評価します。 |

strict と flex のスコア差は、出力形式不遵守による影響の大きさを示します。

---

## データフォーマット

### データセットエントリ（`data/datasets/`）

```json
{
  "metadata": {
    "rule_id": "rdfs2",
    "rules": ["rdfs2"],
    "dataset_type": "rva",
    "fetch_uid": "v-a1b2c3d4",
    "build_uid": "b-e5f6g7h8"
  },
  "entries": [
    {
      "premise_knowledge": "<hasJob, rdfs:domain, Person>, <Alice, hasJob, Engineer>",
      "expected_output": "<Alice, rdf:type, Person>"
    }
  ]
}
```

### タスクファイル（`data/llm-eval/tasks/zeroshot/`）

```json
{
  "metadata": {
    "operation_type": "NRP-full",
    "dataset_type": "rva",
    "rule_id": "rdfs2",
    "rules": ["rdfs2"]
  },
  "tasks": [
    {
      "task_id": "request-1",
      "system_prompt": "You are a helpful assistant.",
      "user_prompt": "Given the following rule and premise knowledge: ...",
      "premise_knowledge": "<hasJob, rdfs:domain, Person>, <Alice, hasJob, Engineer>",
      "expected_output": "<Alice, rdf:type, Person>"
    }
  ]
}
```

---

## ファイル命名規則

| ファイル種別 | パターン |
|---|---|
| LOD サンプル | `lod-sample__{rule}__n{N}__f-{uid}.json` |
| データセット | `dataset__{type}__{rule}__n{N}__f-{uid}__b-{uid}.json` |
| タスク | `task__{op}__{type}__{rule}__n{N}__{uid}__{uid}.json` |
| バッチリクエスト | `batch__{slug}__{op}__{type}__{rule}__n{N}__{uid}__{uid}.jsonl` |
| 逐次リクエスト | `seq__{slug}__{op}__{type}__{rule}__n{N}__{uid}__{uid}.jsonl` |
| バッチレスポンス | `response__{slug}__{op}__{type}__{rule}__n{N}__{uid}__{uid}__batch_{id}__{ts}.jsonl` |
| 評価結果 | `eval-{mode}__{slug}__{op}__{type}__{rule}__n{N}__{uid}__{uid}__batch_{id}__{ts}.jsonl` |

UID プレフィックス: `f-` = fetch/ソース（LOD系データセット）, `b-` = build  
`{slug}` = `model-config.json` で定義したモデルスラグ  
`{ts}` = OpenAI Batch API の `completed_at` タイムスタンプ（`YYYYMMDDHHMMSS`、UTC）

---

## トラブルシューティング

**`0 rows available`（サンプル取得時）**
SPARQL エンドポイントの負荷や一時的不安定が原因です。時間を置いて再実行してください。

**`lod-sample file not found`**
`scripts/build-dataset/lod-sample-config.json` の設定と実際のサンプルファイル名が不一致です。設定を更新してください。

---

## ライセンス

**コード** (`scripts/`): [MIT License](LICENSE) © 2026 Taichi Hosokawa

**データ** (`data/lod-samples/`, `data/datasets/`, `data/llm-eval/`): [CC BY-SA 4.0](LICENSE-DATA)

本データセットは以下のソースから派生しています：

- [DBpedia](https://dbpedia.org) — CC BY-SA 3.0
- [Wikidata](https://www.wikidata.org) — CC0 1.0
- [schema.org](https://schema.org) — CC BY-SA 3.0

データは各ソースの公開 SPARQL エンドポイントへのクエリにより収集しました。

