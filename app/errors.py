"""应用级异常定义"""


class DocumentValidationError(Exception):
    """文档上传/解析不满足规则"""
