"""向量数据库模块 - 使用 ChromaDB（支持用户隔离）"""
import hashlib
import os
import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
from app.config import KNOWLEDGE_DIR


class SentenceTransformerEmbedding(EmbeddingFunction):
    """使用 sentence-transformers 本地模型生成高质量文本向量"""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
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

        # 创建持久化 Chroma 客户端
        self.client = chromadb.PersistentClient(path=str(KNOWLEDGE_DIR))

        # 本地 Embedding 函数（sentence-transformers，语义级理解）
        self.embedding_function = SentenceTransformerEmbedding(
            model_name="all-MiniLM-L6-v2"
        )

    def _get_collection_name(self, user_id: int) -> str:
        """根据用户 ID 获取集合名称"""
        return f"knowledge_user_{user_id}"

    def _get_collection(self, user_id: int):
        """获取或创建用户的知识集合"""
        return self.client.get_or_create_collection(
            name=self._get_collection_name(user_id),
            embedding_function=self.embedding_function,
            metadata={"hnsw:space": "cosine"}
        )

    def add_document(self, content: str, user_id: int, metadata: dict = None) -> str:
        """添加文档到指定用户的向量数据库"""
        collection = self._get_collection(user_id)

        doc_id = hashlib.md5(content.encode()).hexdigest()

        # 检查是否已存在
        existing = collection.get(ids=[doc_id])
        if existing["ids"]:
            return doc_id

        # 确保 metadata 非空（ChromaDB 要求）
        if not metadata:
            metadata = {"added": "true"}

        collection.add(
            documents=[content],
            ids=[doc_id],
            metadatas=[metadata]
        )
        return doc_id

    def search(self, query: str, user_id: int, top_k: int = 3) -> list:
        """搜索指定用户的最相似文档"""
        collection = self._get_collection(user_id)
        if collection.count() == 0:
            return []

        results = collection.query(
            query_texts=[query],
            n_results=min(top_k, collection.count())
        )

        search_results = []
        for i, (doc_id, doc, distance) in enumerate(
            zip(
                results["ids"][0],
                results["documents"][0],
                results["distances"][0]
            )
        ):
            similarity = 1.0 / (1.0 + distance) if distance else 1.0
            search_results.append({
                "score": similarity,
                "document": {
                    "id": doc_id,
                    "content": doc,
                    "metadata": results["metadatas"][0][i]
                }
            })

        return search_results

    def get_stats(self, user_id: int) -> dict:
        """获取指定用户的数据库统计信息"""
        collection = self._get_collection(user_id)
        return {
            "total_docs": collection.count(),
            "index_ready": True
        }

    def delete_document(self, doc_id: str, user_id: int) -> bool:
        """删除指定用户的指定文档"""
        try:
            collection = self._get_collection(user_id)
            collection.delete(ids=[doc_id])
            return True
        except Exception:
            return False

    def clear_all(self, user_id: int):
        """清空指定用户的所有文档"""
        collection_name = self._get_collection_name(user_id)
        self.client.delete_collection(collection_name)
        self._get_collection(user_id)


# 全局单例
vector_db = ChromaVectorDB()
