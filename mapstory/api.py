from mapstory.models import DiaryEntry
from tastypie.resources import ModelResource

class DiaryEntryResource(ModelResource):

    def build_filters(self, filters={}):
        orm_filters = super(DiaryEntryResource, self).build_filters(filters)

        return orm_filters

    def serialize(self, request, data, format, options={}):
        return super(DiaryEntryResource, self).serialize(request, data, format, options)

    class Meta:
        queryset = DiaryEntry.objects.all()
        resource_name = 'journals'
        allowed_methods = ['get']