"""文件内容预览模块 - 判断文件类型并读取内容供前端展示"""
import base64
import mimetypes
import os

# 可直接以文本预览的扩展名
TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".html", ".htm", ".css",
    ".scss", ".less", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".md", ".txt", ".csv", ".sql", ".sh", ".bat", ".ps1", ".java", ".kt",
    ".go", ".rs", ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".rb", ".swift",
    ".xml", ".svg", ".log",
}

# 可预览的图片扩展名
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico"}

# 超过该大小的文本文件不再读取内容
MAX_TEXT_SIZE = 2 * 1024 * 1024

_LANGUAGE_BY_EXT = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
    ".jsx": "jsx", ".vue": "vue", ".html": "html", ".htm": "html", ".css": "css",
    ".scss": "scss", ".less": "less", ".json": "json", ".yaml": "yaml",
    ".yml": "yaml", ".toml": "toml", ".md": "markdown", ".sql": "sql",
    ".sh": "shell", ".bat": "batch", ".ps1": "powershell", ".java": "java",
    ".kt": "kotlin", ".go": "go", ".rs": "rust", ".c": "c", ".cpp": "cpp",
    ".cs": "csharp", ".php": "php", ".rb": "ruby", ".swift": "swift",
    ".xml": "xml", ".svg": "xml",
}


def _detect_language(ext: str) -> str:
    return _LANGUAGE_BY_EXT.get(ext, "")


def read_file_content(file_path: str) -> dict:
    """读取文件内容,返回前端预览所需的完整信息"""
    result = {
        "content": "",
        "content_type": "text/plain",
        "language": "",
        "is_binary": False,
        "image_url": "",
        "size": 0,
        "error": "",
    }

    if not os.path.isfile(file_path):
        result["error"] = "文件不存在"
        return result

    result["size"] = os.path.getsize(file_path)
    ext = os.path.splitext(file_path)[1].lower()

    if ext in IMAGE_EXTENSIONS:
        result["content_type"] = mimetypes.guess_type(file_path)[0] or "image/png"
        result["is_binary"] = True
        try:
            with open(file_path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            result["image_url"] = f"data:{result['content_type']};base64,{data}"
        except Exception as e:
            result["error"] = f"读取图片失败: {e}"
        return result

    if ext not in TEXT_EXTENSIONS:
        result["is_binary"] = True
        result["error"] = "二进制文件，不支持预览"
        return result

    if result["size"] > MAX_TEXT_SIZE:
        result["error"] = "文件过大，不支持在线预览"
        return result

    result["content_type"] = mimetypes.guess_type(file_path)[0] or "text/plain"
    result["language"] = _detect_language(ext)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            result["content"] = f.read()
    except UnicodeDecodeError:
        result["is_binary"] = True
        result["content"] = ""
        result["error"] = "二进制文件，不支持预览"
    except Exception as e:
        result["error"] = f"读取失败: {e}"

    return result
