# EasyGrok ロードマップ

EasyGrok は、xAI Grok API をローカルで検証・運用するための
再現性重視の実験環境です。

中心テーマはこれです。

```text
AI実行を、明示的に、検証可能に、再利用可能にする。
```

EasyGrok は、プロンプトやモデル設定、入力画像、出力、ログを
見えない場所に隠しません。

何を送ったのか。  
何が返ってきたのか。  
あとからどう確認できるのか。

そこを明確にするためのローカル環境です。

---

## 基本方針

### 透明性を優先する

各実行では、できるだけ次の情報を残します。

- model
- prompt
- context files
- image inputs
- output format
- raw response
- Markdown summary

目的は、生成結果を「なんとなく出たもの」にしないことです。

### CLI First

EasyGrok の正本は CLI です。

Tkinter UI は、CLI コマンドを組み立てて実行するための
オーケストレーションUIです。

これにより、実行内容を確認しやすく、自動化や再実行もしやすくなります。

### ローカルファイルを正本にする

生成URLは便利ですが、期限切れや差し替え、消失の可能性があります。

EasyGrok は、重要な出力をローカルに保存し、
その生成条件と一緒に確認できる状態を目指します。

### Tool実行は人間が承認する

LLM が EasyGrok のローカル実行を提案した場合、
UI は実行コマンドを表示し、人間の承認を待ちます。

モデルは提案する。  
実行の最終トリガーはユーザーが持つ。

この構造を重視します。

---

## 現在できること

現在実装済みの主な機能です。

- Text 実行
- Text 実行への画像URL / ローカル画像添付
- Vision 実行
- Image 生成
- Image edit / reference edit
- Batch image generation
- Imagine relay
- Natural Imagine relay
- Raw JSON / Markdown ログ保存
- Markdown context memory
- Session append / reset / archive
- Tkinter prompt console
- Logs タブでのログ閲覧と replay command preview
- Tool request detection / approval
- Recent generated image handoff
- Video route scaffold

まだ未実装のものです。

- 実際のVideo生成APIフロー
- Job queue / polling
- 自動retry policy
- Prompt success database
- Local Stable Diffusion adapter
- Local LLM adapter
- Persona profile switching

---

## ロードマップ

### 1. Replay / Audit の強化

Replay は完全再現ではありません。

LLM や画像生成APIは、時間やモデル状態によって結果が変わる可能性があります。

EasyGrok における Replay は、次の意味です。

```text
同じコマンド
同じプロンプト
同じcontext
同じmodel設定
新しいAPI実行
```

つまり「条件の再構築」です。

今後の候補：

- raw JSON と Markdown ログの対応強化
- replay差分の見える化
- tool approval metadata の記録
- ローカルファイル参照の保持
- 保存画像の checksum

### 2. ローカル保存を標準経路にする

URL出力は便利ですが、長期保存には向きません。

今後の候補：

- URL画像の optional auto-download
- 保存ファイルの checksum
- media横のmetadata保存
- UIからのローカル出力確認

### 3. Public Profile と Lab Profile を分ける

公開可能な構成と、ローカル実験用の構成は分ける必要があります。

今後の候補：

- public-safe example config
- lab config conventions
- ignored-file boundary の明確化
- commitしてはいけないものの文書化

### 4. Prompt / Log Index を作る

ログは、検索・タグ付け・再利用できると価値が上がります。

今後の候補：

- log index
- tags
- favorites
- reuse count
- success / moderation result
- prompt family notes

### 5. Queue を汎用Job Systemにする

Video生成では、polling や delayed completion が必要になります。

同じ考え方は、将来的に長い生成ワークフローにも使えます。

例：

```text
rewrite prompt
generate
analyze result
suggest fix
retry with limit
archive output
```

今後の候補：

- job queue
- max retry limits
- progress display
- result archive

### 6. Engineを慎重に増やす

EasyGrok は xAI API 専用のままではなく、
透明性を保ったまま他の生成・解析エンジンにも広げられます。

候補：

- local Stable Diffusion APIs
- ComfyUI
- AUTOMATIC1111 / Forge compatible endpoints
- Ollama
- LM Studio
- llama.cpp
- vLLM

ローカルLLMの用途候補：

- rewrite
- classification
- tagging
- low-cost review

### 7. Persona と Safety Profile を分ける

Persona は、口調・目的・既定ワークフローを決めます。

Safety Profile は、それとは別に運用条件を決めます。

将来的な構造：

```text
persona profile
+
safety profile
+
tool permissions
```

これにより、同じpersonaでも public-safe / lab / review-only などの
運用モードを切り替えやすくします。

---

## 長期的な方向性

EasyGrok は、ローカルAI運用ベンチを目指しています。

```text
prompt
context
tool request
human approval
execution
local output
log
review
replay
```

重要なのは、単に生成することだけではありません。

何が起きたかを残すこと。  
証拠を保存すること。  
次の実行をより判断しやすくすること。

EasyGrok は、そのための運用環境です。

