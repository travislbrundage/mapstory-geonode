# -*- coding: utf-8 -*-
#########################################################################
#
# Copyright (C) 2019 Planet Federal
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################

"""
Utilities for enabling ESRI:ArcGIS:MapServer and
ESRI:ArcGIS:ImageServer remote services in geonode.
"""

import os
import logging
import traceback

from uuid import uuid4

from django.conf import settings
from django.template.defaultfilters import slugify, safe
from django.utils.translation import ugettext as _

from osgeo import osr

from arcrest.ags import MapService as ArcMapService
from arcrest.ags import ImageService as ArcImageService

from geonode.base.models import Link
from geonode.layers.models import Layer
from geonode.layers.utils import create_thumbnail
from geonode.services import utils
from geonode.services import enumerations
from geonode.services import models
from geonode.services.serviceprocessors import base

from collections import namedtuple

try:
    if 'ssl_pki' not in settings.INSTALLED_APPS:
        raise ImportError
    from ssl_pki.utils import (
        has_pki_prefix,
        pki_to_proxy_route,
        pki_route_reverse,
        proxy_route
    )
except ImportError:
    has_pki_prefix = None
    pki_to_proxy_route = None
    pki_route_reverse = None
    proxy_route = None

logger = logging.getLogger(__name__)

MapLayer = namedtuple("MapLayer",
                      "id, \
                      title, \
                      abstract, \
                      type, \
                      geometryType, \
                      copyrightText, \
                      extent, \
                      fields, \
                      minScale, \
                      maxScale")


def epsg_string(bbox):
    logging.debug('bbox: %s', bbox)
    if 'spatialReference' in bbox:
        sr = bbox['spatialReference']
        if 'latestWkid' in sr:
            return "EPSG:%s" % sr['latestWkid']
        if 'wkt' in sr:
            wkt = sr['wkt']
            logging.debug('wkt: %s', wkt)
            ref = osr.SpatialReference()
            ref.ImportFromWkt(wkt)
            ref.MorphFromESRI()
            matches = ref.FindMatches()
            if len(matches) > 0:
                match = matches[0][0]
                code = match.GetAuthorityCode('PROJCS')
                if code:
                    return "EPSG:%s" % code
                code = match.GetAuthorityCode('GEOGCS')
                if code:
                    return "EPSG:%s" % code
                code = match.GetAuthorityCode(None)
                if code:
                    return "EPSG:%s" % code

    return None

class MapstoryArcMapServiceHandler(base.ServiceHandlerBase):
    """Remote service handler for ESRI:ArcGIS:MapServer services

    This function is mostly a copy and paste of GeoNode's ArcMapServiceHandler.
    The reason for this is because PKI requires a different version of arcgis,
    which restructures the import statements.
    """

    service_type = enumerations.REST_MAP

    def __init__(self, url, **kwargs):
        headers = kwargs.pop('headers', None)
        logger.debug('passed headers = {0}'.format(headers))

        self.proxy_base = None
        self.url = url
        # ONLY Authorization is messing it up due to the bearer token, why?
        # Workaround - create a duplicate
        dupe = ArcMapService(self.url)
        # dupe_layers = dupe.layers
        # Now this will work with headers
        self.parsed_service = ArcMapService(self.url, add_headers=headers)
        extent, srs = utils.get_esri_extent(self.parsed_service)
        try:
            _sname = utils.get_esri_service_name(self.url)
            _title_safe = safe(os.path.basename(os.path.normpath(_sname)))
            _title = _title_safe.replace('_', ' ').strip()
        except BaseException:
            traceback.print_exc()
            _title = self.parsed_service.mapName
        if len(_title) == 0:
            _title = utils.get_esri_service_name(self.url)
        # wkt_geometry = utils.bbox2wktpolygon([
        #     extent['xmin'],
        #     extent['ymin'],
        #     extent['xmax'],
        #     extent['ymax']
        # ])
        self.url = self.parsed_service.url
        self.pki_proxy_url = None
        self.pki_url = None
        if callable(has_pki_prefix) and has_pki_prefix(self.url):
            self.pki_url = self.url
            self.pki_proxy_url = pki_to_proxy_route(self.url)
            self.url = pki_route_reverse(self.url)
        self.indexing_method = enumerations.INDEXED
        self.name = slugify(self.url)[:255]
        self.title = _title

    def create_cascaded_store(self):
        return None

    def create_geonode_service(self, owner, parent=None):
        """Create a new geonode.service.models.Service instance

        :arg owner: The user who will own the service instance
        :type owner: geonode.people.models.Profile

        """

        instance = models.Service(
            uuid=str(uuid4()),
            base_url=self.url,
            proxy_base=self.proxy_base,
            type=self.service_type,
            method=self.indexing_method,
            owner=owner,
            parent=parent,
            version=self.parsed_service.currentVersion,
            name=self.name,
            title=self.title,
            abstract=self.parsed_service.serviceDescription
                     or _("Not provided"),
            online_resource=self.parsed_service.url,
        )
        return instance

    def get_keywords(self):
        return self.parsed_service.documentInfo['Keywords'].split(',')

    def get_resource(self, resource_id):
        ll = None
        try:
            ll = self.parsed_service.layers[int(resource_id)]
        except BaseException:
            traceback.print_exc()

        return self._layer_meta(ll) if ll else None

    def get_resources(self):
        """Return an iterable with the service's resources.

        For WMS we take into account that some layers are just logical groups
        of metadata and do not return those.

        """
        try:
            return self._parse_layers(self.parsed_service.layers)
        except BaseException:
            return None

    def _parse_layers(self, layers):
        map_layers = []
        for l in layers:
            map_layers.append(self._layer_meta(l))
            map_layers.extend(self._parse_layers(l.subLayers))
        return map_layers

    def _layer_meta(self, layer):
        _ll = {}
        _ll['id'] = layer.id
        _ll['title'] = layer.name
        _ll['abstract'] = layer.name
        _ll['type'] = layer.type
        _ll['geometryType'] = layer.geometryType
        _ll['copyrightText'] = layer.copyrightText
        _ll['extent'] = layer.extent
        _ll['fields'] = layer.fields
        _ll['minScale'] = layer.minScale
        _ll['maxScale'] = layer.maxScale
        return MapLayer(**_ll)

    def harvest_resource(self, resource_id, geonode_service):
        """Harvest a single resource from the service

        This method will try to create new ``geonode.layers.models.Layer``
        instance (and its related objects too).

        :arg resource_id: The resource's identifier
        :type resource_id: str
        :arg geonode_service: The already saved service instance
        :type geonode_service: geonode.services.models.Service

        """
        # No layer meta? No - it never gets here?????
        # so get_resource might be the problem then
        # How is this different at all?
        layer_meta = self.get_resource(resource_id)
        logger.debug("layer_meta: {}".format(layer_meta))
        if layer_meta:
            resource_fields = self._get_indexed_layer_fields(layer_meta)
            keywords = resource_fields.pop("keywords")
            existance_test_qs = Layer.objects.filter(
                name=resource_fields["name"],
                store=resource_fields["store"],
                workspace=resource_fields["workspace"]
            )
            if existance_test_qs.exists():
                raise RuntimeError(
                    "Resource {!r} has already been harvested".format(
                        resource_id))
            resource_fields["keywords"] = keywords
            resource_fields["is_approved"] = True
            resource_fields["is_published"] = True
            if settings.RESOURCE_PUBLISHING or settings.ADMIN_MODERATE_UPLOADS:
                resource_fields["is_approved"] = False
                resource_fields["is_published"] = False
            geonode_layer = self._create_layer(
                geonode_service, **resource_fields)
            # self._enrich_layer_metadata(geonode_layer)
            self._create_layer_service_link(geonode_layer)
            # self._create_layer_legend_link(geonode_layer)
        else:
            raise RuntimeError(
                "Resource layers {0} had no layer_meta {1}".format(self.parsed_service.layers, layer_meta))

    def has_resources(self):
        try:
            return True if len(self.parsed_service.layers) > 0 else False
        except BaseException:
            traceback.print_exc()
            return False

    def _offers_geonode_projection(self, srs):
        geonode_projection = getattr(settings, "DEFAULT_MAP_CRS", "EPSG:3857")
        return geonode_projection in "EPSG:{}".format(srs)

    def _get_indexed_layer_fields(self, layer_meta):
        # no spatialreference
        # Need to use the epsg_string function Exhcange made
        # spatialReference is probably not a thing anymore
        # srs = "EPSG:%s" % layer_meta.extent.spatialReference.wkid
        bbox = utils.decimal_encode([layer_meta.extent['xmin'],
                                     layer_meta.extent['ymin'],
                                     layer_meta.extent['xmax'],
                                     layer_meta.extent['ymax']])
        return {
            "name": layer_meta.title,
            "store": self.name,
            "storeType": "remoteStore",
            "workspace": "remoteWorkspace",
            "typename": "{}-{}".format(layer_meta.id, layer_meta.title),
            "alternate": "{}-{}".format(layer_meta.id, layer_meta.title),
            "title": layer_meta.title,
            "abstract": layer_meta.abstract,
            "bbox_x0": bbox[0],
            "bbox_x1": bbox[2],
            "bbox_y0": bbox[1],
            "bbox_y1": bbox[3],
            "srid": epsg_string(layer_meta.extent),
            "keywords": ['ESRI', 'ArcGIS REST MapServer', layer_meta.title],
        }

    def _create_layer(self, geonode_service, **resource_fields):
        # bear in mind that in ``geonode.layers.models`` there is a
        # ``pre_save_layer`` function handler that is connected to the
        # ``pre_save`` signal for the Layer model. This handler does a check
        # for common fields (such as abstract and title) and adds
        # sensible default values
        keywords = resource_fields.pop("keywords") or []
        geonode_layer = Layer(
            owner=geonode_service.owner,
            remote_service=geonode_service,
            uuid=str(uuid4()),
            **resource_fields
        )
        geonode_layer.full_clean()
        geonode_layer.save()
        geonode_layer.keywords.add(*keywords)
        geonode_layer.set_default_permissions()
        return geonode_layer

    def _create_layer_thumbnail(self, geonode_layer):
        """Create a thumbnail with a WMS request."""
        params = {
            "service": "WMS",
            "version": self.parsed_service.version,
            "request": "GetMap",
            "layers": geonode_layer.alternate.encode('utf-8'),
            "bbox": geonode_layer.bbox_string,
            "srs": "EPSG:4326",
            "width": "200",
            "height": "150",
            "format": "image/png",
        }
        kvp = "&".join("{}={}".format(*item) for item in params.items())
        thumbnail_remote_url = "{}?{}".format(
            geonode_layer.remote_service.service_url, kvp)
        logger.debug("thumbnail_remote_url: {}".format(thumbnail_remote_url))
        thumbnail_create_url = "{}?{}".format(
            self.pki_url or geonode_layer.ows_url, kvp)
        logger.debug("thumbnail_create_url: {}".format(thumbnail_create_url))
        create_thumbnail(
            instance=geonode_layer,
            thumbnail_remote_url=thumbnail_remote_url,
            thumbnail_create_url=thumbnail_create_url,
            check_bbox=False,
            overwrite=True
        )

    def _create_layer_service_link(self, geonode_layer):
        Link.objects.get_or_create(
            resource=geonode_layer.resourcebase_ptr,
            url=geonode_layer.ows_url,
            name="ESRI {}: {} Service".format(
                geonode_layer.remote_service.type,
                geonode_layer.store
            ),
            defaults={
                "extension": "html",
                "name": "ESRI {}: {} Service".format(
                    geonode_layer.remote_service.type,
                    geonode_layer.store
                ),
                "url": geonode_layer.ows_url,
                "mime": "text/html",
                "link_type": "ESRI:{}".format(
                    geonode_layer.remote_service.type),
            }
        )


class MapstoryArcImageServiceHandler(MapstoryArcMapServiceHandler):
    """Remote service handler for ESRI:ArcGIS:ImageService services"""

    def __init__(self, url, **kwargs):
        headers = kwargs.pop('headers', None)
        logger.debug('passed headers = {0}'.format(headers))

        self.proxy_base = None
        self.url = url
        self.parsed_service = ArcImageService(self.url, add_headers=headers)
        extent, srs = utils.get_esri_extent(self.parsed_service)
        try:
            _sname = utils.get_esri_service_name(self.url)
            _title_safe = safe(os.path.basename(os.path.normpath(_sname)))
            _title = _title_safe.replace('_', ' ').strip()
        except BaseException:
            traceback.print_exc()
            _title = self.parsed_service.mapName
        if len(_title) == 0:
            _title = utils.get_esri_service_name(self.url)
        # wkt_geometry = utils.bbox2wktpolygon([
        #     extent['xmin'],
        #     extent['ymin'],
        #     extent['xmax'],
        #     extent['ymax']
        # ])
        self.url = self.parsed_service.url
        self.pki_proxy_url = None
        self.pki_url = None
        if callable(has_pki_prefix) and has_pki_prefix(self.url):
            self.pki_url = self.url
            self.pki_proxy_url = pki_to_proxy_route(self.url)
            self.url = pki_route_reverse(self.url)
        self.indexing_method = enumerations.INDEXED
        self.name = slugify(self.url)[:255]
        self.title = _title
