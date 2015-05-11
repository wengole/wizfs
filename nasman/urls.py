from django.conf import settings
from django.conf.urls import patterns, include, url
from django.conf.urls.static import static
from django.contrib import admin

urlpatterns = patterns(
    '',
    url(r'^admin/', include(admin.site.urls)),
    url(r'^', include('nasman.snapshots.urls', namespace='nasman')),
    url(r'^notifications/', include('nasman.notifications.urls',
                                    namespace='notifications'))
) + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

