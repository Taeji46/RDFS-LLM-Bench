# RDFS-LLM-Bench

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![License: CC BY-SA 4.0](https://img.shields.io/badge/Data%20License-CC%20BY--SA%204.0-lightgrey.svg)](LICENSE-DATA)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19867258.svg)](https://doi.org/10.5281/zenodo.19867258)

LLM における RDF Schema 推論を評価するためのベンチマークです。

英語版: [README.md](README.md)

---

## 目次

- [概要](#概要)
- [RDFS 含意ルール](#rdfs-含意ルール)
- [データセット種類](#データセット種類)
- [Presented Rule Type と Rule Format](#presented-rule-type-と-rule-format)
- [ディレクトリ構成](#ディレクトリ構成)
- [クイックスタート: 既存データセットで LLM を評価する](#クイックスタート-既存ベンチマークでllmを評価する) — 既成のデータセットを使う
- [フルビルド: LOD ソースからデータセットを構築する](#フルビルド-lod-ソースからデータセットを構築する) — 自分でデータセットを構築する
- [LLM 評価パイプライン](#llm-評価パイプライン) — 両パスの共通部分
- [データフォーマット](#データフォーマット)
- [ファイル命名規則](#ファイル命名規則)
- [トラブルシューティング](#トラブルシューティング)
- [ライセンス](#ライセンス)

---

## 概要

RDFS-LLM-Bench は LLM の RDFS 推論能力を体系的に評価するためのベンチマークです。
6つのコア RDFS 含意ルール（rdfs2, rdfs3, rdfs5, rdfs7, rdfs9, rdfs11）に加えて
13個の複数ルール組み合わせを扱い、合計 19 種類の含意パターン（1 ルール 6 種 + 2 ルール 7 種 + 3 ルール 6 種）を網羅します。
評価は 7 種類のデータセットに対し、2 種類の Presented Rule Type × 3 種類の Rule Format
（= 6 通りのプロンプト条件）で行います。

---

## RDFS 含意ルール

| ルール | 前提 | 結論 |
|---|---|---|
| rdfs2 | `<i, rdfs:domain, X>` かつ `<a, i, b>` | `<a, rdf:type, X>` |
| rdfs3 | `<i, rdfs:range, X>` かつ `<a, i, b>` | `<b, rdf:type, X>` |
| rdfs5 | `<i, rdfs:subPropertyOf, j>` かつ `<j, rdfs:subPropertyOf, k>` | `<i, rdfs:subPropertyOf, k>` |
| rdfs7 | `<i, rdfs:subPropertyOf, j>` かつ `<a, i, b>` | `<a, j, b>` |
| rdfs9 | `<X, rdfs:subClassOf, Y>` かつ `<a, rdf:type, X>` | `<a, rdf:type, Y>` |
| rdfs11 | `<X, rdfs:subClassOf, Y>` かつ `<Y, rdfs:subClassOf, Z>` | `<X, rdfs:subClassOf, Z>` |

複数ルールの含意パターン（13 種類 = 2 ルール 7 種 + 3 ルール 6 種）: rdfs2\_3, rdfs2\_7, rdfs2\_9, rdfs3\_7, rdfs3\_9, rdfs5\_7, rdfs9\_11, rdfs2\_3\_7, rdfs2\_3\_9, rdfs2\_5\_7, rdfs2\_9\_11, rdfs3\_5\_7, rdfs3\_9\_11

---

## データセット種類

| 種類 | ソース | 説明 |
|---|---|---|
| `rk` | LOD サンプル | DBpedia/Wikidata/schema.org の実世界トリプルをそのまま使用 |
| `ls` | LOD サンプル | ローカルシャッフル: エントリ内でリソースをスワップ・デレンジ |
| `gs` | LOD サンプル | グローバルシャッフル: リソーススロットにグローバルシャッフルした LOD 値を割り当て |
| `gsc` | LOD サンプル | `gs` と同様だが型一貫ケース付き（クラス: PascalCase, プロパティ: camelCase）|
| `ns` | スタンドアロン | 非意味論的: 全リソーススロットにランダム8文字英数字トークン |
| `nsc` | スタンドアロン | ケース付き非意味論的: 型に応じたランダムトークン（PascalCase / camelCase）|
| `rva` | スタンドアロン | ランダム語彙割り当て: リソース種別ごとに DBpedia ローカル名をランダム割り当て |

---

## Presented Rule Type と Rule Format

各データセットエントリには 1 つのプロンプトが対応付けられます。プロンプトの内容は **Presented Rule Type (PRT)** と **Rule Format** の 2 軸で決まります。

| PRT | 略称 | 説明 |
|---|---|---|
| Necessary Rule Presentation | NRP | 推論タスクに必要なルール（群）を与え、モデルがそれを前提知識に適用する |
| All-Rule Presentation | ARP | 全 RDFS ルールを与え、モデルが必要なものを選択・適用する |

各 PRT は次の 3 つの Rule Format のいずれかと組み合わせて使います。

| Format | サフィックス | モデルへの提示内容 |
|---|---|---|
| フル | `-full` | ルール名 + 定義 |
| 名前のみ | `-name` | ルール名のみ |
| 定義のみ | `-def` | 定義のみ |

PRT と Rule Format を組み合わせると合計 6 通りのプロンプト条件になります。CLI 引数・ファイルパス・JSON の `prompting_condition` フィールドでは `{PRT}-{rule_format}` の形式で表記します:
`NRP-full`, `NRP-name`, `NRP-def`, `ARP-full`, `ARP-name`, `ARP-def`。

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
    {1,2,3}-rule/     lod-sample__{pattern_id}__n{N}__f-xxxxxxxx.json
  datasets/
    {rk,ls,gs,gsc,ns,nsc,rva}/
      {1,2,3}-rule/   dataset__{dataset_variant}__{pattern_id}__n{N}__f-xxxxxxxx__b-xxxxxxxx.json
  llm-eval/
    tasks/
      zeroshot/
        {prompting_condition}/{dataset_variant}/{n-rule}/
                        task__{prompting_condition}__{dataset_variant}__{pattern_id}__n{N}__...json
    requests/
      openai-batch/
        {model-slug}/{prompting_condition}/{dataset_variant}/{n-rule}/
                        batch__{model-slug}__{prompting_condition}__{dataset_variant}__{pattern_id}__n{N}__...jsonl
      sequential/
        {model-slug}/{prompting_condition}/{dataset_variant}/{n-rule}/
                        seq__{model-slug}__{prompting_condition}__{dataset_variant}__{pattern_id}__n{N}__...jsonl
    responses/
      openai-batch/
        {model-slug}/{prompting_condition}/{dataset_variant}/{n-rule}/
                        response__{model-slug}__{prompting_condition}__{dataset_variant}__{pattern_id}__n{N}__...
                          __batch_{batch-id}__{YYYYMMDDHHMMSS}.jsonl
    eval/
      {strict,flex}/
        {response_type}/{model}/{prompting_condition}/{dataset_variant}/{n-rule}/
                        eval-{mode}__{model}__{prompting_condition}__{dataset_variant}__{pattern_id}__n{N}__...jsonl
    reports/
      {strict,flex}/
                        scores-{mode}.csv
                        scores-{mode}__{model}.xlsx
                        composite_metrics-{mode}.csv
```

---

## クイックスタート: 既存データセットで LLM を評価する

### 1. 依存関係のインストール

```bash
pip install -r requirements.txt
```

### 2. Zenodo からベンチマークを取得

ベンチマークは [Zenodo（DOI: 10.5281/zenodo.19867258）](https://doi.org/10.5281/zenodo.19867258) で公開しています。`tasks.zip` をダウンロードして、プロジェクトのデータディレクトリに展開します:

```bash
mkdir -p data/llm-eval
cd data/llm-eval && unzip /path/to/tasks.zip && cd -
```

展開すると `data/llm-eval/tasks/zeroshot/{prompting_condition}/{dataset_variant}/{n-rule}/task__*.json` が並びます。

### 3. 評価パイプラインへ進む

[ステップ 1 — LLM の登録](#ステップ-1--llm-の登録) に進みます。

---

## フルビルド: LOD ソースからデータセットを構築する

### 1. 依存関係のインストール

```bash
pip install -r requirements.txt
```

### 2. LOD サンプルの取得

単一ルールの例:

```bash
python scripts/fetch-samples/1-rule/fetch_samples_rdfs2.py --date 20260418
```

19の含意パターンを一括実行:

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

全 dataset variant を一括生成:

```bash
python scripts/build-dataset/run_all.py
```

個別に生成する場合:

```bash
python scripts/build-dataset/from-samples/gen_rk.py
python scripts/build-dataset/from-samples/gen_ls.py
python scripts/build-dataset/from-samples/gen_gs-gsc.py
python scripts/build-dataset/standalone/gen_ns.py
python scripts/build-dataset/standalone/gen_nsc.py
python scripts/build-dataset/standalone/gen_rva.py
```

出力先: `data/datasets/{dataset_variant}/{1,2,3}-rule/dataset__*.json`

### 5. ゼロショットタスクファイルの生成

生成したデータセットから、各プロンプト条件（PRT × Rule Format）のプロンプトファイルを作ります。

全 prompting condition × 全 dataset variant を一括生成:

```bash
python scripts/llm-eval/tasks/build_zeroshot_tasks.py
```

絞り込みの例:

```bash
python scripts/llm-eval/tasks/build_zeroshot_tasks.py \
  --dataset-variants rva,gs \
  --prompting-conditions NRP-full,ARP-full \
  --patterns rdfs2,rdfs9
```

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--dataset-variants` | 全て | カンマ区切りの dataset variant（例: `rva,gs`）|
| `--prompting-conditions` | 全6種 | カンマ区切りの prompting condition（例: `NRP-full,ARP-name`）|
| `--patterns` | 全て | カンマ区切りの pattern id（例: `rdfs2,rdfs2_3`）|
| `--entry-limit` | 0（無制限）| デバッグ用: データセットファイルあたりのエントリ上限 |
| `--max-files` | 0（無制限）| デバッグ用: 処理するファイル数の上限 |
| `--overwrite` | スキップ | 既存タスクファイルをスキップせず上書きする |
| `--verbose` | — | 保存ファイルのパスを逐次出力する（デフォルト: サマリーのみ）|

出力先: `data/llm-eval/tasks/zeroshot/{prompting_condition}/{dataset_variant}/{n-rule}/task__*.json`

### 6. 評価パイプラインへ進む

[ステップ 1 — LLM の登録](#ステップ-1--llm-の登録) に進みます。

---

## LLM 評価パイプライン

クイックスタートとフルビルドのどちらでも共通で実行するパイプラインです。

### ステップ 1 — LLM の登録

評価したい LLM を `scripts/llm-eval/model-config.json` に追加します。各エントリは、パイプラインで `--model` 引数として使うモデル *slug* を、`runner`（実行方式）と `api_model`（API 上のモデル名）に対応付けます:

```json
{
  "your-model-slug": {
    "runner": "sequential-openai-compat",
    "api_model": "provider/model-name"
  }
}
```

`runner` に指定できる値:

| Runner | 用途 |
|---|---|
| `openai-batch` | OpenAI Batch API（例: GPT-4o）|
| `sequential-openai-compat` | OpenAI 互換 HTTP API（例: DeepInfra で公開されているモデル）|
| `sequential-ollama` | ローカルまたはリモートの Ollama デーモン |

### ステップ 2 — リクエストファイルの作成

**OpenAI Batch API 用:**

```bash
python scripts/llm-eval/adapters/to_openai_batch.py \
  --model gpt-4o-mini-2024-07-18 \
  --prompting-conditions NRP-full \
  --dataset-variants rva
```

**逐次実行（OpenAI互換 / Ollama）用:**

```bash
python scripts/llm-eval/adapters/to_sequential.py \
  --model llama3.1-8b \
  --prompting-conditions NRP-full \
  --dataset-variants rva
```

使用可能なモデルは `scripts/llm-eval/model-config.json` で定義します。`--model` にはスラグ（config のキー）を指定し、実際の API モデル名はスクリプト内部で解決されます。

### ステップ 3 — LLM 推論の実行

各 runner は `data/llm-eval/requests/input-queues/` 配下の*キューディレクトリ*からリクエストファイルを読みます。モデルに対応する runner 種別を選び、キューサブディレクトリを作成し、ステップ 2 で生成したリクエストファイルをコピーしてから `--queue <名前>` で runner を起動します。

#### OpenAI Batch

キューディレクトリを作成:

```bash
mkdir -p data/llm-eval/requests/input-queues/openai-batch/<queue-name>
```

リクエストファイルをコピー:

```bash
cp data/llm-eval/requests/openai-batch/<model>/<prompting_condition>/<dataset_variant>/*/batch__*.jsonl \
   data/llm-eval/requests/input-queues/openai-batch/<queue-name>/
```

バッチをアップロード:

```bash
python scripts/llm-eval/run/openai_batch_upload.py --queue <queue-name>
```

全バッチが完了するまで download を繰り返し実行:

```bash
python scripts/llm-eval/run/openai_batch_download.py --queue <queue-name>
```

アップロード結果は `input-queues/openai-batch/<queue-name>/upload_mapping.json` に記録されます。**このファイルは編集・削除しないでください** — `openai_batch_download.py` がアップロード済みジョブのバッチ ID を参照するために読み込みます。

#### 逐次実行（OpenAI 互換 API）

`model-config.json` で `runner: "sequential-openai-compat"` のモデル（DeepInfra ホスト等）が対象です。
`.env` に以下の変数を設定してください:

```
OPENAI_COMPAT_API_KEY=<your-api-key>
OPENAI_COMPAT_BASE_URL=https://api.deepinfra.com/v1/openai
```

キューディレクトリを作成:

```bash
mkdir -p data/llm-eval/requests/input-queues/openai-compat/<queue-name>
```

リクエストファイルをコピー:

```bash
cp data/llm-eval/requests/sequential/<model>/<prompting_condition>/<dataset_variant>/*/seq__*.jsonl \
   data/llm-eval/requests/input-queues/openai-compat/<queue-name>/
```

推論を実行:

```bash
python scripts/llm-eval/run/run_sequential_openai_compat.py --queue <queue-name>
```

#### 逐次実行（Ollama）

`model-config.json` で `runner: "sequential-ollama"` のモデルが対象です。
Ollama デーモンが起動済みで対象モデルがプル済みである必要があります。

キューディレクトリを作成:

```bash
mkdir -p data/llm-eval/requests/input-queues/ollama/<queue-name>
```

リクエストファイルをコピー:

```bash
cp data/llm-eval/requests/sequential/<model>/<prompting_condition>/<dataset_variant>/*/seq__*.jsonl \
   data/llm-eval/requests/input-queues/ollama/<queue-name>/
```

推論を実行:

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

出力先: `data/llm-eval/responses/sequential/{slug}/{prompting_condition}/{dataset_variant}/{n-rule}/response__*.jsonl`

### ステップ 4 — 出力の評価

デフォルトでは `data/llm-eval/responses/` 以下の全レスポンス種別（`openai-batch`、`sequential` 等）をまとめて評価します。

#### Strict モード（デフォルト）

正規形式 `<s, p, o>` のみを正解トリプルとして受け入れます。

```bash
python scripts/llm-eval/eval/evaluate_outputs.py --mode strict
```

#### Flex モード

順序ベースのマッチング。`<s,p,o>`、`<s , p , o>`、`<s p o>` のような区切り文字や空白の表記揺れを許容します。

```bash
python scripts/llm-eval/eval/evaluate_outputs.py --mode flex
```

#### レスポンス種別での絞り込み

`--response-type` で特定のレスポンス種別のみを評価します。

```bash
python scripts/llm-eval/eval/evaluate_outputs.py --mode strict --response-type sequential
```

```bash
python scripts/llm-eval/eval/evaluate_outputs.py --mode strict --response-type openai-batch
```

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--mode` | `strict` | 評価モード: `strict` または `flex` |
| `--response-type` | 全て | `responses/` 以下のサブディレクトリ（例: `openai-batch`, `sequential`）。省略時は全種別を評価 |
| `--models` | 全て | 絞り込むモデルスラグ（カンマ区切り）|
| `--prompting-conditions` | 全て | 絞り込む prompting condition（カンマ区切り）|
| `--dataset-variants` | 全て | 絞り込む dataset variant（カンマ区切り）|
| `--patterns` | 全て | 絞り込む pattern id（カンマ区切り）|
| `--overwrite` | スキップ | 既存の評価ファイルを上書きする |
| `--verbose` | — | ファイルごとの詳細を出力する |

出力先: `data/llm-eval/eval/{strict,flex}/{response_type}/{model}/...`

### （任意）実験状況の確認

モデルごとの実験進捗を Excel に書き出します：

```bash
python scripts/llm-eval/report/export_status_excel.py --overwrite
```

出力先: `data/llm-eval/reports/status.xlsx`（モデルごとに1シート）

各セルは (prompting_condition, pattern_id, dataset_variant) の組み合わせの状態を示します：

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
- **Detail シート** — (model, prompting_condition, dataset_variant, pattern_id) 単位の内訳

input トークンはリクエストファイルのプロンプトメッセージから計算します。
output トークンはタスクファイルの `expected_output` から推定します（ARP 系は `[used_rules: ...]` 行も含む）。

#### モデルごとの単価設定

単価は `scripts/llm-eval/model-pricing.json` から読み込まれます。各エントリは、モデル slug を 100 万トークンあたりの USD レートに対応付けます:

```json
{
  "your-model-slug": {
    "input_per_1m": 0.075,
    "output_per_1m": 0.30
  }
}
```

| フィールド | 単位 | 説明 |
|---|---|---|
| `input_per_1m` | USD / 1M トークン | プロンプト（入力）トークンの単価 |
| `output_per_1m` | USD / 1M トークン | 補完（出力）トークンの単価 |

ローカル実行や無料モデルの場合は両フィールドを `0.0` にしてください。`estimate_budget.py` を実行する前に、最新のレートに合わせて編集します。

> **推論モデルに関する注意。** 本見積もりはプロンプトと期待出力の可視トークンのみをカウントし、一部のモデル（例: gpt-oss 系）が別計算する**内部推論トークンは考慮しません**。推論モデルの予算を見積もる際は、必ず小規模なパイロット実行を行い、API が返す実使用量から外挿してください。

### ステップ 5 — スコアの集計

```bash
python scripts/llm-eval/report/aggregate_scores.py --mode strict
python scripts/llm-eval/report/aggregate_scores.py --mode flex
```

出力先: `data/llm-eval/reports/{strict,flex}/scores-{mode}.csv`

### ステップ 6 — モデル別スコアシートの出力

ステップ 5 で集計した CSV を、モデルごとに 1 つの Excel ファイルへ分割します。各ファイル内ではプロンプト条件（NRP-full、ARP-name 等）ごとにシートが分かれます。

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

出力カラム:

| カラム | 正式名 |
|---|---|
| `RI` | Real-world Inference |
| `SI` | Structural Inference |
| `RRS` | Real-world Rule Selection |
| `SRS` | Structural Rule Selection |
| `VR` | Vocabulary Robustness |
| `TR` | Typographic Robustness |
| `RDI` | Rule Definition Independence |

各指標の正確な定義は論文を参照してください。

### （任意）スケーリング分析

1-rule / 2-rule / 3-rule で F1 がどう変化するかを、ルール形式（full / def / name）ごとに分析します：

```bash
python scripts/llm-eval/report/analyze_scaling.py --mode strict
python scripts/llm-eval/report/analyze_scaling.py --mode flex
```

出力先: `data/llm-eval/reports/{strict,flex}/scaling_analysis-{mode}.xlsx`。各 (Rule Format × dataset_variant) の組み合わせごとに 1 シートが生成されます。シート名の形式:

| Rule Format | シート名 | 例 |
|---|---|---|
| `full` | `<dataset_variant>` | `rk`, `ls`, `ns`, ... |
| `def` | `<dataset_variant>-def` | `rk-def`, `ls-def`, ... |
| `name` | `<dataset_variant>-name` | `rk-name`, `ls-name`, ... |

### （任意）ルールレベル分析

各ルール単体の F1 を、Rule Format が `full` の 1 ルール含意パターンのみから算出します。

```bash
python scripts/llm-eval/report/analyze_rule_accuracy.py --mode strict
python scripts/llm-eval/report/analyze_rule_accuracy.py --mode flex
```

出力先: `data/llm-eval/reports/{strict,flex}/rule_accuracy_analysis-{mode}.xlsx`（データセット種類ごとに1シート）

### （任意）データセット別 F1 集計

`full` 設定のみ、6セル（NRP/ARP × {1-rule, 2-rule, 3-rule}）の平均 F1 を、行=LLM・列=データセット種類の単一表にまとめます：

```bash
python scripts/llm-eval/report/f1_by_dataset_table.py --mode strict
python scripts/llm-eval/report/f1_by_dataset_table.py --mode flex
```

出力先: `data/llm-eval/reports/{strict,flex}/f1_by_dataset-{mode}.xlsx`

---

## データフォーマット

### LOD サンプル（`data/lod-samples/`）

各ルールに対する SPARQL クエリの生結果。`entries` 配列にはエンドポイントから取得した変数バインディングが入ります。

```json
{
  "metadata": {
    "endpoints": ["https://dbpedia.org/sparql"],
    "fetched_at": "20241216",
    "pattern_id": "rdfs9",
    "rules": ["rdfs9"],
    "source": "dbp",
    "limit": 400,
    "fetch_uid": "f-1862e2be",
    "count": 400
  },
  "entries": [
    {
      "a": "http://dbpedia.org/resource/Toll-like_receptor_5",
      "x": "http://dbpedia.org/ontology/Gene",
      "y": "http://dbpedia.org/ontology/Biomolecule"
    }
  ]
}
```

### データセットエントリ（`data/datasets/`）

プロンプト構築に使う前提知識と期待出力のペア集。

```json
{
  "metadata": {
    "pattern_id": "rdfs2",
    "rules": ["rdfs2"],
    "dataset_variant": "rva",
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

プロンプト条件ごとの、レンダリング済みプロンプトを保持するタスクファイル。

```json
{
  "metadata": {
    "prompting_condition": "NRP-full",
    "dataset_variant": "rva",
    "pattern_id": "rdfs2",
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

### リクエストファイル — sequential（`data/llm-eval/requests/sequential/`）

JSON Lines 形式。1 行 1 リクエスト。

```json
{"id": "request-1", "model": "openai/gpt-oss-120b", "input": "Given the following rule and premise knowledge: ..."}
```

### リクエストファイル — OpenAI Batch（`data/llm-eval/requests/openai-batch/`）

OpenAI Batch API の JSON Lines 形式。

```json
{
  "custom_id": "request-1",
  "method": "POST",
  "url": "/v1/chat/completions",
  "body": {
    "model": "gpt-4o-2024-08-06",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Given the following rule and premise knowledge: ..."}
    ]
  }
}
```

### レスポンスファイル（`data/llm-eval/responses/`）

JSON Lines 形式。1 行 1 レスポンス。推論モデルの場合は `reasoning_content` フィールドが追加されます。

```json
{"id": "request-1", "response": "<Alice, rdf:type, Person>"}
```

### 評価結果（`data/llm-eval/eval/`）

JSON Lines 形式。1 リクエストあたり 1 行で、precision / recall / F1 と、抽出・フィルタ済みのトリプルが記録されます。

```json
{
  "task_id": "request-1",
  "premise_knowledge": "<hasJob, rdfs:domain, Person>, <Alice, hasJob, Engineer>",
  "expected_output": "<Alice, rdf:type, Person>",
  "model_output": "<Alice, rdf:type, Person>",
  "expected_triples": ["Alice, rdf:type, Person"],
  "filtered_triples": ["Alice, rdf:type, Person"],
  "precision_triple": 1.0,
  "recall_triple": 1.0,
  "f1_triple": 1.0,
  "triple_ok": true,
  "overall_ok": true
}
```

---

## ファイル命名規則

| ファイル種別 | パターン |
|---|---|
| LOD サンプル | `lod-sample__{pattern_id}__n{N}__f-{uid}.json` |
| データセット | `dataset__{dataset_variant}__{pattern_id}__n{N}__f-{uid}__b-{uid}.json` |
| タスク | `task__{prompting_condition}__{dataset_variant}__{pattern_id}__n{N}__{uid}__{uid}.json` |
| バッチリクエスト | `batch__{slug}__{prompting_condition}__{dataset_variant}__{pattern_id}__n{N}__{uid}__{uid}.jsonl` |
| 逐次リクエスト | `seq__{slug}__{prompting_condition}__{dataset_variant}__{pattern_id}__n{N}__{uid}__{uid}.jsonl` |
| バッチレスポンス | `response__{slug}__{prompting_condition}__{dataset_variant}__{pattern_id}__n{N}__{uid}__{uid}__batch_{id}__{ts}.jsonl` |
| 評価結果 | `eval-{mode}__{slug}__{prompting_condition}__{dataset_variant}__{pattern_id}__n{N}__{uid}__{uid}__batch_{id}__{ts}.jsonl` |

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

