"""向量数据库模块 - ChromaDB（按用户隔离）+ 分块/阈值/重排 RAG 管线

检索链路: 超量召回 → 相关度阈值过滤 → CrossEncoder 重排 → 截断 top_k。
入库链路: 中文友好分块(段落/句子边界,超长句硬切保留重叠) → 同一文档的分块
共享 doc_id 元数据,删除/列表均按父文档聚合。
"""
import hashlib
import os
import re
from typing import Any, Dict, List

import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings

from app.config import (
    EMBEDDING_MODEL,
    KNOWLEDGE_DIR,
    RAG_CHUNK_OVERLAP,
    RAG_CHUNK_SIZE,
    RAG_MIN_SIMILARITY,
    RAG_RERANK_ENABLED,
    RAG_RERANK_MODEL,
)


def chunk_text(text: str, chunk_size: int = None, overlap: int = None) -> List[str]:
    """中文友好的文本分块:优先按段落与句子边界切分,超长句子硬切并保留重叠"""
    chunk_size = chunk_size or RAG_CHUNK_SIZE
    overlap = overlap or RAG_CHUNK_OVERLAP
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    sentences = [s.strip() for s in re.split(r"(?<=[。！？；!?;\n])", text) if s.strip()]
    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) <= chunk_size:
            current += sentence
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(sentence) > chunk_size:
            chunks.append(sentence[:chunk_size])
            sentence = sentence[chunk_size - overlap:]
        current = sentence
    if current:
        chunks.append(current)
    return chunks


class SentenceTransformerEmbedding(EmbeddingFunction):
    """使用 sentence-transformers 本地模型生成高质量文本向量"""

    def __init__(self, model_name: str = EMBEDDING_MODEL):
        from sentence_transformers import SentenceTransformer
        # 优先使用环境变量指定镜像
        if "HF_ENDPOINT" not in os.environ:
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        # 优先加载本地缓存，不尝试联网
        self._model = SentenceTransformer(model_name, local_files_only=True)

    def __call__(self, input: Documents) -> Embeddings:
        embeddings = self._model.encode(input, show_progress_bar=False)
        # 确保返回 list[list[float]] 格式
        return [emb.tolist() for emb in embeddings]


class ChromaVectorDB:
    """基于 ChromaDB 的向量数据库（按用户隔离）"""

    def __init__(self):
        KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

        # 当前使用的 Embedding 模型（更换后旧集合维度不兼容，需清空知识库重建）
        self.model_name = EMBEDDING_MODEL
        self.min_similarity = RAG_MIN_SIMILARITY

        # 重排模型懒加载缓存
        self._reranker = None
        self._reranker_failed = False

        # 创建持久化 Chroma 客户端
        self.client = chromadb.PersistentClient(path=str(KNOWLEDGE_DIR))

        # 本地 Embedding 函数（sentence-transformers，语义级理解）
        self.embedding_function = SentenceTransformerEmbedding(
            model_name=self.model_name
        )

        # 集合缓存（user_id → collection），避免每次调用都重复做兼容性校验
        self._collections: Dict[int, Any] = {}

    def _get_collection_name(self, user_id: int) -> str:
        """根据用户 ID 获取集合名称"""
        return f"knowledge_user_{user_id}"

    def _get_collection(self, user_id: int):
        """获取或创建用户的知识集合（带 Embedding 模型兼容性校验）"""
        if user_id in self._collections:
            return self._collections[user_id]

        collection = self.client.get_or_create_collection(
            name=self._get_collection_name(user_id),
            embedding_function=self.embedding_function,
            metadata={"hnsw:space": "cosine", "embedding_model": self.model_name}
        )
        self._check_collection_compat(collection)
        self._collections[user_id] = collection
        return collection

    def _check_collection_compat(self, collection):
        """校验已有集合的向量与当前 Embedding 模型是否兼容，不兼容时给出明确错误"""
        stored_model = (collection.metadata or {}).get("embedding_model")

        if stored_model and stored_model != self.model_name:
            raise RuntimeError(
                f"知识库向量由 {stored_model} 生成，与当前 Embedding 模型 {self.model_name} 不兼容，"
                f"请清空知识库后重新添加文档"
            )

        if stored_model is None and collection.count() > 0:
            # 旧版本创建的集合没有模型标记，用一次试查询检测向量维度是否匹配
            try:
                collection.query(query_texts=["兼容性检查"], n_results=1)
            except Exception as e:
                raise RuntimeError(
                    f"知识库向量维度与当前 Embedding 模型 {self.model_name} 不匹配"
                    f"（旧知识库由 all-MiniLM-L6-v2 构建），请清空知识库后重新添加文档: {e}"
                )

    def _get_reranker(self):
        """懒加载 CrossEncoder 重排模型；本地无模型时优雅降级为不重排"""
        if not RAG_RERANK_ENABLED:
            return None
        if self._reranker is None and not self._reranker_failed:
            try:
                from sentence_transformers import CrossEncoder
                self._reranker = CrossEncoder(RAG_RERANK_MODEL, max_length=512)
            except Exception as e:
                print(f"[RAG] 重排模型 {RAG_RERANK_MODEL} 不可用，已跳过重排: {e}")
                self._reranker_failed = True
        return self._reranker

    def add_document(self, content: str, user_id: int, metadata: dict = None) -> str:
        """添加文档：自动分块入库，同一文档的所有分块共享 doc_id 元数据"""
        collection = self._get_collection(user_id)

        doc_id = hashlib.md5(content.encode()).hexdigest()

        # 已存在则跳过（按父文档 id 判重）
        existing = collection.get(where={"doc_id": doc_id}, limit=1)
        if existing["ids"]:
            return doc_id

        base_metadata = metadata or {"added": "true"}
        chunks = chunk_text(content)
        collection.add(
            documents=chunks,
            ids=[f"{doc_id}_{i}" for i in range(len(chunks))],
            metadatas=[
                {**base_metadata, "doc_id": doc_id, "chunk_index": i, "chunk_total": len(chunks)}
                for i in range(len(chunks))
            ],
        )
        return doc_id

    def search(self, query: str, user_id: int, top_k: int = 3) -> list:
        """搜索：超量召回 → 阈值过滤 → 重排 → 截断 top_k"""
        collection = self._get_collection(user_id)
        if collection.count() == 0:
            return []

        fetch_k = min(max(top_k * 4, top_k + 4), collection.count())
        results = collection.query(
            query_texts=[query],
            n_results=fetch_k
        )

        candidates = []
        for i, (doc_id, doc, distance) in enumerate(
            zip(
                results["ids"][0],
                results["documents"][0],
                results["distances"][0]
            )
        ):
            similarity = 1.0 - float(distance)  # cosine 空间: distance = 1 - cos_sim
            if similarity < self.min_similarity:
                continue
            candidates.append({
                "score": round(similarity, 4),
                "document": {
                    "id": doc_id,
                    "content": doc,
                    "metadata": results["metadatas"][0][i] or {}
                }
            })

        if not candidates:
            return []

        return self._rerank(query, candidates)[:top_k]

    def _rerank(self, query: str, candidates: list) -> list:
        """CrossEncoder 精排；模型不可用时按向量相似度原序返回"""
        reranker = self._get_reranker()
        if reranker is None or len(candidates) <= 1:
            return candidates
        try:
            scores = reranker.predict([(query, c["document"]["content"]) for c in candidates])
        except Exception as e:
            print(f"[RAG] 重排失败，按向量相似度返回: {e}")
            return candidates
        for candidate, score in zip(candidates, scores):
            candidate["rerank_score"] = round(float(score), 4)
        candidates.sort(key=lambda c: c["rerank_score"], reverse=True)
        return candidates

    def list_documents(self, user_id: int) -> list:
        """按父文档聚合分块，返回文档级列表"""
        collection = self._get_collection(user_id)
        if collection.count() == 0:
            return []

        results = collection.get()
        metadatas = results.get("metadatas") or [{}] * len(results["ids"])

        grouped: Dict[str, dict] = {}
        for chunk_id, content, meta in zip(results["ids"], results["documents"], metadatas):
            meta = meta or {}
            parent = meta.get("doc_id", chunk_id)
            entry = grouped.setdefault(parent, {"doc_id": parent, "chunks": [], "metadata": meta})
            entry["chunks"].append((meta.get("chunk_index", 0), content))

        documents = []
        for parent, entry in grouped.items():
            ordered = sorted(entry["chunks"], key=lambda item: item[0])
            documents.append({
                "doc_id": parent,
                "content": "\n".join(c for _, c in ordered),
                "chunk_count": len(ordered),
                "metadata": entry["metadata"],
            })
        return documents

    def get_stats(self, user_id: int) -> dict:
        """获取指定用户的数据库统计信息"""
        collection = self._get_collection(user_id)
        return {
            "total_docs": collection.count(),
            "index_ready": True
        }

    def delete_document(self, doc_id: str, user_id: int) -> bool:
        """删除指定文档：按父文档 id 删除全部分块，ids 兜底兼容旧版单文档存储"""
        try:
            collection = self._get_collection(user_id)
            collection.delete(where={"doc_id": doc_id})
            collection.delete(ids=[doc_id])
            return True
        except Exception:
            return False

    def clear_all(self, user_id: int):
        """清空指定用户的所有文档"""
        collection_name = self._get_collection_name(user_id)
        self.client.delete_collection(collection_name)
        self._collections.pop(user_id, None)
        self._get_collection(user_id)


# 全局单例
vector_db = ChromaVectorDB()
