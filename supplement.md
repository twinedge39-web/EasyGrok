
---

## 🔎 補足説明

---

### 🐍 実行環境について

このスクリプトは **Python 仮想環境（VENV）内での実行を推奨します。**

Python環境の構築方法については本READMEでは説明しません。
各自の環境に応じて準備してください。

例：

```bash
python -m venv .venv
source .venv/bin/activate  # Windowsは .venv\Scripts\activate
pip install xai-sdk
```

グローバル環境を汚さないため、VENV使用を推奨します。

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
