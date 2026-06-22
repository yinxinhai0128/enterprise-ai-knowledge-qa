"""ORM 模型包。导入以便 Base.metadata 收集所有表。"""
from app.models.chat_record import ChatRecord
from app.models.document import DOC_STATUS, Document

__all__ = ["Document", "DOC_STATUS", "ChatRecord"]
