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

from django.conf import settings
from django.template.defaultfilters import slugify, safe

from arcrest.ags import MapService as ArcMapService
from arcrest.ags import ImageService as ArcImageService

# TODO: So we might need to just entirely rewrite this since it
# doesn't use arcrest.ags. Just copy and paste / rewrite in this file
# so we can remove this import
from geonode.services.serviceprocessors.arcgis \
    import ArcMapServiceHandler, ArcImageServiceHandler
from geonode.layers.utils import create_thumbnail
from geonode.services import utils
from geonode.services.enumerations import INDEXED

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


class MapstoryArcMapServiceHandler(ArcMapServiceHandler):
    """Remote service handler for ESRI:ArcGIS:MapServer services"""

    def __init__(self, url, **kwargs):
        headers = kwargs.pop('headers', None)
        logger.debug('passed headers = {0}'.format(headers))

        self.proxy_base = None
        self.url = url
        self.parsed_service = ArcMapService(self.url, headers=headers)
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
        self.indexing_method = INDEXED
        self.name = slugify(self.url)[:255]
        self.title = _title

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


class MapstoryArcImageServiceHandler(ArcImageServiceHandler):
    """Remote service handler for ESRI:ArcGIS:ImageService services"""

    def __init__(self, url, **kwargs):
        headers = kwargs.pop('headers', None)
        logger.debug('passed headers = {0}'.format(headers))

        self.proxy_base = None
        self.url = url
        self.parsed_service = ArcImageService(self.url, headers=headers)
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
        self.indexing_method = INDEXED
        self.name = slugify(self.url)[:255]
        self.title = _title
