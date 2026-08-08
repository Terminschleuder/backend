from rest_framework import permissions


class IsOwnerOrGroupOrReadOnly(permissions.BasePermission):
    """Object-level permissions for events.

    - Read (safe methods) is public — the events catalog.
    - Create (POST) requires authentication; service accounts must also hold
      the ``events.add_event`` permission.
    - Update/Delete is allowed for:
        * the creator (``created_by``),
        * a member of the event's ``owner_group``,
        * any user holding the matching model permission
          (``events.change_event`` / ``events.delete_event``) — typically a
          service account via its group.
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method == "POST":
            # Service accounts need explicit add permission; human users may
            # create their own events freely.
            if getattr(user, "is_service_account", False):
                return user.has_perm("events.add_event")
            return True
        # PUT/PATCH/DELETE: object-level check decides.
        return True

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        user = request.user
        if not (user and user.is_authenticated):
            return False

        if request.method == "DELETE":
            if user.has_perm("events.delete_event"):
                return True
        else:  # PUT / PATCH
            if user.has_perm("events.change_event"):
                return True

        if obj.created_by_id == user.id:
            return True
        if obj.owner_group_id and user.groups.filter(id=obj.owner_group_id).exists():
            return True
        return False


class IsIngestionService(permissions.BasePermission):
    """Gate the extractor-facing ingestion API (``/api/ingestion/``).

    The caller must be an authenticated user holding the ingestion permissions
    required for the operation. Each ingestion view declares the perms it needs
    via a ``ingestion_perms`` mapping (keys are HTTP methods **or** view
    actions, values are lists of ``app.codename`` perm strings). In practice the
    extractor is a service account placed in an ``ingestion`` group carrying:

        events.view_eventsource            (read due sources)
        events.add_ingestionrun            (report runs)
        events.change_ingestionrun         (finish runs)
        events.view_ingestionrun           (read runs)
        events.add_eventobservation        (submit observations)
        events.view_eventobservation       (read observations)

    Anonymous access is forbidden (the route is not part of the public catalog).

    .. note:: ``user.has_perm()`` caches results on the instance. If a test
        grants a group permission mid-flow, refetch the user from the DB before
        re-checking (see AGENTS.md permission-cache gotcha).
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        perms_map = getattr(view, "ingestion_perms", {})
        action = getattr(view, "action", None)
        # An action-specific entry (e.g. "success"/"failure"/"bulk") wins over
        # the bare HTTP method.
        required = perms_map.get(action) or perms_map.get(request.method)
        if not required:
            return True
        return all(user.has_perm(p) for p in required)