from app.extensions import db
from app.models import InstanceSettings


def get_or_create_instance_settings() -> InstanceSettings:
    row = InstanceSettings.query.first()
    if row:
        return row
    row = InstanceSettings()
    db.session.add(row)
    db.session.commit()
    return row


def resolve_identity(default_app_name: str, default_org_name: str) -> tuple[str, str, str | None, str | None]:
    row = InstanceSettings.query.first()
    if not row:
        return default_app_name, default_org_name, None, None

    app_name = (row.app_name or "").strip() or default_app_name
    org_name = (row.organization_name or "").strip() or default_org_name
    return app_name, org_name, row.app_logo_path, row.organization_logo_path
