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

"""Utilities for enabling OGC WMS remote services in geonode."""

import logging
from urllib import quote
from urlparse import urljoin
from decimal import Decimal

from django.conf import settings
from django.template.defaultfilters import slugify
from django.core.urlresolvers import reverse

from geonode.services.serviceprocessors.wms \
    import WmsServiceHandler, WebMapService, GeoNodeServiceHandler
from geonode.services.enumerations import CASCADED
from geonode.services.enumerations import INDEXED
from geonode.layers.utils import create_thumbnail
from geonode.base.models import Link

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


def decimal_encode(bbox):
    _bbox = []
    for o in bbox:
        try:
            _bbox.append("{0:.15f}".format(round(float(o), 2)))
        except ValueError:
            logger.debug("Found non-numeric value in bbox: {0}".format(o))
    if len(_bbox) < 4:
        logger.error("Did not find enough elements in bbox: {0}".format(bbox))
        # TODO: Is this the right thing to do here?
        while len(_bbox) < 4:
            _bbox.append("0")
    return _bbox


class MapstoryWmsServiceHandler(WmsServiceHandler):
    """Remote service handler for OGC WMS services"""

    def __init__(self, url, **kwargs):
        headers = kwargs.pop('headers', None)
        logger.debug('passed headers = {0}'.format(headers))

        self.proxy_base = urljoin(
            settings.SITEURL, reverse('proxy'))
        # (self.url, self.parsed_service) = WebMapService(
        #     url, proxy_base=self.proxy_base)
        (self.url, self.parsed_service) = WebMapService(
            url, proxy_base=None, headers=headers)
        self.indexing_method = (
            INDEXED if self._offers_geonode_projection() else CASCADED)
        self.url = self.parsed_service.url
        self.pki_proxy_url = None
        self.pki_url = None
        if callable(has_pki_prefix) and has_pki_prefix(self.url):
            self.pki_url = self.url
            self.pki_proxy_url = pki_to_proxy_route(self.url)
            self.url = pki_route_reverse(self.url)
        # TODO: Check if the name already esists
        self.name = slugify(self.url)[:255]

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

    def _create_layer_legend_link(self, geonode_layer):
        """Get the layer's legend and save it locally

        Regardless of the service being INDEXED or CASCADED we're always
        creating the legend by making a request directly to the original
        service.

        """

        params = {
            "service": "WMS",
            "version": self.parsed_service.version,
            "request": "GetLegendGraphic",
            "format": "image/png",
            "width": 20,
            "height": 20,
            "layer": geonode_layer.name,
            "legend_options": (
                "fontAntiAliasing:true;fontSize:12;forceLabels:on")
        }
        if self.pki_url is not None:
            # ArcREST WMS request parser doesn't cope with : or ;
            params["legend_options"] = quote(params["legend_options"])
        kvp = "&".join("{}={}".format(*item) for item in params.items())
        legend_url = "{}?{}".format(
            geonode_layer.remote_service.service_url, kvp)
        if self.pki_url is not None:
            legend_url = proxy_route(legend_url)
        logger.debug("legend_url: {}".format(legend_url))
        Link.objects.get_or_create(
            resource=geonode_layer.resourcebase_ptr,
            url=legend_url,
            name='Legend',
            defaults={
                "extension": 'png',
                "name": 'Legend',
                "url": legend_url,
                "mime": 'image/png',
                "link_type": 'image',
            }
        )

    def _get_cascaded_layer_fields(self, geoserver_resource):
        name = geoserver_resource.name
        workspace = geoserver_resource.workspace.name
        store = geoserver_resource.store

        bbox = decimal_encode(geoserver_resource.native_bbox)
        return {
            "name": name,
            "workspace": workspace,
            "store": store.name,
            "typename": "{}:{}".format(workspace, name),
            "alternate": "{}:{}".format(workspace, name),
            "storeType": "remoteStore",  # store.resource_type,
            "title": geoserver_resource.title,
            "abstract": geoserver_resource.abstract,
            "bbox_x0": bbox[0],
            "bbox_x1": bbox[1],
            "bbox_y0": bbox[2],
            "bbox_y1": bbox[3],
        }

    def _get_indexed_layer_fields(self, layer_meta):
        bbox = decimal_encode(layer_meta.boundingBoxWGS84)
        bbox_y1 = bbox[3]

        return {
            "name": layer_meta.name,
            "store": self.name,
            "storeType": "remoteStore",
            "workspace": "remoteWorkspace",
            "typename": layer_meta.name,
            "alternate": layer_meta.name,
            "title": layer_meta.title,
            "abstract": layer_meta.abstract,
            "bbox_x0": bbox[0],
            "bbox_x1": bbox[2],
            "bbox_y0": bbox[1],
            "bbox_y1": bbox[3],
            "keywords": [keyword[:100] for keyword in layer_meta.keywords],
        }


class MapstoryServiceHandler(GeoNodeServiceHandler):
    """Remote service handler for OGC WMS services"""

    def __init__(self, url, **kwargs):
        headers = kwargs.pop('headers', None)
        logger.debug('passed headers = {0}'.format(headers))

        self.proxy_base = urljoin(
            settings.SITEURL, reverse('proxy'))
        url = self._probe_geonode_wms(url)
        (self.url, self.parsed_service) = WebMapService(
            url, proxy_base=self.proxy_base, headers=headers)
        self.indexing_method = (
            INDEXED if self._offers_geonode_projection() else CASCADED)
        self.url = self.parsed_service.url
        self.pki_proxy_url = None
        self.pki_url = None
        if callable(has_pki_prefix) and has_pki_prefix(self.url):
            self.pki_url = self.url
            self.pki_proxy_url = pki_to_proxy_route(self.url)
            self.url = pki_route_reverse(self.url)
        self.name = slugify(self.url)[:255]
