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