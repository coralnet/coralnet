from django.urls import path
from . import views


urlpatterns = [
    # Pages
    path('view/', views.image_detail, name="image_detail"),
    path('edit/', views.image_detail_edit, name="image_detail_edit"),

    # Actions
    path('delete/', views.image_delete, name="image_delete"),
    path('delete_annotations/',
         views.image_delete_annotations, name="image_delete_annotations"),
    path('regenerate_points/',
         views.image_regenerate_points, name="image_regenerate_points"),
    path('reset_point_generation_method/',
         views.image_reset_point_generation_method,
         name="image_reset_point_generation_method"),
    path('reset_annotation_area/',
         views.image_reset_annotation_area, name="image_reset_annotation_area"),
]
