from django.db import DatabaseError, connection
from django.views.decorators.cache import never_cache
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@never_cache
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return Response({"status": "unavailable"}, status=503)
    return Response({"status": "ok"})
