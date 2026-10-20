from django.urls import path
from .api import platform_youtube_key

from .api import (organization_performance_key, organization_provider_accounts, organization_provider_credential,
                   platform_ai_routing, project_ai_routing,
                   platform_google_analytics_app, platform_google_business_app, platform_google_oauth_app, platform_performance_key, platform_provider_accounts,
                   platform_provider_credential, platform_providers, platform_models)


urlpatterns = [
    path("platform/integrations/youtube-key/", platform_youtube_key, name="platform-youtube-key"),
    path("platform/providers/", platform_providers, name="platform-providers"),
    path("platform/models/", platform_models, name="platform-models"),
    path("platform/ai-routing/", platform_ai_routing, name="platform-ai-routing"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/ai-routing/",
         project_ai_routing, name="project-ai-routing"),
    path("platform/integrations/google-oauth-app/", platform_google_oauth_app, name="platform-google-oauth-app"),
    path("platform/integrations/google-analytics-app/", platform_google_analytics_app,
         name="platform-google-analytics-app"),
    path("platform/integrations/google-business-app/", platform_google_business_app, name="platform-google-business-app"),
    path("platform/integrations/performance-key/", platform_performance_key, name="platform-performance-key"),
    path("platform/providers/<int:provider_id>/accounts/", platform_provider_accounts, name="platform-provider-accounts"),
    path("platform/providers/<int:provider_id>/accounts/<int:account_id>/credential/",
         platform_provider_credential, name="platform-provider-credential"),
    path("organizations/<int:organization_id>/provider-accounts/",
         organization_provider_accounts, name="organization-provider-accounts"),
    path("organizations/<int:organization_id>/performance-key/",
         organization_performance_key, name="organization-performance-key"),
    path("organizations/<int:organization_id>/provider-accounts/<int:account_id>/credential/",
         organization_provider_credential, name="organization-provider-credential"),
]
