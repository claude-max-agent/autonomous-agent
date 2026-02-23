"""
embeddings.py - ローカル埋め込みモデルラッパー

Phase 1: sentence-transformers（ローカル実行・プライバシー重視）
推奨モデル: BAAI/bge-m3（JMTEB日本語 79.74、Dense+Sparse対応）
軽量代替:  intfloat/multilingual-e5-small（速度重視）
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)

# モデル選択
DEFAULT_MODEL = "BAAI/bge-m3"
FAST_MODEL    = "intfloat/multilingual-e5-small"


class EmbeddingModel:
    """sentence-transformers ローカル埋め込みモデル"""

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name
        self._model = None
        log.info(f"EmbeddingModel initialized (lazy load): {model_name}")

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                log.info(f"Loading model: {self.model_name} ...")
                self._model = SentenceTransformer(self.model_name)
                log.info(f"Model loaded: {self.model_name}")
            except ImportError:
                raise ImportError(
                    "sentence-transformers がインストールされていません。"
                    "`pip install sentence-transformers` を実行してください。"
                )

    def encode(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """テキストリストをベクトルに変換"""
        self._load()
        embeddings = self._model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=len(texts) > 100,
            normalize_embeddings=True,  # cosine similarity 用に正規化
        )
        return embeddings.tolist()

    def encode_one(self, text: str) -> list[float]:
        """単一テキストをベクトルに変換"""
        return self.encode([text])[0]


# シングルトン
_model: Optional[EmbeddingModel] = None

def get_model(fast: bool = False) -> EmbeddingModel:
    """埋め込みモデルを取得（シングルトン）"""
    global _model
    if _model is None:
        model_name = FAST_MODEL if fast else DEFAULT_MODEL
        _model = EmbeddingModel(model_name)
    return _model


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    model = get_model(fast=True)  # テストは軽量モデルで
    texts = [
        "HyperLiquidのパーペチュアル取引について",
        "Claude APIを使ったエージェント実装",
        "Pythonのデータ処理",
    ]
    print(f"Encoding {len(texts)} texts...")
    vecs = model.encode(texts)
    print(f"Vector dim: {len(vecs[0])}")
    print("Done!")
