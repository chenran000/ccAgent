"""文件解析模块 - 从 PDF 等文件中提取文本"""
import pdfplumber
from typing import Optional


SUPPORTED_EXTENSIONS = {".pdf", ".txt"}


def extract_text_from_pdf(file_path: str) -> str:
    """
    从 PDF 文件中提取文本

    Args:
        file_path: PDF 文件路径

    Returns:
        提取的文本内容
    """
    with pdfplumber.open(file_path) as pdf:
        pages_text = []
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)
        return "\n\n".join(pages_text)


def extract_text_from_txt(file_path: str) -> str:
    """
    从 TXT 文件中读取文本

    Args:
        file_path: TXT 文件路径

    Returns:
        读取的文本内容
    """
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def parse_file(file_path: str, filename: str) -> str:
    """
    解析文件并提取文本（根据扩展名自动选择解析器）

    Args:
        file_path: 文件路径
        filename: 文件名（用于判断类型）

    Returns:
        提取的文本内容
    """
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"不支持的文件类型: {ext}，仅支持 {SUPPORTED_EXTENSIONS}")

    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    if ext == ".txt":
        return extract_text_from_txt(file_path)

    raise ValueError(f"无法解析文件: {filename}")
