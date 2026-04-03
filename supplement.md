
---

## 🔎 補足説明

---

### 🐍 実行環境について

このスクリプトは **Python 仮想環境（VENV）内での実行を推奨します。**
特に Windows では、カレントディレクトリが正しくてもグローバル Python を使ってしまう事故が起こりやすいため、実行する Python 本体を意識してください。

Python環境の構築方法については本READMEでは説明しません。
各自の環境に応じて準備してください。

例：

```bash
python -m venv .venv
source .venv/bin/activate  # Windowsは .venv\Scripts\activate
pip install xai-sdk
```

グローバル環境を汚さないため、VENV使用を推奨します。

Windows (PowerShell) では、仮想環境を有効化する場合は次を使います。

```powershell
.\.venv\Scripts\Activate.ps1
```

ただし、より安全なのは `venv` 内の Python を直接指定する方法です。

```powershell
.\.venv\Scripts\python.exe easy.py text
```

この形なら、全体の `python` や `py` を誤って使う事故を減らせます。

確認したい場合は、実行前に次を見ます。

```powershell
python -V
Get-Command python
```

事故防止の観点では、重要な実行ほど `.\.venv\Scripts\python.exe` を明示する運用を推奨します。

---

### 🔐 APIキーについて

APIキーは **環境変数に設定することを前提としています。**

```bash
export XAI_API_KEY="your_api_key"
```

Windows (PowerShell):

```powershell
setx XAI_API_KEY "your_api_key"
```

* スクリプト内に直接キーを書きません。
* configファイルにAPIキーを記述する箇所はありません。
* 事故防止のため、各自の環境で設定してください。

---

### 🎛 操作方法について

各種コマンド（text / vision / image）は個別実行可能ですが、

**基本操作は `menu` スクリプトからすべて可能です。**

```bash
python easy.py menu
```

* config編集
* 実行
* モード切替
* バックアップ生成

これらを一括で管理できます。

---

以上を踏まえた上で、`README.md` を参照してください。

---

> This repository assumes basic Python literacy.
