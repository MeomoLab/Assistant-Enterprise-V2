"""Single gate for access to an application's saved work."""
from flask import abort
from flask_login import current_user
from .models import Application, Share


def application_for_user(application_id=None, write=False):
    if not current_user.is_authenticated:
        abort(401)
    if current_user.role == "applicant":
        app = Application.query.filter_by(user_id=current_user.id).first()
        if app and (application_id is None or app.id == application_id):
            return app
    if current_user.role == "mentor" and not write:
        query = Share.query.join(Application).filter(
            Share.mentor_email == current_user.email,
            Share.active.is_(True),
        )
        if application_id is not None:
            query = query.filter(Share.application_id == application_id)
        share = query.first()
        if share:
            return Application.query.get_or_404(share.application_id)
    abort(403)
