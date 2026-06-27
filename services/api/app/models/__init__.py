# Import all ORM models so Alembic can detect them
from app.models.user import User, UserAppPermission  # noqa: F401
from app.models.config import DatasourceConfig, ErrorClassifierPattern  # noqa: F401
from app.models.server import ServerRegistry  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.system_setting import SystemSetting  # noqa: F401
from app.models.chat_session import ChatSession  # noqa: F401
from app.models.chat_message import ChatMessage  # noqa: F401
from app.models.incident import Incident, IncidentTimeline  # noqa: F401
from app.models.topology import TopologyVersion, TopologyNode, TopologyEdge  # noqa: F401
