from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden


def role_required(predicate, message='You do not have permission to access this page.'):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped(request, *args, **kwargs):
            if predicate(request.user):
                return view_func(request, *args, **kwargs)
            return HttpResponseForbidden(message)

        return wrapped

    return decorator


platform_admin_required = role_required(
    lambda user: getattr(user, 'can_access_platform_admin', False),
    'Administrator access only.',
)

merchant_required = role_required(
    lambda user: getattr(user, 'can_access_merchant_centre', False),
    'Merchant access only.',
)

finance_admin_required = role_required(
    lambda user: getattr(user, 'can_access_finance_admin', False),
    'Financial administrator access only.',
)

delivery_partner_required = role_required(
    lambda user: getattr(user, 'can_access_delivery_centre', False),
    'Delivery partner access only.',
)

moderator_required = role_required(
    lambda user: getattr(user, 'can_access_moderation', False),
    'Moderator or support access only.',
)
